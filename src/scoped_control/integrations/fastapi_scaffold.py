"""Scaffolder that drops a production-ready Slack-to-scoped-control FastAPI
bridge into an existing app.

`scoped-control install fastapi --out <dir>` writes two files and prints the
exact deps + Dockerfile additions the embedder needs.

The bridge itself is deliberately one file you can copy and modify.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_BRIDGE_TEMPLATE = '''"""Slack @mention → scoped-agent-control bridge.

Drop this module into your FastAPI app and mount it with:

    from .scoped_slack_bridge import router as scoped_slack_router
    app.include_router(scoped_slack_router)

Env vars the router reads:

    SLACK_SIGNING_SECRET  — from your Slack app "Basic Information" page.
    SLACK_BOT_TOKEN       — xoxb- token used to post replies in-thread.
    GITHUB_TOKEN          — repo scope, used to clone + open PRs.
    GITHUB_REPO           — "owner/repo" format. Default: auto-detect from
                             the `git remote get-url origin` of the cwd.
    ANTHROPIC_API_KEY     — required when SCOPED_CONTROL_EXECUTOR=anthropic
                             or claude_code. Skip for the fake executor.
    SCOPED_CONTROL_ROLE   — role name to pin every incoming request to.
                             Default: "clinical-recruiter".
    SCOPED_CONTROL_EXECUTOR — "anthropic" | "claude_code" | "fake".
                             Default: "anthropic".
    SCOPED_CONTROL_TRIAGER  — "auto" | "heuristic" | "claude_code" | "codex".
                             Default: "auto".

Assumes your repo has a `.scoped-control/config.yaml` at the repo root with
the pinned role defined. Run `scoped-control setup` once to generate it.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse


logger = logging.getLogger(__name__)
router = APIRouter(tags=["scoped-control"])

_GITHUB_REPO = os.environ.get("GITHUB_REPO") or _detect_github_repo()
_ROLE = os.environ.get("SCOPED_CONTROL_ROLE", "clinical-recruiter")
_BRANCH_PREFIX = os.environ.get("SCOPED_CONTROL_BRANCH_PREFIX", "scoped/")
_BASE_BRANCH = os.environ.get("SCOPED_CONTROL_BASE_BRANCH", "main")
_GIT_BOT_NAME = os.environ.get("SCOPED_CONTROL_GIT_NAME", "scoped-control-bot")
_GIT_BOT_EMAIL = os.environ.get("SCOPED_CONTROL_GIT_EMAIL", "scoped-control-bot@localhost")

_COOLDOWN_SECONDS = int(os.environ.get("SCOPED_CONTROL_COOLDOWN_SECONDS", "60"))
_recent_dispatches: dict[str, float] = {}


@router.post("/api/integrations/slack/events", summary="Scoped-control Slack bridge")
async def handle_slack_event(
    request: Request, background_tasks: BackgroundTasks
) -> JSONResponse:
    body = await request.body()
    signing_secret = os.environ.get("SLACK_SIGNING_SECRET", "")
    if signing_secret:
        _verify_slack_signature(
            body=body,
            timestamp=request.headers.get("X-Slack-Request-Timestamp", ""),
            signature=request.headers.get("X-Slack-Signature", ""),
            secret=signing_secret,
        )

    payload = await request.json()
    if payload.get("type") == "url_verification":
        return JSONResponse({"challenge": payload.get("challenge", "")})
    if payload.get("type") == "event_callback":
        event = payload.get("event", {})
        if event.get("type") == "app_mention":
            background_tasks.add_task(_dispatch_app_mention, event)
    return JSONResponse({"ok": True})


