"""Embeddable library entry point.

`handle_request` runs the full scoped-control pipeline in one call: triage a
natural-language request, pick the mode and role, run the executor in a
sandbox, apply deterministic enforcement, and return a structured result.

Designed to be called from other services (e.g. a FastAPI Slack route) so they
can route plain-English messages through scoped-control without shelling out.
"""

from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path

from scoped_control.config.loader import load_config
from scoped_control.index.store import load_index
from scoped_control.triage import TriageDecision, triage_request
from scoped_control.tui.commands import execute_args


@dataclass(frozen=True, slots=True)
class ScopedResult:
    """Structured result of a full scoped-control request pipeline."""

    ok: bool
    mode: str  # "query" | "edit" | "blocked"
    role: str | None
    message: str
    reason: str
    targets: tuple[str, ...]
    changed_files: tuple[str, ...]
    output: str
    lines: tuple[str, ...]
    triager: str
    executor: str


def handle_request(
    repo_path: Path,
    request: str,
    *,
    role: str | None = None,
    executor: str = "claude_code",
    triager: str = "auto",
    top_k_query: int = 3,
    top_k_edit: int = 1,
) -> ScopedResult:
    """End-to-end: triage → execute → return a ScopedResult.

    Args:
        repo_path: Path to a repo initialized with `scoped-control setup`.
        request: Plain-English request text (e.g. a Slack message body).
        role: Pin to a specific role. If omitted, triage picks the narrowest
            role whose scope covers the targets; if provided, triage uses
            that role but still rejects if the role's scope does not cover
            the inferred targets.
        executor: Adapter to run the actual edit/query (e.g. "claude_code",
            "codex", "fake").
        triager: Which classifier to use ("auto", "heuristic", "codex",
            "claude_code").
        top_k_query: How many surfaces a query may pull in as context.
        top_k_edit: How many surfaces an edit may touch.

    Returns:
        ScopedResult. `ok=False` and `mode="blocked"` if triage blocks; `ok`
        reflects the executor + enforcement result otherwise.
    """

    paths, config = load_config(repo_path)
    index = load_index(paths.index_path)

    decision: TriageDecision = triage_request(
        paths.root,
        config,
        index,
        request,
        requested_role=role,
        triager=triager,
    )

    if not decision.ok:
        return ScopedResult(
            ok=False,
            mode="blocked",
            role=decision.role_name,
            message=decision.reason,
            reason=decision.reason,
            targets=decision.target_files,
            changed_files=(),
            output="",
            lines=decision.reasoning,
            triager=decision.triager,
            executor=executor,
        )

    namespace = argparse.Namespace(
        command=decision.mode,
        role_name=decision.role_name,
        request_tokens=[decision.request],
        executor=executor,
        top_k=top_k_query if decision.mode == "query" else top_k_edit,
    )
    result = execute_args(paths.root, namespace, raw_command=f"api {decision.mode}")

    changed_files: tuple[str, ...] = ()
    if decision.mode == "edit" and result.ok:
        changed_files = _git_changed_files(paths.root)

    output = ""
    if "Response:" in result.lines:
        idx = result.lines.index("Response:")
        if idx + 1 < len(result.lines):
            output = result.lines[idx + 1]

    return ScopedResult(
        ok=result.ok,
        mode=decision.mode,
        role=decision.role_name,
        message=result.message,
        reason=result.message if not result.ok else "",
        targets=decision.target_files,
        changed_files=changed_files,
        output=output,
        lines=result.lines,
        triager=decision.triager,
        executor=executor,
    )


def _git_changed_files(repo_path: Path) -> tuple[str, ...]:
    """Return files that have uncommitted changes (staged or unstaged)."""

    completed = subprocess.run(  # noqa: S603, S607
        ["git", "-C", str(repo_path), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return ()
    files: list[str] = []
    for line in completed.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ")[-1]
        files.append(path.strip('"'))
    return tuple(files)


__all__ = ["ScopedResult", "handle_request"]
