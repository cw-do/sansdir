"""Detector-counts heatmaps for SNS NeXus event / histogram files.

Two shapes show up in practice:

* **Histogrammed** files (often after Mantid / drtsans reduction) keep
  pre-aggregated 2-D pixel arrays at
  ``/entry/instrument/bank<N>/data`` — the synthetic fixture in
  ``tests/conftest.py`` matches this shape.
* **Event-mode** files (the raw DAE output) keep a 1-D ``event_id``
  array per bank and no aggregated image. We histogram that with
  :func:`numpy.bincount` and reshape into a square-ish 2-D grid.
  Real detector geometry would need Mantid; this is a "best-effort"
  v1 view that's good enough for sanity checks.

In both cases we return a list of bank counts arrays — multiple banks
are tiled by the existing :func:`sansdir.plot.tile.make_tile_figure`
machinery, just like 2-D Iqxqy.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from sansdir.hdf.reader import open_nexus

if TYPE_CHECKING:
    import h5py
    from matplotlib.figure import Figure


@dataclass(frozen=True, slots=True)
class BankImage:
    """One detector bank as a 2D counts array."""

    name: str
    counts: np.ndarray  # 2D
    total: int


# ---------------------------------------------------------------------------
# Bank reading
# ---------------------------------------------------------------------------


def list_banks(path: Path, *, instrument_path: str = "/entry/instrument") -> list[str]:
    """Return sorted bank group names found under ``instrument_path``."""
    with open_nexus(path) as fh:
        if instrument_path not in fh:
            return []
        inst = fh[instrument_path]
        return sorted(name for name in inst if name.startswith("bank"))


def read_bank_image(
    file: h5py.File, bank_name: str, *, instrument_path: str = "/entry/instrument"
) -> BankImage | None:
    """Materialise a 2D counts array for ``bank_name``.

    Returns ``None`` if the bank exists but has neither aggregated
    ``data`` nor ``event_id`` we can use.
    """
    import h5py

    bank_path = f"{instrument_path}/{bank_name}"
    if bank_path not in file:
        return None
    bank = file[bank_path]
    if not isinstance(bank, h5py.Group):
        return None

    # Path 1: pre-aggregated 2D-or-3D pixel array.
    if "data" in bank:
        ds = bank["data"]
        if isinstance(ds, h5py.Dataset) and ds.ndim >= 2:
            arr = np.asarray(ds[()])
            if arr.ndim == 3:
                # (tof, x, y) or similar — sum over the first axis.
                arr = arr.sum(axis=0)
            counts = arr.astype(np.int64, copy=False)
            return BankImage(name=bank_name, counts=counts, total=int(counts.sum()))

    # Path 2: event-mode — bincount the event_id.
    if "event_id" in bank:
        ids = np.asarray(bank["event_id"][()], dtype=np.int64)
        if ids.size == 0:
            return BankImage(name=bank_name, counts=np.zeros((1, 1), dtype=np.int64), total=0)
        # Normalise to start from the smallest id so we don't allocate a
        # giant array for IDs that begin at 1e6+.
        offset = int(ids.min())
        relative = ids - offset
        nbins = int(relative.max()) + 1
        flat = np.bincount(relative, minlength=nbins).astype(np.int64)
        # Reshape into a near-square grid; the row count is whichever
        # divisor of ``nbins`` is closest to sqrt(nbins).
        rows, cols = _factor_near_square(flat.size)
        if rows * cols != flat.size:
            # Pad with zeros so reshape works; the trailing pixels read
            # as low-count regions, which is fine for "where did
            # neutrons land" sanity checks.
            padded = np.zeros(rows * cols, dtype=flat.dtype)
            padded[: flat.size] = flat
            flat = padded
        counts = flat.reshape(rows, cols)
        return BankImage(name=bank_name, counts=counts, total=int(counts.sum()))

    return None


def read_bank_images(path: Path) -> list[BankImage]:
    """All banks in ``path`` that we can render. Sorted by bank name."""
    out: list[BankImage] = []
    with open_nexus(path) as fh:
        for name in list_banks(path):
            img = read_bank_image(fh, name)
            if img is not None and img.counts.size > 0:
                out.append(img)
    return out


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------


def make_detector_figure(path: Path, *, log_intensity: bool = True) -> Figure:
    """One NeXus file → tile of bank counts heatmaps.

    Banks are sorted by name; each rendered as a single
    ``pcolormesh``. With many banks the layout falls back to the same
    4-wide grid :mod:`sansdir.plot.tile` uses for Iqxqy tiles.
    """
    import math

    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm
    from matplotlib.ticker import MaxNLocator

    banks = read_bank_images(Path(path))
    if not banks:
        raise ValueError(f"{path}: no detector banks with usable counts found")

    n = len(banks)
    ncols = min(4, n)
    nrows = math.ceil(n / ncols)

    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(2.6 * ncols, 2.6 * nrows),
        squeeze=False,
        layout="constrained",
    )
    axes_flat = axes.ravel()

    # Shared colorbar across every bank — common log scale.
    finite_positive = np.concatenate(
        [b.counts[b.counts > 0].ravel() for b in banks if (b.counts > 0).any()]
    )
    if log_intensity and finite_positive.size:
        vmin = max(1.0, float(finite_positive.min()))
        vmax = float(finite_positive.max())
        if vmax <= vmin:
            vmax = vmin * 1.01
        norm: LogNorm | None = LogNorm(vmin=vmin, vmax=vmax)
    else:
        norm = None

    cm = _cmap_with_bad("viridis")
    mappable = None
    for i in range(nrows * ncols):
        ax = axes_flat[i]
        if i >= n:
            ax.axis("off")
            continue
        bank = banks[i]
        counts = bank.counts.astype(float)
        if log_intensity:
            counts = np.where(counts > 0, counts, np.nan)
        pcm = ax.pcolormesh(counts, cmap=cm, norm=norm, shading="flat")
        ax.set_aspect("equal", adjustable="box")
        ax.set_box_aspect(1)
        ax.xaxis.set_major_locator(MaxNLocator(3))
        ax.yaxis.set_major_locator(MaxNLocator(3))
        ax.tick_params(which="both", length=2, labelsize=7)
        ax.text(
            0.5,
            0.98,
            f"{bank.name}: {bank.total:,}",
            ha="center",
            va="top",
            fontsize=7,
            color="white",
            weight="bold",
            transform=ax.transAxes,
            bbox={"facecolor": "black", "alpha": 0.5, "pad": 1, "edgecolor": "none"},
        )
        if mappable is None:
            mappable = pcm

    if mappable is not None:
        cb = fig.colorbar(
            mappable,
            ax=axes_flat.tolist(),
            orientation="vertical",
            shrink=0.95,
            pad=0.02,
        )
        cb.set_label("counts")

    fig.suptitle(f"{Path(path).name} — {n} bank(s), {sum(b.total for b in banks):,} total")
    return fig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _factor_near_square(n: int) -> tuple[int, int]:
    """Return ``(rows, cols)`` whose product is ≥ ``n`` and as square as possible.

    Used for event-mode banks where we don't know the real detector
    pixel layout — we just want the histogram to render as something
    that vaguely *looks* like a 2D image rather than a long stripe.
    """
    if n <= 1:
        return 1, max(1, n)
    side = round(n**0.5)
    # Find the factor of n closest to side; if n is prime, pad by reshaping
    # to (side, ceil(n/side)) — caller pads with zeros if needed.
    for r in range(side, 0, -1):
        if n % r == 0:
            return r, n // r
    rows = side
    cols = (n + rows - 1) // rows
    return rows, cols


def _cmap_with_bad(name: str):  # type: ignore[no-untyped-def]
    import matplotlib as mpl

    cm = mpl.colormaps[name].copy()
    cm.set_bad("#bdbdbd")
    return cm
