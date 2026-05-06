"""``RunCatalogPanel`` — DataTable view of an IPTS's run list.

Mounted as a third "mode" inside :class:`~sansdir.ui.pane_slot.PaneSlot`,
alongside the regular file panel and the inline file viewer. Columns
mirror eqsanscli's ``/load ipts`` table (without the run-classification
column, which is reduction-pipeline specific):

    Run #  ·  Title  ·  Dist (m)  ·  λ (Å)  ·  Count  ·  Time(s)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from sansdir.core.filesystem import format_size

if TYPE_CHECKING:
    from sansdir.core.oncat import Datafile


def _format_counts(n: int) -> str:
    """Compact ``1234567 → '1.2M'`` formatter (matches eqsanscli)."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}K"
    if n < 1_000_000_000:
        return f"{n / 1_000_000:.1f}M"
    return f"{n / 1_000_000_000:.1f}B"


class RunCatalogPanel(Vertical):
    """One pane's worth of "OnCat run catalog for IPTS-NNNNN"."""

    DEFAULT_CSS = """
    RunCatalogPanel {
        border: round $surface;
        height: 1fr;
        width: 1fr;
        padding: 0 1;
    }
    RunCatalogPanel:focus, RunCatalogPanel.-active {
        border: round $accent;
    }
    RunCatalogPanel #catalog-header {
        text-style: bold;
        color: $accent;
        height: 1;
    }
    RunCatalogPanel #catalog-meta {
        color: $text-muted;
        height: 1;
    }
    RunCatalogPanel DataTable {
        height: 1fr;
    }
    RunCatalogPanel .hint {
        color: $text-muted;
        height: 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "close", "Close catalog", show=False),
    ]

    def __init__(self, panel_id: str) -> None:
        super().__init__(id=f"catalog-{panel_id}")
        self._panel_id = panel_id
        self._header = Static("", id="catalog-header")
        self._meta = Static("", id="catalog-meta")
        self._table: DataTable = DataTable(
            cursor_type="row",
            zebra_stripes=False,
            show_header=True,
        )
        self._hint = Static(
            "[dim]F2 toggles filelist · Esc closes catalog[/dim]",
            classes="hint",
        )
        self._ipts: str = ""
        self._files: list[Datafile] = []
        self.can_focus = True

    def compose(self):  # type: ignore[override]
        yield self._header
        yield self._meta
        yield self._table
        yield self._hint

    def on_mount(self) -> None:
        self._table.add_columns("Run #", "Title", "Dist (m)", "λ (Å)", "Count", "Time(s)")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show(self, ipts: str, files: list[Datafile]) -> None:
        """Replace the table contents with ``files`` for ``ipts``."""
        self._ipts = ipts
        self._files = files
        self._header.update(f"OnCat catalog · {ipts}")
        self._meta.update(f"{len(files)} run(s)")
        self._table.clear()
        for f in files:
            self._table.add_row(
                str(f.run_number),
                (f.title or "")[:40],
                f"{f.detector_distance_m:.1f}",
                f"{f.wavelength_a:.1f}",
                _format_counts(f.total_counts),
                str(int(f.duration_s)),
            )
        # Keep cursor visible at top.
        if files:
            self._table.move_cursor(row=0)

    @property
    def ipts(self) -> str:
        return self._ipts

    @property
    def files(self) -> list[Datafile]:
        return list(self._files)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_close(self) -> None:
        # Tell the App to swap this slot back to the FilePanel.
        self.app.close_inline_viewer(self._panel_id)  # type: ignore[attr-defined]


# Re-export ``format_size`` so other modules importing from this module
# see a single namespace if they want the same compact-numbers helper.
__all__ = ["RunCatalogPanel", "format_size"]
