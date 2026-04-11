"""Scoped temporary workspaces for executor runs."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os
import shutil
import stat
import subprocess
import tempfile

from scoped_control.models import ExecutionBrief


class PreparedEditWorkspace:
    """Prepared sandbox workspace for an edit run."""

    def __init__(self, root: Path, strategy: str) -> None:
        self.root = root
        self.strategy = strategy


@contextmanager
def prepare_query_workspace(brief: ExecutionBrief):
    """Materialize only the scoped context in a temporary directory."""

    with tempfile.TemporaryDirectory(prefix="scoped-control-query-") as temp_dir:
        workspace = Path(temp_dir)
        for context in brief.file_contexts:
            target_path = workspace / context.path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(context.excerpt + "\n", encoding="utf-8")
        yield workspace


@contextmanager
def prepare_edit_workspace(root: Path, writable_files: tuple[str, ...]):
    """Create a temporary edit workspace using a worktree when safe, otherwise a copy."""

    if _can_use_git_worktree(root):
        with _git_worktree(root) as workspace:
            _apply_writable_file_permissions(workspace, writable_files)
            yield PreparedEditWorkspace(workspace, "git-worktree")
    else:
        with _copied_workspace(root) as workspace:
            _apply_writable_file_permissions(workspace, writable_files)
            yield PreparedEditWorkspace(workspace, "temp-copy")


def _can_use_git_worktree(root: Path) -> bool:
    git_dir = root / ".git"
    if not git_dir.exists():
        return False
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    return status.returncode == 0 and not status.stdout.strip()


@contextmanager
def _git_worktree(root: Path):
    with tempfile.TemporaryDirectory(prefix="scoped-control-edit-") as temp_dir:
        workspace = Path(temp_dir) / "worktree"
        added = subprocess.run(
            ["git", "-C", str(root), "worktree", "add", "--detach", str(workspace), "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if added.returncode != 0:
            raise RuntimeError(added.stderr.strip() or "Unable to create git worktree.")
        try:
            yield workspace
        finally:
            subprocess.run(
                ["git", "-C", str(root), "worktree", "remove", "--force", str(workspace)],
                capture_output=True,
                text=True,
                check=False,
            )


@contextmanager
def _copied_workspace(root: Path):
    with tempfile.TemporaryDirectory(prefix="scoped-control-edit-") as temp_dir:
        workspace = Path(temp_dir) / "workspace"
        shutil.copytree(root, workspace, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache"))
        yield workspace


def _apply_writable_file_permissions(workspace: Path, writable_files: tuple[str, ...]) -> None:
    writable = set(writable_files)
    for file_path in workspace.rglob("*"):
        if not file_path.is_file():
            continue
        relative = file_path.relative_to(workspace).as_posix()
        mode = file_path.stat().st_mode
        if relative in writable:
            file_path.chmod(mode | stat.S_IWUSR)
        else:
            file_path.chmod(mode & ~stat.S_IWUSR)
