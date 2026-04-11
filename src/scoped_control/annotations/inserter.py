"""Automatic file-level annotation insertion."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
import re

from scoped_control.annotations.parser import parse_annotation_candidate

IGNORED_DIRECTORIES = {".git", ".hg", ".svn", ".scoped-control", ".venv", "node_modules", "__pycache__", ".pytest_cache", "build", "dist"}
HASH_COMMENT_EXTENSIONS = {
    ".py",
    ".sh",
    ".yaml",
    ".yml",
    ".toml",
    ".txt",
    ".md",
    ".env",
    ".ini",
    ".cfg",
}
SLASH_COMMENT_EXTENSIONS = {
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".swift",
    ".kt",
}


@dataclass(slots=True, frozen=True)
class AnnotationInsertResult:
    annotated_files: tuple[str, ...]
    skipped_files: tuple[str, ...]
    warnings: tuple[str, ...]


def auto_annotate_repo(
    root: Path,
    *,
    roles: tuple[str, ...],
    query_globs: tuple[str, ...],
    edit_globs: tuple[str, ...],
    force: bool = False,
    dry_run: bool = False,
) -> AnnotationInsertResult:
    """Insert one file-level surface annotation block into matched files."""

    annotated_files: list[str] = []
    skipped_files: list[str] = []
    warnings: list[str] = []

    matched_files = _collect_matched_files(root, query_globs, edit_globs)
    for relative_path in matched_files:
        file_path = root / relative_path
        prefix = _comment_prefix(file_path)
        if prefix is None:
            skipped_files.append(relative_path)
            warnings.append(f"{relative_path}: unsupported file type for auto-annotation")
            continue

        original_text = file_path.read_text(encoding="utf-8")
        if _looks_annotated(original_text) and not force:
            skipped_files.append(relative_path)
            warnings.append(f"{relative_path}: existing annotations detected; skipped")
            continue

        modes = []
        if _path_matches(relative_path, query_globs):
            modes.append("query")
        if _path_matches(relative_path, edit_globs):
            modes.append("edit")
        if not modes:
            skipped_files.append(relative_path)
            continue

        surface_id = _surface_id(relative_path)
        annotation_lines = [
            f"{prefix} surface: {surface_id}",
            f"{prefix} roles: {', '.join(roles)}",
            f"{prefix} modes: {', '.join(modes)}",
            f"{prefix} invariants: file_scope",
            "",
        ]
        updated_text = _insert_annotation_block(original_text, "\n".join(annotation_lines))
        if not dry_run:
            file_path.write_text(updated_text, encoding="utf-8")
        annotated_files.append(relative_path)

    return AnnotationInsertResult(
        annotated_files=tuple(annotated_files),
        skipped_files=tuple(skipped_files),
        warnings=tuple(warnings),
    )


def _collect_matched_files(root: Path, query_globs: tuple[str, ...], edit_globs: tuple[str, ...]) -> tuple[str, ...]:
    matched: list[str] = []
    for path in root.rglob("*"):
        if any(part in IGNORED_DIRECTORIES for part in path.parts):
            continue
        if not path.is_file():
            continue
        relative_path = path.relative_to(root).as_posix()
        if _path_matches(relative_path, query_globs) or _path_matches(relative_path, edit_globs):
            matched.append(relative_path)
    return tuple(sorted(dict.fromkeys(matched)))


def _path_matches(relative_path: str, globs: tuple[str, ...]) -> bool:
    pure_path = PurePosixPath(relative_path)
    for pattern in globs:
        if pattern in {"*", "**", "**/*"}:
            return True
        if fnmatchcase(relative_path, pattern) or pure_path.match(pattern):
            return True
    return False


def _comment_prefix(path: Path) -> str | None:
    if path.name in {"Dockerfile", "Makefile"}:
        return "#"
    if path.suffix.lower() in HASH_COMMENT_EXTENSIONS:
        return "#"
    if path.suffix.lower() in SLASH_COMMENT_EXTENSIONS:
        return "//"
    return None


def _looks_annotated(text: str) -> bool:
    lines = text.splitlines()
    for line_number, line in enumerate(lines[:24], start=1):
        if parse_annotation_candidate(line, line_number).is_candidate:
            return True
    return False


def _surface_id(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    without_suffix = str(path.with_suffix("")) if path.suffix else relative_path
    normalized = without_suffix.replace("/", ".")
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", ".", normalized)
    normalized = re.sub(r"\.+", ".", normalized).strip(".")
    return normalized or "surface"


def _insert_annotation_block(text: str, block: str) -> str:
    lines = text.splitlines()
    insertion_index = 0
    if lines and lines[0].startswith("#!"):
        insertion_index = 1
        if len(lines) > 1 and re.match(r"^#.*coding[:=]", lines[1]):
            insertion_index = 2

    before = lines[:insertion_index]
    after = lines[insertion_index:]
    assembled = [*before, block]
    if after:
        assembled.append("")
        assembled.extend(after)
    return "\n".join(assembled).rstrip() + "\n"
