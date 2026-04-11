"""Config and repo discovery helpers."""

from __future__ import annotations

from pathlib import Path

import yaml

from scoped_control.config.schema import build_default_config, load_config_model
from scoped_control.errors import ConfigValidationError, RepoNotInitializedError
from scoped_control.index.store import empty_index, write_index
from scoped_control.models import AppConfig, CheckReport, RepoContext, RepoPaths
from scoped_control.config.mutator import write_config

CONTROL_DIR_NAME = ".scoped-control"
CONFIG_FILE_NAME = "config.yaml"
INDEX_FILE_NAME = "index.json"


def discover_repo_root(start: Path | None = None) -> Path:
    """Find the nearest repo root by looking for control files or git metadata."""

    current = (start or Path.cwd()).resolve()
    candidates = (current, *current.parents)
    for candidate in candidates:
        if (candidate / CONTROL_DIR_NAME).exists() or (candidate / ".git").exists():
            return candidate
    return current


def repo_paths(start: Path | None = None) -> RepoPaths:
    root = discover_repo_root(start)
    control_dir = root / CONTROL_DIR_NAME
    return RepoPaths(
        root=root,
        control_dir=control_dir,
        config_path=control_dir / CONFIG_FILE_NAME,
        index_path=control_dir / INDEX_FILE_NAME,
    )


def bootstrap_repo(root: Path | None = None, *, overwrite: bool = False) -> RepoPaths:
    """Create the v1 config and empty index."""

    target_root = (root or Path.cwd()).resolve()
    paths = repo_paths(target_root)
    paths.control_dir.mkdir(parents=True, exist_ok=True)

    if overwrite or not paths.config_path.exists():
        write_config(build_default_config(), paths.config_path)

    if overwrite or not paths.index_path.exists():
        write_index(empty_index(paths.root), paths.index_path)

    return paths


def load_config(start: Path | None = None) -> tuple[RepoPaths, AppConfig]:
    """Load config from the current repo."""

    paths = repo_paths(start)
    if not paths.config_path.exists():
        raise RepoNotInitializedError(
            f"Missing {paths.config_path}. Run `scoped-control init` from the repo root first."
        )

    raw = yaml.safe_load(paths.config_path.read_text(encoding="utf-8"))
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigValidationError("config root must be a mapping", field="root")
    return paths, load_config_model(raw)


def load_repo_context(start: Path | None = None, *, require_config: bool = False) -> RepoContext:
    """Load repo context for the TUI and commands."""

    paths = repo_paths(start)
    try:
        _, config = load_config(paths.root)
        return RepoContext(paths=paths, config=config)
    except (RepoNotInitializedError, ConfigValidationError) as exc:
        if require_config:
            raise
        return RepoContext(paths=paths, config=None, config_error=str(exc))


def check_repo(start: Path | None = None) -> CheckReport:
    """Validate that the repo is initialized and the config can be loaded."""

    paths = repo_paths(start)
    try:
        load_config(paths.root)
    except (RepoNotInitializedError, ConfigValidationError) as exc:
        return CheckReport(ok=False, repo_root=paths.root, config_path=paths.config_path, errors=(str(exc),))
    return CheckReport(ok=True, repo_root=paths.root, config_path=paths.config_path)
