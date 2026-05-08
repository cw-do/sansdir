"""Display-column ↔ bank/tube mapping for the EQSANS layout.

The mask GUI uses ``(col, row)`` heatmap indices internally — the same
``(192, 256)`` grid the plot loader produces after
:func:`_reorder_tubes`. Operators think in *bank* and *tube* numbers
instead, which is what's printed on the cabinet doors and shows up in
Mantid IDFs / instrument scientist scripts. This module owns the
arithmetic that bridges the two worlds.

EQSANS layout (post-reorder, what the heatmap shows)
----------------------------------------------------

* 192 display columns, organised as 24 column-groups of 8 columns.
* :data:`EQSANS_TUBE_REORDER` interleaves each group's 8 tubes
  ``[0,4,1,5,2,6,3,7]`` so front/back tubes alternate left-to-right.
* That makes each column-group exactly two banks (front + back), each
  bank carrying 4 tubes -- 24 * 2 = **48 banks**, matching
  :data:`sansdir.plot.hdf5_detector.EQSANS_NBANKS`.

Conventions
-----------

* ``bank`` is 0-based, range ``0..47``.
* ``tube_in_bank`` is 0-based, range ``0..3``.
* ``col`` is 0-based display column, range ``0..191``.
* ``row`` is 0-based pixel index within a tube, range ``0..255``.

Inverse functions :func:`bank_tube_to_col` and :func:`col_to_bank_tube`
are exact and round-trip.
"""

from __future__ import annotations

EQSANS_NBANKS = 48
EQSANS_NTUBES_PER_BANK = 4
EQSANS_NTUBES = 192
EQSANS_NPIXELS_PER_TUBE = 256


def col_to_bank_tube(col: int) -> tuple[int, int]:
    """Map a display column ``0..191`` to ``(bank, tube_in_bank)``.

    Examples:
        >>> col_to_bank_tube(0)
        (0, 0)
        >>> col_to_bank_tube(1)  # next column = back-tube of same group
        (1, 0)
        >>> col_to_bank_tube(2)  # second front-tube of group 0
        (0, 1)
        >>> col_to_bank_tube(8)  # next column-group → next front-bank
        (2, 0)
        >>> col_to_bank_tube(191)
        (47, 3)
    """
    if not 0 <= col < EQSANS_NTUBES:
        raise ValueError(f"col {col} out of range 0..{EQSANS_NTUBES - 1}")
    column_group = col // 8
    pos = col % 8
    bank = column_group * 2 + (pos % 2)
    tube_in_bank = pos // 2
    return bank, tube_in_bank


def bank_tube_to_col(bank: int, tube_in_bank: int) -> int:
    """Inverse of :func:`col_to_bank_tube`.

    Examples:
        >>> bank_tube_to_col(0, 0)
        0
        >>> bank_tube_to_col(1, 0)
        1
        >>> bank_tube_to_col(47, 3)
        191
        >>> all(
        ...     bank_tube_to_col(*col_to_bank_tube(c)) == c
        ...     for c in range(EQSANS_NTUBES)
        ... )
        True
    """
    if not 0 <= bank < EQSANS_NBANKS:
        raise ValueError(f"bank {bank} out of range 0..{EQSANS_NBANKS - 1}")
    if not 0 <= tube_in_bank < EQSANS_NTUBES_PER_BANK:
        raise ValueError(
            f"tube_in_bank {tube_in_bank} out of range "
            f"0..{EQSANS_NTUBES_PER_BANK - 1}"
        )
    column_group = bank // 2
    pos = (tube_in_bank * 2) + (bank % 2)
    return column_group * 8 + pos


def cols_for_bank(bank: int) -> list[int]:
    """Return the 4 display columns belonging to ``bank``."""
    return [bank_tube_to_col(bank, t) for t in range(EQSANS_NTUBES_PER_BANK)]


# ---------------------------------------------------------------------------
# Spec-string parser — used by the GUI's "Mask spec" text input.
# ---------------------------------------------------------------------------


def _parse_range(token: str) -> list[int]:
    """``"5"`` → ``[5]`` ; ``"5-7"`` → ``[5, 6, 7]``."""
    token = token.strip()
    if "-" in token:
        a, b = token.split("-", 1)
        lo, hi = int(a), int(b)
        if lo > hi:
            lo, hi = hi, lo
        return list(range(lo, hi + 1))
    return [int(token)]


def parse_spec(spec: str) -> list[int]:
    """Parse a ``b<...>``/``t<...>`` spec into a sorted list of columns.

    Tokens are separated by whitespace, comma, or semicolon. Each
    token must start with ``b`` (bank) or ``t`` (tube/display column),
    followed by an int or ``int-int`` range.

    Returns the sorted, deduplicated list of display columns covered.

    Examples:
        >>> parse_spec("b3")
        [12, 13, 14, 15]
        >>> parse_spec("t10")
        [10]
        >>> parse_spec("t10-12")
        [10, 11, 12]
        >>> parse_spec("b0, t5")
        [0, 1, 2, 3, 5]
        >>> parse_spec("")
        []
    """
    spec = spec.strip()
    if not spec:
        return []
    cols: set[int] = set()
    # Normalise separators to whitespace, then split.
    for raw in spec.replace(",", " ").replace(";", " ").split():
        tok = raw.strip().lower()
        if not tok:
            continue
        if tok[0] == "b":
            for bank in _parse_range(tok[1:]):
                cols.update(cols_for_bank(bank))
        elif tok[0] == "t":
            for c in _parse_range(tok[1:]):
                if not 0 <= c < EQSANS_NTUBES:
                    raise ValueError(
                        f"tube/column {c} out of range 0..{EQSANS_NTUBES - 1}"
                    )
                cols.add(c)
        else:
            raise ValueError(
                f"bad token {raw!r}: each token must start with 'b' or 't'"
            )
    return sorted(cols)


def cols_to_runs(cols: list[int]) -> list[tuple[int, int]]:
    """``[4, 5, 6, 9, 10]`` → ``[(4, 6), (9, 10)]`` (inclusive ranges)."""
    if not cols:
        return []
    s = sorted(set(cols))
    runs: list[tuple[int, int]] = []
    lo = prev = s[0]
    for n in s[1:]:
        if n == prev + 1:
            prev = n
            continue
        runs.append((lo, prev))
        lo = prev = n
    runs.append((lo, prev))
    return runs


__all__ = [
    "EQSANS_NBANKS",
    "EQSANS_NPIXELS_PER_TUBE",
    "EQSANS_NTUBES",
    "EQSANS_NTUBES_PER_BANK",
    "bank_tube_to_col",
    "col_to_bank_tube",
    "cols_for_bank",
    "cols_to_runs",
    "parse_spec",
]
