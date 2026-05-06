"""1D ASCII plotting — I(q), transmission.

Reads 2/3/4-column whitespace-delimited ASCII (``#`` comments respected)
and overlays multiple files in one figure with a legend. Defaults follow
SANS convention: log-log for I(q), linear for transmission.

Display strategy
----------------

The :func:`plot_iq` and :func:`plot_transmission` entry points pick one
of two paths:

* **Interactive** (``$DISPLAY`` available) — spawn a separate
  ``python -m sansdir.plot.window …`` subprocess. The subprocess owns
  its own matplotlib event loop, so the figure window is fully
  responsive and the TUI never has to share a thread with Qt/Tk. The
  TUI process never imports matplotlib in this case.

* **Headless** (no display, or ``$SANSDIR_HEADLESS=1``) — build the
  figure inline and save a PNG to ``~/.cache/sansdir/plots/``.

The figure-builder helpers (:func:`make_iq_figure`,
:func:`make_transmission_figure`) are public so the subprocess and the
headless path call the *same* drawing code.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from sansdir.plot.backend import (
    BackendInfo,
    has_display,
    save_figure_to_png,
    spawn_plot_window,
)

if TYPE_CHECKING:
    from matplotlib.figure import Figure


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Iq1D:
    """One reduced I(q) dataset."""

    path: Path
    q: np.ndarray
    intensity: np.ndarray
    sigma_i: np.ndarray | None  # None when the file has only 2 columns

    @property
    def has_errors(self) -> bool:
        return self.sigma_i is not None and self.sigma_i.size > 0


def read_iq(path: Path) -> Iq1D:
    """Load 2/3/4-col ``q I(q) [sigma_I] [sigma_q]`` from ``path``.

    Auto-detects the delimiter (comma for CSV, whitespace otherwise) by
    sniffing the first non-comment line. The 4th column (sigma_q) is
    read but discarded — see PLANNING.md §4.1.
    """
    delim = _detect_delimiter(path)
    data = np.loadtxt(path, comments="#", ndmin=2, delimiter=delim)
    if data.shape[1] < 2:
        raise ValueError(f"{path}: need at least 2 columns, got {data.shape[1]}")
    q = data[:, 0]
    intensity = data[:, 1]
    sigma_i = data[:, 2] if data.shape[1] >= 3 else None
    return Iq1D(path=Path(path), q=q, intensity=intensity, sigma_i=sigma_i)


def _detect_delimiter(path: Path) -> str | None:
    """Sniff the column separator. ``","`` for CSV, ``None`` (=whitespace) else.

    Returns ``None`` when the file is empty or unreadable so :func:`np.loadtxt`
    falls back to its default behavior (any whitespace).
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                # Comma wins if present — CSV-with-spaces is much more
                # common than tab-with-stray-comma.
                return "," if "," in line else None
    except OSError:
        return None
    return None


def read_transmission(path: Path) -> Iq1D:
    """Same shape as :func:`read_iq` but the columns mean λ, T, sigma_T."""
    return read_iq(path)


# ---------------------------------------------------------------------------
# Figure builders (used by the subprocess and by the headless save path)
# ---------------------------------------------------------------------------


def make_iq_figure(
    paths: Iterable[Path],
    *,
    xscale: str = "log",
    yscale: str = "log",
    errorbars: bool = True,
    title: str | None = None,
) -> Figure:
    """Build an I(q) overlay Figure. Caller decides what to do with it."""
    import matplotlib.pyplot as plt

    datasets = [read_iq(Path(p)) for p in paths]
    if not datasets:
        raise ValueError("plot_iq: at least one file required")

    fig, ax = plt.subplots(figsize=(7, 5))
    for ds in datasets:
        label = ds.path.name
        if errorbars and ds.has_errors:
            ax.errorbar(
                ds.q,
                ds.intensity,
                yerr=ds.sigma_i,
                fmt="o-",
                markersize=3,
                linewidth=1,
                capsize=0,
                label=label,
            )
        else:
            ax.plot(ds.q, ds.intensity, "o-", markersize=3, linewidth=1, label=label)
    ax.set_xscale(xscale)
    ax.set_yscale(yscale)
    ax.set_xlabel(r"$q$ (Å$^{-1}$)")
    ax.set_ylabel(r"$I(q)$ (cm$^{-1}$)")
    ax.set_title(title or _auto_title(datasets))
    ax.grid(True, which="both", alpha=0.3)
    if len(datasets) > 1:
        ax.legend(fontsize="small", loc="best")
    fig.tight_layout()
    return fig


