"""Launch a public HTTPS tunnel to a local port, returning the public URL.

Prefers `cloudflared` (free, no account needed for quick tunnels). Falls back
to `ngrok` if cloudflared is missing but ngrok is installed. If neither is
available, raises `MissingTunnelToolError` with install instructions.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import shutil
import subprocess
import threading
import time
from urllib.request import urlopen


CLOUDFLARED_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


class MissingTunnelToolError(RuntimeError):
    """Raised when no supported tunnel tool is installed."""


@dataclass(slots=True)
class TunnelHandle:
    public_url: str
    tool: str
    process: subprocess.Popen


def detect_tunnel_tool() -> str | None:
    if shutil.which("cloudflared"):
        return "cloudflared"
    if shutil.which("ngrok"):
        return "ngrok"
    return None


def start_tunnel(port: int, *, timeout_seconds: float = 30.0) -> TunnelHandle:
    """Start a tunnel to 127.0.0.1:<port> and wait for the public URL.

    Raises MissingTunnelToolError if neither cloudflared nor ngrok is present.
    Raises RuntimeError if the tool exits or times out before a URL appears.
    """

    tool = detect_tunnel_tool()
    if tool is None:
        raise MissingTunnelToolError(_install_message())
    if tool == "cloudflared":
        return _start_cloudflared(port, timeout_seconds)
    return _start_ngrok(port, timeout_seconds)


def stop_tunnel(handle: TunnelHandle) -> None:
    handle.process.terminate()
    try:
        handle.process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        handle.process.kill()


# ---------------------------------------------------------------------------
# Cloudflared


def _start_cloudflared(port: int, timeout_seconds: float) -> TunnelHandle:
    proc = subprocess.Popen(  # noqa: S603
        ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    url_holder: dict[str, str] = {}

    def _read_until_url() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            match = CLOUDFLARED_URL_RE.search(line)
            if match:
                url_holder["url"] = match.group(0)
                return

    reader = threading.Thread(target=_read_until_url, daemon=True)
    reader.start()
    reader.join(timeout=timeout_seconds)

    url = url_holder.get("url")
    if not url:
        proc.terminate()
        raise RuntimeError(
            "cloudflared did not return a public URL in time. "
            "Run `cloudflared tunnel --url http://127.0.0.1:<port>` manually to diagnose."
        )
    return TunnelHandle(public_url=url, tool="cloudflared", process=proc)


# ---------------------------------------------------------------------------
# Ngrok


def _start_ngrok(port: int, timeout_seconds: float) -> TunnelHandle:
    proc = subprocess.Popen(  # noqa: S603
        ["ngrok", "http", str(port), "--log", "stdout", "--log-format", "json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    deadline = time.monotonic() + timeout_seconds
    public_url: str | None = None
    while time.monotonic() < deadline:
        try:
            response = urlopen("http://127.0.0.1:4040/api/tunnels", timeout=2)  # noqa: S310
            payload = json.loads(response.read())
            for tunnel in payload.get("tunnels", []):
                candidate = tunnel.get("public_url", "")
                if candidate.startswith("https://"):
                    public_url = candidate
                    break
            if public_url:
                break
        except Exception:  # noqa: BLE001
            time.sleep(0.4)
    if not public_url:
        proc.terminate()
        raise RuntimeError(
            "ngrok did not expose a tunnel in time. "
            "Check that `ngrok config add-authtoken <token>` has been run."
        )
    return TunnelHandle(public_url=public_url, tool="ngrok", process=proc)


# ---------------------------------------------------------------------------
# Install hint


def _install_message() -> str:
    return (
        "No tunnel tool was found on PATH. Install one of these and re-run:\n\n"
        "  cloudflared (recommended — free, no account needed):\n"
        "    macOS:  brew install cloudflared\n"
        "    Linux:  https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/\n"
        "    Windows: winget install --id Cloudflare.cloudflared\n\n"
        "  ngrok (alternative; requires a free account):\n"
        "    https://ngrok.com/download\n"
        "    Then: ngrok config add-authtoken <your-token>\n"
    )
