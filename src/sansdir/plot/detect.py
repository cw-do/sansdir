"""Sniff what kind of plot a SANS file wants.

Classification uses three signals, in priority order:

1. **Filename** — ``*.nxs.h5`` → ``nexus``; ``*trans*.txt`` (or any other
   extension containing "trans") → ``transmission``.
2. **Header keywords** in ``#``-prefixed lines — ``lambda`` / ``wavelength``
   / ``T(`` upgrades to ``transmission``; ``Iqxqy`` / ``qx qy`` / ``2D``
   upgrades to ``iqxqy``.
3. **First-data-row column count** — 2/3/4 → ``iq``; 4/6 with repeating
   first-column → ``iqxqy``.

Detection is cheap (reads a handful of lines) and pure.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

KIND_IQ: str = "iq"
KIND_TRANSMISSION: str = "transmission"
KIND_IQXQY: str = "iqxqy"
KIND_NEXUS: str = "nexus"
KIND_UNKNOWN: str = "unknown"

VALID_KINDS: frozenset[str] = frozenset(
    {KIND_IQ, KIND_TRANSMISSION, KIND_IQXQY, KIND_NEXUS, KIND_UNKNOWN}
)

_TRANS_NAME_RE = re.compile(r"trans", re.IGNORECASE)
# ``reduceUSANS`` output: UN_<name>_det_1.txt, _det_1_lb.txt,
# _det_1_unscaled.txt, _det_1_background_subtracted.txt — all comma-separated
# ``q,I,E`` 1D curves. Matched by name because the sample name is arbitrary
# and could contain "trans", which would otherwise mis-route the file to the
# transmission plotter.
_USANS_REDUCED_RE = re.compile(r"^UN_.+_det_\d+.*\.txt$", re.IGNORECASE)
_TRANS_HEADER_RE = re.compile(r"\b(lambda|wavelength|T\s*\(|transmission)\b", re.IGNORECASE)
# "Qx Qy", "Qx,Qy" and the NIST-style "Data columns Qx - Qy - I(Qx,Qy) - err(I)".
_IQXQY_HEADER_RE = re.compile(r"\b(iqxqy|qx\W{0,5}qy|2d)\b", re.IGNORECASE)
# drtsans / Mantid name 2D output *_Iqxy.dat / *_Iqxqy.dat.
_IQXQY_NAME_RE = re.compile(r"iq\s*x\s*q?\s*y", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Detected:
    """Result of :func:`detect_kind`."""

    kind: str
    columns: int = 0  # column count of the first data row (0 for nexus/unknown)


def detect_kind(path: Path) -> Detected:
    """Classify ``path``. Doesn't read the whole file.

    Picks NeXus / HDF5 by checking the first 8 bytes for the HDF5
    magic signature in addition to the ``.nxs.h5`` filename. Mantid
    sometimes writes its processed output as just ``.nxs`` (without
    ``.h5``); the file is still HDF5 so detector plot / metadata
    extract still apply. Falls back to extension if the file isn't
    readable for the magic check.
    """
    suffixes = "".join(path.suffixes).lower()
    name_says_nexus = suffixes.endswith(".nxs.h5") or suffixes.endswith(".nxs")
    if name_says_nexus or _is_hdf5_magic(path):
        return Detected(kind=KIND_NEXUS, columns=0)
    if not path.is_file():
        return Detected(kind=KIND_UNKNOWN, columns=0)

    name_says_trans = bool(_TRANS_NAME_RE.search(path.name))
    header = _read_header(path)
    cols = _peek_columns(path)

    # USANS reduced curves are unambiguous from their filename — decide
    # before the transmission / column-count heuristics get a say.
    if _USANS_REDUCED_RE.match(path.name):
        return Detected(kind=KIND_IQ, columns=cols)
    if name_says_trans or _TRANS_HEADER_RE.search(header):
        return Detected(kind=KIND_TRANSMISSION, columns=cols)
    if cols == 0:
        return Detected(kind=KIND_UNKNOWN, columns=0)
    if _IQXQY_NAME_RE.search(path.name) or _IQXQY_HEADER_RE.search(header):
        return Detected(kind=KIND_IQXQY, columns=cols)
    if cols in (4, 6) and _looks_2d(path):
        return Detected(kind=KIND_IQXQY, columns=cols)
    if cols in (2, 3, 4):
        return Detected(kind=KIND_IQ, columns=cols)
    return Detected(kind=KIND_UNKNOWN, columns=cols)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# First 8 bytes of every HDF5 file (and therefore every NeXus file
# Mantid or the DAS writes). Used to sniff content rather than rely
# on the extension, since processed Mantid output is sometimes saved
# as plain ``.nxs`` rather than ``.nxs.h5``.
_HDF5_MAGIC: bytes = b"\x89HDF\r\n\x1a\n"


def _is_hdf5_magic(path: Path) -> bool:
    """Cheap content sniff: first 8 bytes match the HDF5 signature."""
    try:
        with path.open("rb") as fh:
            return fh.read(len(_HDF5_MAGIC)) == _HDF5_MAGIC
    except OSError:
        return False


def _iter_data_lines(path: Path, *, max_lines: int = 8) -> Iterable[str]:
    """Yield up to ``max_lines`` non-comment, non-blank lines from ``path``."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            n = 0
            for line in fh:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                yield stripped
                n += 1
                if n >= max_lines:
                    return
    except OSError:
        return


