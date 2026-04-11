"""Textual application shell."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Vertical
from textual.widgets import Footer, Header, Input, Static

from scoped_control.config.loader import load_repo_context
from scoped_control.index.store import get_surface, load_index, list_surfaces
from scoped_control.setup_flow import run_setup
from scoped_control.tui.commands import CommandResult, execute_command
from scoped_control.tui.screens import SetupScreen, SetupSubmission, SummaryPanel
from scoped_control.tui.state import ConsoleState


class ScopedControlApp(App[None]):
    """The repo console for scoped-control."""

    CSS = """
    Screen {
      layout: vertical;
    }

    #body {
      height: 1fr;
      grid-size: 2 3;
      grid-columns: 1fr 1fr;
      grid-rows: 1fr 1fr 1fr;
      padding: 1;
      grid-gutter: 1 2;
    }

    SummaryPanel, #status {
      border: round $primary;
      padding: 1;
      height: 1fr;
    }

    #command-row {
      height: auto;
      padding: 0 1 1 1;
    }

    #command-input {
      width: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
        Binding("slash", "focus_command", "Command"),
        Binding("s", "open_setup", "Setup"),
    ]

    def __init__(self, *, start_path: Path | None = None) -> None:
        super().__init__()
        self.start_path = start_path or Path.cwd()
        self._setup_prompted = False
        self.console_state = ConsoleState(
            repo_root=self.start_path.resolve(),
            config_path=(self.start_path / ".scoped-control" / "config.yaml").resolve(),
            index_path=(self.start_path / ".scoped-control" / "index.json").resolve(),
            config_loaded=False,
        )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Grid(id="body"):
            yield SummaryPanel("Roles", id="roles")
            yield SummaryPanel("Surfaces", id="surfaces")
            yield SummaryPanel("Validators", id="validators")
            yield SummaryPanel("Requests / Runs", id="requests")
            yield SummaryPanel("Logs / Results", id="logs")
            yield Static("", id="status")
        with Vertical(id="command-row"):
            yield Input(placeholder="/setup", id="command-input")
        yield Footer()

    def on_mount(self) -> None:
        self.action_focus_command()
        self.refresh_repo_state()
        self.call_after_refresh(self._maybe_prompt_setup)

    def action_focus_command(self) -> None:
        self.query_one("#command-input", Input).focus()

    def action_open_setup(self) -> None:
        self.open_setup_screen()

    def refresh_repo_state(self) -> None:
        context = load_repo_context(self.start_path, require_config=False)
        surfaces = ()
        if context.config is not None and context.paths.index_path.exists():
            try:
                surfaces = list_surfaces(load_index(context.paths.index_path))
            except Exception:
                surfaces = ()

        self.console_state = ConsoleState(
            repo_root=context.paths.root,
            config_path=context.paths.config_path,
            index_path=context.paths.index_path,
            config_loaded=context.config is not None,
            config_error=context.config_error,
            roles=context.config.roles if context.config is not None else (),
            validators=context.config.validators if context.config is not None else (),
            surfaces=surfaces,
            selected_surface_id=self.console_state.selected_surface_id,
            requests=self.console_state.requests,
            results=self.console_state.results,
        )
        self._refresh_panels(context)

    def _refresh_panels(self, context) -> None:
        roles_panel = self.query_one("#roles", SummaryPanel)
        surfaces_panel = self.query_one("#surfaces", SummaryPanel)
        validators_panel = self.query_one("#validators", SummaryPanel)
        requests_panel = self.query_one("#requests", SummaryPanel)
        logs_panel = self.query_one("#logs", SummaryPanel)
        status = self.query_one("#status", Static)
        command_input = self.query_one("#command-input", Input)

        if context.config is None:
            command_input.placeholder = "/setup"
            roles_panel.set_body("No config loaded yet.")
            validators_panel.set_body("Validators are unavailable until the repo is initialized.")
            surfaces_panel.set_body("Use `/setup` to bootstrap the repo inside this TUI.")
            requests_panel.set_body("Start with `/setup`, then use slash commands after onboarding.")
            logs_panel.set_body(
                "\n".join(self.console_state.results) or context.config_error or "Use `/setup` to bootstrap this repo here."
            )
            status.update(
                f"[b]Repo[/b]\n{context.paths.root}\n\n[b]Status[/b]\n{context.config_error or 'Not initialized'}"
            )
            return

        command_input.placeholder = "/role list"
        roles_panel.set_body(
            "\n".join(
                f"- {role.name}: q={', '.join(role.query_paths) or '<none>'} | e={', '.join(role.edit_paths) or '<none>'}"
                for role in self.console_state.roles
            )
            or "No roles configured."
        )
        validators_panel.set_body(
            "\n".join(f"- {validator.name}: {validator.command}" for validator in self.console_state.validators)
            or "No validators configured."
        )
        if self.console_state.selected_surface_id:
            selected_surface = next(
                (surface for surface in self.console_state.surfaces if surface.id == self.console_state.selected_surface_id),
                None,
            )
            if selected_surface is not None:
                surfaces_panel.set_body(
                    "\n".join(
                        (
                            f"ID: {selected_surface.id}",
                            f"File: {selected_surface.file}",
                            f"Span: {selected_surface.line_start}-{selected_surface.line_end}",
                            f"Roles: {', '.join(selected_surface.roles) or '<none>'}",
                            f"Modes: {', '.join(selected_surface.modes) or '<none>'}",
                            f"Invariants: {', '.join(selected_surface.invariants) or '<none>'}",
                            f"Depends on: {', '.join(selected_surface.depends_on) or '<none>'}",
                        )
                    )
                )
            else:
                surfaces_panel.set_body(_format_surface_list(self.console_state.surfaces))
        else:
            surfaces_panel.set_body(_format_surface_list(self.console_state.surfaces))
        requests_panel.set_body("\n".join(f"- {item}" for item in self.console_state.requests) or "No commands run yet.")
        logs_panel.set_body("\n".join(self.console_state.results) or "App shell is live. Use `/role list` or `/scan`.")
        status.update(
            f"[b]Repo[/b]\n{context.paths.root}\n\n[b]Config[/b]\n{context.paths.config_path}\n\n[b]Index[/b]\n{context.paths.index_path}"
        )

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "command-input":
            return
        command_text = event.value.strip()
        if not command_text:
            return

        normalized = command_text.lstrip("/").strip()
        if normalized == "setup":
            self.open_setup_screen()
            event.input.value = ""
            self.action_focus_command()
            return

        result = execute_command(self.start_path, command_text)
        self._apply_command_result(result)
        event.input.value = ""
        self.action_focus_command()

    def _apply_command_result(self, result: CommandResult) -> None:
        self.console_state.selected_surface_id = result.selected_surface_id
        self.console_state.record_result(result.command, result.message, result.lines)
        self.refresh_repo_state()

    def open_setup_screen(self) -> None:
        self.push_screen(
            SetupScreen(repo_name=self.start_path.resolve().name),
            self._handle_setup_submission,
        )

    def _maybe_prompt_setup(self) -> None:
        if self.console_state.config_loaded or self._setup_prompted:
            return
        self._setup_prompted = True
        self.open_setup_screen()

    def _handle_setup_submission(self, submission: SetupSubmission | None) -> None:
        if submission is None:
            self.console_state.record_result("setup", "Setup canceled.", ())
            self.refresh_repo_state()
            return
        self.run_setup_submission(submission)

    def run_setup_submission(self, submission: SetupSubmission) -> None:
        try:
            lines = run_setup(
                self.start_path,
                role_name=submission.role_name,
                description=submission.description,
                intent=submission.intent,
                query_paths=(),
                edit_paths=(),
                annotate_query_globs=(),
                annotate_edit_globs=(),
                planner_executor=submission.planner_executor,
                auto_annotate_enabled=submission.auto_annotate_enabled,
                install_github_enabled=submission.install_github_enabled,
                install_slack_enabled=submission.install_slack_enabled,
                slack_webhook_env=submission.slack_webhook_env,
                force_annotations=submission.force_annotations,
            )
        except Exception as exc:
            self.console_state.record_result("setup", f"Setup failed: {exc}", ())
            self.refresh_repo_state()
            return

        self.console_state.record_result("setup", "Setup complete.", lines)
        self.refresh_repo_state()


def _format_surface_list(surfaces) -> str:
    if not surfaces:
        return "No indexed surfaces. Run `/scan`."
    return "\n".join(f"- {surface.id} @ {surface.file}:{surface.line_start}-{surface.line_end}" for surface in surfaces[:12])