async def _dispatch_app_mention(event: dict) -> None:
    channel = event.get("channel", "")
    thread_ts = event.get("thread_ts") or event.get("ts", "")
    raw_text = event.get("text", "")
    message = re.sub(r"<@[A-Z0-9]+>\\s*", "", raw_text).strip()
    if not message:
        return

    cooldown_key = f"{channel}:{thread_ts}"
    now = time.monotonic()
    last = _recent_dispatches.get(cooldown_key)
    if last is not None and now - last < _COOLDOWN_SECONDS:
        return
    _recent_dispatches[cooldown_key] = now

    await _post_slack_reply(
        channel,
        thread_ts,
        "Got it! Looking into this now — I'll reply here shortly.",
    )

    github_token = os.environ.get("GITHUB_TOKEN", "")
    if not github_token:
        await _post_slack_reply(
            channel, thread_ts,
            "I'm not able to open a PR right now (missing GITHUB_TOKEN).",
        )
        return

    try:
        reply = await asyncio.to_thread(
            _run_scoped_request,
            message=message,
            github_token=github_token,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("scoped-control run failed")
        await _post_slack_reply(
            channel, thread_ts,
            f":warning: Something went wrong: `{exc}`.",
        )
        return

    await _post_slack_reply(channel, thread_ts, reply)


def _run_scoped_request(*, message: str, github_token: str) -> str:
    from scoped_control.api import handle_request
    from scoped_control.integrations.github_pr import open_pr_for_changes

    clone_url = f"https://x-access-token:{github_token}@github.com/{_GITHUB_REPO}.git"
    with tempfile.TemporaryDirectory(prefix="scoped-slack-") as tmp:
        tmp_path = Path(tmp)
        subprocess.run(  # noqa: S603
            ["git", "clone", "--depth", "50", clone_url, str(tmp_path)],
            check=True, capture_output=True, text=True,
        )

        result = handle_request(
            tmp_path,
            message,
            role=_ROLE,
            executor=os.environ.get("SCOPED_CONTROL_EXECUTOR", "anthropic"),
            triager=os.environ.get("SCOPED_CONTROL_TRIAGER", "auto"),
        )

        if not result.ok:
            return (
                f":no_entry: {result.reason}\\n"
                f"> mode: `{result.mode}`, role: `{result.role or 'none'}`, "
                f"targets: {', '.join(result.targets) or '<none>'}"
            )

        if result.mode == "query":
            answer = (result.output or result.message).strip()
            targets = f"\\n_Consulted: {', '.join(result.targets)}_" if result.targets else ""
            return f":mag: {answer}{targets}"

        if not result.changed_files:
            return (
                f":information_source: I looked but didn't change anything. "
                f"Executor said: {result.output or result.message}"
            )

        diff_summary = _git_diff_stat(tmp_path)
        pr = open_pr_for_changes(
            tmp_path,
            title=f"scoped: {message[:72]}",
            body=_pr_body(message, result, diff_summary),
            branch_prefix=_BRANCH_PREFIX,
            base_branch=_BASE_BRANCH,
            git_user_name=_GIT_BOT_NAME,
            git_user_email=_GIT_BOT_EMAIL,
            slug_hint=message,
        )
        if not pr.ok:
            return f":warning: Edit ran, but opening a PR failed: `{pr.error}`"

        summary = (result.output or result.message or "").strip()
        files_line = ", ".join(result.changed_files)
        parts = [
            f":white_check_mark: Opened a PR for you: {pr.url}",
            f"\\n*What I did:* {summary}" if summary and "fake edit" not in summary.lower() else "",
            f"\\n*Files changed ({len(result.changed_files)}):* `{files_line}`",
            f"\\n*Diff:* {diff_summary}" if diff_summary else "",
            "\\nReview and merge when it looks right. Reply here for follow-ups.",
        ]
        return "\\n".join(part for part in parts if part)


def _pr_body(message: str, result, diff_summary: str) -> str:  # noqa: ANN001
    diff_line = f"\\n**Diff:** {diff_summary}" if diff_summary else ""
    exec_line = (
        f"\\n**Executor said:** {result.output.strip()}"
        if result.output and result.output.strip() and "fake edit" not in result.output.lower()
        else ""
    )
    return (
        "Scoped via `scoped-agent-control` from a Slack mention.\\n\\n"
        f"**Role:** `{result.role}`\\n"
        f"**Triager:** `{result.triager}`\\n"
        f"**Targets:** {', '.join(result.targets) or '<none>'}\\n"
        f"**Files changed:** {', '.join(result.changed_files)}"
        f"{diff_line}{exec_line}\\n\\n"
        f"**Original request (from Slack):**\\n> {message}\\n"
    )


def _git_diff_stat(repo_path: Path) -> str:
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "-C", str(repo_path), "diff", "--numstat"],
            capture_output=True, text=True, check=False,
        )
    except Exception:  # noqa: BLE001
        return ""
    if out.returncode != 0 or not out.stdout.strip():
        return ""
    adds = dels = files = 0
    for line in out.stdout.splitlines():
        parts = line.split("\\t")
        if len(parts) >= 2:
            try:
                adds += int(parts[0])
                dels += int(parts[1])
                files += 1
            except ValueError:
                continue
    return f"+{adds} −{dels} lines across {files} file(s)" if files else ""


