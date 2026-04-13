from __future__ import annotations

from pathlib import Path

from scoped_control.cli import main
from scoped_control.config.loader import load_config
from scoped_control.index.store import load_index


def test_setup_cli_bootstraps_role_and_auto_annotations(tmp_path, capsys) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    docs_dir = repo_root / "docs"
    docs_dir.mkdir()
    (docs_dir / "brief.md").write_text("Initial brief contents.\n", encoding="utf-8")

    exit_code = main(
        [
            "setup",
            "--path",
            str(repo_root),
            "--role",
            "pm",
            "--description",
            "Product role",
            "--intent",
            "PM can update product docs in the docs folder.",
            "--planner-executor",
            "heuristic",
            "--annotate-files",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Setup complete." in captured.out
    assert "planned role scope via `heuristic`" in captured.out
    assert "Step 4: auto-annotated 1 file(s)" in captured.out

    _, config = load_config(repo_root)
    role = config.get_role("pm")
    assert role.description == "Product role"
    assert role.query_paths == ("docs/**",)
    assert role.edit_paths == ("docs/**",)

    file_text = (docs_dir / "brief.md").read_text(encoding="utf-8")
    assert "# surface: docs.brief" in file_text
    assert "# roles: pm" in file_text
    assert "# modes: query, edit" in file_text
    assert "# invariants: file_scope" in file_text

    index = load_index(repo_root / ".scoped-control" / "index.json")
    surface = next(surface for surface in index.surfaces if surface.id == "docs.brief")
    assert surface.roles == ("pm",)
    assert surface.modes == ("query", "edit")
    assert surface.invariants == ("file_scope",)
    assert surface.line_end == len(file_text.splitlines())


def test_setup_cli_runs_guided_prompts(tmp_path, capsys, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    prompts_dir = repo_root / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "copy.md").write_text("Original copy.\n", encoding="utf-8")

    responses = iter(
        (
            "recruiter",
            "",
            "Recruiter reads prompt copy and related markdown in the prompts folder.",
            "Recruiter can update prompt copy in the prompts folder.",
            "yes",  # annotate prompt -> yes (so the index gets explicit surfaces)
            "no",   # replace existing annotations
            "no",   # install github
            "no",   # install slack
        )
    )

    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))
    monkeypatch.setattr("scoped_control.cli._stdin_isatty", lambda: True)

    exit_code = main(["setup", "--path", str(repo_root), "--planner-executor", "heuristic"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Setup complete." in captured.out
    assert "configured role `recruiter`" in captured.out

    _, config = load_config(repo_root)
    role = config.get_role("recruiter")
    assert role.query_paths == ("prompts/**",)
    assert role.edit_paths == ("prompts/**",)

    index = load_index(repo_root / ".scoped-control" / "index.json")
    assert any(surface.id == "prompts.copy" for surface in index.surfaces)
