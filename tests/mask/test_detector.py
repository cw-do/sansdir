"""Tests for the mask detector loader (Phase 9.6.2).

The pixel-ordering alignment test is the gating one: ``image.flatten()[k]``
must align with ``source_meta.pixel_ids[k]``. Wrong ordering silently
masks the wrong detectors — the worst kind of bug.
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest

from sansdir.mask.core import MaskBuilder, Rectangle
from sansdir.mask.detector import (
    SourceMeta,
    UnsupportedFileLayoutError,
    load_detector_image,
)
from sansdir.plot.hdf5_detector import (
    EQSANS_NBANKS,
    EQSANS_NPIXELS_PER_TUBE,
    EQSANS_NPIXELS_TOTAL,
    EQSANS_NTUBES,
)

# ---------------------------------------------------------------------------
# Synthetic raw EQSANS event-mode fixture
# ---------------------------------------------------------------------------


def _write_synthetic_eqsans(path: Path, *, with_pixel_id: bool = False) -> None:
    """Write a tiny synthetic raw NeXus that the loader recognises.

    The bincount uses one event per known detector ID so we can verify
    flattening alignment without rolling dice.
    """
    rng = np.random.default_rng(seed=7)
    with h5py.File(path, "w") as fh:
        fh.create_dataset("entry/run_number", data=np.bytes_("0001"))
        fh.create_dataset("entry/title", data=np.bytes_("synthetic"))
        inst = fh.create_group("entry/instrument")
        inst.create_dataset("name", data=np.bytes_("EQ-SANS"))
        chunk = EQSANS_NPIXELS_TOTAL // EQSANS_NBANKS
        for b in range(1, EQSANS_NBANKS + 1):
            lo = (b - 1) * chunk
            hi = lo + chunk
            ids = rng.integers(low=lo, high=hi, size=12)
            fh.create_dataset(f"entry/bank{b}_events/event_id", data=ids)
            # The loader requires bank<N>_events for raw detection; the
            # heatmap code summed bincounts over all banks.
        if with_pixel_id:
            # Non-trivial permutation: every-other pair swap.
            ids = np.arange(EQSANS_NPIXELS_TOTAL, dtype=np.int64).reshape(-1, 2)
            ids = ids[:, ::-1].reshape(-1)
            inst.create_dataset("bank1/pixel_id", data=ids)


# ---------------------------------------------------------------------------
# 1. Pixel-ordering alignment — the gating test
# ---------------------------------------------------------------------------


def test_pixel_ordering_alignment_canonical_eqsans(tmp_path: Path) -> None:
    """``image.flatten()[k]`` ↔ detector ID ``pixel_ids[k]`` for EQSANS canonical.

    We build a synthetic file, load it, mask one cell at a known
    ``(row, col)``, and verify the flat detector-id at that flat index
    matches what the heatmap loader put there.
    """
    p = tmp_path / "EQSANS_synth.nxs.h5"
    _write_synthetic_eqsans(p)
    image, meta = load_detector_image(p)
    assert image.shape == (EQSANS_NPIXELS_PER_TUBE, EQSANS_NTUBES)
    assert meta.pixel_ids.shape == (EQSANS_NPIXELS_TOTAL,)
    # Every detector ID 0..49151 appears exactly once.
    assert sorted(meta.pixel_ids.tolist()) == list(range(EQSANS_NPIXELS_TOTAL))

    # Build a single-cell mask and check the resulting detector id is
    # the one the heatmap layout says lives at that (row, col).
    builder = MaskBuilder(image.shape)
    builder.add(Rectangle(50, 100, 50, 100))  # one pixel: (y=100, x=50)
    flat_mask = builder.build().flatten()
    nz = np.flatnonzero(flat_mask)
    assert nz.size == 1
    detid = int(meta.pixel_ids[nz[0]])
    # The flat index for (row=100, col=50) in row-major order is
    # 100 * n_cols + 50 = 100 * 192 + 50 = 19250. The heatmap loader
    # places the detector ID at that flat index; the alignment
    # invariant says pixel_ids agrees.
    expected_flat_idx = 100 * EQSANS_NTUBES + 50
    assert nz[0] == expected_flat_idx
    # Verify pixel_ids[k] is exactly what _reorder_tubes(arange) put there.
    from sansdir.plot.hdf5_detector import _reorder_tubes

    canonical = _reorder_tubes(np.arange(EQSANS_NPIXELS_TOTAL, dtype=np.int64))
    assert detid == int(canonical[100, 50])


def test_pixel_ordering_alignment_explicit_bank1_pixel_id(
    tmp_path: Path,
) -> None:
    """When a file ships ``bank1/pixel_id`` we honour it verbatim."""
    p = tmp_path / "EQSANS_synth_with_pid.nxs.h5"
    _write_synthetic_eqsans(p, with_pixel_id=True)
    _, meta = load_detector_image(p)
    # Synthetic permutation: swap each adjacent pair.
    expected = np.arange(EQSANS_NPIXELS_TOTAL, dtype=np.int64).reshape(-1, 2)
    expected = expected[:, ::-1].reshape(-1)
    assert np.array_equal(meta.pixel_ids, expected)


# ---------------------------------------------------------------------------
# 2. SourceMeta wiring
# ---------------------------------------------------------------------------


def test_source_meta_carries_instrument_and_run(tmp_path: Path) -> None:
    p = tmp_path / "EQSANS_001.nxs.h5"
    _write_synthetic_eqsans(p)
    _, meta = load_detector_image(p)
    assert isinstance(meta, SourceMeta)
    assert meta.instrument_name == "EQ-SANS"
    assert meta.run_number == "0001"
    assert meta.detector_shape == (EQSANS_NPIXELS_PER_TUBE, EQSANS_NTUBES)
    assert meta.source_path == p.resolve()


# ---------------------------------------------------------------------------
# 3. Unsupported layouts fail clearly
# ---------------------------------------------------------------------------


def test_load_rejects_bogus_nexus_file(tmp_path: Path) -> None:
    """A NeXus file that's neither raw event-mode nor processed Mantid
    workspace raises a clear error.

    The mask loader delegates to ``plot.hdf5_detector.load_detector_image``
    which tries raw first, then processed. When both fail it raises
    HdfError with a "not a recognised EQSANS NeXus shape" message.
    """
    from sansdir.hdf.reader import HdfError

    p = tmp_path / "wrong.nxs.h5"
    with h5py.File(p, "w") as fh:
        # Neither bank<N>_events (raw signature) nor mantid_workspace_1
        # (processed signature) — just an empty group.
        fh.create_group("entry/instrument/bank1")
    with pytest.raises(HdfError, match="not a recognised"):
        load_detector_image(p)


def test_load_accepts_processed_workspace2d_file(tmp_path: Path) -> None:
    """Mantid processed files (``mantid_workspace_1/workspace/values``)
    now load through the mask detector loader.

    This is the path EQSANS users hit when they want to mask a
    drtsans-reduced or Mantid-processed run — same detector
    geometry, different storage. Before this commit the loader
    raised because ``load_eqsans_raw`` looks for ``bank<N>_events``
    and processed files don't have them. Now we delegate to the
    plot-side ``load_detector_image`` which tries raw, then
    processed, and the same ``_reorder_tubes`` step normalises the
    output so the pixel-id mapping stays correct.
    """
    p = tmp_path / "proc_workspace2d.nxs"
    n = EQSANS_NPIXELS_TOTAL
    counts = np.arange(n, dtype=np.float64) % 7
    with h5py.File(p, "w") as fh:
        ws = fh.create_group("mantid_workspace_1")
        ws.create_dataset("title", data=np.bytes_("synthetic processed"))
        wsg = ws.create_group("workspace")
        wsg.create_dataset("values", data=counts.reshape(-1))
    image, meta = load_detector_image(p)
    # Same shape + pixel-id contract as the raw path.
    assert image.shape == (EQSANS_NPIXELS_PER_TUBE, EQSANS_NTUBES)
    assert meta.detector_shape == image.shape
    assert meta.pixel_ids.shape == (EQSANS_NPIXELS_TOTAL,)
    # Total counts conserve through the tube-reorder.
    assert int(image.sum()) == int(counts.sum())


def test_load_accepts_processed_event_workspace_file(tmp_path: Path) -> None:
    """Processed files in ``mantid_workspace_1/event_workspace`` form
    (the layout our own mask writer emits — see ``writers.write_nxs``)
    load through the mask detector loader too.

    Round-trip implication: a saved mask can be loaded back as the
    "source" for a follow-up mask edit, which is occasionally
    useful when iterating.
    """
    p = tmp_path / "proc_eventws.nxs"
    n = EQSANS_NPIXELS_TOTAL
    # One event per pixel — diff(indices) sums to n.
    indices = np.arange(n + 1, dtype=np.int64)
    with h5py.File(p, "w") as fh:
        ws = fh.create_group("mantid_workspace_1")
        ws.create_dataset("title", data=np.bytes_("event workspace"))
        ew = ws.create_group("event_workspace")
        ew.create_dataset("indices", data=indices)
    image, meta = load_detector_image(p)
    assert image.shape == (EQSANS_NPIXELS_PER_TUBE, EQSANS_NTUBES)
    assert int(image.sum()) == n  # exactly one count per pixel
    assert meta.pixel_ids.shape == (EQSANS_NPIXELS_TOTAL,)


def test_pixel_id_size_mismatch_raises(tmp_path: Path) -> None:
    """An explicit but wrong-size ``bank1/pixel_id`` raises a clear error."""
    p = tmp_path / "bad.nxs.h5"
    _write_synthetic_eqsans(p)
    # Append a wrong-size pixel_id dataset.
    with h5py.File(p, "a") as fh:
        fh.create_dataset(
            "entry/instrument/bank1/pixel_id",
            data=np.arange(10, dtype=np.int64),
        )
    with pytest.raises(UnsupportedFileLayoutError, match="entries"):
        load_detector_image(p)
