"""Reconcile title-grouped USANS blocks against the ASCII files on disk.

A titled block of N consecutive runs is **not** N usable rocking scans, and
which runs to leave out differs between experiments. Every run the engine
must not read is dropped from :attr:`~sansdir.usans.grouping.Group.scan_runs`
and its reason is recorded in :attr:`~sansdir.usans.grouping.Group.skipped`,
so the NOTE can list *what was left out and why* instead of guessing:

* **No ARN scan files** — ``reduceUSANS`` reads
  ``USANS_<run>_monitor_scan_ARN.txt`` / ``..._detector_scan_ARN_peak_*.txt``
  and dies with ``FileNotFoundError`` on a run without them. Two kinds seen
  so far: the *trailing transmission run* of each block (IPTS-37679), and
  *pause* runs with a near-zero monitor sitting in front of a block
  (IPTS-35306, 48233 / 48248).
* **Off-wavelength runs** — a run whose per-run files carry only a
  non-primary wavelength suffix (``USANS_<run>_detector_1.2.txt``, no
  ``_3.6``). The *first* run of every block in IPTS-35306 and IPTS-37679 is
  one; it has ARN files, but a ~15x lower monitor and essentially no
  detector counts. Why the instrument records these is not yet known, so
  the rule can be switched off (``skip_off_wavelength``) and every skipped
  run is listed in the NOTE rather than dropped silently.

Runs that are kept but look suspicious (monitor far below the block's
median) are recorded in :attr:`~sansdir.usans.grouping.Group.run_warnings`.

N itself is *not* fixed: it varies with the experiment's settings, so
``num_of_scans`` always comes from the runs that survive, never from a
hard-coded block size.

A second wrinkle: sometimes a measurement is stopped and restarted under
the same title, leaving an oversized block where only the last few runs are
real. We can't always tell, so :func:`flag_restarts` narrows to the last
modal-size window and flags the block for human review — the generated CSV
is preliminary by design.
"""

from __future__ import annotations

import csv
import re
import statistics
from collections import Counter
from pathlib import Path

from sansdir.usans.grouping import Group

# The engine's ``Scan`` loader reads these per run. Bank 1 is enough to
# decide a run was ARN-scanned (the engine itself reads banks 1..4).
MONITOR_PATTERN: str = "USANS_{run}_monitor_scan_ARN.txt"
DETECTOR_PATTERN: str = "USANS_{run}_detector_scan_ARN_peak_1.txt"

# Whole-run monitor counts (``X,Y,E`` rows under a ``#`` header).
MONITOR_COUNTS_PATTERN: str = "USANS_{run}_monitor.txt"

# ``USANS_<run>_detector_<wavelength>.txt`` — autoreduction's per-run file
# tagged with the wavelength the run was recorded at.
WAVELENGTH_FILE_RE: re.Pattern[str] = re.compile(r"^USANS_(\d+)_detector_(\d+(?:\.\d+)?)\.txt$")

# The analyzer's primary wavelength (Å); the engine's ``prim_wave`` default.
PRIMARY_WAVELENGTH: str = "3.6"

# A run without ARN files whose monitor is below this is a pause, not a
# transmission run (IPTS-35306 pauses: 8-12 counts; transmission runs: 10^3+).
PAUSE_MONITOR_MAX: int = 1000

# A kept run whose monitor is below this fraction of its block's median is
# flagged for review (not dropped).
LOW_MONITOR_FRACTION: float = 0.1

# Reason labels stored in ``Group.skipped``; the NOTE groups by these.
REASON_OFF_WAVELENGTH: str = "off-wavelength"
REASON_PAUSE: str = "pause"
REASON_NO_ARN: str = "no ARN scan files"


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


def run_wavelengths(data_dir: str | Path) -> dict[int, set[str]]:
    """Map run → wavelengths its ``USANS_<run>_detector_<λ>.txt`` files carry.

    One directory scan for the whole IPTS rather than a glob per run: the
    autoreduce folder holds thousands of files on a network mount.
    """
    out: dict[int, set[str]] = {}
    try:
        names = [e.name for e in Path(data_dir).iterdir()]
    except OSError:
        return out
    for name in names:
        m = WAVELENGTH_FILE_RE.match(name)
        if m:
            out.setdefault(int(m.group(1)), set()).add(m.group(2))
    return out


