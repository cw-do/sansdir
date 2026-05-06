"""Bottom status bar.

Two zones, both single-line:

* **Left** — cwd of the active pane and a file count.
* **Right** — free disk space on the active pane's filesystem.

Updated by the app whenever the active pane changes or its listing refreshes.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Label

from sansdir.core.filesystem import format_size, free_disk_bytes


class StatusBar(Horizontal):
    """A 1-line status bar at the bottom of the app."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $surface;
        color: $text;
    }
    StatusBar > .left {
        width: 1fr;
        content-align: left middle;
        padding: 0 1;
    }
    StatusBar > .right {
        width: auto;
        content-align: right middle;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._left = Label("", classes="left")
        self._right = Label("", classes="right")

    def compose(self) -> ComposeResult:
        yield self._left
        yield self._right

    def update_for(
        self,
        cwd: Path,
        file_count: int,
        *,
        filter_substring: str = "",
    ) -> None:
        if filter_substring:
            self._left.update(
                f"{cwd}  ({file_count} entries · [b yellow]filter:[/] [b]{filter_substring}[/])"
            )
        else:
            self._left.update(f"{cwd}  ({file_count} entries)")
        self._right.update(f"free: {format_size(free_disk_bytes(cwd))}")
