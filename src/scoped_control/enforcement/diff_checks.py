"""Diff collection and limit checks."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
import shutil

from scoped_control.models import LimitsConfig

IGNORED_DIRECTORIES = {".git", ".venv", "__pycache__", ".pytest_cache"}


@dataclass(slots=True, frozen=True)
class FileChange:
    path: str
    status: str
    diff_lines: int
    original_text: str | None
    updated_text: str | None
    touched_original_ranges: tuple[tuple[int, int], ...]


def collect_file_changes(original_root: Path, edited_root: Path) -> tuple[FileChange, ...]:
    """Collect file changes between the original repo and the sandbox."""

    original = _snapshot_tree(original_root)
    edited = _snapshot_tree(edited_root)
    changes: list[FileChange] = []

    for path in sorted(set(original) | set(edited)):
        before = original.get(path)
        after = edited.get(path)
        if before == after:
            continue
        original_text = before.decode("utf-8", errors="replace") if before is not None else None
        updated_text = after.decode("utf-8", errors="replace") if after is not None else None
        status = "modified"
        if before is None:
            status = "added"
        elif after is None:
            status = "deleted"
        changes.append(
            FileChange(
                path=path,
                status=status,
                diff_lines=_diff_line_count(original_text or "", updated_text or ""),
                original_text=original_text,
                updated_text=updated_text,
                touched_original_ranges=_touched_original_ranges(original_text or "", updated_text or ""),
            )
        )

    return tuple(changes)


def enforce_diff_limits(changes: tuple[FileChange, ...], limits: LimitsConfig) -> tuple[str, ...]:
    """Return diff-size violations."""

    reasons: list[str] = []
    if len(changes) > limits.max_changed_files:
        reasons.append(
            f"changed file count {len(changes)} exceeds limit {limits.max_changed_files}"
        )
    total_diff_lines = sum(change.diff_lines for change in changes)
    if total_diff_lines > limits.max_diff_lines:
        reasons.append(
            f"diff size {total_diff_lines} exceeds limit {limits.max_diff_lines}"
        )
    return tuple(reasons)


def apply_file_changes(target_root: Path, edited_root: Path, changes: tuple[FileChange, ...]) -> None:
    """Apply approved sandbox changes back to the repo root."""

    for change in changes:
        source_path = edited_root / change.path
        target_path = target_root / change.path
        if change.status == "deleted":
            if target_path.exists():
                target_path.unlink()
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    for path in root.rglob("*"):
        if any(part in IGNORED_DIRECTORIES for part in path.parts):
            continue
        if path.is_file():
            snapshot[path.relative_to(root).as_posix()] = path.read_bytes()
    return snapshot


def _diff_line_count(before: str, after: str) -> int:
    matcher = SequenceMatcher(a=before.splitlines(), b=after.splitlines())
    total = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        total += (i2 - i1) + (j2 - j1)
    return total


def _touched_original_ranges(before: str, after: str) -> tuple[tuple[int, int], ...]:
    matcher = SequenceMatcher(a=before.splitlines(), b=after.splitlines())
    ranges: list[tuple[int, int]] = []
    for tag, i1, i2, _, _ in matcher.get_opcodes():
        if tag == "equal":
            continue
        start = i1 + 1
        end = max(i1 + 1, i2)
        ranges.append((start, end))
    return tuple(ranges)
