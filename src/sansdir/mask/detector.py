"""Detector image loader for the mask GUI.

Wraps :func:`sansdir.plot.hdf5_detector.load_eqsans_raw` and pairs the
resulting heatmap with a flat ``pixel_ids`` array such that
``image.flatten()[k]`` corresponds to detector ID ``pixel_ids[k]``.

The pixel-ordering invariant is the heart of the writer's correctness
— get it wrong here and the writer silently masks the wrong detectors.
The alignment test in ``tests/mask/test_detector.py`` pins it.

Where ``pixel_ids`` comes from
------------------------------

1. If the file ships its own ``/entry/instrument/bank1/pixel_id`` array
   (the layout the spec hopes for), we use it verbatim. The synthetic
   test fixture exercises this path because we control the permutation
   and can assert exact alignment.
2. Real cluster EQSANS event-mode files don't carry a ``pixel_id``
   dataset — the bank groups hold only the event stream
   (``event_id``, ``event_index``, ...). The detector ID of every
   spectrum is implicit: each ``event_id`` is itself the detector ID,
   running over the full ``[0, EQSANS_NPIXELS_TOTAL)`` range. We
   reproduce that mapping by computing ``pixel_ids[r, c]`` from the
   same canonical layout (24 bank-pairs x 8 staggered tubes x 256
   pixels) that :func:`sansdir.plot.hdf5_detector._reorder_tubes` uses
   to build the heatmap. This is *not* a heuristic, it's the
   inverse of the existing reorder.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from sansdir.hdf.reader import HdfError, open_nexus
from sansdir.plot.hdf5_detector import (
    EQSANS_NPIXELS_PER_TUBE,
    EQSANS_NPIXELS_TOTAL,
    EQSANS_NTUBES,
    load_eqsans_raw,
)


class UnsupportedFileLayoutError(RuntimeError):
    """Raised when a NeXus file lacks the structure the loader needs."""


@dataclass(frozen=True, slots=True)
class SourceMeta:
    """Everything the writers need from the source file.

    Layout invariant: ``pixel_ids`` is 1D with
    ``len == prod(detector_shape)``, and ``pixel_ids[k]`` is the
    detector ID at flat index ``k`` in the heatmap (i.e.
    ``image.flatten()[k]``). The writers depend on this — keep the
    invariant intact when you touch :func:`load_detector_image`.
    """

    source_path: Path
    instrument_name: str
    detector_shape: tuple[int, int]
    pixel_ids: np.ndarray  # 1D int32 / int64
    run_number: str


def load_detector_image(path: Path | str) -> tuple[np.ndarray, SourceMeta]:
    """Load the heatmap + the matching ``pixel_ids`` for ``path``."""
    path = Path(path)
    image = load_eqsans_raw(path).image  # (256, 192)
    detector_shape = image.shape  # (n_rows, n_cols)
    pixel_ids = _resolve_pixel_ids(path, detector_shape)
    instrument_name = _read_str(path, "/entry/instrument/name") or "EQSANS"
    run_number = _read_str(path, "/entry/run_number")
    meta = SourceMeta(
        source_path=path.resolve(),
        instrument_name=instrument_name,
        detector_shape=detector_shape,
        pixel_ids=pixel_ids,
        run_number=run_number,
    )
    return image, meta


# ---------------------------------------------------------------------------
# pixel_ids resolution
# ---------------------------------------------------------------------------


def _resolve_pixel_ids(path: Path, detector_shape: tuple[int, int]) -> np.ndarray:
    """Return the flat ``(prod(shape),)`` pixel_ids array for ``path``."""
    n_expected = detector_shape[0] * detector_shape[1]

    # 1) Honour an explicit pixel_id dataset when the file ships one.
    try:
        with open_nexus(path) as fh:
            if "entry/instrument/bank1/pixel_id" in fh:
                arr = np.asarray(fh["entry/instrument/bank1/pixel_id"][()])
                flat = arr.reshape(-1).astype(np.int64)
                if flat.size != n_expected:
                    raise UnsupportedFileLayoutError(
                        f"{path}: bank1/pixel_id has {flat.size} entries, "
                        f"detector_shape implies {n_expected}"
                    )
                return flat
    except HdfError as exc:  # corrupt file etc.
        raise UnsupportedFileLayoutError(
            f"{path}: could not open file to read pixel_id ({exc})"
        ) from exc

    # 2) Canonical EQSANS event-mode layout: derive the mapping from the
    #    same reorder the heatmap loader applies. Only valid when the
    #    detector_shape matches what we know for EQSANS.
    if detector_shape == (EQSANS_NPIXELS_PER_TUBE, EQSANS_NTUBES):
        return _eqsans_canonical_pixel_ids()

    raise UnsupportedFileLayoutError(
        f"{path}: no /entry/instrument/bank1/pixel_id and detector_shape "
        f"{detector_shape} doesn't match the canonical EQSANS layout "
        f"({EQSANS_NPIXELS_PER_TUBE}, {EQSANS_NTUBES})"
    )


def _eqsans_canonical_pixel_ids() -> np.ndarray:
    """Return ``pixel_ids[k]`` for the heatmap's flat order.

    ``_reorder_tubes`` builds the ``(256, 192)`` heatmap from a flat
    ``(EQSANS_NPIXELS_TOTAL,)`` bincount where each cell ``b``
    corresponds to detector ID ``b``. We invert that operation by
    running an ``arange(EQSANS_NPIXELS_TOTAL)`` of detector IDs through
    the same reorder; the resulting ``(256, 192)`` array's
    ``.flatten()`` is the pixel_ids in heatmap order.
    """
    from sansdir.plot.hdf5_detector import _reorder_tubes

    detids = np.arange(EQSANS_NPIXELS_TOTAL, dtype=np.int64)
    arranged = _reorder_tubes(detids)  # (256, 192) of detector IDs
    return arranged.reshape(-1)


def _read_str(path: Path, key: str) -> str:
    try:
        with open_nexus(path) as fh:
            if key not in fh:
                return ""
            v = fh[key][()]
    except HdfError:
        return ""
    if isinstance(v, np.ndarray) and v.size:
        v = v.flat[0]
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return str(v)


__all__ = [
    "SourceMeta",
    "UnsupportedFileLayoutError",
    "load_detector_image",
]
