"""Repo-wide setup planning from plain-English role intent."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess

from scoped_control.errors import CommandExecutionError
from scoped_control.models import AppConfig

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
    ".pytest_cache",
}
TOKEN_RE = re.compile(r"[a-z0-9_]+")
GLOBAL_SCOPE_HINTS = {
    "all",
    "anything",
    "entire",
    "everything",
    "full",
    "maintainer",
    "owner",
    "whole",
}
READ_ONLY_HINTS = {
    "analyze",
    "inspect",
    "read",
    "review",
}
EDIT_HINTS = {
    "change",
    "edit",
    "fix",
    "modify",
    "refactor",
    "rename",
    "rewrite",
    "update",
    "write",
}


@dataclass(slots=True, frozen=True)
class PlannedRoleScope:
    query_paths: tuple[str, ...]
    edit_paths: tuple[str, ...]
    annotate_query_globs: tuple[str, ...]
    annotate_edit_globs: tuple[str, ...]
    reasoning: tuple[str, ...]
    planner: str


def plan_role_scope(
    root: Path,
    *,
    config: AppConfig,
    role_name: str,
    description: str,
    intent: str,
    planner_executor: str = "auto",
    max_files: int = 400,
    read_intent: str | None = None,
    write_intent: str | None = None,
) -> PlannedRoleScope:
    """Infer query/edit scope from a role description and repository inventory.

    If `read_intent` and/or `write_intent` are provided, the planner uses them
    to infer query_paths and edit_paths independently. Otherwise it falls back
    to the single `intent` field.
    """

    inventory = collect_repo_inventory(root, max_files=max_files)
    selected_planner = _resolve_planner_executor(config, planner_executor)
    combined_intent = _combine_intents(intent=intent, read_intent=read_intent, write_intent=write_intent)
    split_intents = bool(read_intent or write_intent)

    if selected_planner == "heuristic":
        return _plan_role_scope_heuristic(
            role_name=role_name,
            description=description,
            intent=combined_intent,
            inventory=inventory,
            read_intent=read_intent,
            write_intent=write_intent,
        )

    try:
        return _plan_role_scope_with_llm(
            root,
            config=config,
            role_name=role_name,
            description=description,
            intent=combined_intent,
            inventory=inventory,
            planner=selected_planner,
            read_intent=read_intent if split_intents else None,
            write_intent=write_intent if split_intents else None,
        )
    except Exception as exc:
        heuristic = _plan_role_scope_heuristic(
            role_name=role_name,
            description=description,
            intent=combined_intent,
            inventory=inventory,
            read_intent=read_intent,
            write_intent=write_intent,
        )
        return PlannedRoleScope(
            query_paths=heuristic.query_paths,
            edit_paths=heuristic.edit_paths,
            annotate_query_globs=heuristic.annotate_query_globs,
            annotate_edit_globs=heuristic.annotate_edit_globs,
            reasoning=(f"{selected_planner} planner failed: {exc}", *heuristic.reasoning),
            planner=f"{selected_planner}->heuristic",
        )


def _combine_intents(*, intent: str, read_intent: str | None, write_intent: str | None) -> str:
    parts: list[str] = []
    if read_intent:
        parts.append(f"READ: {read_intent}")
    if write_intent:
        parts.append(f"WRITE: {write_intent}")
    if intent:
        parts.append(intent)
    return "\n".join(parts).strip() or intent


def collect_repo_inventory(root: Path, *, max_files: int = 400) -> tuple[str, ...]:
    """Collect a stable repository file inventory for planning."""

    files: list[str] = []
    for path in sorted(root.rglob("*")):
        if any(part in IGNORED_DIRECTORIES for part in path.parts):
            continue
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        files.append(relative)
        if len(files) >= max_files:
            break
    return tuple(files)


def _resolve_planner_executor(config: AppConfig, requested: str) -> str:
    if requested != "auto":
        return requested
    codex_binary = config.executors.codex.command[0] if config.executors.codex.command else "codex"
    if shutil.which(codex_binary):
        return "codex"
    claude_binary = config.executors.claude_code.command[0] if config.executors.claude_code.command else "claude"
    if shutil.which(claude_binary):
        return "claude_code"
    return "heuristic"


def _plan_role_scope_with_llm(
    root: Path,
    *,
    config: AppConfig,
    role_name: str,
    description: str,
    intent: str,
    inventory: tuple[str, ...],
    planner: str,
    read_intent: str | None = None,
    write_intent: str | None = None,
) -> PlannedRoleScope:
    prompt = _render_planner_prompt(
        role_name=role_name,
        description=description,
        intent=intent,
        inventory=inventory,
        read_intent=read_intent,
        write_intent=write_intent,
    )
    if planner == "codex":
        output = _run_codex_planner(config, root, prompt)
    elif planner == "claude_code":
        output = _run_claude_planner(config, root, prompt)
    else:
        raise ValueError(f"Unsupported planner executor `{planner}`.")
    payload = _load_json_payload(output)
    return _parse_planned_role_scope(payload, planner=planner)


def _render_planner_prompt(
    *,
    role_name: str,
    description: str,
    intent: str,
    inventory: tuple[str, ...],
    read_intent: str | None = None,
    write_intent: str | None = None,
) -> str:
    intent_lines: list[str] = []
    if read_intent:
        intent_lines.append(f"Read intent (maps to query_paths): {read_intent}")
    if write_intent:
        intent_lines.append(f"Write intent (maps to edit_paths): {write_intent}")
    if not intent_lines and intent:
        intent_lines.append(f"Role intent: {intent}")
    intents_block = "\n".join(intent_lines) if intent_lines else ""

    return (
        "You are planning repository access for scoped-agent-control.\n"
        "Infer the narrowest practical role scope from the role description and repository inventory.\n"
        "Return JSON only with this shape:\n"
        '{\n'
        '  "query_paths": ["repo-relative glob", "..."],\n'
        '  "edit_paths": ["repo-relative glob", "..."],\n'
        '  "annotate_query_globs": ["repo-relative glob", "..."],\n'
        '  "annotate_edit_globs": ["repo-relative glob", "..."],\n'
        '  "reasoning": ["short sentence", "..."]\n'
        '}\n'
        "Rules:\n"
        "- Use only paths or globs that match the inventory below.\n"
        "- Prefer repository-relative globs such as src/** or exact file paths.\n"
        "- edit_paths should usually be a subset of query_paths.\n"
        "- If the role truly needs broad project access, use **/*.\n"
        "- If the write intent says `none` or is empty, edit_paths must be [].\n"
        "- Do not include markdown fences or commentary outside the JSON.\n\n"
        f"Role name: {role_name}\n"
        f"Role description: {description}\n"
        f"{intents_block}\n\n"
        "Repository inventory:\n"
        + "\n".join(f"- {path}" for path in inventory)
        + "\n"
    )


def _run_codex_planner(config: AppConfig, root: Path, prompt: str) -> str:
    binary = config.executors.codex.command[0] if config.executors.codex.command else "codex"
    if shutil.which(binary) is None:
        raise CommandExecutionError("Codex CLI is not installed. Install Codex or use `--planner-executor heuristic`.")
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
    completed = subprocess.run(
        command,
        input=prompt,
        text=True,
        capture_output=True,
        cwd=root,
        check=False,
    )
    if completed.returncode != 0:
        raise CommandExecutionError(completed.stderr.strip() or completed.stdout.strip() or "Codex planner command failed.")
    return completed.stdout.strip()


def _run_claude_planner(config: AppConfig, root: Path, prompt: str) -> str:
    binary = config.executors.claude_code.command[0] if config.executors.claude_code.command else "claude"
    if shutil.which(binary) is None:
        raise CommandExecutionError("Claude Code CLI is not installed. Install Claude Code or use `--planner-executor heuristic`.")
    command = [
        *config.executors.claude_code.command,
        *config.executors.claude_code.query_args,
        "--print",
        "--output-format",
        "text",
        "--permission-mode",
        "default",
    ]
    completed = subprocess.run(
        command,
        input=prompt,
        text=True,
        capture_output=True,
        cwd=root,
        check=False,
    )
    if completed.returncode != 0:
        raise CommandExecutionError(completed.stderr.strip() or completed.stdout.strip() or "Claude planner command failed.")
    return completed.stdout.strip()


def _load_json_payload(text: str) -> dict[str, object]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Planner response did not contain a JSON object.")
    return json.loads(stripped[start : end + 1])


def _parse_planned_role_scope(payload: dict[str, object], *, planner: str) -> PlannedRoleScope:
    query_paths = _as_string_tuple(payload.get("query_paths"))
    edit_paths = _as_string_tuple(payload.get("edit_paths"))
    annotate_query_globs = _as_string_tuple(payload.get("annotate_query_globs")) or query_paths
    annotate_edit_globs = _as_string_tuple(payload.get("annotate_edit_globs")) or edit_paths
    reasoning = _as_string_tuple(payload.get("reasoning"))
    if not query_paths and not edit_paths:
        raise ValueError("Planner returned no query_paths or edit_paths.")
    return PlannedRoleScope(
        query_paths=query_paths,
        edit_paths=edit_paths,
        annotate_query_globs=annotate_query_globs,
        annotate_edit_globs=annotate_edit_globs,
        reasoning=reasoning,
        planner=planner,
    )


def _plan_role_scope_heuristic(
    *,
    role_name: str,
    description: str,
    intent: str,
    inventory: tuple[str, ...],
    read_intent: str | None = None,
    write_intent: str | None = None,
) -> PlannedRoleScope:
    combined = " ".join((role_name, description, intent, read_intent or "", write_intent or "")).lower()
    tokens = set(_tokenize(combined))
    write_is_none = write_intent is not None and write_intent.strip().lower() in {"none", "no", "n/a", "nothing", "read-only", "readonly"}

    if tokens & GLOBAL_SCOPE_HINTS:
        read_only = _looks_read_only(combined) or write_is_none
        return PlannedRoleScope(
            query_paths=("**/*",),
            edit_paths=() if read_only else ("**/*",),
            annotate_query_globs=("**/*",),
            annotate_edit_globs=() if read_only else ("**/*",),
            reasoning=("Detected broad-project access intent.",),
            planner="heuristic",
        )

    scored = sorted(
        (
            (_score_inventory_path(path, tokens), path)
            for path in inventory
        ),
        key=lambda item: (-item[0], item[1]),
    )
    matched_files = tuple(path for score, path in scored if score > 0)
    if not matched_files:
        read_only = _looks_read_only(combined) or write_is_none
        return PlannedRoleScope(
            query_paths=("**/*",),
            edit_paths=() if read_only else ("**/*",),
            annotate_query_globs=("**/*",),
            annotate_edit_globs=() if read_only else ("**/*",),
            reasoning=("No strong path matches found, so the heuristic fell back to broad project scope.",),
            planner="heuristic",
        )

    top_matches = matched_files[:12]
    query_paths = _collapse_paths_to_globs(top_matches)
    edit_paths = () if (_looks_read_only(combined) or write_is_none) else query_paths
    return PlannedRoleScope(
        query_paths=query_paths,
        edit_paths=edit_paths,
        annotate_query_globs=query_paths,
        annotate_edit_globs=edit_paths,
        reasoning=tuple(f"Heuristic matched repo paths: {', '.join(top_matches[:5])}" for _ in (0,)),
        planner="heuristic",
    )


def _score_inventory_path(path: str, tokens: set[str]) -> int:
    path_tokens = set(_tokenize(path.replace("/", " ").replace(".", " ")))
    score = 10 * len(tokens & path_tokens)
    lower_path = path.lower()
    if any(word in tokens for word in ("recruiter", "pm", "marketing", "sales", "gtm", "copy", "content")):
        if lower_path.endswith((".md", ".txt", ".yaml", ".yml")):
            score += 8
        if any(segment in lower_path for segment in ("readme", "examples", "docs", "prompt", "behavior")):
            score += 12
    if "test" in tokens and "tests/" in lower_path:
        score += 10
    if any(word in tokens for word in ("slack", "github", "integration")) and "integrations/" in lower_path:
        score += 12
    if any(word in tokens for word in ("cli", "setup")) and any(segment in lower_path for segment in ("cli.py", "setup_flow.py")):
        score += 12
    return score


def _collapse_paths_to_globs(paths: tuple[str, ...]) -> tuple[str, ...]:
    first_segments = [PurePosixPath(path).parts[0] for path in paths if PurePosixPath(path).parts]
    if first_segments:
        segment_counts: dict[str, int] = {}
        for segment in first_segments:
            segment_counts[segment] = segment_counts.get(segment, 0) + 1
        dominant_segment, count = max(segment_counts.items(), key=lambda item: item[1])
        if count >= max(3, len(paths) // 2):
            return (f"{dominant_segment}/**",)

    parents = [PurePosixPath(path).parent.as_posix() for path in paths]
    unique_parents = tuple(dict.fromkeys(parent for parent in parents if parent and parent != "."))
    if len(unique_parents) == 1:
        return (f"{unique_parents[0]}/**",)

    return tuple(dict.fromkeys(paths))


def _looks_read_only(text: str) -> bool:
    lowered = text.lower()
    has_read = any(hint in lowered for hint in READ_ONLY_HINTS) or "read-only" in lowered or "read only" in lowered
    has_edit = any(hint in lowered for hint in EDIT_HINTS)
    return has_read and not has_edit


def _tokenize(text: str) -> tuple[str, ...]:
    return tuple(token for token in TOKEN_RE.findall(text.lower()) if len(token) > 1)


def _as_string_tuple(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        return ()
    values: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            values.append(item.strip())
    return tuple(dict.fromkeys(values))
