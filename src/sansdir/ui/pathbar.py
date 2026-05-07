"""Two-up path display below the title bar.

Shows each pane's current working directory at all times, side-by-
side. Updated automatically via a reactive watch on each panel's
``cwd``, so the bar tracks ``cd``, ``=``, swap, F2, drag-clicks —
anything that changes either pane.

Cluster paths under ``/gpfs/neutronsfs/instruments/...`` are
rewritten to ``/SNS/...`` for display: that's the conventional
mount point users type in scripts and emails, even though the
back-end exposes the longer GPFS path. The on-disk path the app
actually uses is unchanged; only the rendered string is shortened.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from sansdir.ui.panel import FilePanel

# The GPFS mount the cluster exposes under /SNS via a symlink. Users
# type and remember the short form; we display that.
_GPFS_PREFIX: str = "/gpfs/neutronsfs/instruments"
_SNS_PREFIX: str = "/SNS"


def display_path(path: Path | str) -> str:
    """Return ``str(path)`` with the GPFS prefix shortened to ``/SNS``."""
    s = str(path)
    if s == _GPFS_PREFIX or s.startswith(_GPFS_PREFIX + "/"):
        s = _SNS_PREFIX + s[len(_GPFS_PREFIX) :]
    return s


class PathBar(Horizontal):
    """One row, two cells — left pane path | right pane path."""

    DEFAULT_CSS = """
    PathBar {
        height: 1;
        background: $surface;
    }
    PathBar > .pathbar-cell {
        width: 1fr;
        padding: 0 1;
        color: $text-muted;
        content-align: left middle;
    }
    PathBar > .pathbar-cell.-active {
        color: $accent;
        text-style: bold;
        background: $boost;
    }
    """

    def __init__(self, left: FilePanel, right: FilePanel) -> None:
        super().__init__(id="pathbar")
        self._left_panel = left
        self._right_panel = right
        self._left_cell = Static("", classes="pathbar-cell", id="pathbar-left")
        self._right_cell = Static("", classes="pathbar-cell", id="pathbar-right")

    def compose(self) -> ComposeResult:
        yield self._left_cell
        yield self._right_cell

    def on_mount(self) -> None:
        self._refresh()
        # Each FilePanel exposes ``cwd`` as a reactive; the watch
        # callback fires whenever it changes — including the
        # cd-via-set_cwd path, panel swap, and the focus-sync logic.
        self.watch(self._left_panel, "cwd", lambda *_: self._refresh())
        self.watch(self._right_panel, "cwd", lambda *_: self._refresh())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_active(self, panel_id: str) -> None:
        """Re-style the cells so the active pane's cwd reads as primary."""
        self._left_cell.set_class(panel_id == "left", "-active")
        self._right_cell.set_class(panel_id == "right", "-active")

    def _refresh(self) -> None:
        self._left_cell.update(display_path(self._left_panel.cwd))
        self._right_cell.update(display_path(self._right_panel.cwd))
