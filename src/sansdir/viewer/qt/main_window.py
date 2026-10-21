"""Viewer main window: detector view, colour-scale panel, TOF panel, readout, loading."""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QSettings, QSignalBlocker, Qt, QTimer, Signal
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
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QWidget,
)

from sansdir.viewer.cache import CubeCache, describe
from sansdir.viewer.colorscale import (
    COLORMAPS,
    ScaleState,
    counts_from_levels,
    display_levels,
    display_values,
)
from sansdir.viewer.cube import DEFAULT_NBINS, TofCube
from sansdir.viewer.geometry import PixelInfo
from sansdir.viewer.qt.image_view import DetectorView
from sansdir.viewer.qt.loader import CubeLoader
from sansdir.viewer.qt.progress import LoadProgress, format_count
from sansdir.viewer.qt.scale_panel import ScalePanel
from sansdir.viewer.qt.tof_panel import TofPanel

NEXUS_FILTER = "NeXus files (*.nxs.h5 *.nxs *.h5);;All files (*)"
SETTINGS_GROUP = "scale"


def default_settings() -> QSettings:
    """``~/.config/sansdir/viewer.ini`` — colour-scale choices kept between sessions."""
    return QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "sansdir", "viewer")


class MainWindow(QMainWindow):
    # Emitted with each new CubeLoader before it starts (a small run can finish
    # before open_path returns) and before the window's own slots are connected:
    # _on_finished drops the last reference to the loader, so slots connected
    # after it would never run.
    loader_created = Signal(object)

    def __init__(
        self,
        nbins: int = DEFAULT_NBINS,
        cache: CubeCache | None = None,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__()
        self.nbins = nbins
        self.cache = cache
        self.settings = settings  # None: nothing remembered (tests)
        self.cube: TofCube | None = None
        self._image: np.ndarray | None = None  # counts currently shown
        self.scale = _load_scale(settings)
        self._applying_levels = False
        self._hover: PixelInfo | None = None
        self._loader: CubeLoader | None = None
        self._retired: set[CubeLoader] = set()
        self._t_open = 0.0
        self._title = "EQSANS detector viewer"

        self.view = DetectorView()
        self.view.hovered.connect(self._show_readout)
        self.view.lut.sigLevelsChanged.connect(self._on_bar_dragged)
        self.view.set_cmap(self.scale.cmap)
        self.scale_panel = ScalePanel()
        self.scale_panel.log_toggled.connect(self._set_log)
        self.scale_panel.limits_edited.connect(self._on_limits_typed)
        self.scale_panel.auto_clicked.connect(self._on_auto)
        self.scale_panel.reset_clicked.connect(self._on_reset)
        self.scale_panel.lock_toggled.connect(self._on_lock)
        self.scale_panel.percentiles_edited.connect(self._on_percentiles)
        self.scale_panel.cmap_changed.connect(self._on_cmap)
        self.scale_panel.show_state(self.scale)
        self.tof_panel = TofPanel()
        self.tof_panel.range_changed.connect(self._on_tof_range)

        top = QWidget()
        row = QHBoxLayout(top)
        row.setContentsMargins(0, 0, 4, 0)
        row.addWidget(self.view, 1)
        row.addWidget(self.scale_panel)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(top)
        splitter.addWidget(self.tof_panel)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([720, 240])
        self.setCentralWidget(splitter)

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
        self.resize(1100, 980)

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
        self.log_action.setChecked(self.scale.log)
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
        self.loader_created.emit(loader)
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
        # A preview → full load of the same run keeps the TOF selection.
        spectrum = cube.spectrum() if cube.has_tof else None
        self.tof_panel.set_cube(cube.tof_edges, spectrum, keep=not new_file)
        self._image = cube.image(*self.tof_panel.selection) if cube.has_tof else cube.image()
        label = f"run {cube.run_number}" if cube.run_number else cube.path.name
        title = f" — {cube.title}" if cube.title else ""
        self._title = f"{label}{title} — EQSANS detector viewer"
        self._update_title()
        self._refresh()
        if new_file:
            self.view.fit()

    # -- display -----------------------------------------------------------

    def _on_tof_range(self, a: int, b: int) -> None:
        if self.cube is None:
            return
        self._image = self.cube.image(a, b)
        self._refresh()
        self._show_readout(self._hover)  # the readout's counts are per slice

    def _refresh(self) -> None:
        """New image: re-derive the limits (unless locked) and redraw."""
        if self._image is None:
            return
        self.scale.limits_for(self._image)
        self._apply_scale()

    def _apply_scale(self) -> None:
        """Push the current image and :attr:`scale` to the view and the panel."""
        self.scale_panel.show_state(self.scale)
        if self._image is None:
            return
        log = self.scale.log
        values = display_values(self._image, log=log)
        levels = display_levels(self.scale.vmin, self.scale.vmax, log=log)
        self._applying_levels = True  # our own setLevels is not a handle drag
        try:
            self.view.set_values(values, levels)
        finally:
            self._applying_levels = False
        self.view.set_count_ticks(log, values, levels)

    def _set_log(self, log: bool) -> None:
        self.scale.set_log(log, self._image)
        with QSignalBlocker(self.log_action):
            self.log_action.setChecked(log)
        self._save_scale()
        self._refresh()

    def _on_bar_dragged(self) -> None:
        """Colour-bar handles moved: they set (and lock) the limits."""
        if self._applying_levels:
            return
        lo, hi = self.view.lut.getLevels()
        self.scale.set_limits(*counts_from_levels(lo, hi, log=self.scale.log))
        self.scale.locked = True
        self.scale_panel.show_state(self.scale)
        self._save_scale()

    def _on_limits_typed(self, vmin: float, vmax: float) -> None:
        self.scale.set_limits(vmin, vmax)
        self.scale.locked = True
        self._save_scale()
        self._apply_scale()

    def _on_auto(self) -> None:
        if self._image is not None:
            self.scale.auto(self._image)
        self._save_scale()
        self._apply_scale()

    def _on_reset(self) -> None:
        if self._image is not None:
            self.scale.reset(self._image)
        self._save_scale()
        self._apply_scale()

    def _on_lock(self, locked: bool) -> None:
        self.scale.locked = locked
        self._save_scale()
        self._refresh()

    def _on_percentiles(self, lo: float, hi: float) -> None:
        self.scale.set_percentiles(lo, hi)
        self._save_scale()
        self._refresh()

    def _on_cmap(self, name: str) -> None:
        self.scale.cmap = name
        self.view.set_cmap(name)
        self._save_scale()

    def _save_scale(self) -> None:
        if self.settings is not None:
            _store_scale(self.settings, self.scale)

    def _show_readout(self, info: PixelInfo | None) -> None:
        self._hover = info
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


def _load_scale(settings: QSettings | None) -> ScaleState:
    """The remembered colour-scale choices; defaults for anything missing or bad."""
    state = ScaleState()
    if settings is None:
        return state
    settings.beginGroup(SETTINGS_GROUP)
    try:
        state.log = _as_bool(settings.value("log"), state.log)
        state.locked = _as_bool(settings.value("locked"), state.locked)
        cmap = str(settings.value("cmap", state.cmap))
        state.cmap = cmap if cmap in COLORMAPS else state.cmap
        try:
            state.set_percentiles(
                float(settings.value("percentile_lo", state.percentiles[0])),  # type: ignore[arg-type]
                float(settings.value("percentile_hi", state.percentiles[1])),  # type: ignore[arg-type]
            )
            state.set_limits(
                float(settings.value("vmin", state.vmin)),  # type: ignore[arg-type]
                float(settings.value("vmax", state.vmax)),  # type: ignore[arg-type]
            )
        except (TypeError, ValueError):
            pass
    finally:
        settings.endGroup()
    return state


def _store_scale(settings: QSettings, state: ScaleState) -> None:
    settings.beginGroup(SETTINGS_GROUP)
    settings.setValue("log", state.log)
    settings.setValue("locked", state.locked)
    settings.setValue("cmap", state.cmap)
    settings.setValue("percentile_lo", state.percentiles[0])
    settings.setValue("percentile_hi", state.percentiles[1])
    settings.setValue("vmin", state.vmin)
    settings.setValue("vmax", state.vmax)
    settings.endGroup()


def _as_bool(value: object, default: bool) -> bool:
    """QSettings hands booleans back as ``"true"`` / ``"false"`` from an ini file."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes")


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
    win = MainWindow(nbins, CubeCache.default() if use_cache else None, default_settings())
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

    def hook(loader: CubeLoader) -> None:
        loader.preview.connect(
            lambda _c: QTimer.singleShot(0, lambda: mark("preview image on screen"))
        )
        loader.loaded.connect(lambda _c: QTimer.singleShot(0, lambda: mark("full image on screen")))

        def done() -> None:
            mark("loader finished (cache written if any)")
            _benchmark_slider(app, win)
            app.quit()

        loader.finished.connect(done)

        def failed(message: str) -> None:
            mark(f"failed: {message}")
            app.quit()

        loader.failed.connect(failed)

    win.loader_created.connect(hook)


def _benchmark_slider(app: QApplication, win: MainWindow, frames: int = 200) -> None:
    """Time slider moves end to end: new slice, limits, image, colour bar, repaint."""
    panel = win.tof_panel
    if win.cube is None or not panel.has_tof:
        return
    panel.set_full(False)
    last = panel.slider.maximum()
    positions = [round(i * last / (frames - 1)) for i in range(frames)]
    times: list[float] = []
    for start in positions:
        t = time.perf_counter()
        panel.slider.setValue(start)
        app.processEvents()  # runs the repaint
        times.append((time.perf_counter() - t) * 1e3)
    times.sort()
    p95 = times[int(0.95 * (len(times) - 1))]
    print(
        f"   slider: {frames} moves, median {statistics.median(times):.1f} ms, "
        f"p95 {p95:.1f} ms, max {times[-1]:.1f} ms "
        f"(width {panel.selection[1] - panel.selection[0]} bins)",
        file=sys.stderr,
        flush=True,
    )
