"""Codex non-interactive query adapter."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from scoped_control.errors import CommandExecutionError
from scoped_control.executors.base import ExecutorAdapter
from scoped_control.models import ExecutionBrief, ExecutorConfig, RunResult


class CodexExecutor(ExecutorAdapter):
    name = "codex"

    def __init__(self, config: ExecutorConfig) -> None:
        self.config = config

    def run_query(self, brief: ExecutionBrief, prompt: str, workspace: Path) -> RunResult:
        binary = self.config.command[0] if self.config.command else "codex"
        if shutil.which(binary) is None:
            raise CommandExecutionError("Codex CLI is not installed. Install Codex or use `--executor fake`.")

        output_path = workspace / "codex-last-message.txt"
        command = [
            *self.config.command,
            *self.config.query_args,
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--cd",
            str(workspace),
            "--ephemeral",
            "--output-last-message",
            str(output_path),
            "-",
        ]
        completed = subprocess.run(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            cwd=workspace,
            check=False,
        )
        if completed.returncode != 0:
            raise CommandExecutionError(
                completed.stderr.strip() or completed.stdout.strip() or "Codex query command failed."
            )

        output = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else completed.stdout.strip()
        return RunResult(kind="query", ok=True, summary="Query completed via codex.", output=output)
