"""Panes must not keep pointing at things that no longer exist.

Three states used to be reachable, none of which raised — which was the
problem, since a silently-wrong pane is worse than an error:

* a pane sitting *inside* a directory deleted from the other pane: zero
  rows at a dead path, indistinguishable from an empty directory;
* an inline viewer still rendering a file that had been deleted;
* a stale row in a deleted directory, where ``Enter`` recovered only by
  luck (if the cursor happened to be on ``..``).

The repair is in :meth:`FilePanel.refresh_listing` (re-anchor to the
nearest surviving ancestor) and :meth:`PaneSlot.revalidate` (drop a ghost
viewer), so it also covers deletions sansdir didn't make — ``:!rm``, or
another user on a shared filesystem.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from sansdir.app import SansdirApp


def _run(coro) -> None:  # type: ignore[no-untyped-def]
    asyncio.run(coro)


def _auto_confirm(app: SansdirApp) -> None:
    """Answer ``ui.delete_tagged``'s modal automatically.

    Without this the dispatch awaits a ConfirmDialog nobody ever answers
    and the test hangs rather than fails.
    """

    async def _yes(_message: str, *, danger: bool = False) -> bool:
        return True

    app.confirm = _yes  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# FilePanel re-anchoring (unit level — no app needed)
# ---------------------------------------------------------------------------


def test_refresh_reanchors_out_of_a_deleted_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "inside.txt").write_text("x", encoding="utf-8")

    async def _drive() -> None:
        app = SansdirApp(start_path=tmp_path, right_path=victim)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._right.cwd == victim
            shutil.rmtree(victim)
            app._right.refresh_listing()
            await pilot.pause()
            assert app._right.cwd == tmp_path, "should climb to the surviving parent"
            assert app._right.cwd.is_dir()

    _run(_drive())


def test_reanchor_climbs_past_several_dead_levels(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)

    async def _drive() -> None:
        app = SansdirApp(start_path=tmp_path, right_path=deep)
        async with app.run_test() as pilot:
            await pilot.pause()
            shutil.rmtree(tmp_path / "a")
            app._right.refresh_listing()
            await pilot.pause()
            assert app._right.cwd == tmp_path

    _run(_drive())


def test_reanchor_drops_tags_and_filter(tmp_path: Path, monkeypatch) -> None:
    """Both referred to a directory that is gone."""
    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "a.txt").write_text("x", encoding="utf-8")

    async def _drive() -> None:
        app = SansdirApp(start_path=tmp_path, right_path=victim)
        async with app.run_test() as pilot:
            await pilot.pause()
            app._right.tags.add(victim / "a.txt")
            app._right.filter_substring = "a"
            await pilot.pause()
            shutil.rmtree(victim)
            app._right.refresh_listing()
            await pilot.pause()
            assert app._right.tags == set()
            assert app._right.filter_substring == ""

    _run(_drive())


def test_refresh_is_untouched_for_a_live_directory(tmp_path: Path, monkeypatch) -> None:
    """The happy path must not move anything."""
    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))
    live = tmp_path / "live"
    live.mkdir()
    (live / "a.txt").write_text("x", encoding="utf-8")

    async def _drive() -> None:
        app = SansdirApp(start_path=tmp_path, right_path=live)
        async with app.run_test() as pilot:
            await pilot.pause()
            app._right.tags.add(live / "a.txt")
            app._right.refresh_listing()
            await pilot.pause()
            assert app._right.cwd == live
            assert app._right.tags == {live / "a.txt"}

    _run(_drive())


# ---------------------------------------------------------------------------
# Ghost viewer
# ---------------------------------------------------------------------------


def test_viewer_closes_when_its_file_is_deleted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))
    note = tmp_path / "note.md"
    note.write_text("original content", encoding="utf-8")

    async def _drive() -> None:
        app = SansdirApp(start_path=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.view_in_other_pane(note)
            await pilot.pause()
            assert app._right_slot.viewer_visible

            note.unlink()
            app.revalidate_panes()
            await pilot.pause()

            assert not app._right_slot.viewer_visible, "must not render a deleted file"
            assert app._right_slot.mode == "list"
            assert app._right_slot.viewer.path is None

    _run(_drive())


def test_viewer_survives_a_refresh_while_its_file_lives(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))
    note = tmp_path / "note.md"
    note.write_text("still here", encoding="utf-8")

    async def _drive() -> None:
        app = SansdirApp(start_path=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.view_in_other_pane(note)
            await pilot.pause()
            app.revalidate_panes()
            await pilot.pause()
            assert app._right_slot.viewer_visible

    _run(_drive())


# ---------------------------------------------------------------------------
# End-to-end: F8 delete from the left pane
# ---------------------------------------------------------------------------


def test_deleting_a_folder_the_other_pane_is_inside(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "inside.txt").write_text("x", encoding="utf-8")

    async def _drive() -> None:
        app = SansdirApp(start_path=tmp_path, right_path=victim)
        async with app.run_test() as pilot:
            await pilot.pause()
            app._left.move_cursor_to_path(victim)
            _auto_confirm(app)
            await pilot.pause()
            await app.registry.dispatch("ui.delete_tagged")
            await pilot.pause()

            assert not victim.exists()
            assert app._right.cwd == tmp_path, "right pane must not sit on a dead path"

    _run(_drive())


def test_deleting_a_file_the_other_pane_is_viewing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))
    note = tmp_path / "note.md"
    note.write_text("original content", encoding="utf-8")

    async def _drive() -> None:
        app = SansdirApp(start_path=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.view_in_other_pane(note)
            await pilot.pause()
            app._left.move_cursor_to_path(note)
            _auto_confirm(app)
            await pilot.pause()
            await app.registry.dispatch("ui.delete_tagged")
            await pilot.pause()

            assert not note.exists()
            assert not app._right_slot.viewer_visible

    _run(_drive())


def test_f5_repairs_an_externally_deleted_directory(tmp_path: Path, monkeypatch) -> None:
    """Covers `:!rm`, another user, an unmounted share — not just our delete."""
    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))
    victim = tmp_path / "victim"
    victim.mkdir()

    async def _drive() -> None:
        app = SansdirApp(start_path=tmp_path, right_path=victim)
        async with app.run_test() as pilot:
            await pilot.pause()
            shutil.rmtree(victim)
            await app.registry.dispatch("ui.refresh")
            await pilot.pause()
            assert app._right.cwd == tmp_path

    _run(_drive())
