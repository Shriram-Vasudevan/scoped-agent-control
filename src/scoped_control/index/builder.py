"""Index construction from scanned annotations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scoped_control.annotations.scanner import scan_repo
from scoped_control.config.loader import load_config
from scoped_control.index.store import write_index
from scoped_control.models import IndexRecord, SurfaceRecord


@dataclass(slots=True, frozen=True)
class BuildIndexResult:
    index: IndexRecord
    files_scanned: int
    warnings: tuple[str, ...]


def build_index(root: Path) -> BuildIndexResult:
    """Build an in-memory index from repo annotations."""

    scan_result = scan_repo(root)
    seen: dict[str, SurfaceRecord] = {}
    surfaces: list[SurfaceRecord] = []
    warnings = list(scan_result.warnings)

    for surface in scan_result.surfaces:
        if surface.id in seen:
            original = seen[surface.id]
            warnings.append(
                f"{surface.file}:line {surface.line_start}: duplicate surface id `{surface.id}` already defined at {original.file}:line {original.line_start}; skipping duplicate"
            )
            continue
        seen[surface.id] = surface
        surfaces.append(surface)

    index = IndexRecord(
        root=str(root.resolve()),
        surfaces=tuple(sorted(surfaces, key=lambda item: (item.file, item.line_start, item.id))),
        warnings=tuple(warnings),
    )
    return BuildIndexResult(index=index, files_scanned=scan_result.files_scanned, warnings=tuple(warnings))


def rebuild_index(start: Path | None = None) -> tuple[BuildIndexResult, Path]:
    """Build and persist the index for an initialized repo."""

    paths, _ = load_config(start)
    result = build_index(paths.root)
    write_index(result.index, paths.index_path)
    return result, paths.index_path
