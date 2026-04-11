"""Claude Code non-interactive query adapter."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from scoped_control.errors import CommandExecutionError
from scoped_control.executors.base import ExecutorAdapter
from scoped_control.models import ExecutionBrief, ExecutorConfig, RunResult


class ClaudeCodeExecutor(ExecutorAdapter):
    name = "claude_code"

    def __init__(self, config: ExecutorConfig) -> None:
        self.config = config

    def run_query(self, brief: ExecutionBrief, prompt: str, workspace: Path) -> RunResult:
        binary = self.config.command[0] if self.config.command else "claude"
        if shutil.which(binary) is None:
            raise CommandExecutionError("Claude Code CLI is not installed. Install Claude Code or use `--executor fake`.")

        command = [
            *self.config.command,
            *self.config.query_args,
            "--print",
            "--output-format",
            "text",
            "--permission-mode",
            "default",
            "--tools",
            "",
            prompt,
        ]
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            cwd=workspace,
            check=False,
        )
        if completed.returncode != 0:
            raise CommandExecutionError(
                completed.stderr.strip() or completed.stdout.strip() or "Claude Code query command failed."
            )
        return RunResult(kind="query", ok=True, summary="Query completed via claude_code.", output=completed.stdout.strip())

    def run_edit(self, brief: ExecutionBrief, prompt: str, workspace: Path, writable_files: tuple[str, ...]) -> RunResult:
        binary = self.config.command[0] if self.config.command else "claude"
        if shutil.which(binary) is None:
            raise CommandExecutionError("Claude Code CLI is not installed. Install Claude Code or use `--executor fake`.")

        command = [
            *self.config.command,
            *self.config.edit_args,
            "--print",
            "--output-format",
            "text",
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            "Edit,Read,Bash",
            prompt,
        ]
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            cwd=workspace,
            check=False,
        )
        if completed.returncode != 0:
            raise CommandExecutionError(
                completed.stderr.strip() or completed.stdout.strip() or "Claude Code edit command failed."
            )
        return RunResult(kind="edit", ok=True, summary="Edit completed via claude_code.", output=completed.stdout.strip())
