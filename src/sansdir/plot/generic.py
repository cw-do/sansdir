"""Generic linear-linear plot for tabular data files.

Used by the ``l`` keystroke. Reads any whitespace-, comma-, or tab-
separated file (the common output of :mod:`sansdir.hdf.batch`) and
plots the *first* column as ``x`` against every remaining column as a
separate ``y`` series. When the first non-comment line looks like a
header (i.e. its tokens don't all parse as floats) we use those
tokens as axis / legend labels — so the table you just extracted
with ``M`` plots itself meaningfully without you typing column
names.

Both axes default to **linear** scale; this is intentionally not
:func:`~sansdir.plot.ascii1d.plot_iq`, which is log-log and assumes
SANS reduced data. ``l`` is for "look at this table".
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
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


def _detect_delim(line: str) -> str | None:
    """Pick a delimiter from the first non-comment line.

    Returns ``,`` for CSV, ``\\t`` for TSV, ``None`` to mean
    "whitespace" (numpy's ``loadtxt`` default).
    """
    if "," in line:
        return ","
    if "\t" in line:
        return "\t"
    return None


def _is_numeric_row(tokens: Sequence[str]) -> bool:
    """True iff every token in ``tokens`` parses as a float."""
    if not tokens:
        return False
    for t in tokens:
        try:
            float(t)
        except ValueError:
            return False
    return True


def read_table_with_header(path: Path) -> tuple[list[str] | None, np.ndarray]:
    """Parse ``path`` into ``(header, data)``.

    ``header`` is the list of column names if the first non-comment
    line is non-numeric (e.g. ``filename,time,phase1``); ``None``
    otherwise. ``data`` is a 2-D ``(rows, cols)`` ``np.ndarray`` of
    floats — non-numeric cells (like a string ``filename`` column in
    a summary-mode export) become ``NaN`` and are skipped at plot time.

    Comment lines starting with ``#`` are ignored.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    raw_lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not raw_lines:
        raise ValueError(f"{path}: empty file (no non-comment lines)")
    delim = _detect_delim(raw_lines[0])

    def _split(line: str) -> list[str]:
        return [t.strip() for t in line.split(delim) if t.strip()] if delim else line.split()

    first_tokens = _split(raw_lines[0])
    if _is_numeric_row(first_tokens):
        header: list[str] | None = None
        data_lines = raw_lines
    else:
        header = first_tokens
        data_lines = raw_lines[1:]
    if not data_lines:
        raise ValueError(f"{path}: header but no data rows")
    # Build the matrix row-by-row; non-floats → NaN so a leading
    # ``filename`` column from a summary table doesn't crash the read.
    rows: list[list[float]] = []
    for line in data_lines:
        cells = _split(line)
        row: list[float] = []
        for c in cells:
            try:
                row.append(float(c))
            except ValueError:
                row.append(float("nan"))
        rows.append(row)
    # Pad ragged rows with NaN so np.array doesn't raise.
    width = max(len(r) for r in rows)
    for r in rows:
        if len(r) < width:
            r.extend([float("nan")] * (width - len(r)))
    return header, np.asarray(rows, dtype=float)


def _first_numeric_col(data: np.ndarray) -> int:
    """Index of the first column whose values are at least *partly* numeric.

    Skips columns that are entirely NaN — handy when the table starts
    with a string column (e.g. ``filename`` in a summary export).
    """
    for c in range(data.shape[1]):
        if not np.all(np.isnan(data[:, c])):
            return c
    raise ValueError("no numeric columns to plot")


def make_generic_figure(
    paths: Iterable[Path],
    *,
    title: str | None = None,
) -> Figure:
    """Linear-linear overlay of every numeric column in each file.

    Column 0 (or the first not-all-NaN column) is the ``x`` axis;
    every other numeric column becomes its own ``y`` series. With
    multiple files we prefix the legend label with the filename so
    overlays stay readable.
    """
    import matplotlib.pyplot as plt

    path_list = [Path(p) for p in paths]
    if not path_list:
        raise ValueError("make_generic_figure: at least one file required")
    fig, ax = plt.subplots(figsize=(8, 6), layout="constrained")
    seen_header: list[str] | None = None
    for path in path_list:
        try:
            header, data = read_table_with_header(path)
        except (OSError, ValueError) as exc:
            ax.text(
                0.5,
                0.5 - 0.05 * path_list.index(path),
                f"{path.name}: {exc}",
                transform=ax.transAxes,
                color="red",
                ha="center",
            )
            continue
        if data.size == 0 or data.shape[1] < 2:
            continue
        x_col = _first_numeric_col(data)
        x = data[:, x_col]
        for ci in range(x_col + 1, data.shape[1]):
            y = data[:, ci]
            if np.all(np.isnan(y)):
                continue
            base_label = (
                header[ci] if header and ci < len(header) else f"col{ci + 1}"
            )
            label = f"{path.stem}:{base_label}" if len(path_list) > 1 else base_label
            ax.plot(x, y, marker=".", linestyle="-", label=label)
        if seen_header is None and header is not None:
            seen_header = header
            x_name = header[x_col] if x_col < len(header) else "x"
            ax.set_xlabel(x_name)
            # Y axis label only makes sense when every series shares units;
            # we skip it on overlays since each series is named in the legend.
            if data.shape[1] - x_col == 2:
                y_name = header[x_col + 1] if (x_col + 1) < len(header) else "value"
                ax.set_ylabel(y_name)
    ax.set_xscale("linear")
    ax.set_yscale("linear")
    ax.grid(True, which="both", linestyle=":", alpha=0.4)
    ax.legend(loc="best", fontsize="small")
    if title:
        ax.set_title(title)
    elif len(path_list) == 1:
        ax.set_title(path_list[0].name)
    return fig


def plot_generic(
    paths: Iterable[Path],
    *,
    title: str | None = None,
) -> tuple[Path | None, BackendInfo]:
    """Display or save a linear-linear overlay. Returns ``(png_or_none, info)``."""
    path_list = [Path(p) for p in paths]
    if not path_list:
        raise ValueError("plot_generic: at least one file required")
    if has_display():
        info = spawn_plot_window("generic", path_list, title=title)
        return None, info
    fig = make_generic_figure(path_list, title=title)
    stem = path_list[0].stem if len(path_list) == 1 else "table"
    return save_figure_to_png(fig, title=f"{stem}_linear")
