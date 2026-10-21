"""Colour-scale maths for the viewer (Qt-free).

Limits are always expressed in **counts**, in both linear and log mode;
only the values handed to the image item change. In log mode a pixel
with zero counts becomes NaN, which pyqtgraph draws as background.
"""

from __future__ import annotations

import numpy as np

DEFAULT_PERCENTILES: tuple[float, float] = (1.0, 99.5)


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
    lo = max(float(vmin), 1e-3)
    hi = max(float(vmax), lo * 10)
    return float(np.log10(lo)), float(np.log10(hi))


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
    values = np.asarray(image, dtype=np.float64)
    keep = values > 0
    if mask is not None:
        keep &= ~mask.astype(bool)
    data = values[keep]
    if data.size == 0:
        return (1.0, 10.0) if log else (0.0, 1.0)
    lo, hi = np.percentile(data, percentiles)
    if not log:
        lo = 0.0 if lo <= data.min() else lo
    if hi <= lo:
        hi = lo + 1.0
    return float(lo), float(hi)


__all__ = ["DEFAULT_PERCENTILES", "auto_limits", "display_levels", "display_values"]
