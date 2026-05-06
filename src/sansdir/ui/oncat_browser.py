"""Full-screen browser for OnCat experiment results.

Mimics the ``/list *`` output of eqsanscli: each IPTS renders as two
lines — bold cyan ``IPTS-NNNNN`` + title on top, then a dimmed line with
``N runs · DATE_FROM — DATE_TO · members``. Up/Down navigates, ``/``
focuses the filter input, Enter selects, Esc cancels.
"""

from __future__ import annotations

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
        head.append(f"  {title[:80]}")
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
    ]

    filter_text: reactive[str] = reactive("")

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
            yield Static(
                f"OnCat — {len(self._all)} experiment(s)  [dim](press [b]/[/] to filter)[/dim]",
                classes="title",
            )
            yield Input(
                value=self._initial_keyword,
                placeholder="filter by IPTS / title / member name",
                id="filter-input",
                select_on_focus=False,
                compact=True,
            )
            yield ListView(id="results-list")
            yield Static(
                "[dim]↑/↓ navigate · Enter select · / filter · Esc cancel[/dim]",
                classes="hint",
            )

    def on_mount(self) -> None:
        self.filter_text = self._initial_keyword
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

    def _refresh_list(self) -> None:
        kw = self.filter_text.strip()
        matches = [e for e in self._all if e.matches(kw)]
        try:
            lv = self.query_one("#results-list", ListView)
        except Exception:
            return
        lv.clear()
        for exp in matches:
            lv.append(_ExpItem(exp))
        if matches:
            lv.index = 0

    # ------------------------------------------------------------------
    # Selection / cancel
    # ------------------------------------------------------------------

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, _ExpItem):
            self.dismiss(event.item.experiment)

    def action_focus_filter(self) -> None:
        self.query_one("#filter-input", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)
