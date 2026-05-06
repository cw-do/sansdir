"""Single + multi-2D plot layouts for Iqxqy data.

Conventions follow ``/SNS/EQSANS/shared/script/eqsanstools/plot_iqxqy.py``,
which is the reference 2D plot for EQSANS users:

* **log intensity by default** — SANS data spans many orders of magnitude;
  set ``log_intensity=False`` to override.
* **Cell edges, not centres** — qx/qy in the file are bin centres, so we
  derive edges via half-spacing (``centers_to_edges``) before passing to
  ``pcolormesh``. Otherwise cells are offset by half a bin.
* **Tile layout: 4 columns x ceil(N/4) rows**, with one shared colorbar in
  a dedicated last column. Per-subplot colorbars available via
  ``colorbar_mode="independent"``.
* **Filename overlay** in each tile (small white-on-black tag at the
  top), and axis labels only on the bottom-left subplot.
* **Natural file ordering** by basename so ``run10`` comes after
  ``run2``, not before.
"""

from __future__ import annotations

import math
import re
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
    log_intensity: bool = True,
    title: str | None = None,
) -> Figure:
    """One Iqxqy file → one pcolormesh + colorbar.

    Defaults to log-scaled intensity (the SANS norm). Non-positive cells
    are masked rather than floored — they render in the colormap's
    "bad" colour (soft grey) so a beam-stop or dead-pixel mask reads as
    "no data" instead of "minimum intensity".
    """
    import matplotlib.pyplot as plt

    ds = read_iqxqy(Path(path))
    fig, ax = plt.subplots(figsize=(7, 6))
    intensity, norm = _intensity_and_norm(ds.intensity, log_intensity=log_intensity)
    cm = _cmap_with_bad(cmap)
    x_edges, y_edges = _grid_edges(ds.qx, ds.qy)
    pcm = ax.pcolormesh(x_edges, y_edges, intensity, cmap=cm, norm=norm, shading="flat")
    fig.colorbar(pcm, ax=ax, label=r"$I(q_x, q_y)$ (cm$^{-1}$)")
    ax.set_xlabel(r"$q_x$ (Å$^{-1}$)")
    ax.set_ylabel(r"$q_y$ (Å$^{-1}$)")
    ax.set_aspect("equal", adjustable="box")
    ax.set_box_aspect(1)
    ax.set_title(title or ds.path.name)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Multi-2D tile
# ---------------------------------------------------------------------------


TILE_NCOLS: int = 4


