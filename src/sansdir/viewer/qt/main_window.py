"""Viewer main window: detector view, status-bar readout, background loading."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QFontDatabase,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QProgressBar,
)

from sansdir.viewer.colorscale import auto_limits, display_levels, display_values
from sansdir.viewer.cube import DEFAULT_NBINS, TofCube
from sansdir.viewer.geometry import PixelInfo
from sansdir.viewer.qt.image_view import DetectorView
from sansdir.viewer.qt.loader import CubeLoader

NEXUS_FILTER = "NeXus files (*.nxs.h5 *.nxs *.h5);;All files (*)"


class MainWindow(QMainWindow):
    def __init__(self, nbins: int = DEFAULT_NBINS) -> None:
        super().__init__()
        self.nbins = nbins
        self.cube: TofCube | None = None
        self._image: np.ndarray | None = None  # counts currently shown
        self._log = True
        self._loader: CubeLoader | None = None
        self._retired: set[CubeLoader] = set()
        self._t_open = 0.0

        self.view = DetectorView()
        self.setCentralWidget(self.view)
        self.view.hovered.connect(self._show_readout)

        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.readout = QLabel()
        self.readout.setFont(mono)
        self.info = QLabel()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setMaximumWidth(160)
        self.progress.hide()
        bar = self.statusBar()
        bar.addWidget(self.readout, 1)
        bar.addPermanentWidget(self.info)
        bar.addPermanentWidget(self.progress)

        self._build_menus()
        self.setAcceptDrops(True)
        self.setWindowTitle("EQSANS detector viewer")
        self.resize(1000, 860)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        open_action = QAction("&Open…", self, shortcut=QKeySequence(QKeySequence.StandardKey.Open))
        open_action.triggered.connect(self._ask_open)
        quit_action = QAction("&Quit", self, shortcut=QKeySequence(QKeySequence.StandardKey.Quit))
        quit_action.triggered.connect(self.close)
        file_menu.addActions([open_action, quit_action])

        view_menu = self.menuBar().addMenu("&View")
        self.log_action = QAction("&Log scale", self, shortcut=QKeySequence("L"), checkable=True)
        self.log_action.setChecked(self._log)
        self.log_action.toggled.connect(self._set_log)
        view_menu.addAction(self.log_action)

    # -- loading -----------------------------------------------------------

    def _ask_open(self) -> None:
        start = str(self.cube.path.parent) if self.cube else ""
        name, _ = QFileDialog.getOpenFileName(self, "Open NeXus file", start, NEXUS_FILTER)
        if name:
            self.open_path(Path(name))

    def open_path(self, path: Path) -> None:
        if self._loader is not None:
            self._loader.stop()
        loader = CubeLoader(path, self.nbins)
        loader.progressed.connect(self._on_progress)
        loader.preview.connect(self._on_preview)
        loader.loaded.connect(self._on_loaded)
        loader.failed.connect(self._on_failed)
        loader.finished.connect(lambda: self._retired.discard(loader))
        self._retired.add(loader)  # keep a reference until the thread ends
        self._loader = loader
        self._t_open = time.perf_counter()
        self.progress.setValue(0)
        self.progress.show()
        self.info.setText(f"loading {path.name}…")
        self.setWindowTitle(f"{path.name} — EQSANS detector viewer")
        loader.start()

    def _is_current(self) -> bool:
        return self.sender() is self._loader

    def _on_progress(self, fraction: float) -> None:
        if self._is_current():
            self.progress.setValue(int(fraction * 1000))

    def _on_preview(self, cube: TofCube) -> None:
        if not self._is_current():
            return
        self._set_cube(cube)
        self.info.setText(
            f"preview from {cube.n_events / cube.total_events:.1%} of "
            f"{cube.total_events / 1e9:.2f} G events (scaled) · loading the full run…"
        )

    def _on_loaded(self, cube: TofCube) -> None:
        if not self._is_current():
            return
        self._loader = None
        self.progress.hide()
        self._set_cube(cube)
        elapsed = time.perf_counter() - self._t_open
        if cube.has_tof:
            self.info.setText(
                f"{_events(cube.n_events)} events · {cube.nbins} TOF bins · loaded in {elapsed:.2f} s"
            )
        else:
            self.info.setText(f"processed file (no TOF) · loaded in {elapsed:.2f} s")

    def _on_failed(self, message: str) -> None:
        if not self._is_current():
            return
        self._loader = None
        self.progress.hide()
        self.info.setText(message.splitlines()[0])
        self.info.setToolTip(message)

    def _set_cube(self, cube: TofCube) -> None:
        new_file = self.cube is None or self.cube.path != cube.path
        self.cube = cube
        self._image = cube.image()
        label = f"run {cube.run_number}" if cube.run_number else cube.path.name
        title = f" — {cube.title}" if cube.title else ""
        self.setWindowTitle(f"{label}{title} — EQSANS detector viewer")
        self._refresh()
        if new_file:
            self.view.fit()

    # -- display -----------------------------------------------------------

    def _set_log(self, log: bool) -> None:
        self._log = log
        self._refresh()

    def _refresh(self) -> None:
        if self._image is None:
            return
        vmin, vmax = auto_limits(self._image, log=self._log)
        self.view.set_values(
            display_values(self._image, log=self._log),
            display_levels(vmin, vmax, log=self._log),
        )

    def _show_readout(self, info: PixelInfo | None) -> None:
        if info is None or self._image is None:
            self.readout.clear()
            return
        counts = float(self._image[info.y, info.x])
        approx = "≈" if self.cube is not None and self.cube.is_preview else ""
        self.readout.setText(
            f"x {info.x:3d}  y {info.y:3d} │ {info.panel} bank{info.bank} "
            f"tube{info.tube} pixel{info.pixel} │ ID {info.detid} · DAS bank{info.das_bank} "
            f"│ {approx}{counts:,.0f} counts"
        )

    # -- Qt plumbing -------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 — Qt override
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 — Qt override
        urls = event.mimeData().urls()
        if urls:
            self.open_path(Path(urls[0].toLocalFile()))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — Qt override
        for loader in list(self._retired):
            loader.stop()
            loader.wait(2000)
        super().closeEvent(event)


def _events(n: int) -> str:
    return f"{n / 1e9:.2f} G" if n >= 1e9 else f"{n / 1e6:.2f} M"


def run(path: Path | None, *, nbins: int = DEFAULT_NBINS, benchmark: bool = False) -> int:
    """Create the application, show the window, start loading ``path``."""
    t0 = time.perf_counter()
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication(sys.argv[:1])
    pg.setConfigOptions(antialias=False)
    win = MainWindow(nbins)
    win.show()
    if benchmark:
        _attach_benchmark(app, win, t0)
    if path is not None:
        QTimer.singleShot(0, lambda: win.open_path(path))
    return int(app.exec())


def _attach_benchmark(app: QApplication, win: MainWindow, t0: float) -> None:
    """``--benchmark``: print milestones to stderr, quit after the full load."""

    def mark(what: str) -> None:
        print(f"{time.perf_counter() - t0:7.2f} s  {what}", file=sys.stderr, flush=True)

    mark("window shown")
    original_open = win.open_path

    def open_and_hook(path: Path) -> None:
        original_open(path)
        loader = win._loader
        if loader is None:
            return
        loader.preview.connect(
            lambda _c: QTimer.singleShot(0, lambda: mark("preview image on screen"))
        )

        def done(_c: TofCube) -> None:
            def finish() -> None:
                mark("full image on screen")
                app.quit()

            QTimer.singleShot(0, finish)

        loader.loaded.connect(done)

        def failed(message: str) -> None:
            mark(f"failed: {message}")
            app.quit()

        loader.failed.connect(failed)

    win.open_path = open_and_hook  # type: ignore[method-assign]