def off_wavelength(wavelengths: set[str], primary: str = PRIMARY_WAVELENGTH) -> str | None:
    """The run's wavelength when it was recorded *only* off the primary one.

    Runs without any wavelength-tagged file (older autoreduction) are never
    flagged: absence of evidence is not a 1.2 Å marker.

    Returns:
        E.g. ``"1.2"``, or ``None`` for a normal (or untagged) run.
    """
    if not wavelengths or primary in wavelengths:
        return None
    return ",".join(sorted(wavelengths))


def monitor_counts(data_dir: str | Path, run: int) -> int | None:
    """Total monitor counts of ``run``, or ``None`` when the file is missing/bad.

    Sums the second column of ``USANS_<run>_monitor.txt`` the same way
    ``reduceUSANS`` does, so the numbers in the NOTE match the engine's.
    """
    path = Path(data_dir) / MONITOR_COUNTS_PATTERN.format(run=run)
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            return sum(
                int(float(row[1]))
                for row in csv.reader(fh)
                if len(row) >= 3 and not row[0].lstrip().startswith("#")
            )
    except (OSError, ValueError, IndexError):
        return None


def reconcile(
    groups: list[Group],
    data_dir: str | Path,
    *,
    skip_off_wavelength: bool = True,
    primary_wavelength: str = PRIMARY_WAVELENGTH,
) -> None:
    """Decide which runs of each block the engine should read, and why not the rest.

    Fills :attr:`~sansdir.usans.grouping.Group.scan_runs` (what survives),
    :attr:`~sansdir.usans.grouping.Group.skipped` (run → reason for every
    run left out) and :attr:`~sansdir.usans.grouping.Group.run_warnings`
    (kept runs worth a second look). After this a block's ``reduce_*``
    properties — and so ``start_scan`` / ``num_of_scans`` / ``exclude`` —
    follow from the surviving runs.

    Args:
        groups: Blocks to annotate in place.
        data_dir: The IPTS ``shared/autoreduce`` folder.
        skip_off_wavelength: Drop runs recorded only at a non-primary
            wavelength (see the module docstring). ``False`` keeps them but
            still flags them in ``run_warnings``.
        primary_wavelength: The wavelength suffix a normal scan carries.
    """
    base = Path(data_dir)
    tagged = run_wavelengths(base)
    for g in groups:
        monitors = {r: monitor_counts(base, r) for r in g.runs}
        kept: list[int] = []
        g.skipped = {}
        g.run_warnings = {}
        for r in g.runs:
            mon = monitors[r]
            mon_txt = f"monitor {mon:,} counts" if mon is not None else "no monitor file"
            if not is_reducible(base, r):
                if mon is not None and mon < PAUSE_MONITOR_MAX:
                    g.skipped[r] = f"{REASON_PAUSE} — {REASON_NO_ARN}, {mon_txt}"
                else:
                    g.skipped[r] = f"{REASON_NO_ARN} (transmission run?) — {mon_txt}"
                continue
            wl = off_wavelength(tagged.get(r, set()), primary_wavelength)
            if wl is not None:
                note = (
                    f"{REASON_OFF_WAVELENGTH} — recorded at {wl} Å "
                    f"(no _{primary_wavelength} files), {mon_txt}"
                )
                if skip_off_wavelength:
                    g.skipped[r] = note
                    continue
                g.run_warnings[r] = note + " — kept ([usans].skip_off_wavelength = false)"
            kept.append(r)
        g.scan_runs = kept
        kept_monitors = [m for r in kept if (m := monitors[r]) is not None]
        if len(kept_monitors) >= 3:
            median = statistics.median(kept_monitors)
            for r in kept:
                mon = monitors[r]
                if mon is not None and mon < LOW_MONITOR_FRACTION * median:
                    g.run_warnings.setdefault(
                        r,
                        f"low monitor — {mon:,} counts vs block median {median:,.0f}",
                    )


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
