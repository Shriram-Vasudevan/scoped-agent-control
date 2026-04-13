"""Anthropic Python SDK executor.

Uses the `anthropic` library instead of shelling out to the `claude` CLI.
Wins over the CLI path:

  - No Node.js or claude-code npm package in the deployment image.
  - Stable, versioned API surface that doesn't drift between CLI releases.
  - Direct subprocess-free control flow; easier to timeout, retry, observe.

Query path: one-shot `messages.create` returning the text answer.

Edit path: single-file whole-file rewrite. We show Claude the current file,
ask for the full new content, write it back. Works well for prompt files and
small-to-medium modules; falls down on sprawling multi-file refactors (use
the `claude_code` CLI executor for those).

The SDK is an *optional* dependency (`pip install scoped-agent-control[anthropic]`).
If unavailable, this executor raises at instantiation time with a clear message.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from scoped_control.errors import CommandExecutionError
from scoped_control.executors.base import ExecutorAdapter
from scoped_control.models import ExecutionBrief, ExecutorConfig, RunResult


_DEFAULT_MODEL = "claude-sonnet-4-5"
_DEFAULT_MAX_TOKENS = 16_384
_FENCE_RE = re.compile(r"^\s*```[a-zA-Z0-9]*\n(.*?)\n```\s*$", re.DOTALL)


class AnthropicExecutor(ExecutorAdapter):
    """Executor backed by the official Anthropic Python SDK."""

    name = "anthropic"

    def __init__(
        self,
        config: ExecutorConfig | None = None,
        *,
        model: str = _DEFAULT_MODEL,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> None:
        try:
            from anthropic import Anthropic  # noqa: F401  # imported lazily
        except ImportError as exc:
            raise CommandExecutionError(
                "The Anthropic SDK is not installed. "
                "Run `pip install scoped-agent-control[anthropic]` (or `pip install anthropic`)."
            ) from exc
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise CommandExecutionError(
                "ANTHROPIC_API_KEY is not set. Either export it or fall back to --executor fake."
            )
        self.model = os.environ.get("SCOPED_CONTROL_MODEL", model)
        self.max_tokens = max_tokens
        # Note: `config` is accepted for signature parity with CLI executors;
        # the SDK doesn't need the CLI path/args.
        self.config = config

    def run_query(self, brief: ExecutionBrief, prompt: str, workspace: Path) -> RunResult:
        text = self._call(prompt).strip()
        return RunResult(
            kind="query",
            ok=True,
            summary="Query completed via anthropic sdk.",
            output=text,
        )

    def run_edit(
        self,
        brief: ExecutionBrief,
        prompt: str,
        workspace: Path,
        writable_files: tuple[str, ...],
    ) -> RunResult:
        if not writable_files:
            return RunResult(
                kind="edit",
                ok=True,
                summary="Edit completed via anthropic sdk.",
                output="No writable files.",
            )

        # Single-file edit: whole-file rewrite. Simple, robust for prompt
        # files and small modules. Multi-file edits use `claude_code` CLI.
        target = writable_files[0]
        target_path = workspace / target
        if not target_path.exists():
            raise CommandExecutionError(f"Edit target `{target}` not found in workspace.")
        original = target_path.read_text(encoding="utf-8")

        edit_prompt = _render_edit_prompt(
            file_path=target,
            original=original,
            request=brief.request,
            brief=prompt,
        )
        new_content = _strip_fence(self._call(edit_prompt))
        if not new_content.strip():
            raise CommandExecutionError("Anthropic SDK returned an empty edit body.")

        target_path.write_text(new_content, encoding="utf-8")
        return RunResult(
            kind="edit",
            ok=True,
            summary="Edit completed via anthropic sdk.",
            output=f"Rewrote {target} ({len(original.splitlines())} → {len(new_content.splitlines())} lines).",
        )

    def _call(self, prompt: str) -> str:
        from anthropic import Anthropic

        client = Anthropic()
        response = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        parts: list[str] = []
        for block in response.content:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
        if not parts:
            raise CommandExecutionError("Anthropic SDK returned no text content.")
        return "".join(parts)


def _render_edit_prompt(*, file_path: str, original: str, request: str, brief: str) -> str:
    return (
        "You are editing a single file to satisfy a scoped change request.\n\n"
        f"Scope brief:\n{brief}\n\n"
        f"File: {file_path}\n"
        f"Request: {request}\n\n"
        "Here is the current file content:\n\n"
        "```\n"
        f"{original}\n"
        "```\n\n"
        "Output ONLY the complete new content of this file. Do not explain. "
        "Do not wrap in markdown. No preamble. Just the literal new file bytes "
        "that will replace the current version."
    )


def _strip_fence(text: str) -> str:
    """If the model wrapped output in a ```...``` fence, unwrap it."""

    match = _FENCE_RE.match(text)
    if match:
        return match.group(1)
    return text
