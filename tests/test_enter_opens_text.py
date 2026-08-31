"""``Enter`` on a readable text file previews it in the other pane.

Enter used to fall through to ``nav.cd`` for every non-directory,
non-image path, so pressing it on a ``NOTE.md`` / ``_Iq.dat`` / setup CSV
produced a bare ``NotADirectoryError``. It now routes anything that
sniffs as text to the same in-pane viewer ``F3`` opens.

Binary files (``.nxs.h5`` above all) must keep the old fallback: the
viewer would only flash open and dismiss itself.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sansdir.core.filesystem import is_text_file
from tests.test_phase1_commands import FakeApp, FakePanel, bind_registry

# The first 8 bytes of every HDF5 / NeXus file.
HDF5_MAGIC = b"\x89HDF\r\n\x1a\n"


@pytest.fixture
def app(tmp_path: Path) -> FakeApp:
    left = tmp_path / "L"
    right = tmp_path / "R"
    left.mkdir()
    right.mkdir()
    return FakeApp(left=FakePanel(cwd=left), right=FakePanel(cwd=right))


# ---------------------------------------------------------------------------
# is_text_file — content sniff, not an extension allowlist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["IPTS-1_NOTE.md", "setup.csv", "notes.txt", "run_Iq.dat", "reduction.log", "README"],
)
def test_text_files_are_recognised(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_text("q,I,E\n1e-4,12.0,0.3\n", encoding="utf-8")
    assert is_text_file(path)


def test_nexus_is_not_text(tmp_path: Path) -> None:
    path = tmp_path / "EQSANS_172749.nxs.h5"
    path.write_bytes(HDF5_MAGIC + b"\x00" * 64)
    assert not is_text_file(path)


def test_empty_file_counts_as_text(tmp_path: Path) -> None:
    path = tmp_path / "empty.dat"
    path.write_bytes(b"")
    assert is_text_file(path)


def test_utf8_text_is_not_mistaken_for_binary(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text("# λ = 6 Å — 2θ scan\n", encoding="utf-8")
    assert is_text_file(path)


def test_missing_or_directory_paths_are_not_text(tmp_path: Path) -> None:
    assert not is_text_file(tmp_path / "nope.txt")
    assert not is_text_file(tmp_path)


def test_nul_beyond_the_sniff_window_is_ignored(tmp_path: Path) -> None:
    """A huge text file with junk far in isn't re-read; the head decides."""
    path = tmp_path / "big.dat"
    path.write_bytes(b"a" * 9000 + b"\x00")
    assert is_text_file(path)


# ---------------------------------------------------------------------------
# Enter routing
# ---------------------------------------------------------------------------


async def test_enter_on_a_text_file_opens_the_viewer(app: FakeApp) -> None:
    note = app.left.cwd / "IPTS-1_NOTE.md"
    note.write_text("# USANS reduction notes\n", encoding="utf-8")
    app.left.cursor_path = note
    reg = bind_registry(app)

    await reg.dispatch("ui.activate_cursor")

    assert app.viewer_calls == [note]
    assert app.is_other_pane_viewing()


async def test_enter_on_a_directory_still_cds(app: FakeApp) -> None:
    child = app.left.cwd / "child"
    child.mkdir()
    app.left.cursor_path = child
    reg = bind_registry(app)

    await reg.dispatch("ui.activate_cursor")

    assert app.left.cwd == child
    assert app.viewer_calls == []


async def test_enter_on_a_binary_file_keeps_the_old_error(app: FakeApp) -> None:
    nexus = app.left.cwd / "EQSANS_172749.nxs.h5"
    nexus.write_bytes(HDF5_MAGIC + b"\x00" * 64)
    app.left.cursor_path = nexus
    reg = bind_registry(app)

    with pytest.raises(NotADirectoryError):
        await reg.dispatch("ui.activate_cursor")
    assert app.viewer_calls == []


async def test_enter_is_idempotent_and_switches_files(app: FakeApp) -> None:
    """Unlike F3, Enter never toggles the viewer shut."""
    first = app.left.cwd / "a.dat"
    second = app.left.cwd / "b.dat"
    first.write_text("1 2\n", encoding="utf-8")
    second.write_text("3 4\n", encoding="utf-8")
    reg = bind_registry(app)

    app.left.cursor_path = first
    await reg.dispatch("ui.activate_cursor")
    app.left.cursor_path = second
    await reg.dispatch("ui.activate_cursor")

    assert app.viewer_calls == [first, second]
    assert app.is_other_pane_viewing(), "second Enter must not close the viewer"


async def test_view_in_other_pane_rejects_a_directory(app: FakeApp) -> None:
    reg = bind_registry(app)
    assert await reg.dispatch("view.in_other_pane", path=str(app.left.cwd)) is False
    assert any("not a file" in n for n in app.notifications)


# ---------------------------------------------------------------------------
# The viewer frees its buffer when it stops being visible
# ---------------------------------------------------------------------------


def test_closing_the_viewer_releases_the_file_contents(tmp_path: Path, monkeypatch) -> None:
    from sansdir.app import SansdirApp

    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))
    big = tmp_path / "IPTS-1_NOTE.md"
    big.write_text("x" * 50_000, encoding="utf-8")

    async def _drive() -> None:
        app = SansdirApp(start_path=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            viewer = app._right_slot.viewer
            app.view_in_other_pane(big)
            await pilot.pause()
            assert viewer.path == big
            assert len(str(viewer._body.content)) > 10_000

            app.close_inline_viewer("right")
            await pilot.pause()
            assert viewer.path is None
            assert str(viewer._body.content) == ""

    asyncio.run(_drive())


def test_reopening_the_viewer_rereads_from_disk(tmp_path: Path, monkeypatch) -> None:
    """Clearing on close is safe precisely because nothing is cached."""
    from sansdir.app import SansdirApp

    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))
    note = tmp_path / "note.md"
    note.write_text("before\n", encoding="utf-8")

    async def _drive() -> None:
        app = SansdirApp(start_path=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.view_in_other_pane(note)
            await pilot.pause()
            app.close_inline_viewer("right")
            await pilot.pause()
            note.write_text("after\n", encoding="utf-8")
            app.view_in_other_pane(note)
            await pilot.pause()
            assert "after" in str(app._right_slot.viewer._body.content)

    asyncio.run(_drive())
