from __future__ import annotations

from dataclasses import replace
import json
import shutil
from pathlib import Path

import yaml

from scoped_control.cli import main
from scoped_control.config.loader import bootstrap_repo, load_config
from scoped_control.config.mutator import update_role, write_config
from scoped_control.index.builder import rebuild_index
from scoped_control.models import LimitsConfig, RoleConfig, ValidatorConfig


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "wave5"


def test_install_github_and_remote_edit_cli(tmp_path, capsys) -> None:
    repo_root = _seed_remote_repo(tmp_path)

    install_exit = main(["install", "github", "--path", str(repo_root)])
    install_output = capsys.readouterr().out

    assert install_exit == 0
    assert "Installed GitHub remote-edit scaffolding." in install_output
    workflow_path = repo_root / ".github" / "workflows" / "scoped-control.yml"
    assert workflow_path.exists()
    config_payload = yaml.safe_load((repo_root / ".scoped-control" / "config.yaml").read_text(encoding="utf-8"))
    assert config_payload["integrations"]["github"]["enabled"] is True

    event_path = repo_root / "event.json"
    event_path.write_text(
        json.dumps(
            {
                "inputs": {
                    "role": "maintainer",
                    "request": "change return 1 to return 10",
                    "executor": "fake",
                    "top_k": "1",
                }
            }
        ),
        encoding="utf-8",
    )

    remote_exit = main(["remote-edit", "--path", str(repo_root), "--event-file", str(event_path)])
    remote_output = capsys.readouterr().out

    assert remote_exit == 0
    assert "Edit completed via fake executor." in remote_output
    assert "return 10" in (repo_root / "editable_module.py").read_text(encoding="utf-8")


def _seed_remote_repo(tmp_path) -> Path:
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
        limits=LimitsConfig(max_changed_files=5, max_diff_lines=400),
    )
    write_config(updated, paths.config_path)
    rebuild_index(repo_root)
    return repo_root
