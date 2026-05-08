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

    # Cap the rendered window so a wildcard filter (or no filter at
    # all) doesn't have to mount thousands of two-Static ListItems on
    # every keystroke. The overflow hint tells the user to narrow.
    MAX_VISIBLE: ClassVar[int] = 200
    # ms of quiet typing before we actually rebuild the list — the
    # cost of `lv.clear() + N x lv.append(...)` dominates the input
    # latency, so coalescing keystrokes is a huge win on big catalogs.
    FILTER_DEBOUNCE_MS: ClassVar[int] = 200

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
        # Pending debounced refresh (cancelled if another keystroke
        # arrives before it fires).
        self._refresh_timer: object | None = None

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
            yield Static("", id="overflow-hint", classes="hint")
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
            # next Enter picks an item — but if a debounced refresh is
            # still pending, run it now so the list reflects the latest
            # filter before the user moves on.
            self._cancel_pending_refresh()
            self._refresh_list()
            self.query_one("#results-list", ListView).focus()

    def watch_filter_text(self, _old: str, _new: str) -> None:
        # Debounce — schedule a rebuild after a short quiet period.
        # The first call from on_mount happens before any timer is
        # available; in that case we just rebuild inline.
        self._cancel_pending_refresh()
        try:
            self._refresh_timer = self.set_timer(
                self.FILTER_DEBOUNCE_MS / 1000, self._refresh_list
            )
        except Exception:
            # Fallback: not mounted yet → rebuild inline.
            self._refresh_list()

    def watch_sort_mode(self, _old: str, _new: str) -> None:
        # Sort cycles via a key press, not typing — refresh immediately.
        self._cancel_pending_refresh()
        self._refresh_list()
        # Reflect the new mode in the title bar.
        with contextlib.suppress(Exception):
            self.query_one("#browser-title", Static).update(self._title_text())

    def _cancel_pending_refresh(self) -> None:
        if self._refresh_timer is not None:
            with contextlib.suppress(Exception):
                self._refresh_timer.stop()  # type: ignore[attr-defined]
            self._refresh_timer = None

    def _refresh_list(self) -> None:
        self._refresh_timer = None
        kw = self.filter_text.strip()
        matches = [e for e in self._all if e.matches(kw)]
        matches = self._sorted(matches)
        try:
            lv = self.query_one("#results-list", ListView)
        except Exception:
            return
        total = len(matches)
        truncated = matches[: self.MAX_VISIBLE]
        # Batch the swap so Textual issues a single layout pass for
        # the whole rebuild instead of one per appended row.
        with self.app.batch_update():
            lv.clear()
            for exp in truncated:
                lv.append(_ExpItem(exp))
            if truncated:
                lv.index = 0
        # Update the overflow hint underneath the list.
        with contextlib.suppress(Exception):
            hint = self.query_one("#overflow-hint", Static)
            if total > self.MAX_VISIBLE:
                extra = total - self.MAX_VISIBLE
                hint.update(
                    f"[dim]showing first {self.MAX_VISIBLE} of {total} "
                    f"matches  [b]·[/]  +{extra} more — narrow your filter[/]"
                )
            elif total == 0 and kw:
                hint.update(f"[dim]no matches for {kw!r}[/]")
            else:
                hint.update("")

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
