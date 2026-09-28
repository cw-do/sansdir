"""Centered modal shown during OnCat device sign-in.

The device-authorization flow hands back a verification URL (and sometimes a
code) that the user must open in a browser. A transient notification is too
easy to miss and vanishes before it can be copied, so this modal shows the URL
prominently in the middle of the screen with explicit copy-paste instructions
and stays up until the background sign-in worker finishes or the user cancels
with Esc.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class OnCatLoginScreen(ModalScreen[bool]):
    """Displays the OnCat sign-in URL and instructions during device login."""

    DEFAULT_CSS = """
    OnCatLoginScreen {
        align: center middle;
    }
    OnCatLoginScreen > Vertical {
        background: $surface;
        border: round $accent;
        padding: 1 2;
        width: 80;
        max-width: 90%;
        height: auto;
    }
    OnCatLoginScreen .title {
        text-style: bold;
        margin-bottom: 1;
    }
    OnCatLoginScreen #oncat-login-url {
        background: $boost;
        color: $text;
        padding: 1 2;
        margin: 1 0;
        border: round $primary;
    }
    OnCatLoginScreen .hint {
        color: $text-muted;
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("OnCat sign-in", classes="title")
            yield Static("Contacting OnCat — one moment…", id="oncat-login-body")
            # URL gets its own boxed, selectable line; hidden until it arrives.
            url = Static("", id="oncat-login-url")
            url.display = False
            yield url
            yield Static("", id="oncat-login-hint", classes="hint")

    def show_challenge(self, url: str, code: str = "") -> None:
        """Populate the modal with the verification URL and instructions."""
        body = self.query_one("#oncat-login-body", Static)
        url_widget = self.query_one("#oncat-login-url", Static)
        hint = self.query_one("#oncat-login-hint", Static)

        body.update(
            "To sign in, open this web address in a browser [b]on your own "
            "computer[/b].\nA click in the terminal usually will not work over "
            "SSH — [b]select the address and copy-paste it[/b] (in many "
            "terminals [b]Ctrl+Click[/b], or [b]Cmd+Click[/b] on macOS, opens "
            "it too):"
        )
        url_widget.update(url)
        url_widget.display = True

        lines = []
        if code:
            lines.append(f"If the page asks for a code, enter:  [b]{code}[/b]")
        lines.append("Then sign in with your UCAMS/XCAMS and approve access.")
        lines.append("This window closes automatically once you are signed in.")
        lines.append("[dim]Press Esc to cancel.[/dim]")
        hint.update("\n".join(lines))

    def show_error(self, message: str) -> None:
        """Replace the body with an error; the caller dismisses shortly after."""
        self.query_one("#oncat-login-body", Static).update(f"[b red]{message}[/b red]")
        self.query_one("#oncat-login-url", Static).display = False
        self.query_one("#oncat-login-hint", Static).update("[dim]Press Esc to close.[/dim]")

    def action_cancel(self) -> None:
        self.dismiss(False)
