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


def _write_raw_eqsans(path: Path, *, run_number: str = "999", title: str = "test") -> None:
    """Write a tiny NeXus file shaped like a raw EQSANS event-mode run.

    48 banks named ``bank<N>_events`` each with an ``event_id`` array
    whose IDs collectively span 0..(256*192-1) — exactly what
    EQSANS_raw_2D.py ingests.
    """
    import h5py

    n_total = hdf5_detector.EQSANS_NPIXELS_TOTAL
    rng = np.random.default_rng(seed=42)
    with h5py.File(path, "w") as fh:
        fh.create_dataset("entry/run_number", data=np.bytes_(run_number))
        fh.create_dataset("entry/title", data=np.bytes_(title))
        chunk = n_total // hdf5_detector.EQSANS_NBANKS
        for b in range(1, hdf5_detector.EQSANS_NBANKS + 1):
            lo = (b - 1) * chunk
            hi = lo + chunk
            ids = rng.integers(low=lo, high=hi, size=20)
            fh.create_dataset(f"entry/bank{b}_events/event_id", data=ids)


def test_load_eqsans_raw_round_trip(tmp_path: Path) -> None:
    f = tmp_path / "EQSANS_999.nxs.h5"
    _write_raw_eqsans(f, run_number="999", title="my sample")
    img = hdf5_detector.load_eqsans_raw(f)
    assert img.image.shape == (256, 192)
    assert img.run_number == "999"
    assert img.title == "my sample"
    assert img.source == "raw"
    # Total counts: 48 banks x 20 events.
    assert int(img.image.sum()) == hdf5_detector.EQSANS_NBANKS * 20


def test_load_eqsans_raw_rejects_files_without_bank_events(tmp_path: Path) -> None:
    import h5py

    f = tmp_path / "wrong_shape.nxs.h5"
    with h5py.File(f, "w") as fh:
        fh.create_group("entry/instrument/bank1")
    with pytest.raises(reader.HdfError, match="no /entry/bank"):
        hdf5_detector.load_eqsans_raw(f)


def test_load_processed_round_trip(tmp_path: Path) -> None:
    """Mantid-written file: 1D values array of length 256*192."""
    import h5py

    f = tmp_path / "processed.nxs.h5"
    n = hdf5_detector.EQSANS_NPIXELS_TOTAL
    with h5py.File(f, "w") as fh:
        fh.create_dataset("mantid_workspace_1/title", data=np.bytes_("processed sample"))
        fh.create_dataset(
            "mantid_workspace_1/workspace/values",
            data=np.arange(n, dtype=float).reshape(192, 256).ravel(),
        )
    img = hdf5_detector.load_processed(f)
    assert img.image.shape == (256, 192)
    assert img.source == "processed"
    assert img.title == "processed sample"


def test_load_processed_rejects_wrong_size(tmp_path: Path) -> None:
    import h5py

    f = tmp_path / "tiny.nxs.h5"
    with h5py.File(f, "w") as fh:
        fh.create_dataset("mantid_workspace_1/title", data=np.bytes_("x"))
        fh.create_dataset("mantid_workspace_1/workspace/values", data=np.arange(10))
    with pytest.raises(reader.HdfError, match="can't be reduced"):
        hdf5_detector.load_processed(f)


def test_load_detector_image_prefers_raw_when_both_shapes_present(tmp_path: Path) -> None:
    f = tmp_path / "both.nxs.h5"
    _write_raw_eqsans(f, run_number="42", title="hybrid")
    img = hdf5_detector.load_detector_image(f)
    assert img.source == "raw"


def test_load_detector_image_falls_back_to_processed(tmp_path: Path) -> None:
    import h5py

    f = tmp_path / "proc_only.nxs.h5"
    n = hdf5_detector.EQSANS_NPIXELS_TOTAL
    with h5py.File(f, "w") as fh:
        fh.create_dataset("mantid_workspace_1/title", data=np.bytes_("proc"))
        fh.create_dataset("mantid_workspace_1/workspace/values", data=np.zeros(n))
    img = hdf5_detector.load_detector_image(f)
    assert img.source == "processed"


def test_load_detector_image_neither_shape_raises(tmp_path: Path) -> None:
    import h5py

    f = tmp_path / "junk.nxs.h5"
    with h5py.File(f, "w") as fh:
        fh.create_group("entry")
    with pytest.raises(reader.HdfError, match="not a recognised EQSANS"):
        hdf5_detector.load_detector_image(f)


def test_make_detector_figure_dispatches_to_iqxy_for_2d_workspace(
    tmp_path: Path,
) -> None:
    """A Mantid Iqxy workspace renders as a pcolormesh with q axes."""
    import h5py
    import matplotlib.pyplot as plt

    f = tmp_path / "fake_iqxy.nxs"
    n_qx, n_qy = 16, 12
    with h5py.File(f, "w") as fh:
        fh.create_dataset("mantid_workspace_1/title", data=np.bytes_("iqxy-fixture"))
        fh.create_dataset(
            "mantid_workspace_1/workspace/values",
            data=np.random.default_rng(1).poisson(5.0, size=(n_qy, n_qx)).astype(float),
        )
        fh.create_dataset(
            "mantid_workspace_1/workspace/axis1",
            data=np.linspace(-0.3, 0.3, n_qx + 1),
        )
        fh.create_dataset(
            "mantid_workspace_1/workspace/axis2",
            data=np.linspace(-0.3, 0.3, n_qy + 1),
        )
    fig = hdf5_detector.make_detector_figure(f)
    ax = fig.axes[0]
    # pcolormesh adds a Collection, not an Image — that's the
    # signature that says "we took the Iqxy branch" rather than the
    # detector imshow path.
    assert len(list(ax.get_images())) == 0
    assert len(ax.collections) == 1
    assert "q_x" in ax.get_xlabel()
    assert "q_y" in ax.get_ylabel()
    assert "iqxy-fixture" in ax.get_title()
    plt.close(fig)


