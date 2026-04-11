from __future__ import annotations

import shutil
from pathlib import Path

from scoped_control.cli import main
from scoped_control.config.loader import bootstrap_repo, load_config
from scoped_control.config.mutator import write_config
from scoped_control.index.builder import rebuild_index
from scoped_control.models import AppConfig, ExecutorConfig, ExecutorsConfig


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "wave2"


def test_query_reports_missing_executor_binary_cleanly(tmp_path, capsys) -> None:
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
    rebuild_index(repo_root)

    paths, config = load_config(repo_root)
    updated = AppConfig(
        version=config.version,
        default_provider=config.default_provider,
        roles=config.roles,
        validators=config.validators,
        integrations=config.integrations,
        limits=config.limits,
        executors=ExecutorsConfig(
            default=config.executors.default,
            codex=ExecutorConfig(command=("definitely-missing-codex",), query_args=("exec",), edit_args=("exec",)),
            claude_code=config.executors.claude_code,
        ),
    )
    write_config(updated, paths.config_path)

    exit_code = main(
        [
            "query",
            "maintainer",
            "Explain",
            "python",
            "primary",
            "--executor",
            "codex",
            "--path",
            str(repo_root),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Install Codex or use `--executor fake`." in captured.err
