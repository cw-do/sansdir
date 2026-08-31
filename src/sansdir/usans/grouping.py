"""Group consecutive same-title USANS runs into reduction blocks.

A USANS "sample" is a run of consecutive run numbers sharing one title
(typically 5 to 7 runs). The block whose title contains ``empty`` or ``banjo``
is the background (empty cell) subtracted from every sample; everything
else is a sample.

Run titles often carry a trailing annotation after a space, e.g.
``"S0-20C 1p"`` → sample name ``S0-20C`` with annotation ``1p``. The first
whitespace token becomes the reduction sample name (and therefore the
reduced-output filename stem); the remainder is kept for the NOTE.

This module is pure: it takes anything with ``run_number`` and ``title``
attributes (:class:`sansdir.core.oncat.Datafile` satisfies that) and never
touches the network or the filesystem. On-disk reconciliation of which runs
are actually reducible lives in :mod:`sansdir.usans.reconcile`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# Title substrings that mark a block as the empty-cell background.
BACKGROUND_KEYWORDS: tuple[str, ...] = ("empty", "banjo")

# Sample thickness written into the setup CSV when the user hasn't said
# otherwise. Overridable via ``[usans].thickness_cm`` in the config.
DEFAULT_THICKNESS_CM: float = 0.1


@runtime_checkable
class RunLike(Protocol):
    """Structural type for one catalogued run.

    :class:`sansdir.core.oncat.Datafile` matches this without any adapter,
    which is the whole point — the grouping code never imports the OnCat
    client and stays offline-testable.
    """

    @property
    def run_number(self) -> int: ...

    @property
    def title(self) -> str: ...


@dataclass
class Group:
    """A contiguous block of same-title runs.

    Attributes:
        title: The verbatim OnCat run title shared by every run in the block.
        runs: Run numbers in the block, ascending and contiguous.
        thickness_cm: Sample thickness written to the setup CSV.
        included: ``False`` marks a block that is recorded in the NOTE but
            kept out of the reduction table (e.g. pre-``start_run`` tests).
        scan_runs: Runs that actually have ARN-scan files on disk. ``None``
            means "not reconciled yet" — fall back to raw title grouping.
        window: A narrowed guess at the *real* measurement inside an
            oversized (restarted) block. ``None`` when no narrowing applied.
        restart_suspect: True when the block looks like a stop-and-restart
            under one title and therefore needs human review.
    """

    title: str
    runs: list[int] = field(default_factory=list)
    thickness_cm: float = DEFAULT_THICKNESS_CM
    included: bool = True
    scan_runs: list[int] | None = None
    window: list[int] | None = None
    restart_suspect: bool = False

    # ---- raw (title-grouping) view --------------------------------------

    @property
    def start_run(self) -> int:
        """First run number of the raw title block."""
        return self.runs[0]

    @property
    def count(self) -> int:
        """How many runs the raw title block holds."""
        return len(self.runs)

    # ---- reduction view (respects on-disk ARN-scan availability) ---------

    @property
    def reduce_runs(self) -> list[int]:
        """Runs to hand the engine.

        Priority: the narrowed restart window, else the ARN-scanned subset,
        else (unreconciled) the raw title block.
        """
        if self.window is not None:
            return self.window
        if self.scan_runs is not None:
            return self.scan_runs
        return self.runs

    @property
    def reduce_start(self) -> int:
        """``start_scan`` for the setup CSV."""
        rr = self.reduce_runs
        return rr[0] if rr else self.start_run

    @property
    def reduce_count(self) -> int:
        """``num_of_scans`` for the setup CSV."""
        return len(self.reduce_runs)

    @property
    def reduce_span(self) -> int:
        """Run count from first to last reducible run, gaps included."""
        rr = self.reduce_runs
        return rr[-1] - rr[0] + 1 if rr else 0

    @property
    def reduce_exclude(self) -> list[int]:
        """Runs inside the reducible span that have no ARN files (mid-block gaps).

        ``reduceUSANS`` reads ``num_of_scans`` *consecutive* runs from
        ``start_scan``, so a hole in the middle has to be spelled out in the
        CSV's ``exclude`` column rather than shortening the count.
        """
        rr = self.reduce_runs
        if not rr:
            return []
        present = set(rr)
        return [r for r in range(rr[0], rr[-1] + 1) if r not in present]

    @property
    def transmission_runs(self) -> list[int]:
        """Runs in the title block that are *not* reducible ARN scans.

        Empty until the block has been reconciled against the data
        directory. On USANS this is normally the single trailing
        transmission run of each block.
        """
        if self.scan_runs is None:
            return []
        present = set(self.scan_runs)
        return [r for r in self.runs if r not in present]

    @property
    def dropped_runs(self) -> list[int]:
        """ARN-scanned runs excluded by the restart-window narrowing."""
        if self.window is None or self.scan_runs is None:
            return []
        kept = set(self.window)
        return [r for r in self.scan_runs if r not in kept]

    # ---- naming ---------------------------------------------------------

    @property
    def name(self) -> str:
        """Reduction sample name — the first whitespace token of the title."""
        parts = self.title.split()
        return parts[0] if parts else self.title

    @property
    def annotation(self) -> str:
        """Everything after the first whitespace token (free-text note)."""
        parts = self.title.split(None, 1)
        return parts[1].strip() if len(parts) > 1 else ""

    @property
    def is_background(self) -> bool:
        """True when the title names an empty cell / empty banjo."""
        lowered = self.title.lower()
        return any(k in lowered for k in BACKGROUND_KEYWORDS)

    @property
    def flag(self) -> str:
        """Setup-CSV flag: ``b`` background, ``s`` sample."""
        return "b" if self.is_background else "s"


def group_runs(runs: Iterable[RunLike]) -> list[Group]:
    """Collapse a run list into contiguous same-title blocks.

    A new block starts whenever the title changes or a run-number gap
    appears, so a repeated title separated by other measurements yields two
    blocks rather than one.

    Args:
        runs: Any iterable of objects exposing ``run_number`` and ``title``.

    Returns:
        Blocks in ascending run-number order.
    """
    groups: list[Group] = []
    for r in sorted(runs, key=lambda x: x.run_number):
        if groups and groups[-1].title == r.title and groups[-1].runs[-1] == r.run_number - 1:
            groups[-1].runs.append(r.run_number)
        else:
            groups.append(Group(title=r.title, runs=[r.run_number]))
    return groups


def apply_start_run(groups: list[Group], start_run: int | None) -> int:
    """Mark blocks starting before ``start_run`` as not-included.

    Used to drop the pre-experiment alignment / test runs from the reduction
    table while still recording them in the NOTE.

    Args:
        groups: Blocks to annotate in place.
        start_run: First run of the real experiment; ``None`` includes all.

    Returns:
        How many blocks were excluded.
    """
    if start_run is None:
        return 0
    excluded = 0
    for g in groups:
        if g.start_run < start_run:
            g.included = False
            excluded += 1
    return excluded


def default_background(groups: list[Group]) -> Group | None:
    """Pick the background block: the last *included* empty/banjo block.

    "Last" rather than "first" because a restarted empty-cell measurement
    supersedes the aborted one before it.
    """
    candidates = [g for g in groups if g.included and g.is_background]
    return candidates[-1] if candidates else None
