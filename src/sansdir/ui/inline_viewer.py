"""``InlineFileViewer`` — an in-pane preview widget.

Used by F3 to show the file under the cursor in the **inactive** pane,
Norton-Commander style: the active pane stays focused and navigable while
the other pane displays the file contents.

Binary files are detected by a NUL-byte heuristic in the first 8 KB and
short-circuit to a one-line warning instead of dumping bytes.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from textual.binding import Binding, BindingType
from textual.containers import VerticalScroll
from textual.widgets import Static

MAX_BYTES: int = 1_000_000


class InlineFileViewer(VerticalScroll):
    """Scrolls a file's text content inside one pane slot."""

    DEFAULT_CSS = """
    InlineFileViewer {
        border: round $surface;
        height: 1fr;
        width: 1fr;
        padding: 0 1;
    }
    InlineFileViewer:focus, InlineFileViewer.-active {
        border: round $accent;
    }
    InlineFileViewer > #viewer-header {
        text-style: bold;
        color: $text-muted;
    }
    """

    # Keys handled when the viewer itself is focused. Esc closes the
    # viewer; the App listens for the message and restores the FilePanel.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "close", "Close viewer", show=False),
        Binding("q", "close", "Close viewer", show=False),
    ]

    def __init__(self, panel_id: str) -> None:
        super().__init__(id=f"viewer-{panel_id}")
        self._panel_id = panel_id
        self._header = Static("", id="viewer-header")
        self._body = Static("", id="viewer-body")
        self._path: Path | None = None
        self.can_focus = True

    def compose(self):  # type: ignore[override]
        yield self._header
        yield self._body

    def set_path(self, path: Path) -> bool:
        """Load and display ``path``. Returns False on binary / error."""
        self._path = path
        self._header.update(f"view: {path}")
        try:
            data = path.read_bytes()[:MAX_BYTES]
        except OSError as exc:
            self._body.update(f"<error: {exc}>")
            return False
        if b"\x00" in data[:8192]:
            self._body.update("<binary file — refusing to render>")
            return False
        try:
            text = data.decode("utf-8", errors="replace")
        except UnicodeDecodeError as exc:
            self._body.update(f"<decode error: {exc}>")
            return False
        if path.stat().st_size > MAX_BYTES:
            text += f"\n\n... [truncated at {MAX_BYTES} bytes]"
        self._body.update(text)
        return True

    @property
    def path(self) -> Path | None:
        return self._path

    def action_close(self) -> None:
        # The App owns the panel/viewer swap; tell it to do the swap.
        self.app.close_inline_viewer(self._panel_id)  # type: ignore[attr-defined]
