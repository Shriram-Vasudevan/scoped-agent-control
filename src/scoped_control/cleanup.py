"""Cleanup helpers for scoped-control-managed repo artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

import yaml

from scoped_control.annotations.inserter import remove_auto_annotations
from scoped_control.config.loader import repo_paths
from scoped_control.models import GitHubIntegrationConfig


@dataclass(slots=True, frozen=True)
class RepoCleanupResult:
    root: Path
    annotation_files: tuple[str, ...]
    annotation_blocks_removed: int
    removed_files: tuple[str, ...]
    removed_directories: tuple[str, ...]
    warnings: tuple[str, ...]


def cleanup_repo(repo_path: Path, *, dry_run: bool = False) -> RepoCleanupResult:
    """Remove scoped-control-managed annotations and repo scaffolding."""

    paths = repo_paths(repo_path)
    annotation_result = remove_auto_annotations(paths.root, dry_run=dry_run)

    removed_files: list[str] = []
    removed_directories: list[str] = []
    warnings: list[str] = list(annotation_result.warnings)

    for workflow_path in _workflow_candidates(paths.config_path):
        workflow_file = _resolve_repo_relative_path(paths.root, workflow_path)
        if workflow_file is None:
            warnings.append(f"Skipped workflow path outside repo root: {workflow_path}")
            continue
        if not workflow_file.exists():
            continue
        if not dry_run:
            workflow_file.unlink()
            _prune_empty_parents(workflow_file.parent, stop=paths.root)
        removed_files.append(workflow_file.relative_to(paths.root).as_posix())

    if paths.control_dir.exists():
        if not dry_run:
            shutil.rmtree(paths.control_dir)
        removed_directories.append(f"{paths.control_dir.relative_to(paths.root).as_posix()}/")

    return RepoCleanupResult(
        root=paths.root,
        annotation_files=annotation_result.cleaned_files,
        annotation_blocks_removed=annotation_result.removed_blocks,
        removed_files=tuple(removed_files),
        removed_directories=tuple(removed_directories),
        warnings=tuple(warnings),
    )


def _workflow_candidates(config_path: Path) -> tuple[str, ...]:
    candidates = [GitHubIntegrationConfig().workflow_path]
    if not config_path.exists():
        return tuple(candidates)

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return tuple(candidates)

    if not isinstance(raw, dict):
        return tuple(candidates)

    integrations = raw.get("integrations")
    if not isinstance(integrations, dict):
        return tuple(candidates)

    github = integrations.get("github")
    if not isinstance(github, dict):
        return tuple(candidates)

    workflow_path = github.get("workflow_path")
    if isinstance(workflow_path, str) and workflow_path.strip():
        candidates.append(workflow_path.strip())
    return tuple(dict.fromkeys(candidates))


def _resolve_repo_relative_path(root: Path, raw_path: str) -> Path | None:
    candidate = (root / raw_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _prune_empty_parents(path: Path, *, stop: Path) -> None:
    current = path
    while current != stop and current.exists():
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent
