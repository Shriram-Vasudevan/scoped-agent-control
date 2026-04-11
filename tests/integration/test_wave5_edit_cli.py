from __future__ import annotations

from dataclasses import replace
import shutil
from pathlib import Path

from scoped_control.cli import main
from scoped_control.config.loader import bootstrap_repo, load_config
from scoped_control.config.mutator import update_role, write_config
from scoped_control.index.builder import rebuild_index
from scoped_control.models import LimitsConfig, RoleConfig, ValidatorConfig


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "wave5"


def test_edit_cli_applies_valid_scoped_change(tmp_path, capsys) -> None:
    repo_root = _seed_edit_repo(tmp_path)

    exit_code = main(
        [
            "edit",
            "maintainer",
            "change",
            "return",
            "1",
            "to",
            "10",
            "--executor",
            "fake",
            "--path",
            str(repo_root),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Edit completed via fake executor." in output
    assert "Changed files: editable_module.py" in output
    assert "Validator py-compile: ok" in output
    assert "return 10" in (repo_root / "editable_module.py").read_text(encoding="utf-8")


def test_edit_cli_blocks_out_of_scope_file_changes(tmp_path, capsys) -> None:
    repo_root = _seed_edit_repo(tmp_path)
    before = (repo_root / "editable_module.py").read_text(encoding="utf-8")

    exit_code = main(
        [
            "edit",
            "maintainer",
            "[touch-unallowed-file]",
            "change",
            "return",
            "1",
            "to",
            "10",
            "--executor",
            "fake",
            "--path",
            str(repo_root),
        ]
    )
    error_output = capsys.readouterr().err

    assert exit_code == 1
    assert "Edit blocked by deterministic enforcement." in error_output
    assert "out-of-scope file edit: UNSCOPED.txt" in error_output
    assert not (repo_root / "UNSCOPED.txt").exists()
    assert (repo_root / "editable_module.py").read_text(encoding="utf-8") == before


def test_edit_cli_blocks_dependency_changes(tmp_path, capsys) -> None:
    repo_root = _seed_edit_repo(tmp_path)
    before = (repo_root / "editable_module.py").read_text(encoding="utf-8")

    exit_code = main(
        [
            "edit",
            "maintainer",
            "[edit-dependency]",
            "change",
            "helper",
            "--executor",
            "fake",
            "--path",
            str(repo_root),
        ]
    )
    error_output = capsys.readouterr().err

    assert exit_code == 1
    assert "dependency changes are blocked in editable_module.py" in error_output
    assert (repo_root / "editable_module.py").read_text(encoding="utf-8") == before


def test_edit_cli_blocks_validator_failures(tmp_path, capsys) -> None:
    repo_root = _seed_edit_repo(tmp_path)
    before = (repo_root / "editable_module.py").read_text(encoding="utf-8")

    exit_code = main(
        [
            "edit",
            "maintainer",
            "[break-syntax]",
            "change",
            "return",
            "1",
            "to",
            "10",
            "--executor",
            "fake",
            "--path",
            str(repo_root),
        ]
    )
    error_output = capsys.readouterr().err

    assert exit_code == 1
    assert "validator failed: py-compile" in error_output
    assert (repo_root / "editable_module.py").read_text(encoding="utf-8") == before


def test_edit_cli_blocks_diff_limits(tmp_path, capsys) -> None:
    repo_root = _seed_edit_repo(tmp_path, max_changed_files=1, max_diff_lines=40)
    before = (repo_root / "editable_module.py").read_text(encoding="utf-8")

    exit_code = main(
        [
            "edit",
            "maintainer",
            "[touch-many-files]",
            "[massive-edit]",
            "--executor",
            "fake",
            "--path",
            str(repo_root),
        ]
    )
    error_output = capsys.readouterr().err

    assert exit_code == 1
    assert "changed file count" in error_output or "diff size" in error_output
    assert (repo_root / "editable_module.py").read_text(encoding="utf-8") == before


def _seed_edit_repo(tmp_path, *, max_changed_files: int = 5, max_diff_lines: int = 400) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    bootstrap_repo(repo_root)
    shutil.copy2(FIXTURES / "editable_module.py", repo_root / "editable_module.py")

    paths, config = load_config(repo_root)
    maintainer = config.get_role("maintainer")
    updated_role = RoleConfig(
        name=maintainer.name,
        description=maintainer.description,
        query_paths=("**/*",),
        edit_paths=("**/*",),
    )
    updated = update_role(config, updated_role)
    updated = replace(
        updated,
        validators=(ValidatorConfig(name="py-compile", command="python -m py_compile editable_module.py", modes=("edit",)),),
        limits=LimitsConfig(max_changed_files=max_changed_files, max_diff_lines=max_diff_lines),
    )
    write_config(updated, paths.config_path)
    rebuild_index(repo_root)
    return repo_root
