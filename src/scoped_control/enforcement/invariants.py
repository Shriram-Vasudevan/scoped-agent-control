"""Cheap deterministic invariant pre-check helpers."""

from __future__ import annotations

from scoped_control.models import SurfaceRecord


def collect_edit_precheck_notes(
    target_surfaces: tuple[SurfaceRecord, ...],
    dependency_surfaces: tuple[SurfaceRecord, ...],
) -> tuple[str, ...]:
    """Summarize invariant and dependency constraints before an edit run."""

    notes: list[str] = []
    for surface in target_surfaces:
        for invariant in surface.invariants:
            notes.append(f"Invariant for {surface.id}: {invariant}")
    if dependency_surfaces:
        notes.append(
            "Dependencies are read-only during edit runs: "
            + ", ".join(surface.id for surface in dependency_surfaces)
        )
    return tuple(notes)
