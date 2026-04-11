"""Base executor interfaces and registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from scoped_control.models import AppConfig, ExecutionBrief, RunResult


class ExecutorAdapter(ABC):
    """Common query/edit executor interface."""

    name: str

    @abstractmethod
    def run_query(self, brief: ExecutionBrief, prompt: str, workspace: Path) -> RunResult:
        """Execute a read-only query."""

    @abstractmethod
    def run_edit(self, brief: ExecutionBrief, prompt: str, workspace: Path, writable_files: tuple[str, ...]) -> RunResult:
        """Execute a scoped edit."""


def resolve_executor_name(config: AppConfig, requested: str | None = None) -> str:
    if requested:
        return requested
    if config.executors.default:
        return config.executors.default
    return config.default_provider


class FakeExecutor(ExecutorAdapter):
    """Deterministic local executor for tests and demos."""

    name = "fake"

    def run_query(self, brief: ExecutionBrief, prompt: str, workspace: Path) -> RunResult:
        target_ids = ", ".join(surface.id for surface in brief.target_surfaces)
        return RunResult(
            kind="query",
            ok=True,
            summary="Query completed via fake executor.",
            output=(
                f"Fake executor answer for request: {brief.request}\n"
                f"Role: {brief.role_name}\n"
                f"Targets: {target_ids}\n"
                f"Files: {', '.join(brief.allowed_files)}"
            ),
        )

    def run_edit(self, brief: ExecutionBrief, prompt: str, workspace: Path, writable_files: tuple[str, ...]) -> RunResult:
        request_lower = brief.request.lower()

        if "[touch-unallowed-file]" in request_lower:
            (workspace / "UNSCOPED.txt").write_text("blocked\n", encoding="utf-8")
            return RunResult(kind="edit", ok=True, summary="Edit completed via fake executor.", output="Touched an unallowed file.")

        if "[touch-many-files]" in request_lower:
            for name in ("one.txt", "two.txt", "three.txt"):
                (workspace / name).write_text("too many\n", encoding="utf-8")
            return RunResult(kind="edit", ok=True, summary="Edit completed via fake executor.", output="Touched too many files.")

        if not writable_files:
            return RunResult(kind="edit", ok=True, summary="Edit completed via fake executor.", output="No writable files.")

        target_path = workspace / writable_files[0]
        text = target_path.read_text(encoding="utf-8")

        if "[edit-dependency]" in request_lower:
            dependency_context = next((context for context in brief.file_contexts if context.kind == "dependency"), None)
            if dependency_context is not None:
                replacement = dependency_context.excerpt.replace("return 5", "return 55")
                text = text.replace(dependency_context.excerpt, replacement, 1)
        elif "[spill-outside]" in request_lower:
            text = text.rstrip() + "\n\nSPILLED_CHANGE = True\n"
        elif "[break-syntax]" in request_lower:
            text = text.replace("return 1", "return (", 1)
        elif "[massive-edit]" in request_lower:
            marker = "\n".join(f"    filler_line_{index} = {index}" for index in range(120))
            text = text.replace("return 1", f"{marker}\n    return 10", 1)
        else:
            text = _apply_requested_replacement(text, brief.request)

        target_path.write_text(text, encoding="utf-8")
        return RunResult(kind="edit", ok=True, summary="Edit completed via fake executor.", output="Applied fake edit.")


def build_query_executor(config: AppConfig, requested: str | None = None) -> ExecutorAdapter:
    """Build one query executor adapter."""

    name = resolve_executor_name(config, requested)
    if name == "fake":
        return FakeExecutor()
    if name == "codex":
        from scoped_control.executors.codex import CodexExecutor

        return CodexExecutor(config.executors.codex)
    if name == "claude_code":
        from scoped_control.executors.claude_code import ClaudeCodeExecutor

        return ClaudeCodeExecutor(config.executors.claude_code)
    raise ValueError(f"Unsupported executor `{name}`. Use codex, claude_code, or fake.")


def build_edit_executor(config: AppConfig, requested: str | None = None) -> ExecutorAdapter:
    """Build one edit executor adapter."""

    return build_query_executor(config, requested)


def _apply_requested_replacement(text: str, request: str) -> str:
    import re

    return_change = re.search(r"change return (\d+) to return (\d+)", request, re.IGNORECASE)
    if return_change:
        before, after = return_change.groups()
        return text.replace(f"return {before}", f"return {after}", 1)

    generic_replace = re.search(r"replace ([^ ]+) with ([^ ]+)", request, re.IGNORECASE)
    if generic_replace:
        before, after = generic_replace.groups()
        return text.replace(before, after, 1)

    return text.replace("return 1", "return 10", 1)
