from __future__ import annotations

from dataclasses import replace
import json

from scoped_control.config.loader import bootstrap_repo, load_config
from scoped_control.integrations.installer import install_github, install_slack
from scoped_control.integrations.slack import send_slack_notification
from scoped_control.models import SlackIntegrationConfig


def test_install_slack_updates_config_and_workflow_env(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    bootstrap_repo(repo_root)
    install_github(repo_root)

    config_path = install_slack(repo_root, webhook_env="TEAM_SLACK_WEBHOOK")

    assert config_path.exists()
    _, config = load_config(repo_root)
    assert config.integrations.slack.enabled is True
    assert config.integrations.slack.webhook_url_env == "TEAM_SLACK_WEBHOOK"

    workflow_text = (repo_root / ".github" / "workflows" / "scoped-control.yml").read_text(encoding="utf-8")
    assert "TEAM_SLACK_WEBHOOK: ${{ secrets.TEAM_SLACK_WEBHOOK }}" in workflow_text


def test_send_slack_notification_posts_webhook_payload(monkeypatch, tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    bootstrap_repo(repo_root)
    _, config = load_config(repo_root)
    config = replace(
        config,
        integrations=replace(
            config.integrations,
            slack=SlackIntegrationConfig(enabled=True, webhook_url_env="SLACK_WEBHOOK_URL"),
        ),
    )

    captured: dict[str, object] = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b"ok"

    def fake_urlopen(req, timeout):  # noqa: ANN001
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return _Response()

    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T000/B000/XXXX")
    monkeypatch.setattr("scoped_control.integrations.slack.request.urlopen", fake_urlopen)

    status = send_slack_notification(
        config,
        event_key="edit_success",
        repo_root=repo_root,
        command="edit writer",
        ok=True,
        message="Edit completed.",
        lines=("Changed files: docs/faq.md", "Validator py-compile: ok"),
    )

    assert status == "Slack notification sent."
    assert captured["url"] == "https://hooks.slack.com/services/T000/B000/XXXX"
    assert captured["timeout"] == 10
    assert "edit writer" in captured["payload"]["text"]
    assert "Changed files: docs/faq.md" in captured["payload"]["text"]


def test_send_slack_notification_reports_missing_env(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    bootstrap_repo(repo_root)
    _, config = load_config(repo_root)
    config = replace(
        config,
        integrations=replace(
            config.integrations,
            slack=SlackIntegrationConfig(enabled=True, webhook_url_env="TEAM_SLACK_WEBHOOK"),
        ),
    )

    status = send_slack_notification(
        config,
        event_key="edit_blocked",
        repo_root=repo_root,
        command="edit writer",
        ok=False,
        message="Blocked.",
        lines=("Blocked: validator failed",),
    )

    assert status == "Slack enabled but env var `TEAM_SLACK_WEBHOOK` is not set."
