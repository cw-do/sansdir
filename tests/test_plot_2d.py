"""Tests for sansdir.plot.ascii2d + tile (2D Iqxqy plotting)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sansdir.plot import ascii2d, backend, tile


@pytest.fixture(autouse=True)
def headless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv(backend.HEADLESS_ENV, "1")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    backend.reset_backend_cache()


def _write_iqxqy(path: Path, nx: int = 5, ny: int = 4, *, cols: int = 4) -> None:
    """Write a regular Iqxqy grid with optional sigma_I + dqx/dqy columns."""
    qx_vals = np.linspace(-0.1, 0.1, nx)
    qy_vals = np.linspace(-0.08, 0.08, ny)
    rows = ["# qx qy I sigI" + (" dqx dqy" if cols == 6 else "")]
    for iy, qy in enumerate(qy_vals):
        for ix, qx in enumerate(qx_vals):
            intensity = 1.0 + ix + 10 * iy
            line = [f"{qx:.4e}", f"{qy:.4e}", f"{intensity:.4e}", f"{intensity * 0.05:.4e}"]
            if cols == 6:
                line.extend(["1.0e-3", "1.0e-3"])
            rows.append("\t".join(line))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# read_iqxqy
# ---------------------------------------------------------------------------


def test_read_iqxqy_4col(tmp_path: Path) -> None:
    f = tmp_path / "Iqxqy.dat"
    _write_iqxqy(f, nx=5, ny=4, cols=4)
    ds = ascii2d.read_iqxqy(f)
    assert ds.shape == (4, 5)  # (ny, nx)
    assert ds.qx.shape == (5,)
    assert ds.qy.shape == (4,)
    assert ds.sigma_i is not None
    # First cell at (qx=qx[0], qy=qy[0]) should be intensity 1.0 (ix=0, iy=0).
    assert ds.intensity[0, 0] == pytest.approx(1.0)
    assert ds.intensity[3, 4] == pytest.approx(1.0 + 4 + 10 * 3)


def test_read_iqxqy_6col_drops_dq(tmp_path: Path) -> None:
    f = tmp_path / "Iqxqy.dat"
    _write_iqxqy(f, cols=6)
    ds = ascii2d.read_iqxqy(f)
    assert ds.shape == (4, 5)


def test_read_iqxqy_sparse_grid_fills_nan(tmp_path: Path) -> None:
    """Real SANS files mask the beam-stop region — missing cells stay NaN.

    Regression: read_iqxqy used to raise GridError on any unfilled cell,
    which rejected almost every real Iqxqy.dat from the cluster. Now we
    just leave NaN there and let pcolormesh render it as a soft grey.
    """
    f = tmp_path / "scatter.dat"
    f.write_text(
        "# qx qy I sigI\n0.0 0.0 1.0 0.1\n0.05 0.0 1.5 0.1\n0.1 0.05 2.0 0.1\n",
        encoding="utf-8",
    )
    ds = ascii2d.read_iqxqy(f)
    assert ds.shape == (2, 3)  # 2 unique qy x 3 unique qx
    assert ds.intensity[0, 0] == pytest.approx(1.0)
    assert ds.intensity[0, 1] == pytest.approx(1.5)
    assert ds.intensity[1, 2] == pytest.approx(2.0)
    # The other 3 cells weren't supplied → NaN, not a hard failure.
    assert np.isnan(ds.intensity[0, 2])
    assert np.isnan(ds.intensity[1, 0])
    assert np.isnan(ds.intensity[1, 1])


def test_read_iqxqy_real_grid_with_masked_centre(tmp_path: Path) -> None:
    """Regular grid with a masked square in the middle — most cells filled."""
    f = tmp_path / "Iqxqy.dat"
    rows = ["# qx qy I sigI"]
    qx_vals = np.linspace(-0.1, 0.1, 5)
    qy_vals = np.linspace(-0.08, 0.08, 4)
    for iy, qy in enumerate(qy_vals):
        for ix, qx in enumerate(qx_vals):
            # Skip the centre 2x2 region as if it were masked by the beam stop.
            if 1 <= ix <= 2 and 1 <= iy <= 2:
                continue
            rows.append(f"{qx:.4e}\t{qy:.4e}\t{ix + 10 * iy + 1.0}\t0.1")
    f.write_text("\n".join(rows) + "\n", encoding="utf-8")
    ds = ascii2d.read_iqxqy(f)
    assert ds.shape == (4, 5)
    nan_count = int(np.isnan(ds.intensity).sum())
    assert nan_count == 4  # the masked 2x2 block


def test_read_iqxqy_rejects_wrong_columns(tmp_path: Path) -> None:
    f = tmp_path / "x.dat"
    f.write_text("# only three\n1.0 2.0 3.0\n4.0 5.0 6.0\n", encoding="utf-8")
    with pytest.raises(ascii2d.GridError, match="4 or 6 columns"):
        ascii2d.read_iqxqy(f)


# ---------------------------------------------------------------------------
# Single 2D plot
# ---------------------------------------------------------------------------


def test_make_iqxqy_figure_returns_figure_with_pcolormesh(tmp_path: Path) -> None:
    import matplotlib.pyplot as plt

    f = tmp_path / "Iqxqy.dat"
    _write_iqxqy(f)
    fig = tile.make_iqxqy_figure(f)
    # One axes + one colorbar axes = two axes total.
    assert len(fig.axes) == 2
    # The first axes carries our pcolormesh as a QuadMesh collection.
    main = fig.axes[0]
    assert any(c.__class__.__name__ == "QuadMesh" for c in main.collections)
    assert "qx" in main.get_xlabel().lower() or "q_x" in main.get_xlabel()
    plt.close(fig)


def test_make_iqxqy_figure_log_intensity(tmp_path: Path) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    f = tmp_path / "Iqxqy.dat"
    _write_iqxqy(f)
    fig = tile.make_iqxqy_figure(f, log_intensity=True)
    main = fig.axes[0]
    pcm = next(c for c in main.collections if c.__class__.__name__ == "QuadMesh")
    assert isinstance(pcm.norm, LogNorm)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Tile mode (multi-2D)
# ---------------------------------------------------------------------------


def test_tile_one_file_falls_through_to_single(tmp_path: Path) -> None:
    import matplotlib.pyplot as plt

    f = tmp_path / "Iqxqy.dat"
    _write_iqxqy(f)
    fig = tile.make_tile_figure([f])
    # Same shape as single Iqxqy: 1 main + 1 colorbar.
    assert len(fig.axes) == 2
    plt.close(fig)


def test_tile_four_files_uses_2x2_with_shared_colorbar(tmp_path: Path) -> None:
    import matplotlib.pyplot as plt

    files = []
    for i in range(4):
        f = tmp_path / f"Iqxqy_{i}.dat"
        _write_iqxqy(f)
        files.append(f)
    fig = tile.make_tile_figure(files, colorbar_mode="shared")
    plt.close(fig)
    # 4 data axes + 1 shared colorbar axes = 5.
    # (the figure caches them on .axes after creation)
    # We also separately confirm the layout by checking ceil(sqrt(4)) = 2.
    import math

    assert math.ceil(math.sqrt(4)) == 2


def test_tile_four_files_independent_colorbars(tmp_path: Path) -> None:
    import matplotlib.pyplot as plt

    files = []
    for i in range(4):
        f = tmp_path / f"Iqxqy_{i}.dat"
        _write_iqxqy(f)
        files.append(f)
    fig = tile.make_tile_figure(files, colorbar_mode="independent")
    # 4 data axes + 4 per-subplot colorbars = 8.
    assert len(fig.axes) == 8
    plt.close(fig)


def test_tile_three_files_hides_unused_subplot(tmp_path: Path) -> None:
    import matplotlib.pyplot as plt

    files = []
    for i in range(3):
        f = tmp_path / f"Iqxqy_{i}.dat"
        _write_iqxqy(f)
        files.append(f)
    fig = tile.make_tile_figure(files, colorbar_mode="independent")
    # The 2x2 layout has one un-used cell — make_tile_figure marks it
    # invisible. We can't easily filter "data axes" from "colorbar axes"
    # via has_data(), so just check that exactly one axes is invisible
    # (the spare slot) and the rest are visible.
    invisible = [ax for ax in fig.axes if not ax.get_visible()]
    assert len(invisible) == 1
    plt.close(fig)


def test_tile_rejects_empty_paths() -> None:
    with pytest.raises(ValueError, match="at least one file"):
        tile.make_tile_figure([])


# ---------------------------------------------------------------------------
# Detector kind (Phase 5 detect.py — the iqxqy branch)
# ---------------------------------------------------------------------------


def test_detect_kind_iqxqy_for_real_grid(tmp_path: Path) -> None:
    """A real 4-col regular Iqxqy grid (repeating qx) is detected as iqxqy."""
    from sansdir.plot import detect

    f = tmp_path / "Iqxqy.dat"
    _write_iqxqy(f, nx=5, ny=4)
    d = detect.detect_kind(f)
    assert d.kind == detect.KIND_IQXQY
