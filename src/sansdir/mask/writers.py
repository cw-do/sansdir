"""Mask file writers — pure stdlib + h5py + numpy, no Mantid imports.

Three formats:

* :func:`write_xml`  — Mantid SaveMask v1 format (``<detector-masking>``)
* :func:`write_nxs`  — Mantid Processed NeXus laid out the same way
  ``MantidWorkspace`` ``MaskWorkspace`` saves itself
* :func:`write_npy`  — plain ``np.save`` plus a ``.meta.json`` sidecar

Plus :func:`write_log` — a ``mask_log.json`` next to the saved file
that round-trips through :meth:`MaskBuilder.from_log`.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from sansdir import __version__
from sansdir.mask.core import MaskBuilder, Shape
from sansdir.mask.detector import SourceMeta

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _masked_detector_ids(mask: np.ndarray, source_meta: SourceMeta) -> np.ndarray:
    """Return sorted detector IDs at the masked (==1) cells.

    The flattening order of ``mask`` and ``source_meta.pixel_ids`` must
    agree — that's the whole-system invariant the
    ``test_pixel_ordering_alignment_*`` tests pin. We sort the result
    so ranges compress cleanly downstream.
    """
    flat_mask = mask.reshape(-1)
    flat_ids = source_meta.pixel_ids.reshape(-1)
    if flat_mask.size != flat_ids.size:
        raise ValueError(
            f"mask size ({flat_mask.size}) != pixel_ids size ({flat_ids.size})"
        )
    return np.sort(flat_ids[flat_mask.astype(bool)])


def _compress_ranges(ids: Iterable[int]) -> str:
    """``[5, 9, 10, 11, 12, 42, 43, 44]`` → ``"5,9-12,42-44"``."""
    sorted_ids = sorted({int(i) for i in ids})
    if not sorted_ids:
        return ""
    runs: list[tuple[int, int]] = []
    start = prev = sorted_ids[0]
    for n in sorted_ids[1:]:
        if n == prev + 1:
            prev = n
            continue
        runs.append((start, prev))
        start = prev = n
    runs.append((start, prev))
    return ",".join(f"{lo}" if lo == hi else f"{lo}-{hi}" for lo, hi in runs)


def _bytes(value: str) -> np.bytes_:
    """Pack a python str as a fixed-length ASCII NeXus scalar.

    Older Mantid (<= 6.12) is strict about ASCII fixed-length; newer
    accepts UTF-8 variable-length. ``np.bytes_`` is the
    most-compatible common form across Mantid versions.
    """
    return np.bytes_(value.encode("utf-8") if isinstance(value, str) else value)


# ---------------------------------------------------------------------------
# XML writer (Mantid SaveMask v1 — <detector-masking>)
# ---------------------------------------------------------------------------


def write_xml(path: Path | str, mask: np.ndarray, source_meta: SourceMeta) -> Path:
    """Write Mantid SaveMask v1 XML and return the path."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    detids = _masked_detector_ids(mask, source_meta)
    root = ET.Element("detector-masking")
    group = ET.SubElement(root, "group")
    detids_el = ET.SubElement(group, "detids")
    detids_el.text = _compress_ranges(detids.tolist())
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ", level=0)
    tree.write(out, encoding="utf-8", xml_declaration=True)
    return out


# ---------------------------------------------------------------------------
# NeXus writer (Mantid Processed NeXus — MaskWorkspace shape)
# ---------------------------------------------------------------------------


