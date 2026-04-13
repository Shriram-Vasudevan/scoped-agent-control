"""Guided setup for an incoming Slack slash-command bot.

`scoped-control install slack-bot` runs the full flow end to end:

  1. Starts a public tunnel to a local port automatically.
  2. Prints a ready-to-paste Slack app manifest with the URL already filled in.
  3. Asks for the signing secret, no env var juggling.
  4. Tells the user the two clicks they still have to make in Slack.
  5. Starts the local server and smoke-tests it through the tunnel.

Then it prints a team announcement template and keeps the server + tunnel
running until Ctrl+C. Target time: ~3 minutes including browser clicks.
"""

from __future__ import annotations

from dataclasses import dataclass
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Callable, TextIO
import getpass
import hashlib
import hmac
import json
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.request

from scoped_control.integrations.slack_server import _SlackHandler
from scoped_control.integrations.tunnel import (
    MissingTunnelToolError,
    TunnelHandle,
    start_tunnel,
    stop_tunnel,
)


@dataclass(slots=True, frozen=True)
class SmokeTestResult:
    ok: bool
    message: str


# ---------------------------------------------------------------------------
# Templates


def render_manifest(public_url: str, repo_name: str) -> str:
    """Return the YAML manifest the user pastes into Slack."""

    return textwrap.dedent(
        f"""\
        display_information:
          name: scoped-control
          description: Scoped AI queries and edits on the {repo_name} repo.
        features:
          bot_user:
            display_name: scoped-control
            always_online: true
          slash_commands:
            - command: /scoped
              url: {public_url}/
              description: Ask a scoped-control question or request an edit
              usage_hint: update the careers intro
              should_escape: false
        oauth_config:
          scopes:
            bot:
              - commands
              - chat:write
        settings:
          org_deploy_enabled: false
          socket_mode_enabled: false
          token_rotation_enabled: false
        """
    )


def render_team_announcement(repo_name: str) -> str:
    """Return the text to share with the team."""

    return textwrap.dedent(
        f"""\
        Hey team — /scoped is live for the {repo_name} repo. Use it to ask
        questions about the code or request small changes.

        Examples:
          /scoped what does the careers intro say?
          /scoped update the careers intro to mention remote work

        It figures out if your request is a read or an edit, checks whether
        your role has access, and either answers you directly or runs the
        change through our normal review process. Blocked requests come
        back with a clear reason.
        """
    )


# ---------------------------------------------------------------------------
# Smoke test


