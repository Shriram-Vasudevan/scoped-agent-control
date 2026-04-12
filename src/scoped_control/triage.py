"""Natural-language request triage: classify read vs edit, pick role, check scope."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
import json
import re
import shutil
import subprocess

from scoped_control.errors import CommandExecutionError
from scoped_control.models import AppConfig, IndexRecord, RoleConfig

EDIT_HINTS = {
    "add",
    "change",
    "create",
    "delete",
    "edit",
    "fix",
    "implement",
    "insert",
    "modify",
    "patch",
    "refactor",
    "remove",
    "rename",
    "replace",
    "rewrite",
    "update",
    "write",
}
QUERY_HINTS = {
    "analyze",
    "check",
    "describe",
    "explain",
    "find",
    "how",
    "inspect",
    "read",
    "report",
    "review",
    "show",
    "summarize",
    "tell",
    "what",
    "where",
    "why",
}
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


@dataclass(slots=True, frozen=True)
class TriageDecision:
    """Outcome of triaging a natural-language request against a config + index."""

    mode: str  # "query" | "edit" | "blocked"
    role_name: str | None
    request: str
    reason: str
    target_files: tuple[str, ...] = ()
    candidate_roles: tuple[str, ...] = ()
    triager: str = "heuristic"
    reasoning: tuple[str, ...] = ()
    ok: bool = True


def triage_request(
    repo_root: Path,
    config: AppConfig,
    index: IndexRecord,
    request: str,
    *,
    requested_role: str | None = None,
    triager: str = "auto",
) -> TriageDecision:
    """Classify a request, pick a role, and check scope against the config.

    Steps:
      1) Decide mode: query vs edit (LLM if available, else heuristic).
      2) Identify likely target files (LLM or keyword match over the index).
      3) Pick a role that covers those files for the chosen mode, preferring
         the explicitly requested role when provided.
      4) If no role covers the targets, return mode="blocked" with a reason.
    """

    text = (request or "").strip()
    if not text:
        return TriageDecision(
            mode="blocked",
            role_name=None,
            request="",
            reason="Empty request.",
            ok=False,
        )

    chosen_triager = _resolve_triager(config, triager)
    llm_payload: dict[str, object] | None = None
    reasoning: list[str] = []

    if chosen_triager in {"codex", "claude_code"}:
        try:
            llm_payload = _run_llm_triager(
                repo_root,
                config=config,
                index=index,
                request=text,
                triager=chosen_triager,
                requested_role=requested_role,
            )
        except Exception as exc:  # noqa: BLE001 - fall back gracefully
            reasoning.append(f"{chosen_triager} triager failed: {exc}")
            chosen_triager = "heuristic"

    if llm_payload is not None:
        mode = _coerce_mode(llm_payload.get("mode"))
        targets = _coerce_files(llm_payload.get("target_files"), index)
        reasoning.extend(_coerce_reasons(llm_payload.get("reasoning")))
        suggested_role = llm_payload.get("role")
        suggested_role = suggested_role if isinstance(suggested_role, str) and suggested_role else None
    else:
        mode = _heuristic_mode(text)
        targets = _heuristic_targets(text, index)
        reasoning.append("Heuristic triager: mode inferred from verbs, files matched by keyword overlap with index.")
        suggested_role = None

    if not mode:
        mode = "query"
        reasoning.append("Mode could not be inferred; defaulted to query.")

    if not targets:
        # Without target files we still want to answer query requests against
        # the whole index. Edits without a target get blocked.
        if mode == "edit":
            return TriageDecision(
                mode="blocked",
                role_name=None,
                request=text,
                reason="Edit request did not name any indexed surface or file.",
                target_files=(),
                triager=chosen_triager,
                reasoning=tuple(reasoning),
                ok=False,
            )

    role, candidates, block_reason = _pick_role(
        config=config,
        mode=mode,
        targets=targets,
        requested_role=requested_role or suggested_role,
    )

    if role is None:
        return TriageDecision(
            mode="blocked",
            role_name=requested_role or suggested_role,
            request=text,
            reason=block_reason or "No configured role can cover this request.",
            target_files=targets,
            candidate_roles=candidates,
            triager=chosen_triager,
            reasoning=tuple(reasoning),
            ok=False,
        )

    return TriageDecision(
        mode=mode,
        role_name=role.name,
        request=text,
        reason=f"Matched role `{role.name}` for {mode} of {len(targets) or 'indexed'} target(s).",
        target_files=targets,
        candidate_roles=candidates,
        triager=chosen_triager,
        reasoning=tuple(reasoning),
        ok=True,
    )


# ---------------------------------------------------------------------------
# Heuristics


def _heuristic_mode(text: str) -> str:
    tokens = {token.lower() for token in TOKEN_RE.findall(text)}
    has_edit = bool(tokens & EDIT_HINTS)
    has_query = bool(tokens & QUERY_HINTS)
    if has_edit and not has_query:
        return "edit"
    if has_query and not has_edit:
        return "query"
    if has_edit and has_query:
        # A sentence with both (e.g. "review and update ...") favors edit.
        return "edit"
    return "query"


def _heuristic_targets(text: str, index: IndexRecord) -> tuple[str, ...]:
    tokens = {token.lower() for token in TOKEN_RE.findall(text) if len(token) > 1}
    if not tokens:
        return ()
    scored: list[tuple[int, str]] = []
    seen_files: set[str] = set()
    for surface in index.surfaces:
        score = 0
        surface_tokens = {t.lower() for t in TOKEN_RE.findall(surface.id + " " + surface.file)}
        overlap = tokens & surface_tokens
        if overlap:
            score += 10 * len(overlap)
        # Raw substring match of the filename stem is a strong signal.
        stem = PurePosixPath(surface.file).stem.lower()
        if stem and stem in text.lower():
            score += 15
        if score > 0 and surface.file not in seen_files:
            scored.append((score, surface.file))
            seen_files.add(surface.file)
    scored.sort(key=lambda item: (-item[0], item[1]))
    return tuple(path for _, path in scored[:5])


# ---------------------------------------------------------------------------
# Role matching


def _pick_role(
    *,
    config: AppConfig,
    mode: str,
    targets: tuple[str, ...],
    requested_role: str | None,
) -> tuple[RoleConfig | None, tuple[str, ...], str | None]:
    roles = list(config.roles)
    candidates: list[str] = []

    def covers(role: RoleConfig) -> bool:
        patterns = role.edit_paths if mode == "edit" else role.query_paths
        if not patterns:
            return False
        if not targets:
            # No concrete targets: only roles with real scope are viable, and
            # for queries we allow them.
            return mode == "query"
        return all(_path_matches(target, patterns) for target in targets)

    # Honor explicit role pick if provided.
    if requested_role:
        matched = next((r for r in roles if r.name == requested_role), None)
        if matched is None:
            return None, (), f"Requested role `{requested_role}` is not configured."
        if not covers(matched):
            return (
                None,
                (matched.name,),
                f"Role `{matched.name}` does not have {mode} access to the requested target(s).",
            )
        return matched, (matched.name,), None

    # Otherwise, pick the narrowest role that covers every target.
    viable: list[tuple[int, RoleConfig]] = []
    for role in roles:
        if covers(role):
            patterns = role.edit_paths if mode == "edit" else role.query_paths
            # Prefer roles with more specific (non-global) scope.
            specificity = sum(0 if pattern in {"*", "**", "**/*"} else 1 for pattern in patterns)
            viable.append((specificity, role))
            candidates.append(role.name)

    if not viable:
        return None, tuple(candidates), (
            f"No configured role has {mode} access to the requested target(s)."
        )
    viable.sort(key=lambda item: (-item[0], item[1].name))
    return viable[0][1], tuple(candidates), None


def _path_matches(path: str, patterns: tuple[str, ...]) -> bool:
    if not patterns:
        return False
    pure_path = PurePosixPath(path)
    for pattern in patterns:
        if pattern in {"*", "**", "**/*"}:
            return True
        if fnmatchcase(path, pattern) or pure_path.match(pattern):
            return True
    return False


# ---------------------------------------------------------------------------
# LLM triager


def _resolve_triager(config: AppConfig, requested: str) -> str:
    if requested == "heuristic":
        return "heuristic"
    if requested in {"codex", "claude_code"}:
        return requested
    # auto
    codex_binary = config.executors.codex.command[0] if config.executors.codex.command else "codex"
    if shutil.which(codex_binary):
        return "codex"
    claude_binary = config.executors.claude_code.command[0] if config.executors.claude_code.command else "claude"
    if shutil.which(claude_binary):
        return "claude_code"
    return "heuristic"


def _run_llm_triager(
    repo_root: Path,
    *,
    config: AppConfig,
    index: IndexRecord,
    request: str,
    triager: str,
    requested_role: str | None,
) -> dict[str, object]:
    prompt = _render_triage_prompt(
        config=config,
        index=index,
        request=request,
        requested_role=requested_role,
    )
    if triager == "codex":
        output = _run_codex(config, repo_root, prompt)
    elif triager == "claude_code":
        output = _run_claude(config, repo_root, prompt)
    else:  # pragma: no cover
        raise ValueError(f"Unsupported triager `{triager}`.")
    return _load_json_payload(output)


def _render_triage_prompt(
    *,
    config: AppConfig,
    index: IndexRecord,
    request: str,
    requested_role: str | None,
) -> str:
    roles_block = "\n".join(
        f"- {role.name}: query={list(role.query_paths) or '[]'} edit={list(role.edit_paths) or '[]'} ({role.description})"
        for role in config.roles
    ) or "- (no roles configured)"
    files_block = "\n".join(
        f"- {surface.id} @ {surface.file} modes={list(surface.modes)}"
        for surface in index.surfaces[:200]
    ) or "- (no indexed surfaces)"
    role_hint = f"Requested role: {requested_role}\n" if requested_role else ""
    return (
        "You are the triage step of scoped-agent-control.\n"
        "Decide whether a natural-language request is a read-only query or an edit,\n"
        "which files it would touch, and which configured role (if any) could serve it.\n"
        "Return JSON only with this shape:\n"
        '{\n'
        '  "mode": "query" | "edit",\n'
        '  "target_files": ["path1", ...],\n'
        '  "role": "<role name or null>",\n'
        '  "reasoning": ["short sentence", "..."]\n'
        '}\n'
        "Rules:\n"
        "- Only use target_files that appear in the indexed surfaces below.\n"
        "- Prefer the narrowest role whose paths cover the target_files.\n"
        "- If the request asks to modify anything, use mode = edit.\n"
        "- No markdown, no commentary outside the JSON.\n\n"
        f"{role_hint}"
        f"Request: {request}\n\n"
        "Roles:\n"
        f"{roles_block}\n\n"
        "Indexed surfaces:\n"
        f"{files_block}\n"
    )


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
        raise CommandExecutionError(completed.stderr.strip() or completed.stdout.strip() or "Codex triager failed.")
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
        "--tools",
        "",
        prompt,
    ]
    completed = subprocess.run(  # noqa: S603
        command,
        text=True,
        capture_output=True,
        cwd=root,
        check=False,
    )
    if completed.returncode != 0:
        raise CommandExecutionError(completed.stderr.strip() or completed.stdout.strip() or "Claude triager failed.")
    return completed.stdout.strip()


def _load_json_payload(text: str) -> dict[str, object]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Triager response did not contain a JSON object.")
    return json.loads(stripped[start : end + 1])


def _coerce_mode(raw: object) -> str:
    if not isinstance(raw, str):
        return ""
    value = raw.strip().lower()
    if value in {"query", "read", "read-only", "readonly"}:
        return "query"
    if value in {"edit", "write", "modify"}:
        return "edit"
    return ""


def _coerce_files(raw: object, index: IndexRecord) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    known = {surface.file for surface in index.surfaces}
    result: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            value = item.strip()
            if value in known and value not in result:
                result.append(value)
    return tuple(result)


def _coerce_reasons(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [item.strip() for item in raw if isinstance(item, str) and item.strip()]