def write_nxs(
    output_path: Path | str,
    mask: np.ndarray,
    source_meta: SourceMeta,
) -> Path:
    """Write a Mantid event-workspace NeXus mirror of ``mask_4m2.nxs``.

    The reference file ``tests/data/mask_4m2.nxs`` (which sansdir's
    ``p`` keystroke loads correctly) is a ``SaveNexus(EventWorkspace)``
    output, NOT the histogram MaskWorkspace earlier drafts of this
    writer produced. We mirror its layout dataset-for-dataset so the
    saved mask plots back through the existing
    ``event_workspace/indices`` path in
    :func:`sansdir.plot.hdf5_detector.load_processed`.

    Mask encoding: each **unmasked** detector carries one synthetic
    event, masked detectors carry zero — same visual convention as
    the reference ``mask_4m2.nxs`` (a real beamstop file where the
    blocked region naturally has 0 events). When the file is plotted
    via the existing ``p`` keystroke, the masked area shows up as
    grey "no-data" cells over the detector. ``pulsetime`` and ``tof``
    are zero-filled — only *which* detectors have events matters.

    The MaskBuilder still uses the Mantid SpecialWorkspace2D
    convention internally (``1 = masked``); only the on-disk event
    encoding inverts so the file's visual matches users' intuition
    from instrument-room mask files.

    Layout (every dataset / attribute mirrors the reference file):

    * ``mantid_workspace_1`` (NXentry).
    * ``definition`` / ``definition_local`` = ``"Mantid Processed
      Workspace"`` with the standard ``URL`` / ``Version`` attrs.
    * ``event_workspace`` (NXdata) with ``axis1`` (TOF bin edges,
      single bin since this is a mask), ``axis2`` (spectrum number
      1..N), ``indices`` (cumsum boundaries, length N+1),
      ``pulsetime`` (int64 zeros), ``tof`` (float64 zeros).
    * ``instrument/detector`` (NXdetector) with the standard
      five-dataset spectrum-to-detector mapping; identity
      ``detector_list`` so spectrum k == detector k.
    * ``process`` (NXprocess) with ``MantidEnvironment`` plus one
      ``MantidAlgorithm_*`` note for provenance.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = source_meta.pixel_ids.size
    if mask.size != n:
        raise ValueError(
            f"mask / pixel_ids ordering mismatch: mask {mask.size} vs ids {n}"
        )

    # Mask is in heatmap-flat order. Re-order into detector-id order
    # so ``indices[k+1] - indices[k]`` lines up with detector k
    # (== spectrum k) for the identity ``detector_list`` we write.
    pid = source_meta.pixel_ids.reshape(-1).astype(np.int64)
    inv_pid = np.argsort(pid)  # inv_pid[d] = k such that pid[k] == d
    # Invert at write-time so masked detectors have 0 events (grey when
    # plotted, matching mask_4m2.nxs's visual convention) and unmasked
    # detectors have 1 event each.
    masked_in_det_order = mask.reshape(-1).astype(np.uint8)[inv_pid]
    unmasked_in_det_order = (1 - masked_in_det_order).astype(np.uint8)

    indices = np.zeros(n + 1, dtype=np.int64)
    indices[1:] = np.cumsum(unmasked_in_det_order, dtype=np.int64)
    n_events = int(indices[-1])
    pulsetime = np.zeros(n_events, dtype=np.int64)
    tof = np.zeros(n_events, dtype=np.float64)

    iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    title = (
        f"{source_meta.instrument_name}_{source_meta.run_number}_mask"
        if source_meta.run_number
        else f"{source_meta.instrument_name}_mask"
    )

    with h5py.File(out, "w") as f:
        f.attrs["NX_class"] = _bytes("NXroot")
        f.attrs["NeXus_version"] = _bytes("4.4.3")
        f.attrs["file_name"] = _bytes(str(out))
        f.attrs["HDF5_Version"] = _bytes(h5py.version.hdf5_version)

        ent = f.create_group("mantid_workspace_1")
        ent.attrs["NX_class"] = "NXentry"
        ent.create_dataset("title", data=np.array([_bytes(title)]))

        defn = np.array([_bytes("Mantid Processed Workspace")])
        d = ent.create_dataset("definition", data=defn)
        d.attrs["URL"] = "http://www.nexusformat.org/instruments/xml/NXprocessed.xml"
        d.attrs["Version"] = "1.0"
        dl = ent.create_dataset("definition_local", data=defn)
        dl.attrs["URL"] = "http://www.isis.rl.ac.uk/xml/IXmantid.xml"
        dl.attrs["Version"] = "1.0"
        ent.create_dataset(
            "workspace_name", data=np.array([_bytes(out.name)])
        )

        # ``event_workspace`` group is the discriminator the existing
        # sansdir plot loader keys off — and matches mask_4m2.nxs.
        ew = ent.create_group("event_workspace")
        ew.attrs["NX_class"] = "NXdata"
        a1 = ew.create_dataset(
            "axis1", data=np.array([0.0, 1000.0], dtype=np.float64)
        )
        a1.attrs["distribution"] = "0"
        a1.attrs["units"] = "TOF"
        a2 = ew.create_dataset(
            "axis2", data=np.arange(1, n + 1, dtype=np.float64)
        )
        a2.attrs["caption"] = "Spectrum"
        a2.attrs["label"] = ""
        a2.attrs["units"] = "spectraNumber"
        ix = ew.create_dataset("indices", data=indices)
        ix.attrs["units"] = "Counts"
        ix.attrs["unit_label"] = "Counts"
        ew.create_dataset("pulsetime", data=pulsetime)
        ew.create_dataset("tof", data=tof)

        inst = ent.create_group("instrument")
        inst.attrs["NX_class"] = "NXinstrument"
        inst.attrs["version"] = np.int32(1)
        inst.create_dataset(
            "name", data=np.array([_bytes(source_meta.instrument_name)])
        )
        det = inst.create_group("detector")
        det.attrs["NX_class"] = "NXdetector"
        det.attrs["version"] = np.int32(1)
        det.create_dataset(
            "detector_list", data=np.arange(n, dtype=np.int32)
        )
        det.create_dataset("detector_count", data=np.ones(n, dtype=np.int32))
        det.create_dataset("detector_index", data=np.arange(n, dtype=np.int32))
        det.create_dataset(
            "detector_positions", data=np.zeros((n, 3), dtype=np.float64)
        )
        det.create_dataset("spectra", data=np.arange(1, n + 1, dtype=np.int32))

        smp = ent.create_group("sample")
        smp.attrs["NX_class"] = "NXsample"
        smp.create_dataset("name", data=np.array([_bytes("")]))

        proc = ent.create_group("process")
        proc.attrs["NX_class"] = "NXprocess"
        env = proc.create_group("MantidEnvironment")
        env.attrs["NX_class"] = "NXnote"
        env.create_dataset("author", data=np.array([_bytes("sansdir")]))
        env.create_dataset("date", data=np.array([_bytes(iso)]))
        env.create_dataset(
            "description", data=np.array([_bytes("Mantid Environment data")])
        )
        env.create_dataset(
            "data",
            data=np.array(
                [_bytes("sansdir mask writer; pure python; no Mantid runtime.")]
            ),
        )
        alg = proc.create_group("MantidAlgorithm_1")
        alg.attrs["NX_class"] = "NXnote"
        alg.create_dataset("author", data=np.array([_bytes("sansdir")]))
        alg.create_dataset("date", data=np.array([_bytes(iso)]))
        alg.create_dataset(
            "description", data=np.array([_bytes("Mantid Algorithm data")])
        )
        alg.create_dataset(
            "data",
            data=np.array(
                [_bytes(f"sansdir.mask.create; SourceFile={source_meta.source_path}")]
            ),
        )
    return out


# ---------------------------------------------------------------------------
# npy writer (numpy + json sidecar)
# ---------------------------------------------------------------------------


def write_npy(path: Path | str, mask: np.ndarray, source_meta: SourceMeta) -> Path:
    """Save the raw ``uint8`` mask plus a ``.meta.json`` sidecar."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.save(out, mask)
    sidecar = out.with_suffix(out.suffix + ".meta.json")
    sidecar.write_text(
        json.dumps(
            {
                "source_path": str(source_meta.source_path),
                "instrument_name": source_meta.instrument_name,
                "detector_shape": list(source_meta.detector_shape),
                "run_number": source_meta.run_number,
                "n_masked": int(np.count_nonzero(mask)),
                "convention": "1=masked, 0=kept (Mantid SpecialWorkspace2D)",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return out


# ---------------------------------------------------------------------------
# Common log writer (mask_log.json)
# ---------------------------------------------------------------------------


def log_path_for(output_path: Path | str) -> Path:
    """Return the canonical ``<basename>.mask_log.json`` next to ``output_path``."""
    p = Path(output_path)
    return p.with_name(p.stem + ".mask_log.json")


def write_log(
    output_path: Path | str,
    source_meta: SourceMeta,
    builder: MaskBuilder,
    mask_stats: dict[str, Any] | None = None,
) -> Path:
    """Write ``<basename>.mask_log.json`` and return its path.

    The schema matches § 9.6.6 — every field a future
    :meth:`MaskBuilder.from_log` needs to reconstruct the *exact* same
    builder, plus provenance for humans reading the file later.
    """
    log = log_path_for(output_path)
    log.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "sansdir_version": __version__,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_nxs": str(source_meta.source_path),
        "instrument": source_meta.instrument_name,
        "detector_shape": list(source_meta.detector_shape),
        "inverse": bool(builder.inverse),
        "shapes": [s.to_dict() for s in builder.shapes],
        "stats": dict(mask_stats or {}),
    }
    log.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return log


def shapes_from_log(path: Path | str) -> tuple[list[Shape], bool, tuple[int, int]]:
    """Inverse of :func:`write_log` — returns ``(shapes, inverse, shape)``."""
    builder = MaskBuilder.from_log(path)
    return list(builder.shapes), builder.inverse, builder.detector_shape


def stats_for(mask: np.ndarray) -> dict[str, float]:
    """Convenience: ``masked_pixels`` and ``masked_fraction`` for a mask."""
    n = int(mask.size)
    masked = int(np.count_nonzero(mask))
    return {
        "masked_pixels": masked,
        "masked_fraction": (masked / n) if n else 0.0,
    }


__all__ = [
    "log_path_for",
    "shapes_from_log",
    "stats_for",
    "write_log",
    "write_npy",
    "write_nxs",
    "write_xml",
]


