"""Tests for sansdir.usans.desmear_io — reading, writing, naming."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sansdir.usans.desmear import desmear
from sansdir.usans.desmear_io import (
    DESMEARED_SUFFIX,
    desmeared_path,
    format_header,
    looks_like_iq,
    read_curve,
    write_curve,
)


def _curve(tmp_path: Path, name: str = "UN_S0_det_1_bsub.txt", *, sep: str = ",") -> Path:
    """A reduced-curve file in the engine's own format."""
    q = np.geomspace(5e-5, 3e-3, 40)
    i = 1e-6 * q**-3.0
    d = 0.02 * i
    path = tmp_path / name
    trailing = sep if sep == "," else ""
    path.write_text(
        "".join(
            f"{a:.6e}{sep}{b:.6e}{sep}{c:.6e}{trailing}\n" for a, b, c in zip(q, i, d, strict=True)
        ),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------


def test_desmeared_path_appends_the_suffix(tmp_path: Path) -> None:
    got = desmeared_path(tmp_path / "UN_S0-20C_det_1_bsub.txt")
    assert got.name == "UN_S0-20C_det_1_bsub" + DESMEARED_SUFFIX
    assert got.parent == tmp_path


def test_desmeared_path_honours_an_output_dir(tmp_path: Path) -> None:
    got = desmeared_path(tmp_path / "a" / "c.txt", out_dir=tmp_path / "out")
    assert got == tmp_path / "out" / f"c{DESMEARED_SUFFIX}"


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sep", [",", " "])
def test_read_curve_handles_both_delimiters(tmp_path: Path, sep: str) -> None:
    q, i, d = read_curve(_curve(tmp_path, sep=sep))
    assert q.size == 40 and i.size == 40 and d.size == 40
    assert np.all(np.isfinite(q)) and np.all(q > 0)


def test_read_curve_synthesises_errors_for_a_two_column_file(tmp_path: Path) -> None:
    p = tmp_path / "two.txt"
    q = np.geomspace(1e-4, 1e-3, 20)
    p.write_text(
        "".join(f"{a:.5e} {b:.5e}\n" for a, b in zip(q, q**-3.0, strict=True)), encoding="utf-8"
    )
    _, i, d = read_curve(p)
    assert np.allclose(d, 0.05 * np.abs(i))


def test_looks_like_iq_accepts_a_reduced_curve(tmp_path: Path) -> None:
    assert looks_like_iq(_curve(tmp_path))


def test_looks_like_iq_rejects_a_setup_csv_and_a_directory(tmp_path: Path) -> None:
    csv = tmp_path / "IPTS-1_setup.csv"
    csv.write_text("b,E,100,4,0.1\n", encoding="utf-8")
    assert not looks_like_iq(csv)
    assert not looks_like_iq(tmp_path)
    assert not looks_like_iq(tmp_path / "nope.txt")


def test_looks_like_iq_rejects_a_binary_file(tmp_path: Path) -> None:
    nx = tmp_path / "USANS_1.nxs.h5"
    nx.write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 64)
    assert not looks_like_iq(nx)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _result(tmp_path: Path):  # type: ignore[no-untyped-def]
    q, i, d = read_curve(_curve(tmp_path))
    return desmear(q, i, d)


def test_write_curve_is_three_columns_and_reloadable(tmp_path: Path) -> None:
    src = _curve(tmp_path)
    result = _result(tmp_path)
    out = write_curve(result, desmeared_path(src), source=src)
    assert out.is_file()
    # Round-trips through the same reader the plotter uses.
    q2, i2, d2 = read_curve(out)
    assert np.allclose(q2, result.q)
    assert np.allclose(i2, result.intensity)
    assert np.allclose(d2, result.sigma)


def test_written_curve_plots_as_iq(tmp_path: Path) -> None:
    """It must land on the 1-D plotter like every other reduced curve."""
    from sansdir.plot.detect import KIND_IQ, detect_kind

    src = _curve(tmp_path)
    out = write_curve(_result(tmp_path), desmeared_path(src), source=src)
    assert detect_kind(out).kind == KIND_IQ


def test_header_records_the_method_and_the_no_sans_warning(tmp_path: Path) -> None:
    src = _curve(tmp_path)
    header = format_header(_result(tmp_path), src, None)
    assert "truncated Abel" in header
    assert "Huang" in header
    assert "sigma_y" in header
    assert "WARNING - no SANS data was supplied." in header
    assert "TRUNCATED" in header
    assert src.name in header


def test_header_names_the_sans_companion_when_there_is_one(tmp_path: Path) -> None:
    src = _curve(tmp_path)
    q, i, d = read_curve(src)
    qe = np.geomspace(1e-3, 0.5, 60)
    ie = 1e-6 * qe**-3.0
    result = desmear(q, i, d, sans=(qe, ie, 0.02 * ie))
    header = format_header(result, src, tmp_path / "EQSANS_merged.txt")
    assert "EQSANS_merged.txt" in header
    assert "WARNING - no SANS data" not in header
    assert "scaled onto the smeared SANS" in header


def test_write_curve_creates_the_output_directory(tmp_path: Path) -> None:
    src = _curve(tmp_path)
    out = write_curve(_result(tmp_path), tmp_path / "deep" / "x_desmeared.txt", source=src)
    assert out.is_file()
