from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from textual.widgets import Input

from scoped_control.app import ScopedControlApp
from scoped_control.config.loader import bootstrap_repo
from scoped_control.tui.screens import SetupScreen, SetupSubmission


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "wave2"


def test_tui_command_flow_updates_live_state(tmp_path) -> None:
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

            await app.on_input_submitted(Input.Submitted(command_input, "role add writer --query-path prompts --edit-path prompts"))
            await pilot.pause()
            assert any(role.name == "writer" for role in app.console_state.roles)

            await app.on_input_submitted(Input.Submitted(command_input, "scan"))
            await pilot.pause()
            assert any(surface.id == "python.primary" for surface in app.console_state.surfaces)

            await app.on_input_submitted(Input.Submitted(command_input, "surface show python.primary"))
            await pilot.pause()
            assert app.console_state.selected_surface_id == "python.primary"
            assert any("Showing surface `python.primary`." in line for line in app.console_state.results)

    asyncio.run(run_app())


def test_tui_auto_prompts_for_setup_on_uninitialized_repo(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    async def run_app() -> None:
        app = ScopedControlApp(start_path=repo_root)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert any(isinstance(screen, SetupScreen) for screen in app.screen_stack)
            assert app.query_one("#command-input", Input).placeholder == "/setup"

    asyncio.run(run_app())


def test_tui_setup_submission_bootstraps_repo_inside_app(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    docs_dir = repo_root / "docs"
    docs_dir.mkdir()
    (docs_dir / "brief.md").write_text("Initial brief contents.\n", encoding="utf-8")

    async def run_app() -> None:
        app = ScopedControlApp(start_path=repo_root)
        async with app.run_test() as pilot:
            await pilot.pause()
            setup_screen = next(screen for screen in app.screen_stack if isinstance(screen, SetupScreen))
            setup_screen.dismiss(
                SetupSubmission(
                    role_name="pm",
                    description="Product role",
                    intent="PM can update docs in the docs folder.",
                    planner_executor="heuristic",
                    auto_annotate_enabled=True,
                    install_github_enabled=False,
                    install_slack_enabled=False,
                    slack_webhook_env="SLACK_WEBHOOK_URL",
                )
            )
            await pilot.pause()
            assert app.console_state.config_loaded is True
            assert any(role.name == "pm" for role in app.console_state.roles)
            assert any(surface.id == "docs.brief" for surface in app.console_state.surfaces)
            assert app.query_one("#command-input", Input).placeholder == "/role list"
            assert any("Setup complete." in line for line in app.console_state.results)

    asyncio.run(run_app())


def test_tui_setup_slash_command_opens_setup_screen(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    bootstrap_repo(repo_root)

    async def run_app() -> None:
        app = ScopedControlApp(start_path=repo_root)
        async with app.run_test() as pilot:
            command_input = app.query_one("#command-input", Input)
            await app.on_input_submitted(Input.Submitted(command_input, "setup"))
            await pilot.pause()
            assert any(isinstance(screen, SetupScreen) for screen in app.screen_stack)

    asyncio.run(run_app())
