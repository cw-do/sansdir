"""Cumulative TOF cube loading (Phase 9.10.1).

Synthetic raw files carry known (detector ID, TOF) events so every bin
can be checked exactly; the real ``tests/data`` run is compared with the
existing heatmap loader when present.
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest

from sansdir.hdf.reader import HdfError
from sansdir.plot.hdf5_detector import load_eqsans_raw
from sansdir.viewer import cube as cube_mod
from sansdir.viewer.cube import LoadCancelledError, load_cube, load_raw
from sansdir.viewer.geometry import NPIX, to_image

REAL_RUN = Path(__file__).parents[1] / "data" / "EQSANS_172749.nxs.h5"

FREQ_HZ = 60.0
TOF_MAX = 1.1e6 / FREQ_HZ  # µs — the cube's grid spans 1.1 frames


def _events(seed: int = 3, per_bank: int = 400) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    """bank number → (event_id, event_time_offset), IDs inside the bank's block."""
    rng = np.random.default_rng(seed)
    out = {}
    for bank in range(1, 49):
        lo = (bank - 1) * 1024
        ids = rng.integers(lo, lo + 1024, size=per_bank).astype(np.uint32)
        tof = rng.uniform(500.0, 15000.0, size=per_bank).astype(np.float32)
        out[bank] = (ids, tof)
    return out


def _write_raw(
    path: Path,
    events: dict[int, tuple[np.ndarray, np.ndarray]],
    *,
    frequency: float | None = FREQ_HZ,
) -> Path:
    with h5py.File(path, "w") as fh:
        fh.create_dataset("entry/run_number", data=np.bytes_("4242"))
        fh.create_dataset("entry/title", data=np.bytes_("synthetic run"))
        if frequency is not None:
            fh.create_dataset(
                "entry/DASlogs/BL6:Det:TH:BL:Frequency/value", data=np.array([frequency])
            )
        for bank, (ids, tof) in events.items():
            fh.create_dataset(f"entry/bank{bank}_events/event_id", data=ids)
            fh.create_dataset(f"entry/bank{bank}_events/event_time_offset", data=tof)
    return path


def _expected(events: dict[int, tuple[np.ndarray, np.ndarray]], nbins: int) -> np.ndarray:
    """Brute-force (nbins, NPIX) histogram on the cube's grid."""
    ids = np.concatenate([e[0] for e in events.values()]).astype(np.int64)
    tof = np.concatenate([e[1] for e in events.values()])
    bins = np.minimum((tof * (nbins / TOF_MAX)).astype(np.int64), nbins - 1)
    hist = np.zeros((nbins, NPIX), dtype=np.int64)
    np.add.at(hist, (bins, ids), 1)
    return hist


@pytest.fixture
def events() -> dict[int, tuple[np.ndarray, np.ndarray]]:
    return _events()


@pytest.fixture
def raw_file(tmp_path: Path, events: dict[int, tuple[np.ndarray, np.ndarray]]) -> Path:
    return _write_raw(tmp_path / "EQSANS_4242.nxs.h5", events)


def test_every_tof_bin_is_exact(
    raw_file: Path, events: dict[int, tuple[np.ndarray, np.ndarray]]
) -> None:
    cube = load_cube(raw_file, nbins=200)
    hist = _expected(events, 200)
    assert cube.source == "raw" and cube.has_tof
    assert cube.run_number == "4242" and cube.title == "synthetic run"
    assert cube.n_events == cube.total_events == 48 * 400
    for a, b in [(0, cube.nbins), (10, 11), (30, 95), (0, 1)]:
        assert np.array_equal(cube.counts(a, b), hist[a:b].sum(axis=0))
        assert np.array_equal(cube.image(a, b), to_image(hist[a:b].sum(axis=0)))
    assert np.array_equal(cube.spectrum(), hist[: cube.nbins].sum(axis=1))


def test_grid_follows_frame_frequency_and_trims_empty_tail(raw_file: Path) -> None:
    cube = load_cube(raw_file, nbins=200)
    width = TOF_MAX / 200
    assert cube.tof_edges is not None
    assert cube.tof_edges[1] == pytest.approx(width)
    # Events stop at 15 ms: the grid is trimmed to the last non-empty bin.
    assert cube.tof_edges[-1] == pytest.approx(np.ceil(15000.0 / width) * width, abs=width)
    assert cube.spectrum()[-1] > 0


