"""The `d` key and the two-pane SANS picker.

The interaction is the point here: a single curve offers to pair with a SANS
measurement, and the question goes in *one* pane while the user browses in the
*other* — a modal would hide the file list they need to read. A batch skips
the question entirely, because a high-Q companion has to be matched per
sample and cannot be guessed for a whole folder.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np

from sansdir.app import SansdirApp
from sansdir.ui.keys import default_keymap
from sansdir.usans.desmear import smear


def _run(coro) -> None:  # type: ignore[no-untyped-def]
    asyncio.run(coro)


def _truth(q):  # type: ignore[no-untyped-def]
    return 1e-6 * np.asarray(q, dtype=float) ** -4.0


def make_usans(path: Path, n: int = 60) -> Path:
    q = np.geomspace(5e-5, 3e-3, n)
    i = smear(_truth, q)
    d = 0.02 * i
    path.write_text(
        "".join(f"{a:.6e},{b:.6e},{c:.6e},\n" for a, b, c in zip(q, i, d, strict=True)),
        encoding="utf-8",
    )
    return path


def make_sans(path: Path) -> Path:
    q = np.geomspace(1e-3, 0.5, 80)
    i = _truth(q)
    path.write_text(
        "".join(f"{a:.6e} {b:.6e} {c:.6e}\n" for a, b, c in zip(q, i, 0.02 * i, strict=True)),
        encoding="utf-8",
    )
    return path


def _usans_dir(tmp_path: Path) -> Path:
    work = tmp_path / "usans" / "IPTS-1" / "shared"
    work.mkdir(parents=True)
    return work


async def _settle(pilot, predicate, tries: int = 60) -> None:  # type: ignore[no-untyped-def]
    for _ in range(tries):
        await asyncio.sleep(0.05)
        await pilot.pause()
        if predicate():
            return


# ---------------------------------------------------------------------------
# Key scoping
# ---------------------------------------------------------------------------


def test_d_is_usans_only_and_names_a_real_command(tmp_path: Path) -> None:
    from sansdir.commands.builtins import build_default_registry
    from tests.test_phase1_commands import FakeApp, FakePanel

    assert "d" not in {kb.key for kb in default_keymap()}
    usans = [kb for kb in default_keymap(mode="USANS") if kb.key == "d"]
    assert len(usans) == 1 and usans[0].command == "usans.desmear"
    app = FakeApp(left=FakePanel(cwd=tmp_path), right=FakePanel(cwd=tmp_path))
    assert "usans.desmear" in {c.name for c in build_default_registry(app=app).all()}


# ---------------------------------------------------------------------------
# Batch: no question
# ---------------------------------------------------------------------------


def test_batch_desmears_usans_only_without_asking(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))
    work = _usans_dir(tmp_path)
    for name in ("UN_A_det_1_bsub.txt", "UN_B_det_1_bsub.txt"):
        make_usans(work / name)

    async def _drive() -> None:
        app = SansdirApp(start_path=work)
        async with app.run_test() as pilot:
            await pilot.pause()
            for name in ("UN_A_det_1_bsub.txt", "UN_B_det_1_bsub.txt"):
                app.active_panel.move_cursor_to_path(work / name)
                app.active_panel.toggle_tag()
            await pilot.pause()
            await pilot.press("d")
            await _settle(pilot, lambda: len(list(work.glob("*_desmeared.txt"))) >= 2)

            assert len(list(work.glob("*_desmeared.txt"))) == 2
            assert not app._left_slot.prompt_visible, "a batch must not ask about SANS"
            assert "usans-only" in (work / "UN_A_det_1_bsub_desmeared.txt").read_text()

    _run(_drive())


# ---------------------------------------------------------------------------
# Single: the two-pane question
# ---------------------------------------------------------------------------


def test_single_curve_asks_in_one_pane_and_picks_in_the_other(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))
    work = _usans_dir(tmp_path)
    curve = make_usans(work / "UN_A_det_1_bsub.txt")
    make_sans(work / "EQSANS_A_merged.txt")

    async def _drive() -> None:
        app = SansdirApp(start_path=work)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.active_panel.move_cursor_to_path(curve)
            await pilot.pause()
            await pilot.press("d")
            await _settle(pilot, lambda: app._left_slot.prompt_visible)

            # Question in the pane the user was in; file list in the other.
            assert app._left_slot.prompt_visible
            assert app._right_slot.mode == "list"
            # The picking pane is active, so arrows and `/` work natively.
            assert app._active_id == "right"
            assert "SANS" in str(app._left_slot.prompt._body.content)

            app.active_panel.move_cursor_to_path(work / "EQSANS_A_merged.txt")
            await pilot.pause()
            await pilot.press("enter")
            await _settle(pilot, lambda: bool(list(work.glob("*_desmeared.txt"))))

            out = work / "UN_A_det_1_bsub_desmeared.txt"
            assert out.is_file()
            text = out.read_text()
            assert "mode: with-sans" in text
            assert "EQSANS_A_merged.txt" in text
            # Panes restored, cursor left on the new file.
            assert app._left_slot.mode == "list" and app._right_slot.mode == "list"
            assert app._active_id == "left"
            assert app.active_panel.cursor_path == out

    _run(_drive())


def test_escape_declines_and_falls_back_to_usans_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))
    work = _usans_dir(tmp_path)
    curve = make_usans(work / "UN_A_det_1_bsub.txt")
    make_sans(work / "EQSANS_A_merged.txt")

    async def _drive() -> None:
        app = SansdirApp(start_path=work)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.active_panel.move_cursor_to_path(curve)
            await pilot.pause()
            await pilot.press("d")
            await _settle(pilot, lambda: app._left_slot.prompt_visible)
            await pilot.press("escape")
            await _settle(pilot, lambda: bool(list(work.glob("*_desmeared.txt"))))

            text = (work / "UN_A_det_1_bsub_desmeared.txt").read_text()
            assert "mode: usans-only" in text
            assert "WARNING - no SANS data was supplied." in text
            assert app._left_slot.mode == "list"
            assert app._active_id == "left"

    _run(_drive())


def test_quit_is_suppressed_while_the_picker_is_open(tmp_path: Path, monkeypatch) -> None:
    """`q` must not quit out from under a pending question."""
    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))
    work = _usans_dir(tmp_path)
    curve = make_usans(work / "UN_A_det_1_bsub.txt")

    async def _drive() -> None:
        app = SansdirApp(start_path=work)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.active_panel.move_cursor_to_path(curve)
            await pilot.pause()
            await pilot.press("d")
            await _settle(pilot, lambda: app._left_slot.prompt_visible)
            await pilot.press("q")
            await pilot.pause()
            assert app._pick_future is not None, "still waiting for an answer"
            assert app.is_running
            await pilot.press("escape")
            await _settle(pilot, lambda: app._pick_future is None)

    _run(_drive())


def test_non_curve_selection_is_reported_not_crashed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))
    work = _usans_dir(tmp_path)
    setup = work / "IPTS-1_setup.csv"
    setup.write_text("b,E,100,4,0.1\n", encoding="utf-8")

    async def _drive() -> None:
        app = SansdirApp(start_path=work)
        notes: list[str] = []
        app.notify = lambda m, **k: notes.append(str(m))  # type: ignore[method-assign]
        async with app.run_test() as pilot:
            await pilot.pause()
            app.active_panel.move_cursor_to_path(setup)
            await pilot.pause()
            await pilot.press("d")
            await _settle(pilot, lambda: bool(notes))
            assert not list(work.glob("*_desmeared.txt"))
            assert any("no reduced I(Q) curves" in n for n in notes)

    _run(_drive())
