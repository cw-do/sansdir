"""``RunCatalogPanel`` — DataTable view of an IPTS's run list.

Mounted as a third "mode" inside :class:`~sansdir.ui.pane_slot.PaneSlot`,
alongside the regular file panel and the inline file viewer. Columns
mirror eqsanscli's ``/load ipts`` table (without the run-classification
column, which is reduction-pipeline specific):

    Run #  ·  Title  ·  Dist (m)  ·  λ (Å)  ·  Count  ·  Time(s)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from sansdir.core.filesystem import format_size

if TYPE_CHECKING:
    from sansdir.core.oncat import Datafile


class CatalogTable(DataTable):
    """DataTable subclass that delegates ``p`` / ``Enter`` to the catalog parent.

    Bindings live here (not on the parent ``Vertical``) because the
    DataTable is the focusable widget — Tab into the slot lands the
    cursor here, not on the wrapping container, so this is where keys
    actually arrive.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("p", "plot_current", "Plot raw NeXus", show=False),
        Binding("enter", "plot_current", "Plot raw NeXus", show=False),
    ]

    def action_plot_current(self) -> None:
        # Walk up to the RunCatalogPanel ancestor and run its handler.
        node = self.parent
        while node is not None and not isinstance(node, RunCatalogPanel):
            node = node.parent  # type: ignore[assignment]
        if node is not None:
            node.action_plot_current()


def _r(value: str) -> Text:
    """Right-justified Rich Text — used for numeric columns."""
    return Text(value, justify="right")


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
        # Use the CatalogTable subclass so Up/Down navigates rows AND
        # ``p`` / ``Enter`` plot the cursor row's raw NeXus.
        self._table: CatalogTable = CatalogTable(
            cursor_type="row",
            zebra_stripes=False,
            show_header=True,
        )
        self._hint = Static(
            "[dim]p / Enter: plot raw run · F2 toggles filelist · Esc closes[/dim]",
            classes="hint",
        )
        self._ipts: str = ""
        self._files: list[Datafile] = []
        self._instrument: str = "EQSANS"
        self._facility: str = "SNS"
        # The container itself isn't focusable — focus belongs to the
        # CatalogTable inside, which handles cursor nav and key bindings.
        self.can_focus = False

    def compose(self):  # type: ignore[override]
        yield self._header
        yield self._meta
        yield self._table
        yield self._hint

    def on_mount(self) -> None:
        # Right-justify numeric column headers so they line up over their
        # right-justified data cells.
        self._table.add_columns(
            _r("Run #"),
            "Title",
            _r("Dist (m)"),
            _r("λ (Å)"),
            _r("Count"),
            _r("Time(s)"),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show(
        self,
        ipts: str,
        files: list[Datafile],
        *,
        instrument: str = "EQSANS",
        facility: str = "SNS",
    ) -> None:
        """Replace the table contents with ``files`` for ``ipts``."""
        self._ipts = ipts
        self._files = files
        self._instrument = instrument
        self._facility = facility
        self._header.update(f"OnCat catalog · {ipts}")
        self._meta.update(f"{len(files)} run(s)")
        self._table.clear()
        for f in files:
            self._table.add_row(
                _r(str(f.run_number)),
                (f.title or "")[:40],
                # detector_distance_m converts the raw mm value from OnCat
                # for us — UI quotes metres with one decimal: "2.5", "1.3".
                _r(f"{f.detector_distance_m:.1f}"),
                _r(f"{f.wavelength_a:.1f}"),
                _r(_format_counts(f.total_counts)),
                _r(str(int(f.duration_s))),
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

    @property
    def instrument(self) -> str:
        return self._instrument

    @property
    def facility(self) -> str:
        return self._facility

    @property
    def table(self) -> CatalogTable:
        """The inner DataTable — what callers should focus when entering this slot."""
        return self._table

    @property
    def current_run_number(self) -> int | None:
        """Run number of the cursor row, or ``None`` if the table is empty."""
        if not self._files:
            return None
        row = self._table.cursor_row
        if row < 0 or row >= len(self._files):
            return None
        return self._files[row].run_number

    def raw_nexus_path(self, run_number: int) -> Path:
        """Conventional cluster path: ``/<facility>/<instr>/IPTS-N/nexus/<INSTR>_<run>.nxs.h5``."""
        return Path(
            f"/{self._facility}/{self._instrument}/{self._ipts}/nexus/"
            f"{self._instrument}_{run_number}.nxs.h5"
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_close(self) -> None:
        # Tell the App to swap this slot back to the FilePanel.
        self.app.close_inline_viewer(self._panel_id)  # type: ignore[attr-defined]

    def action_plot_current(self) -> None:
        """Plot the raw NeXus file for the cursor row's run number."""
        run = self.current_run_number
        if run is None:
            self.app.notify("no run under cursor", severity="warning")  # type: ignore[attr-defined]
            return
        path = self.raw_nexus_path(run)
        if not path.exists():
            self.app.notify(  # type: ignore[attr-defined]
                f"raw file not found: {path}",
                severity="warning",
            )
            return
        # Dispatch through the registry so the LLM layer can call this
        # path too — we deliberately don't reach into matplotlib here.
        self.app.run_worker(  # type: ignore[attr-defined]
            self.app.registry.dispatch("plot.detector_sum", paths=[str(path)]),  # type: ignore[attr-defined]
            name=f"plot:run{run}",
            exclusive=False,
        )


# Re-export ``format_size`` so other modules importing from this module
# see a single namespace if they want the same compact-numbers helper.
__all__ = ["RunCatalogPanel", "format_size"]
