"""``PromptPanel`` — an in-pane question, answered by picking in the other pane.

The fourth thing a :class:`~sansdir.ui.pane_slot.PaneSlot` can show, after the
file list, the inline viewer and the run catalog. It exists for one shape of
interaction that a modal dialog handles badly: *"answer this by choosing a
file"*. A modal would cover the file list the user needs to read; putting the
question in one pane and letting them navigate the other keeps both on screen,
which is the whole reason sansdir has two panes.

The panel itself is inert — it renders text and nothing else. The state
machine that routes ``Enter`` and ``Esc`` while a pick is in flight lives in
:meth:`sansdir.app.SansdirApp.pick_file_in_other_pane`.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


class PromptPanel(Vertical):
    """A question rendered inside one pane while the user answers in the other."""

    DEFAULT_CSS = """
    PromptPanel {
        border: round $accent;
        height: 1fr;
        width: 1fr;
        padding: 1 2;
    }
    PromptPanel #prompt-title {
        text-style: bold;
        color: $accent;
        height: auto;
    }
    PromptPanel #prompt-body {
        height: auto;
        margin-top: 1;
    }
    PromptPanel #prompt-help {
        color: $text-muted;
        height: auto;
        margin-top: 1;
    }
    PromptPanel #prompt-keys {
        color: $text-muted;
        height: auto;
        margin-top: 1;
        text-style: bold;
    }
    """

    def __init__(self, panel_id: str) -> None:
        super().__init__(id=f"prompt-{panel_id}")
        self._panel_id = panel_id
        self._title = Static("", id="prompt-title")
        self._body = Static("", id="prompt-body")
        self._help = Static("", id="prompt-help")
        self._keys = Static("", id="prompt-keys")
        # Focus belongs to the *other* pane, where the user is choosing.
        self.can_focus = False

    def compose(self) -> ComposeResult:
        yield self._title
        yield self._body
        yield self._help
        yield self._keys

    def show(self, title: str, message: str, help_text: str = "", keys: str = "") -> None:
        """Render a question. All fields accept Rich console markup."""
        self._title.update(title)
        self._body.update(message)
        self._help.update(help_text)
        self._keys.update(keys or "[b]Enter[/b] choose · [b]Esc[/b] skip · [b]/[/b] filter")

    def clear(self) -> None:
        """Drop the rendered text once the question has been answered."""
        for widget in (self._title, self._body, self._help, self._keys):
            widget.update("")
