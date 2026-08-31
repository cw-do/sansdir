"""Top-of-screen title bar.

A 1-line widget showing the program identity at the very top of the
TUI. Lives at the top of the App's layout so the user can see the
build they're running at a glance — useful when there are several
versions installed across cluster modules.

It also carries the instrument chip: which instrument (and therefore
which mode — SANS or USANS) the session targets. That decides what ``i``
searches, what the run catalog shows, and whether the USANS keys are
live, so it belongs somewhere permanently visible.
"""

from __future__ import annotations

from textual.widgets import Static

from sansdir import __version__


class TitleBar(Static):
    """Static colored line: ``▣ SansDIR  v0.0.1  ·  EQSANS``."""

    DEFAULT_CSS = """
    TitleBar {
        height: 1;
        background: $surface;
        color: $text;
        padding: 0 1;
    }
    """

    def __init__(self, instrument: str = "") -> None:
        # Two coloured glyphs as a faux-pixel SANS detector logo: an
        # outer block + nested inner block, suggesting a pixel array.
        # Followed by the program name in accent + version in muted.
        self._instrument = instrument
        super().__init__(self._render_text(), id="titlebar")

    def _render_text(self) -> str:
        chip = f"  [dim]·[/dim]  [b green]{self._instrument}[/]" if self._instrument else ""
        return f"[b cyan]▣[/] [b orange1]SansDIR[/]  [dim]v{__version__}[/dim]{chip}"

    def set_instrument(self, instrument: str) -> None:
        """Update the instrument chip (``:instrument usans`` and friends)."""
        self._instrument = instrument
        self.update(self._render_text())
