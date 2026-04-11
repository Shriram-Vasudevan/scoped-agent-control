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
