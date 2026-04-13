"""Unit tests for open_pr_for_changes (mocked subprocess)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scoped_control.integrations.github_pr import (
    PullRequestResult,
    open_pr_for_changes,
)


def _ok(stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)


def _fail(cmd: list[str], stderr: str) -> subprocess.CalledProcessError:
    return subprocess.CalledProcessError(returncode=1, cmd=cmd, output="", stderr=stderr)


def test_open_pr_returns_no_changes_when_status_is_clean(monkeypatch, tmp_path: Path) -> None:
    def fake_run(args, cwd, capture_output, text, check):  # noqa: ARG001
        return _ok(stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = open_pr_for_changes(tmp_path, title="anything")
    assert isinstance(result, PullRequestResult)
    assert result.ok is False
    assert "no changes" in (result.error or "")


def test_open_pr_full_happy_path(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    outputs = {
        ("git", "status", "--porcelain"): _ok(stdout=" M foo.py\n"),
        ("git", "push"): _ok(),
        ("gh", "pr", "create"): _ok(
            stdout="https://github.com/example/repo/pull/42\n"
        ),
    }

    def fake_run(args, cwd, capture_output, text, check):  # noqa: ARG001
        calls.append(list(args))
        for key, response in outputs.items():
            if args[: len(key)] == list(key):
                return response
        return _ok()

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = open_pr_for_changes(
        tmp_path,
        title="prompt update: be kinder",
        body="requested in slack",
        branch_prefix="prompt-tuner/",
    )
    assert result.ok is True
    assert result.url == "https://github.com/example/repo/pull/42"
    assert result.branch is not None
    assert result.branch.startswith("prompt-tuner/")
    assert "prompt-update-be-kinder" in result.branch

    # Validate that we actually called the sequence we expect.
    seen = [tuple(c[:2]) for c in calls]
    assert ("git", "status") in seen
    assert ("git", "checkout") in seen
    assert ("git", "add") in seen
    assert ("git", "commit") in seen
    assert ("git", "push") in seen
    assert ("gh", "pr") in seen


def test_open_pr_surfaces_gh_error(monkeypatch, tmp_path: Path) -> None:
    def fake_run(args, cwd, capture_output, text, check):  # noqa: ARG001
        if args[:3] == ["git", "status", "--porcelain"]:
            return _ok(stdout=" M foo.py\n")
        if args[:2] == ["gh", "pr"]:
            raise _fail(list(args), stderr="not authenticated\n")
        return _ok()

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = open_pr_for_changes(tmp_path, title="thing")
    assert result.ok is False
    assert "not authenticated" in (result.error or "")


def test_open_pr_reports_missing_binary(monkeypatch, tmp_path: Path) -> None:
    def fake_run(args, cwd, capture_output, text, check):  # noqa: ARG001
        raise FileNotFoundError(2, "No such file", "gh")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = open_pr_for_changes(tmp_path, title="thing")
    assert result.ok is False
    assert "missing binary" in (result.error or "") or "git" in (result.error or "")
