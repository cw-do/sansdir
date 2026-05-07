"""Batch HDF5 metadata extraction.

Reads a fixed set of keys (e.g. ``DASlogs/temperature/value``) from many
NeXus files and produces a tabular file (TSV / CSV / aligned columns)
suitable for spreadsheets or pandas. Used by the ``M`` keystroke and
the ``sansdir extract`` CLI subcommand.

Three building blocks:

* :func:`extract_one` reads every key from a single file in one open.
* :func:`extract_many` farms ``extract_one`` out across a thread pool
  (h5py releases the GIL on read), preserves input order, optionally
  reports progress.
* :func:`write_table` serialises the rows to TSV / CSV / aligned
  columns. The convenience function :func:`extract_to_file` chains
  the two together for one-shot CLI / command use.

Optional ``with_stats=True`` adds ``<key>_stdev`` and ``<key>_n``
columns alongside the mean for every numeric time-series key.
"""

from __future__ import annotations

import csv
import io
import time
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np

from sansdir.hdf.metadata import ExtractedValue, extract_value
from sansdir.hdf.reader import HdfError, open_nexus

ProgressCallback = Callable[[int, int], None]
Format = Literal["tsv", "csv", "columns"]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Row:
    """One file's worth of extracted values, in input-key order.

    ``values[key]`` is :class:`~sansdir.hdf.metadata.ExtractedValue` for
    keys that resolved cleanly, or ``None`` when the key was missing
    or unreadable. ``error`` is set if the *file itself* failed to
    open — in that case ``values`` is empty.
    """

    path: Path
    values: dict[str, ExtractedValue | None] = field(default_factory=dict)
    error: str | None = None


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def extract_one(path: Path, keys: Sequence[str]) -> Row:
    """Open ``path`` once and pull every key in ``keys``.

    A missing or unreadable key becomes ``values[key] = None`` so the
    table stays rectangular. A file that won't open at all becomes
    ``Row(error=...)`` with an empty ``values`` dict.
    """
    path = Path(path)
    row = Row(path=path)
    try:
        with open_nexus(path) as fh:
            for key in keys:
                try:
                    row.values[key] = extract_value(fh, key)
                except (KeyError, ValueError, OSError):
                    # Any per-key failure → leave the cell blank, keep
                    # going. We deliberately don't log here; the user
                    # sees the blank cell and the count is reflected
                    # in the table footer.
                    row.values[key] = None
    except HdfError as exc:
        row.error = str(exc)
    return row


def extract_many(
    paths: Iterable[Path],
    keys: Sequence[str],
    *,
    max_workers: int = 8,
    progress_cb: ProgressCallback | None = None,
) -> list[Row]:
    """Run :func:`extract_one` in parallel; return rows in *input order*.

    h5py releases the GIL during reads, so a ThreadPoolExecutor scales
    well for I/O-bound NeXus traversal. We submit eagerly, collect via
    ``as_completed`` for live progress, then re-sort to match input
    order so the output table matches the user's selection.

    ``progress_cb(done, total)`` is invoked after every completed file
    (on the calling thread, via ``as_completed``) — no locking needed.
    """
    file_list = [Path(p) for p in paths]
    total = len(file_list)
    rows: list[Row | None] = [None] * total
    if total == 0:
        return []
    workers = max(1, min(max_workers, total))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_idx = {pool.submit(extract_one, p, keys): i for i, p in enumerate(file_list)}
        for done, fut in enumerate(as_completed(future_to_idx), start=1):
            idx = future_to_idx[fut]
            rows[idx] = fut.result()
            if progress_cb is not None:
                progress_cb(done, total)
    # Every slot was filled by one extract_one call; rows is fully populated.
    return [r for r in rows if r is not None]


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _short_key(key: str) -> str:
    """``/entry/DASlogs/temperature/value`` → ``temperature``.

    The DASlogs node name is what users actually want as a column
    header. For non-DASlogs keys (``entry/duration`` etc.) we just use
    the basename.
    """
    parts = [p for p in key.split("/") if p]
    if not parts:
        return key
    if "daslogs" in [p.lower() for p in parts]:
        # Strip the trailing ``/value`` if present, then return the
        # node name (the segment after ``DASlogs``).
        if parts[-1].lower() == "value" and len(parts) >= 2:
            return parts[-2]
        return parts[-1]
    return parts[-1]


def _header(keys: Sequence[str], *, with_stats: bool) -> list[str]:
    cols = ["filename"]
    for k in keys:
        short = _short_key(k)
        cols.append(short)
        if with_stats:
            cols.append(f"{short}_stdev")
            cols.append(f"{short}_n")
    return cols


def _format_value(v: ExtractedValue | None) -> str:
    if v is None or v.value is None:
        return ""
    val = v.value
    if isinstance(val, float):
        # Six significant digits — covers DASlogs precision without
        # eating screen real estate.
        return f"{val:.6g}"
    return str(val)


