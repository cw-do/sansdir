"""Tests for the XML / NeXus / npy / log writers (Phase 9.6.3)."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import h5py
import numpy as np
import pytest

from sansdir.mask.core import Circle, MaskBuilder, Rectangle
from sansdir.mask.detector import SourceMeta
from sansdir.mask.writers import (
    _compress_ranges,
    _masked_detector_ids,
    log_path_for,
    stats_for,
    write_log,
    write_npy,
    write_nxs,
    write_xml,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _meta(detector_shape=(10, 10), pixel_ids=None) -> SourceMeta:  # type: ignore[no-untyped-def]
    if pixel_ids is None:
        pixel_ids = np.arange(detector_shape[0] * detector_shape[1], dtype=np.int64)
    return SourceMeta(
        source_path=Path("/SNS/EQSANS/IPTS-12345/nexus/EQSANS_172749.nxs.h5"),
        instrument_name="EQ-SANS",
        detector_shape=detector_shape,
        pixel_ids=pixel_ids,
        run_number="172749",
    )


# ---------------------------------------------------------------------------
# Range-compression
# ---------------------------------------------------------------------------


def test_compress_ranges_examples() -> None:
    assert _compress_ranges([]) == ""
    assert _compress_ranges([5]) == "5"
    assert _compress_ranges([5, 9, 10, 11, 12, 42, 43, 44]) == "5,9-12,42-44"
    # Out-of-order input is sorted; duplicates collapse.
    assert _compress_ranges([12, 9, 11, 10, 12]) == "9-12"


# ---------------------------------------------------------------------------
# _masked_detector_ids — validates the system-wide pixel-ordering invariant
# ---------------------------------------------------------------------------


def test_masked_detector_ids_uses_pixel_id_indirection() -> None:
    """If pixel_ids permutes IDs, the masked list reflects that permutation."""
    pixel_ids = np.array([10, 20, 30, 40], dtype=np.int64)  # identity-permuted
    meta = _meta(detector_shape=(2, 2), pixel_ids=pixel_ids)
    # Mask top-left cell (flat index 0) → detector ID 10.
    mask = np.array([[1, 0], [0, 0]], dtype=np.uint8)
    assert _masked_detector_ids(mask, meta).tolist() == [10]
    # Mask the diagonal (flat indexes 0, 3) → ids 10 and 40.
    mask = np.array([[1, 0], [0, 1]], dtype=np.uint8)
    assert _masked_detector_ids(mask, meta).tolist() == [10, 40]


def test_masked_detector_ids_size_mismatch_raises() -> None:
    meta = _meta(detector_shape=(2, 2))
    bad = np.zeros((3, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="size"):
        _masked_detector_ids(bad, meta)


# ---------------------------------------------------------------------------
# XML writer
# ---------------------------------------------------------------------------


def test_write_xml_round_trip(tmp_path: Path) -> None:
    meta = _meta()
    builder = MaskBuilder(meta.detector_shape)
    builder.add(Rectangle(2, 2, 5, 5))
    out = write_xml(tmp_path / "mask.xml", builder.build(), meta)
    tree = ET.parse(out)
    root = tree.getroot()
    assert root.tag == "detector-masking"
    detids = root.find("group/detids")
    assert detids is not None and detids.text
    parsed_text = detids.text
    # 4x4 inclusive rectangle at (2,2)-(5,5) → cells (2..5, 2..5):
    # rows y=2..5, cols x=2..5. Flat indices = y * 10 + x.
    expected = sorted(y * 10 + x for y in range(2, 6) for x in range(2, 6))
    # Range-compressed form.
    runs = []
    s = e = expected[0]
    for n in expected[1:]:
        if n == e + 1:
            e = n
        else:
            runs.append((s, e))
            s = e = n
    runs.append((s, e))
    expected_text = ",".join(f"{a}" if a == b else f"{a}-{b}" for a, b in runs)
    assert parsed_text == expected_text


def test_write_xml_empty_mask(tmp_path: Path) -> None:
    """An all-zero mask still writes valid XML; the detids text is empty."""
    meta = _meta()
    out = write_xml(tmp_path / "empty.xml", np.zeros(meta.detector_shape, dtype=np.uint8), meta)
    root = ET.parse(out).getroot()
    detids = root.find("group/detids")
    assert detids is not None
    assert (detids.text or "") == ""


# ---------------------------------------------------------------------------
# NeXus writer — group hierarchy + critical attributes
# ---------------------------------------------------------------------------


def test_write_nxs_structure_matches_reference(tmp_path: Path) -> None:
    """Layout mirrors ``tests/data/mask_4m2.nxs`` dataset-for-dataset.

    The reference is a ``SaveNexus(EventWorkspace)`` output (a real
    cluster mask file) that sansdir's ``p`` loads via the
    ``event_workspace/indices`` path. We check for the same group
    hierarchy and the same critical attrs.
    """
    meta = _meta()
    builder = MaskBuilder(meta.detector_shape)
    builder.add(Rectangle(2, 2, 5, 5))
    out = write_nxs(tmp_path / "mask.nxs", builder.build(), meta)
    n = meta.pixel_ids.size

    with h5py.File(out, "r") as f:
        # Root-level attrs match a Mantid-saved file's NXroot envelope.
        assert f.attrs["NX_class"] == np.bytes_("NXroot")
        ent = f["mantid_workspace_1"]
        assert ent["definition"][0] == np.bytes_("Mantid Processed Workspace")
        assert (
            ent["definition"].attrs["URL"]
            == "http://www.nexusformat.org/instruments/xml/NXprocessed.xml"
        )
        assert ent["definition"].attrs["Version"] == "1.0"
        assert ent["definition_local"][0] == np.bytes_("Mantid Processed Workspace")
        assert ent["workspace_name"].shape == (1,)

        # Type discriminator: the GROUP NAME ``event_workspace`` —
        # this is what the existing plot loader checks for.
        ew = ent["event_workspace"]
        assert ew.attrs["NX_class"] == "NXdata"
        assert ew["indices"].shape == (n + 1,)
        assert ew["indices"].dtype == np.int64
        # ``diff(indices)`` is the per-detector *unmasked* flag —
        # masked detectors carry 0 events (grey when plotted) and
        # unmasked detectors carry exactly 1 event each. So the
        # cumsum at the end equals (n_total - n_masked).
        diffs = np.diff(ew["indices"][()])
        n_total = int(meta.pixel_ids.size)
        assert diffs.sum() == n_total - int(builder.build().sum())
        assert ew["axis1"].attrs["units"] == "TOF"
        assert ew["axis2"].shape == (n,)
        assert ew["axis2"].attrs["units"] == "spectraNumber"
        # pulsetime / tof present, sized by total events.
        n_events = int(ew["indices"][-1])
        assert ew["pulsetime"].shape == (n_events,)
        assert ew["tof"].shape == (n_events,)

        det = ent["instrument/detector"]
        assert det.attrs["NX_class"] == "NXdetector"
        assert int(det.attrs["version"]) == 1
        # Identity detector_list — same as mask_4m2.nxs (so spectrum
        # k corresponds to detector k).
        assert np.array_equal(
            det["detector_list"][()], np.arange(n, dtype=np.int32)
        )
        assert det["detector_count"][()].sum() == n
        assert det["spectra"][0] == 1
        assert det["detector_positions"].shape == (n, 3)

        proc = ent["process"]
        assert proc.attrs["NX_class"] == "NXprocess"
        for note in ("MantidEnvironment", "MantidAlgorithm_1"):
            g = proc[note]
            assert g.attrs["NX_class"] == "NXnote"
            assert g["author"][0] == np.bytes_("sansdir")


def test_write_nxs_size_mismatch_raises(tmp_path: Path) -> None:
    meta = _meta(detector_shape=(2, 2))
    with pytest.raises(ValueError, match="ordering mismatch"):
        write_nxs(tmp_path / "bad.nxs", np.zeros((3, 3), dtype=np.uint8), meta)


def test_saved_mask_round_trips_through_plot_loader(tmp_path: Path) -> None:
    """``p`` on a sansdir-written mask file must produce a usable heatmap.

    The plot loader reads the file's ``detector_list`` to invert our
    pre-permutation; without that step the rendered image is a
    scrambled mess. Regression test: cells the mask flagged as
    masked must show up at the *same* (row, col) in the round-trip
    image.
    """
    # Build a tiny synthetic raw EQSANS file (the same recipe the
    # detector loader test uses) and mask one rectangle on it.
    import h5py

    from sansdir.mask.api import create_mask
    from sansdir.mask.core import Rectangle
    from sansdir.plot.hdf5_detector import (
        EQSANS_NPIXELS_PER_TUBE,
        EQSANS_NTUBES,
    )
    from sansdir.plot.hdf5_detector import (
        load_detector_image as _load_processed_for_plot,
    )

    src = tmp_path / "EQSANS_synth.nxs.h5"
    rng = np.random.default_rng(0)
    with h5py.File(src, "w") as fh:
        fh.create_dataset("entry/run_number", data=np.bytes_("0001"))
        fh.create_dataset("entry/title", data=np.bytes_("synthetic"))
        fh.create_dataset("entry/instrument/name", data=np.bytes_("EQ-SANS"))
        from sansdir.plot.hdf5_detector import EQSANS_NBANKS, EQSANS_NPIXELS_TOTAL

        chunk = EQSANS_NPIXELS_TOTAL // EQSANS_NBANKS
        for b in range(1, EQSANS_NBANKS + 1):
            lo = (b - 1) * chunk
            ids = rng.integers(low=lo, high=lo + chunk, size=12)
            fh.create_dataset(f"entry/bank{b}_events/event_id", data=ids)

    out = tmp_path / "synth_mask.nxs"
    create_mask(src, [Rectangle(50, 100, 60, 110)], output=out, fmt="nxs")

    det = _load_processed_for_plot(out)
    assert det.image.shape == (EQSANS_NPIXELS_PER_TUBE, EQSANS_NTUBES)
    # 11x11 inclusive rectangle = 121 masked cells. The on-disk
    # encoding is inverted (each unmasked detector carries 1 event,
    # masked carry 0) so the plot loader sees the *complement*: the
    # drawn rectangle reads as 0 (grey/masked region on the heatmap)
    # and the rest of the detector reads as 1.
    n_total = (
        det.image.shape[0] * det.image.shape[1]
    )
    assert int(det.image.sum()) == n_total - 121
    # Cells inside the drawn rectangle are 0 (masked → no events).
    assert det.image[105, 55] == 0
    # Cells outside are 1 (unmasked → one synthetic event each).
    assert det.image[0, 0] == 1
    assert det.image[200, 100] == 1


def test_write_nxs_round_trip_via_h5py(tmp_path: Path) -> None:
    """Read back the file and reconstruct the masked-detid list.

    ``diff(indices)`` gives the per-detector *unmasked* flag (1 if
    that detector is kept, 0 if masked) — the on-disk encoding is
    inverted so masked regions read as zero events (grey on the
    heatmap, matching ``mask_4m2.nxs``). ``detector_list`` carries
    the spectrum→detector_id mapping (identity in our writer).
    """
    meta = _meta()  # identity pixel_ids → flat index == detector id
    mask = np.zeros(meta.detector_shape, dtype=np.uint8)
    mask[3, 3] = 1
    mask[7, 8] = 1
    out = write_nxs(tmp_path / "rt.nxs", mask, meta)
    with h5py.File(out, "r") as f:
        indices = f["mantid_workspace_1/event_workspace/indices"][()]
        det_list = f["mantid_workspace_1/instrument/detector/detector_list"][()]
    flags = np.diff(indices)
    # Detectors with 0 events are the masked ones.
    masked = sorted(int(d) for v, d in zip(flags, det_list, strict=True) if v == 0)
    assert masked == sorted([3 * 10 + 3, 7 * 10 + 8])


# ---------------------------------------------------------------------------
# npy writer
# ---------------------------------------------------------------------------


def test_write_npy_with_meta_sidecar(tmp_path: Path) -> None:
    meta = _meta()
    mask = np.zeros(meta.detector_shape, dtype=np.uint8)
    mask[1, 1] = 1
    out = write_npy(tmp_path / "x.npy", mask, meta)
    re_loaded = np.load(out)
    assert np.array_equal(re_loaded, mask)
    sidecar = out.with_suffix(out.suffix + ".meta.json")
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["instrument_name"] == "EQ-SANS"
    assert payload["n_masked"] == 1
    assert "1=masked" in payload["convention"]


# ---------------------------------------------------------------------------
# Log writer
# ---------------------------------------------------------------------------


def test_log_path_for_sibling() -> None:
    p = Path("/tmp/mask.nxs")
    assert log_path_for(p) == Path("/tmp/mask.mask_log.json")


def test_write_log_round_trips_via_from_log(tmp_path: Path) -> None:
    meta = _meta()
    builder = MaskBuilder(meta.detector_shape, inverse=True)
    builder.add(Rectangle(1, 1, 4, 4))
    builder.add(Circle(7, 7, 2))
    mask = builder.build()
    log = write_log(tmp_path / "out.nxs", meta, builder, stats_for(mask))
    rebuilt = MaskBuilder.from_log(log)
    assert rebuilt.detector_shape == builder.detector_shape
    assert rebuilt.inverse == builder.inverse
    assert len(rebuilt.shapes) == 2
    assert np.array_equal(rebuilt.build(), mask)


def test_write_log_carries_provenance(tmp_path: Path) -> None:
    meta = _meta()
    builder = MaskBuilder(meta.detector_shape)
    builder.add(Rectangle(0, 0, 1, 1))
    log = write_log(tmp_path / "out.nxs", meta, builder, stats_for(builder.build()))
    payload = json.loads(log.read_text(encoding="utf-8"))
    assert payload["source_nxs"] == str(meta.source_path)
    assert payload["instrument"] == "EQ-SANS"
    assert payload["stats"]["masked_pixels"] == 4
    assert payload["sansdir_version"]
