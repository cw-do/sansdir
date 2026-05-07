"""Top-of-screen title bar.

A 1-line widget showing the program identity at the very top of the
TUI. Lives at the top of the App's layout so the user can see the
build they're running at a glance — useful when there are several
versions installed across cluster modules.
"""

from __future__ import annotations

from textual.widgets import Static

from sansdir import __version__


class TitleBar(Static):
    """Static colored line: ``▣ SansDIR  v0.0.1``."""

    DEFAULT_CSS = """
    TitleBar {
        height: 1;
        background: $surface;
        color: $text;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        # Two coloured glyphs as a faux-pixel SANS detector logo: an
        # outer block + nested inner block, suggesting a pixel array.
        # Followed by the program name in accent + version in muted.
        super().__init__(
            f"[b cyan]▣[/] [b orange1]SansDIR[/]  [dim]v{__version__}[/dim]",
            id="titlebar",
        )
