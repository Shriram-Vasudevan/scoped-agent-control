from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from textual.widgets import Input

from scoped_control.app import ScopedControlApp
from scoped_control.config.loader import bootstrap_repo


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "wave2"


def test_tui_query_command_runs_with_fake_executor(tmp_path) -> None:
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

    async def run_app() -> None:
        app = ScopedControlApp(start_path=repo_root)
        async with app.run_test() as pilot:
            command_input = app.query_one("#command-input", Input)

            await app.on_input_submitted(Input.Submitted(command_input, "scan"))
            await pilot.pause()
            await app.on_input_submitted(
                Input.Submitted(command_input, "query maintainer Explain python primary behavior --executor fake")
            )
            await pilot.pause()

            assert any("Query completed via fake executor." in line for line in app.console_state.results)
            assert any("Matched python.primary" in line for line in app.console_state.results)

    asyncio.run(run_app())
