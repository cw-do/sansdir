"""On-disk cache of loaded TOF cubes (Phase 9.10.5, done early).

A 7.7e9-event run takes about a minute to histogram; the result is
~90 MB, and reading it back takes well under a second. So every load that
took at least :data:`MIN_LOAD_SECONDS` is saved under
``~/.cache/sansdir/viewer/`` (``$SANSDIR_CACHE_DIR`` honoured), and the
next open of the same file reads that instead.

Each entry is two files sharing a stem, ``<run file stem>_<key>``:

* ``.npy`` — the cumulative ``(nbins + 1, NPIX)`` int32 array;
* ``.json`` — run metadata, TOF edges and spectrum. Written **last**, so
  an entry only counts once both halves are complete; a crash mid-write
  leaves a stray ``.npy`` that eviction removes.

The key hashes the resolved path, file size, mtime (ns), requested bin
count and :data:`FORMAT_VERSION`, so a file that is still being written
(live run) or has been replaced is simply a miss. Entries are
least-recently-used: a hit touches them, and :meth:`CubeCache.put` evicts
the oldest until the directory is under its size cap.

Qt-free.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from sansdir.core.history import default_history_path
from sansdir.viewer.cube import TofCube

FORMAT_VERSION: int = 1
MIN_LOAD_SECONDS: float = 2.0  # faster loads are not worth the disk space
MAX_BYTES: int = 5 * 1024**3
STALE_SECONDS: float = 3600.0  # a half-written entry older than this is abandoned


def default_cache_dir() -> Path:
    """``~/.cache/sansdir/viewer`` (honours ``$SANSDIR_CACHE_DIR``)."""
    return default_history_path().parent / "viewer"


@dataclass
class CubeCache:
    directory: Path
    max_bytes: int = MAX_BYTES
    min_load_seconds: float = MIN_LOAD_SECONDS

    @classmethod
    def default(cls) -> CubeCache:
        return cls(default_cache_dir())

    # -- keys ----------------------------------------------------------------

    def _stem(self, source: Path, nbins: int) -> str | None:
        try:
            resolved = source.resolve()
            st = resolved.stat()
        except OSError:
            return None
        ident = f"{resolved}|{st.st_size}|{st.st_mtime_ns}|{nbins}|v{FORMAT_VERSION}"
        key = hashlib.sha1(ident.encode()).hexdigest()[:16]
        name = resolved.name.split(".")[0]
        return f"{name}_{key}"

    # -- read ----------------------------------------------------------------

    def get(self, source: Path, nbins: int) -> TofCube | None:
        """The cached cube for ``source`` as it is on disk now, or ``None``."""
        t0 = time.perf_counter()
        stem = self._stem(source, nbins)
        if stem is None:
            return None
        meta_path = self.directory / f"{stem}.json"
        data_path = self.directory / f"{stem}.npy"
        if not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text())
            cum = np.load(data_path)
            edges = np.asarray(meta["tof_edges"], dtype=np.float64)
            spectrum = np.asarray(meta["spectrum"], dtype=np.int64)
            if cum.shape != (edges.size, int(meta["npix"])) or spectrum.size != edges.size - 1:
                raise ValueError(f"inconsistent cache entry {stem}")
        except (OSError, ValueError, KeyError, TypeError):
            self._remove(stem)
            return None
        now = time.time()
        for p in (meta_path, data_path):
            with contextlib.suppress(OSError):
                os.utime(p, (now, now))  # least-recently-used bookkeeping
        return TofCube(
            path=source,
            run_number=str(meta.get("run_number", "")),
            title=str(meta.get("title", "")),
            source="raw",
            cum=cum,
            tof_edges=edges,
            n_events=int(meta["n_events"]),
            total_events=int(meta["total_events"]),
            overflow=int(meta.get("overflow", 0)),
            timings={"cache_read": time.perf_counter() - t0},
            _spectrum=spectrum,
        )

    # -- write ---------------------------------------------------------------

    def should_store(self, cube: TofCube) -> bool:
        """Only complete raw loads that were slow enough to be worth it."""
        return (
            cube.source == "raw"
            and not cube.is_preview
            and cube.tof_edges is not None
            and "cache_read" not in cube.timings
            and cube.timings.get("total", 0.0) >= self.min_load_seconds
        )

    def put(self, cube: TofCube, nbins: int) -> Path | None:
        """Save ``cube`` (loaded with ``nbins``); returns the ``.npy`` path.

        Raises ``OSError`` if the directory is not writable or full.
        """
        stem = self._stem(cube.path, nbins)
        if stem is None or cube.tof_edges is None:
            return None
        self.directory.mkdir(parents=True, exist_ok=True)
        data_path = self.directory / f"{stem}.npy"
        meta_path = self.directory / f"{stem}.json"
        tag = f".{os.getpid()}.tmp"
        meta = {
            "format": FORMAT_VERSION,
            "source": str(cube.path.resolve()),
            "run_number": cube.run_number,
            "title": cube.title,
            "n_events": cube.n_events,
            "total_events": cube.total_events,
            "overflow": cube.overflow,
            "npix": int(cube.cum.shape[1]),
            "tof_edges": [float(x) for x in cube.tof_edges],
            "spectrum": [int(x) for x in cube.spectrum()],
            "load_seconds": cube.timings.get("total", 0.0),
            "created": time.time(),
        }
        tmp_data = data_path.with_name(data_path.name + tag)
        tmp_meta = meta_path.with_name(meta_path.name + tag)
        try:
            with open(tmp_data, "wb") as fh:
                np.save(fh, np.ascontiguousarray(cube.cum))
            tmp_meta.write_text(json.dumps(meta))
            os.replace(tmp_data, data_path)
            os.replace(tmp_meta, meta_path)  # the entry exists from here on
        finally:
            for p in (tmp_data, tmp_meta):
                p.unlink(missing_ok=True)
        self.evict(keep=stem)
        return data_path

    # -- housekeeping --------------------------------------------------------

    def entries(self) -> list[tuple[float, int, str]]:
        """``(last used, bytes, stem)`` per entry, oldest first (complete or not)."""
        if not self.directory.is_dir():
            return []
        stems: dict[str, list[os.stat_result]] = {}
        for p in self.directory.iterdir():
            try:
                st = p.stat()
            except OSError:
                continue
            if p.suffix in (".npy", ".json"):
                stems.setdefault(p.stem, []).append(st)
            elif p.suffix == ".tmp" and time.time() - st.st_mtime > STALE_SECONDS:
                p.unlink(missing_ok=True)  # left by a crashed writer
        return sorted(
            (max(s.st_mtime for s in stats), sum(s.st_size for s in stats), stem)
            for stem, stats in stems.items()
        )

    def evict(self, keep: str | None = None) -> None:
        """Drop orphaned halves, then the oldest entries until under the cap."""
        now = time.time()
        entries = []
        for used, size, stem in self.entries():
            complete = (self.directory / f"{stem}.json").exists()
            # Another viewer may be between its two renames: give it time.
            if not complete and stem != keep and now - used > STALE_SECONDS:
                self._remove(stem)
            else:
                entries.append((used, size, stem))
        total = sum(size for _, size, _ in entries)
        for _, size, stem in entries:
            if total <= self.max_bytes:
                break
            if stem != keep:
                self._remove(stem)
                total -= size

    def _remove(self, stem: str) -> None:
        for suffix in (".json", ".npy"):  # json first: the entry stops counting
            (self.directory / f"{stem}{suffix}").unlink(missing_ok=True)


__all__ = ["CubeCache", "default_cache_dir"]
