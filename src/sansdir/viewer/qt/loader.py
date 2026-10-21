"""Background loading: run :func:`sansdir.viewer.cube.load_cube` off the UI thread."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from sansdir.viewer.cube import DEFAULT_NBINS, LoadCancelledError, load_cube


class CubeLoader(QThread):
    """Loads one file.

    Emits ``preview`` (big runs only) with a sampled, scaled cube,
    ``progressed`` with the fraction of events done, then ``loaded`` or
    ``failed``. Floats, not ints, for progress: Qt's ``int`` is 32-bit
    and runs exceed 2**31 events.
    """

    progressed = Signal(float)
    preview = Signal(object)  # TofCube
    loaded = Signal(object)  # TofCube
    failed = Signal(str)

    def __init__(self, path: Path, nbins: int = DEFAULT_NBINS) -> None:
        super().__init__()
        self.path = path
        self.nbins = nbins
        self._stop = False

    def stop(self) -> None:
        """Ask the load to give up at the next chunk boundary."""
        self._stop = True

    def run(self) -> None:
        try:
            cube = load_cube(
                self.path,
                nbins=self.nbins,
                progress=self.progressed.emit,
                should_stop=lambda: self._stop,
                on_preview=self.preview.emit,
            )
        except LoadCancelledError:
            return
        except Exception as exc:  # surfaced in the status bar, never a traceback
            self.failed.emit(f"{self.path.name}: {exc}")
            return
        if not self._stop:
            self.loaded.emit(cube)
