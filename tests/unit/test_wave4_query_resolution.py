from __future__ import annotations

import shutil
from pathlib import Path

from scoped_control.config.loader import bootstrap_repo, load_config
from scoped_control.config.mutator import add_role, write_config
from scoped_control.index.builder import rebuild_index
from scoped_control.index.store import load_index
from scoped_control.models import RoleConfig
from scoped_control.resolver.brief import compile_query_brief, render_query_brief
from scoped_control.resolver.matcher import resolve_query_surfaces


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "wave2"


def test_query_resolution_filters_by_role_and_includes_dependencies(tmp_path) -> None:
    repo_root = _seed_query_repo(tmp_path)
    paths, config = load_config(repo_root)
    index = load_index(paths.index_path)
    reviewer = config.get_role("reviewer")

    resolution = resolve_query_surfaces(reviewer, index, "Explain python secondary handler", top_k=1)

    assert resolution.matches[0].surface.id == "python.secondary"
    assert any("surface id keywords" in reason for reason in resolution.matches[0].reasons)
    assert resolution.dependency_surfaces[0].id == "python.primary"
    assert resolution.allowed_files == ("python_repeated_annotations.py",)

    brief = compile_query_brief(paths.root, config, reviewer, "Explain python secondary handler", resolution.matches, resolution.dependency_surfaces)
    prompt = render_query_brief(brief)

    assert brief.target_surfaces[0].id == "python.secondary"
    assert brief.dependency_files == ("python_repeated_annotations.py",)
    assert len(brief.file_contexts) == 2
    assert "### TARGET python_repeated_annotations.py:17-18" in prompt
    assert "### DEPENDENCY python_repeated_annotations.py:7-8" in prompt
    assert "def secondary_handler():" in prompt
    assert "def primary_handler():" in prompt


def test_query_resolution_respects_role_visibility(tmp_path) -> None:
    repo_root = _seed_query_repo(tmp_path)
    paths, config = load_config(repo_root)
    index = load_index(paths.index_path)
    maintainer = config.get_role("maintainer")

    resolution = resolve_query_surfaces(maintainer, index, "Explain plaintext secondary", top_k=3)

    assert resolution.matches
    assert all(not match.surface.roles or maintainer.name in match.surface.roles for match in resolution.matches)
    assert all(match.surface.id != "plaintext.secondary" for match in resolution.matches)


def _seed_query_repo(tmp_path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    bootstrap_repo(repo_root)
    for source in (
        FIXTURES / "python_repeated_annotations.py",
        FIXTURES / "typescript_repeated_annotations.ts",
        FIXTURES / "plain_text_repeated_annotations.txt",
        FIXTURES / "malformed_and_duplicate.py",
    ):
        shutil.copy2(source, repo_root / source.name)

    paths, config = load_config(repo_root)
    updated = add_role(
        config,
        RoleConfig(
            name="reviewer",
            description="Read-only review role",
            query_paths=("**/*",),
            edit_paths=(),
        ),
    )
    write_config(updated, paths.config_path)
    rebuild_index(repo_root)
    return repo_root