async def _post_slack_reply(channel: str, thread_ts: str, text: str) -> None:
    bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not bot_token:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {bot_token}"},
                json={"channel": channel, "thread_ts": thread_ts, "text": text},
            )
            data = resp.json()
            if not data.get("ok"):
                logger.error("Slack reply failed: %s", data.get("error"))
    except Exception:  # noqa: BLE001
        logger.exception("Failed to post Slack reply")


def _verify_slack_signature(body: bytes, timestamp: str, signature: str, secret: str) -> None:
    if not timestamp or not signature:
        raise HTTPException(status_code=401, detail="Missing Slack signature headers")
    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid timestamp") from exc
    if abs(time.time() - ts) > 300:
        raise HTTPException(status_code=401, detail="Request too old")
    sig_basestring = f"v0:{timestamp}:{body.decode()}"
    computed = "v0=" + hmac.new(
        secret.encode(), sig_basestring.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(computed, signature):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")


def _detect_github_repo() -> str:
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True,
        )
    except Exception:  # noqa: BLE001
        return ""
    url = out.stdout.strip()
    match = re.search(r"github\\.com[:/]([^/]+/[^/]+?)(?:\\.git)?$", url)
    return match.group(1) if match else ""
'''


_INSTRUCTIONS_TEMPLATE = """\
scoped-control Slack bridge written to {out_path}

## Wire it into your FastAPI app

    from .{module_name} import router as scoped_slack_router

    app.include_router(scoped_slack_router)

## Python deps to add

    scoped-agent-control[anthropic] @ git+https://github.com/Shriram-Vasudevan/scoped-agent-control.git@main
    httpx>=0.27
    PyYAML>=6.0

## Container/Dockerfile additions (only if you want to open PRs)

    # git (for clone/commit/push) and gh (for `gh pr create`)
    RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates gnupg && \\
        curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \\
            | gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg && \\
        echo "deb [signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \\
            > /etc/apt/sources.list.d/github-cli.list && \\
        apt-get update && apt-get install -y --no-install-recommends gh && \\
        apt-get clean && rm -rf /var/lib/apt/lists/*

## Env vars

Required:
  SLACK_SIGNING_SECRET         — from your Slack app admin page
  SLACK_BOT_TOKEN              — xoxb- token
  GITHUB_TOKEN                 — repo scope on your target repo
  GITHUB_REPO                  — "owner/repo" (or auto-detected from origin)
  ANTHROPIC_API_KEY            — for the default anthropic executor

Optional:
  SCOPED_CONTROL_ROLE          — default: clinical-recruiter
  SCOPED_CONTROL_EXECUTOR      — anthropic | claude_code | fake  (default: anthropic)
  SCOPED_CONTROL_TRIAGER       — auto | heuristic | claude_code  (default: auto)
  SCOPED_CONTROL_BRANCH_PREFIX — default: scoped/
  SCOPED_CONTROL_BASE_BRANCH   — default: main
  SCOPED_CONTROL_COOLDOWN_SECONDS — per-thread dispatch cooldown. Default: 60.

## One-time repo setup

Before the first Slack mention, run `scoped-control setup` at your repo
root. Answer the wizard with the role name you set in SCOPED_CONTROL_ROLE
and the files it's allowed to edit. This writes `.scoped-control/config.yaml`.

## Slack app config

Point the Slack app's Event Subscriptions Request URL at:

    https://<your-host>/api/integrations/slack/events

Subscribe to the `app_mention` bot event, install to workspace, you're done.
"""


@dataclass(slots=True, frozen=True)
class FastAPIScaffoldResult:
    bridge_path: Path
    instructions: str


def install_fastapi(out_dir: Path, *, module_name: str = "scoped_slack_bridge") -> FastAPIScaffoldResult:
    """Write the Slack-to-scoped-control FastAPI bridge to `out_dir`."""

    out_dir.mkdir(parents=True, exist_ok=True)
    bridge_path = out_dir / f"{module_name}.py"
    bridge_path.write_text(_BRIDGE_TEMPLATE, encoding="utf-8")
    instructions = _INSTRUCTIONS_TEMPLATE.format(
        out_path=bridge_path,
        module_name=module_name,
    )
    return FastAPIScaffoldResult(bridge_path=bridge_path, instructions=instructions)
