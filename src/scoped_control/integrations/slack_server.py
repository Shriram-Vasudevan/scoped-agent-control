"""Incoming Slack slash-command server that triages and dispatches requests."""

from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs
import argparse
import hashlib
import hmac
import json
import os
import threading
import time


@dataclass(slots=True, frozen=True)
class SlackTriageReply:
    text: str
    ok: bool


def verify_slack_signature(
    *,
    signing_secret: str,
    timestamp: str,
    body: bytes,
    signature: str,
    now: float | None = None,
) -> bool:
    """Validate a Slack request signature per Slack's signing spec."""

    if not signing_secret or not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    current = int(now if now is not None else time.time())
    if abs(current - ts) > 60 * 5:
        return False
    basestring = b"v0:" + timestamp.encode("utf-8") + b":" + body
    digest = hmac.new(signing_secret.encode("utf-8"), basestring, hashlib.sha256).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, signature)


def parse_slash_command_body(body: bytes) -> dict[str, str]:
    """Parse a Slack slash-command POST body (application/x-www-form-urlencoded)."""

    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: values[0] for key, values in parsed.items() if values}


def handle_slack_request(
    repo_path: Path,
    body: bytes,
    headers: dict[str, str],
    *,
    signing_secret: str,
    executor: str | None,
    dispatch: Callable[[Path, str, str | None], SlackTriageReply] | None = None,
    now: float | None = None,
) -> tuple[int, dict[str, str], bytes]:
    """Verify the request, run triage + dispatch, and return an HTTP response."""

    timestamp = headers.get("x-slack-request-timestamp", "")
    signature = headers.get("x-slack-signature", "")
    if signing_secret and not verify_slack_signature(
        signing_secret=signing_secret,
        timestamp=timestamp,
        body=body,
        signature=signature,
        now=now,
    ):
        return 401, {"Content-Type": "text/plain"}, b"invalid signature"

    form = parse_slash_command_body(body)
    text = form.get("text", "").strip()
    user = form.get("user_name") or form.get("user_id") or "slack"
    if not text:
        payload = {"response_type": "ephemeral", "text": "Usage: /scoped <request>"}
        return 200, {"Content-Type": "application/json"}, json.dumps(payload).encode("utf-8")

    runner = dispatch or _default_dispatch
    reply = runner(repo_path, text, executor)
    response_type = "in_channel" if reply.ok else "ephemeral"
    prefix = f"@{user} " if user else ""
    payload = {"response_type": response_type, "text": f"{prefix}{reply.text}"}
    return 200, {"Content-Type": "application/json"}, json.dumps(payload).encode("utf-8")


def _default_dispatch(repo_path: Path, text: str, executor: str | None) -> SlackTriageReply:
    """Run the real triage + query/edit pipeline and format a Slack reply."""

    # Local imports so the module can be imported without pulling the full
    # executor stack (useful when only verifying signatures in tests).
    from scoped_control.config.loader import load_config
    from scoped_control.index.store import load_index
    from scoped_control.triage import triage_request
    from scoped_control.tui.commands import execute_args

    paths, config = load_config(repo_path)
    index = load_index(paths.index_path)
    decision = triage_request(paths.root, config, index, text)

    header = (
        f":mag: *scoped-control triage*\n"
        f"> request: {text}\n"
        f"> mode: `{decision.mode}`\n"
        f"> role: `{decision.role_name or 'none'}`\n"
        f"> targets: {', '.join(decision.target_files) or '<none>'}\n"
        f"> triager: `{decision.triager}`\n"
    )

    if not decision.ok:
        return SlackTriageReply(text=f"{header}\n:no_entry: blocked: {decision.reason}", ok=False)

    namespace = argparse.Namespace(
        command=decision.mode,
        role_name=decision.role_name,
        request_tokens=[decision.request],
        executor=executor,
        top_k=3 if decision.mode == "query" else 1,
    )
    result = execute_args(paths.root, namespace, raw_command=f"slack {decision.mode} {decision.role_name}")
    status = ":white_check_mark: ok" if result.ok else ":no_entry: blocked"
    detail_lines = list(result.lines)[:8]
    detail = "\n".join(f"> {line}" for line in detail_lines) if detail_lines else ""
    summary = result.message
    body = f"{header}\n{status}: {summary}\n{detail}".strip()
    return SlackTriageReply(text=body, ok=result.ok)


class _SlackHandler(BaseHTTPRequestHandler):
    repo_path: Path = Path.cwd()
    signing_secret: str = ""
    executor: str | None = None

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        # Quiet the default stderr spam; server users can see stdout prints.
        return

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length) if length else b""
        headers = {key.lower(): value for key, value in self.headers.items()}
        status, resp_headers, payload = handle_slack_request(
            self.repo_path,
            body,
            headers,
            signing_secret=self.signing_secret,
            executor=self.executor,
        )
        self.send_response(status)
        for key, value in resp_headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        payload = b'{"status":"ok","service":"scoped-control slack server"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def serve(
    repo_path: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    signing_secret: str | None = None,
    executor: str | None = None,
) -> None:
    """Run the Slack slash-command server until interrupted."""

    secret = signing_secret if signing_secret is not None else os.environ.get("SLACK_SIGNING_SECRET", "")
    handler = type(
        "_BoundSlackHandler",
        (_SlackHandler,),
        {"repo_path": repo_path, "signing_secret": secret, "executor": executor},
    )
    server = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="scoped-control-slack")
    thread.start()
    print(f"scoped-control Slack server listening on http://{host}:{port}")
    print("Point a Slack slash command at <public-url>/slack (use a tunnel like ngrok).")
    if not secret:
        print("Warning: SLACK_SIGNING_SECRET is not set; requests will NOT be verified.")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("Shutting down.")
        server.shutdown()
        thread.join(timeout=5)