def test_load_processed_per_pixel_histogram_sums_bins(tmp_path: Path) -> None:
    """``(49152, n_bins)`` layout: sum across bins → detector image."""
    import h5py

    f = tmp_path / "per_pixel_hist.nxs"
    n_pix = hdf5_detector.EQSANS_NPIXELS_TOTAL
    n_bins = 30
    rng = np.random.default_rng(0)
    raw = rng.poisson(1.0, size=(n_pix, n_bins)).astype(float)
    with h5py.File(f, "w") as fh:
        fh.create_dataset("mantid_workspace_1/title", data=np.bytes_("multi-bin"))
        fh.create_dataset("mantid_workspace_1/workspace/values", data=raw)
    img = hdf5_detector.load_processed(f)
    assert img.image.shape == (256, 192)
    # Total counts == raw.sum() — bins are summed, no data dropped.
    assert float(img.image.sum()) == pytest.approx(raw.sum())


def test_load_processed_transposed_histogram_sums_along_axis0(tmp_path: Path) -> None:
    """``(n_bins, 49152)`` is also accepted; sum on axis 0."""
    import h5py

    f = tmp_path / "transposed_hist.nxs"
    n_pix = hdf5_detector.EQSANS_NPIXELS_TOTAL
    raw = np.random.default_rng(1).poisson(1.0, size=(7, n_pix)).astype(float)
    with h5py.File(f, "w") as fh:
        fh.create_dataset("mantid_workspace_1/title", data=np.bytes_("t"))
        fh.create_dataset("mantid_workspace_1/workspace/values", data=raw)
    img = hdf5_detector.load_processed(f)
    assert img.image.shape == (256, 192)
    assert float(img.image.sum()) == pytest.approx(raw.sum())


def test_load_iqxy_reduced_rejects_inconsistent_axes(tmp_path: Path) -> None:
    """``axis1`` / ``axis2`` must be ``n_bins+1`` / ``n_spectra+1`` long."""
    import h5py

    f = tmp_path / "bad_axes.nxs"
    with h5py.File(f, "w") as fh:
        fh.create_dataset("mantid_workspace_1/title", data=np.bytes_("bad"))
        fh.create_dataset(
            "mantid_workspace_1/workspace/values", data=np.zeros((4, 4))
        )
        fh.create_dataset(
            "mantid_workspace_1/workspace/axis1", data=np.linspace(0, 1, 4)
        )
        fh.create_dataset(
            "mantid_workspace_1/workspace/axis2", data=np.linspace(0, 1, 4)
        )
    with pytest.raises(reader.HdfError, match="bin-edge"):
        hdf5_detector.load_iqxy_reduced(f)


def test_make_detector_figure_for_processed_short_nxs(tmp_path: Path) -> None:
    """Processed Mantid output with ``.nxs`` (no ``.h5``) plots end-to-end."""
    import h5py
    import matplotlib.pyplot as plt

    f = tmp_path / "processed.nxs"
    n = hdf5_detector.EQSANS_NPIXELS_TOTAL
    with h5py.File(f, "w") as fh:
        fh.create_dataset(
            "mantid_workspace_1/title", data=np.bytes_("processed-sample")
        )
        fh.create_dataset(
            "mantid_workspace_1/workspace/values",
            data=np.arange(n, dtype=float).reshape(192, 256).ravel(),
        )
    fig = hdf5_detector.make_detector_figure(f)
    main = fig.axes[0]
    assert "processed-sample" in main.get_title()
    assert len(list(main.get_images())) == 1
    plt.close(fig)


def test_make_detector_figure_renders_imshow(tmp_path: Path) -> None:
    """Single (256x192) imshow with colorbar — not a tile of banks."""
    import matplotlib.pyplot as plt

    f = tmp_path / "EQSANS_99.nxs.h5"
    _write_raw_eqsans(f)
    fig = hdf5_detector.make_detector_figure(f)
    assert len(fig.axes) == 2  # main + colorbar
    main = fig.axes[0]
    assert len(list(main.get_images())) == 1
    assert main.get_xlabel() == "Tube"
    assert main.get_ylabel() == "Pixel"
    # Initial layout is a square plot box; user can press `a` to flip.
    assert main.get_box_aspect() == 1
    plt.close(fig)


def test_reorder_tubes_validates_size() -> None:
    with pytest.raises(ValueError, match="expected"):
        hdf5_detector._reorder_tubes(np.zeros(100))


# ---------------------------------------------------------------------------
# detect.py — KIND_NEXUS routing for *.nxs.h5
# ---------------------------------------------------------------------------


def test_detect_kind_classifies_nxs_h5(synthetic_nexus: Path) -> None:
    from sansdir.plot import detect

    d = detect.detect_kind(synthetic_nexus)
    assert d.kind == detect.KIND_NEXUS
