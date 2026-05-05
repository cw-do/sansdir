"""Always-visible ``:``-line at the bottom of the app.

Behaves like a shell prompt:

* ``Up`` / ``Down`` — walk persistent history (saved to
  ``~/.cache/sansdir/cmd_history``).
* ``Tab`` — complete the first token against registered command names;
  hitting Tab on a unique completion fills the rest of the name plus a
  trailing space; a multi-match shows them in the status notifier.
* ``Esc`` — cancel and return focus to the active pane.
* ``Enter`` — submit; the App's :meth:`SansdirApp.run_command_line` handles
  parsing and dispatch.

The widget itself is just plumbing; all parsing and dispatch lives in
:mod:`sansdir.commands.parser` and the registry, so the LLM layer (Phase
10+) reuses the same code path.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding, BindingType
from textual.widgets import Input

from sansdir.commands.parser import common_prefix, complete_command_name
from sansdir.core.history import CommandHistory

if TYPE_CHECKING:
    from sansdir.commands.registry import CommandRegistry


class CommandInput(Input):
    """The single-line ``:``-prompt at the bottom of :class:`SansdirApp`."""

    DEFAULT_CSS = """
    CommandInput {
        height: 1;
        border: none;
        padding: 0 1;
        background: $surface;
    }
    CommandInput:focus {
        background: $boost;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "history_prev", "History prev", show=False),
        Binding("down", "history_next", "History next", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+c", "cancel", "Cancel", show=False),
        Binding("tab", "complete", "Complete", show=False),
    ]

    def __init__(
        self,
        *,
        registry: CommandRegistry,
        history: CommandHistory,
    ) -> None:
        super().__init__(
            placeholder=":  type a command — try `help` or `cd /tmp`",
            id="cmdline",
            # Textual Input selects-all on focus by default, which would make
            # any key after `cmdline_prompt(...)` (e.g. pressing `+` to land
            # in the input pre-filled with "tag.glob ") wipe the prefix. Keep
            # the cursor where we put it.
            select_on_focus=False,
        )
        self._registry = registry
        self._history = history

    # ---- history navigation --------------------------------------------------

    def action_history_prev(self) -> None:
        line = self._history.previous(self.value)
        if line != self.value:
            self.value = line
            self.cursor_position = len(line)

    def action_history_next(self) -> None:
        line = self._history.next(self.value)
        if line != self.value:
            self.value = line
            self.cursor_position = len(line)

    # ---- cancel --------------------------------------------------------------

    def action_cancel(self) -> None:
        self.value = ""
        # Return focus to the active pane so navigation keys work again.
        with contextlib.suppress(AttributeError, LookupError):
            self.app.set_focus(self.app.active_panel)  # type: ignore[attr-defined]

    # ---- completion ----------------------------------------------------------

    def action_complete(self) -> None:
        text = self.value
        if " " in text.rstrip():
            # Past the first token — Phase 2 only completes command names;
            # path completion is Phase 6+.
            return
        prefix = text.lstrip()
        matches = complete_command_name(prefix, self._registry)
        if not matches:
            return
        if len(matches) == 1:
            self.value = matches[0] + " "
            self.cursor_position = len(self.value)
            return
        common = common_prefix(matches)
        if common and common != prefix:
            self.value = common
            self.cursor_position = len(common)
        # Show candidates without forcing the user to dismiss a popup.
        self.app.notify(
            "  ".join(matches[:12]) + (" ..." if len(matches) > 12 else ""),
            title="completions",
            timeout=4,
        )

    # ---- public helpers used by the app -------------------------------------

    def reset(self) -> None:
        """Clear the line and reset the history cursor."""
        self.value = ""
        # Reset the history cursor by submitting an empty step — the
        # CommandHistory ``append`` path resets it too, so callers using the
        # submit flow don't need to call this.
        self._history.begin("")
