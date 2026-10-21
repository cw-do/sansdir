"""Colour-scale maths for the viewer (Qt-free).

Limits are always expressed in **counts**, in both linear and log mode;
only the values handed to the image item change. In log mode a pixel
with zero counts becomes NaN, which pyqtgraph draws as background, and
the colour bar's axis is labelled in counts (1, 10, 100, …) by
:func:`log_ticks`.

:class:`ScaleState` holds what the side panel edits (log/lin, Min/Max,
Lock, Auto percentiles, colour map) and the rules tying them together,
so the Qt panel only has to display it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

DEFAULT_PERCENTILES: tuple[float, float] = (1.0, 99.5)
DEFAULT_CMAP: str = "viridis"
COLORMAPS: tuple[str, ...] = (
    "viridis",
    "inferno",
    "magma",
    "plasma",
    "cividis",
    "turbo",
    "jet",
    "gray",
)
LOG_FLOOR: float = 1e-3  # smallest count limit in log mode
_MINOR_STEPS = (2, 3, 4, 5, 6, 7, 8, 9)
_SUFFIXES = ((1e9, "G"), (1e6, "M"), (1e3, "k"))

Tick = tuple[float, str]


def display_values(image: np.ndarray, *, log: bool) -> np.ndarray:
    """Counts → float32 values for the image item (``log10`` in log mode)."""
    out = np.asarray(image, dtype=np.float32)
    if not log:
        return out
    shown = np.full(out.shape, np.nan, dtype=np.float32)
    positive = out > 0
    np.log10(out, out=shown, where=positive)
    return shown


def display_levels(vmin: float, vmax: float, *, log: bool) -> tuple[float, float]:
    """Count limits → image-item levels."""
    if not log:
        return float(vmin), float(vmax)
    lo = max(float(vmin), LOG_FLOOR)
    hi = max(float(vmax), lo * 10)
    return float(np.log10(lo)), float(np.log10(hi))


def counts_from_levels(lo: float, hi: float, *, log: bool) -> tuple[float, float]:
    """Image-item levels → count limits (inverse of :func:`display_levels`)."""
    if not log:
        return float(lo), float(hi)
    return float(10.0**lo), float(10.0**hi)


def auto_limits(
    image: np.ndarray,
    *,
    percentiles: tuple[float, float] = DEFAULT_PERCENTILES,
    mask: np.ndarray | None = None,
    log: bool = True,
) -> tuple[float, float]:
    """Count limits from percentiles of the non-zero, unmasked pixels.

    Zero-count pixels are left out because a detector image is mostly
    empty at short TOF; including them would pin the lower limit at 0.
    """
    data = _kept(image, mask)
    if data.size == 0:
        return (1.0, 10.0) if log else (0.0, 1.0)
    lo, hi = np.percentile(data, percentiles)
    if not log:
        lo = 0.0 if lo <= data.min() else lo
    if hi <= lo:
        hi = lo + 1.0
    return float(lo), float(hi)


def full_limits(
    image: np.ndarray, *, mask: np.ndarray | None = None, log: bool = True
) -> tuple[float, float]:
    """The whole data range: smallest non-zero count (0 in linear mode) → largest."""
    data = _kept(image, mask)
    if data.size == 0:
        return (1.0, 10.0) if log else (0.0, 1.0)
    lo = float(data.min()) if log else 0.0
    hi = float(data.max())
    if hi <= lo:
        hi = lo + 1.0
    return lo, hi


def _kept(image: np.ndarray, mask: np.ndarray | None) -> np.ndarray:
    values = np.asarray(image, dtype=np.float64)
    keep = values > 0
    if mask is not None:
        keep &= ~mask.astype(bool)
    return values[keep]


def count_label(value: float) -> str:
    """Short tick label for a count: ``0.1``, ``1``, ``50``, ``2k``, ``1M``."""
    for size, suffix in _SUFFIXES:
        if value >= size:
            return f"{value / size:.3g}{suffix}"
    return f"{value:.3g}"


def log_ticks(lo: float, hi: float) -> tuple[list[Tick], list[Tick]]:
    """Colour-bar ticks for log10 display values ``lo … hi``, labelled in counts.

    Returns ``(major, minor)`` in the form pyqtgraph's ``AxisItem.setTicks``
    takes. Majors are the decades; when the range spans less than about two
    decades, 2x and 5x are labelled too so the bar is never bare. The
    unlabelled minors fill in 2-9 x each decade.
    """
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return [], []
    lo, hi = min(lo, hi), max(lo, hi)
    first, last = math.floor(lo), math.ceil(hi)
    dense = hi - lo < 2.0
    major: list[Tick] = []
    minor: list[Tick] = []
    for decade in range(first, last + 1):
        base = 10.0**decade
        major.append((float(decade), count_label(base)))
        for step in _MINOR_STEPS:
            pos = math.log10(step * base)
            if pos > last:
                break
            if dense and step in (2, 5):
                major.append((pos, count_label(step * base)))
            else:
                minor.append((pos, ""))
    return major, minor


@dataclass
class ScaleState:
    """What the colour-scale panel edits. Limits are counts in both modes.

    With ``locked`` off, :meth:`limits_for` re-derives the limits from
    each new image (percentiles); with it on they stay put so TOF slices
    can be compared.
    """

    log: bool = True
    vmin: float = 1.0
    vmax: float = 10.0
    locked: bool = False
    percentiles: tuple[float, float] = DEFAULT_PERCENTILES
    cmap: str = DEFAULT_CMAP

    def limits_for(self, image: np.ndarray, mask: np.ndarray | None = None) -> tuple[float, float]:
        """Limits for a newly shown image: auto unless locked."""
        if not self.locked:
            self.auto(image, mask)
        return self.vmin, self.vmax

    def auto(self, image: np.ndarray, mask: np.ndarray | None = None) -> None:
        """Set the limits from the percentiles of ``image`` (the Auto button)."""
        self.vmin, self.vmax = auto_limits(
            image, percentiles=self.percentiles, mask=mask, log=self.log
        )

    def reset(self, image: np.ndarray, mask: np.ndarray | None = None) -> None:
        """Set the limits to the full data range (the Reset button)."""
        self.vmin, self.vmax = full_limits(image, mask=mask, log=self.log)

    def set_limits(self, vmin: float, vmax: float) -> None:
        """Typed or dragged limits, made valid for the current mode."""
        vmin, vmax = float(vmin), float(vmax)
        vmin = max(vmin, LOG_FLOOR if self.log else 0.0)
        if vmax <= vmin:
            vmax = vmin * 10 if self.log else vmin + 1.0
        self.vmin, self.vmax = vmin, vmax

    def set_log(self, log: bool, image: np.ndarray | None = None) -> None:
        """Switch log/lin; a locked Min of 0 cannot be shown in log, so re-derive it."""
        self.log = log
        if log and self.vmin <= 0:
            lo = auto_limits(image, percentiles=self.percentiles)[0] if image is not None else 1.0
            self.set_limits(min(lo, self.vmax / 10), self.vmax)

    def set_percentiles(self, lo: float, hi: float) -> None:
        lo, hi = sorted((float(lo), float(hi)))
        self.percentiles = (max(lo, 0.0), min(hi, 100.0))


__all__ = [
    "COLORMAPS",
    "DEFAULT_CMAP",
    "DEFAULT_PERCENTILES",
    "LOG_FLOOR",
    "ScaleState",
    "auto_limits",
    "count_label",
    "counts_from_levels",
    "display_levels",
    "display_values",
    "full_limits",
    "log_ticks",
]
