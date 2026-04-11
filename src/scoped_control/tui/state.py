"""Mutable app state used by the Textual shell."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from scoped_control.models import RoleConfig, SurfaceRecord, ValidatorConfig


@dataclass(slots=True)
class ConsoleState:
    repo_root: Path
    config_path: Path
    index_path: Path
    config_loaded: bool
    config_error: str | None = None
    roles: tuple[RoleConfig, ...] = ()
    validators: tuple[ValidatorConfig, ...] = ()
    surfaces: tuple[SurfaceRecord, ...] = ()
    selected_surface_id: str | None = None
    requests: list[str] = field(default_factory=list)
    results: list[str] = field(default_factory=list)

    def record_result(self, command: str, message: str, lines: tuple[str, ...]) -> None:
        self.requests.append(command)
        self.requests = self.requests[-10:]
        self.results.extend((message, *lines))
        self.results = self.results[-24:]


__all__ = ["ConsoleState"]
