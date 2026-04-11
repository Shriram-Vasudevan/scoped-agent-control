"""Surface-span enforcement for edit diffs."""

from __future__ import annotations

from scoped_control.enforcement.diff_checks import FileChange
from scoped_control.models import SurfaceRecord


def enforce_surface_spans(
    changes: tuple[FileChange, ...],
    target_surfaces: tuple[SurfaceRecord, ...],
    dependency_surfaces: tuple[SurfaceRecord, ...],
) -> tuple[str, ...]:
    """Return span and dependency violations for changed files."""

    reasons: list[str] = []
    target_spans: dict[str, list[tuple[int, int]]] = {}
    dependency_spans: dict[str, list[tuple[int, int]]] = {}

    for surface in target_surfaces:
        target_spans.setdefault(surface.file, []).append((surface.line_start, surface.line_end))
    for surface in dependency_surfaces:
        dependency_spans.setdefault(surface.file, []).append((surface.line_start, surface.line_end))

    for change in changes:
        if change.path not in target_spans:
            if change.path in dependency_spans:
                reasons.append(f"dependency changes are blocked in {change.path}")
            else:
                reasons.append(f"out-of-scope file edit: {change.path}")
            continue

        allowed_ranges = target_spans[change.path]
        blocked_dependency_ranges = dependency_spans.get(change.path, [])
        for touched in change.touched_original_ranges:
            if _range_allowed(touched, allowed_ranges):
                continue
            if _range_overlaps(touched, blocked_dependency_ranges):
                reasons.append(f"dependency changes are blocked in {change.path}")
            else:
                reasons.append(f"edit outside allowed surface spans in {change.path}:{touched[0]}-{touched[1]}")
            break

    return tuple(dict.fromkeys(reasons))


def _range_allowed(candidate: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    start, end = candidate
    for span_start, span_end in spans:
        if start >= span_start and end <= span_end + 1:
            return True
    return False


def _range_overlaps(candidate: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    start, end = candidate
    for span_start, span_end in spans:
        if start <= span_end and end >= span_start:
            return True
    return False
