"""Validator execution for edit runs."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scoped_control.models import AppConfig, ValidationResult


def run_validators(config: AppConfig, workspace: Path, *, mode: str) -> tuple[ValidationResult, ...]:
    """Run configured validators for a given mode."""

    results: list[ValidationResult] = []
    for validator in config.validators:
        if mode not in validator.modes:
            continue
        completed = subprocess.run(
            validator.command,
            shell=True,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=validator.timeout_seconds,
            check=False,
        )
        output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part).strip()
        results.append(
            ValidationResult(
                name=validator.name,
                ok=completed.returncode == 0,
                command=validator.command,
                output=output,
            )
        )
    return tuple(results)
