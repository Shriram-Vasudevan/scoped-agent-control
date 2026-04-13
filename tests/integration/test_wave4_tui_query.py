from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from textual.widgets import Input, RichLog

from scoped_control.app import ScopedControlApp
from scoped_control.config.loader import bootstrap_repo


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "wave2"


def _log_text(app: ScopedControlApp) -> str:
    log = app.query_one("#log", RichLog)
    parts: list[str] = []
    for strip in log.lines:
        try:
            parts.append(strip.text)
        except AttributeError:
            parts.append(str(strip))
    return "\n".join(parts)


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
            await pilot.pause()
            inp = app.query_one("#input", Input)

            await app.on_input_submitted(Input.Submitted(inp, "scan"))
            await pilot.pause()
            await app.on_input_submitted(
                Input.Submitted(inp, "query maintainer Explain python primary behavior --executor fake")
            )
            await pilot.pause()

            text = _log_text(app)
            assert "Query completed via fake executor." in text
            assert "Matched python.primary" in text

    asyncio.run(run_app())
