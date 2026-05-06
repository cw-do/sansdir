"""``PaneSlot`` — one side of the dual-pane layout.

Holds three swappable views:

* :class:`~sansdir.ui.panel.FilePanel`        — the default file listing
* :class:`~sansdir.ui.inline_viewer.InlineFileViewer` — F3 in-pane preview
* :class:`~sansdir.ui.run_catalog.RunCatalogPanel`    — OnCat run catalog

Exactly one is visible at a time. The :class:`~sansdir.ui.panel.FilePanel`
remains the canonical "active pane" reference (held by the App) even when
its slot currently shows a viewer or a catalog — that lets handlers like
``nav.cd`` keep working uniformly regardless of the visible mode.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from textual.app import ComposeResult
from textual.containers import Container

from sansdir.ui.inline_viewer import InlineFileViewer
from sansdir.ui.panel import FilePanel
from sansdir.ui.run_catalog import RunCatalogPanel

if TYPE_CHECKING:
    from sansdir.core.oncat import Datafile

PaneMode = Literal["list", "viewer", "catalog"]


class PaneSlot(Container):
    """A container that swaps between FilePanel / InlineFileViewer / RunCatalogPanel."""

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
        self._catalog = RunCatalogPanel(panel_id=panel_id)
        self._mode: PaneMode = "list"
        # Remember the last loaded catalog so F2 can reopen it without
        # another OnCat round-trip.
        self._catalog_loaded: bool = False

    def compose(self) -> ComposeResult:
        yield self._panel
        yield self._viewer
        yield self._catalog

    def on_mount(self) -> None:
        self._viewer.display = False
        self._catalog.display = False

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def panel(self) -> FilePanel:
        return self._panel

    @property
    def viewer(self) -> InlineFileViewer:
        return self._viewer

    @property
    def catalog(self) -> RunCatalogPanel:
        return self._catalog

    @property
    def mode(self) -> PaneMode:
        return self._mode

    @property
    def viewer_visible(self) -> bool:
        return self._mode == "viewer"

    @property
    def catalog_visible(self) -> bool:
        return self._mode == "catalog"

    @property
    def has_catalog(self) -> bool:
        """True once :meth:`show_catalog` has populated the run table at least once."""
        return self._catalog_loaded

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    def show_panel(self) -> None:
        self._panel.display = True
        self._viewer.display = False
        self._catalog.display = False
        self._mode = "list"

    def show_viewer(self, path: Path) -> bool:
        ok = self._viewer.set_path(path)
        self._panel.display = False
        self._catalog.display = False
        self._viewer.display = True
        self._mode = "viewer"
        return ok

    def show_catalog(
        self,
        ipts: str,
        files: list[Datafile],
        *,
        instrument: str = "EQSANS",
        facility: str = "SNS",
    ) -> None:
        self._catalog.show(ipts, files, instrument=instrument, facility=facility)
        self._panel.display = False
        self._viewer.display = False
        self._catalog.display = True
        self._mode = "catalog"
        self._catalog_loaded = True
