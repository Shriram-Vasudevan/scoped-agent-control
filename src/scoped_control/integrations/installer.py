"""Installer helpers for GitHub and placeholder channels."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from scoped_control.config.loader import load_config
from scoped_control.config.mutator import write_config
from scoped_control.integrations.github import render_github_workflow
from scoped_control.models import GitHubIntegrationConfig


def install_github(repo_path: Path, *, workflow_path: str | None = None, force: bool = False) -> tuple[Path, Path]:
    """Install deterministic GitHub workflow scaffolding and enable config wiring."""

    paths, config = load_config(repo_path)
    target_workflow = workflow_path or config.integrations.github.workflow_path
    workflow_file = paths.root / target_workflow
    if workflow_file.exists() and not force:
        raise ValueError(f"{target_workflow} already exists. Re-run with --force to overwrite it.")

    workflow_file.parent.mkdir(parents=True, exist_ok=True)
    workflow_file.write_text(render_github_workflow(), encoding="utf-8")

    updated = replace(
        config,
        integrations=replace(
            config.integrations,
            github=GitHubIntegrationConfig(enabled=True, workflow_path=target_workflow),
        ),
    )
    write_config(updated, paths.config_path)
    return paths.config_path, workflow_file


def placeholder_install_message(channel: str) -> str:
    """Explain the v1 placeholder status for non-GitHub channels."""

    return (
        f"{channel} installation is a v1 placeholder. Install GitHub first; "
        f"{channel.lower()} delivery depends on the GitHub remote-edit workflow scaffold."
    )
