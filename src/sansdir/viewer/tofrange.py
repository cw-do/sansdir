"""TOF selection maths for the viewer (Qt-free).

A selection is a half-open range of fine TOF bins ``[a, b)`` into a
:class:`~sansdir.viewer.cube.TofCube`; ``tof_edges`` (µs, length
``nbins + 1``) maps bins to time. The TOF panel works in milliseconds,
snaps a dragged region to bin edges with :func:`snap`, and steps a
fixed-width window through the run with :func:`step` (wrapping at the end,
which is what *play* does).
"""

from __future__ import annotations

import numpy as np

DEFAULT_WIDTH_FRACTION: int = 25  # a new window is nbins // 25 bins wide (20 of 500)


def default_width(nbins: int) -> int:
    """Width, in bins, of the window shown when leaving the full range."""
    return max(1, nbins // DEFAULT_WIDTH_FRACTION)


def clamp(a: int, b: int, nbins: int) -> tuple[int, int]:
    """Keep ``[a, b)`` inside ``[0, nbins]`` and at least one bin wide."""
    nbins = max(nbins, 1)
    width = min(max(b - a, 1), nbins)
    a = min(max(a, 0), nbins - width)
    return a, a + width


def snap(edges: np.ndarray, t0: float, t1: float) -> tuple[int, int]:
    """TOF interval (same unit as ``edges``) → nearest bin edges ``[a, b)``.

    Always at least one bin wide, so a region collapsed by a drag still
    shows something.
    """
    nbins = len(edges) - 1
    lo, hi = sorted((float(t0), float(t1)))
    a = _nearest(edges, lo)
    b = _nearest(edges, hi)
    if b <= a:
        b = a + 1
    return clamp(a, b, nbins)


def _nearest(edges: np.ndarray, t: float) -> int:
    i = int(np.searchsorted(edges, t))
    if i <= 0:
        return 0
    if i >= len(edges):
        return len(edges) - 1
    return i if edges[i] - t < t - edges[i - 1] else i - 1


def step(a: int, b: int, nbins: int, n: int = 1, *, wrap: bool = True) -> tuple[int, int]:
    """Move the window ``n`` widths later (earlier if negative).

    With ``wrap``, stepping past either end jumps to the other end, so
    *play* loops through the run; without it the window stops at the end.
    """
    width = max(b - a, 1)
    last = max(nbins - width, 0)
    start = a + n * width
    if wrap:
        if start > last:
            start = 0 if a >= last else last
        elif start < 0:
            start = last if a <= 0 else 0
    return clamp(start, start + width, nbins)


def describe(edges: np.ndarray | None, a: int, b: int) -> str:
    """``"TOF 4.21-4.98 ms · bins 57-66 of 500"`` (bins 0-based, inclusive)."""
    if edges is None:
        return "no TOF (processed file)"
    nbins = len(edges) - 1
    if a <= 0 and b >= nbins:
        return f"all TOF {edges[0] / 1e3:.2f}-{edges[-1] / 1e3:.2f} ms · {nbins} bins"
    span = f"bin {a}" if b - a == 1 else f"bins {a}-{b - 1}"
    return f"TOF {edges[a] / 1e3:.3f}-{edges[b] / 1e3:.3f} ms · {span} of {nbins}"


__all__ = ["clamp", "default_width", "describe", "snap", "step"]
