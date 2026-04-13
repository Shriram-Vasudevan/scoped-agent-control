"""Unit tests for the triage classifier."""

from __future__ import annotations

from dataclasses import replace

from scoped_control.config.loader import bootstrap_repo, load_config
from scoped_control.config.mutator import add_role, write_config
from scoped_control.index.builder import rebuild_index
from scoped_control.models import RoleConfig
from scoped_control.triage import triage_request


def _seed_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    bootstrap_repo(repo)
    docs = repo / "docs"
    docs.mkdir()
    (docs / "faq.md").write_text(
        "# surface: docs.faq\n"
        "# roles: writer\n"
        "# modes: query, edit\n"
        "# invariants: file_scope\n"
        "\n"
        "FAQ contents.\n",
        encoding="utf-8",
    )
    src = repo / "src"
    src.mkdir()
    (src / "core.py").write_text(
        "# surface: src.core\n"
        "# roles: maintainer\n"
        "# modes: query, edit\n"
        "# invariants: file_scope\n"
        "\n"
        "def run():\n    return 1\n",
        encoding="utf-8",
    )

    paths, config = load_config(repo)
    config = add_role(
        config,
        RoleConfig(
            name="writer",
            description="Docs writer",
            query_paths=("docs/**",),
            edit_paths=("docs/**",),
        ),
    )
    write_config(config, paths.config_path)
    rebuild_index(repo)
    return repo


def test_triage_heuristic_classifies_edit_and_picks_narrow_role(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    paths, config = load_config(repo)
    from scoped_control.index.store import load_index

    index = load_index(paths.index_path)

    decision = triage_request(
        repo,
        config,
        index,
        "Please update the FAQ copy",
        triager="heuristic",
    )
    assert decision.ok is True
    assert decision.mode == "edit"
    assert decision.role_name == "writer"
    assert "docs/faq.md" in decision.target_files


def test_triage_heuristic_classifies_query_when_read_verb(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    paths, config = load_config(repo)
    from scoped_control.index.store import load_index

    index = load_index(paths.index_path)

    decision = triage_request(
        repo,
        config,
        index,
        "Explain the FAQ",
        triager="heuristic",
    )
    assert decision.mode == "query"
    assert decision.role_name == "writer"


def test_triage_blocks_when_no_role_covers_target(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    paths, config = load_config(repo)
    from scoped_control.index.store import load_index

    index = load_index(paths.index_path)

    decision = triage_request(
        repo,
        config,
        index,
        "Update src/core.py to return 7",
        requested_role="writer",
        triager="heuristic",
    )
    assert decision.ok is False
    assert decision.mode == "blocked"
    assert "does not have" in decision.reason or "not configured" in decision.reason


def test_triage_blocks_edit_with_no_targets(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    paths, config = load_config(repo)
    from scoped_control.index.store import load_index

    index = load_index(paths.index_path)

    decision = triage_request(
        repo,
        config,
        index,
        "Please rewrite everything",
        triager="heuristic",
    )
    # "everything" has no file tokens so this should be blocked.
    assert decision.mode == "blocked"
    assert decision.ok is False
