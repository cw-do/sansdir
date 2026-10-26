"""Find a raw run file from its run number alone, like Mantid's file finder.

Mantid finds ``EQSANS_176669`` without being told the IPTS; this does the
same on the cluster filesystem, without OnCat or any network call: look in
every ``<root>/IPTS-*`` folder for the run's file, in the layouts EQSANS
has used:

* ``IPTS-N/nexus/EQSANS_<run>.nxs.h5`` — current;
* ``IPTS-N/data/EQSANS_<run>_event.nxs`` — older runs (before ~2018).

Only existence checks — nothing is opened or written. ~1100 IPTS folders
take ~1 s one by one on GPFS, so the checks run on a thread pool, and the
folders most likely to hold the run (the last hit's IPTS, the one the user
is in) are tried first. UI-free; the TUI calls :func:`find_run` from a
worker thread.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DEFAULT_ROOT = Path("/SNS/EQSANS")
DEFAULT_PREFIX = "EQSANS"
ROOT_ENV = "SANSDIR_RUN_ROOT"  # tests (and other trees) point the search elsewhere
WORKERS = 32
_IPTS_RE = re.compile(r"^IPTS-(\d+)$")
_RUN_RE = re.compile(r"(\d+)")

_last_hit_ipts: Path | None = None


def parse_run(text: str) -> int | None:
    """``"176669"`` / ``"EQSANS_176669"`` / ``" run 176669 "`` → 176669; None if no number."""
    numbers = _RUN_RE.findall(text)
    return int(numbers[-1]) if numbers else None


def search_root() -> Path:
    env = os.environ.get(ROOT_ENV)
    return Path(env) if env else DEFAULT_ROOT


def candidates(ipts_dir: Path, run: int, prefix: str = DEFAULT_PREFIX) -> list[Path]:
    """Where run ``run`` would be inside one IPTS folder, newest layout first."""
    return [
        ipts_dir / "nexus" / f"{prefix}_{run}.nxs.h5",
        ipts_dir / "data" / f"{prefix}_{run}_event.nxs",
    ]


def ipts_dirs(root: Path) -> list[Path]:
    """``root/IPTS-*`` folders, newest (highest number) first; [] if unreadable."""
    found: list[tuple[int, Path]] = []
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                m = _IPTS_RE.match(entry.name)
                if m is not None:
                    found.append((int(m.group(1)), Path(entry.path)))
    except OSError:
        return []
    return [path for _, path in sorted(found, reverse=True)]


def ipts_of(path: Path | None) -> Path | None:
    """The ``IPTS-*`` folder ``path`` is in (or is), if any."""
    if path is None:
        return None
    for part in (path, *path.parents):
        if _IPTS_RE.match(part.name):
            return part
    return None


def _hits(dirs: Iterable[Path], run: int, prefix: str, workers: int) -> list[Path]:
    def check(ipts: Path) -> list[Path]:
        return [p for p in candidates(ipts, run, prefix) if p.is_file()]

    dirs = list(dirs)
    if len(dirs) <= 2:
        results = [check(d) for d in dirs]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(check, dirs))
    return [p for group in results for p in group]


def find_run(
    run: int,
    *,
    root: Path | None = None,
    prefix: str = DEFAULT_PREFIX,
    near: Path | None = None,
    workers: int = WORKERS,
) -> list[Path]:
    """Every file for ``run`` under ``root/IPTS-*``; the preferred one first.

    ``near`` (e.g. the folder the user is in) and the last hit's IPTS are
    checked before the full scan; a hit there returns at once.
    """
    global _last_hit_ipts
    root = root or search_root()
    hints = [d for d in (ipts_of(near), _last_hit_ipts) if d is not None and d.parent == root]
    quick = _hits(dict.fromkeys(hints), run, prefix, workers)
    hits = quick or _hits(ipts_dirs(root), run, prefix, workers)
    hits.sort(key=lambda p: (p.suffix != ".h5", p))  # current .nxs.h5 layout first
    if hits:
        _last_hit_ipts = ipts_of(hits[0])
    return hits


__all__ = [
    "DEFAULT_ROOT",
    "ROOT_ENV",
    "candidates",
    "find_run",
    "ipts_dirs",
    "ipts_of",
    "parse_run",
]
