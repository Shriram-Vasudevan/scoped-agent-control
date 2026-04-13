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
    # RichLog stores its Rich renderables in `.lines` (Strip objects) — use their text.
    parts: list[str] = []
    for strip in log.lines:
        try:
            parts.append(strip.text)
        except AttributeError:
            parts.append(str(strip))
    return "\n".join(parts)


def test_tui_auto_starts_wizard_on_uninitialized_repo(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    async def run_app() -> None:
        app = ScopedControlApp(start_path=repo_root)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            assert app._mode == "wizard"
            text = _log_text(app)
            assert "Adding a role" in text
            assert "Role name" in text
            # Input should be focused and ready to receive typing.
            assert app.query_one("#input", Input).has_focus

    asyncio.run(run_app())


def test_tui_wizard_walks_four_questions_and_creates_role(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    docs_dir = repo_root / "docs"
    docs_dir.mkdir()
    (docs_dir / "brief.md").write_text("Initial brief contents.\n", encoding="utf-8")

    async def run_app() -> None:
        app = ScopedControlApp(start_path=repo_root)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            assert app._mode == "wizard"
            inp = app.query_one("#input", Input)

            for answer in ("pm", "Product role", "PM reads docs folder.", "PM can update docs folder."):
                await app.on_input_submitted(Input.Submitted(inp, answer))
                # Allow any asyncio.to_thread work on the final step to complete.
                for _ in range(40):
                    await pilot.pause()
                    if app._mode == "idle":
                        break

            text = _log_text(app)
            assert app._mode == "idle"
            assert "Role `pm` created" in text
            assert any("configured role `pm`" in line for line in text.splitlines())
            # Config + index were actually written.
            assert (repo_root / ".scoped-control" / "config.yaml").exists()
            assert (repo_root / ".scoped-control" / "index.json").exists()

    asyncio.run(run_app())


def test_tui_wizard_accepts_all_defaults_on_enter(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "hello.md").write_text("hi\n", encoding="utf-8")

    async def run_app() -> None:
        app = ScopedControlApp(start_path=repo_root)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            inp = app.query_one("#input", Input)

            # Empty-Enter four times should use every default.
            for _ in range(4):
                await app.on_input_submitted(Input.Submitted(inp, ""))
                for _ in range(40):
                    await pilot.pause()
                    if app._mode == "idle":
                        break

            text = _log_text(app)
            assert app._mode == "idle"
            assert "Role `maintainer` created" in text

    asyncio.run(run_app())


def test_tui_wizard_cancel(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    async def run_app() -> None:
        app = ScopedControlApp(start_path=repo_root)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            assert app._mode == "wizard"
            inp = app.query_one("#input", Input)
            await app.on_input_submitted(Input.Submitted(inp, "/cancel"))
            await pilot.pause()
            assert app._mode == "idle"
            assert "Setup canceled" in _log_text(app)

    asyncio.run(run_app())


def test_tui_slash_command_runs_in_idle_mode(tmp_path) -> None:
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
            assert app._mode == "idle"
            inp = app.query_one("#input", Input)

            await app.on_input_submitted(Input.Submitted(inp, "scan"))
            await pilot.pause()
            text = _log_text(app)
            assert "Indexed" in text
            assert "python.primary" in text or "Wrote" in text

            await app.on_input_submitted(Input.Submitted(inp, "role list"))
            await pilot.pause()
            text = _log_text(app)
            assert "maintainer" in text

    asyncio.run(run_app())


def test_tui_setup_slash_command_restarts_wizard(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    bootstrap_repo(repo_root)

    async def run_app() -> None:
        app = ScopedControlApp(start_path=repo_root)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._mode == "idle"
            inp = app.query_one("#input", Input)
            await app.on_input_submitted(Input.Submitted(inp, "/setup"))
            await pilot.pause()
            assert app._mode == "wizard"
            assert app._wizard_step == 0

    asyncio.run(run_app())


def test_tui_init_slash_command_also_starts_wizard(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    bootstrap_repo(repo_root)

    async def run_app() -> None:
        app = ScopedControlApp(start_path=repo_root)
        async with app.run_test() as pilot:
            await pilot.pause()
            inp = app.query_one("#input", Input)
            await app.on_input_submitted(Input.Submitted(inp, "/init"))
            await pilot.pause()
            assert app._mode == "wizard"

    asyncio.run(run_app())


def test_tui_help_command(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    bootstrap_repo(repo_root)

    async def run_app() -> None:
        app = ScopedControlApp(start_path=repo_root)
        async with app.run_test() as pilot:
            await pilot.pause()
            inp = app.query_one("#input", Input)
            await app.on_input_submitted(Input.Submitted(inp, "/help"))
            await pilot.pause()
            text = _log_text(app)
            assert "Slash commands" in text
            assert "/setup" in text

    asyncio.run(run_app())
