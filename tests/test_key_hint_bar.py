"""Tests for KeyHintBar."""

from __future__ import annotations

from sansdir.ui.key_hint_bar import HINT_ORDER, LABEL_OVERRIDES, KeyHintBar
from sansdir.ui.keys import default_keymap


def test_hint_bar_builds_cells_in_order() -> None:
    bar = KeyHintBar(default_keymap())
    # Every cell key must come from HINT_ORDER and be in that order.
    indices = [HINT_ORDER.index(k) for k in _displayed_keys(bar)]
    assert indices == sorted(indices), "hint cells out of order"


def test_hint_labels_are_short() -> None:
    bar = KeyHintBar(default_keymap())
    for _, label in bar._cells:
        words = label.split()
        assert len(words) <= 2, f"label too long: {label!r}"


def test_hint_render_returns_text_with_keys_and_labels() -> None:
    bar = KeyHintBar(default_keymap())
    rendered = bar.render().plain
    # F-keys and signature shortcuts should all show up.
    for token in ("F3:View", "F5:Refresh", "F6:Copy", "F8:Delete", ":Cmd", "Tab:Pane"):
        assert token in rendered, f"missing {token!r} in {rendered!r}"


def test_overrides_take_precedence_over_keymap_description() -> None:
    bar = KeyHintBar(default_keymap())
    cell_labels = {label for _, label in bar._cells}
    for label in LABEL_OVERRIDES.values():
        if label in cell_labels:
            return
    raise AssertionError("no LABEL_OVERRIDES entries appeared in rendered cells")


def _displayed_keys(bar: KeyHintBar) -> list[str]:
    """Reverse the KEY_DISPLAY mapping to recover the canonical key per cell."""
    from sansdir.ui.key_hint_bar import KEY_DISPLAY

    inv = {v: k for k, v in KEY_DISPLAY.items()}
    return [inv[d] for d, _ in bar._cells]
