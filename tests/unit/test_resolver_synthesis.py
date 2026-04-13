"""Tests for on-demand synthesis of whole-file surfaces in the resolver.

Core contract:
- If a role's globs cover a file but no explicit surface exists for it,
  the resolver returns a synthesized whole-file surface on demand.
- Explicit surfaces always win over synthesized ones when both apply.
"""

from __future__ import annotations

from scoped_control.models import IndexRecord, RoleConfig, SurfaceRecord
from scoped_control.resolver.matcher import (
    resolve_edit_surfaces,
    resolve_query_surfaces,
)


def _write(path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def test_resolve_query_synthesizes_when_no_index(tmp_path) -> None:
    _write(tmp_path / "src" / "core.py", "def a():\n    return 1\n")
    _write(tmp_path / "docs" / "faq.md", "# FAQ\n")
    role = RoleConfig(name="maintainer", query_paths=("**/*",), edit_paths=())

    resolution = resolve_query_surfaces(
        role,
        IndexRecord(root=str(tmp_path), surfaces=(), warnings=()),
        "explain the FAQ",
        top_k=3,
        repo_root=tmp_path,
    )

    assert resolution.matches, "should synthesize at least one surface"
    paths = {match.surface.file for match in resolution.matches}
    assert "docs/faq.md" in paths
    # Synthesized surfaces are tagged `implicit`.
    assert all("implicit" in match.surface.invariants for match in resolution.matches)


def test_resolve_query_restricts_synthesis_to_role_globs(tmp_path) -> None:
    _write(tmp_path / "docs" / "guide.md", "# guide\n")
    _write(tmp_path / "src" / "secret.py", "password = 'x'\n")
    role = RoleConfig(name="writer", query_paths=("docs/**",), edit_paths=())

    resolution = resolve_query_surfaces(
        role,
        IndexRecord(root=str(tmp_path), surfaces=(), warnings=()),
        "anything",
        top_k=5,
        repo_root=tmp_path,
    )

    files = {match.surface.file for match in resolution.matches}
    assert "docs/guide.md" in files
    assert "src/secret.py" not in files


def test_resolve_query_ignores_binary_and_noise_directories(tmp_path) -> None:
    _write(tmp_path / "README.md", "# hi\n")
    _write(tmp_path / "build" / "output.bin", "binary\n")
    _write(tmp_path / "node_modules" / "pkg.py", "x = 1\n")
    _write(tmp_path / "assets" / "logo.png", "png\n")
    role = RoleConfig(name="maintainer", query_paths=("**/*",), edit_paths=())

    resolution = resolve_query_surfaces(
        role,
        IndexRecord(root=str(tmp_path), surfaces=(), warnings=()),
        "anything",
        top_k=10,
        repo_root=tmp_path,
    )

    files = {match.surface.file for match in resolution.matches}
    assert "README.md" in files
    assert "build/output.bin" not in files
    assert "node_modules/pkg.py" not in files
    assert "assets/logo.png" not in files


def test_explicit_surface_wins_over_synthesized_when_same_file(tmp_path) -> None:
    _write(tmp_path / "src" / "core.py", "def a():\n    return 1\n")
    explicit = SurfaceRecord(
        id="core.a",
        file="src/core.py",
        line_start=1,
        line_end=2,
        roles=(),
        modes=("query", "edit"),
        invariants=("file_scope",),
        depends_on=(),
        hash="",
    )
    index = IndexRecord(root=str(tmp_path), surfaces=(explicit,), warnings=())
    role = RoleConfig(name="maintainer", query_paths=("**/*",), edit_paths=("**/*",))

    resolution = resolve_edit_surfaces(
        role,
        index,
        "change return 1 to return 10",
        top_k=1,
        repo_root=tmp_path,
    )

    assert resolution.matches
    top = resolution.matches[0].surface
    assert top.id == "core.a"
    assert "implicit" not in top.invariants


def test_explicit_wins_when_request_has_no_keyword_match(tmp_path) -> None:
    # Two files: one with an explicit surface, one without.
    _write(tmp_path / "src" / "core.py", "x = 1\n")
    _write(tmp_path / "src" / "other.py", "y = 2\n")
    explicit = SurfaceRecord(
        id="core.primary",
        file="src/core.py",
        line_start=1,
        line_end=1,
        roles=(),
        modes=("query", "edit"),
        invariants=("file_scope",),
        depends_on=(),
        hash="",
    )
    index = IndexRecord(root=str(tmp_path), surfaces=(explicit,), warnings=())
    role = RoleConfig(name="maintainer", query_paths=("**/*",), edit_paths=("**/*",))

    resolution = resolve_edit_surfaces(
        role,
        index,
        "do something generic",  # no keyword hits any file or surface
        top_k=1,
        repo_root=tmp_path,
    )

    assert resolution.matches
    assert resolution.matches[0].surface.id == "core.primary"


def test_edit_mode_excludes_files_the_role_cannot_write(tmp_path) -> None:
    _write(tmp_path / "src" / "core.py", "x = 1\n")
    _write(tmp_path / "docs" / "readme.md", "hi\n")
    role = RoleConfig(
        name="docs-writer",
        query_paths=("**/*",),
        edit_paths=("docs/**",),
    )

    resolution = resolve_edit_surfaces(
        role,
        IndexRecord(root=str(tmp_path), surfaces=(), warnings=()),
        "update the readme",
        top_k=5,
        repo_root=tmp_path,
    )

    files = {match.surface.file for match in resolution.matches}
    assert "docs/readme.md" in files
    assert "src/core.py" not in files


def test_repo_root_omitted_falls_back_to_index_only_behavior(tmp_path) -> None:
    # Without repo_root, we must not synthesize anything.
    _write(tmp_path / "docs" / "faq.md", "# FAQ\n")
    role = RoleConfig(name="maintainer", query_paths=("**/*",), edit_paths=())

    resolution = resolve_query_surfaces(
        role,
        IndexRecord(root=str(tmp_path), surfaces=(), warnings=()),
        "explain anything",
        top_k=3,
        # repo_root intentionally omitted
    )

    assert resolution.matches == ()
