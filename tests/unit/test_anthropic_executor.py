"""Unit tests for the AnthropicExecutor (mocked SDK)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scoped_control.errors import CommandExecutionError
from scoped_control.executors.anthropic_sdk import (
    _strip_fence,
    AnthropicExecutor,
)
from scoped_control.models import ExecutionBrief


pytest.importorskip("anthropic")


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = [SimpleNamespace(text=text)]


class _FakeMessages:
    def __init__(self, text: str) -> None:
        self.text = text
        self.call: dict = {}

    def create(self, **kwargs):  # noqa: ANN003
        self.call = kwargs
        return _FakeResponse(self.text)


class _FakeClient:
    def __init__(self, text: str) -> None:
        self.messages = _FakeMessages(text)


def _exec(monkeypatch, reply_text: str) -> tuple[AnthropicExecutor, _FakeClient]:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fake = _FakeClient(reply_text)
    import scoped_control.executors.anthropic_sdk as mod

    monkeypatch.setattr(mod, "Anthropic", lambda: fake, raising=False)

    # Force the Anthropic import to resolve from our stub at call time.
    import anthropic as anth_mod

    monkeypatch.setattr(anth_mod, "Anthropic", lambda: fake, raising=False)
    executor = AnthropicExecutor()
    return executor, fake


def _brief(request: str) -> ExecutionBrief:
    return ExecutionBrief(
        kind="query",
        role_name="maintainer",
        request=request,
    )


def test_executor_raises_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(CommandExecutionError, match="ANTHROPIC_API_KEY"):
        AnthropicExecutor()


def test_run_query_returns_model_text(monkeypatch, tmp_path: Path) -> None:
    executor, _ = _exec(monkeypatch, "Robin greets the candidate warmly.")
    result = executor.run_query(_brief("what does robin do"), "prompt", tmp_path)
    assert result.ok is True
    assert result.kind == "query"
    assert "Robin greets" in result.output
    assert result.summary == "Query completed via anthropic sdk."


def test_run_edit_rewrites_single_file(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "example.py"
    target.write_text("x = 1\n", encoding="utf-8")
    executor, fake = _exec(monkeypatch, "x = 42\n")
    result = executor.run_edit(
        _brief("change x to 42"),
        "brief",
        tmp_path,
        ("example.py",),
    )
    assert result.ok is True
    assert target.read_text(encoding="utf-8") == "x = 42\n"
    assert "example.py" in result.output


def test_run_edit_strips_markdown_fences(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "file.py"
    target.write_text("old\n", encoding="utf-8")
    executor, _ = _exec(monkeypatch, "```python\nnew content\nhere\n```")
    executor.run_edit(_brief("edit"), "brief", tmp_path, ("file.py",))
    assert target.read_text(encoding="utf-8") == "new content\nhere"


def test_run_edit_raises_on_missing_target(monkeypatch, tmp_path: Path) -> None:
    executor, _ = _exec(monkeypatch, "whatever")
    with pytest.raises(CommandExecutionError, match="not found in workspace"):
        executor.run_edit(_brief("x"), "brief", tmp_path, ("nope.py",))


def test_run_edit_raises_on_empty_body(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "f.py"
    target.write_text("x\n", encoding="utf-8")
    executor, _ = _exec(monkeypatch, "")
    with pytest.raises(CommandExecutionError, match="empty"):
        executor.run_edit(_brief("x"), "brief", tmp_path, ("f.py",))


def test_strip_fence_noop_when_no_fence() -> None:
    assert _strip_fence("plain text") == "plain text"


def test_strip_fence_unwraps_python_fence() -> None:
    assert _strip_fence("```python\ndef x():\n    pass\n```") == "def x():\n    pass"