def _row_cells(row: Row, keys: Sequence[str], *, with_stats: bool) -> list[str]:
    cells: list[str] = [row.path.name]
    for key in keys:
        ev = row.values.get(key)
        cells.append(_format_value(ev))
        if with_stats:
            if ev is not None and ev.stdev is not None:
                cells.append(f"{ev.stdev:.6g}")
            else:
                cells.append("")
            cells.append(str(ev.n_points) if ev is not None else "")
    return cells


def write_table(
    rows: Sequence[Row],
    keys: Sequence[str],
    out_path: Path,
    fmt: Format = "tsv",
    *,
    with_stats: bool = False,
) -> Path:
    """Serialise ``rows`` to ``out_path`` in ``fmt``.

    Returns the resolved ``out_path`` so callers can echo it. Skips
    rows whose file failed to open entirely (their ``error`` is set);
    a per-key miss still produces a row with blanks where the key
    wasn't found.
    """
    header = _header(keys, with_stats=with_stats)
    body = [_row_cells(r, keys, with_stats=with_stats) for r in rows if r.error is None]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        text = _to_delimited(header, body, delim=",")
    elif fmt == "tsv":
        text = _to_delimited(header, body, delim="\t")
    elif fmt == "columns":
        text = _to_columns(header, body)
    else:
        raise ValueError(f"unknown fmt: {fmt!r}")
    out_path.write_text(text, encoding="utf-8")
    return out_path


def _to_delimited(header: list[str], rows: list[list[str]], *, delim: str) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delim, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue()


def _to_columns(header: list[str], rows: list[list[str]]) -> str:
    """Right-padded fixed-width columns. One whitespace separator."""
    widths = [len(h) for h in header]
    for r in rows:
        for i, cell in enumerate(r):
            if len(cell) > widths[i]:
                widths[i] = len(cell)
    lines = [_pad_row(header, widths)]
    lines.extend(_pad_row(r, widths) for r in rows)
    return "\n".join(lines) + "\n"


def _pad_row(cells: list[str], widths: list[int]) -> str:
    return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))


# ---------------------------------------------------------------------------
# One-shot helper
# ---------------------------------------------------------------------------


def extract_to_file(
    files: Iterable[Path],
    keys: Sequence[str],
    out_path: Path | str | None = None,
    fmt: Format = "tsv",
    *,
    with_stats: bool = False,
    max_workers: int = 8,
    progress_cb: ProgressCallback | None = None,
) -> Path | list[Path]:
    """Extract metadata, dispatching by output template.

    Two output modes, picked from the shape of ``out_path``:

    * **Summary** (the default): one row per input file, one column
      per key, time-series values reduced to their mean. Returned as a
      single :class:`~pathlib.Path` to the table.
    * **Per-file**: triggered when ``out_path`` contains the literal
      placeholder ``<filename>``. Each input file gets its own table
      with the *full* arrays preserved (so e.g.
      ``time + temperature/value`` lands as a 2-column CSV with one row
      per sample). Returned as a ``list[Path]`` of every file written.

    If ``out_path`` is ``None`` we fall back to summary mode at
    ``./extracted_<YYYYMMDD-HHMMSS>.<ext>``.
    """
    if out_path is not None and "<filename>" in str(out_path):
        return extract_per_file(
            files, keys, out_path, fmt=fmt, progress_cb=progress_cb
        )
    if out_path is None:
        ext = {"tsv": "tsv", "csv": "csv", "columns": "txt"}[fmt]
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out_path = Path.cwd() / f"extracted_{stamp}.{ext}"
    out_path = Path(out_path)
    rows = extract_many(files, keys, max_workers=max_workers, progress_cb=progress_cb)
    return write_table(rows, keys, out_path, fmt=fmt, with_stats=with_stats)


# ---------------------------------------------------------------------------
# Per-file mode — one output per input, full arrays preserved
# ---------------------------------------------------------------------------


