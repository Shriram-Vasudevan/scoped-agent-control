from __future__ import annotations

import shutil
from pathlib import Path

from scoped_control.cli import main
from scoped_control.config.loader import bootstrap_repo, load_config
from scoped_control.tui.commands import execute_command


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "wave2"


def test_role_crud_via_cli(tmp_path, capsys) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    bootstrap_repo(repo_root)

    assert main(["role", "add", "writer", "--path", str(repo_root), "--description", "Writer role", "--query-path", "prompts", "--edit-path", "prompts"]) == 0
    add_output = capsys.readouterr().out
    assert "Added role `writer`." in add_output

    _, config = load_config(repo_root)
    writer = config.get_role("writer")
    assert writer.description == "Writer role"
    assert writer.query_paths == ("prompts",)
    assert writer.edit_paths == ("prompts",)

    assert main(["role", "edit", "writer", "--path", str(repo_root), "--description", "Updated role", "--query-path", "configs", "--clear-edit-paths"]) == 0
    capsys.readouterr()

    _, config = load_config(repo_root)
    writer = config.get_role("writer")
    assert writer.description == "Updated role"
    assert writer.query_paths == ("configs",)
    assert writer.edit_paths == ()

    assert main(["role", "list", "--path", str(repo_root)]) == 0
    list_output = capsys.readouterr().out
    assert "writer: query=configs edit=<none>" in list_output

    assert main(["role", "remove", "writer", "--path", str(repo_root)]) == 0
    remove_output = capsys.readouterr().out
    assert "Removed role `writer`." in remove_output

    _, config = load_config(repo_root)
    assert all(role.name != "writer" for role in config.roles)


def test_surface_and_validator_cli_commands(tmp_path, capsys) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    bootstrap_repo(repo_root)
    for source in (
        FIXTURES / "python_repeated_annotations.py",
        FIXTURES / "typescript_repeated_annotations.ts",
        FIXTURES / "plain_text_repeated_annotations.txt",
        FIXTURES / "malformed_and_duplicate.py",
    ):
        shutil.copy2(source, repo_root / source.name)

    assert main(["scan", "--path", str(repo_root)]) == 0
    capsys.readouterr()

    assert main(["surface", "list", "--path", str(repo_root)]) == 0
    surface_list_output = capsys.readouterr().out
    assert "python.primary @ python_repeated_annotations.py:7-8" in surface_list_output

    assert main(["surface", "show", "python.primary", "--path", str(repo_root)]) == 0
    surface_show_output = capsys.readouterr().out
    assert "Showing surface `python.primary`." in surface_show_output
    assert "Roles: maintainer, reviewer" in surface_show_output

    assert main(["validator", "list", "--path", str(repo_root)]) == 0
    validator_output = capsys.readouterr().out
    assert "No validators configured." in validator_output


def test_cleanup_command_is_available_in_tui_parser(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    result = execute_command(repo_root, "cleanup --dry-run")

    assert result.ok is True
    assert result.message == "No scoped-control artifacts found."
