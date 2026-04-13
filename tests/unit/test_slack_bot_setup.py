"""Unit tests for the guided Slack bot setup."""

from __future__ import annotations

import io

from scoped_control.integrations.slack_bot import (
    guided_setup,
    render_manifest,
    render_team_announcement,
    run_smoke_test,
)
from scoped_control.integrations.tunnel import (
    CLOUDFLARED_URL_RE,
    MissingTunnelToolError,
    TunnelHandle,
)


def test_render_manifest_includes_url_and_repo_name() -> None:
    manifest = render_manifest("https://example.trycloudflare.com", "my-repo")
    assert "https://example.trycloudflare.com/" in manifest
    assert "my-repo" in manifest
    assert "slash_commands:" in manifest
    assert "command: /scoped" in manifest
    assert "commands" in manifest and "chat:write" in manifest


def test_render_team_announcement_contains_examples_and_repo_name() -> None:
    body = render_team_announcement("my-repo")
    assert "/scoped" in body
    assert "my-repo" in body
    assert "blocked" in body.lower() or "blocks" in body.lower()


def test_cloudflared_url_regex_matches_expected_format() -> None:
    line = "2024-01-01T00:00:00Z INF Your quick tunnel is https://abc-def.trycloudflare.com"
    match = CLOUDFLARED_URL_RE.search(line)
    assert match is not None
    assert match.group(0) == "https://abc-def.trycloudflare.com"


def test_guided_setup_aborts_when_no_tunnel_tool(tmp_path, capsys) -> None:
    def no_tool(_port: int) -> TunnelHandle:  # pragma: no cover - inlined
        raise MissingTunnelToolError("install something")

    rc = guided_setup(
        tmp_path,
        port=8787,
        in_stream=io.StringIO(""),
        out_stream=io.StringIO(),
        tunnel_starter=no_tool,
        block_until_interrupted=False,
    )
    assert rc == 1


def test_guided_setup_aborts_when_secret_is_blank(tmp_path, monkeypatch) -> None:
    class _FakeProc:
        def terminate(self) -> None:
            pass

        def wait(self, timeout: float = 0) -> int:
            return 0

        def kill(self) -> None:
            pass

    handle = TunnelHandle(
        public_url="https://example.trycloudflare.com",
        tool="cloudflared",
        process=_FakeProc(),  # type: ignore[arg-type]
    )

    output = io.StringIO()
    rc = guided_setup(
        tmp_path,
        port=8787,
        in_stream=io.StringIO("\n"),
        out_stream=output,
        tunnel_starter=lambda _port: handle,
        signing_secret_reader=lambda _s: "",
        block_until_interrupted=False,
    )
    assert rc == 1
    text = output.getvalue()
    assert "No secret entered" in text


def test_smoke_test_returns_failure_when_url_unreachable() -> None:
    # Port 1 is reserved and should refuse connection.
    result = run_smoke_test("http://127.0.0.1:1", "whatever", timeout_seconds=1.0)
    assert result.ok is False
    assert "could not reach" in result.message or "HTTP" in result.message
