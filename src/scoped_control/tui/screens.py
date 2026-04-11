"""Reusable widgets for the Textual shell."""

from __future__ import annotations

from textual.widgets import Static


class SummaryPanel(Static):
    """Simple bordered summary panel."""

    def __init__(self, title: str, body: str = "", **kwargs: object) -> None:
        super().__init__("", **kwargs)
        self.title = title
        self.set_body(body)

    def set_body(self, body: str) -> None:
        text = body.strip() if body.strip() else "Not loaded yet."
        self.update(f"[b]{self.title}[/b]\n{text}")
