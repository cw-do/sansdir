"""Cumulative TOF histogram (the viewer's data model).

Loading reads each ``/entry/bank<N>_events`` group's ``event_id`` and
``event_time_offset`` in fixed-size chunks and histograms them onto a
fine TOF grid with one vectorised ``bincount`` per chunk. The result is
stored as a **cumulative** sum over TOF, shape ``(nbins + 1, NPIX)`` with
row 0 all zeros, so the counts for any TOF range ``[a, b)`` are one
subtraction of two contiguous rows (well under 1 ms) — the TOF slider
never has to touch the events again.

Big runs
--------

EQSANS runs reach billions of events (7.7e9 / 60 GB seen in
IPTS-37618). One process reads ~75 M events/s and histograms ~90 M/s,
so a full load is minutes. Measured on GPFS (2026-10-21) the aggregate
rate levels off at ~210 M events/s with 8-16 reader processes, so above
:data:`PARALLEL_MIN_EVENTS`:

1. a **preview** histograms an evenly spaced sample of every bank (the
   same fraction of each, spread over the whole run) and is scaled up by
   ``1 / fraction``; it is handed to ``on_preview`` as soon as it is done;
2. the **full** load runs as bank slices and replaces the preview.

Both run in one spawn-context process pool, preview tasks queued first.
The preview is bound by GPFS seek latency (~5-10 ms per scattered
slice), not bandwidth, so it is spread over the workers and each bank's
slices share one task (one file open).

Small runs take the in-process path, so no pool start-up cost.

TOF grid
--------

The TOF range is fixed before the data are read: 1.1x the frame period
from the DAS ``BL6:Det:TH:BL:Frequency`` log (60 Hz → 16.7 ms, 30 Hz →
33.3 ms). Real files carry a few events slightly past one period
(17.3 ms seen at 60 Hz), hence the margin; anything beyond it lands in
the last bin and is counted in :attr:`TofCube.overflow`. Trailing empty
bins are trimmed after loading.

Processed (Mantid / drtsans) files have no events. They load through
:func:`sansdir.plot.hdf5_detector.load_processed` into a one-bin cube
with ``tof_edges = None``.

Qt-free: the viewer's ``QThread`` calls :func:`load_cube`.
"""

from __future__ import annotations

import contextlib
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from sansdir.hdf.reader import HdfError, open_nexus
from sansdir.viewer.geometry import NPIX, PIXELS_PER_BLOCK, to_flat, to_image

if TYPE_CHECKING:
    import h5py

DEFAULT_NBINS: int = 500
CHUNK_EVENTS: int = 4_000_000
SLICE_EVENTS: int = 50_000_000  # one pool task
PARALLEL_MIN_EVENTS: int = 100_000_000
PREVIEW_EVENTS: int = 20_000_000
PREVIEW_SLICES_PER_BANK: int = 8
MAX_WORKERS: int = 12  # aggregate GPFS rate is flat past ~8-16 readers
FRAME_MARGIN: float = 1.1
FALLBACK_FREQUENCY_HZ: float = 30.0  # the longer frame — never truncates a 60 Hz run
FREQUENCY_LOGS: tuple[str, ...] = (
    "entry/DASlogs/BL6:Det:TH:BL:Frequency/value",
    "entry/DASlogs/Speed1/value",
)
_BANK_RE = re.compile(r"^bank(\d+)_events$")

# progress(stage, events done, events in the file). Stages, in order:
# STAGE_PREVIEW (big runs only; no count, done = 0) then STAGE_LOADING.
Progress = Callable[[str, int, int], None]
STAGE_PREVIEW: str = "preview"
STAGE_LOADING: str = "loading"


class LoadCancelledError(RuntimeError):
    """Raised when ``should_stop()`` turns true part-way through a load."""


