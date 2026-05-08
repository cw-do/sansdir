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
    """DataTable subclass that delegates ``p`` / ``Enter`` / ``m`` / ``M``.

    Bindings live here (not on the parent ``Vertical``) because the
    DataTable is the focusable widget — Tab into the slot lands the
    cursor here, not on the wrapping container, so this is where keys
    actually arrive. Each action walks up to the
    :class:`RunCatalogPanel` and runs the matching handler so the
    catalog can resolve runs to raw NeXus paths.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("p", "plot_current", "Plot raw NeXus", show=False),
        Binding("enter", "plot_current", "Plot raw NeXus", show=False),
        Binding("m", "show_keys_current", "HDF5 metadata tree", show=False),
        Binding("M", "batch_extract_selection", "Batch extract metadata", show=False),
        Binding("K", "mask_current", "Mask editor", show=False),
        Binding("space", "toggle_tag", "Tag run", show=False),
        Binding("u", "clear_tags", "Clear all tags", show=False),
    ]

    def _delegate(self, name: str) -> None:
        node = self.parent
        while node is not None and not isinstance(node, RunCatalogPanel):
            node = node.parent  # type: ignore[assignment]
        if node is not None:
            getattr(node, name)()

    def action_plot_current(self) -> None:
        self._delegate("action_plot_current")

    def action_show_keys_current(self) -> None:
        self._delegate("action_show_keys_current")

    def action_batch_extract_selection(self) -> None:
        self._delegate("action_batch_extract_selection")

    def action_mask_current(self) -> None:
        self._delegate("action_mask_current")

    def action_toggle_tag(self) -> None:
        self._delegate("action_toggle_tag")

    def action_clear_tags(self) -> None:
        self._delegate("action_clear_tags")


def _r(value: str) -> Text:
    """Right-justified Rich Text — used for numeric columns."""
    return Text(value, justify="right")


def _matches(f: Datafile, sub: str) -> bool:
    """True if ``sub`` (already lowercased) appears in run number or title.

    Run number is matched as a substring of its decimal form, so users
    can type ``200`` to highlight every run starting with that prefix
    (12001, 12002 → both contain ``200``). Title match is case-insensitive.
    """
    if sub in str(f.run_number):
        return True
    return bool(f.title and sub in f.title.lower())


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
            "[dim]Space tag · u clear tags · p plot · m keys · M extract · "
            "K mask · / filter · F2 list · Esc close[/dim]",
            classes="hint",
        )
        self._ipts: str = ""
        # Two lists so filtering doesn't mutate the underlying catalog —
        # ``_all_files`` is the authoritative OnCat result, ``_files`` is
        # what's visible in the table after the filter is applied.
        self._files: list[Datafile] = []
        self._all_files: list[Datafile] = []
        self._filter_substring: str = ""
        # Run numbers the user has tagged (Space). Stable across filter
        # changes — tagging persists when you narrow / widen the view.
        self._tagged_runs: set[int] = set()
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
        self._all_files = list(files)
        self._instrument = instrument
        self._facility = facility
        self._header.update(f"OnCat catalog · {ipts}")
        # Loading a fresh catalog drops any leftover filter and tags —
        # otherwise stale state from the previous IPTS would silently
        # hide rows or carry over selections that no longer match.
        self._filter_substring = ""
        self._tagged_runs.clear()
        self._rebuild()

    # ------------------------------------------------------------------
    # Filter
    # ------------------------------------------------------------------

    @property
    def filter_substring(self) -> str:
        return self._filter_substring

    @filter_substring.setter
    def filter_substring(self, pattern: str) -> None:
        new = (pattern or "").strip()
        if new == self._filter_substring:
            return
        self._filter_substring = new
        self._rebuild()

    def _rebuild(self) -> None:
        """Re-apply the current filter and rebuild the table rows."""
        sub = self._filter_substring.lower()
        if sub:
            self._files = [f for f in self._all_files if _matches(f, sub)]
        else:
            self._files = list(self._all_files)
        bits: list[str] = [f"{len(self._files)} of {len(self._all_files)} run(s)"]
        if sub:
            bits.append(f"filter: [b yellow]{self._filter_substring}[/]")
        if self._tagged_runs:
            bits.append(f"tagged: [b yellow]{len(self._tagged_runs)}[/]")
        self._meta.update("  ·  ".join(bits))
        self._table.clear()
        for f in self._files:
            tag_marker = "* " if f.run_number in self._tagged_runs else "  "
            self._table.add_row(
                _r(tag_marker + str(f.run_number)),
                (f.title or "")[:40],
                # detector_distance_m converts the raw mm value from OnCat
                # for us — UI quotes metres with one decimal: "2.5", "1.3".
                _r(f"{f.detector_distance_m:.1f}"),
                _r(f"{f.wavelength_a:.1f}"),
                _r(_format_counts(f.total_counts)),
                _r(str(int(f.duration_s))),
            )
        if self._files:
            self._table.move_cursor(row=0)

    @property
    def ipts(self) -> str:
        return self._ipts

    @property
    def files(self) -> list[Datafile]:
        """The currently-visible (post-filter) run list."""
        return list(self._files)

    @property
    def all_files(self) -> list[Datafile]:
        """Every run OnCat returned, ignoring the active filter."""
        return list(self._all_files)

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
        # If a filter is active, Esc clears the filter first (matches
        # the FilePanel's Esc behaviour) — only the *next* Esc closes
        # the catalog. This keeps the user from accidentally losing
        # their position when they just wanted to drop the filter.
        if self._filter_substring:
            self.filter_substring = ""
            return
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

    def action_show_keys_current(self) -> None:
        """``m`` from the catalog: open the HDF5 tree for the cursor row's run."""
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
        self.app.run_worker(  # type: ignore[attr-defined]
            self.app.registry.dispatch("hdf.show_keys", path=str(path)),  # type: ignore[attr-defined]
            name=f"keys:run{run}",
            exclusive=False,
        )

    def action_mask_current(self) -> None:
        """``K`` from the catalog: launch the mask editor on the cursor row's run."""
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
        self.app.run_worker(  # type: ignore[attr-defined]
            self.app.registry.dispatch("ui.mask", path=str(path)),  # type: ignore[attr-defined]
            name=f"mask:run{run}",
            exclusive=False,
        )

    def action_batch_extract_selection(self) -> None:
        """``M`` from the catalog: batch-extract metadata from the selection.

        Selection rules (mirroring the file-pane convention):

        * If any rows are tagged (``Space``), use *those* runs.
        * Otherwise use just the cursor row — this matches ``F5``/``F6``
          on the file pane, where "no tags → just this one". Tag with
          ``Space`` first when you want the multi-run flow.

        Runs whose raw NeXus file isn't on disk yet are dropped with a
        notify; the rest land in :class:`BatchExtractDialog` as the
        file list.
        """
        if self._tagged_runs:
            runs = [f for f in self._all_files if f.run_number in self._tagged_runs]
            source = f"{len(runs)} tagged run(s)"
        else:
            current = self.current_run_number
            runs = [f for f in self._files if f.run_number == current] if current else []
            source = f"run {current}" if runs else "(no run under cursor)"
        if not runs:
            self.app.notify("catalog is empty", severity="warning")  # type: ignore[attr-defined]
            return
        paths = [self.raw_nexus_path(r.run_number) for r in runs]
        existing = [p for p in paths if p.exists()]
        missing = len(paths) - len(existing)
        if not existing:
            self.app.notify(  # type: ignore[attr-defined]
                f"no raw NeXus files on disk for {source}",
                severity="warning",
            )
            return
        if missing:
            self.app.notify(  # type: ignore[attr-defined]
                f"skipping {missing} run(s) without raw NeXus on disk",
            )
        self.app.run_worker(  # type: ignore[attr-defined]
            self.app.registry.dispatch(  # type: ignore[attr-defined]
                "ui.batch_extract",
                paths=[str(p) for p in existing],
            ),
            name="catalog:batch_extract",
            exclusive=False,
        )

    # ------------------------------------------------------------------
    # Tag actions (Space / u)
    # ------------------------------------------------------------------

    def action_toggle_tag(self) -> None:
        """``Space`` on the catalog: tag/untag the run under the cursor."""
        run = self.current_run_number
        if run is None:
            return
        if run in self._tagged_runs:
            self._tagged_runs.remove(run)
        else:
            self._tagged_runs.add(run)
        # Preserve cursor row across the rebuild so Space-Space-Space…
        # marches down naturally instead of resetting to row 0.
        cursor = self._table.cursor_row
        self._rebuild()
        if 0 <= cursor < len(self._files):
            self._table.move_cursor(row=cursor)
        self._notify_app_status_changed()

    def action_clear_tags(self) -> None:
        """``u`` on the catalog: drop all tags."""
        if not self._tagged_runs:
            return
        cursor = self._table.cursor_row
        self._tagged_runs.clear()
        self._rebuild()
        if 0 <= cursor < len(self._files):
            self._table.move_cursor(row=cursor)
        self._notify_app_status_changed()

    def _notify_app_status_changed(self) -> None:
        """Bump the bottom status bar to reflect the new tagged-runs count."""
        refresh = getattr(self.app, "_refresh_status", None)
        if callable(refresh):
            refresh()

    @property
    def tagged_runs(self) -> set[int]:
        """Run numbers the user has Space-tagged in this catalog."""
        return set(self._tagged_runs)


# Re-export ``format_size`` so other modules importing from this module
# see a single namespace if they want the same compact-numbers helper.
__all__ = ["RunCatalogPanel", "format_size"]
