"""End-to-end smoke tests for ``SansdirApp`` using Textual's ``Pilot``.

These tests boot the real app, drive it with simulated keystrokes, and
assert state changes — confirming that key → registry → handler → panel
state actually flows. They run headless in CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sansdir.app import SansdirApp


def _scratch(tmp_path: Path) -> tuple[Path, Path]:
    left = tmp_path / "L"
    right = tmp_path / "R"
    left.mkdir()
    right.mkdir()
    (left / "child").mkdir()
    (left / "data.dat").write_text("0", encoding="utf-8")
    (right / "other.dat").write_text("1", encoding="utf-8")
    return left, right


async def test_app_boots_and_shows_two_panes(tmp_path: Path) -> None:
    left, right = _scratch(tmp_path)
    app = SansdirApp(start_path=left, right_path=right)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.active_panel.cwd == left
        assert app.inactive_panel.cwd == right


async def test_tab_switches_active_pane(tmp_path: Path) -> None:
    left, right = _scratch(tmp_path)
    app = SansdirApp(start_path=left, right_path=right)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.active_panel.cwd == left
        await pilot.press("tab")
        await pilot.pause()
        assert app.active_panel.cwd == right
        await pilot.press("tab")
        await pilot.pause()
        assert app.active_panel.cwd == left


async def test_q_quits_via_registry(tmp_path: Path) -> None:
    left, right = _scratch(tmp_path)
    app = SansdirApp(start_path=left, right_path=right)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
    # If we exit cleanly the test reaches here; assert the app's return code.
    assert app.return_code == 0


async def test_pane_sync_copies_active_to_inactive(tmp_path: Path) -> None:
    left, right = _scratch(tmp_path)
    app = SansdirApp(start_path=left, right_path=right)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.inactive_panel.cwd == right
        await pilot.press("=")
        await pilot.pause()
        assert app.inactive_panel.cwd == left
        await pilot.press("q")


async def test_ctrl_u_swaps_panes(tmp_path: Path) -> None:
    left, right = _scratch(tmp_path)
    app = SansdirApp(start_path=left, right_path=right)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.active_panel.cwd == left
        assert app.inactive_panel.cwd == right
        await pilot.press("ctrl+u")
        await pilot.pause()
        # Active is still the "left" pane object, but its cwd is now right.
        assert app.active_panel.cwd == right
        assert app.inactive_panel.cwd == left
        await pilot.press("q")


async def test_h_toggles_hidden_only_on_active(tmp_path: Path) -> None:
    left, right = _scratch(tmp_path)
    (left / ".secret").write_text("x", encoding="utf-8")
    app = SansdirApp(start_path=left, right_path=right)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.active_panel.show_hidden is False
        assert app.inactive_panel.show_hidden is False
        await pilot.press("h")
        await pilot.pause()
        assert app.active_panel.show_hidden is True
        assert app.inactive_panel.show_hidden is False
        await pilot.press("q")


async def test_help_overlay_opens_and_closes(tmp_path: Path) -> None:
    left, right = _scratch(tmp_path)
    app = SansdirApp(start_path=left, right_path=right)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert len(app.screen_stack) == 1
        await pilot.press("?")
        await pilot.pause()
        assert len(app.screen_stack) == 2
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1
        await pilot.press("q")


async def test_ctrl_o_toggles_max(tmp_path: Path) -> None:
    left, right = _scratch(tmp_path)
    app = SansdirApp(start_path=left, right_path=right)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._max is False
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert app._max is True
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert app._max is False
        await pilot.press("q")


@pytest.mark.parametrize(
    ("key", "expected"),
    [("1", "name"), ("2", "mtime"), ("3", "size"), ("4", "ext")],
)
async def test_sort_key_keys(tmp_path: Path, key: str, expected: str) -> None:
    left, right = _scratch(tmp_path)
    app = SansdirApp(start_path=left, right_path=right)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press(key)
        await pilot.pause()
        assert app.active_panel.sort_key == expected
        await pilot.press("q")