@dataclass
class TofCube:
    """Per-detector counts, cumulative over TOF."""

    path: Path
    run_number: str
    title: str
    source: str  # "raw" | "processed"
    cum: np.ndarray  # (nbins + 1, NPIX), row 0 = 0
    tof_edges: np.ndarray | None  # (nbins + 1,) µs; None when there is no TOF
    n_events: int = 0  # events actually histogrammed
    total_events: int = 0  # events in the file
    scale: float = 1.0  # > 1 for a sampled preview
    overflow: int = 0
    timings: dict[str, float] = field(default_factory=dict)
    _spectrum: np.ndarray | None = field(default=None, repr=False)

    @property
    def has_tof(self) -> bool:
        return self.tof_edges is not None

    @property
    def is_preview(self) -> bool:
        return self.scale != 1.0

    @property
    def nbins(self) -> int:
        return int(self.cum.shape[0] - 1)

    def _range(self, a: int, b: int | None) -> tuple[int, int]:
        b = self.nbins if b is None else b
        a = min(max(a, 0), self.nbins)
        b = min(max(b, a), self.nbins)
        return a, b

    def counts(self, a: int = 0, b: int | None = None) -> np.ndarray:
        """Per-detector-ID counts ``(NPIX,)`` in TOF bins ``[a, b)``."""
        a, b = self._range(a, b)
        diff: np.ndarray = self.cum[b] - self.cum[a]
        return diff if self.scale == 1.0 else diff * self.scale

    def image(self, a: int = 0, b: int | None = None) -> np.ndarray:
        """Display image ``(256, 192)`` for TOF bins ``[a, b)``."""
        return to_image(self.counts(a, b))

    def spectrum(self) -> np.ndarray:
        """Whole-detector counts per TOF bin ``(nbins,)``; cached."""
        if self._spectrum is None:
            self._spectrum = np.diff(self.cum.sum(axis=1, dtype=np.int64))
        return self._spectrum if self.scale == 1.0 else self._spectrum * self.scale


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def load_cube(
    path: Path | str,
    *,
    nbins: int = DEFAULT_NBINS,
    progress: Progress | None = None,
    should_stop: Callable[[], bool] | None = None,
    on_preview: Callable[[TofCube], None] | None = None,
    workers: int | None = None,
) -> TofCube:
    """Raw event file → TOF cube; processed file → one-bin cube."""
    path = Path(path)
    try:
        return load_raw(
            path,
            nbins=nbins,
            progress=progress,
            should_stop=should_stop,
            on_preview=on_preview,
            workers=workers,
        )
    except HdfError as raw_err:
        try:
            return load_processed(path)
        except HdfError as proc_err:
            raise HdfError(
                f"{path}: not a recognised EQSANS NeXus shape\n"
                f"  raw: {raw_err}\n  processed: {proc_err}"
            ) from raw_err


@dataclass(frozen=True, slots=True)
class _Task:
    """Event slices of one bank; picklable for the pool."""

    path: str
    group: str
    block: int  # detector-ID block the bank should hold (bank<N> → N-1)
    ranges: tuple[tuple[int, int], ...]  # [start, stop) event slices
    nbins: int
    scale: float  # bins per µs
    chunk: int

    @property
    def n_events(self) -> int:
        return sum(stop - start for start, stop in self.ranges)


@dataclass(slots=True)
class _Partial:
    block: int
    hist: np.ndarray  # (nbins, PIXELS_PER_BLOCK) int32
    spectrum: np.ndarray  # (nbins,) int64
    n: int
    overflow: int
    stray_index: np.ndarray  # flat bin*NPIX + id for IDs outside the block
    stray_counts: np.ndarray


