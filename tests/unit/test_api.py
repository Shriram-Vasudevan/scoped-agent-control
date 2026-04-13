"""Unit tests for the embeddable handle_request API."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from scoped_control.api import ScopedResult, handle_request
from scoped_control.config.loader import bootstrap_repo, load_config
from scoped_control.config.mutator import add_role, update_role, write_config
from scoped_control.index.builder import rebuild_index
from scoped_control.models import LimitsConfig, RoleConfig


def _seed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    bootstrap_repo(repo)

    # One editable module and one docs file.
    (repo / "editable.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    docs = repo / "docs"
    docs.mkdir()
    (docs / "faq.md").write_text("# FAQ\n\nThe answer is 42.\n", encoding="utf-8")

    paths, config = load_config(repo)
    config = update_role(
        config,
        RoleConfig(
            name="maintainer",
            description="Maintainer",
            query_paths=("**/*",),
            edit_paths=("editable.py",),
        ),
    )
    config = add_role(
        config,
        RoleConfig(
            name="docs-writer",
            description="Docs only",
            query_paths=("docs/**",),
            edit_paths=("docs/**",),
        ),
    )
    config = replace(config, limits=LimitsConfig(max_changed_files=5, max_diff_lines=400))
    write_config(config, paths.config_path)
    rebuild_index(repo)
    return repo


def test_handle_request_routes_query_to_fake_executor(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)
    result = handle_request(
        repo,
        "explain the FAQ",
        executor="fake",
        triager="heuristic",
    )
    assert isinstance(result, ScopedResult)
    assert result.ok is True
    assert result.mode == "query"
    # Either role could cover docs/faq.md; triage should pick the narrowest.
    assert result.role in {"maintainer", "docs-writer"}
    assert "docs/faq.md" in result.targets
    assert "Query completed" in result.message


def test_handle_request_blocks_when_no_role_can_edit(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)
    result = handle_request(
        repo,
        "update the FAQ doc",
        role="maintainer",  # maintainer only edits editable.py, not docs/**
        executor="fake",
        triager="heuristic",
    )
    assert result.ok is False
    assert result.mode == "blocked"
    assert result.role == "maintainer"
    assert "does not have" in result.reason or "not" in result.reason.lower()


def test_handle_request_pinned_role_runs_when_scope_matches(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)
    result = handle_request(
        repo,
        "update the FAQ",
        role="docs-writer",
        executor="fake",
        triager="heuristic",
    )
    assert result.ok is True
    assert result.mode == "edit"
    assert result.role == "docs-writer"


def test_handle_request_empty_input_is_blocked(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)
    result = handle_request(repo, "", triager="heuristic", executor="fake")
    assert result.ok is False
    assert result.mode == "blocked"


def test_handle_request_tracks_changed_files_after_successful_edit(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)
    # Initialize git so we can detect changes.
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=str(repo),
        check=True,
    )

    result = handle_request(
        repo,
        "change return 1 to return 10 in editable.py",
        role="maintainer",
        executor="fake",
        triager="heuristic",
    )
    assert result.ok is True
    assert result.mode == "edit"
    assert "editable.py" in result.changed_files
