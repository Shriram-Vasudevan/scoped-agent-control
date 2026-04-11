"""Slack incoming webhook notifications."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib import request

from scoped_control.models import AppConfig


def send_slack_notification(
    config: AppConfig,
    *,
    event_key: str,
    repo_root: Path,
    command: str,
    ok: bool,
    message: str,
    lines: tuple[str, ...],
) -> str | None:
    """Send a Slack notification if enabled and configured."""

    slack = config.integrations.slack
    if not slack.enabled or event_key not in slack.notify_on:
        return None

    webhook_url = os.environ.get(slack.webhook_url_env, "").strip()
    if not webhook_url:
        return f"Slack enabled but env var `{slack.webhook_url_env}` is not set."

    status = "SUCCESS" if ok else "BLOCKED"
    preview_lines = "\n".join(lines[:8]).strip()
    payload = {
        "text": (
            f"[scoped-control] {status} in {repo_root.name}\n"
            f"Command: {command}\n"
            f"Summary: {message}\n"
            f"{preview_lines}"
        ).strip()
    }
    req = request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with request.urlopen(req, timeout=10) as response:  # noqa: S310
        response.read()
    return "Slack notification sent."