def load_raw(
    path: Path | str,
    *,
    nbins: int = DEFAULT_NBINS,
    progress: Progress | None = None,
    should_stop: Callable[[], bool] | None = None,
    on_preview: Callable[[TofCube], None] | None = None,
    workers: int | None = None,
    chunk: int = CHUNK_EVENTS,
) -> TofCube:
    """Histogram a raw event-mode file. Raises :class:`HdfError` if not raw.

    ``workers=1`` forces the in-process path; ``None`` picks the pool
    for runs above :data:`PARALLEL_MIN_EVENTS`.
    """
    from sansdir.plot.hdf5_detector import _scalar

    path = Path(path)
    t0 = time.perf_counter()
    with open_nexus(path) as fh:
        entry = fh.get("entry")
        banks: list[tuple[int, str, int]] = []
        for name in entry.keys() if entry is not None else ():
            m = _BANK_RE.match(name)
            group = entry[name]
            if m and "event_id" in group and "event_time_offset" in group:
                banks.append((int(m.group(1)), name, int(group["event_id"].shape[0])))
        if not banks:
            raise HdfError(f"{path}: no /entry/bank<N>_events groups (not raw EQSANS)")
        banks.sort()
        run_number = _scalar(fh, "entry/run_number")
        title = _scalar(fh, "entry/title")
        tof_max = FRAME_MARGIN * 1e6 / _frequency_hz(fh)
    total = sum(n for _, _, n in banks)
    scale = nbins / tof_max

    def task(number: int, group: str, ranges: list[tuple[int, int]]) -> _Task:
        return _Task(str(path), group, number - 1, tuple(ranges), nbins, scale, chunk)

    full = [
        task(number, group, [(s, min(s + SLICE_EVENTS, n))])
        for number, group, n in banks
        for s in range(0, n, SLICE_EVENTS)
    ]

    def finish(acc: _Accumulator, fraction: float) -> TofCube:
        cube = acc.finish(tof_max)
        cube.path, cube.run_number, cube.title = path, run_number, title
        cube.total_events = total
        if fraction < 1.0 and cube.n_events:
            cube.scale = total / cube.n_events
        cube.timings["total"] = time.perf_counter() - t0
        return cube

    stop = should_stop or (lambda: False)
    n_workers = workers if workers is not None else min(MAX_WORKERS, os.cpu_count() or 1)
    acc = _Accumulator(nbins)
    report = progress or (lambda _stage, _done, _total: None)
    if total < PARALLEL_MIN_EVENTS or n_workers <= 1:
        done = 0
        report(STAGE_LOADING, 0, total)
        with open_nexus(path) as fh:  # one open for all banks
            for t in full:
                if stop():
                    raise LoadCancelledError(str(path))
                acc.add(_run_task(t, stop, fh))
                done += t.n_events
                report(STAGE_LOADING, done, total)
        return finish(acc, 1.0)

    import multiprocessing as mp
    from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

    # spawn, not fork: the caller is a Qt process with live threads.
    pool = ProcessPoolExecutor(n_workers, mp_context=mp.get_context("spawn"))
    try:
        preview_futures = []
        if on_preview is not None:
            # The same fraction of every bank, in slices spread over the
            # whole run, so one scale factor fixes up the whole image.
            fraction = PREVIEW_EVENTS / total
            for number, group, n in banks:
                width = max(1, int(n * fraction / PREVIEW_SLICES_PER_BANK))
                starts = np.linspace(0, max(n - width, 0), PREVIEW_SLICES_PER_BANK).astype(int)
                ranges = sorted({(int(s), min(int(s) + width, n)) for s in starts})
                preview_futures.append(pool.submit(_run_task, task(number, group, ranges)))
        futures = {pool.submit(_run_task, t): t for t in full}  # queued behind the preview
        if on_preview is not None and preview_futures:
            report(STAGE_PREVIEW, 0, total)
            preview = _Accumulator(nbins)
            for fut in preview_futures:
                while not fut.done():
                    if stop():
                        raise LoadCancelledError(str(path))
                    wait([fut], timeout=0.2)
                preview.add(fut.result())
            on_preview(finish(preview, fraction))
            del preview
        # Merge each slice as it lands: holding all ~200 partials (2 MB each)
        # until the end doubled peak memory on a 7.7e9-event run.
        done = 0
        report(STAGE_LOADING, 0, total)
        pending = set(futures)
        while pending:
            if stop():
                raise LoadCancelledError(str(path))
            finished, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
            for fut in finished:
                acc.add(fut.result())
                done += futures.pop(fut).n_events
            if finished:
                report(STAGE_LOADING, done, total)
        return finish(acc, 1.0)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------


def _run_task(
    t: _Task,
    should_stop: Callable[[], bool] | None = None,
    fh: h5py.File | None = None,  # reuse an open file; None opens t.path
) -> _Partial:
    """Histogram one bank slice. Runs in-process or in a pool worker."""
    lo = t.block * PIXELS_PER_BLOCK
    hist = np.zeros((t.nbins, PIXELS_PER_BLOCK), dtype=np.int32)
    spectrum = np.zeros(t.nbins, dtype=np.int64)
    n = overflow = 0
    strays: list[np.ndarray] = []
    opened = contextlib.nullcontext(fh) if fh is not None else open_nexus(Path(t.path))
    with opened as handle:
        group = handle["entry"][t.group]
        ids_ds, tof_ds = group["event_id"], group["event_time_offset"]
        for start, end in _chunks(t.ranges, t.chunk):
            if should_stop is not None and should_stop():
                raise LoadCancelledError(t.path)
            ids = np.asarray(ids_ds[start:end], dtype=np.int64)
            tof = np.asarray(tof_ds[start:end])
            bins = (np.maximum(tof, 0) * t.scale).astype(np.int64)
            overflow += int(np.count_nonzero(bins >= t.nbins))
            np.minimum(bins, t.nbins - 1, out=bins)
            local = ids - lo
            inside = (local >= 0) & (local < PIXELS_PER_BLOCK)
            if not inside.all():
                # IDs outside the bank's own block: never seen in real
                # files, but kept (sparse) rather than silently dropped.
                stray = ~inside & (ids >= 0) & (ids < NPIX)
                strays.append(bins[stray] * NPIX + ids[stray])
                spectrum += np.bincount(bins[stray], minlength=t.nbins)
                n += int(np.count_nonzero(stray))
                bins, local = bins[inside], local[inside]
            counts = np.bincount(bins * PIXELS_PER_BLOCK + local, minlength=hist.size)
            np.add(hist, counts.reshape(hist.shape), out=hist, casting="unsafe")
            spectrum += np.bincount(bins, minlength=t.nbins)
            n += int(bins.size)
    if strays:
        stray_index, stray_counts = np.unique(np.concatenate(strays), return_counts=True)
    else:
        stray_index = stray_counts = np.zeros(0, dtype=np.int64)
    return _Partial(t.block, hist, spectrum, n, overflow, stray_index, stray_counts)


