"""Installer helpers for GitHub and Slack."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from scoped_control.config.loader import load_config
from scoped_control.config.mutator import write_config
from scoped_control.integrations.github import render_github_triage_workflow, render_github_workflow
from scoped_control.models import GitHubIntegrationConfig, SlackIntegrationConfig


def install_github(repo_path: Path, *, workflow_path: str | None = None, force: bool = False) -> tuple[Path, Path, Path]:
    """Install deterministic GitHub workflow scaffolding and enable config wiring.

    Writes two workflow files: the explicit remote-edit dispatch and a
    remote-triage dispatch that auto-classifies read vs edit.
    """

    paths, config = load_config(repo_path)
    target_workflow = workflow_path or config.integrations.github.workflow_path
    workflow_file = paths.root / target_workflow
    triage_workflow_file = workflow_file.with_name(_derived_triage_filename(workflow_file.name))
    for path in (workflow_file, triage_workflow_file):
        if path.exists() and not force:
            raise ValueError(f"{path.relative_to(paths.root)} already exists. Re-run with --force to overwrite it.")

    workflow_file.parent.mkdir(parents=True, exist_ok=True)
    workflow_file.write_text(
        render_github_workflow(slack_webhook_env=config.integrations.slack.webhook_url_env),
        encoding="utf-8",
    )
    triage_workflow_file.write_text(
        render_github_triage_workflow(slack_webhook_env=config.integrations.slack.webhook_url_env),
        encoding="utf-8",
    )

    updated = replace(
        config,
        integrations=replace(
            config.integrations,
            github=GitHubIntegrationConfig(enabled=True, workflow_path=target_workflow),
        ),
    )
    write_config(updated, paths.config_path)
    return paths.config_path, workflow_file, triage_workflow_file


def _derived_triage_filename(primary_name: str) -> str:
    stem = primary_name.rsplit(".", 1)[0] if "." in primary_name else primary_name
    suffix = primary_name[len(stem) :] or ".yml"
    return f"{stem}-triage{suffix}"


def install_slack(repo_path: Path, *, webhook_env: str = "SLACK_WEBHOOK_URL") -> Path:
    """Enable Slack notifications in config and refresh GitHub workflow if present."""

    paths, config = load_config(repo_path)
    updated = replace(
        config,
        integrations=replace(
            config.integrations,
            slack=SlackIntegrationConfig(
                enabled=True,
                webhook_url_env=webhook_env,
                notify_on=("edit_success", "edit_blocked", "remote_edit_success", "remote_edit_blocked"),
            ),
        ),
    )
    write_config(updated, paths.config_path)

    workflow_path = paths.root / updated.integrations.github.workflow_path
    if workflow_path.exists():
        workflow_path.write_text(render_github_workflow(slack_webhook_env=webhook_env), encoding="utf-8")
    triage_workflow_path = workflow_path.with_name(_derived_triage_filename(workflow_path.name))
    if triage_workflow_path.exists():
        triage_workflow_path.write_text(
            render_github_triage_workflow(slack_webhook_env=webhook_env),
            encoding="utf-8",
        )

    return paths.config_path


def placeholder_install_message(channel: str) -> str:
    """Explain the placeholder status for unsupported channels."""

    return f"{channel} installation is not implemented yet."
