"""``PaneSlot`` — one side of the dual-pane layout.

Holds a :class:`~sansdir.ui.panel.FilePanel` and an
:class:`~sansdir.ui.inline_viewer.InlineFileViewer`; exactly one of the
two is visible at a time. The slot is what the App composes; the
``FilePanel`` stays the canonical "active pane" reference even when its
slot is currently showing a viewer.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container

from sansdir.ui.inline_viewer import InlineFileViewer
from sansdir.ui.panel import FilePanel


class PaneSlot(Container):
    """A container that swaps between a FilePanel and an InlineFileViewer."""

    DEFAULT_CSS = """
    PaneSlot {
        width: 1fr;
        height: 1fr;
    }
    """

    def __init__(self, panel: FilePanel, *, panel_id: str) -> None:
        super().__init__(id=f"slot-{panel_id}")
        self._panel = panel
        self._viewer = InlineFileViewer(panel_id=panel_id)

    def compose(self) -> ComposeResult:
        yield self._panel
        yield self._viewer

    def on_mount(self) -> None:
        # Default: panel visible, viewer hidden. We toggle ``display``
        # rather than mounting/unmounting so reactive watchers and tags
        # survive a peek.
        self._viewer.display = False

    @property
    def panel(self) -> FilePanel:
        return self._panel

    @property
    def viewer(self) -> InlineFileViewer:
        return self._viewer

    @property
    def viewer_visible(self) -> bool:
        return bool(self._viewer.display)

    def show_viewer(self, path: Path) -> bool:
        """Load ``path`` into the viewer and show it. Returns False on binary."""
        ok = self._viewer.set_path(path)
        self._panel.display = False
        self._viewer.display = True
        return ok

    def show_panel(self) -> None:
        self._viewer.display = False
        self._panel.display = True
