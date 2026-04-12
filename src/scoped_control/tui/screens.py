"""Reusable widgets and screens for the Textual shell."""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Static


class SummaryPanel(Static):
    """Simple bordered summary panel."""

    def __init__(self, title: str, body: str = "", **kwargs: object) -> None:
        super().__init__("", **kwargs)
        self.title = title
        self.set_body(body)

    def set_body(self, body: str) -> None:
        text = body.strip() if body.strip() else "Not loaded yet."
        self.update(f"[b]{self.title}[/b]\n{text}")


@dataclass(slots=True, frozen=True)
class SetupSubmission:
    role_name: str
    description: str
    intent: str
    planner_executor: str
    auto_annotate_enabled: bool
    install_github_enabled: bool
    install_slack_enabled: bool
    slack_webhook_env: str
    force_annotations: bool = False
    read_intent: str = ""
    write_intent: str = ""
    semantic_annotations: bool = False


class SetupScreen(ModalScreen[SetupSubmission | None]):
    """Interactive repo bootstrap flow inside the Textual app."""

    CSS = """
    SetupScreen {
      align: center middle;
    }

    #setup-dialog {
      width: 88;
      max-width: 96;
      height: auto;
      border: round $primary;
      background: $surface;
      padding: 1 2;
    }

    .setup-field {
      margin: 0 0 1 0;
    }

    #setup-intro {
      margin: 0 0 1 0;
    }

    #setup-error {
      color: $error;
      margin: 1 0 0 0;
      min-height: 1;
    }

    #setup-actions {
      height: auto;
      margin: 1 0 0 0;
    }
    """

    def __init__(self, *, repo_name: str) -> None:
        super().__init__()
        self.repo_name = repo_name

    def compose(self) -> ComposeResult:
        with Vertical(id="setup-dialog"):
            yield Static(
                "[b]Interactive Setup[/b]\n"
                "Describe the role once. scoped-control will scan the repo, infer scope, annotate files, and build the index.",
                id="setup-intro",
            )
            yield Label("Role name")
            yield Input(value="maintainer", id="setup-role", classes="setup-field")
            yield Label("Description")
            yield Input(
                value=f"Scoped operator for {self.repo_name}.",
                id="setup-description",
                classes="setup-field",
            )
            yield Label("What should this role be allowed to READ?")
            yield Input(
                value=f"Files in {self.repo_name} this role needs to reason about.",
                id="setup-read-intent",
                classes="setup-field",
            )
            yield Label("What should this role be allowed to WRITE / EDIT? (say 'none' for read-only)")
            yield Input(
                value="The narrowest set of files this role may change.",
                id="setup-write-intent",
                classes="setup-field",
            )
            yield Label("Optional single-sentence intent (legacy, overrides the two above if filled)")
            yield Input(
                value="",
                id="setup-intent",
                classes="setup-field",
            )
            yield Label("Planner")
            yield Input(
                value="auto",
                placeholder="auto, codex, claude_code, or heuristic",
                id="setup-planner",
                classes="setup-field",
            )
            yield Checkbox("Auto-annotate matched files", value=True, id="setup-auto-annotate", classes="setup-field")
            yield Checkbox("Semantic annotations (per-function, LLM-placed)", value=False, id="setup-semantic-annotate", classes="setup-field")
            yield Checkbox("Install GitHub workflow", value=False, id="setup-install-github", classes="setup-field")
            yield Checkbox("Enable Slack notifications", value=False, id="setup-install-slack", classes="setup-field")
            yield Label("Slack webhook env var")
            yield Input(value="SLACK_WEBHOOK_URL", id="setup-slack-env", classes="setup-field")
            yield Static("", id="setup-error")
            with Horizontal(id="setup-actions"):
                yield Button("Run setup", id="setup-run", variant="primary")
                yield Button("Cancel", id="setup-cancel")

    def on_mount(self) -> None:
        self.query_one("#setup-role", Input).focus()
        self._sync_slack_env_state()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "setup-install-slack":
            self._sync_slack_env_state()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "setup-cancel":
            self.dismiss(None)
            return
        if event.button.id == "setup-run":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "setup-slack-env":
            self._submit()

    def _submit(self) -> None:
        role_name = self.query_one("#setup-role", Input).value.strip()
        description = self.query_one("#setup-description", Input).value.strip()
        intent = self.query_one("#setup-intent", Input).value.strip()
        read_intent = self.query_one("#setup-read-intent", Input).value.strip()
        write_intent = self.query_one("#setup-write-intent", Input).value.strip()
        planner_executor = self.query_one("#setup-planner", Input).value.strip().lower() or "auto"
        auto_annotate_enabled = self.query_one("#setup-auto-annotate", Checkbox).value
        semantic_annotations = self.query_one("#setup-semantic-annotate", Checkbox).value
        install_github_enabled = self.query_one("#setup-install-github", Checkbox).value
        install_slack_enabled = self.query_one("#setup-install-slack", Checkbox).value
        slack_webhook_env = self.query_one("#setup-slack-env", Input).value.strip() or "SLACK_WEBHOOK_URL"

        if not role_name:
            self._set_error("Role name is required.")
            return
        if not description:
            self._set_error("Description is required.")
            return
        if not intent and not (read_intent or write_intent):
            self._set_error("Provide at least one of: read intent, write intent, or the single-sentence intent.")
            return
        if planner_executor not in {"auto", "codex", "claude_code", "heuristic"}:
            self._set_error("Planner must be one of: auto, codex, claude_code, heuristic.")
            return
        if install_slack_enabled and not slack_webhook_env:
            self._set_error("Slack webhook env var is required when Slack is enabled.")
            return

        self.dismiss(
            SetupSubmission(
                role_name=role_name,
                description=description,
                intent=intent,
                planner_executor=planner_executor,
                auto_annotate_enabled=auto_annotate_enabled,
                install_github_enabled=install_github_enabled,
                install_slack_enabled=install_slack_enabled,
                slack_webhook_env=slack_webhook_env,
                read_intent=read_intent,
                write_intent=write_intent,
                semantic_annotations=semantic_annotations,
            )
        )

    def _set_error(self, message: str) -> None:
        self.query_one("#setup-error", Static).update(message)

    def _sync_slack_env_state(self) -> None:
        slack_enabled = self.query_one("#setup-install-slack", Checkbox).value
        slack_env = self.query_one("#setup-slack-env", Input)
        slack_env.disabled = not slack_enabled
