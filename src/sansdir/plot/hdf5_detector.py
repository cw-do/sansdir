"""Detector-counts heatmaps for EQSANS NeXus files.

Two loaders, picked automatically by inspecting the file's structure:

* :func:`load_eqsans_raw` — for raw event-mode files (the default DAS
  output ``EQSANS_<run>.nxs.h5``). Mirrors
  ``/SNS/EQSANS/shared/script/eqsanstools/EQSANS_raw_2D.py``: bincount
  the ``event_id`` of each ``/entry/bank<N>_events`` group into a
  ``256x192`` array, then reorder tubes [0,4,1,5,2,6,3,7] to match the
  physical detector layout.

* :func:`load_processed` — for files written by Mantid / drtsans
  (``mantid_workspace_1/workspace/values``). Same final shape, no
  reorder needed.

Both produce one ``(256, 192)`` array — pixel rows x tube columns —
which we render with ``imshow`` (LogNorm, viridis, "Tube" / "Pixel"
axis labels). This is a *single* detector image, not a per-bank tile,
because the 48 banks are physically one detector.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from sansdir.hdf.reader import HdfError, open_nexus

if TYPE_CHECKING:
    from matplotlib.figure import Figure


# EQSANS detector geometry — 48 banks of 8 tubes x 256 pixels each, in
# 24 columns of 8 tubes, total 192 tubes x 256 pixels per tube.
EQSANS_NPIXELS_PER_TUBE: int = 256
EQSANS_NTUBES: int = 192
EQSANS_NPIXELS_TOTAL: int = EQSANS_NPIXELS_PER_TUBE * EQSANS_NTUBES
EQSANS_NBANKS: int = 48
EQSANS_TUBE_REORDER: tuple[int, ...] = (0, 4, 1, 5, 2, 6, 3, 7)


@dataclass(frozen=True, slots=True)
class DetectorImage:
    """Final 2D image we hand to matplotlib."""

    image: np.ndarray  # shape (npixels, ntubes), rows = pixel index, cols = tube
    run_number: str
    title: str
    source: str  # "raw" | "processed" | "fallback"


# ---------------------------------------------------------------------------
# Raw loader (event mode) — mirrors EQSANS_raw_2D.py
# ---------------------------------------------------------------------------


def load_eqsans_raw(path: Path) -> DetectorImage:
    """Build the ``(256, 192)`` detector image from raw event-mode NeXus.

    Replicates the logic in
    ``/SNS/EQSANS/shared/script/eqsanstools/EQSANS_raw_2D.py``.
    """
    bc = np.zeros(EQSANS_NPIXELS_TOTAL, dtype=np.int64)
    with open_nexus(path) as fh:
        if "entry/bank1_events" not in fh:
            raise HdfError(f"{path}: no /entry/bank<N>_events groups (not raw EQSANS)")
        run_number = _scalar(fh, "entry/run_number")
        title = _scalar(fh, "entry/title")
        for b in range(1, EQSANS_NBANKS + 1):
            key = f"entry/bank{b}_events/event_id"
            if key not in fh:
                continue
            ids = np.asarray(fh[key][()], dtype=np.int64)
            if ids.size:
                bc += np.bincount(ids, minlength=EQSANS_NPIXELS_TOTAL)[:EQSANS_NPIXELS_TOTAL]
    image = _reorder_tubes(bc)
    return DetectorImage(image=image, run_number=run_number, title=title, source="raw")


def _reorder_tubes(bincounts: np.ndarray) -> np.ndarray:
    """Map a flat 49152-pixel bincount to a ``(256, 192)`` detector image.

    The EQSANS detector layout interleaves tubes [0,4,1,5,2,6,3,7]
    within each 8-tube bank — without this reorder the image is sliced
    incorrectly. Math taken verbatim from EQSANS_raw_2D.py.
    """
    if bincounts.size != EQSANS_NPIXELS_TOTAL:
        raise ValueError(
            f"_reorder_tubes: expected {EQSANS_NPIXELS_TOTAL} cells, got {bincounts.size}"
        )
    data = bincounts.reshape(-1, 8, EQSANS_NPIXELS_PER_TUBE).T  # (256, 8, 24)
    reordered = data[:, list(EQSANS_TUBE_REORDER), :]  # interleave tubes
    final = reordered.transpose().reshape(-1, EQSANS_NPIXELS_PER_TUBE)  # (192, 256)
    return final.T  # (256, 192)


# ---------------------------------------------------------------------------
# Processed loader — Mantid / drtsans output
# ---------------------------------------------------------------------------


def load_processed(path: Path) -> DetectorImage:
    """For files Mantid / drtsans wrote: 1D ``mantid_workspace_1/workspace/values``."""
    with open_nexus(path) as fh:
        if "mantid_workspace_1/workspace/values" not in fh:
            raise HdfError(
                f"{path}: no /mantid_workspace_1/workspace/values (not a processed EQSANS file)"
            )
        title = _scalar(fh, "mantid_workspace_1/title", default="")
        raw = np.asarray(fh["mantid_workspace_1/workspace/values"][()])
    if raw.size != EQSANS_NPIXELS_TOTAL:
        raise HdfError(
            f"{path}: workspace/values has {raw.size} elements, expected {EQSANS_NPIXELS_TOTAL}"
        )
    image = raw.reshape(EQSANS_NTUBES, EQSANS_NPIXELS_PER_TUBE).T  # (256, 192)
    return DetectorImage(image=image, run_number="", title=title, source="processed")


# ---------------------------------------------------------------------------
# Auto-dispatch
# ---------------------------------------------------------------------------


def load_detector_image(path: Path) -> DetectorImage:
    """Try the raw loader, then the processed loader.

    Raises :class:`HdfError` if neither shape is present.
    """
    try:
        return load_eqsans_raw(path)
    except HdfError as raw_err:
        try:
            return load_processed(path)
        except HdfError as proc_err:
            raise HdfError(
                f"{path}: not a recognised EQSANS NeXus shape\n"
                f"  raw: {raw_err}\n  processed: {proc_err}"
            ) from raw_err


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------


def make_detector_figure(path: Path, *, log_intensity: bool = True) -> Figure:
    """Render one EQSANS NeXus file as a single ``(256x192)`` heatmap."""
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    img = load_detector_image(Path(path))
    data = img.image.astype(float)
    if log_intensity:
        data = np.where(data > 0, data, np.nan)
    fig, ax = plt.subplots(figsize=(6, 7), layout="constrained")
    cm = _cmap_with_bad("viridis")
    norm: LogNorm | None = None
    if log_intensity:
        finite = data[np.isfinite(data)]
        if finite.size:
            vmin = max(1.0, float(np.nanmin(finite)))
            vmax = float(np.nanmax(finite))
            if vmax <= vmin:
                vmax = vmin * 1.01
            norm = LogNorm(vmin=vmin, vmax=vmax)
    im = ax.imshow(
        data,
        norm=norm,
        cmap=cm,
        extent=(0.5, EQSANS_NTUBES + 0.5, 0.5, EQSANS_NPIXELS_PER_TUBE + 0.5),
        origin="lower",
        aspect="auto",
    )
    cb = fig.colorbar(im, ax=ax, shrink=0.95)
    cb.set_label("counts")
    ax.set_xlabel("Tube")
    ax.set_ylabel("Pixel")
    title = f"EQSANS_{img.run_number}" if img.run_number else "EQSANS"
    if img.title:
        title = f"{title} — {img.title}"
    ax.set_title(title, fontsize=10)
    return fig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scalar(fh, key: str, *, default: str = "") -> str:  # type: ignore[no-untyped-def]
    """Read a scalar string-like dataset; tolerates ``[b'...']`` arrays."""
    if key not in fh:
        return default
    raw = fh[key][()]
    if isinstance(raw, np.ndarray) and raw.size:
        raw = raw.flat[0]
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _cmap_with_bad(name: str):  # type: ignore[no-untyped-def]
    import matplotlib as mpl

    cm = mpl.colormaps[name].copy()
    cm.set_bad("#bdbdbd")
    return cm
