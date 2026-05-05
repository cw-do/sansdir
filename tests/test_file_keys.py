"""End-to-end tests for the F5/F6/F7/F8 file-op keys."""

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
# F7 mkdir (via cmdline prompt)
# ---------------------------------------------------------------------------


async def test_f7_prompts_for_mkdir(tmp_path: Path) -> None:
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f7")
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
# F5 / F6 copy / move (with confirm dialog)
# ---------------------------------------------------------------------------


async def _confirm_yes(pilot) -> None:  # type: ignore[no-untyped-def]
    """Helper: press Enter twice (focus + confirm) to accept a ConfirmDialog."""
    await pilot.press("enter")
    await pilot.pause()


async def test_f5_copy_tagged_to_other_pane(tmp_path: Path) -> None:
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
        # F5 → confirm dialog → Yes
        await pilot.press("f5")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        right = app.inactive_panel.cwd
        assert (right / "a.dat").read_text(encoding="utf-8") == "aa"
        assert (right / "b.dat").read_text(encoding="utf-8") == "bb"
        # Sources untouched.
        assert (app.active_panel.cwd / "a.dat").exists()
        await pilot.press("q")


async def test_f5_no_selection_notifies(tmp_path: Path) -> None:
    """No tags, cursor on '..' — F5 should warn, not crash."""
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Cursor starts on '..' — selection() is empty.
        await pilot.press("f5")
        await pilot.pause()
        # No copy happened; right pane unchanged.
        right_files = list(app.inactive_panel.cwd.iterdir())
        assert right_files == []
        await pilot.press("q")


async def test_f6_move_tagged_to_other_pane(tmp_path: Path) -> None:
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
        await pilot.press("y")
        await pilot.pause()
        left = app.active_panel.cwd
        right = app.inactive_panel.cwd
        assert not (left / "a.dat").exists()
        assert (right / "a.dat").exists()
        await pilot.press("q")


async def test_f5_can_be_cancelled(tmp_path: Path) -> None:
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("+")
        for ch in "*.dat":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("f5")
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
