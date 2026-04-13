"""Commit, push, and open a PR for any working-tree changes.

Thin wrapper around `git` and `gh`. Both must be on PATH and authenticated
(the GitHub CLI uses `GITHUB_TOKEN` or a stored login).

Typical use: after `scoped_control.api.handle_request` returns a successful
edit, call `open_pr_for_changes(repo_path, title=...)` to turn the sandbox
result into a reviewable PR.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PullRequestResult:
    ok: bool
    url: str | None
    branch: str | None
    error: str | None


_BRANCH_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def open_pr_for_changes(
    repo_path: Path,
    *,
    title: str,
    body: str = "",
    branch_prefix: str = "scoped-control/",
    base_branch: str = "main",
    git_user_name: str = "scoped-control-bot",
    git_user_email: str = "scoped-control-bot@localhost",
    slug_hint: str | None = None,
) -> PullRequestResult:
    """Turn working-tree changes into a PR.

    Steps:
      1. Bail out if there are no changes.
      2. Configure git user.name / user.email locally for this repo.
      3. Checkout a new branch named `<branch_prefix><slug><timestamp>`.
      4. Add + commit all changes under `title`.
      5. Push with `-u origin`.
      6. `gh pr create` and capture the URL.

    Returns a PullRequestResult. `ok=False` means either there were no
    changes, git failed, or gh failed — the `error` field carries stderr/
    stdout from whichever step failed.
    """

    def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            list(args),
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=check,
        )

    try:
        status = run("git", "status", "--porcelain", check=False)
    except FileNotFoundError:
        return PullRequestResult(ok=False, url=None, branch=None, error="git not installed")
    if status.returncode != 0:
        return PullRequestResult(
            ok=False,
            url=None,
            branch=None,
            error=(status.stderr or status.stdout).strip() or "git status failed",
        )
    if not status.stdout.strip():
        return PullRequestResult(ok=False, url=None, branch=None, error="no changes to commit")

    slug = _slugify(slug_hint or title, max_len=40)
    branch = f"{branch_prefix}{slug}-{int(time.time())}" if slug else f"{branch_prefix}{int(time.time())}"

    try:
        run("git", "config", "user.name", git_user_name)
        run("git", "config", "user.email", git_user_email)
        run("git", "checkout", "-b", branch)
        run("git", "add", "-A")
        run("git", "commit", "-m", title)
        run("git", "push", "-u", "origin", branch)
        pr = run(
            "gh",
            "pr",
            "create",
            "--base",
            base_branch,
            "--head",
            branch,
            "--title",
            title,
            "--body",
            body,
        )
    except FileNotFoundError as exc:
        return PullRequestResult(
            ok=False, url=None, branch=branch, error=f"missing binary: {exc.filename}"
        )
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout or str(exc)).strip()
        return PullRequestResult(ok=False, url=None, branch=branch, error=message)

    url = _extract_pr_url(pr.stdout)
    return PullRequestResult(ok=True, url=url, branch=branch, error=None)


def _slugify(text: str, *, max_len: int) -> str:
    slug = _BRANCH_SLUG_RE.sub("-", text.lower()).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug


def _extract_pr_url(gh_output: str) -> str | None:
    for token in gh_output.split():
        if token.startswith("https://github.com/") and "/pull/" in token:
            return token
    return None


__all__ = ["PullRequestResult", "open_pr_for_changes"]
