"""Integration test for the remote-triage CLI path."""

from __future__ import annotations

from dataclasses import replace
import json
import shutil
from pathlib import Path

from scoped_control.cli import main
from scoped_control.config.loader import bootstrap_repo, load_config
from scoped_control.config.mutator import update_role, write_config
from scoped_control.index.builder import rebuild_index
from scoped_control.models import LimitsConfig, RoleConfig, ValidatorConfig


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "wave5"


def test_remote_triage_auto_routes_to_edit(tmp_path, capsys) -> None:
    repo = _seed(tmp_path)

    event = repo / "event.json"
    event.write_text(
        json.dumps(
            {
                "inputs": {
                    "request": "update editable_module.py to return 10 instead of 1",
                    "executor": "fake",
                }
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "remote-triage",
            "--path",
            str(repo),
            "--event-file",
            str(event),
            "--triager",
            "heuristic",
            "--executor",
            "fake",
        ]
    )
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Triage decision: mode=edit" in out
    assert "role=maintainer" in out


def test_remote_triage_blocks_out_of_scope(tmp_path, capsys) -> None:
    repo = _seed(tmp_path, scope="narrow")
    event = repo / "event.json"
    event.write_text(
        json.dumps(
            {
                "inputs": {
                    "request": "update editable_module.py to return 10",
                }
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "remote-triage",
            "--path",
            str(repo),
            "--event-file",
            str(event),
            "--triager",
            "heuristic",
        ]
    )
    err = capsys.readouterr()
    assert exit_code == 1
    combined = err.out + err.err
    assert "mode=blocked" in combined


def _seed(tmp_path, *, scope: str = "broad") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    bootstrap_repo(repo)
    shutil.copy2(FIXTURES / "editable_module.py", repo / "editable_module.py")
    paths, config = load_config(repo)
    maintainer = config.get_role("maintainer")
    if scope == "broad":
        updated_role = RoleConfig(
            name=maintainer.name,
            description=maintainer.description,
            query_paths=("**/*",),
            edit_paths=("**/*",),
        )
    else:
        updated_role = RoleConfig(
            name=maintainer.name,
            description=maintainer.description,
            query_paths=("docs/**",),
            edit_paths=("docs/**",),
        )
    updated = update_role(config, updated_role)
    updated = replace(
        updated,
        validators=(ValidatorConfig(name="py-compile", command="python -m py_compile editable_module.py", modes=("edit",)),),
        limits=LimitsConfig(max_changed_files=5, max_diff_lines=400),
    )
    write_config(updated, paths.config_path)
    rebuild_index(repo)
    return repo
