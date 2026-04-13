from __future__ import annotations

import asyncio
from dataclasses import replace
import shutil
from pathlib import Path

from textual.widgets import Input, RichLog

from scoped_control.app import ScopedControlApp


def _log_text(app: ScopedControlApp) -> str:
    log = app.query_one("#log", RichLog)
    parts: list[str] = []
    for strip in log.lines:
        try:
            parts.append(strip.text)
        except AttributeError:
            parts.append(str(strip))
    return "\n".join(parts)
from scoped_control.config.loader import bootstrap_repo, load_config
from scoped_control.config.mutator import update_role, write_config
from scoped_control.index.builder import rebuild_index
from scoped_control.models import LimitsConfig, RoleConfig, ValidatorConfig


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "wave5"


def test_tui_edit_command_applies_valid_fake_edit(tmp_path) -> None:
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

    async def run_app() -> None:
        app = ScopedControlApp(start_path=repo_root)
        async with app.run_test() as pilot:
            await pilot.pause()
            inp = app.query_one("#input", Input)
            await app.on_input_submitted(
                Input.Submitted(inp, "edit maintainer change return 1 to return 10 --executor fake")
            )
            await pilot.pause()

            text = _log_text(app)
            assert "Edit completed via fake executor." in text
            assert "return 10" in (repo_root / "editable_module.py").read_text(encoding="utf-8")

    asyncio.run(run_app())
