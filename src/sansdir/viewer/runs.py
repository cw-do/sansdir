"""Neighbouring runs for PgUp / PgDn, and which ones are cheap to preload (Qt-free).

Runs are the files in the same folder that share the current file's name
pattern ``<prefix><run number><suffix>`` (``EQSANS_176669.nxs.h5`` →
``EQSANS_`` + ``176669`` + ``.nxs.h5``), ordered by run number; gaps in the
numbering are skipped.

Preloading must never tie up the node behind the user's back: a run is
preloaded only when it is in the histogram cache (~0.25 s) or small enough
to load in-process (≲ 1e8 events, about a second). Multi-GB runs load when
the user actually steps to them.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from sansdir.viewer.cache import CubeCache

# ~7.8 bytes per event on disk (60 GB ↔ 7.67e9 events), so 1 GB ≈ 1.3e8 events.
PRELOAD_MAX_BYTES: int = 1_000_000_000
_RUN_RE = re.compile(r"^(?P<prefix>.*?)(?P<run>\d+)(?P<suffix>\.nxs\.h5|\.nxs|\.h5)$")


def split_run(name: str) -> tuple[str, int, str] | None:
    """``"EQSANS_176669.nxs.h5"`` → ``("EQSANS_", 176669, ".nxs.h5")``; None if no run number."""
    m = _RUN_RE.match(name)
    if m is None:
        return None
    return m["prefix"], int(m["run"]), m["suffix"]


def sibling_runs(path: Path) -> list[tuple[int, Path]]:
    """``(run, path)`` for every file next to ``path`` with the same pattern, by run."""
    parts = split_run(path.name)
    if parts is None:
        return []
    prefix, _run, suffix = parts
    found: list[tuple[int, Path]] = []
    try:
        with os.scandir(path.parent) as entries:
            for entry in entries:
                other = split_run(entry.name)
                if other is None or (other[0], other[2]) != (prefix, suffix):
                    continue
                if entry.is_file():
                    found.append((other[1], Path(entry.path)))
    except OSError:
        return []
    return sorted(found)


def neighbour(path: Path, step: int) -> Path | None:
    """The run ``step`` places after (negative: before) ``path``, or None at the ends."""
    parts = split_run(path.name)
    if parts is None or step == 0:
        return None
    runs = sibling_runs(path)
    numbers = [run for run, _ in runs]
    current = parts[1]
    if step > 0:
        later = [i for i, run in enumerate(numbers) if run > current]
        index = later[0] + step - 1 if later else None
    else:
        earlier = [i for i, run in enumerate(numbers) if run < current]
        index = earlier[-1] + step + 1 if earlier else None
    if index is None or not 0 <= index < len(runs):
        return None
    return runs[index][1]


def worth_preloading(path: Path, cache: CubeCache | None, nbins: int) -> bool:
    """Cached, or small enough to histogram in about a second."""
    if cache is not None and cache.has(path, nbins):
        return True
    try:
        return path.stat().st_size <= PRELOAD_MAX_BYTES
    except OSError:
        return False


__all__ = ["PRELOAD_MAX_BYTES", "neighbour", "sibling_runs", "split_run", "worth_preloading"]
