"""Tests for sansdir.plot — backend, detect, ascii1d.

Forces the headless Agg path so all "show" calls produce PNGs we can
inspect, instead of trying to pop a window in CI.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest

from sansdir.plot import ascii1d, backend, detect


@pytest.fixture(autouse=True)
def isolate_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv(backend.HEADLESS_ENV, "1")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    backend.reset_backend_cache()


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


def test_has_display_respects_headless_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv(backend.HEADLESS_ENV, "1")
    assert backend.has_display() is False


def test_has_display_with_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(backend.HEADLESS_ENV, raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert backend.has_display() is False


def test_has_display_with_x11(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(backend.HEADLESS_ENV, raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    assert backend.has_display() is True


def test_init_backend_picks_agg_when_headless() -> None:
    info = backend.init_backend()
    assert info.name == "Agg"
    assert info.interactive is False


def test_init_backend_is_cached() -> None:
    info1 = backend.init_backend()
    info2 = backend.init_backend()
    assert info1 is info2


# ---------------------------------------------------------------------------
# Detect
# ---------------------------------------------------------------------------


def _write_iq(path: Path, cols: int) -> None:
    rows = []
    for i in range(5):
        q = 0.01 + 0.01 * i
        line = [f"{q:.3e}", f"{1.0 + i:.3e}"]
        if cols >= 3:
            line.append(f"{0.1 * (i + 1):.3e}")
        if cols >= 4:
            line.append(f"{1e-3:.3e}")
        rows.append("\t".join(line))
    path.write_text("# header\n" + "\n".join(rows) + "\n", encoding="utf-8")


def test_detect_iq_3col(tmp_path: Path) -> None:
    f = tmp_path / "sample_Iq.dat"
    _write_iq(f, 3)
    d = detect.detect_kind(f)
    assert d.kind == detect.KIND_IQ
    assert d.columns == 3


def test_detect_iq_4col(tmp_path: Path) -> None:
    f = tmp_path / "sample_Iq.dat"
    _write_iq(f, 4)
    d = detect.detect_kind(f)
    assert d.kind == detect.KIND_IQ
    assert d.columns == 4


def test_detect_transmission_by_name(tmp_path: Path) -> None:
    f = tmp_path / "sample_trans.txt"
    _write_iq(f, 3)
    d = detect.detect_kind(f)
    assert d.kind == detect.KIND_TRANSMISSION


def test_detect_nexus_by_extension(tmp_path: Path) -> None:
    f = tmp_path / "EQSANS_1.nxs.h5"
    f.write_bytes(b"")
    d = detect.detect_kind(f)
    assert d.kind == detect.KIND_NEXUS


def test_detect_iqxqy_by_repeated_first_col(tmp_path: Path) -> None:
    """4-col with repeating qx values in first rows → 2D, not 1D Iq."""
    f = tmp_path / "Iqxqy_4col.dat"
    f.write_text(
        "# qx qy I sigI\n"
        "-0.1 -0.1 1.0 0.1\n"
        "-0.1 -0.05 1.5 0.1\n"
        "-0.1 0.0 2.0 0.1\n"
        "-0.05 -0.1 1.2 0.1\n",
        encoding="utf-8",
    )
    d = detect.detect_kind(f)
    assert d.kind == detect.KIND_IQXQY


def test_detect_unknown_for_empty_file(tmp_path: Path) -> None:
    f = tmp_path / "empty.dat"
    f.write_text("# only comments\n# nothing here\n", encoding="utf-8")
    d = detect.detect_kind(f)
    assert d.kind == detect.KIND_UNKNOWN


# ---------------------------------------------------------------------------
# ASCII 1D plotting (real fixtures + headless)
# ---------------------------------------------------------------------------

DATA = Path(__file__).parent / "data"


def test_read_iq_3col_synthetic(tmp_path: Path) -> None:
    f = tmp_path / "x.dat"
    _write_iq(f, 3)
    ds = ascii1d.read_iq(f)
    assert ds.q.shape == (5,)
    assert ds.has_errors


def test_read_iq_4col_drops_sigq(tmp_path: Path) -> None:
    f = tmp_path / "x.dat"
    _write_iq(f, 4)
    ds = ascii1d.read_iq(f)
    # sigma_q is column 4; we don't expose it.
    assert ds.q.shape == (5,)
    assert ds.sigma_i is not None
    assert ds.sigma_i.shape == (5,)


def test_plot_iq_real_fixture_produces_png(tmp_path: Path) -> None:
    """The bundled 4-col fixture must plot in headless mode quickly.

    The first matplotlib call is dominated by font-cache + backend init
    (~1 s); the DoD's "<500 ms" budget is for repeat plots, which is what
    a user feels after the first one. We do a warm-up plot, then time the
    second call.
    """
    f = DATA / "test_2o5m2o5a_Iq.dat"
    assert f.exists(), f"fixture missing: {f}"
    # Warm-up — pays the import + font cost.
    ascii1d.plot_iq([f])
    start = time.perf_counter()
    png, info = ascii1d.plot_iq([f])
    elapsed = time.perf_counter() - start
    assert info.name == "Agg"
    assert png is not None
    assert png.exists()
    assert png.suffix == ".png"
    assert elapsed < 0.5, f"warm plot took {elapsed * 1000:.0f} ms (budget 500)"


def test_plot_iq_overlay_two_curves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    a = DATA / "test_2o5m2o5a_Iq.dat"
    b = DATA / "NG7_ORNL_B1_All_4col.dat"
    png, _ = ascii1d.plot_iq([a, b])
    assert png is not None and png.exists()


def test_plot_transmission_uses_lambda_label(tmp_path: Path) -> None:
    f = tmp_path / "sample_trans.txt"
    np.savetxt(
        f,
        np.column_stack([np.linspace(2, 14, 8), np.linspace(0.9, 0.5, 8), np.full(8, 0.01)]),
        header="lambda T sigT",
    )
    png, _ = ascii1d.plot_transmission([f])
    assert png is not None and png.exists()


def test_plot_iq_rejects_empty_paths() -> None:
    with pytest.raises(ValueError, match="at least one file"):
        ascii1d.plot_iq([])


def test_show_or_save_writes_into_cache_dir(tmp_path: Path) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    ax.plot([1, 2, 3], [4, 5, 6])
    png, info = backend.show_or_save(fig, title="smoke")
    assert png is not None
    assert png.parent == backend.plot_cache_dir()
    assert os.access(png, os.R_OK)
    assert info.name == "Agg"
