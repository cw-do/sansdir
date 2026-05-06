"""Tests for sansdir.hdf.* and the detector heatmap.

Uses the ``synthetic_nexus`` fixture from tests/conftest.py — a tiny
in-tmp_path NeXus file that mimics SNS conventions
(``/entry/instrument/bank{1,2}/data`` + ``/entry/DASlogs/...``). Real
350 MB cluster files are gitignored; the synthetic fixture is what
runs in CI.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sansdir.hdf import metadata, reader
from sansdir.plot import backend, hdf5_detector


@pytest.fixture(autouse=True)
def headless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv(backend.HEADLESS_ENV, "1")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    backend.reset_backend_cache()


# ---------------------------------------------------------------------------
# reader.py
# ---------------------------------------------------------------------------


def test_open_nexus_round_trip(synthetic_nexus: Path) -> None:
    with reader.open_nexus(synthetic_nexus) as fh:
        assert "entry/instrument/bank1/data" in fh
        assert fh["entry/instrument/bank1/data"].shape == (16, 16)


def test_open_nexus_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(reader.HdfError), reader.open_nexus(tmp_path / "nope.nxs.h5"):
        pass


def test_walk_tree_finds_known_paths(synthetic_nexus: Path) -> None:
    with reader.open_nexus(synthetic_nexus) as fh:
        nodes = reader.walk_tree(fh)
    paths = {n.path for n in nodes}
    assert "/entry/instrument" in paths
    assert "/entry/instrument/bank1/data" in paths
    assert "/entry/DASlogs/temperature/value" in paths


def test_list_children_one_level_deep(synthetic_nexus: Path) -> None:
    with reader.open_nexus(synthetic_nexus) as fh:
        kids = reader.list_children(fh, "/entry/instrument")
    names = {n.path for n in kids}
    assert names == {"/entry/instrument/bank1", "/entry/instrument/bank2"}
    assert all(n.kind == "group" for n in kids)


def test_describe_dataset_includes_dtype_and_shape(synthetic_nexus: Path) -> None:
    with reader.open_nexus(synthetic_nexus) as fh:
        kids = reader.list_children(fh, "/entry/instrument/bank1")
    by_path = {k.path: k for k in kids}
    data = by_path["/entry/instrument/bank1/data"]
    assert data.kind == "dataset"
    assert data.shape == (16, 16)
    assert "uint" in data.dtype or "int" in data.dtype


def test_preview_value_handles_scalar(synthetic_nexus: Path) -> None:
    with reader.open_nexus(synthetic_nexus) as fh:
        ds = fh["/entry/instrument/bank1/total_counts"]
        prev = reader.preview_value(ds)
    # Just confirm it returns something readable rather than a traceback.
    assert prev and "<error" not in prev


# ---------------------------------------------------------------------------
# metadata.py
# ---------------------------------------------------------------------------


def test_extract_value_time_series_returns_mean(synthetic_nexus: Path) -> None:
    """DASlogs/temperature is a 10-sample time series — extractor takes the mean."""
    with reader.open_nexus(synthetic_nexus) as fh:
        v = metadata.extract_value(fh, "/entry/DASlogs/temperature")
    assert v.is_scalar is False
    assert v.n_points == 10
    # Synthetic fixture draws from N(298.15, 0.05); mean should be close.
    assert abs(v.value - 298.15) < 0.5


def test_extract_value_via_value_subkey(synthetic_nexus: Path) -> None:
    """Group with a 'value' member auto-recurses into the dataset."""
    with reader.open_nexus(synthetic_nexus) as fh:
        v_group = metadata.extract_value(fh, "/entry/DASlogs/shear")
        v_direct = metadata.extract_value(fh, "/entry/DASlogs/shear/value")
    assert v_group.value == pytest.approx(v_direct.value)


def test_extract_value_unknown_key_raises(synthetic_nexus: Path) -> None:
    with reader.open_nexus(synthetic_nexus) as fh, pytest.raises(KeyError):
        metadata.extract_value(fh, "/entry/DASlogs/nope")


def test_extract_value_from_path_one_shot(synthetic_nexus: Path) -> None:
    v = metadata.extract_value_from_path(synthetic_nexus, "/entry/DASlogs/temperature/value")
    assert v.n_points == 10


# ---------------------------------------------------------------------------
# hdf5_detector.py
# ---------------------------------------------------------------------------


def test_list_banks_returns_known_banks(synthetic_nexus: Path) -> None:
    banks = hdf5_detector.list_banks(synthetic_nexus)
    assert banks == ["bank1", "bank2"]


def test_read_bank_image_uses_aggregated_data(synthetic_nexus: Path) -> None:
    """Synthetic fixture has pre-aggregated 'data' arrays — use them as-is."""
    with reader.open_nexus(synthetic_nexus) as fh:
        img = hdf5_detector.read_bank_image(fh, "bank1")
    assert img is not None
    assert img.counts.shape == (16, 16)
    assert img.total > 0


def test_read_bank_image_event_mode_falls_back_to_bincount(tmp_path: Path) -> None:
    """When only event_id is present, bincount + reshape gives a usable image."""
    import h5py

    f = tmp_path / "events.nxs.h5"
    with h5py.File(f, "w") as fh:
        bank = fh.create_group("entry/instrument/bank1")
        # 4x4 detector; ids 0..15 each fired a few times.
        rng = np.random.default_rng(seed=1)
        ids = rng.integers(low=0, high=16, size=200)
        bank.create_dataset("event_id", data=ids)
    with reader.open_nexus(f) as fh:
        img = hdf5_detector.read_bank_image(fh, "bank1")
    assert img is not None
    # 16 pixels → 4x4 (perfect square), with sum equal to the # of events.
    assert img.counts.shape == (4, 4)
    assert img.total == 200


def test_make_detector_figure_returns_figure_with_pcolormesh(synthetic_nexus: Path) -> None:
    """Synthetic 2-bank file → tile of 2 heatmaps + shared colorbar."""
    import matplotlib.pyplot as plt

    fig = hdf5_detector.make_detector_figure(synthetic_nexus)
    # 2 data tiles + 1 shared colorbar = at least 3 axes.
    assert len(fig.axes) >= 3
    pcm_count = sum(
        1 for ax in fig.axes for c in ax.collections if c.__class__.__name__ == "QuadMesh"
    )
    assert pcm_count >= 2  # at least one per bank (cbar may add one too)
    plt.close(fig)


def test_make_detector_figure_no_banks_raises(tmp_path: Path) -> None:
    """A NeXus file without any bank<N> groups errors out cleanly."""
    import h5py

    f = tmp_path / "no_banks.nxs.h5"
    with h5py.File(f, "w") as fh:
        fh.create_group("entry")
    with pytest.raises(ValueError, match="no detector banks"):
        hdf5_detector.make_detector_figure(f)


def test_factor_near_square() -> None:
    assert hdf5_detector._factor_near_square(16) == (4, 4)
    assert hdf5_detector._factor_near_square(20) == (4, 5)
    # Prime → fall back to side x ceil(n/side).
    rows, cols = hdf5_detector._factor_near_square(17)
    assert rows * cols >= 17


# ---------------------------------------------------------------------------
# detect.py — KIND_NEXUS routing for *.nxs.h5
# ---------------------------------------------------------------------------


def test_detect_kind_classifies_nxs_h5(synthetic_nexus: Path) -> None:
    from sansdir.plot import detect

    d = detect.detect_kind(synthetic_nexus)
    assert d.kind == detect.KIND_NEXUS
