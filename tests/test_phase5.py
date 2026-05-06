"""End-to-end Pilot tests for Phase 5 — `p` plot key."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sansdir.app import SansdirApp
from sansdir.core.history import CommandHistory
from sansdir.plot import backend

DATA = Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def isolate_cache_and_force_headless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv(backend.HEADLESS_ENV, "1")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    backend.reset_backend_cache()


def _scratch_with_iq(tmp_path: Path) -> tuple[Path, Path]:
    left = tmp_path / "L"
    right = tmp_path / "R"
    left.mkdir()
    right.mkdir()
    # Copy the bundled fixture into the active pane so the cursor lands on it.
    shutil.copy(DATA / "test_2o5m2o5a_Iq.dat", left / "sample_Iq.dat")
    return left, right


def _real_app(tmp_path: Path) -> SansdirApp:
    left, right = _scratch_with_iq(tmp_path)
    history = CommandHistory(path=tmp_path / "hist", load=False)
    return SansdirApp(start_path=left, right_path=right, history=history)


async def test_p_on_iq_file_writes_png(tmp_path: Path) -> None:
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Cursor starts on '..'; step down to the .dat file.
        await pilot.press("down")
        await pilot.pause()
        await pilot.press("p")
        # Plot dispatch is async (worker) so give it room to finish.
        await pilot.pause(2.0)
        plots = list(backend.plot_cache_dir().glob("*.png"))
        assert plots, f"expected a PNG in {backend.plot_cache_dir()}"
        await pilot.press("q")


async def test_p_with_no_selection_notifies(tmp_path: Path) -> None:
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Cursor on '..' — selection() returns empty.
        await pilot.press("p")
        await pilot.pause(0.5)
        # No PNGs created.
        assert not list(backend.plot_cache_dir().glob("*.png"))
        await pilot.press("q")


async def test_p_on_transmission_file_uses_lambda_axis(tmp_path: Path) -> None:
    """A `*trans*.txt` file routes through plot.transmission."""
    import numpy as np

    left = tmp_path / "L"
    right = tmp_path / "R"
    left.mkdir()
    right.mkdir()
    np.savetxt(
        left / "sample_trans.txt",
        np.column_stack([np.linspace(2, 14, 8), np.linspace(0.9, 0.5, 8), np.full(8, 0.01)]),
        header="lambda T sigT",
    )
    history = CommandHistory(path=tmp_path / "hist", load=False)
    app = SansdirApp(start_path=left, right_path=right, history=history)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause(2.0)
        plots = list(backend.plot_cache_dir().glob("*.png"))
        assert plots
        # Filename includes "trans" (PNG name encodes input stem).
        assert any("trans" in p.name for p in plots)
        await pilot.press("q")
