"""End-to-end Pilot tests for the ``:``-input."""

from __future__ import annotations

from pathlib import Path

from sansdir.app import SansdirApp
from sansdir.core.history import CommandHistory


def _scratch(tmp_path: Path) -> tuple[Path, Path]:
    left = tmp_path / "L"
    right = tmp_path / "R"
    left.mkdir()
    right.mkdir()
    (left / "child").mkdir()
    return left, right


def _app(tmp_path: Path, hist_path: Path | None = None) -> SansdirApp:
    left, right = _scratch(tmp_path)
    history = CommandHistory(path=hist_path or tmp_path / "hist", load=False)
    return SansdirApp(start_path=left, right_path=right, history=history)


# ---------------------------------------------------------------------------
# Focus / cancel
# ---------------------------------------------------------------------------


async def test_colon_focuses_command_line(tmp_path: Path) -> None:
    app = _app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.focused is app.active_panel
        await pilot.press(":")
        await pilot.pause()
        assert app.focused is app._cmdline


async def test_escape_returns_focus_to_active_pane(tmp_path: Path) -> None:
    app = _app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press(":")
        await pilot.pause()
        assert app.focused is app._cmdline
        await pilot.press("escape")
        await pilot.pause()
        assert app.focused is app.active_panel


async def test_typing_in_cmdline_is_not_intercepted_by_keymap(tmp_path: Path) -> None:
    app = _app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press(":")
        await pilot.pause()
        # Typing 'q' would normally quit, but the cmdline owns the keys now.
        await pilot.press("q")
        await pilot.pause()
        assert app.focused is app._cmdline
        assert app._cmdline.value == "q"


async def test_prompt_prefix_renders_in_cmdline_row(tmp_path: Path) -> None:
    """The bottom row shows ``> `` before whatever the user is typing.

    Verified by exporting an SVG screenshot and looking for both the
    prompt and the typed text on the same row.
    """
    app = _app(tmp_path)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press(":")
        for ch in "help":
            await pilot.press(ch)
        await pilot.pause()
        svg = app.export_screenshot()
        # The prompt is rendered as `&gt; ` (HTML-escaped) and `help`
        # immediately after on the same y-coordinate.
        assert "&gt;" in svg, "prompt `>` not found in rendered SVG"
        assert ">help<" in svg, "typed value not found in rendered SVG"


async def test_typing_after_colon_inserts_full_word(tmp_path: Path) -> None:
    """Regression: pressing `:` then typing immediately must accept every
    character. A previous version of `_dispatch` ran *all* handlers as
    workers, so the focus-shift from `app.cmdline_open` lagged behind the
    next keystroke and the keymap re-intercepted letters with bindings
    (`g`, `h`, `q`, etc.).
    """
    app = _app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press(":")
        # No pause between `:` and the first letter — exactly what a user
        # who types fluidly would do.
        await pilot.press("h")
        await pilot.press("e")
        await pilot.press("l")
        await pilot.press("p")
        await pilot.pause()
        assert app.focused is app._cmdline, "cmdline did not actually receive focus"
        assert app._cmdline.value == "help", (
            f"expected 'help' in cmdline, got {app._cmdline.value!r}"
        )


# ---------------------------------------------------------------------------
# Submission → registry dispatch
# ---------------------------------------------------------------------------


async def test_typing_quit_command_quits(tmp_path: Path) -> None:
    app = _app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press(":")
        await pilot.pause()
        for ch in "quit":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
    assert app.return_code == 0


async def test_typing_cd_changes_active_pane(tmp_path: Path) -> None:
    app = _app(tmp_path)
    left, _ = _scratch(tmp_path) if False else (app.active_panel.cwd, None)  # type: ignore[assignment]
    async with app.run_test() as pilot:
        await pilot.pause()
        target = left / "child"
        await pilot.press(":")
        for ch in f"cd {target}":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        assert app.active_panel.cwd == target.resolve()
        await pilot.press("q")


async def test_unknown_command_does_not_crash(tmp_path: Path) -> None:
    app = _app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press(":")
        for ch in "nopecmd":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        # App still alive, focus back on pane.
        assert app.focused is app.active_panel
        await pilot.press("q")


# ---------------------------------------------------------------------------
# History (Up / Down)
# ---------------------------------------------------------------------------


async def test_up_arrow_walks_history(tmp_path: Path) -> None:
    hist_path = tmp_path / "hist"
    hist = CommandHistory(path=hist_path, load=False)
    hist.extend(["help", "cd /tmp", "set_sort key=mtime"])
    left, right = _scratch(tmp_path)
    app = SansdirApp(start_path=left, right_path=right, history=hist)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press(":")
        await pilot.pause()
        await pilot.press("up")
        await pilot.pause()
        assert app._cmdline.value == "set_sort key=mtime"
        await pilot.press("up")
        await pilot.pause()
        assert app._cmdline.value == "cd /tmp"
        await pilot.press("up")
        await pilot.pause()
        assert app._cmdline.value == "help"
        # Past the bottom — stays on oldest.
        await pilot.press("up")
        await pilot.pause()
        assert app._cmdline.value == "help"
        # Down restores intermediate steps and finally the draft (empty).
        await pilot.press("down")
        await pilot.pause()
        assert app._cmdline.value == "cd /tmp"
        await pilot.press("escape")
        await pilot.press("q")


async def test_submit_appends_to_history_and_persists(tmp_path: Path) -> None:
    hist_path = tmp_path / "hist"
    hist = CommandHistory(path=hist_path, load=False)
    left, right = _scratch(tmp_path)
    app = SansdirApp(start_path=left, right_path=right, history=hist)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press(":")
        for ch in "help":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("q")
    # Loaded fresh from disk, the entry should be there.
    h2 = CommandHistory(path=hist_path)
    assert "help" in h2.entries()


# ---------------------------------------------------------------------------
# Tab completion
# ---------------------------------------------------------------------------


async def test_tab_completes_unique_command(tmp_path: Path) -> None:
    app = _app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press(":")
        # "nav.c" → unique completion → "nav.cd "
        for ch in "nav.c":
            await pilot.press(ch)
        await pilot.press("tab")
        await pilot.pause()
        assert app._cmdline.value == "nav.cd "
        await pilot.press("escape")
        await pilot.press("q")


async def test_tab_extends_to_common_prefix(tmp_path: Path) -> None:
    app = _app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press(":")
        # "pa" matches pane.activate, pane.swap, pane.sync, pane.toggle_max,
        # pane.toggle_catalog → common prefix "pane.".
        # ("p" alone now matches plot.* too, which would have only "p" as
        # the common prefix.)
        await pilot.press("p")
        await pilot.press("a")
        await pilot.press("tab")
        await pilot.pause()
        assert app._cmdline.value == "pane."
        await pilot.press("escape")
        await pilot.press("q")
