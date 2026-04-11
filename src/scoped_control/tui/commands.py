"""Shared command result models for CLI and TUI flows."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class CommandResult:
    command: str
    ok: bool
    message: str
