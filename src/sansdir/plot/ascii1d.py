"""1D ASCII plotting — I(q), transmission.

Reads 2/3/4-column whitespace-delimited ASCII (``#`` comments respected),
overlays multiple files in one figure with a legend, and routes through
:mod:`sansdir.plot.backend` for display/save. Defaults follow SANS
convention: log-log for I(q), linear for transmission.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from sansdir.plot.backend import BackendInfo, show_or_save


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

    The 4th column (sigma_q) is read but discarded — see PLANNING.md §4.1.
    """
    data = np.loadtxt(path, comments="#", ndmin=2)
    if data.shape[1] < 2:
        raise ValueError(f"{path}: need at least 2 columns, got {data.shape[1]}")
    q = data[:, 0]
    intensity = data[:, 1]
    sigma_i = data[:, 2] if data.shape[1] >= 3 else None
    return Iq1D(path=Path(path), q=q, intensity=intensity, sigma_i=sigma_i)


def read_transmission(path: Path) -> Iq1D:
    """Same shape as :func:`read_iq` but the columns mean λ, T, sigma_T."""
    return read_iq(path)


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------


def plot_iq(
    paths: Iterable[Path],
    *,
    xscale: str = "log",
    yscale: str = "log",
    errorbars: bool = True,
    title: str | None = None,
) -> tuple[Path | None, BackendInfo]:
    """Plot one or more I(q) curves, overlaid. Returns ``(png_or_none, info)``."""
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
    return show_or_save(fig, title=_safe_title(datasets, "iq"))


def plot_transmission(
    paths: Iterable[Path],
    *,
    xscale: str = "linear",
    yscale: str = "linear",
    errorbars: bool = True,
    title: str | None = None,
) -> tuple[Path | None, BackendInfo]:
    """Plot one or more transmission curves: ``T(λ)`` vs ``λ``."""
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
    return show_or_save(fig, title=_safe_title(datasets, "trans"))


# ---------------------------------------------------------------------------
# Title helpers
# ---------------------------------------------------------------------------


def _auto_title(datasets: list[Iq1D], *, prefix: str = "") -> str:
    title = datasets[0].path.name if len(datasets) == 1 else f"{len(datasets)} curves"
    return f"{prefix}: {title}" if prefix else title


def _safe_title(datasets: list[Iq1D], default: str) -> str:
    if len(datasets) == 1:
        return datasets[0].path.stem
    return f"{default}_{len(datasets)}files"
