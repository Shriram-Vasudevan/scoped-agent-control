"""Textual application shell."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid
from textual.widgets import Footer, Header, Static

from scoped_control.config.loader import load_repo_context
from scoped_control.models import AppState
from scoped_control.tui.screens import SummaryPanel


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
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
    ]

    def __init__(self, *, start_path: Path | None = None) -> None:
        super().__init__()
        self.start_path = start_path or Path.cwd()
        self.app_state = AppState(
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
        yield Footer()

    def on_mount(self) -> None:
        context = load_repo_context(self.start_path, require_config=False)
        self.app_state = AppState(
            repo_root=context.paths.root,
            config_path=context.paths.config_path,
            index_path=context.paths.index_path,
            config_loaded=context.config is not None,
            config_error=context.config_error,
        )
        self._refresh_panels(context)

    def _refresh_panels(self, context) -> None:
        roles_panel = self.query_one("#roles", SummaryPanel)
        surfaces_panel = self.query_one("#surfaces", SummaryPanel)
        validators_panel = self.query_one("#validators", SummaryPanel)
        requests_panel = self.query_one("#requests", SummaryPanel)
        logs_panel = self.query_one("#logs", SummaryPanel)
        status = self.query_one("#status", Static)

        if context.config is None:
            roles_panel.set_body("No config loaded yet.")
            validators_panel.set_body("Validators are unavailable until the repo is initialized.")
            surfaces_panel.set_body("Surface index will appear after scan/index commands land.")
            requests_panel.set_body("Scoped query/edit flows arrive in later waves.")
            logs_panel.set_body(context.config_error or "Run `scoped-control init` to bootstrap this repo.")
            status.update(
                f"[b]Repo[/b]\n{context.paths.root}\n\n[b]Status[/b]\n{context.config_error or 'Not initialized'}"
            )
            return

        roles_panel.set_body("\n".join(f"- {role.name}: {role.description}" for role in context.config.roles))
        validators_panel.set_body(
            "\n".join(f"- {validator.name}: {validator.command}" for validator in context.config.validators)
            or "No validators configured."
        )
        surfaces_panel.set_body(f"Index path: {context.paths.index_path}\nSurface loading arrives in Wave 2.")
        requests_panel.set_body("Slash-command dispatch and executor runs arrive in later waves.")
        logs_panel.set_body("App shell is live. Use `q` to quit.")
        status.update(
            f"[b]Repo[/b]\n{context.paths.root}\n\n[b]Config[/b]\n{context.paths.config_path}\n\n[b]Index[/b]\n{context.paths.index_path}"
        )
