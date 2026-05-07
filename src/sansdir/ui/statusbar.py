"""Bottom status bar.

The cwd lives in the top :class:`~sansdir.ui.pathbar.PathBar` since
v0.0.2, so this row is the "what state am I in?" line — three zones,
all single-line, updated by the App whenever the active pane
refreshes or the catalog state changes:

* **Left** — selection / filter for the active pane (``N entries · M
  tagged · filter: …``).
* **Middle** — run catalog summary (``catalog visible: IPTS-12345
  (47 runs · 3 tagged)``), blank when nothing's loaded.
* **Right** — reserved for the upcoming LLM layer (Phase 10) so the
  user can see plan / progress / token usage without opening a modal.
  Empty for now; :meth:`update_for` accepts ``llm_status`` so the
  Phase 10 wiring is a one-line change here.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Label


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
    StatusBar > .middle {
        width: auto;
        content-align: center middle;
        padding: 0 1;
        color: $accent;
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
        self._middle = Label("", classes="middle")
        self._right = Label("", classes="right")

    def compose(self) -> ComposeResult:
        yield self._left
        yield self._middle
        yield self._right

    def update_for(
        self,
        file_count: int,
        *,
        filter_substring: str = "",
        tag_count: int = 0,
        catalog_summary: str = "",
        llm_status: str = "",
    ) -> None:
        """Re-render the three zones.

        ``llm_status`` reserves the right cell for the Phase 10 LLM
        layer (``\\\\``-prompt translator); pass an empty string to
        leave it blank, which is the current default.
        """
        bits: list[str] = [f"{file_count} entries"]
        if tag_count:
            bits.append(f"{tag_count} tagged")
        if filter_substring:
            bits.append(f"filter: [b yellow]{filter_substring}[/]")
        self._left.update("  ·  ".join(bits))
        self._middle.update(catalog_summary)
        self._right.update(llm_status)
