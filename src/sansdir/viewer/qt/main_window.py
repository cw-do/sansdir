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
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
)

from sansdir.viewer.cache import CubeCache, describe
from sansdir.viewer.colorscale import auto_limits, display_levels, display_values
from sansdir.viewer.cube import DEFAULT_NBINS, TofCube
from sansdir.viewer.geometry import PixelInfo
from sansdir.viewer.qt.image_view import DetectorView
from sansdir.viewer.qt.loader import CubeLoader
from sansdir.viewer.qt.progress import LoadProgress, format_count

NEXUS_FILTER = "NeXus files (*.nxs.h5 *.nxs *.h5);;All files (*)"


class MainWindow(QMainWindow):
    def __init__(self, nbins: int = DEFAULT_NBINS, cache: CubeCache | None = None) -> None:
        super().__init__()
        self.nbins = nbins
        self.cache = cache
        self.cube: TofCube | None = None
        self._image: np.ndarray | None = None  # counts currently shown
        self._log = True
        self._loader: CubeLoader | None = None
        self._retired: set[CubeLoader] = set()
        self._t_open = 0.0
        self._title = "EQSANS detector viewer"

        self.view = DetectorView()
        self.setCentralWidget(self.view)
        self.view.hovered.connect(self._show_readout)

        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.readout = QLabel()
        self.readout.setFont(mono)
        self.info = QLabel()
        self.loading = LoadProgress()
        self.loading.cancel_requested.connect(self.cancel_load)
        bar = self.statusBar()
        bar.addWidget(self.readout, 1)
        bar.addPermanentWidget(self.info)
        bar.addPermanentWidget(self.loading)
        QShortcut(QKeySequence("Esc"), self, self.cancel_load)

        self._build_menus()
        self.setAcceptDrops(True)
        self._update_title()
        self.resize(1000, 860)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        open_action = QAction("&Open…", self, shortcut=QKeySequence(QKeySequence.StandardKey.Open))
        open_action.triggered.connect(self._ask_open)
        quit_action = QAction("&Quit", self, shortcut=QKeySequence(QKeySequence.StandardKey.Quit))
        quit_action.triggered.connect(self.close)
        self.clear_cache_action = QAction("Clear viewer &cache…", self)
        self.clear_cache_action.triggered.connect(self.clear_cache)
        if self.cache is None:
            self.clear_cache_action.setEnabled(False)
            self.clear_cache_action.setToolTip("started with --no-cache")
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        file_menu.addAction(self.clear_cache_action)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)

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
        loader = CubeLoader(path, self.nbins, self.cache)
        loader.progressed.connect(self._on_progress)
        loader.preview.connect(self._on_preview)
        loader.loaded.connect(self._on_loaded)
        loader.failed.connect(self._on_failed)
        loader.note.connect(self._on_note)
        loader.finished.connect(self._on_finished)
        self._retired.add(loader)  # keep a reference until the thread ends
        self._loader = loader
        self._t_open = time.perf_counter()
        self.loading.start(path.name)
        self.info.setText("")
        self.info.setToolTip("")
        self._title = f"{path.name} — EQSANS detector viewer"
        self._update_title()
        loader.start()

    def clear_cache(self) -> None:
        """File → Clear viewer cache…: show the size, confirm, delete."""
        if self.cache is None:
            return
        runs, size = self.cache.summary()
        if size == 0:
            QMessageBox.information(self, "Viewer cache", "The viewer cache is already empty.")
            return
        answer = QMessageBox.question(
            self,
            "Clear viewer cache",
            f"Delete the cached histograms ({describe(runs, size)}) in\n"
            f"{self.cache.directory}?\n\n"
            "Big runs will take their full load time again the next time they are "
            "opened. The run on screen is not affected.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        runs, size = self.cache.clear()
        self.info.setText(f"cache cleared: {describe(runs, size)}")

    def cancel_load(self) -> None:
        """Stop the current load (Cancel button / Esc); a preview stays up."""
        loader = self._loader
        if loader is None:
            return
        loader.stop()
        self._loader = None  # ignore anything it still emits
        self.loading.finish()
        if self.cube is not None and self.cube.is_preview:
            self.info.setText("cancelled — showing the preview only (counts are estimates)")
        else:
            self.info.setText("loading cancelled")
        self._update_title()

    def _is_current(self) -> bool:
        return self._loader is not None and self.sender() is self._loader

    def _on_progress(self, stage: str, done: float, total: float) -> None:
        if self._is_current():
            self.loading.update_stage(stage, done, total)
            self._update_title()

    def _on_preview(self, cube: TofCube) -> None:
        if not self._is_current():
            return
        self._set_cube(cube)
        self.info.setText(
            f"PREVIEW from {cube.n_events / cube.total_events:.1%} of the events, scaled"
        )

    def _on_loaded(self, cube: TofCube) -> None:
        if not self._is_current():
            return
        self._set_cube(cube)
        elapsed = time.perf_counter() - self._t_open
        if "cache_read" in cube.timings:
            how = f"from cache in {elapsed:.2f} s"
        else:
            how = f"in {elapsed:.2f} s"
        if cube.has_tof:
            self.info.setText(
                f"{format_count(cube.n_events)} events · {cube.nbins} TOF bins · {how}"
            )
        else:
            self.info.setText(f"processed file (no TOF) · {how}")

    def _on_failed(self, message: str) -> None:
        if not self._is_current():
            return
        self.info.setText(message.splitlines()[0])
        self.info.setToolTip(message)

    def _on_note(self, message: str) -> None:
        if self._is_current():
            self.info.setToolTip(message)

    def _on_finished(self) -> None:
        loader = self.sender()
        self._retired.discard(loader)
        if loader is self._loader:
            self._loader = None
            self.loading.finish()
            self._update_title()

    def _update_title(self) -> None:
        percent = self.loading.percent
        prefix = f"[{percent}%] " if percent is not None and self._loader is not None else ""
        self.setWindowTitle(prefix + self._title)

    def _set_cube(self, cube: TofCube) -> None:
        new_file = self.cube is None or self.cube.path != cube.path
        self.cube = cube
        self._image = cube.image()
        label = f"run {cube.run_number}" if cube.run_number else cube.path.name
        title = f" — {cube.title}" if cube.title else ""
        self._title = f"{label}{title} — EQSANS detector viewer"
        self._update_title()
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
        # A load stops within ~0.2 s; a cache write in progress (~1 s) is
        # left to finish so it is not torn.
        for loader in list(self._retired):
            loader.stop()
            loader.wait(15_000)
        super().closeEvent(event)


def run(
    path: Path | None,
    *,
    nbins: int = DEFAULT_NBINS,
    use_cache: bool = True,
    benchmark: bool = False,
) -> int:
    """Create the application, show the window, start loading ``path``."""
    t0 = time.perf_counter()
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication(sys.argv[:1])
    pg.setConfigOptions(antialias=False)
    win = MainWindow(nbins, CubeCache.default() if use_cache else None)
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

        loader.loaded.connect(lambda _c: QTimer.singleShot(0, lambda: mark("full image on screen")))

        def done() -> None:
            mark("loader finished (cache written if any)")
            app.quit()

        loader.finished.connect(done)

        def failed(message: str) -> None:
            mark(f"failed: {message}")
            app.quit()

        loader.failed.connect(failed)

    win.open_path = open_and_hook  # type: ignore[method-assign]