def test_missing_frequency_log_falls_back_to_30_hz(tmp_path: Path) -> None:
    path = _write_raw(tmp_path / "nofreq.nxs.h5", _events(), frequency=None)
    cube = load_cube(path, nbins=100)
    assert cube.tof_edges is not None
    assert cube.tof_edges[1] == pytest.approx(1.1e6 / 30.0 / 100)


def test_late_events_land_in_last_bin_and_are_counted(tmp_path: Path) -> None:
    ev = _events(per_bank=10)
    ev[1][1][:3] = TOF_MAX + 500.0
    cube = load_cube(_write_raw(tmp_path / "late.nxs.h5", ev), nbins=50)
    assert cube.overflow == 3
    assert cube.n_events == 480
    assert int(cube.counts().sum()) == 480


def test_ids_outside_their_bank_are_kept(tmp_path: Path) -> None:
    ev = _events(per_bank=10)
    ev[1][0][:2] = 40000  # belongs to another block
    ev[1][0][2] = NPIX + 5  # not a detector at all → dropped
    cube = load_cube(_write_raw(tmp_path / "stray.nxs.h5", ev), nbins=20)
    assert cube.counts()[40000] >= 2
    assert cube.n_events == 479


def test_chunking_does_not_change_the_result(raw_file: Path) -> None:
    whole = load_raw(raw_file, nbins=64)
    chunked = load_raw(raw_file, nbins=64, chunk=37)
    assert np.array_equal(whole.cum, chunked.cum)


def test_progress_reaches_one(raw_file: Path) -> None:
    seen: list[float] = []
    load_cube(raw_file, nbins=20, progress=seen.append)
    assert len(seen) == 48 and seen == sorted(seen) and seen[-1] == pytest.approx(1.0)


def test_cancel(raw_file: Path) -> None:
    with pytest.raises(LoadCancelledError):
        load_cube(raw_file, should_stop=lambda: True)


def test_parallel_path_with_preview(
    raw_file: Path,
    events: dict[int, tuple[np.ndarray, np.ndarray]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Force the process pool on a tiny file: same answer, plus a scaled preview."""
    monkeypatch.setattr(cube_mod, "PARALLEL_MIN_EVENTS", 0)
    monkeypatch.setattr(cube_mod, "SLICE_EVENTS", 150)
    monkeypatch.setattr(cube_mod, "PREVIEW_EVENTS", 48 * 40)
    serial = load_cube(raw_file, nbins=80, workers=1)
    previews = []
    parallel = load_cube(raw_file, nbins=80, workers=2, on_preview=previews.append)
    assert np.array_equal(parallel.counts(), serial.counts())
    assert np.array_equal(parallel.spectrum(), serial.spectrum())
    assert not parallel.is_preview
    (preview,) = previews
    assert preview.is_preview
    assert preview.n_events < preview.total_events == serial.n_events
    assert preview.counts().sum() == pytest.approx(serial.n_events)


def test_processed_file_has_no_tof(tmp_path: Path) -> None:
    path = tmp_path / "processed.nxs"
    values = np.arange(NPIX, dtype=np.float64)
    with h5py.File(path, "w") as fh:
        fh.create_dataset("mantid_workspace_1/workspace/values", data=values)
        fh.create_dataset("mantid_workspace_1/title", data=np.bytes_("reduced"))
    cube = load_cube(path)
    assert cube.source == "processed" and not cube.has_tof and cube.nbins == 1
    assert np.array_equal(cube.counts(), values)


def test_unrecognised_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "junk.h5"
    with h5py.File(path, "w") as fh:
        fh.create_dataset("x", data=1)
    with pytest.raises(HdfError):
        load_cube(path)


@pytest.mark.skipif(not REAL_RUN.exists(), reason="real EQSANS run not present")
def test_real_run_matches_heatmap_loader() -> None:
    cube = load_cube(REAL_RUN)
    assert np.array_equal(cube.image(), load_eqsans_raw(REAL_RUN).image)
    assert int(cube.spectrum().sum()) == cube.n_events
