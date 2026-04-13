"""Unit tests for the Claude Code slash command installer."""

from __future__ import annotations

from scoped_control.integrations.claude_code import COMMANDS, install_claude_code


def test_install_claude_code_writes_slash_commands(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    installed = install_claude_code(repo)
    assert len(installed) == len(COMMANDS)
    for filename in COMMANDS:
        target = repo / ".claude" / "commands" / filename
        assert target.exists()
        text = target.read_text(encoding="utf-8")
        assert text.startswith("---")
        assert "scoped-control" in text


def test_install_claude_code_skips_existing_unless_force(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    install_claude_code(repo)
    rerun = install_claude_code(repo)
    assert rerun == ()
    forced = install_claude_code(repo, force=True)
    assert len(forced) == len(COMMANDS)
