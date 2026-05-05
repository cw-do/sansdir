"""Smoke tests for the test fixtures themselves.

These ensure the synthetic NeXus generator produces the structure later
phases (HDF5 reader, batch metadata extract, detector heatmap plot) will
rely on, so a regression in the fixture surfaces immediately rather than
inside an unrelated test.
"""

from __future__ import annotations

from pathlib import Path


def test_synthetic_nexus_has_expected_layout(synthetic_nexus: Path) -> None:
    import h5py

    with h5py.File(synthetic_nexus, "r") as f:
        assert "entry/instrument/bank1/data" in f
        assert "entry/instrument/bank2/total_counts" in f
        assert f["entry/instrument/bank1/data"].shape == (16, 16)
        assert f["entry/DASlogs/temperature/value"].shape == (10,)
        assert f["entry/DASlogs/shear/time"][-1] == 600.0
        assert f["entry/sample/name"][()] == b"synthetic-sample"


def test_iq_fixtures_are_present(iq_3col_path: Path, iq_4col_path: Path) -> None:
    assert iq_3col_path.is_file()
    assert iq_4col_path.is_file()
    assert iq_3col_path.stat().st_size > 0
    assert iq_4col_path.stat().st_size > 0
