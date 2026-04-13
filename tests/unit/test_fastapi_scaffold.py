"""Unit tests for the FastAPI Slack-bridge scaffolder."""

from __future__ import annotations

import ast
from pathlib import Path

from scoped_control.integrations.fastapi_scaffold import install_fastapi


def test_scaffold_writes_importable_module(tmp_path: Path) -> None:
    result = install_fastapi(tmp_path / "routers")
    assert result.bridge_path.exists()
    assert result.bridge_path.name == "scoped_slack_bridge.py"
    # The generated module must parse as valid Python — no template artifacts.
    ast.parse(result.bridge_path.read_text(encoding="utf-8"))


def test_scaffold_instructions_mention_install_and_env_vars(tmp_path: Path) -> None:
    result = install_fastapi(tmp_path / "routers")
    instructions = result.instructions
    assert "app.include_router(scoped_slack_router)" in instructions
    assert "ANTHROPIC_API_KEY" in instructions
    assert "GITHUB_TOKEN" in instructions
    assert "SLACK_SIGNING_SECRET" in instructions
    assert "scoped-agent-control" in instructions


def test_scaffold_respects_custom_module_name(tmp_path: Path) -> None:
    result = install_fastapi(tmp_path / "routers", module_name="my_slack_route")
    assert result.bridge_path.name == "my_slack_route.py"
    assert "from .my_slack_route import router" in result.instructions


def test_scaffolded_module_imports_expected_symbols(tmp_path: Path) -> None:
    result = install_fastapi(tmp_path / "routers")
    source = result.bridge_path.read_text(encoding="utf-8")
    assert "router = APIRouter" in source
    assert "handle_slack_event" in source
    assert "_dispatch_app_mention" in source
    assert "_verify_slack_signature" in source
    assert "open_pr_for_changes" in source
    # Ensure the scoped-control API is what the bridge calls into.
    assert "from scoped_control.api import handle_request" in source
