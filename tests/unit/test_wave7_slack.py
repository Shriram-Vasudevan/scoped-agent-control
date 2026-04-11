from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from scoped_control.config.schema import build_default_config
from scoped_control.integrations.slack import send_slack_notification
from scoped_control.models import SlackIntegrationConfig


def test_send_slack_notification_posts_payload_when_configured(monkeypatch) -> None:
    captured = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"ok"

    def fake_urlopen(request_obj, timeout=10):
        captured["url"] = request_obj.full_url
        captured["payload"] = json.loads(request_obj.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setenv("TEAM_SLACK_WEBHOOK", "https://example.com/webhook")
    monkeypatch.setattr("scoped_control.integrations.slack.request.urlopen", fake_urlopen)

    base_config = build_default_config()
    config = replace(
        base_config,
        integrations=replace(
            base_config.integrations,
            slack=SlackIntegrationConfig(
                enabled=True,
                webhook_url_env="TEAM_SLACK_WEBHOOK",
                notify_on=("edit_success",),
            ),
        ),
    )

    result = send_slack_notification(
        config,
        event_key="edit_success",
        repo_root=Path("/tmp/repo"),
        command="edit writer refactor helper",
        ok=True,
        message="Edit completed.",
        lines=("Executor: fake", "Changed files: app.py"),
    )

    assert result == "Slack notification sent."
    assert captured["url"] == "https://example.com/webhook"
    assert captured["timeout"] == 10
    assert "SUCCESS in repo" in captured["payload"]["text"]
    assert "Edit completed." in captured["payload"]["text"]
    assert "Changed files: app.py" in captured["payload"]["text"]


def test_send_slack_notification_reports_missing_env_without_network_call(monkeypatch) -> None:
    def fail_urlopen(*args, **kwargs):
        raise AssertionError("urlopen should not be called when the webhook env is missing")

    monkeypatch.delenv("TEAM_SLACK_WEBHOOK", raising=False)
    monkeypatch.setattr("scoped_control.integrations.slack.request.urlopen", fail_urlopen)

    base_config = build_default_config()
    config = replace(
        base_config,
        integrations=replace(
            base_config.integrations,
            slack=SlackIntegrationConfig(
                enabled=True,
                webhook_url_env="TEAM_SLACK_WEBHOOK",
                notify_on=("edit_success",),
            ),
        ),
    )

    result = send_slack_notification(
        config,
        event_key="edit_success",
        repo_root=Path("/tmp/repo"),
        command="edit writer refactor helper",
        ok=True,
        message="Edit completed.",
        lines=("Executor: fake",),
    )

    assert result == "Slack enabled but env var `TEAM_SLACK_WEBHOOK` is not set."
