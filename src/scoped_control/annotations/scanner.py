"""Repo scanning for inline surface annotations."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path

from scoped_control.annotations.parser import AnnotationCandidate, finalize_annotation_run, parse_annotation_candidate
from scoped_control.annotations.spans import infer_surface_span
from scoped_control.models import SurfaceRecord

IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".scoped-control",
    ".venv",
    "build",
    "dist",
    "node_modules",
    "__pycache__",
}


@dataclass(slots=True, frozen=True)
class ScanRepositoryResult:
    surfaces: tuple[SurfaceRecord, ...]
    warnings: tuple[str, ...]
    files_scanned: int


def scan_repo(root: Path) -> ScanRepositoryResult:
    """Scan a repository root for supported annotation runs."""

    target_root = root.resolve()
    surfaces: list[SurfaceRecord] = []
    warnings: list[str] = []
    files_scanned = 0

    for current_root, dirnames, filenames in os.walk(target_root):
        dirnames[:] = sorted(directory for directory in dirnames if directory not in IGNORED_DIRECTORIES)
        for filename in sorted(filenames):
            path = Path(current_root) / filename
            if not path.is_file():
                continue
            files_scanned += 1
            file_surfaces, file_warnings = scan_file(path, target_root)
            surfaces.extend(file_surfaces)
            warnings.extend(file_warnings)

    ordered_surfaces = tuple(sorted(surfaces, key=lambda surface: (surface.file, surface.line_start, surface.id)))
    return ScanRepositoryResult(surfaces=ordered_surfaces, warnings=tuple(warnings), files_scanned=files_scanned)


def scan_file(path: Path, root: Path) -> tuple[tuple[SurfaceRecord, ...], tuple[str, ...]]:
    """Scan a single file for annotated surfaces."""

    relative_path = path.resolve().relative_to(root.resolve()).as_posix()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return (), ()

    surfaces: list[SurfaceRecord] = []
    warnings: list[str] = []

    index = 0
    while index < len(lines):
        candidate = parse_annotation_candidate(lines[index], index + 1)
        if not candidate.is_candidate:
            index += 1
            continue

        run: list[AnnotationCandidate] = [candidate]
        index += 1
        while index < len(lines):
            next_candidate = parse_annotation_candidate(lines[index], index + 1)
            if not next_candidate.is_candidate:
                break
            run.append(next_candidate)
            index += 1

        content_index = _find_attached_content(lines, index)
        if content_index is None:
            warnings.append(
                f"{relative_path}:line {run[0].line_number}: annotation block has no attached content and was skipped"
            )
            continue

        if parse_annotation_candidate(lines[content_index], content_index + 1).is_candidate:
            warnings.append(
                f"{relative_path}:line {run[0].line_number}: annotation block had no content before the next annotation block"
            )
            index = content_index
            continue

        metadata, run_warnings = finalize_annotation_run(run, relative_path)
        warnings.extend(run_warnings)
        if metadata is None:
            index = content_index
            continue

        if "file_scope" in metadata.invariants:
            end_index = len(lines) - 1
        else:
            next_annotation_index = _find_next_annotation_start(lines, content_index + 1)
            stop_index = next_annotation_index if next_annotation_index is not None else len(lines)
            end_index = infer_surface_span(lines, content_index, stop_index)
        block_lines = lines[content_index : end_index + 1]
        surfaces.append(
            SurfaceRecord(
                id=metadata.surface,
                file=relative_path,
                line_start=content_index + 1,
                line_end=end_index + 1,
                roles=metadata.roles,
                modes=metadata.modes,
                invariants=metadata.invariants,
                depends_on=metadata.depends_on,
                hash=_surface_hash(relative_path, metadata, block_lines),
            )
        )
        index = end_index + 1

    return tuple(surfaces), tuple(warnings)


def _find_attached_content(lines: list[str], start_index: int) -> int | None:
    for index in range(start_index, len(lines)):
        if lines[index].strip():
            return index
    return None


def _find_next_annotation_start(lines: list[str], start_index: int) -> int | None:
    for index in range(start_index, len(lines)):
        if parse_annotation_candidate(lines[index], index + 1).is_candidate:
            return index
    return None


def _surface_hash(relative_path: str, metadata, block_lines: list[str]) -> str:
    normalized_text = "\n".join(line.rstrip() for line in block_lines).strip()
    payload = {
        "file": relative_path,
        "surface": metadata.surface,
        "roles": list(metadata.roles),
        "modes": list(metadata.modes),
        "invariants": list(metadata.invariants),
        "depends_on": list(metadata.depends_on),
        "text": normalized_text,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
