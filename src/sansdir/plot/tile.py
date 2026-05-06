"""Single + multi-2D plot layouts for Iqxqy data.

* :func:`make_iqxqy_figure` — one file, one ``pcolormesh`` with colorbar.
* :func:`make_tile_figure`  — N files in a ``ceil(sqrt(N))`` grid, with
  either one shared colorbar or per-subplot colorbars.

Both functions return the matplotlib :class:`~matplotlib.figure.Figure`
so the caller (TUI subprocess or headless save path) decides what to
do with it — same split as the 1D path.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import numpy as np

from sansdir.plot.ascii2d import Iq2D, read_iqxqy

if TYPE_CHECKING:
    from matplotlib.figure import Figure

ColorbarMode = Literal["shared", "independent"]


# ---------------------------------------------------------------------------
# Single 2D
# ---------------------------------------------------------------------------


def make_iqxqy_figure(
    path: Path,
    *,
    cmap: str = "viridis",
    log_intensity: bool = False,
    title: str | None = None,
) -> Figure:
    """One Iqxqy file → one pcolormesh + colorbar.

    NaN cells (masked beam stop, dead pixels) render in a soft grey via
    :func:`_cmap_with_bad`, so the user can see the *shape* of the mask
    rather than mistaking it for missing data.
    """
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    ds = read_iqxqy(Path(path))
    fig, ax = plt.subplots(figsize=(7, 6))
    norm = LogNorm() if log_intensity else None
    intensity = _safe_for_log(ds.intensity) if log_intensity else ds.intensity
    cm = _cmap_with_bad(cmap)
    pcm = ax.pcolormesh(ds.qx, ds.qy, intensity, cmap=cm, norm=norm, shading="auto")
    fig.colorbar(pcm, ax=ax, label=r"$I(q_x, q_y)$ (cm$^{-1}$)")
    ax.set_xlabel(r"$q_x$ (Å$^{-1}$)")
    ax.set_ylabel(r"$q_y$ (Å$^{-1}$)")
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_title(title or ds.path.name)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Multi-2D tile
# ---------------------------------------------------------------------------


def make_tile_figure(
    paths: Iterable[Path],
    *,
    cmap: str = "viridis",
    colorbar_mode: ColorbarMode = "shared",
    log_intensity: bool = False,
    title: str | None = None,
) -> Figure:
    """N Iqxqy files → ceil(sqrt(N)) x ceil(sqrt(N)) grid.

    ``colorbar_mode`` selects between one shared colorbar (vmin/vmax =
    common mean +- 3 sigma across all data, matches :pep:`PLANNING.md` §4.5)
    and per-subplot colorbars.
    """
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    datasets = [read_iqxqy(Path(p)) for p in paths]
    if not datasets:
        raise ValueError("make_tile_figure: at least one file required")
    n = len(datasets)
    if n == 1:
        return make_iqxqy_figure(
            datasets[0].path, cmap=cmap, log_intensity=log_intensity, title=title
        )

    side = math.ceil(math.sqrt(n))
    fig, axes = plt.subplots(side, side, figsize=(4 * side, 4 * side), squeeze=False)
    flat_axes = axes.ravel()

    vmin: float | None = None
    vmax: float | None = None
    if colorbar_mode == "shared":
        vmin, vmax = _shared_vrange(datasets)

    pcm_for_shared_bar = None
    cm = _cmap_with_bad(cmap)
    for i, ds in enumerate(datasets):
        ax = flat_axes[i]
        norm: object | None = None
        intensity = ds.intensity
        if log_intensity:
            intensity = _safe_for_log(intensity)
            norm = LogNorm(vmin=vmin if vmin and vmin > 0 else None, vmax=vmax)
        pcm = ax.pcolormesh(
            ds.qx,
            ds.qy,
            intensity,
            cmap=cm,
            norm=norm,
            vmin=None if log_intensity else vmin,
            vmax=None if log_intensity else vmax,
            shading="auto",
        )
        ax.set_xlabel(r"$q_x$ (Å$^{-1}$)")
        ax.set_ylabel(r"$q_y$ (Å$^{-1}$)")
        ax.set_aspect("equal", adjustable="datalim")
        ax.set_title(ds.path.name, fontsize="small")
        if colorbar_mode == "independent":
            fig.colorbar(pcm, ax=ax)
        elif pcm_for_shared_bar is None:
            pcm_for_shared_bar = pcm

    # Hide any unused subplots in the trailing row.
    for j in range(n, side * side):
        flat_axes[j].set_visible(False)

    if colorbar_mode == "shared" and pcm_for_shared_bar is not None:
        # One colorbar on the right, spanning the full figure height.
        fig.subplots_adjust(right=0.88)
        cax = fig.add_axes((0.91, 0.1, 0.02, 0.8))
        fig.colorbar(pcm_for_shared_bar, cax=cax, label=r"$I(q_x, q_y)$")
    else:
        fig.tight_layout()

    if title:
        fig.suptitle(title)
    return fig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _shared_vrange(datasets: list[Iq2D]) -> tuple[float, float]:
    """``mean +- 3 sigma`` across every cell of every dataset (PLANNING.md §4.5)."""
    flat = np.concatenate([d.intensity[~np.isnan(d.intensity)].ravel() for d in datasets])
    if flat.size == 0:
        return 0.0, 1.0
    mean = float(np.mean(flat))
    std = float(np.std(flat))
    return mean - 3 * std, mean + 3 * std


def _cmap_with_bad(name: str):  # type: ignore[no-untyped-def]
    """Copy the named colormap and set "bad" (NaN) cells to a soft grey.

    matplotlib's default for masked / NaN cells is fully transparent,
    which on a default white axes face also looks white — visually
    indistinguishable from the colormap's lowest value. Setting an
    explicit grey makes a beam-stop mask visible at a glance.
    """
    import matplotlib as mpl

    cm = mpl.colormaps[name].copy()
    cm.set_bad("#bdbdbd")
    return cm


def _safe_for_log(arr: np.ndarray) -> np.ndarray:
    """Replace non-positive values with the smallest positive in the array.

    LogNorm chokes on ``≤ 0``; SANS data does have legitimate zeros and
    occasional negatives from background subtraction. Floor at the
    minimum positive so log scaling stays well-defined.
    """
    positive = arr[arr > 0]
    if positive.size == 0:
        return arr
    floor = float(positive.min())
    return np.where(arr > 0, arr, floor)
