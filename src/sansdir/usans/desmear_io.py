"""Read reduced I(Q) curves and write desmeared ones.

Kept apart from :mod:`sansdir.usans.desmear` so the physics stays free of
file-format concerns. Reading reuses :func:`sansdir.plot.ascii1d.read_iq`,
which already copes with everything the reduction engines emit — comma or
whitespace delimiters, a trailing delimiter, ``#`` comments, stray header
rows — so a desmeared curve and a plotted curve can never disagree about how
a file was parsed.

The written file is plain ``Q, I, dI`` with a ``#`` header, matching the
3-column convention of every other reduced curve, so ``p`` plots it with no
special case.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np

from sansdir.usans.desmear import DesmearResult

# Appended to the input stem. ``UN_S0_det_1_bsub.txt`` -> ``..._bsub_desmeared.txt``.
DESMEARED_SUFFIX: str = "_desmeared.txt"


def desmeared_path(source: str | Path, out_dir: str | Path | None = None) -> Path:
    """Where the desmeared curve for ``source`` should be written.

    Args:
        source: The input reduced curve.
        out_dir: Directory for the output; defaults to the input's own.
    """
    src = Path(source)
    stem = src.name[: -len(src.suffix)] if src.suffix else src.name
    base = Path(out_dir) if out_dir is not None else src.parent
    return base / f"{stem}{DESMEARED_SUFFIX}"


def read_curve(path: str | Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load ``(q, I, dI)`` from a reduced 2/3/4-column I(Q) file.

    Delegates to the 1-D plotter's reader so parsing is shared. A 2-column
    file gets a 5% nominal uncertainty, which is only used to weight the
    smoother — desmearing a curve with no errors is possible but the reported
    uncertainties are then nominal too.

    Raises:
        ValueError: When the file has no numeric rows or fewer than 2 columns.
    """
    from sansdir.plot.ascii1d import read_iq

    data = read_iq(Path(path))
    q = np.asarray(data.q, dtype=float)
    i = np.asarray(data.intensity, dtype=float)
    if data.sigma_i is not None and np.size(data.sigma_i) == q.size:
        di = np.asarray(data.sigma_i, dtype=float)
    else:
        di = 0.05 * np.abs(i)
    return q, i, di


def format_header(result: DesmearResult, source: Path, sans_source: Path | None) -> str:
    """The ``#`` block written above the desmeared curve.

    Records everything needed to reproduce or distrust the result: which
    inversion, the slit width, the smoother bandwidth, the mode, and — in
    ``usans-only`` mode — an explicit warning that the high-Q side was
    assumed rather than measured.
    """
    lines = [
        f"desmeared I(Q) from {source.name}",
        "method: truncated Abel inversion, Huang et al., J. Appl. Cryst. 59, 1083 (2026), eq. 15",
        f"generated: {date.today().isoformat()} by sansdir",
        f"sigma_y: {result.sigma_y:g} A^-1   (slit half-width)",
        f"smoother bandwidth h: {result.bandwidth:.4g} in ln Q   reduced chi^2: {result.chi2:.3g}",
        f"mode: {result.mode}",
    ]
    if result.mode == "with-sans" and sans_source is not None:
        lines.append(f"SANS companion: {sans_source.name}")
        lines.append(f"USANS scaled onto the smeared SANS by k = {result.sans_scale:.5g}")
        if np.isfinite(result.join_rms):
            lines.append(f"join scatter about one power law: {result.join_rms:.3f} dex")
    else:
        lines.append("")
        lines.append("WARNING - no SANS data was supplied.")
        lines.append(
            f"  Equation 15 needs I(Q) out to Q_m ~ sigma_y = {result.sigma_y:g} A^-1, two"
        )
        lines.append("  decades above this measurement. That side was extrapolated as a")
        lines.append(f"  power law Q^{result.tail_slope:.2f} fitted to the top of the USANS data.")
        lines.append("  Huang et al. (2026) Fig. 2 shows reconstructions without measured")
        lines.append("  high-Q data track the truth at low Q, then deviate and collapse.")
        lines.append("  This file is therefore TRUNCATED to the measured USANS range;")
        lines.append("  treat it as valid there and nowhere else.")
        lines.append("")
    lines.append(f"intensity gain at the lowest Q: x{result.gain_at_low_q:.3g}")
    for w in result.warnings:
        lines.append(f"note: {w}")
    lines.append("")
    lines.append("Q(1/A)  I(1/cm)  dI(1/cm)")
    return "\n".join(lines)


def write_curve(
    result: DesmearResult,
    path: str | Path,
    *,
    source: str | Path,
    sans_source: str | Path | None = None,
) -> Path:
    """Write ``result`` as a 3-column ``Q I dI`` file with a ``#`` header.

    Whitespace-delimited and 3 columns, so ``p`` (and any other 2/3/4-column
    reader) treats it exactly like every other reduced curve.

    Returns:
        The path written.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = format_header(result, Path(source), Path(sans_source) if sans_source else None)
    np.savetxt(
        path,
        np.column_stack([result.q, result.intensity, result.sigma]),
        header=header,
        fmt="%.6e",
    )
    return path


def looks_like_iq(path: str | Path) -> bool:
    """Cheap check that ``path`` is a plottable 1-D I(Q) text file.

    Used to filter a selection before offering to desmear it, so a stray
    ``.csv`` setup table or a NeXus file produces a clear message instead of
    a parser traceback.
    """
    p = Path(path)
    if not p.is_file() or p.suffix.lower() not in (".txt", ".dat", ".iq"):
        return False
    try:
        q, i, _ = read_curve(p)
    except (ValueError, OSError):
        return False
    return bool(q.size >= 8 and np.isfinite(q).any() and np.isfinite(i).any())