_PEEK_LINES: int = 8


def _split(line: str) -> list[str]:
    """One data row's fields: comma-separated if it has commas, else whitespace."""
    if "," in line:
        return [f.strip() for f in line.split(",") if f.strip()]
    return line.split()


def _data_rows(path: Path, *, max_lines: int = _PEEK_LINES) -> list[list[str]]:
    """The first data rows that share the most common column count.

    Mantid's ``SaveAscii`` writes a lone spectrum number (``1``) before the
    data, and transmission files a sample count; taking the dominant column
    count over a few rows drops those, as :func:`sansdir.plot.ascii1d`'s
    loader does — otherwise a 4-column I(q) file sniffs as 1 column.
    """
    from collections import Counter

    rows = [_split(line) for line in _iter_data_lines(path, max_lines=max_lines)]
    rows = [r for r in rows if r]
    if not rows:
        return []
    width = Counter(len(r) for r in rows).most_common(1)[0][0]
    return [r for r in rows if len(r) == width]


def _peek_columns(path: Path) -> int:
    """The data's column count (comma or whitespace separated), or 0 if none."""
    rows = _data_rows(path)
    return len(rows[0]) if rows else 0


def _is_numeric_row(line: str) -> bool:
    """Whether a line starts with a number (a data row, not a text header)."""
    fields = _split(line)
    try:
        float(fields[0])
    except (ValueError, IndexError):
        return False
    return True


def _read_header(path: Path, *, max_lines: int = 8) -> str:
    """Concatenate the header lines before the data into one string.

    ``#`` comments, and also plain text lines before the first numeric row
    (Mantid's NIST-style 2D ``.dat`` starts ``Data columns Qx - Qy - …``).
    Used for keyword-based kind detection when the filename and column
    count alone aren't decisive.
    """
    out: list[str] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                if not stripped.startswith("#") and _is_numeric_row(stripped):
                    break
                out.append(stripped.lstrip("#").strip())
                if len(out) >= max_lines:
                    break
    except OSError:
        return ""
    return " ".join(out)


def _looks_2d(path: Path) -> bool:
    """Heuristic for distinguishing 4-col Iq (q I sigI sigq) from 4-col Iqxqy.

    A real 2D file usually has the first column change *every* row (qx
    sweeps through many values), while 1D Iq has a monotonic q axis.
    Sampling a few rows and checking for repeated qx values within the
    first few entries is good enough — and dirt cheap.
    """
    import itertools

    rows = _data_rows(path)[:4]
    if len(rows) < 3:
        return False
    try:
        first_cols = [float(r[0]) for r in rows]
    except ValueError:
        return False
    # 1D Iq: q is strictly increasing. 2D Iqxqy: qx repeats or is non-monotonic.
    return not all(b > a for a, b in itertools.pairwise(first_cols))
