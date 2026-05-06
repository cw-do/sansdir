"""``KeyHintBar`` — the Norton-style F-key hint strip.

Two lines above the ``:``-prompt, in the style of mc/Norton:

* **Row 1** — F-keys + pane controls (Tab, ^U)
* **Row 2** — selection / navigation / actions (Space, +, U, p, z, e, /, g, i, :, ?)

Cell labels are derived from the keymap (``default_keymap()``) so a new
binding shows up in the hint bar automatically — but the canonical
short labels live in :data:`LABEL_OVERRIDES` so a verbose
``description`` doesn't blow out the cell width.
"""

from __future__ import annotations

from rich.text import Text
from textual.widget import Widget

from sansdir.ui.keys import KeyBinding, default_keymap

# Two rows of cells. Order within each row is left-to-right as rendered.
HINT_ROW_1: tuple[str, ...] = (
    "f2",
    "f3",
    "f4",
    "f5",
    "f6",
    "f7",
    "f8",
    "f10",
    "tab",
    "ctrl+u",
)
HINT_ROW_2: tuple[str, ...] = (
    "space",
    "+",
    "u",
    "p",
    "m",
    "z",
    "e",
    "/",
    "g",
    "i",
    ":",
    "?",
)

# Back-compat: tests import this — keep it as the concatenated row order.
HINT_ORDER: tuple[str, ...] = HINT_ROW_1 + HINT_ROW_2

LABEL_OVERRIDES: dict[str, str] = {
    "f2": "Catalog",
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
    "u": "Untag all",
    "p": "Plot",
    "m": "Metadata",
    "z": "Zip",
    "e": "Email",
    "/": "Filter",
    "g": "Goto",
    "i": "IPTS",
    ":": "Cmd",
    "?": "Help",
}

KEY_DISPLAY: dict[str, str] = {
    "f2": "F2",
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
    "u": "u",
    "p": "p",
    "m": "m",
    "z": "z",
    "e": "e",
    "/": "/",
    "g": "g",
    "i": "i",
    ":": ":",
    "?": "?",
}


class KeyHintBar(Widget):
    """Two-line key hint strip rendered above the ``:``-prompt."""

    DEFAULT_CSS = """
    KeyHintBar {
        height: 2;
        background: $surface;
        color: $text;
        padding: 0 1;
    }
    """

    def __init__(self, keymap: list[KeyBinding] | None = None) -> None:
        super().__init__()
        self._keymap = keymap if keymap is not None else default_keymap()
        self._row1 = self._build_cells(self._keymap, HINT_ROW_1)
        self._row2 = self._build_cells(self._keymap, HINT_ROW_2)
        # Tests still inspect ._cells; expose the concatenation.
        self._cells = self._row1 + self._row2

    @staticmethod
    def _build_cells(keymap: list[KeyBinding], keys: tuple[str, ...]) -> list[tuple[str, str]]:
        by_key = {kb.key: kb for kb in keymap if kb.show_in_help}
        cells: list[tuple[str, str]] = []
        for key in keys:
            label = LABEL_OVERRIDES.get(key)
            if label is None:
                kb = by_key.get(key)
                if kb is None:
                    continue
                label = " ".join(kb.description.split()[:2])
            display = KEY_DISPLAY.get(key, key)
            cells.append((display, label))
        return cells

    @staticmethod
    def _render_row(cells: list[tuple[str, str]]) -> Text:
        text = Text()
        for i, (key, label) in enumerate(cells):
            if i:
                text.append("  ")
            text.append(key, style="bold reverse")
            text.append(f":{label}", style="")
        return text

    def render(self) -> Text:
        text = self._render_row(self._row1)
        text.append("\n")
        text.append_text(self._render_row(self._row2))
        return text
