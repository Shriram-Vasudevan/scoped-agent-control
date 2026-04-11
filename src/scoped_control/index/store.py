"""JSON storage for the surface index."""

from __future__ import annotations

import json
from pathlib import Path

from scoped_control.errors import RepoNotInitializedError
from scoped_control.models import IndexRecord, SurfaceRecord


def empty_index(root: Path) -> IndexRecord:
    """Return the bootstrap empty index."""

    return IndexRecord(root=str(root.resolve()), surfaces=(), warnings=())


def write_index(index: IndexRecord, path: Path) -> None:
    """Persist the index as canonical JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "root": index.root,
        "surfaces": [
            {
                "id": surface.id,
                "file": surface.file,
                "line_start": surface.line_start,
                "line_end": surface.line_end,
                "roles": list(surface.roles),
                "modes": list(surface.modes),
                "invariants": list(surface.invariants),
                "depends_on": list(surface.depends_on),
                "hash": surface.hash,
            }
            for surface in index.surfaces
        ],
        "warnings": list(index.warnings),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_index(path: Path) -> IndexRecord:
    """Load a stored index without rescanning."""

    if not path.exists():
        raise RepoNotInitializedError(f"Missing index file at {path}. Run `scoped-control scan` first.")
    raw = json.loads(path.read_text(encoding="utf-8"))
    surfaces = tuple(
        SurfaceRecord(
            id=item["id"],
            file=item["file"],
            line_start=item["line_start"],
            line_end=item["line_end"],
            roles=tuple(item.get("roles", [])),
            modes=tuple(item.get("modes", [])),
            invariants=tuple(item.get("invariants", [])),
            depends_on=tuple(item.get("depends_on", [])),
            hash=item.get("hash", ""),
        )
        for item in raw.get("surfaces", [])
    )
    return IndexRecord(root=raw.get("root", ""), surfaces=surfaces, warnings=tuple(raw.get("warnings", [])))


def list_surfaces(index: IndexRecord) -> tuple[SurfaceRecord, ...]:
    """Return surfaces in stable display order."""

    return tuple(sorted(index.surfaces, key=lambda surface: (surface.file, surface.line_start, surface.id)))


def get_surface(index: IndexRecord, surface_id: str) -> SurfaceRecord | None:
    """Return one surface by id if present."""

    for surface in index.surfaces:
        if surface.id == surface_id:
            return surface
    return None
