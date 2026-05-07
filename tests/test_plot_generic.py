"""Tests for ``sansdir.plot.generic`` — linear-linear plot of headered tables."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sansdir.plot import generic


@pytest.fixture(autouse=True)
def headless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sansdir.plot import backend

    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv(backend.HEADLESS_ENV, "1")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    backend.reset_backend_cache()


# ---------------------------------------------------------------------------
# Table parsing
# ---------------------------------------------------------------------------


def test_read_table_with_header_csv(tmp_path: Path) -> None:
    p = tmp_path / "t.csv"
    p.write_text("time,temperature\n0.0,298.0\n1.0,299.5\n2.0,301.0\n")
    header, data = generic.read_table_with_header(p)
    assert header == ["time", "temperature"]
    assert data.shape == (3, 2)
    assert data[1, 1] == pytest.approx(299.5)


def test_read_table_with_header_tsv_with_filename_column(tmp_path: Path) -> None:
    """Summary-mode tables have a ``filename`` first column → NaNs, still parse."""
    p = tmp_path / "summary.tsv"
    p.write_text(
        "filename\ttemperature\tduration\n"
        "EQSANS_1.nxs.h5\t298.1\t600\n"
        "EQSANS_2.nxs.h5\t299.5\t1200\n"
    )
    header, data = generic.read_table_with_header(p)
    assert header == ["filename", "temperature", "duration"]
    # First column is non-numeric → NaN; the numeric columns still parse.
    assert np.all(np.isnan(data[:, 0]))
    assert data[0, 1] == pytest.approx(298.1)


def test_read_table_no_header_whitespace(tmp_path: Path) -> None:
    p = tmp_path / "t.dat"
    p.write_text("0.0 1.0 2.0\n0.1 1.5 2.4\n")
    header, data = generic.read_table_with_header(p)
    assert header is None
    assert data.shape == (2, 3)


def test_read_table_skips_comment_lines(tmp_path: Path) -> None:
    p = tmp_path / "t.dat"
    p.write_text("# created 2026-05\nx,y\n0,1\n2,3\n")
    header, data = generic.read_table_with_header(p)
    assert header == ["x", "y"]
    assert data.shape == (2, 2)


def test_read_table_empty_file_raises(tmp_path: Path) -> None:
    p = tmp_path / "empty.csv"
    p.write_text("# only comments\n# nothing else\n")
    with pytest.raises(ValueError, match="empty"):
        generic.read_table_with_header(p)


# ---------------------------------------------------------------------------
# Figure construction (headless: writes to PNG path)
# ---------------------------------------------------------------------------


def test_make_generic_figure_uses_header_for_axis_labels(tmp_path: Path) -> None:
    import matplotlib.pyplot as plt

    p = tmp_path / "t.csv"
    p.write_text("time,temperature\n0.0,298.0\n1.0,299.5\n2.0,301.0\n")
    fig = generic.make_generic_figure([p])
    ax = fig.axes[0]
    assert ax.get_xlabel() == "time"
    assert ax.get_ylabel() == "temperature"
    # One series, one line.
    assert len(ax.get_lines()) == 1
    assert ax.get_xscale() == "linear"
    assert ax.get_yscale() == "linear"
    plt.close(fig)


def test_make_generic_figure_skips_all_nan_columns(tmp_path: Path) -> None:
    """A summary-mode export's ``filename`` column shouldn't render."""
    import matplotlib.pyplot as plt

    p = tmp_path / "summary.tsv"
    p.write_text(
        "filename\ttime\tphase1\n"
        "EQSANS_1.nxs.h5\t0.0\t1.0\n"
        "EQSANS_2.nxs.h5\t1.0\t2.0\n"
    )
    fig = generic.make_generic_figure([p])
    ax = fig.axes[0]
    # First numeric col (time) is x; phase1 is the lone series.
    assert ax.get_xlabel() == "time"
    assert len(ax.get_lines()) == 1
    plt.close(fig)


def test_make_generic_figure_overlays_multiple_files(tmp_path: Path) -> None:
    import matplotlib.pyplot as plt

    a = tmp_path / "a.csv"
    a.write_text("time,t\n0,1\n1,2\n")
    b = tmp_path / "b.csv"
    b.write_text("time,t\n0,3\n1,4\n")
    fig = generic.make_generic_figure([a, b])
    ax = fig.axes[0]
    # Two series — one per file.
    assert len(ax.get_lines()) == 2
    # Multi-file labels are prefixed with the file stem.
    labels = [ln.get_label() for ln in ax.get_lines()]
    assert any(label.startswith("a:") for label in labels)
    assert any(label.startswith("b:") for label in labels)
    plt.close(fig)


def test_plot_generic_headless_writes_png(tmp_path: Path) -> None:
    p = tmp_path / "t.csv"
    p.write_text("time,temperature\n0,298\n1,300\n")
    png, _info = generic.plot_generic([p])
    assert png is not None
    assert png.exists()


# ---------------------------------------------------------------------------
# Panel kind-styling — color-coded file rows
# ---------------------------------------------------------------------------


def test_panel_kind_style_picks_color_per_file_kind(tmp_path: Path) -> None:
    """`_kind_style` picks a Rich style based on extension / mode bits."""
    from sansdir.core.filesystem import _stat_entry
    from sansdir.ui.panel import _kind_style

    (tmp_path / "sub").mkdir()
    (tmp_path / "sample_Iq.dat").write_text("0 1\n")
    (tmp_path / "sample_Iqxqy.dat").write_text("0 0 1\n")
    (tmp_path / "trans_lambda.txt").write_text("1 0.9\n")
    (tmp_path / "EQSANS_1.nxs.h5").write_text("\x89HDF\r\n\x1a\n")
    (tmp_path / "plain.txt").write_text("hi\n")
    script = tmp_path / "run.sh"
    script.write_text("#!/bin/sh\necho hi\n")
    script.chmod(0o755)

    cases = {
        "sub": "bold blue",
        "sample_Iq.dat": "green",
        "sample_Iqxqy.dat": "magenta",
        "trans_lambda.txt": "cyan",
        "EQSANS_1.nxs.h5": "bright_yellow",
        "plain.txt": "",
        "run.sh": "bold red",
    }
    for name, expected in cases.items():
        entry = _stat_entry(tmp_path / name)
        assert _kind_style(entry) == expected, name
