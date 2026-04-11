from __future__ import annotations

import shutil
from pathlib import Path

from scoped_control.cli import main
from scoped_control.config.loader import bootstrap_repo, load_config
from scoped_control.config.mutator import add_role, write_config
from scoped_control.index.builder import rebuild_index
from scoped_control.models import RoleConfig


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "wave2"


def test_query_cli_runs_end_to_end_with_fake_executor(tmp_path, capsys) -> None:
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

    paths, config = load_config(repo_root)
    updated = add_role(
        config,
        RoleConfig(name="reviewer", description="Read-only reviewer", query_paths=("**/*",), edit_paths=()),
    )
    write_config(updated, paths.config_path)
    rebuild_index(repo_root)
    before_index = paths.index_path.read_text(encoding="utf-8")

    exit_code = main(
        [
            "query",
            "reviewer",
            "Explain",
            "python",
            "secondary",
            "behavior",
            "--executor",
            "fake",
            "--path",
            str(repo_root),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Query completed via fake executor." in output
    assert "Executor: fake" in output
    assert "Allowed files: python_repeated_annotations.py" in output
    assert "Matched python.secondary" in output
    assert "Fake executor answer for request: Explain python secondary behavior" in output
    assert paths.index_path.read_text(encoding="utf-8") == before_index