def _chunks(ranges: tuple[tuple[int, int], ...], chunk: int) -> list[tuple[int, int]]:
    return [(s, min(s + chunk, stop)) for start, stop in ranges for s in range(start, stop, chunk)]


class _Accumulator:
    """Merges :class:`_Partial` histograms into one trimmed cumulative cube."""

    def __init__(self, nbins: int) -> None:
        self.nbins = nbins
        self.cum = np.zeros((nbins + 1, NPIX), dtype=np.int32)
        self.spectrum = np.zeros(nbins, dtype=np.int64)
        self.n_events = 0
        self.overflow = 0

    def add(self, p: _Partial) -> None:
        hist = self.cum[1:]
        lo = p.block * PIXELS_PER_BLOCK
        cols = hist[:, lo : lo + PIXELS_PER_BLOCK]
        np.add(cols, p.hist, out=cols, casting="unsafe")
        if p.stray_index.size:
            np.add.at(hist.reshape(-1), p.stray_index, p.stray_counts.astype(np.int32))
        self.spectrum += p.spectrum
        self.n_events += p.n
        self.overflow += p.overflow

    def finish(self, tof_max: float) -> TofCube:
        """Running sum over TOF, then trim; the accumulator is spent after this."""
        hist = self.cum[1:]
        # Row-by-row running sum: ``np.cumsum(..., out=hist)`` copies the whole
        # array first because input and output overlap (~0.4 s); this is ~10 ms.
        for k in range(1, self.nbins):
            np.add(hist[k], hist[k - 1], out=hist[k])
        # Trim trailing empty bins so the slider spans only real data. A view,
        # not a copy: the trimmed tail is ~10 % and not worth a 100 MB copy.
        nonzero = np.flatnonzero(self.spectrum)
        keep = (int(nonzero[-1]) + 1 if nonzero.size else 1) + 1
        return TofCube(
            path=Path(),
            run_number="",
            title="",
            source="raw",
            cum=self.cum[:keep],
            tof_edges=np.linspace(0.0, tof_max, self.nbins + 1)[:keep],
            n_events=self.n_events,
            overflow=self.overflow,
            _spectrum=self.spectrum[: keep - 1],
        )


def _frequency_hz(fh) -> float:  # type: ignore[no-untyped-def]
    """Frame frequency from the DAS logs; the 30 Hz fallback never truncates."""
    for key in FREQUENCY_LOGS:
        if key in fh:
            values = np.asarray(fh[key][()], dtype=float).ravel()
            values = values[np.isfinite(values) & (values > 1.0)]
            if values.size:
                return float(np.median(values))
    return FALLBACK_FREQUENCY_HZ


# ---------------------------------------------------------------------------
# Processed files
# ---------------------------------------------------------------------------


def load_processed(path: Path | str) -> TofCube:
    """Mantid / drtsans processed file → one-bin cube (no TOF axis)."""
    from sansdir.plot.hdf5_detector import load_processed as _load_processed_image

    path = Path(path)
    t0 = time.perf_counter()
    img = _load_processed_image(path)
    cum = np.zeros((2, NPIX), dtype=np.float64)
    cum[1] = to_flat(np.asarray(img.image, dtype=np.float64))
    return TofCube(
        path=path,
        run_number=img.run_number,
        title=img.title,
        source="processed",
        cum=cum,
        tof_edges=None,
        timings={"total": time.perf_counter() - t0},
    )


__all__ = [
    "DEFAULT_NBINS",
    "STAGE_LOADING",
    "STAGE_PREVIEW",
    "LoadCancelledError",
    "TofCube",
    "load_cube",
    "load_processed",
    "load_raw",
]
