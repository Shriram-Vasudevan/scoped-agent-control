"""Role-aware query and edit surface matching.

Surfaces come from two sources:

1. The on-disk index — explicit surfaces that were placed by `annotate`
   (either file-scope or semantic).
2. Synthesized surfaces — created on the fly for files the role's globs cover
   but that have no explicit annotation. This is what lets a role with
   `query_paths: ["**/*"]` work without stamping a header on every file.

Explicit surfaces always win: if a file already has an explicit record, we do
NOT synthesize one for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
import re

from scoped_control.models import IndexRecord, ResolverMatch, RoleConfig, SurfaceRecord
from scoped_control.resolver.ranking import rank_surface_for_request


SYNTH_IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".scoped-control",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "build",
    "dist",
    ".next",
    ".cache",
}
SYNTH_IGNORE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".so",
    ".dylib",
    ".dll",
    ".class",
    ".o",
    ".a",
    ".exe",
    ".bin",
    ".lock",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".wasm",
}
_IMPLICIT_INVARIANT = "implicit"
_WHOLE_FILE_LINE_END = 10_000_000


@dataclass(slots=True, frozen=True)
class QueryResolution:
    matches: tuple[ResolverMatch, ...]
    dependency_surfaces: tuple[SurfaceRecord, ...]
    allowed_files: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class EditResolution:
    matches: tuple[ResolverMatch, ...]
    dependency_surfaces: tuple[SurfaceRecord, ...]
    writable_files: tuple[str, ...]


def resolve_query_surfaces(
    role: RoleConfig,
    index: IndexRecord,
    request: str,
    *,
    top_k: int = 3,
    repo_root: Path | None = None,
) -> QueryResolution:
    """Resolve query surfaces for a role.

    If `repo_root` is provided, files covered by `role.query_paths` that have
    no explicit surface in the index are given synthesized whole-file
    surfaces so the role can read them without per-file annotations.
    """

    candidates = _gather_surfaces(
        role=role,
        index=index,
        repo_root=repo_root,
        mode="query",
    )
    accessible = [
        surface
        for surface in candidates
        if "query" in surface.modes
        and _path_allowed(surface.file, role.query_paths)
        and (not surface.roles or role.name in surface.roles)
    ]
    ranked = [rank_surface_for_request(surface, request) for surface in accessible]
    ranked = sorted(ranked, key=_rank_sort_key)

    positive = [item for item in ranked if item.score > 0]
    if positive:
        selected = tuple(positive[:top_k])
    else:
        selected = tuple(
            ResolverMatch(
                surface=item.surface,
                score=1,
                reasons=("fallback within allowed query scope",),
            )
            for item in ranked[:top_k]
        )

    selected_surfaces = [match.surface for match in selected]
    accessible_by_id = {surface.id: surface for surface in accessible}
    seen_ids = {surface.id for surface in selected_surfaces}
    dependencies: list[SurfaceRecord] = []
    for surface in selected_surfaces:
        for dependency_id in surface.depends_on:
            dependency = accessible_by_id.get(dependency_id)
            if dependency is None or dependency.id in seen_ids:
                continue
            seen_ids.add(dependency.id)
            dependencies.append(dependency)

    allowed_files = tuple(
        sorted({surface.file for surface in (*selected_surfaces, *dependencies)})
    )
    return QueryResolution(
        matches=selected,
        dependency_surfaces=tuple(dependencies),
        allowed_files=allowed_files,
    )


def resolve_edit_surfaces(
    role: RoleConfig,
    index: IndexRecord,
    request: str,
    *,
    top_k: int = 3,
    repo_root: Path | None = None,
) -> EditResolution:
    """Resolve edit target surfaces for a role.

    Like `resolve_query_surfaces`, synthesizes whole-file surfaces for files
    covered by `role.edit_paths` that have no explicit annotation.
    """

    edit_candidates = _gather_surfaces(
        role=role,
        index=index,
        repo_root=repo_root,
        mode="edit",
    )
    writable_candidates = [
        surface
        for surface in edit_candidates
        if "edit" in surface.modes
        and _path_allowed(surface.file, role.edit_paths)
        and (not surface.roles or role.name in surface.roles)
    ]
    ranked = [rank_surface_for_request(surface, request) for surface in writable_candidates]
    ranked = sorted(ranked, key=_rank_sort_key)

    positive = [item for item in ranked if item.score > 0]
    if positive:
        selected = tuple(positive[:top_k])
    else:
        selected = tuple(
            ResolverMatch(
                surface=item.surface,
                score=1,
                reasons=("fallback within allowed edit scope",),
            )
            for item in ranked[:top_k]
        )

    selected_surfaces = [match.surface for match in selected]
    readable_patterns = tuple(dict.fromkeys((*role.query_paths, *role.edit_paths)))
    readable_pool = _gather_surfaces(
        role=role,
        index=index,
        repo_root=repo_root,
        mode="readable",
        patterns_override=readable_patterns,
    )
    readable_candidates = [
        surface
        for surface in readable_pool
        if _path_allowed(surface.file, readable_patterns)
        and (not surface.roles or role.name in surface.roles)
        and ("query" in surface.modes or "edit" in surface.modes)
    ]
    readable_by_id = {surface.id: surface for surface in readable_candidates}
    seen_ids = {surface.id for surface in selected_surfaces}
    dependencies: list[SurfaceRecord] = []
    for surface in selected_surfaces:
        for dependency_id in surface.depends_on:
            dependency = readable_by_id.get(dependency_id)
            if dependency is None or dependency.id in seen_ids:
                continue
            seen_ids.add(dependency.id)
            dependencies.append(dependency)

    writable_files = tuple(sorted({surface.file for surface in selected_surfaces}))
    return EditResolution(
        matches=selected,
        dependency_surfaces=tuple(dependencies),
        writable_files=writable_files,
    )


# ---------------------------------------------------------------------------
# Surface gathering (explicit + synthesized)


def _gather_surfaces(
    *,
    role: RoleConfig,
    index: IndexRecord,
    repo_root: Path | None,
    mode: str,
    patterns_override: tuple[str, ...] | None = None,
) -> list[SurfaceRecord]:
    explicit = list(index.surfaces)
    if repo_root is None:
        return explicit

    if patterns_override is not None:
        patterns = patterns_override
    elif mode == "edit":
        patterns = role.edit_paths
    else:
        patterns = role.query_paths

    if not patterns:
        return explicit

    explicit_files = {surface.file for surface in explicit}
    synthesized = _synthesize_surfaces(
        repo_root=repo_root,
        patterns=patterns,
        excluded_files=explicit_files,
    )
    return explicit + synthesized


def _synthesize_surfaces(
    *,
    repo_root: Path,
    patterns: tuple[str, ...],
    excluded_files: set[str],
) -> list[SurfaceRecord]:
    """Walk the repo and create whole-file surfaces for matched files."""

    if not repo_root.exists() or not repo_root.is_dir():
        return []

    surfaces: list[SurfaceRecord] = []
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        relative_path_obj = path.relative_to(repo_root)
        if any(part in SYNTH_IGNORE_DIRS for part in relative_path_obj.parts):
            continue
        if path.suffix.lower() in SYNTH_IGNORE_SUFFIXES:
            continue
        relative = relative_path_obj.as_posix()
        if relative in excluded_files:
            continue
        if not _path_allowed(relative, patterns):
            continue
        surfaces.append(
            SurfaceRecord(
                id=_implicit_surface_id(relative),
                file=relative,
                line_start=1,
                line_end=_WHOLE_FILE_LINE_END,
                roles=(),
                modes=("query", "edit"),
                invariants=("file_scope", _IMPLICIT_INVARIANT),
                depends_on=(),
                hash="",
            )
        )
    return surfaces


def _implicit_surface_id(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    without_suffix = str(path.with_suffix("")) if path.suffix else relative_path
    normalized = without_suffix.replace("/", ".")
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", ".", normalized)
    normalized = re.sub(r"\.+", ".", normalized).strip(".")
    return f"_implicit.{normalized or 'surface'}"


def _rank_sort_key(item: ResolverMatch) -> tuple[int, bool, str, int, str]:
    """Sort by score desc, then explicit surfaces before implicit, then path."""

    is_implicit = _IMPLICIT_INVARIANT in item.surface.invariants
    return (-item.score, is_implicit, item.surface.file, item.surface.line_start, item.surface.id)


def _path_allowed(path: str, patterns: tuple[str, ...]) -> bool:
    if not patterns:
        return False
    pure_path = PurePosixPath(path)
    for pattern in patterns:
        if pattern in {"*", "**", "**/*"}:
            return True
        if fnmatchcase(path, pattern) or pure_path.match(pattern):
            return True
    return False
