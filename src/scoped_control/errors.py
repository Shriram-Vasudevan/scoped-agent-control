"""Project error types."""

from __future__ import annotations


class ScopedControlError(Exception):
    """Base error for the control plane."""


class RepoNotInitializedError(ScopedControlError):
    """Raised when a repo has not been initialized."""


class ConfigValidationError(ScopedControlError):
    """Raised when config.yaml is malformed."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class CommandExecutionError(ScopedControlError):
    """Raised when a user-facing command fails."""