def run_smoke_test(
    public_url: str,
    signing_secret: str,
    *,
    timeout_seconds: float = 10.0,
) -> SmokeTestResult:
    """Send a signed no-op request through the tunnel and check the reply."""

    body = b"text=&user_name=smoke-test"
    timestamp = str(int(time.time()))
    basestring = b"v0:" + timestamp.encode() + b":" + body
    digest = hmac.new(signing_secret.encode(), basestring, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": f"v0={digest}",
    }
    request = urllib.request.Request(  # noqa: S310
        public_url.rstrip("/") + "/",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return SmokeTestResult(
                ok=False,
                message=(
                    "Server rejected the signature. Double-check you pasted the Signing "
                    "Secret exactly as shown in the Slack app's Basic Information page."
                ),
            )
        return SmokeTestResult(ok=False, message=f"HTTP {exc.code}: {exc.reason}")
    except Exception as exc:  # noqa: BLE001
        return SmokeTestResult(ok=False, message=f"could not reach the tunnel: {exc}")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return SmokeTestResult(ok=False, message=f"unexpected response: {raw[:120]}")
    if "text" in payload and "Usage" in payload.get("text", ""):
        return SmokeTestResult(ok=True, message="tunnel, server, and signature all verified")
    return SmokeTestResult(ok=True, message="server replied (unrecognized body)")


# ---------------------------------------------------------------------------
# Guided setup orchestrator


def guided_setup(
    repo_path: Path,
    *,
    port: int = 8787,
    executor: str | None = None,
    in_stream: TextIO = sys.stdin,
    out_stream: TextIO = sys.stdout,
    signing_secret_reader: Callable[[TextIO], str] | None = None,
    tunnel_starter: Callable[[int], TunnelHandle] | None = None,
    block_until_interrupted: bool = True,
) -> int:
    """Run the full guided flow. Returns a shell exit code.

    `signing_secret_reader`, `tunnel_starter`, and `block_until_interrupted`
    are overridable for testing.
    """

    def say(line: str = "") -> None:
        print(line, file=out_stream, flush=True)

    repo_name = repo_path.resolve().name

    say("scoped-control Slack bot — guided setup")
    say("=" * 40)
    say()
    say("About 3 minutes from here. I'll start a public tunnel, print a")
    say("ready-to-paste Slack app manifest, wait for you to paste it and")
    say("copy the signing secret back, then smoke-test the whole chain.")
    say()

    # -- Step 1: tunnel ------------------------------------------------------
    say("Step 1 of 5 — starting a public tunnel")
    starter = tunnel_starter or start_tunnel
    try:
        tunnel = starter(port)
    except MissingTunnelToolError as exc:
        say()
        say(str(exc))
        return 1
    except Exception as exc:  # noqa: BLE001
        say(f"  ✗ Failed to start tunnel: {exc}")
        return 1
    say(f"  ✓ Public URL: {tunnel.public_url}  (via {tunnel.tool})")
    say()

    server: ThreadingHTTPServer | None = None
    server_thread: threading.Thread | None = None

    try:
        # -- Step 2: manifest ------------------------------------------------
        say("Step 2 of 5 — create the Slack app")
        say()
        say("  1. Open this URL in your browser:")
        say("       https://api.slack.com/apps?new_app=1")
        say("  2. Click \"From a manifest\", pick your workspace, click Next.")
        say("  3. Replace the example YAML with the manifest below, then Create:")
        say()
        say(_indent(render_manifest(tunnel.public_url, repo_name)))

        # -- Step 3: signing secret -----------------------------------------
        say("Step 3 of 5 — copy the Signing Secret")
        say()
        say("  On your new app's \"Basic Information\" page, scroll to")
        say("  \"App Credentials\", click \"Show\" next to Signing Secret,")
        say("  then paste it here (the value will be hidden as you type).")
        say()
        reader = signing_secret_reader or _default_secret_reader
        signing_secret = reader(in_stream).strip()
        if not signing_secret:
            say("  No secret entered. Aborting.")
            return 1
        say("  ✓ Signing secret captured.")
        say()

        # -- Step 4: install + URL -----------------------------------------
        say("Step 4 of 5 — install the app and press Enter here")
        say()
        say("  1. In the Slack app settings, click \"Install App\" → \"Install\n"
            "     to Workspace\" → Allow.")
        say(f"  2. Confirm the slash command URL is {tunnel.public_url}/")
        say("     (Slash Commands → /scoped → edit, if it isn't).")
        say("  3. Come back here and press Enter.")
        say()
        in_stream.readline()

        # -- Step 5: server + smoke test -----------------------------------
        say("Step 5 of 5 — starting the local server and testing")
        handler = type(
            "_BoundSlackHandler",
            (_SlackHandler,),
            {"repo_path": repo_path, "signing_secret": signing_secret, "executor": executor},
        )
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        # Give the server a breath before we test.
        time.sleep(0.2)
        result = run_smoke_test(tunnel.public_url, signing_secret)
        if result.ok:
            say(f"  ✓ {result.message}")
        else:
            say(f"  ✗ {result.message}")
            say("    The server will stay running; try /scoped in Slack and")
            say("    come back here if something misbehaves.")
        say()

        # -- Done ------------------------------------------------------------
        say("All set.")
        say()
        say("─── Share this with your team ───")
        say()
        say(_indent(render_team_announcement(repo_name)))
        say("─────────────────────────────────")
        say()
        say(f"Listening on {tunnel.public_url}/   (local port {port})")
        say("Press Ctrl+C to stop. The public URL becomes invalid when this exits.")
        say()

        if not block_until_interrupted:
            return 0

        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            say("\nShutting down...")
        return 0
    finally:
        if server is not None:
            server.shutdown()
        if server_thread is not None:
            server_thread.join(timeout=5)
        stop_tunnel(tunnel)


# ---------------------------------------------------------------------------
# Helpers


def _indent(text: str, prefix: str = "      ") -> str:
    return "\n".join(f"{prefix}{line}" if line else "" for line in text.splitlines())


def _default_secret_reader(in_stream: TextIO) -> str:
    # If the caller is piping stdin (tests, automation), don't use getpass.
    if not in_stream.isatty():
        return in_stream.readline().strip()
    return getpass.getpass("  Signing Secret: ")
