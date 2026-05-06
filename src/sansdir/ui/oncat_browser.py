"""Full-screen browser for OnCat experiment results.

Mimics the ``/list *`` output of eqsanscli: each IPTS renders as two
lines — bold cyan ``IPTS-NNNNN`` + title on top, then a dimmed line with
``N runs · DATE_FROM — DATE_TO · members``.

* Up/Down — navigate
* ``/`` — focus the filter input
* ``s`` — cycle sort: IPTS-number (newest first, default) → date (newest
  first); operates on the already-fetched listing, no OnCat round trip
* Enter — pick highlighted IPTS
* Esc — cancel
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Input, ListItem, ListView, Static

if TYPE_CHECKING:
    from sansdir.core.oncat import Experiment


class _ExpItem(ListItem):
    """One ListView entry — two stacked Statics (title row + meta row)."""

    DEFAULT_CSS = """
    _ExpItem {
        padding: 0 1;
        height: auto;
    }
    _ExpItem > Static {
        width: 100%;
    }
    _ExpItem.--highlight {
        background: $boost;
    }
    """

    def __init__(self, exp: Experiment) -> None:
        super().__init__()
        self.experiment = exp

    def compose(self) -> ComposeResult:
        title = self.experiment.title or "(no title)"
        head = Text()
        head.append(self.experiment.ipts, style="bold cyan")
        # eqsanscli truncates titles to 60 chars on /list output; match it.
        head.append(f"  {title[:60]}")
        yield Static(head)

        bits: list[str] = []
        if self.experiment.runs_count:
            bits.append(f"{self.experiment.runs_count} runs")
        if dr := self.experiment.date_range():
            bits.append(dr)
        if ms := self.experiment.members_summary():
            bits.append(ms)
        meta = Text(f"    {' · '.join(bits)}", style="dim") if bits else Text()
        yield Static(meta)


class OnCatBrowserScreen(ModalScreen):  # type: ignore[type-arg]
    """Full-screen IPTS browser with live substring filter."""

    DEFAULT_CSS = """
    OnCatBrowserScreen {
        align: center middle;
    }
    OnCatBrowserScreen > Vertical {
        background: $surface;
        border: round $accent;
        padding: 1 2;
        width: 95%;
        height: 90%;
    }
    OnCatBrowserScreen .title {
        text-style: bold;
        margin-bottom: 1;
    }
    OnCatBrowserScreen #filter-input {
        margin-bottom: 1;
    }
    OnCatBrowserScreen .hint {
        color: $text-muted;
        margin-top: 1;
    }
    OnCatBrowserScreen ListView {
        height: 1fr;
        background: $surface;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("slash", "focus_filter", "Filter", show=False),
        Binding("/", "focus_filter", "Filter", show=False),
        Binding("s", "cycle_sort", "Cycle sort", show=False),
    ]

    SORT_MODES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("ipts", "IPTS↓ (newest first)"),
        ("date", "Date↓ (newest acquisition)"),
    )

    filter_text: reactive[str] = reactive("")
    sort_mode: reactive[str] = reactive("ipts")

    def __init__(
        self,
        experiments: list[Experiment],
        *,
        keyword: str = "",
    ) -> None:
        super().__init__()
        self._all = experiments
        # Initial filter — set as reactive after compose so the watcher fires.
        self._initial_keyword = keyword

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self._title_text(), id="browser-title", classes="title")
            yield Input(
                value=self._initial_keyword,
                placeholder="filter by IPTS / title / member name",
                id="filter-input",
                select_on_focus=False,
                compact=True,
            )
            yield ListView(id="results-list")
            yield Static(
                "[dim]↑/↓ navigate · Enter select · / filter · s sort · Esc cancel[/dim]",
                classes="hint",
            )

    def on_mount(self) -> None:
        self.filter_text = self._initial_keyword
        # Reactives are already at their default values; force one render.
        self._refresh_list()
        # Focus the list (not the filter) so up/down works immediately.
        if self._initial_keyword:
            self.query_one("#filter-input", Input).focus()
        else:
            self.query_one("#results-list", ListView).focus()

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter-input":
            self.filter_text = event.value

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter-input":
            # Pressing Enter in the filter moves focus to the list so the
            # next Enter picks an item.
            self.query_one("#results-list", ListView).focus()

    def watch_filter_text(self, _old: str, _new: str) -> None:
        self._refresh_list()

    def watch_sort_mode(self, _old: str, _new: str) -> None:
        self._refresh_list()
        # Reflect the new mode in the title bar.
        with contextlib.suppress(Exception):
            self.query_one("#browser-title", Static).update(self._title_text())

    def _refresh_list(self) -> None:
        kw = self.filter_text.strip()
        matches = [e for e in self._all if e.matches(kw)]
        matches = self._sorted(matches)
        try:
            lv = self.query_one("#results-list", ListView)
        except Exception:
            return
        lv.clear()
        for exp in matches:
            lv.append(_ExpItem(exp))
        if matches:
            lv.index = 0

    def _sorted(self, items: list[Experiment]) -> list[Experiment]:
        if self.sort_mode == "date":
            # Newest acquisition first; entries with no date go to the end.
            return sorted(
                items,
                key=lambda e: (e.sort_date_key == "", e.sort_date_key),
                reverse=True,
            )
        # Default: IPTS number, descending (highest = newest IPTS first).
        return sorted(items, key=lambda e: e.ipts_number, reverse=True)

    def _title_text(self) -> str:
        mode_label = next(
            (lbl for key, lbl in self.SORT_MODES if key == self.sort_mode),
            self.sort_mode,
        )
        return (
            f"OnCat — {len(self._all)} experiment(s)  "
            f"[dim]· sort:[/] [b]{mode_label}[/]  "
            "[dim](press [b]s[/] to cycle, [b]/[/] to filter)[/dim]"
        )

    # ------------------------------------------------------------------
    # Selection / cancel / sort
    # ------------------------------------------------------------------

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, _ExpItem):
            self.dismiss(event.item.experiment)

    def action_focus_filter(self) -> None:
        self.query_one("#filter-input", Input).focus()

    def action_cycle_sort(self) -> None:
        keys = [k for k, _ in self.SORT_MODES]
        idx = keys.index(self.sort_mode) if self.sort_mode in keys else -1
        self.sort_mode = keys[(idx + 1) % len(keys)]

    def action_cancel(self) -> None:
        self.dismiss(None)
