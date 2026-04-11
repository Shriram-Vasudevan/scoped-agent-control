from __future__ import annotations

import shutil
from pathlib import Path

from scoped_control.cli import main
from scoped_control.config.loader import bootstrap_repo
from scoped_control.index.store import load_index


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "wave2"


def test_scan_and_index_cli_commands_build_and_read_the_index(tmp_path, capsys) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    bootstrap_repo(repo_root)

    for path in (
        FIXTURES / "python_repeated_annotations.py",
        FIXTURES / "typescript_repeated_annotations.ts",
        FIXTURES / "plain_text_repeated_annotations.txt",
        FIXTURES / "malformed_and_duplicate.py",
    ):
        shutil.copy2(path, repo_root / path.name)

    scan_exit = main(["scan", "--path", str(repo_root)])
    scan_output = capsys.readouterr().out

    assert scan_exit == 0
    assert "Indexed 7 surfaces from 4 files." in scan_output
    assert "duplicate surface id `shared.duplicate`" in scan_output

    index = load_index(repo_root / ".scoped-control" / "index.json")
    assert len(index.surfaces) == 7
    assert any(surface.id == "python.primary" for surface in index.surfaces)

    index_exit = main(["index", "--path", str(repo_root)])
    index_output = capsys.readouterr().out

    assert index_exit == 0
    assert "Surface count: 7" in index_output
    assert "- python.primary @ python_repeated_annotations.py:7-8" in index_output
