"""Tests for tag commands and Pilot end-to-end tagging."""

from __future__ import annotations

from pathlib import Path

from sansdir.app import SansdirApp
from sansdir.commands.builtins import build_default_registry
from sansdir.core.history import CommandHistory
from tests.test_phase1_commands import FakeApp, FakePanel

# ---------------------------------------------------------------------------
# Unit-level: tag.* commands against the FakeApp
# ---------------------------------------------------------------------------


def _bound_app(tmp_path: Path, names: list[str]) -> FakeApp:
    cwd = tmp_path / "L"
    cwd.mkdir(exist_ok=True)
    visible = []
    for n in names:
        p = cwd / n
        p.write_text("x", encoding="utf-8")
        visible.append(p)
    panel = FakePanel(cwd=cwd, visible=visible, cursor_path=visible[0] if visible else None)
    return FakeApp(left=panel, right=FakePanel(cwd=tmp_path / "R"))


async def test_tag_toggle_via_dispatch(tmp_path: Path) -> None:
    app = _bound_app(tmp_path, ["a.txt", "b.txt"])
    reg = build_default_registry(app=app)
    await reg.dispatch("tag.toggle")
    assert app.left.tags == {app.left.cursor_path}
    assert app.left.cursor_advances == 1


async def test_tag_toggle_no_advance(tmp_path: Path) -> None:
    app = _bound_app(tmp_path, ["a.txt"])
    reg = build_default_registry(app=app)
    await reg.dispatch("tag.toggle", advance=False)
    assert app.left.cursor_advances == 0


async def test_tag_glob_matches_visible(tmp_path: Path) -> None:
    app = _bound_app(
        tmp_path,
        ["a_Iq.dat", "b_Iq.dat", "trans.txt", "noise.dat"],
    )
    reg = build_default_registry(app=app)
    n = await reg.dispatch("tag.glob", pattern="*Iq*.dat")
    assert n == 2
    tagged_names = {p.name for p in app.left.tags}
    assert tagged_names == {"a_Iq.dat", "b_Iq.dat"}


async def test_tag_untag_glob_removes(tmp_path: Path) -> None:
    app = _bound_app(tmp_path, ["a_Iq.dat", "b_Iq.dat", "c.txt"])
    reg = build_default_registry(app=app)
    await reg.dispatch("tag.glob", pattern="*")
    assert len(app.left.tags) == 3
    n = await reg.dispatch("tag.untag_glob", pattern="*Iq*.dat")
    assert n == 2
    assert {p.name for p in app.left.tags} == {"c.txt"}


async def test_tag_clear(tmp_path: Path) -> None:
    app = _bound_app(tmp_path, ["a", "b"])
    reg = build_default_registry(app=app)
    await reg.dispatch("tag.glob", pattern="*")
    n = await reg.dispatch("tag.clear")
    assert n == 2
    assert app.left.tags == set()


async def test_app_cmdline_prompt_dispatches(tmp_path: Path) -> None:
    app = _bound_app(tmp_path, ["a"])
    reg = build_default_registry(app=app)
    await reg.dispatch("app.cmdline_prompt", text="tag.glob ")
    assert app.cmdline_prompts == ["tag.glob "]


# ---------------------------------------------------------------------------
# End-to-end: tag through the real app via Pilot
# ---------------------------------------------------------------------------


def _scratch(tmp_path: Path) -> tuple[Path, Path]:
    left = tmp_path / "L"
    right = tmp_path / "R"
    left.mkdir()
    right.mkdir()
    (left / "a_Iq.dat").write_text("0", encoding="utf-8")
    (left / "b_Iq.dat").write_text("0", encoding="utf-8")
    (left / "noise.dat").write_text("0", encoding="utf-8")
    return left, right


def _real_app(tmp_path: Path) -> SansdirApp:
    left, right = _scratch(tmp_path)
    history = CommandHistory(path=tmp_path / "hist", load=False)
    return SansdirApp(start_path=left, right_path=right, history=history)


async def test_space_toggles_tag_and_advances(tmp_path: Path) -> None:
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Cursor starts on row 0 (..); space on parent must be a no-op.
        await pilot.press("space")
        await pilot.pause()
        assert app.active_panel.tags == set()
        # Step down to first real entry, then tag.
        await pilot.press("down")
        await pilot.pause()
        before_row = app.active_panel.cursor_row
        await pilot.press("space")
        await pilot.pause()
        assert len(app.active_panel.tags) == 1
        assert app.active_panel.cursor_row == before_row + 1
        await pilot.press("q")


async def test_plus_opens_cmdline_with_tag_glob_prefix(tmp_path: Path) -> None:
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("+")
        await pilot.pause()
        assert app.focused is app._cmdline
        assert app._cmdline.value == "tag.glob "
        # Type a glob and submit.
        for ch in "*Iq*.dat":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        names = {p.name for p in app.active_panel.tags}
        assert names == {"a_Iq.dat", "b_Iq.dat"}
        await pilot.press("q")


async def test_minus_opens_cmdline_with_untag_glob_prefix(tmp_path: Path) -> None:
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("+")
        await pilot.pause()
        for ch in "*":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.active_panel.tags) >= 1
        await pilot.press("-")
        await pilot.pause()
        assert app._cmdline.value == "tag.untag_glob "
        for ch in "*Iq*.dat":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        names = {p.name for p in app.active_panel.tags}
        assert names == {"noise.dat"}
        await pilot.press("q")


async def test_tags_clear_on_cd(tmp_path: Path) -> None:
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("+")
        for ch in "*":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        assert app.active_panel.tags
        # cd to parent (Backspace).
        await pilot.press("backspace")
        await pilot.pause()
        assert app.active_panel.tags == set()
        await pilot.press("q")
