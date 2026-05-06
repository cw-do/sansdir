"""2D ASCII reader for ``Iqxqy`` files.

Reads 4-column ``qx qy I sigI`` or 6-column ``qx qy I sigI dqx dqy``
ASCII (whitespace or comma — same tolerant parser the 1D path uses)
and reshapes the flat row data into a regular ``(ny, nx)`` grid via
sorted unique qx/qy values.

Cells the file doesn't supply data for stay ``np.nan`` — real SANS
Iqxqy files routinely mask out the beam-stop region and dead detector
pixels, and matplotlib's ``pcolormesh`` renders NaN cells as the
colormap's "bad" colour (we set this to a soft grey in
:mod:`sansdir.plot.tile`).

:class:`GridError` is reserved for the cases where we *can't* yield a
2D grid at all — empty file, unsupported column count.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np


class GridError(ValueError):
    """Raised when 2D data doesn't reshape onto a regular qx/qy grid."""


@dataclass(frozen=True, slots=True)
class Iq2D:
    """One 2D reduced dataset, already reshaped onto a regular grid."""

    path: Path
    qx: np.ndarray  # 1D, length nx
    qy: np.ndarray  # 1D, length ny
    intensity: np.ndarray  # 2D, shape (ny, nx)
    sigma_i: np.ndarray | None  # same shape as intensity, or None

    @property
    def shape(self) -> tuple[int, int]:
        return self.intensity.shape


def read_iqxqy(path: Path) -> Iq2D:
    """Load 4/6-col ``qx qy I [sigI [dqx dqy]]`` from ``path``.

    Builds the (ny, nx) grid from sorted unique qx/qy. Any cell the
    file doesn't supply (masked beam stop, dead pixels) stays
    ``np.nan``. The optional dqx / dqy columns (5-6) are read but
    discarded.

    Raises :class:`GridError` only for empty input or an unsupported
    column count — gaps in the grid are *not* an error.
    """
    rows = _read_numeric_rows(path)
    if not rows:
        raise GridError(f"{path}: no numeric data found")
    target_cols = Counter(len(r) for r in rows).most_common(1)[0][0]
    rows = [r for r in rows if len(r) == target_cols]
    if target_cols not in (4, 6):
        raise GridError(
            f"{path}: expected 4 or 6 columns of qx,qy,I[,sigI[,dqx,dqy]]; got {target_cols}"
        )
    data = np.asarray(rows, dtype=float)
    qx_flat = data[:, 0]
    qy_flat = data[:, 1]
    i_flat = data[:, 2]
    sig_flat = data[:, 3] if target_cols >= 4 else None

    qx = np.unique(qx_flat)
    qy = np.unique(qy_flat)
    nx = qx.size
    ny = qy.size

    # ``searchsorted`` is exact because qx/qy come from ``np.unique``
    # (sorted, no duplicates) — every flat (qx, qy) maps to a unique
    # cell. Cells without input data stay NaN; pcolormesh renders them
    # with the colormap's "bad" colour (soft grey, see plot.tile).
    ix = np.searchsorted(qx, qx_flat)
    iy = np.searchsorted(qy, qy_flat)
    grid = np.full((ny, nx), np.nan, dtype=float)
    grid[iy, ix] = i_flat
    sig_grid: np.ndarray | None = None
    if sig_flat is not None:
        sig_grid = np.full((ny, nx), np.nan, dtype=float)
        sig_grid[iy, ix] = sig_flat
    return Iq2D(path=Path(path), qx=qx, qy=qy, intensity=grid, sigma_i=sig_grid)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_numeric_rows(path: Path) -> list[list[float]]:
    """Same tolerant parser the 1D side uses — comments out, mixed delimiters,
    silently drop rows whose tokens won't parse as float."""
    out: list[list[float]] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = (
                [s.strip() for s in line.split(",") if s.strip()] if "," in line else line.split()
            )
            try:
                values = [float(p) for p in parts]
            except ValueError:
                continue
            if values:
                out.append(values)
    return out
