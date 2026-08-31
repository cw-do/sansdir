"""Reconcile title-grouped USANS blocks against the ASCII files on disk.

The critical USANS quirk: a titled block of N consecutive runs is really
**(N-1) ARN rocking-curve scans + 1 transmission run** (the last run). The
transmission run has no ``USANS_<run>_monitor_scan_ARN.txt`` /
``USANS_<run>_detector_scan_ARN_peak_*.txt`` files, and ``reduceUSANS``
reads exactly those — so telling the engine the block is N runs long makes
it die with ``FileNotFoundError`` on the transmission run.

N is *not* fixed: it varies with the experiment's settings (5→4 scans,
6→5, …). Rather than hard-coding a block size we look at which runs
actually have ARN files and let that set ``num_of_scans``. That handles
4/5/6-run blocks with no configuration.

A second wrinkle: sometimes a measurement is stopped and restarted under
the same title, leaving an oversized block where only the last few runs are
real. We can't always tell, so :func:`flag_restarts` narrows to the last
modal-size window and flags the block for human review — the generated CSV
is preliminary by design.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from sansdir.usans.grouping import Group

# The engine's ``Scan`` loader reads these per run. Bank 1 is enough to
# decide a run was ARN-scanned (the engine itself reads banks 1..4).
MONITOR_PATTERN: str = "USANS_{run}_monitor_scan_ARN.txt"
DETECTOR_PATTERN: str = "USANS_{run}_detector_scan_ARN_peak_1.txt"


def is_reducible(data_dir: Path, run: int) -> bool:
    """True when ``run`` has the ARN monitor + detector files the engine needs.

    Args:
        data_dir: The IPTS ``shared/autoreduce`` folder.
        run: Run number to test.
    """
    return (data_dir / MONITOR_PATTERN.format(run=run)).exists() and (
        data_dir / DETECTOR_PATTERN.format(run=run)
    ).exists()


def reducible_runs(data_dir: str | Path, runs: list[int]) -> list[int]:
    """Subset of ``runs`` that have ARN-scan files present, order preserved."""
    base = Path(data_dir)
    return [r for r in runs if is_reducible(base, r)]


def reconcile(groups: list[Group], data_dir: str | Path) -> None:
    """Fill in each block's :attr:`~sansdir.usans.grouping.Group.scan_runs`.

    After this, a block's ``reduce_*`` properties reflect only the runs the
    engine can actually process, dropping the trailing transmission run.

    Args:
        groups: Blocks to annotate in place.
        data_dir: The IPTS ``shared/autoreduce`` folder.
    """
    base = Path(data_dir)
    for g in groups:
        g.scan_runs = reducible_runs(base, g.runs)


def modal_scan_count(groups: list[Group]) -> int | None:
    """The most common reducible-scan count among included sample blocks.

    Background blocks are included in the tally only when nothing else is
    available, since an experiment usually measures the empty cell with the
    same scan count as its samples.

    Returns:
        The modal count, or ``None`` when there is nothing to count.
    """
    counts = [g.reduce_count for g in groups if g.included and not g.is_background]
    counts = [c for c in counts if c > 0]
    if not counts:
        counts = [g.reduce_count for g in groups if g.included and g.reduce_count > 0]
    if not counts:
        return None
    # Counter.most_common breaks ties by insertion order; sort first so the
    # result is deterministic regardless of block ordering.
    tally = Counter(counts)
    best = max(tally.values())
    return min(c for c, n in tally.items() if n == best)


def flag_restarts(groups: list[Group], *, modal: int | None = None) -> list[Group]:
    """Narrow and flag oversized blocks that look like stop-and-restart.

    A block with more ARN-scanned runs than the modal block size is usually
    an aborted measurement followed by the real one under the same title.
    The best guess is that the *last* ``modal`` scans are the real
    measurement, so we set ``window`` to that slice and raise
    ``restart_suspect`` — the NOTE then tells the user to verify before
    reducing.

    Blocks are only narrowed when the modal size is established by at least
    two blocks; a single-block experiment has no baseline to judge against
    and is left untouched.

    Args:
        groups: Blocks to annotate in place (must already be reconciled).
        modal: Override the computed modal scan count.

    Returns:
        The blocks that were flagged.
    """
    if modal is None:
        modal = modal_scan_count(groups)
    if modal is None or modal <= 0:
        return []
    sized = [g for g in groups if g.included and g.reduce_count == modal]
    if len(sized) < 2:
        return []
    flagged: list[Group] = []
    for g in groups:
        if not g.included or g.scan_runs is None:
            continue
        if len(g.scan_runs) <= modal:
            continue
        g.window = g.scan_runs[-modal:]
        g.restart_suspect = True
        flagged.append(g)
    return flagged
