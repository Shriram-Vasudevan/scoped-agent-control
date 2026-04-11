"""Scoped temporary workspaces for executor runs."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import tempfile

from scoped_control.models import ExecutionBrief


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
