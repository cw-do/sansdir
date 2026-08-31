"""The USANS reduction table — the reviewable, hand-editable setup CSV.

CSV columns, consumed verbatim by ``reduceUSANS``::

    flag,name,start_scan,num_of_scans,thickness_cm[,exclude;scan;nums]

* ``flag``          — ``b`` background (empty cell) / ``s`` sample
* ``name``          — sample name; becomes the ``UN_<name>_det_1*.txt`` stem
* ``start_scan``    — first run number of the block
* ``num_of_scans``  — how many consecutive runs the engine should read
* ``thickness_cm``  — sample thickness in cm
* ``exclude``       — optional ``;``-separated run numbers to skip

Rows starting with ``#`` are comments the engine ignores, so we use them
for a human-readable header. The file is plain text on purpose: it is
reviewed and corrected with sansdir's existing ``F4`` ($EDITOR) flow rather
than a bespoke table widget.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from sansdir.usans.grouping import DEFAULT_THICKNESS_CM, Group

# Number of leading cells a valid data row must have.
MIN_CELLS: int = 4


class TableError(ValueError):
    """Raised when a setup CSV can't be parsed or fails validation."""


@dataclass
class Row:
    """One line of the setup CSV.

    Attributes:
        flag: ``"b"`` (background/empty cell) or ``"s"`` (sample).
        name: Sample name — becomes the reduced-output filename stem.
        start_run: First run number of the block.
        num_runs: Consecutive runs the engine reads from ``start_run``.
        thickness_cm: Sample thickness in centimetres.
        exclude: Run numbers inside the span the engine must skip.
        annotation: Free-text note from the run title. Never written to the
            engine CSV — it lives in the NOTE and in dialogs.
        restart_suspect: Set when the generator narrowed an oversized block
            and wants the user to confirm the guess.
    """

    flag: str
    name: str
    start_run: int
    num_runs: int
    thickness_cm: float = DEFAULT_THICKNESS_CM
    exclude: list[int] = field(default_factory=list)
    annotation: str = ""
    restart_suspect: bool = False

    @property
    def is_background(self) -> bool:
        """True for the ``b``-flagged empty-cell row."""
        return self.flag == "b"

    @property
    def end_run(self) -> int:
        """Last run number the engine will read for this row."""
        return self.start_run + self.num_runs - 1

    def to_cells(self) -> list[str]:
        """Render as the CSV cells ``reduceUSANS`` expects."""
        cells = [
            self.flag,
            self.name,
            str(self.start_run),
            str(self.num_runs),
            f"{self.thickness_cm:g}",
        ]
        if self.exclude:
            cells.append(";".join(str(r) for r in self.exclude))
        return cells


def _row_from_group(g: Group, *, flag: str | None = None) -> Row:
    """Build a :class:`Row` from a reconciled :class:`Group`."""
    return Row(
        flag=flag if flag is not None else g.flag,
        name=g.name,
        start_run=g.reduce_start,
        num_runs=g.reduce_count,
        thickness_cm=g.thickness_cm,
        exclude=g.reduce_exclude,
        annotation=g.annotation,
        restart_suspect=g.restart_suspect,
    )


