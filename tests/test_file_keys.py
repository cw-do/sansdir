"""End-to-end tests for the F2..F9 file-op keys.

Layout (post-2026 reshuffle):

* F2  = Rename file under cursor
* F5  = Refresh both panes
* F6  = Copy tagged → other pane
* F7  = Move tagged → other pane
* F8  = Delete tagged
* F9  = Make directory
* `c` = Toggle catalog (Phase 4 feature; tested in test_phase4.py).
        Was on F2 originally, briefly on F10 — but most terminals
        reserve F10 for the menu bar, so it landed on a letter key.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sansdir.app import SansdirApp
from sansdir.core.history import CommandHistory


@pytest.fixture(autouse=True)
def isolate_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path / "cache"))


def _scratch(tmp_path: Path) -> tuple[Path, Path]:
    left = tmp_path / "L"
    right = tmp_path / "R"
    left.mkdir()
    right.mkdir()
    (left / "a.dat").write_text("aa", encoding="utf-8")
    (left / "b.dat").write_text("bb", encoding="utf-8")
    (left / "noise.txt").write_text("nn", encoding="utf-8")
    return left, right


def _real_app(tmp_path: Path) -> SansdirApp:
    left, right = _scratch(tmp_path)
    history = CommandHistory(path=tmp_path / "hist", load=False)
    return SansdirApp(start_path=left, right_path=right, history=history)


# ---------------------------------------------------------------------------
# F5 refresh
# ---------------------------------------------------------------------------


async def test_f5_refreshes_both_panes(tmp_path: Path) -> None:
    """F5 picks up files written outside the TUI (e.g. mask GUI subprocess)."""
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Drop a new file in the *active* pane after start-up.
        new_left = app.active_panel.cwd / "external.dat"
        new_left.write_text("xx", encoding="utf-8")
        # And one in the inactive pane too.
        new_right = app.inactive_panel.cwd / "remote.txt"
        new_right.write_text("yy", encoding="utf-8")
        # Sanity: the panel cache hasn't seen them yet.
        active_names_before = {e.name for e in app.active_panel._all_entries}
        assert "external.dat" not in active_names_before
        await pilot.press("f5")
        await pilot.pause()
        active_names_after = {e.name for e in app.active_panel._all_entries}
        inactive_names_after = {e.name for e in app.inactive_panel._all_entries}
        assert "external.dat" in active_names_after
        assert "remote.txt" in inactive_names_after
        await pilot.press("q")


# ---------------------------------------------------------------------------
# F9 mkdir (via cmdline prompt)
# ---------------------------------------------------------------------------


async def test_f9_prompts_for_mkdir(tmp_path: Path) -> None:
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f9")
        await pilot.pause()
        assert app.focused is app._cmdline
        assert app._cmdline.value == "mkdir "
        for ch in "freshdir":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        assert (app.active_panel.cwd / "freshdir").is_dir()
        await pilot.press("q")


# ---------------------------------------------------------------------------
# F6 / F7 copy / move (with confirm dialog)
# ---------------------------------------------------------------------------


async def _confirm_yes(pilot) -> None:  # type: ignore[no-untyped-def]
    """Helper: press Enter twice (focus + confirm) to accept a ConfirmDialog."""
    await pilot.press("enter")
    await pilot.pause()


async def test_f6_copy_tagged_to_other_pane(tmp_path: Path) -> None:
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Tag every file in the left pane.
        await pilot.press("+")
        await pilot.pause()
        for ch in "*.dat":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.active_panel.tags) == 2
        # F6 → confirm dialog → Yes
        await pilot.press("f6")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        right = app.inactive_panel.cwd
        assert (right / "a.dat").read_text(encoding="utf-8") == "aa"
        assert (right / "b.dat").read_text(encoding="utf-8") == "bb"
        # Sources untouched.
        assert (app.active_panel.cwd / "a.dat").exists()
        await pilot.press("q")


async def test_f6_no_selection_notifies(tmp_path: Path) -> None:
    """No tags, cursor on '..' — F6 should warn, not crash."""
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Cursor starts on '..' — selection() is empty.
        await pilot.press("f6")
        await pilot.pause()
        # No copy happened; right pane unchanged.
        right_files = list(app.inactive_panel.cwd.iterdir())
        assert right_files == []
        await pilot.press("q")


async def test_f7_move_tagged_to_other_pane(tmp_path: Path) -> None:
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("+")
        for ch in "*.dat":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("f7")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        left = app.active_panel.cwd
        right = app.inactive_panel.cwd
        assert not (left / "a.dat").exists()
        assert (right / "a.dat").exists()
        await pilot.press("q")


async def test_f6_can_be_cancelled(tmp_path: Path) -> None:
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("+")
        for ch in "*.dat":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("f6")
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        right = app.inactive_panel.cwd
        assert not (right / "a.dat").exists()
        await pilot.press("q")


# ---------------------------------------------------------------------------
# F8 delete (with confirm + send2trash mocked into a tmp dir)
# ---------------------------------------------------------------------------


async def test_f8_delete_tagged_with_confirm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[str] = []

    def fake_send2trash(path: str) -> None:
        captured.append(path)
        Path(path).unlink()

    import sys
    import types

    fake_mod = types.ModuleType("send2trash")
    fake_mod.send2trash = fake_send2trash  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "send2trash", fake_mod)

    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("+")
        for ch in "*.dat":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("f8")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        left = app.active_panel.cwd
        assert not (left / "a.dat").exists()
        assert not (left / "b.dat").exists()
        assert (left / "noise.txt").exists()
        await pilot.press("q")
    assert len(captured) == 2


async def test_f3_shows_file_in_other_pane(tmp_path: Path) -> None:
    """F3 from active pane shows file content in the inactive pane (Norton-style).

    Active pane keeps focus so the user can keep navigating.
    """
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Cursor on '..' first; step down to first .dat file.
        await pilot.press("down")
        await pilot.pause()
        active_before = app.active_panel
        await pilot.press("f3")
        await pilot.pause()
        # The inactive *slot* is now showing its viewer; the active panel
        # is unchanged and still focused.
        assert app._inactive_slot.viewer_visible
        assert app.active_panel is active_before
        assert app.focused is app.active_panel
        # Press F3 again to close.
        await pilot.press("f3")
        await pilot.pause()
        assert not app._inactive_slot.viewer_visible
        await pilot.press("q")


async def test_f3_tab_into_viewer_then_close(tmp_path: Path) -> None:
    """F3 → Tab into viewer pane → Esc / F3 close from there.

    The viewer keeps focus when Tab brings it into the active slot;
    `Esc` (the viewer's own binding) and `F3` (the toggle handler)
    both dismiss it from inside.
    """
    from sansdir.ui.inline_viewer import InlineFileViewer

    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        await pilot.press("f3")
        await pilot.pause()
        assert app._inactive_slot.viewer_visible
        # Tab → active slot is now the viewer slot, and focus follows
        # to the InlineFileViewer (so Esc / q reach the widget).
        await pilot.press("tab")
        await pilot.pause()
        assert app._active_slot.viewer_visible
        assert isinstance(app.focused, InlineFileViewer)
        # Esc closes it from inside the viewer.
        await pilot.press("escape")
        await pilot.pause()
        assert not app._active_slot.viewer_visible
        # Re-open and verify F3 from inside the viewer also closes.
        # First Tab back to the file pane to set up the F3.
        await pilot.press("tab")
        await pilot.pause()
        await pilot.press("f3")
        await pilot.pause()
        assert app._inactive_slot.viewer_visible
        await pilot.press("tab")
        await pilot.pause()
        assert app._active_slot.viewer_visible
        await pilot.press("f3")
        await pilot.pause()
        assert not app._active_slot.viewer_visible
        await pilot.press("q")


async def test_focus_sync_keeps_active_id_aligned_with_textual_focus(
    tmp_path: Path,
) -> None:
    """Mouse clicks (or any focus change) drag ``_active_id`` along.

    Without this sync the visible "active" border and the keymap's
    target panel can desync — the user sees the yellow border on the
    left but arrows still scroll the right pane.
    """
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Start active = left.
        assert app._active_id == "left"
        # Move Textual focus to the right panel directly (the same
        # thing Textual does when you click on it).
        right_panel = app._right
        right_panel.focus()
        await pilot.pause()
        assert app._active_id == "right"
        # And back.
        app._left.focus()
        await pilot.pause()
        assert app._active_id == "left"
        await pilot.press("q")


async def test_f3_on_directory_notifies(tmp_path: Path) -> None:
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Cursor on '..' (a directory) — F3 should notify, not crash.
        await pilot.press("f3")
        await pilot.pause()
        assert not app._inactive_slot.viewer_visible
        await pilot.press("q")


async def test_space_tag_preserves_scroll_position(tmp_path: Path) -> None:
    """Tagging a file deep in a scrolled list must not snap scroll to top.

    Reported bug: pressing Space on a row that's mid-list moved the
    cursor to the next row correctly, but the file pane re-rendered
    the whole DataTable (``clear()`` + re-add) — which resets scroll
    to 0, and Textual's ``move_cursor`` then re-anchors the cursor
    row at the *bottom* of the visible window. Every Space press
    dragged the user's focus down to the bottom of the viewport.

    Pin: after Space, the panel's ``scroll_y`` is non-zero (we were
    mid-list before pressing Space; we should still be mid-list
    after).
    """
    # Lay down 200 dummy files so the list is unambiguously
    # scrollable.
    left = tmp_path / "L"
    right = tmp_path / "R"
    left.mkdir()
    right.mkdir()
    for i in range(200):
        (left / f"file_{i:03d}.dat").write_text("x", encoding="utf-8")

    from sansdir.app import SansdirApp

    history = CommandHistory(path=tmp_path / "hist", load=False)
    app = SansdirApp(start_path=left, right_path=right, history=history)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        panel = app.active_panel
        # Step cursor far enough that we have to scroll. PageDown
        # is faster than 80 Down keystrokes.
        for _ in range(4):
            await pilot.press("pagedown")
            await pilot.pause()
        scroll_before = float(panel.scroll_y)
        cursor_before = panel.cursor_row
        # Sanity: we're actually scrolled.
        assert scroll_before > 0, (
            f"test fixture wasn't scrolled; cursor={cursor_before}, "
            f"scroll_y={scroll_before}"
        )
        # Press Space — should tag-and-advance, but scroll should
        # only move if the new cursor row is off-screen, NOT snap
        # the view back to top.
        await pilot.press("space")
        await pilot.pause()
        scroll_after = float(panel.scroll_y)
        cursor_after = panel.cursor_row
        # Cursor advanced by one (tag-and-advance semantic).
        assert cursor_after == cursor_before + 1
        # Scroll didn't reset to top. Allow a small increment if the
        # new cursor row needed to scroll into view, but it should
        # NOT be near zero.
        assert scroll_after >= scroll_before - 1, (
            f"scroll snapped backwards on Space: {scroll_before} -> {scroll_after}"
        )
        await pilot.press("q")


async def test_f8_delete_keeps_cursor_near_deleted_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After delete + refresh the cursor lands on the entry just below
    (or the new last row), not back at row 0 — mc / Norton convention.
    Without this preservation users have to scroll back every time
    they delete a single file from a long listing.
    """
    import sys
    import types

    fake_mod = types.ModuleType("send2trash")
    fake_mod.send2trash = lambda p: Path(p).unlink()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "send2trash", fake_mod)

    # _scratch lays down: a.dat, b.dat, noise.txt (sorted alphabetically
    # under default sort, with ``..`` at row 0).
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Step the cursor to ``b.dat`` (row 2: ``..`` at 0, ``a.dat``
        # at 1, ``b.dat`` at 2).
        await pilot.press("down")
        await pilot.press("down")
        await pilot.pause()
        assert app.active_panel.current_entry.name == "b.dat"
        # Delete via F8 → confirm.
        await pilot.press("f8")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        # ``b.dat`` is gone; the row index 2 now points to
        # ``noise.txt`` (the file that was below it). The cursor
        # should land there, NOT on row 0.
        cur = app.active_panel.current_entry
        assert cur is not None
        assert cur.name == "noise.txt", (
            f"cursor jumped away from the delete site to {cur.name!r}"
        )
        await pilot.press("q")


async def test_f8_delete_last_file_clamps_to_new_last(tmp_path: Path) -> None:
    """If the cursor was on the bottom-most file, after delete it
    sticks to the new bottom rather than going to row 0.
    """
    import sys
    import types

    fake_mod = types.ModuleType("send2trash")
    fake_mod.send2trash = lambda p: Path(p).unlink()  # type: ignore[attr-defined]

    import pytest as _pytest
    monkey = _pytest.MonkeyPatch()
    monkey.setitem(sys.modules, "send2trash", fake_mod)
    try:
        app = _real_app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Default sort: ``..``, ``a.dat``, ``b.dat``, ``noise.txt``.
            # Step to noise.txt (row 3).
            for _ in range(3):
                await pilot.press("down")
            await pilot.pause()
            assert app.active_panel.current_entry.name == "noise.txt"
            await pilot.press("f8")
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            cur = app.active_panel.current_entry
            assert cur is not None
            # noise.txt was at row 3; new list has 3 entries (``..``,
            # ``a.dat``, ``b.dat``). Cursor clamps to row 2 = ``b.dat``.
            assert cur.name == "b.dat"
            await pilot.press("q")
    finally:
        monkey.undo()


async def test_f2_renames_cursor_file(tmp_path: Path) -> None:
    """F2 → rename dialog → new name → file renamed in-place,
    cursor follows the renamed file."""
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Cursor on a.dat (row 1).
        await pilot.press("down")
        await pilot.pause()
        assert app.active_panel.current_entry.name == "a.dat"
        await pilot.press("f2")
        await pilot.pause()
        # The TextPromptDialog is open with "a.dat" pre-filled.
        from sansdir.ui.dialogs import TextPromptDialog

        dialog = next(
            s for s in app.screen_stack if isinstance(s, TextPromptDialog)
        )
        # Replace the pre-filled value.
        from textual.widgets import Input

        inp = dialog.query_one(Input)
        inp.value = "renamed.dat"
        await pilot.press("enter")
        await pilot.pause()
        left = app.active_panel.cwd
        assert not (left / "a.dat").exists()
        assert (left / "renamed.dat").exists()
        # Cursor should now be on the renamed file.
        cur = app.active_panel.current_entry
        assert cur is not None
        assert cur.name == "renamed.dat"
        await pilot.press("q")


async def test_f2_on_parent_row_notifies(tmp_path: Path) -> None:
    """F2 with the cursor on ``..`` warns instead of crashing."""
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Cursor starts on ``..``.
        assert app.active_panel.current_entry.is_parent
        await pilot.press("f2")
        await pilot.pause()
        # No dialog pushed.
        from sansdir.ui.dialogs import TextPromptDialog

        assert not any(isinstance(s, TextPromptDialog) for s in app.screen_stack)
        await pilot.press("q")


async def test_f8_no_skips_when_user_declines(tmp_path: Path) -> None:
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("+")
        for ch in "*.dat":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("f8")
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        # Files still present.
        assert (app.active_panel.cwd / "a.dat").exists()
        assert (app.active_panel.cwd / "b.dat").exists()
        await pilot.press("q")
