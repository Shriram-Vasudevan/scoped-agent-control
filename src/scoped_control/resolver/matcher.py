"""Role-aware query surface matching."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

from scoped_control.models import IndexRecord, ResolverMatch, RoleConfig, SurfaceRecord
from scoped_control.resolver.ranking import rank_surface_for_request


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
) -> QueryResolution:
    """Resolve query surfaces deterministically for one role."""

    accessible = [
        surface
        for surface in index.surfaces
        if "query" in surface.modes
        and _path_allowed(surface.file, role.query_paths)
        and (not surface.roles or role.name in surface.roles)
    ]
    ranked = [rank_surface_for_request(surface, request) for surface in accessible]
    ranked = sorted(ranked, key=lambda item: (-item.score, item.surface.file, item.surface.line_start, item.surface.id))

    positive = [item for item in ranked if item.score > 0]
    if positive:
        selected = positive[:top_k]
    else:
        selected = tuple(
            ResolverMatch(surface=item.surface, score=1, reasons=("fallback within allowed query scope",))
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

    allowed_files = tuple(sorted({surface.file for surface in (*selected_surfaces, *dependencies)}))
    return QueryResolution(matches=tuple(selected), dependency_surfaces=tuple(dependencies), allowed_files=allowed_files)


def resolve_edit_surfaces(
    role: RoleConfig,
    index: IndexRecord,
    request: str,
    *,
    top_k: int = 3,
) -> EditResolution:
    """Resolve edit target surfaces for one role."""

    writable_candidates = [
        surface
        for surface in index.surfaces
        if "edit" in surface.modes
        and _path_allowed(surface.file, role.edit_paths)
        and (not surface.roles or role.name in surface.roles)
    ]
    ranked = [rank_surface_for_request(surface, request) for surface in writable_candidates]
    ranked = sorted(ranked, key=lambda item: (-item.score, item.surface.file, item.surface.line_start, item.surface.id))

    positive = [item for item in ranked if item.score > 0]
    if positive:
        selected = positive[:top_k]
    else:
        selected = tuple(
            ResolverMatch(surface=item.surface, score=1, reasons=("fallback within allowed edit scope",))
            for item in ranked[:top_k]
        )

    selected_surfaces = [match.surface for match in selected]
    readable_candidates = [
        surface
        for surface in index.surfaces
        if _path_allowed(surface.file, tuple(dict.fromkeys((*role.query_paths, *role.edit_paths))))
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
    return EditResolution(matches=tuple(selected), dependency_surfaces=tuple(dependencies), writable_files=writable_files)


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
