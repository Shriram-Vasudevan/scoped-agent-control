from __future__ import annotations

from dataclasses import replace
import shutil
from pathlib import Path

from scoped_control.cli import main
from scoped_control.config.loader import load_config
from scoped_control.config.mutator import update_role, write_config
from scoped_control.models import LimitsConfig, RoleConfig, ValidatorConfig


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "wave5"


def test_wave6_smoke_init_scan_query_blocked_edit_and_install(tmp_path, capsys) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    assert main(["init", "--path", str(repo_root)]) == 0
    capsys.readouterr()
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
        limits=LimitsConfig(max_changed_files=5, max_diff_lines=400),
    )
    write_config(updated, paths.config_path)

    assert main(["scan", "--path", str(repo_root)]) == 0
    scan_output = capsys.readouterr().out
    assert "Indexed" in scan_output

    assert main(["query", "maintainer", "Explain", "editable", "value", "--executor", "fake", "--path", str(repo_root)]) == 0
    query_output = capsys.readouterr().out
    assert "Query completed via fake executor." in query_output

    assert main(["edit", "maintainer", "[touch-unallowed-file]", "change", "return", "1", "to", "10", "--executor", "fake", "--path", str(repo_root)]) == 1
    edit_error = capsys.readouterr().err
    assert "Edit blocked by deterministic enforcement." in edit_error

    assert main(["install", "github", "--path", str(repo_root)]) == 0
    install_output = capsys.readouterr().out
    assert "Installed GitHub remote-edit and remote-triage scaffolding." in install_output
    assert (repo_root / ".github" / "workflows" / "scoped-control.yml").exists()
    assert (repo_root / ".github" / "workflows" / "scoped-control-triage.yml").exists()