def extract_per_file(
    files: Iterable[Path],
    keys: Sequence[str],
    out_template: Path | str,
    fmt: Format = "tsv",
    *,
    progress_cb: ProgressCallback | None = None,
) -> list[Path]:
    """One output file per input. ``<filename>`` in ``out_template`` is
    replaced with each input's stem (``EQSANS_001.nxs.h5`` → ``EQSANS_001``).

    Selected keys are read as full 1-D arrays and laid out as columns,
    one row per sample. A scalar key (e.g. ``/entry/duration``) is
    broadcast to every row. Mismatched-length arrays still produce a
    file: shorter columns are padded with empty cells so the user can
    see the misalignment rather than getting a silent failure.
    """
    template = str(out_template)
    if "<filename>" not in template:
        raise ValueError(
            "extract_per_file: out_template must contain '<filename>' placeholder"
        )
    files_list = [Path(p) for p in files]
    written: list[Path] = []
    total = len(files_list)
    for i, path in enumerate(files_list, start=1):
        out = _resolve_template(template, path)
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            arrays = _read_arrays_one(path, keys)
        except HdfError:
            # Skip unreadable files — caller's progress_cb still ticks.
            if progress_cb is not None:
                progress_cb(i, total)
            continue
        rows = _build_array_rows(keys, arrays)
        header = [_short_key(k) for k in keys]
        if fmt == "csv":
            text = _to_delimited(header, rows, delim=",")
        elif fmt == "tsv":
            text = _to_delimited(header, rows, delim="\t")
        elif fmt == "columns":
            text = _to_columns(header, rows)
        else:
            raise ValueError(f"unknown fmt: {fmt!r}")
        out.write_text(text, encoding="utf-8")
        written.append(out)
        if progress_cb is not None:
            progress_cb(i, total)
    return written


def _resolve_template(template: str, path: Path) -> Path:
    """Substitute ``<filename>`` with the input's stem.

    A typical SNS NeXus name like ``EQSANS_172749.nxs.h5`` has
    ``Path.stem`` = ``EQSANS_172749.nxs`` (Path only strips the last
    suffix), so we additionally strip a trailing ``.nxs`` if present.
    """
    stem = path.stem
    if stem.endswith(".nxs"):
        stem = stem[:-4]
    return Path(template.replace("<filename>", stem))


def _read_arrays_one(path: Path, keys: Sequence[str]) -> dict[str, np.ndarray | None]:
    """Read each key as a flat 1-D array; ``None`` for misses."""
    out: dict[str, np.ndarray | None] = {}
    with open_nexus(path) as fh:
        for key in keys:
            try:
                out[key] = _read_array(fh, key)
            except (KeyError, ValueError, OSError):
                out[key] = None
    return out


def _read_array(fh, key: str) -> np.ndarray | None:  # type: ignore[no-untyped-def]
    """Resolve ``key`` to a 1-D array; recurse into ``value`` for groups."""
    norm = key.lstrip("/")
    if norm not in fh:
        return None
    obj = fh[norm]
    if hasattr(obj, "keys"):  # h5py.Group
        if "value" in obj:
            return _read_array(fh, f"{norm}/value")
        return None
    arr = np.asarray(obj[()])
    if arr.ndim == 0:
        return arr.reshape(1)
    return arr.ravel()


def _build_array_rows(
    keys: Sequence[str], arrays: dict[str, np.ndarray | None]
) -> list[list[str]]:
    """Lay out the per-key arrays as a row-major table.

    Row count is the longest array (excluding scalars). Scalars are
    repeated in every row; arrays shorter than the row count get blank
    cells past their end.
    """
    long_lengths = [len(a) for a in arrays.values() if a is not None and len(a) > 1]
    n_rows = max(long_lengths) if long_lengths else 1
    rows: list[list[str]] = []
    for r in range(n_rows):
        row: list[str] = []
        for k in keys:
            a = arrays.get(k)
            if a is None:
                row.append("")
            elif len(a) == 1:
                row.append(_format_array_cell(a[0]))
            elif r < len(a):
                row.append(_format_array_cell(a[r]))
            else:
                row.append("")
        rows.append(row)
    return rows


def _format_array_cell(v) -> str:  # type: ignore[no-untyped-def]
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


# ---------------------------------------------------------------------------
# Key suggestion (powers the dialog's autocomplete)
# ---------------------------------------------------------------------------


def suggest_keys(path: Path, *, prefix: str = "/entry/DASlogs") -> list[str]:
    """Return DASlogs-style keys present in ``path``, ready for the picker.

    Walks ``prefix`` and yields ``<prefix>/<child>/value`` for every
    direct child that has a ``value`` member (the DASlogs convention).
    Falls back to plain ``<prefix>/<child>`` for children without a
    ``value`` member, so non-DAS groups still get something to click
    on. Errors return an empty list — the caller surfaces a notify
    rather than crashing the dialog.
    """
    try:
        with open_nexus(Path(path)) as fh:
            if prefix.lstrip("/") not in fh:
                return []
            group = fh[prefix.lstrip("/")]
            keys: list[str] = []
            for name in group:
                child = group[name]
                # h5py.Group exposes a .keys() iterator; we test for
                # 'value' presence rather than isinstance to avoid
                # importing h5py at module top.
                if hasattr(child, "keys") and "value" in child:
                    keys.append(f"{prefix.rstrip('/')}/{name}/value")
                else:
                    keys.append(f"{prefix.rstrip('/')}/{name}")
            keys.sort()
            return keys
    except HdfError:
        return []


__all__ = [
    "Row",
    "extract_many",
    "extract_one",
    "extract_per_file",
    "extract_to_file",
    "suggest_keys",
    "write_table",
]