def make_tile_figure(
    paths: Iterable[Path],
    *,
    cmap: str = "viridis",
    colorbar_mode: ColorbarMode = "shared",
    log_intensity: bool = True,
    title: str | None = None,
) -> Figure:
    """N Iqxqy files → 4-wide tile with one shared colorbar.

    Shared mode uses a single :class:`LogNorm` (log-default for SANS)
    spanning the union of positive intensities across all files. Per-
    subplot colorbars are available via ``colorbar_mode="independent"``.

    Filenames are sorted in natural order (``run2`` before ``run10``)
    and shown as a small overlay tag inside each tile so the layout
    stays compact at small sizes.
    """
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm
    from matplotlib.ticker import MaxNLocator

    path_list = sorted([Path(p) for p in paths], key=_natural_key)
    if not path_list:
        raise ValueError("make_tile_figure: at least one file required")
    datasets = [read_iqxqy(p) for p in path_list]
    n = len(datasets)
    if n == 1:
        return make_iqxqy_figure(
            datasets[0].path, cmap=cmap, log_intensity=log_intensity, title=title
        )

    ncols = TILE_NCOLS
    nrows = math.ceil(n / ncols)

    # constrained_layout auto-sizes the inter-tile gaps, the cbar gutter,
    # and the outer margins to fit every tick label without clipping —
    # better than the manual subplots_adjust we used to drive.
    fig_w = 2.6 * ncols
    fig_h = 2.6 * nrows
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(fig_w, fig_h),
        squeeze=False,
        layout="constrained",
    )
    axes_flat = axes.ravel()

    shared_norm: LogNorm | None = None
    shared_vmin: float | None = None
    shared_vmax: float | None = None
    if colorbar_mode == "shared":
        shared_vmin, shared_vmax = _shared_positive_range(datasets)
        if log_intensity and shared_vmin is not None and shared_vmax is not None:
            shared_norm = LogNorm(vmin=shared_vmin, vmax=shared_vmax)

    cm = _cmap_with_bad(cmap)
    mappable_for_cbar = None

    for i in range(nrows * ncols):
        ax = axes_flat[i]
        if i >= n:
            ax.axis("off")
            continue
        ds = datasets[i]
        intensity, per_norm = _intensity_and_norm(
            ds.intensity, log_intensity=log_intensity, shared_norm=shared_norm
        )
        x_edges, y_edges = _grid_edges(ds.qx, ds.qy)
        if shared_norm is not None:
            pcm = ax.pcolormesh(
                x_edges, y_edges, intensity, cmap=cm, norm=shared_norm, shading="flat"
            )
        else:
            pcm = ax.pcolormesh(
                x_edges,
                y_edges,
                intensity,
                cmap=cm,
                norm=per_norm,
                vmin=None if log_intensity else shared_vmin,
                vmax=None if log_intensity else shared_vmax,
                shading="flat",
            )
        ax.set_aspect("equal", adjustable="box")
        ax.set_box_aspect(1)
        # Show qx / qy ticks + tick values on *every* tile — the user
        # cares about the q range each panel covers. Keep the values
        # tiny (labelsize=7, MaxNLocator(3)) so they don't crowd.
        ax.xaxis.set_major_locator(MaxNLocator(3))
        ax.yaxis.set_major_locator(MaxNLocator(3))
        ax.tick_params(which="both", length=2, labelsize=7)
        # Filename overlay in the panel — keeps the tiles compact.
        ax.text(
            0.5,
            0.98,
            ds.path.name,
            ha="center",
            va="top",
            fontsize=7,
            color="white",
            weight="bold",
            transform=ax.transAxes,
            bbox={"facecolor": "black", "alpha": 0.5, "pad": 1, "edgecolor": "none"},
        )
        if colorbar_mode == "independent":
            fig.colorbar(pcm, ax=ax)
        elif mappable_for_cbar is None:
            mappable_for_cbar = pcm

    # Bottom-left tile carries the axis-name labels (Qx, Qy) — keeping
    # them on every panel would crowd the layout. Tick *values* stay on
    # every tile (set in the loop above).
    if n > 0:
        bl = axes[nrows - 1, 0]
        bl.set_xlabel(r"$Q_x$ (Å$^{-1}$)")
        bl.set_ylabel(r"$Q_y$ (Å$^{-1}$)")

    if colorbar_mode == "shared" and mappable_for_cbar is not None:
        # ``ax=axes_flat.tolist()`` makes matplotlib steal a slice from the
        # right of the data axes' bounding box for the colorbar — the bar
        # ends up the same height as a tile (not the whole figure), and
        # tick labels stay inside ``bbox_inches="tight"``.
        cb = fig.colorbar(
            mappable_for_cbar,
            ax=axes_flat.tolist(),
            orientation="vertical",
            shrink=0.95,
            pad=0.02,
        )
        cb.set_label(r"$I(q_x, q_y)$")
    if title:
        fig.suptitle(title)
    return fig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _intensity_and_norm(
    arr: np.ndarray,
    *,
    log_intensity: bool,
    shared_norm: object | None = None,
) -> tuple[np.ndarray, object | None]:
    """Mask non-positives for log scaling; return (array, norm)."""
    from matplotlib.colors import LogNorm

    if not log_intensity:
        return arr, None
    masked = np.where(arr > 0, arr, np.nan)
    if shared_norm is not None:
        return masked, None  # caller passes shared_norm directly
    finite = masked[np.isfinite(masked)]
    if finite.size == 0:
        return masked, None
    vmin = float(finite.min())
    vmax = float(finite.max())
    if vmax <= vmin:
        vmax = vmin * 1.01
    return masked, LogNorm(vmin=vmin, vmax=vmax)


def _shared_positive_range(datasets: list[Iq2D]) -> tuple[float | None, float | None]:
    """Strict-positive vmin/vmax across every dataset, for the shared LogNorm."""
    mins: list[float] = []
    maxs: list[float] = []
    for d in datasets:
        positive = d.intensity[(d.intensity > 0) & np.isfinite(d.intensity)]
        if positive.size:
            mins.append(float(positive.min()))
            maxs.append(float(positive.max()))
    if not mins:
        return None, None
    vmin = min(mins)
    vmax = max(maxs)
    if vmax <= vmin:
        vmax = vmin * 1.01
    return vmin, vmax


def _grid_edges(qx_centers: np.ndarray, qy_centers: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """qx/qy in the file are bin centres; pcolormesh wants edges."""
    return _centers_to_edges(qx_centers), _centers_to_edges(qy_centers)


def _centers_to_edges(c: np.ndarray) -> np.ndarray:
    if c.size == 1:
        w = 0.5 * (abs(c[0]) if c[0] != 0 else 1e-3)
        return np.array([c[0] - w, c[0] + w])
    dc = np.diff(c)
    edges = np.empty(c.size + 1, dtype=float)
    edges[1:-1] = c[:-1] + dc / 2
    edges[0] = c[0] - dc[0] / 2
    edges[-1] = c[-1] + dc[-1] / 2
    return edges


def _hide_ticks(ax) -> None:  # type: ignore[no-untyped-def]
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def _natural_key(path: Path) -> list:  # type: ignore[type-arg]
    """Number-aware sort key on the file basename — ``run2`` < ``run10``."""
    name = path.name
    parts = re.findall(r"\d+|\D+", name)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def _cmap_with_bad(name: str):  # type: ignore[no-untyped-def]
    """Copy the named colormap and set "bad" (NaN) cells to a soft grey."""
    import matplotlib as mpl

    cm = mpl.colormaps[name].copy()
    cm.set_bad("#bdbdbd")
    return cm
