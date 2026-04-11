from __future__ import annotations

from scoped_control.cli import main
from scoped_control.config.loader import bootstrap_repo
from scoped_control.index.store import load_index


def test_annotate_cli_uses_role_paths_when_globs_are_omitted(tmp_path, capsys) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    docs_dir = repo_root / "docs"
    docs_dir.mkdir()
    (docs_dir / "faq.md").write_text("FAQ copy.\n", encoding="utf-8")
    bootstrap_repo(repo_root)

    assert main(
        [
            "role",
            "add",
            "writer",
            "--path",
            str(repo_root),
            "--query-path",
            "docs/**",
            "--edit-path",
            "docs/**",
        ]
    ) == 0
    capsys.readouterr()

    exit_code = main(["annotate", "--role", "writer", "--path", str(repo_root)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Auto-annotated 1 file(s)." in captured.out
    assert "Query globs: docs/**" in captured.out
    assert "Edit globs: docs/**" in captured.out

    file_text = (docs_dir / "faq.md").read_text(encoding="utf-8")
    assert "# surface: docs.faq" in file_text

    index = load_index(repo_root / ".scoped-control" / "index.json")
    surface = next(surface for surface in index.surfaces if surface.id == "docs.faq")
    assert surface.roles == ("writer",)
    assert surface.modes == ("query", "edit")
