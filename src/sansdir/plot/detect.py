"""Sniff what kind of plot a SANS file wants.

We classify by extension *plus* a peek at the first non-comment line:

* ``*trans*.txt`` → ``transmission`` (different axis labels, linear scales)
* 2/3/4-col ASCII   → ``iq`` (1D reduced data)
* 4/6-col ASCII     → ``iqxqy`` if the file looks 2D (Phase 6)
* ``*.nxs.h5``      → ``nexus`` (Phase 7)

Detection is cheap (reads a few lines) and pure — it returns a string
constant that the dispatcher uses to pick a plot command.
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


@dataclass(frozen=True, slots=True)
class Detected:
    """Result of :func:`detect_kind`."""

    kind: str
    columns: int = 0  # column count of the first data row (0 for nexus/unknown)


def detect_kind(path: Path) -> Detected:
    """Classify ``path``. Doesn't read the whole file."""
    suffixes = "".join(path.suffixes).lower()
    if suffixes.endswith(".nxs.h5"):
        return Detected(kind=KIND_NEXUS, columns=0)
    if not path.is_file():
        return Detected(kind=KIND_UNKNOWN, columns=0)

    # Transmission lives under the *trans* naming convention regardless
    # of column count.
    if _TRANS_NAME_RE.search(path.name):
        cols = _peek_columns(path)
        return Detected(kind=KIND_TRANSMISSION, columns=cols)

    cols = _peek_columns(path)
    if cols == 0:
        return Detected(kind=KIND_UNKNOWN, columns=0)
    if cols in (4, 6) and _looks_2d(path):
        return Detected(kind=KIND_IQXQY, columns=cols)
    if cols in (2, 3, 4):
        return Detected(kind=KIND_IQ, columns=cols)
    return Detected(kind=KIND_UNKNOWN, columns=cols)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _peek_columns(path: Path) -> int:
    """Return the column count of the first non-comment line, or 0 on failure."""
    for line in _iter_data_lines(path, max_lines=1):
        return len(line.split())
    return 0


def _looks_2d(path: Path) -> bool:
    """Heuristic for distinguishing 4-col Iq (q I sigI sigq) from 4-col Iqxqy.

    A real 2D file usually has the first column change *every* row (qx
    sweeps through many values), while 1D Iq has a monotonic q axis.
    Sampling a few rows and checking for repeated qx values within the
    first few entries is good enough — and dirt cheap.
    """
    import itertools

    rows = list(_iter_data_lines(path, max_lines=4))
    if len(rows) < 3:
        return False
    try:
        first_cols = [float(r.split()[0]) for r in rows]
    except (ValueError, IndexError):
        return False
    # 1D Iq: q is strictly increasing. 2D Iqxqy: qx repeats or is non-monotonic.
    return not all(b > a for a, b in itertools.pairwise(first_cols))
