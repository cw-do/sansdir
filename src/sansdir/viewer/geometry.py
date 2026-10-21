"""EQSANS display grid ↔ detector ID ↔ Mantid bank / tube / pixel.

The viewer draws the same ``(256, 192)`` image the rest of sansdir uses
(rows = pixel along tube, cols = tube after the ``[0,4,1,5,2,6,3,7]``
interleave). This module owns every translation out of that grid so the
UI never does detector arithmetic itself.

Naming — verified against Mantid's ``EQ-SANS_Definition.xml`` via
``LoadEmptyInstrument`` on 2026-10-21:

* Detector IDs come in 48 blocks of 1024 (4 tubes x 256 pixels). The
  raw NeXus group ``bank<N>_events`` holds block ``N-1``; that is the
  **DAS bank** number.
* Mantid's IDF names the blocks differently: even blocks are the
  front panel ``bank1..bank24``, odd blocks the back panel
  ``bank25..bank48``. So ID 1024 is ``back-panel/bank25/tube1/pixel1``
  and ID 2048 is ``front-panel/bank2/tube1/pixel1``.
* ``tube1..4`` and ``pixel1..256`` are 1-based; ``pixel1`` is the
  bottom of the tube, which is image row 0.

The older :mod:`sansdir.mask.banktube` helpers (and the ``b<N>`` mask
spec) count *DAS* blocks from 0. They are untouched; the readout shows
both names so nobody has to guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

import numpy as np

from sansdir.plot.hdf5_detector import (
    EQSANS_NBANKS,
    EQSANS_NPIXELS_PER_TUBE,
    EQSANS_NPIXELS_TOTAL,
    EQSANS_NTUBES,
)

NROWS: int = EQSANS_NPIXELS_PER_TUBE  # 256 — pixels along a tube (y)
NCOLS: int = EQSANS_NTUBES  # 192 — tubes across the detector (x)
NPIX: int = EQSANS_NPIXELS_TOTAL  # 49152
PIXELS_PER_BLOCK: int = 1024
TUBES_PER_BANK: int = 4
NBANKS_PER_PANEL: int = EQSANS_NBANKS // 2  # 24
# Width / height of one display cell, from the IDF: interleaved front/back
# tubes sit ~5.5 mm apart across the detector, pixels 1.042 m / 255 apart
# along a tube. Locks the on-screen aspect so the detector isn't squashed.
CELL_ASPECT: float = 5.5 / (1042.0 / 255)


@cache
def detector_ids() -> np.ndarray:
    """``(256, 192)`` array: the detector ID drawn at ``[row, col]``.

    Built by pushing ``arange(NPIX)`` through the same reorder the
    heatmap loaders use, so it can never disagree with them.
    """
    from sansdir.mask.detector import _eqsans_canonical_pixel_ids

    ids = _eqsans_canonical_pixel_ids().reshape(NROWS, NCOLS)
    ids.setflags(write=False)
    return ids


def to_image(flat: np.ndarray) -> np.ndarray:
    """Per-detector-ID values ``(NPIX,)`` → display image ``(256, 192)``."""
    image: np.ndarray = flat[detector_ids()]
    return image


def to_flat(image: np.ndarray) -> np.ndarray:
    """Inverse of :func:`to_image`."""
    flat = np.empty(NPIX, dtype=image.dtype)
    flat[detector_ids()] = image
    return flat


@dataclass(frozen=True, slots=True)
class PixelInfo:
    """Everything the hover readout shows for one display cell."""

    x: int  # display column 0..191
    y: int  # display row 0..255 (0 = bottom)
    detid: int
    panel: str  # "front" | "back"
    bank: int  # Mantid IDF bank 1..48
    tube: int  # Mantid tube 1..4 within the bank
    pixel: int  # Mantid pixel 1..256 along the tube (1 = bottom)
    das_bank: int  # raw NeXus bank<N>_events group, 1..48


def _info(detid: int, col: int, row: int) -> PixelInfo:
    block, within = divmod(detid, PIXELS_PER_BLOCK)
    tube0, pixel0 = divmod(within, NROWS)
    front = block % 2 == 0
    return PixelInfo(
        x=col,
        y=row,
        detid=detid,
        panel="front" if front else "back",
        bank=block // 2 + 1 + (0 if front else NBANKS_PER_PANEL),
        tube=tube0 + 1,
        pixel=pixel0 + 1,
        das_bank=block + 1,
    )


def info_for_detid(detid: int) -> PixelInfo:
    """Mantid / DAS naming for a detector ID, with its display cell."""
    if not 0 <= detid < NPIX:
        raise ValueError(f"detector ID {detid} out of range 0..{NPIX - 1}")
    row, col = divmod(int(to_flat(np.arange(NPIX).reshape(NROWS, NCOLS))[detid]), NCOLS)
    return _info(detid, col, row)


def pixel_info(x: float, y: float) -> PixelInfo | None:
    """Info for the display cell containing ``(x, y)``; ``None`` if off-detector.

    Cell ``(col, row)`` spans ``[col, col+1) x [row, row+1)``, which is
    how pyqtgraph places an image at the origin.
    """
    col, row = int(np.floor(x)), int(np.floor(y))
    if not (0 <= col < NCOLS and 0 <= row < NROWS):
        return None
    return _info(int(detector_ids()[row, col]), col, row)


def bank_columns(bank: int) -> list[int]:
    """Display columns holding Mantid ``bank`` (1..48), left to right."""
    if not 1 <= bank <= EQSANS_NBANKS:
        raise ValueError(f"bank {bank} out of range 1..{EQSANS_NBANKS}")
    front = bank <= NBANKS_PER_PANEL
    block = 2 * (bank - 1) if front else 2 * (bank - NBANKS_PER_PANEL - 1) + 1
    col_blocks = detector_ids()[0] // PIXELS_PER_BLOCK
    return [int(c) for c in np.nonzero(col_blocks == block)[0]]


__all__ = [
    "CELL_ASPECT",
    "NCOLS",
    "NPIX",
    "NROWS",
    "PixelInfo",
    "bank_columns",
    "detector_ids",
    "info_for_detid",
    "pixel_info",
    "to_flat",
    "to_image",
]
