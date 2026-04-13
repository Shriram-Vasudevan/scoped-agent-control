"""Textual application shell — conversational chat-style UI.

Layout is intentionally simple: one scrolling log for everything the system
says, one input pinned to the bottom for everything the user types. No
dashboard, no grid, no stacked screens. Every interaction flows through the
same input and appears in the same scroll.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Input, RichLog

from scoped_control.config.loader import bootstrap_repo, load_repo_context
from scoped_control.setup_flow import run_setup
from scoped_control.tui.commands import CommandResult, execute_command


WIZARD_QUESTIONS = (
    (
        "Role name",
        "Short name. Examples: maintainer, docs-writer, recruiter, test-author.",
        "maintainer",
    ),
    (
        "Describe this role in one line",
        "What does this person or agent actually do?",
        "",  # filled in at runtime with repo name
    ),
    (
        "What should this role be allowed to READ?",
        "Plain English. e.g. 'the careers page and hiring docs'. 'everything' is valid.",
        "everything",
    ),
    (
        "What should this role be allowed to WRITE / EDIT?",
        "Plain English. Say 'none' for read-only, or name the narrowest set of files.",
        "none",
    ),
)


class ScopedControlApp(App[None]):
    """Conversational TUI for scoped-control.

    Mode is either `wizard` (collecting answers one question at a time) or
    `idle` (accepting slash commands). Either way, every submission goes to
    the same Input widget and renders into the same RichLog scroll.
    """

    CSS = """
    Screen {
      layout: vertical;
      background: $surface;
    }

    #log {
      height: 1fr;
      padding: 1 2;
      background: $surface;
      border: none;
    }

    #input {
      height: 3;
      margin: 0 2 1 2;
      border: round $primary;
    }

    #input:focus {
      border: round $accent;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("ctrl+d", "quit", "Quit", show=False),
    ]

    def __init__(self, *, start_path: Path | None = None) -> None:
        super().__init__()
        self.start_path = (start_path or Path.cwd()).resolve()
        self._mode: str = "idle"
        self._wizard_step: int = 0
        self._wizard_answers: list[str] = []
        self._last_role_name: str | None = None

    # ------------------------------------------------------------------
    # Layout

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield RichLog(id="log", wrap=True, markup=True, auto_scroll=True)
        yield Input(id="input", placeholder="Type a message and press Enter")
        yield Footer()

    async def on_mount(self) -> None:
        self.title = "scoped-control"
        self.sub_title = str(self.start_path)
        log = self.query_one("#log", RichLog)

        log.write("[bold]scoped-control[/bold]  [dim]— scoped AI query/edit operations[/dim]")
        log.write("")

        if self._repo_is_initialized():
            log.write(f"Repo: [dim]{self.start_path}[/dim]")
            log.write("This repo is already initialized.")
            log.write(
                "Try [b]/role list[/b], [b]/surface list[/b], or [b]/setup[/b] to add another role."
            )
            log.write("")
            self.query_one("#input", Input).placeholder = (
                "/role list   /surface list   /setup   /query <role> <request>"
            )
        else:
            log.write(f"Repo: [dim]{self.start_path}[/dim]")
            log.write("This repo isn't set up yet. Let's add your first role.")
            log.write("")
            self._start_wizard()

        self.query_one("#input", Input).focus()

    # ------------------------------------------------------------------
    # Wizard

    def _start_wizard(self) -> None:
        try:
            bootstrap_repo(self.start_path, overwrite=False)
        except Exception as exc:  # noqa: BLE001
            self._say(f"[red]Could not initialize the repo: {exc}[/red]")
            return
        self._mode = "wizard"
        self._wizard_step = 0
        self._wizard_answers = []
        self._say("[bold]Adding a role.[/bold] I'll ask 4 quick questions. Type /cancel to abort.")
        self._say("")
        self._ask_wizard_question()

    def _ask_wizard_question(self) -> None:
        label, hint, default = WIZARD_QUESTIONS[self._wizard_step]
        if self._wizard_step == 1 and not default:
            default = f"Scoped operator for {self.start_path.name}"

        self._say(f"[bold cyan]Step {self._wizard_step + 1} of {len(WIZARD_QUESTIONS)}[/bold cyan]  [bold]{label}[/bold]")
        self._say(f"  [dim]{hint}[/dim]")
        if default:
            self._say(f"  [dim]Press Enter to use:[/dim] {default}")
        self._say("")
        inp = self.query_one("#input", Input)
        inp.value = ""
        inp.placeholder = default or "Type your answer and press Enter"
        inp.focus()

    async def _run_wizard(self) -> None:
        defaults: list[str] = []
        for index, (_, _, default) in enumerate(WIZARD_QUESTIONS):
            if index == 1 and not default:
                defaults.append(f"Scoped operator for {self.start_path.name}")
            else:
                defaults.append(default)

        resolved: list[str] = []
        for index, answer in enumerate(self._wizard_answers):
            stripped = answer.strip()
            resolved.append(stripped or defaults[index])
        role_name, description, read_intent, write_intent = resolved

        self._say(f"[dim]Planning scope for `{role_name}`...[/dim]")
        try:
            lines = await asyncio.to_thread(
                run_setup,
                self.start_path,
                role_name=role_name,
                description=description,
                intent=None,
                read_intent=read_intent,
                write_intent=write_intent,
                query_paths=(),
                edit_paths=(),
                annotate_query_globs=(),
                annotate_edit_globs=(),
                planner_executor="auto",
                auto_annotate_enabled=False,
                install_github_enabled=False,
                install_slack_enabled=False,
                slack_webhook_env="SLACK_WEBHOOK_URL",
                force_annotations=False,
                semantic_annotations=False,
            )
        except Exception as exc:  # noqa: BLE001
            self._say(f"[red]Setup failed:[/red] {exc}")
            self._say("")
            self._mode = "idle"
            self.query_one("#input", Input).placeholder = "Type /setup to try again"
            return

        self._say(f"[green]✓ Role `{role_name}` created.[/green]")
        for line in lines:
            self._say(f"  [dim]·[/dim] {line}")
        self._say("")
        self._say(
            f"[dim]Next:[/dim] /role list  ·  /surface list  ·  /query {role_name} <question>  ·  /setup to add another role"
        )
        self._say("")

        self._mode = "idle"
        self._last_role_name = role_name
        self.query_one("#input", Input).placeholder = (
            f"/query {role_name} <question>   /surface list   /setup"
        )

    # ------------------------------------------------------------------
    # Input dispatch

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "input":
            return
        text = event.value
        event.input.value = ""

        if self._mode == "wizard":
            await self._handle_wizard_submit(text)
            self.query_one("#input", Input).focus()
            return

        await self._handle_idle_submit(text)
        self.query_one("#input", Input).focus()

    async def _handle_wizard_submit(self, text: str) -> None:
        stripped = text.strip()
        # Echo what the user picked (show default explicitly if empty).
        label, _, default = WIZARD_QUESTIONS[self._wizard_step]
        if self._wizard_step == 1 and not default:
            default = f"Scoped operator for {self.start_path.name}"
        shown = stripped or f"{default}  [dim](default)[/dim]"
        self._say(f"  [cyan]›[/cyan] {shown}")
        self._say("")

        if stripped.lower() in {"/cancel", "cancel", "/abort", "abort"}:
            self._mode = "idle"
            self._say("[yellow]Setup canceled.[/yellow]")
            self._say("")
            self.query_one("#input", Input).placeholder = "Type /setup to begin"
            return

        self._wizard_answers.append(text)
        self._wizard_step += 1

        if self._wizard_step >= len(WIZARD_QUESTIONS):
            await self._run_wizard()
        else:
            self._ask_wizard_question()

    async def _handle_idle_submit(self, text: str) -> None:
        stripped = text.strip()
        if not stripped:
            return

        self._say(f"[b]›[/b] {stripped}")

        normalized = stripped.lstrip("/").strip().lower()
        if normalized in {"setup", "init"}:
            self._start_wizard()
            return
        if normalized in {"quit", "exit"}:
            self.exit()
            return
        if normalized in {"help", "?"}:
            self._show_help()
            return
        if normalized in {"clear", "cls"}:
            self.query_one("#log", RichLog).clear()
            return

        # Delegate to the shared command parser/executor.
        try:
            result: CommandResult = execute_command(self.start_path, stripped)
        except Exception as exc:  # noqa: BLE001
            self._say(f"[red]Command failed:[/red] {exc}")
            self._say("")
            return

        color = "green" if result.ok else "red"
        if result.message:
            self._say(f"[{color}]{result.message}[/{color}]")
        for line in result.lines:
            self._say(f"  {line}")
        self._say("")

    def _show_help(self) -> None:
        self._say("[bold]Slash commands[/bold]")
        self._say("  [b]/setup[/b]              Add or update a role (guided)")
        self._say("  [b]/role list[/b]          List configured roles")
        self._say("  [b]/surface list[/b]       List indexed surfaces")
        self._say("  [b]/query ROLE REQ[/b]     Scoped read query")
        self._say("  [b]/edit ROLE REQ[/b]      Scoped edit with enforcement")
        self._say("  [b]/scan[/b]               Rebuild the surface index")
        self._say("  [b]/cleanup --force[/b]    Remove all scoped-control artifacts")
        self._say("  [b]/clear[/b]              Clear the log")
        self._say("  [b]/quit[/b]               Exit")
        self._say("")

    # ------------------------------------------------------------------
    # Helpers

    def _say(self, markup: str) -> None:
        self.query_one("#log", RichLog).write(markup)

    def _repo_is_initialized(self) -> bool:
        try:
            context = load_repo_context(self.start_path, require_config=False)
        except Exception:
            return False
        return context.config is not None
