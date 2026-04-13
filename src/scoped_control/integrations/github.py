"""GitHub workflow scaffolding and remote edit event parsing."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(slots=True, frozen=True)
class RemoteEditRequest:
    role_name: str
    request: str
    executor: str | None = None
    top_k: int = 1


@dataclass(slots=True, frozen=True)
class RemoteTriageRequest:
    """A request that has not yet been classified as query vs edit.

    Only `request` is required. `role` is optional and acts as a preference or
    guard rail; triage will reject the run if the named role does not cover
    the targets it infers.
    """

    request: str
    role_name: str | None = None
    executor: str | None = None


def render_github_workflow(*, slack_webhook_env: str = "SLACK_WEBHOOK_URL") -> str:
    """Return a deterministic GitHub Actions workflow with edit + triage dispatch."""

    return f"""name: scoped-control remote edit

on:
  workflow_dispatch:
    inputs:
      role:
        description: Role name from .scoped-control/config.yaml
        required: true
        type: string
      request:
        description: Scoped edit request
        required: true
        type: string
      executor:
        description: Local executor adapter to use
        required: false
        default: fake
        type: choice
        options:
          - fake
          - codex
          - claude_code
      top_k:
        description: Number of edit target surfaces
        required: false
        default: "1"
        type: string

jobs:
  remote-edit:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install scoped-control
        run: |
          python -m pip install --upgrade pip
          pip install .
      - name: Run scoped-control remote edit
        env:
          OPENAI_API_KEY: ${{{{ secrets.OPENAI_API_KEY }}}}
          ANTHROPIC_API_KEY: ${{{{ secrets.ANTHROPIC_API_KEY }}}}
          {slack_webhook_env}: ${{{{ secrets.{slack_webhook_env} }}}}
        run: |
          scoped-control remote-edit --path . --event-file "$GITHUB_EVENT_PATH"
      - name: Show resulting diff
        run: |
          git status --short
          git diff --stat
"""


def render_github_triage_workflow(*, slack_webhook_env: str = "SLACK_WEBHOOK_URL") -> str:
    """Return a workflow that accepts a plain request and auto-triages it.

    The caller does NOT pick read vs edit or the role. Triage classifies the
    request, picks the narrowest covering role, and dispatches to query or
    edit. If no role covers the targets, the run is blocked with a reason.
    """

    return f"""name: scoped-control remote triage

on:
  workflow_dispatch:
    inputs:
      request:
        description: Natural-language request (auto-triaged into query or edit)
        required: true
        type: string
      role:
        description: Optional preferred role name (triage will still check scope)
        required: false
        type: string
      executor:
        description: Executor adapter to use after triage
        required: false
        default: fake
        type: choice
        options:
          - fake
          - codex
          - claude_code

jobs:
  remote-triage:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install scoped-control
        run: |
          python -m pip install --upgrade pip
          pip install .
      - name: Run scoped-control remote triage
        env:
          OPENAI_API_KEY: ${{{{ secrets.OPENAI_API_KEY }}}}
          ANTHROPIC_API_KEY: ${{{{ secrets.ANTHROPIC_API_KEY }}}}
          {slack_webhook_env}: ${{{{ secrets.{slack_webhook_env} }}}}
        run: |
          scoped-control remote-triage --path . --event-file "$GITHUB_EVENT_PATH"
      - name: Show resulting diff
        run: |
          git status --short
          git diff --stat
"""


def load_remote_edit_request(event_path: Path) -> RemoteEditRequest:
    """Load a remote edit request from a GitHub event payload."""

    payload = json.loads(event_path.read_text(encoding="utf-8"))
    inputs = payload.get("inputs") or payload.get("client_payload") or {}

    role_name = inputs.get("role") or inputs.get("role_name")
    request = inputs.get("request")
    if not role_name or not request:
        raise ValueError("GitHub event payload must include `role` and `request` inputs.")

    executor = inputs.get("executor")
    top_k_raw = inputs.get("top_k", 1)
    try:
        top_k = int(top_k_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("GitHub event payload `top_k` must be an integer.") from exc

    return RemoteEditRequest(role_name=role_name, request=request, executor=executor, top_k=top_k)


def load_remote_triage_request(event_path: Path) -> RemoteTriageRequest:
    """Load a remote triage request from a GitHub event payload."""

    payload = json.loads(event_path.read_text(encoding="utf-8"))
    inputs = payload.get("inputs") or payload.get("client_payload") or {}

    request = inputs.get("request")
    if not request:
        raise ValueError("GitHub event payload must include a `request` input for remote triage.")

    role_name = inputs.get("role") or inputs.get("role_name") or None
    if isinstance(role_name, str) and not role_name.strip():
        role_name = None
    executor = inputs.get("executor") or None
    return RemoteTriageRequest(request=request, role_name=role_name, executor=executor)
