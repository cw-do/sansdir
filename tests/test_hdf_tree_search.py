"""Keyword search inside the ``m`` HDF5 tree modal (:class:`HdfTreeScreen`)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from textual.widgets import DataTable, Input, Static, Tree

from sansdir.app import SansdirApp
from sansdir.core.history import CommandHistory
from sansdir.ui.hdf_tree import HdfTreeScreen


@pytest.fixture(autouse=True)
def isolate_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path / "cache"))


def _write_nx(path: Path) -> None:
    import h5py

    with h5py.File(path, "w") as fh:
        entry = fh.create_group("entry")
        entry.create_dataset("duration", data=np.float64(600.0))
        daslogs = entry.create_group("DASlogs")
        for name in ("temperature", "shear", "sample_position"):
            grp = daslogs.create_group(name)
            grp.create_dataset("value", data=np.linspace(0.0, 1.0, 10))
            grp.create_dataset("time", data=np.linspace(0.0, 600.0, 10))


def _app(tmp_path: Path) -> tuple[SansdirApp, Path]:
    left = tmp_path / "L"
    right = tmp_path / "R"
    left.mkdir()
    right.mkdir()
    target = left / "EQSANS_001.nxs.h5"
    _write_nx(target)
    app = SansdirApp(
        start_path=left,
        right_path=right,
        history=CommandHistory(path=tmp_path / "hist", load=False),
    )
    return app, target


async def test_search_filters_keys_and_updates_detail(tmp_path: Path) -> None:
    """``/`` + a substring lists matching keys; the cursor row drives the detail pane."""
    app, target = _app(tmp_path)
    async with app.run_test() as pilot:
        app.push_screen(HdfTreeScreen(target))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, HdfTreeScreen)

        await pilot.press("slash")
        await pilot.pause()
        assert isinstance(screen.focused, Input)

        for ch in "temperature":
            await pilot.press(ch)
        # The walk runs in a worker; wait for it to land.
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert screen.has_class("-searching")
        table = screen.query_one("#hdf-search-results", DataTable)
        paths = [str(table.get_row_at(r)[0]) for r in range(table.row_count)]
        assert paths, "expected at least one match"
        assert all("temperature" in p for p in paths)
        assert "/entry/DASlogs/temperature/value" in paths

        detail = str(screen.query_one("#hdf-detail", Static).render())
        assert "temperature" in detail


async def test_search_is_case_insensitive_and_clearing_restores_tree(tmp_path: Path) -> None:
    """Uppercase query still matches; emptying the box returns to tree mode."""
    app, target = _app(tmp_path)
    async with app.run_test() as pilot:
        app.push_screen(HdfTreeScreen(target))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, HdfTreeScreen)

        await pilot.press("slash")
        for ch in "SHEAR":
            await pilot.press(ch)
        await app.workers.wait_for_complete()
        await pilot.pause()
        table = screen.query_one("#hdf-search-results", DataTable)
        assert table.row_count > 0

        # Esc backs out of search but keeps the modal open.
        await pilot.press("escape")
        await pilot.pause()
        assert not screen.has_class("-searching")
        assert app.screen is screen
        assert screen.query_one("#hdf-search", Input).value == ""
        assert isinstance(screen.focused, Tree)

        # A second Esc closes the modal.
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, HdfTreeScreen)


async def test_search_with_no_match_reports_empty(tmp_path: Path) -> None:
    """A query matching nothing clears the table rather than erroring."""
    app, target = _app(tmp_path)
    async with app.run_test() as pilot:
        app.push_screen(HdfTreeScreen(target))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, HdfTreeScreen)

        await pilot.press("slash")
        for ch in "zzz":
            await pilot.press(ch)
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert screen.query_one("#hdf-search-results", DataTable).row_count == 0
        assert "no match" in str(screen.query_one("#hdf-detail", Static).render())
