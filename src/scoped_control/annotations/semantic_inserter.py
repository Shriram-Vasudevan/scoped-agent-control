"""LLM-backed semantic annotation insertion.

Uses an executor adapter to identify function- or class-level boundaries in a
file and inserts fine-grained surface annotations above each one. Falls back to
the file-scope annotator on any error.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
import json
import re
import shutil
import subprocess

from scoped_control.annotations.inserter import (
    AnnotationInsertResult,
    _comment_prefix,
    _looks_annotated,
    _path_matches,
    _surface_id,
    auto_annotate_repo,
)
from scoped_control.errors import CommandExecutionError
from scoped_control.models import AppConfig


IGNORED_DIRECTORIES = {".git", ".hg", ".svn", ".scoped-control", ".venv", "node_modules", "__pycache__", ".pytest_cache", "build", "dist"}


@dataclass(slots=True, frozen=True)
class SemanticBoundary:
    id: str
    line_start: int
    line_end: int


def semantic_annotate_repo(
    root: Path,
    *,
    config: AppConfig,
    roles: tuple[str, ...],
    query_globs: tuple[str, ...],
    edit_globs: tuple[str, ...],
    executor: str = "auto",
    force: bool = False,
    dry_run: bool = False,
) -> AnnotationInsertResult:
    """Insert semantic (per-function) annotations; fall back to file-scope on failure."""

    planner = _resolve_executor(config, executor)
    if planner == "heuristic":
        return auto_annotate_repo(
            root,
            roles=roles,
            query_globs=query_globs,
            edit_globs=edit_globs,
            force=force,
            dry_run=dry_run,
        )

    annotated: list[str] = []
    skipped: list[str] = []
    warnings: list[str] = []
    fallback_query: list[str] = []
    fallback_edit: list[str] = []

    matched = _collect_matched_files(root, query_globs, edit_globs)
    for relative in matched:
        file_path = root / relative
        prefix = _comment_prefix(file_path)
        if prefix is None:
            skipped.append(relative)
            continue
        original = file_path.read_text(encoding="utf-8")
        if _looks_annotated(original) and not force:
            skipped.append(relative)
            warnings.append(f"{relative}: existing annotations detected; skipped")
            continue
        modes: list[str] = []
        if _path_matches(relative, query_globs):
            modes.append("query")
        if _path_matches(relative, edit_globs):
            modes.append("edit")
        if not modes:
            skipped.append(relative)
            continue

        try:
            boundaries = _plan_boundaries(
                root=root,
                file_path=file_path,
                relative=relative,
                original=original,
                config=config,
                planner=planner,
            )
        except Exception as exc:  # noqa: BLE001 - fallback on any planner error
            warnings.append(f"{relative}: semantic planner failed ({exc}); using file-scope")
            if "query" in modes:
                fallback_query.append(relative)
            if "edit" in modes:
                fallback_edit.append(relative)
            continue

        if not boundaries:
            if "query" in modes:
                fallback_query.append(relative)
            if "edit" in modes:
                fallback_edit.append(relative)
            continue

        updated = _insert_semantic_blocks(
            original=original,
            boundaries=boundaries,
            roles=roles,
            modes=tuple(modes),
            prefix=prefix,
        )
        if not dry_run:
            file_path.write_text(updated, encoding="utf-8")
        annotated.append(relative)

    if fallback_query or fallback_edit:
        fallback_result = auto_annotate_repo(
            root,
            roles=roles,
            query_globs=tuple(fallback_query),
            edit_globs=tuple(fallback_edit),
            force=force,
            dry_run=dry_run,
        )
        annotated.extend(fallback_result.annotated_files)
        skipped.extend(fallback_result.skipped_files)
        warnings.extend(fallback_result.warnings)

    return AnnotationInsertResult(
        annotated_files=tuple(dict.fromkeys(annotated)),
        skipped_files=tuple(dict.fromkeys(skipped)),
        warnings=tuple(warnings),
    )


def _collect_matched_files(root: Path, query_globs: tuple[str, ...], edit_globs: tuple[str, ...]) -> tuple[str, ...]:
    matched: list[str] = []
    for path in root.rglob("*"):
        if any(part in IGNORED_DIRECTORIES for part in path.parts):
            continue
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if _path_matches(relative, query_globs) or _path_matches(relative, edit_globs):
            matched.append(relative)
    return tuple(sorted(dict.fromkeys(matched)))


def _insert_semantic_blocks(
    *,
    original: str,
    boundaries: tuple[SemanticBoundary, ...],
    roles: tuple[str, ...],
    modes: tuple[str, ...],
    prefix: str,
) -> str:
    lines = original.splitlines()
    # Insert bottom-up so earlier line numbers stay stable.
    sorted_boundaries = sorted(boundaries, key=lambda b: -b.line_start)
    for boundary in sorted_boundaries:
        if boundary.line_start < 1 or boundary.line_start > len(lines) + 1:
            continue
        block = [
            f"{prefix} surface: {boundary.id}",
            f"{prefix} roles: {', '.join(roles)}",
            f"{prefix} modes: {', '.join(modes)}",
            f"{prefix} invariants: span_scope",
            "",
        ]
        insert_index = boundary.line_start - 1
        # Preserve indentation of the target line so the annotation sits at the same level.
        target = lines[insert_index] if insert_index < len(lines) else ""
        indent = target[: len(target) - len(target.lstrip())]
        block = [f"{indent}{line}" if line else line for line in block]
        lines[insert_index:insert_index] = block
    return "\n".join(lines).rstrip() + "\n"


def _plan_boundaries(
    *,
    root: Path,
    file_path: Path,
    relative: str,
    original: str,
    config: AppConfig,
    planner: str,
) -> tuple[SemanticBoundary, ...]:
    prompt = _render_boundary_prompt(relative, original)
    if planner == "codex":
        output = _run_codex(config, root, prompt)
    elif planner == "claude_code":
        output = _run_claude(config, root, prompt)
    else:  # pragma: no cover
        raise ValueError(f"Unsupported semantic planner `{planner}`.")
    payload = _load_json_payload(output)
    return _parse_boundaries(payload, relative=relative, total_lines=len(original.splitlines()))


def _render_boundary_prompt(relative: str, original: str) -> str:
    # Pre-number the file so the planner can reference exact line numbers.
    numbered = "\n".join(f"{i + 1:5}| {line}" for i, line in enumerate(original.splitlines()))
    stem = PurePosixPath(relative).stem
    return (
        "You are planning scoped-control surface boundaries for one file.\n"
        "Identify top-level declarations (functions, classes, exported constants) that make\n"
        "sense as independently scoped surfaces. Skip imports, type aliases, module docstrings,\n"
        "and trivial one-liners.\n\n"
        "Return JSON only with this shape:\n"
        '{\n'
        '  "surfaces": [{"id": "identifier", "line_start": int, "line_end": int}, ...]\n'
        '}\n'
        "Rules:\n"
        f"- id must be a short kebab or dot-separated identifier derived from the declaration name, prefixed with `{stem}.`.\n"
        "- line_start is the first line of the declaration (the `def` / `class` / export line).\n"
        "- line_end is the last line that belongs to that declaration.\n"
        "- Line numbers refer to the numbered listing below.\n"
        "- Do not emit overlapping surfaces.\n"
        "- If the file has no meaningful surfaces, return {\"surfaces\": []}.\n"
        "- Do not include commentary outside the JSON.\n\n"
        f"File: {relative}\n"
        "```\n"
        f"{numbered}\n"
        "```\n"
    )


def _resolve_executor(config: AppConfig, requested: str) -> str:
    if requested in {"codex", "claude_code", "heuristic"}:
        return requested
    # auto
    codex_binary = config.executors.codex.command[0] if config.executors.codex.command else "codex"
    if shutil.which(codex_binary):
        return "codex"
    claude_binary = config.executors.claude_code.command[0] if config.executors.claude_code.command else "claude"
    if shutil.which(claude_binary):
        return "claude_code"
    return "heuristic"


def _run_codex(config: AppConfig, root: Path, prompt: str) -> str:
    binary = config.executors.codex.command[0] if config.executors.codex.command else "codex"
    if shutil.which(binary) is None:
        raise CommandExecutionError("Codex CLI not available.")
    command = [
        *config.executors.codex.command,
        *config.executors.codex.query_args,
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--cd",
        str(root),
        "--ephemeral",
        "-",
    ]
    completed = subprocess.run(  # noqa: S603
        command,
        input=prompt,
        text=True,
        capture_output=True,
        cwd=root,
        check=False,
    )
    if completed.returncode != 0:
        raise CommandExecutionError(completed.stderr.strip() or completed.stdout.strip() or "Codex semantic planner failed.")
    return completed.stdout.strip()


def _run_claude(config: AppConfig, root: Path, prompt: str) -> str:
    binary = config.executors.claude_code.command[0] if config.executors.claude_code.command else "claude"
    if shutil.which(binary) is None:
        raise CommandExecutionError("Claude Code CLI not available.")
    command = [
        *config.executors.claude_code.command,
        *config.executors.claude_code.query_args,
        "--print",
        "--output-format",
        "text",
        "--permission-mode",
        "default",
    ]
    completed = subprocess.run(  # noqa: S603
        command,
        input=prompt,
        text=True,
        capture_output=True,
        cwd=root,
        check=False,
    )
    if completed.returncode != 0:
        raise CommandExecutionError(completed.stderr.strip() or completed.stdout.strip() or "Claude semantic planner failed.")
    return completed.stdout.strip()


def _load_json_payload(text: str) -> dict[str, object]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Semantic planner response did not contain a JSON object.")
    return json.loads(stripped[start : end + 1])


def _parse_boundaries(payload: dict[str, object], *, relative: str, total_lines: int) -> tuple[SemanticBoundary, ...]:
    raw = payload.get("surfaces")
    if not isinstance(raw, list):
        return ()
    stem = _surface_id(relative)
    seen: set[str] = set()
    results: list[SemanticBoundary] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        identifier = item.get("id")
        start = item.get("line_start")
        end = item.get("line_end")
        if not isinstance(identifier, str) or not identifier.strip():
            continue
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        if start < 1 or end < start or start > total_lines:
            continue
        normalized = identifier.strip()
        if not normalized.startswith(stem):
            normalized = f"{stem}.{normalized}"
        if normalized in seen:
            continue
        seen.add(normalized)
        results.append(SemanticBoundary(id=normalized, line_start=start, line_end=min(end, total_lines)))
    # Keep them in file order for deterministic reasoning.
    results.sort(key=lambda b: b.line_start)
    return tuple(results)