def make_transmission_figure(
    paths: Iterable[Path],
    *,
    xscale: str = "linear",
    yscale: str = "linear",
    errorbars: bool = True,
    title: str | None = None,
) -> Figure:
    """Build a transmission overlay Figure: T(λ) vs λ."""
    import matplotlib.pyplot as plt

    datasets = [read_transmission(Path(p)) for p in paths]
    if not datasets:
        raise ValueError("plot_transmission: at least one file required")

    fig, ax = plt.subplots(figsize=(7, 5))
    for ds in datasets:
        label = ds.path.name
        if errorbars and ds.has_errors:
            ax.errorbar(
                ds.q,
                ds.intensity,
                yerr=ds.sigma_i,
                fmt="o-",
                markersize=3,
                linewidth=1,
                capsize=0,
                label=label,
            )
        else:
            ax.plot(ds.q, ds.intensity, "o-", markersize=3, linewidth=1, label=label)
    ax.set_xscale(xscale)
    ax.set_yscale(yscale)
    ax.set_xlabel(r"$\lambda$ (Å)")
    ax.set_ylabel(r"$T(\lambda)$")
    ax.set_title(title or _auto_title(datasets, prefix="Transmission"))
    ax.grid(True, alpha=0.3)
    if len(datasets) > 1:
        ax.legend(fontsize="small", loc="best")
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# High-level entry points (used by the command registry)
# ---------------------------------------------------------------------------


def plot_iq(
    paths: Iterable[Path],
    *,
    xscale: str = "log",
    yscale: str = "log",
    errorbars: bool = True,
    title: str | None = None,
) -> tuple[Path | None, BackendInfo]:
    """Display or save an I(q) overlay. Returns ``(png_or_none, info)``."""
    path_list = [Path(p) for p in paths]
    if not path_list:
        raise ValueError("plot_iq: at least one file required")
    if has_display():
        info = spawn_plot_window(
            "iq",
            path_list,
            xscale=xscale,
            yscale=yscale,
            errorbars=errorbars,
            title=title,
        )
        return None, info
    fig = make_iq_figure(path_list, xscale=xscale, yscale=yscale, errorbars=errorbars, title=title)
    return save_figure_to_png(
        fig,
        title=_safe_title([read_iq(p) for p in path_list[:1]] or [], "iq", path_list),
    )


def plot_transmission(
    paths: Iterable[Path],
    *,
    xscale: str = "linear",
    yscale: str = "linear",
    errorbars: bool = True,
    title: str | None = None,
) -> tuple[Path | None, BackendInfo]:
    """Display or save a transmission overlay."""
    path_list = [Path(p) for p in paths]
    if not path_list:
        raise ValueError("plot_transmission: at least one file required")
    if has_display():
        info = spawn_plot_window(
            "transmission",
            path_list,
            xscale=xscale,
            yscale=yscale,
            errorbars=errorbars,
            title=title,
        )
        return None, info
    fig = make_transmission_figure(
        path_list, xscale=xscale, yscale=yscale, errorbars=errorbars, title=title
    )
    return save_figure_to_png(
        fig,
        title=_safe_title([], "trans", path_list),
    )


# ---------------------------------------------------------------------------
# Title helpers
# ---------------------------------------------------------------------------


def _auto_title(datasets: list[Iq1D], *, prefix: str = "") -> str:
    title = datasets[0].path.name if len(datasets) == 1 else f"{len(datasets)} curves"
    return f"{prefix}: {title}" if prefix else title


def _safe_title(datasets: list[Iq1D], default: str, paths: list[Path] | None = None) -> str:
    """Filename-safe title for the saved PNG."""
    if datasets:
        if len(datasets) == 1:
            return datasets[0].path.stem
        return f"{default}_{len(datasets)}files"
    if paths and len(paths) == 1:
        return paths[0].stem
    return f"{default}_{len(paths) if paths else 0}files"
