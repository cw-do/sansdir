"""Background work off the UI thread: loading a run (cache → :func:`load_cube` → cache), saving a mask."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from sansdir.viewer.cache import CubeCache
from sansdir.viewer.cube import DEFAULT_NBINS, LoadCancelledError, load_cube
from sansdir.viewer.masking import MaskState, save_mask

# Stages reported on top of cube.STAGE_PREVIEW / STAGE_LOADING.
STAGE_CACHE_READ = "cache-read"
STAGE_CACHE_WRITE = "cache-write"


class CubeLoader(QThread):
    """Loads one file.

    Emits ``progressed(stage, done, total)`` throughout, ``preview`` (big
    runs only) with a sampled, scaled cube, then ``loaded`` or
    ``failed``; after ``loaded`` it may still save to the cache, so the
    load is over only at ``finished``. Event counts travel as floats:
    Qt's ``int`` is 32-bit and runs exceed 2**31 events.
    """

    progressed = Signal(str, float, float)
    preview = Signal(object)  # TofCube
    loaded = Signal(object)  # TofCube
    failed = Signal(str)
    note = Signal(str)  # non-fatal: cache trouble

    def __init__(
        self, path: Path, nbins: int = DEFAULT_NBINS, cache: CubeCache | None = None
    ) -> None:
        super().__init__()
        self.path = path
        self.nbins = nbins
        self.cache = cache
        self._stop = False

    def stop(self) -> None:
        """Ask the load to give up at the next chunk boundary."""
        self._stop = True

    def _report(self, stage: str, done: int, total: int) -> None:
        self.progressed.emit(stage, float(done), float(total))

    def run(self) -> None:
        if self.cache is not None:
            self._report(STAGE_CACHE_READ, 0, 0)
            try:
                cached = self.cache.get(self.path, self.nbins)
            except Exception:  # a broken cache must never block a load
                cached = None
            if cached is not None:
                if not self._stop:
                    self.loaded.emit(cached)
                return
        try:
            cube = load_cube(
                self.path,
                nbins=self.nbins,
                progress=self._report,
                should_stop=lambda: self._stop,
                on_preview=self.preview.emit,
            )
        except LoadCancelledError:
            return
        except Exception as exc:  # surfaced in the status bar, never a traceback
            self.failed.emit(f"{self.path.name}: {exc}")
            return
        if self._stop:
            return
        self.loaded.emit(cube)
        if self.cache is not None and self.cache.should_store(cube):
            self._report(STAGE_CACHE_WRITE, 0, 0)
            try:
                self.cache.put(cube, self.nbins)
            except OSError as exc:
                self.note.emit(f"not cached: {exc}")


class MaskSaver(QThread):
    """Saves a mask off the UI thread: ``.nxs`` goes through Mantid (8-15 s)."""

    saved = Signal(object)  # SavedMask
    failed = Signal(str)

    def __init__(self, state: MaskState, source: Path, run_number: str, output: Path) -> None:
        super().__init__()
        self.state = state
        self.source = source
        self.run_number = run_number
        self.output = output

    def run(self) -> None:
        try:
            result = save_mask(self.state, self.source, self.run_number, self.output)
        except Exception as exc:  # surfaced in a message box, never a traceback
            self.failed.emit(f"{self.output.name}: {exc}")
            return
        self.saved.emit(result)
