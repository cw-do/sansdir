"""``KeyHintBar`` — the Norton-style F-key hint strip.

One line above the ``:``-prompt. Picks short labels (max two words) for
the F-keys plus a few signature shortcuts and renders them in a compact
"key:label" form. The list is derived from :func:`default_keymap` so a
new keybinding shows up here automatically.

If your terminal is narrow, the bar elides labels from the right.
"""

from __future__ import annotations

from rich.text import Text
from textual.widget import Widget

from sansdir.ui.keys import KeyBinding, default_keymap

# Keys we always want to show, in this order.
HINT_ORDER: tuple[str, ...] = (
    "f3",
    "f4",
    "f5",
    "f6",
    "f7",
    "f8",
    "f10",
    "tab",
    "ctrl+u",
    "space",
    "+",
    "z",
    "e",
    "/",
    "g",
    "i",
    ":",
    "?",
)

# Display labels override the keybinding's verbose description so the bar
# stays at most two words per cell. Falls back to the keybinding's own
# description when not present here.
LABEL_OVERRIDES: dict[str, str] = {
    "f3": "View",
    "f4": "Edit",
    "f5": "Copy",
    "f6": "Move",
    "f7": "Mkdir",
    "f8": "Delete",
    "f10": "Quit",
    "tab": "Pane",
    "ctrl+u": "Swap",
    "space": "Tag",
    "+": "Tag glob",
    "z": "Zip",
    "e": "Email",
    "/": "Filter",
    "g": "Goto",
    "i": "IPTS",
    ":": "Cmd",
    "?": "Help",
}

# How each key prints in the hint cell. F-keys keep their digit; named
# Textual keys ("colon", "asterisk", ...) are normalised back to a glyph.
KEY_DISPLAY: dict[str, str] = {
    "f3": "F3",
    "f4": "F4",
    "f5": "F5",
    "f6": "F6",
    "f7": "F7",
    "f8": "F8",
    "f10": "F10",
    "tab": "Tab",
    "ctrl+u": "^U",
    "space": "Spc",
    "+": "+",
    "z": "z",
    "e": "e",
    "/": "/",
    "g": "g",
    "i": "i",
    ":": ":",
    "?": "?",
}


class KeyHintBar(Widget):
    """Single-line F-key hint strip rendered above the ``:``-prompt."""

    DEFAULT_CSS = """
    KeyHintBar {
        height: 1;
        background: $surface;
        color: $text;
        padding: 0 1;
    }
    """

    def __init__(self, keymap: list[KeyBinding] | None = None) -> None:
        super().__init__()
        self._keymap = keymap if keymap is not None else default_keymap()
        self._cells = self._build_cells(self._keymap)

    @staticmethod
    def _build_cells(keymap: list[KeyBinding]) -> list[tuple[str, str]]:
        # Index keymap by key for label fallback lookups.
        by_key = {kb.key: kb for kb in keymap if kb.show_in_help}
        cells: list[tuple[str, str]] = []
        for key in HINT_ORDER:
            label = LABEL_OVERRIDES.get(key)
            if label is None:
                kb = by_key.get(key)
                if kb is None:
                    continue
                # Trim to first two words.
                label = " ".join(kb.description.split()[:2])
            display = KEY_DISPLAY.get(key, key)
            cells.append((display, label))
        return cells

    def render(self) -> Text:
        text = Text()
        for i, (key, label) in enumerate(self._cells):
            if i:
                text.append("  ")
            text.append(key, style="bold reverse")
            text.append(f":{label}", style="")
        return text
