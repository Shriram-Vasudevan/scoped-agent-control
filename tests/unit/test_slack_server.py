"""Unit tests for the incoming Slack slash-command server."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path

from scoped_control.integrations.slack_server import (
    SlackTriageReply,
    handle_slack_request,
    parse_slash_command_body,
    verify_slack_signature,
)


SECRET = "shhh"


def _sign(body: bytes, ts: str) -> str:
    digest = hmac.new(SECRET.encode(), f"v0:{ts}:".encode() + body, hashlib.sha256).hexdigest()
    return f"v0={digest}"


def test_verify_slack_signature_accepts_valid() -> None:
    body = b"token=x&text=hello"
    ts = str(int(time.time()))
    sig = _sign(body, ts)
    assert verify_slack_signature(
        signing_secret=SECRET,
        timestamp=ts,
        body=body,
        signature=sig,
    )


def test_verify_slack_signature_rejects_tampered() -> None:
    body = b"token=x&text=hello"
    ts = str(int(time.time()))
    sig = _sign(body, ts)
    tampered = body + b"&evil=1"
    assert not verify_slack_signature(
        signing_secret=SECRET,
        timestamp=ts,
        body=tampered,
        signature=sig,
    )


def test_verify_slack_signature_rejects_old_timestamp() -> None:
    body = b"x"
    ts = str(int(time.time()) - 60 * 10)
    sig = _sign(body, ts)
    assert not verify_slack_signature(
        signing_secret=SECRET,
        timestamp=ts,
        body=body,
        signature=sig,
    )


def test_parse_slash_command_body() -> None:
    body = b"token=T&user_name=alice&text=update+the+faq"
    form = parse_slash_command_body(body)
    assert form["user_name"] == "alice"
    assert form["text"] == "update the faq"


def test_handle_slack_request_dispatches_and_formats_reply(tmp_path: Path) -> None:
    body = b"text=update+the+faq&user_name=alice"
    ts = str(int(time.time()))
    sig = _sign(body, ts)

    def fake_dispatch(repo_path, text, executor):
        return SlackTriageReply(text=f"ran {text} on {repo_path.name}", ok=True)

    status, headers, payload = handle_slack_request(
        tmp_path,
        body,
        {"x-slack-request-timestamp": ts, "x-slack-signature": sig},
        signing_secret=SECRET,
        executor=None,
        dispatch=fake_dispatch,
    )
    assert status == 200
    assert headers["Content-Type"] == "application/json"
    decoded = json.loads(payload)
    assert decoded["response_type"] == "in_channel"
    assert "update the faq" in decoded["text"]
    assert "@alice" in decoded["text"]


def test_handle_slack_request_rejects_bad_signature(tmp_path: Path) -> None:
    body = b"text=hello"
    ts = str(int(time.time()))
    status, _, payload = handle_slack_request(
        tmp_path,
        body,
        {"x-slack-request-timestamp": ts, "x-slack-signature": "v0=bogus"},
        signing_secret=SECRET,
        executor=None,
        dispatch=lambda *a, **k: SlackTriageReply(text="unreachable", ok=True),
    )
    assert status == 401
    assert payload == b"invalid signature"


def test_handle_slack_request_usage_on_empty_text(tmp_path: Path) -> None:
    body = b"text="
    ts = str(int(time.time()))
    sig = _sign(body, ts)
    status, _, payload = handle_slack_request(
        tmp_path,
        body,
        {"x-slack-request-timestamp": ts, "x-slack-signature": sig},
        signing_secret=SECRET,
        executor=None,
        dispatch=lambda *a, **k: SlackTriageReply(text="should-not-run", ok=True),
    )
    assert status == 200
    decoded = json.loads(payload)
    assert decoded["response_type"] == "ephemeral"
    assert "Usage" in decoded["text"]