@dataclass
class ReductionTable:
    """An ordered list of :class:`Row` plus the IPTS it belongs to."""

    ipts: str
    rows: list[Row] = field(default_factory=list)

    # ---- construction ----------------------------------------------------

    @classmethod
    def from_groups(
        cls,
        ipts: str,
        groups: list[Group],
        background: Group | None,
    ) -> ReductionTable:
        """Build a table from reconciled blocks.

        The background row is written first so a reader sees the empty cell
        at the top. Blocks with zero reducible runs are skipped entirely —
        the engine would raise ``FileNotFoundError`` on them — and they are
        reported in the NOTE instead.

        Args:
            ipts: Label such as ``"IPTS-37679"``, written into the header.
            groups: Blocks from :func:`~sansdir.usans.grouping.group_runs`.
            background: The chosen empty-cell block, or ``None``.
        """
        rows: list[Row] = []
        if background is not None and background.reduce_count > 0:
            rows.append(_row_from_group(background, flag="b"))
        for g in groups:
            if not g.included or g is background or g.reduce_count == 0:
                continue
            # An extra empty/banjo block that isn't the chosen background is
            # still reduced, but as a sample — the engine treats the last
            # ``b`` row as THE background, and two of them is ambiguous.
            rows.append(_row_from_group(g, flag="s" if g.is_background else None))
        return cls(ipts=ipts, rows=rows)

    @classmethod
    def from_csv(cls, path: str | Path, ipts: str = "") -> ReductionTable:
        """Parse a setup CSV back into a table.

        Used to validate a user-edited file before handing it to the engine,
        and by the NOTE renderer. Comment and blank lines are skipped.

        Raises:
            TableError: On a malformed row (bad column count or non-numeric
                run / thickness values).
        """
        path = Path(path)
        rows: list[Row] = []
        label = ipts
        with path.open(newline="", encoding="utf-8") as fh:
            for lineno, raw in enumerate(csv.reader(fh), start=1):
                if not raw or not raw[0].strip() or raw[0].strip().startswith("#"):
                    if not label and raw and "IPTS-" in ",".join(raw):
                        label = _ipts_from_text(",".join(raw))
                    continue
                if len(raw) < MIN_CELLS:
                    raise TableError(
                        f"{path}:{lineno}: expected at least {MIN_CELLS} columns "
                        f"(flag,name,start_scan,num_of_scans), got {len(raw)}"
                    )
                flag = raw[0].strip().lower()
                if flag not in ("b", "s"):
                    raise TableError(f"{path}:{lineno}: flag must be 'b' or 's', got {flag!r}")
                try:
                    start_run = int(raw[2])
                    num_runs = int(raw[3])
                    thickness = (
                        float(raw[4]) if len(raw) > 4 and raw[4].strip() else DEFAULT_THICKNESS_CM
                    )
                    exclude = (
                        [int(x) for x in raw[5].split(";") if x.strip()]
                        if len(raw) > 5 and raw[5].strip()
                        else []
                    )
                except ValueError as exc:
                    raise TableError(f"{path}:{lineno}: {exc}") from exc
                rows.append(
                    Row(
                        flag=flag,
                        name=raw[1].strip(),
                        start_run=start_run,
                        num_runs=num_runs,
                        thickness_cm=thickness,
                        exclude=exclude,
                    )
                )
        return cls(ipts=label, rows=rows)

    # ---- inspection ------------------------------------------------------

    def find(self, name: str) -> Row | None:
        """First row named ``name``, or ``None``."""
        for r in self.rows:
            if r.name == name:
                return r
        return None

    @property
    def backgrounds(self) -> list[Row]:
        """Every ``b``-flagged row (should be exactly one)."""
        return [r for r in self.rows if r.is_background]

    def validate(self) -> list[str]:
        """Return human-readable problems that would break the reduction.

        An empty list means the table is safe to hand to ``reduceUSANS``.
        """
        problems: list[str] = []
        if not self.rows:
            problems.append("no data rows — nothing to reduce")
        n_bg = len(self.backgrounds)
        if n_bg == 0:
            problems.append("no background row — exactly one row must have flag 'b'")
        elif n_bg > 1:
            names = ", ".join(r.name for r in self.backgrounds)
            problems.append(f"{n_bg} background rows ({names}) — exactly one 'b' row is allowed")
        for r in self.rows:
            if r.num_runs <= 0:
                problems.append(f"{r.name}: num_of_scans is {r.num_runs} — must be ≥ 1")
            if r.thickness_cm <= 0:
                problems.append(f"{r.name}: thickness is {r.thickness_cm:g} cm — must be > 0")
            stray = [e for e in r.exclude if not r.start_run <= e <= r.end_run]
            if stray:
                problems.append(
                    f"{r.name}: exclude {stray} falls outside {r.start_run}-{r.end_run}"
                )
        duplicates = {n for n in (r.name for r in self.rows) if _count(self.rows, n) > 1}
        for name in sorted(duplicates):
            problems.append(f"duplicate sample name {name!r} — reduced outputs would overwrite")
        return problems

    # ---- editing ---------------------------------------------------------

    def set_thickness(self, name: str, thickness_cm: float) -> bool:
        """Set one sample's thickness; ``False`` when the name is unknown."""
        row = self.find(name)
        if row is None:
            return False
        row.thickness_cm = thickness_cm
        return True

    def set_background(self, name: str) -> bool:
        """Make ``name`` the background, demoting any current one to sample."""
        target = self.find(name)
        if target is None:
            return False
        for r in self.rows:
            r.flag = "s"
        target.flag = "b"
        return True

    # ---- output ----------------------------------------------------------

    def to_csv(self, path: str | Path, *, header: bool = True) -> Path:
        """Write the engine-ready setup CSV; returns the path written.

        Line endings are forced to ``\\n``. ``csv.writer`` defaults to
        ``\\r\\n``, which would leave the header comments (written with
        plain ``write``) and the data rows disagreeing — an ugly surprise
        for a file whose whole point is being hand-edited in ``$EDITOR``.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            if header:
                fh.write(f"# USANS reduction table for {self.ipts}\n")
                fh.write("# columns: flag,name,start_scan,num_of_scans,thickness_cm[,exclude]\n")
                fh.write("#   flag: b=background(empty)  s=sample\n")
            writer = csv.writer(fh, lineterminator="\n")
            for r in self.rows:
                writer.writerow(r.to_cells())
        return path


def _count(rows: list[Row], name: str) -> int:
    return sum(1 for r in rows if r.name == name)


def _ipts_from_text(text: str) -> str:
    """Pull an ``IPTS-NNNNN`` label out of free text; ``""`` when absent."""
    idx = text.find("IPTS-")
    if idx < 0:
        return ""
    tail = text[idx + len("IPTS-") :]
    digits = ""
    for ch in tail:
        if not ch.isdigit():
            break
        digits += ch
    return f"IPTS-{digits}" if digits else ""
