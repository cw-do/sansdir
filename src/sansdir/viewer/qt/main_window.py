"""Viewer main window: detector view, mask tools, colour-scale panel, TOF panel, readout."""

from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QSettings, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QFontDatabase,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSpinBox,
    QSplitter,
    QToolBar,
    QWidget,
)

from sansdir.viewer import EXIT_SAVED
from sansdir.viewer.cache import CubeCache, describe
from sansdir.viewer.colorscale import (
    ScaleState,
    counts_from_levels,
    display_levels,
    display_values,
)
from sansdir.viewer.cube import DEFAULT_NBINS, TofCube
from sansdir.viewer.geometry import NPIX, PixelInfo
from sansdir.viewer.masking import (
    SAVE_FORMATS,
    SavedMask,
    default_output,
    read_mask_file,
)
from sansdir.viewer.qt.dialogs import ThresholdDialog, ask_spec
from sansdir.viewer.qt.image_view import DetectorView
from sansdir.viewer.qt.loader import CubeLoader, MaskSaver
from sansdir.viewer.qt.mask_editor import MaskEditor
from sansdir.viewer.qt.progress import LoadProgress, format_count
from sansdir.viewer.qt.scale_panel import ScalePanel
from sansdir.viewer.qt.tof_panel import TofPanel
from sansdir.viewer.settings import default_path, load_scale, save_scale

NEXUS_FILTER = "NeXus files (*.nxs.h5 *.nxs *.h5);;All files (*)"
MASK_OPEN_FILTER = "Masks (*.json *.xml *.nxs *.h5 *.npy);;All files (*)"
MASK_SAVE_FILTERS = {
    "Mantid mask NeXus (*.nxs)": ".nxs",
    "Mantid mask XML (*.xml)": ".xml",
    "NumPy array (*.npy)": ".npy",
}
SETTINGS_SAVE_DELAY_MS = 1500  # write preferences once changes settle, never per drag event
# Qt's own file dialog, not the desktop's: the native one on the cluster is GTK's
# chooser, which goes through gvfs / D-Bus and can stall on a node; Qt's needs
# neither, and with isolate_qt_settings() its history stays off the NFS home.
DIALOG_OPTIONS = QFileDialog.Option.DontUseNativeDialog
# (tool, label, key, tooltip) per mask tool, in toolbar order.
TOOL_ACTIONS: tuple[tuple[str, str, str, str], ...] = (
    ("pan", "Pan", "V", "Pan / select: drag to pan; drag ROIs to move, handles to resize"),
    ("rect", "Rect", "R", "Draw a rectangle"),
    ("ellipse", "Ellipse", "E", "Draw an ellipse"),
    ("circle", "Circle", "C", "Draw a circle (drag from the centre)"),
    ("polygon", "Polygon", "P", "Click the corners; double-click to close"),
    ("brush", "Brush", "B", "Paint masked pixels (click or drag)"),
    ("eraser", "Eraser", "X", "Unmask pixels, also inside shapes (click or drag)"),
    ("tube", "Tube", "T", "Click a tube to mask / unmask it; Shift-click: its whole bank"),
)


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
        settings: Path | None = None,
        *,
        mask_output: Path | None = None,
        ask_to_save: bool = False,
    ) -> None:
        super().__init__()
        self.nbins = nbins
        self.cache = cache
        self.settings = settings  # viewer.json; None: nothing remembered (tests)
        self.mask_output = mask_output  # default "Save mask" path
        self.ask_to_save = ask_to_save  # closing with unsaved mask edits asks first
        self.saved_any = False
        self._mask: np.ndarray | None = None  # None when nothing is masked
        self._saver: MaskSaver | None = None
        self._close_after_save = False
        self.cube: TofCube | None = None
        self._image: np.ndarray | None = None  # counts currently shown
        self.scale = load_scale(settings) if settings is not None else ScaleState()
        self._settings_timer = QTimer(self)
        self._settings_timer.setSingleShot(True)
        self._settings_timer.setInterval(SETTINGS_SAVE_DELAY_MS)
        self._settings_timer.timeout.connect(self.flush_settings)
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
        self.editor = MaskEditor(self.view)
        self.editor.changed.connect(self._on_mask_changed)
        self.editor.message.connect(self._say)

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
        self.mask_label = QLabel()
        self.loading = LoadProgress()
        self.loading.cancel_requested.connect(self.cancel_load)
        bar = self.statusBar()
        bar.addWidget(self.readout, 1)
        bar.addPermanentWidget(self.info)
        bar.addPermanentWidget(self.mask_label)
        bar.addPermanentWidget(self.loading)
        QShortcut(QKeySequence("Esc"), self, self._on_escape)

        self._build_menus()
        self._build_mask_tools()
        self._update_mask_label()
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
        self.load_mask_action = QAction("&Load mask…", self, shortcut=QKeySequence("Ctrl+L"))
        self.load_mask_action.triggered.connect(self._ask_load_mask)
        self.save_mask_action = QAction("&Save mask…", self)
        self.save_mask_action.setShortcuts([QKeySequence("Ctrl+S"), QKeySequence("S")])
        self.save_mask_action.triggered.connect(self.save_mask)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        file_menu.addAction(self.load_mask_action)
        file_menu.addAction(self.save_mask_action)
        file_menu.addSeparator()
        file_menu.addAction(self.clear_cache_action)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu("&View")
        self.log_action = QAction("&Log scale", self, shortcut=QKeySequence("L"), checkable=True)
        self.log_action.setChecked(self.scale.log)
        self.log_action.toggled.connect(self._set_log)
        view_menu.addAction(self.log_action)
        self.overlay_action = QAction(
            "Show &mask", self, shortcut=QKeySequence("O"), checkable=True
        )
        self.overlay_action.setChecked(True)
        self.overlay_action.toggled.connect(lambda _on: self._on_mask_changed())
        view_menu.addAction(self.overlay_action)

    def _build_mask_tools(self) -> None:
        """Mask toolbar (tools + edits) and the Mask menu with the same actions."""
        bar = QToolBar("Mask tools")
        bar.setObjectName("mask-tools")
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)
        menu = self.menuBar().addMenu("&Mask")
        group = QActionGroup(self)
        self.tool_actions: dict[str, QAction] = {}
        for name, label, key, tip in TOOL_ACTIONS:
            action = QAction(label, self, checkable=True, shortcut=QKeySequence(key))
            action.setToolTip(f"{tip}  ({key})")
            action.triggered.connect(lambda _c=False, n=name: self.set_tool(n))
            group.addAction(action)
            bar.addAction(action)
            menu.addAction(action)
            self.tool_actions[name] = action
        self.tool_actions["pan"].setChecked(True)
        self.brush_box = QSpinBox()
        self.brush_box.setRange(0, 20)
        self.brush_box.setPrefix("r ")
        self.brush_box.setToolTip("Brush / eraser radius in pixels (0 = one pixel)")
        self.brush_box.valueChanged.connect(self._on_brush_radius)
        bar.addWidget(self.brush_box)
        bar.addSeparator()
        menu.addSeparator()

        def add(label: str, keys: list[str], slot, tip: str, checkable: bool = False) -> QAction:  # type: ignore[no-untyped-def]
            action = QAction(label, self, checkable=checkable)
            action.setShortcuts([QKeySequence(k) for k in keys])
            action.setToolTip(f"{tip}  ({', '.join(keys)})")
            action.triggered.connect(slot)
            bar.addAction(action)
            menu.addAction(action)
            return action

        self.undo_action = add("Undo", ["Z", "Ctrl+Z"], self.editor.undo, "Undo the last mask edit")
        self.redo_action = add(
            "Redo", ["Shift+Z", "Ctrl+Shift+Z", "Ctrl+Y"], self.editor.redo, "Redo"
        )
        self.delete_action = add(
            "Delete",
            ["Delete", "Backspace"],
            self.editor.delete_selected,
            "Delete the selected shape (click a shape to select it)",
        )
        self.invert_action = add(
            "Invert", ["I"], self.editor.set_inverted, "Invert the mask", checkable=True
        )
        self.clear_action = add("Clear", [], self._ask_clear, "Remove the whole mask")
        bar.addSeparator()
        menu.addSeparator()
        self.spec_action = add("Tubes…", ["K"], self._ask_spec, "Mask tubes by number: b3 t10-12")
        self.threshold_action = add(
            "Dead/hot…", ["H"], self._ask_threshold, "Mask pixels by counts in the current image"
        )
        bar.addSeparator()
        bar.addAction(self.load_mask_action)
        bar.addAction(self.save_mask_action)

    # -- loading -----------------------------------------------------------

    def _ask_open(self) -> None:
        start = str(self.cube.path.parent) if self.cube else ""
        name, _ = QFileDialog.getOpenFileName(
            self, "Open NeXus file", start, NEXUS_FILTER, options=DIALOG_OPTIONS
        )
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
        self.scale.limits_for(self._image, self._mask)
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
            self.scale.auto(self._image, self._mask)
        self._save_scale()
        self._apply_scale()

    def _on_reset(self) -> None:
        if self._image is not None:
            self.scale.reset(self._image, self._mask)
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
        """Schedule a preferences write (debounced: a handle drag is hundreds of events)."""
        if self.settings is not None:
            self._settings_timer.start()

    def flush_settings(self) -> None:
        self._settings_timer.stop()
        if self.settings is not None:
            save_scale(self.settings, self.scale)

    def _show_readout(self, info: PixelInfo | None) -> None:
        self._hover = info
        if info is None or self._image is None:
            self.readout.clear()
            return
        counts = float(self._image[info.y, info.x])
        approx = "≈" if self.cube is not None and self.cube.is_preview else ""
        masked = " │ MASKED" if self._mask is not None and self._mask[info.y, info.x] else ""
        self.readout.setText(
            f"x {info.x:3d}  y {info.y:3d} │ {info.panel} bank{info.bank} "
            f"tube{info.tube} pixel{info.pixel} │ ID {info.detid} · DAS bank{info.das_bank} "
            f"│ {approx}{counts:,.0f} counts{masked}"
        )

    # -- mask --------------------------------------------------------------

    def set_tool(self, name: str) -> None:
        self.editor.set_tool(name)
        self.tool_actions[name].setChecked(True)

    def _on_brush_radius(self, radius: int) -> None:
        self.editor.brush_radius = float(radius)

    def _on_escape(self) -> None:
        if not self.editor.cancel():
            self.cancel_load()

    def _say(self, message: str) -> None:
        self.info.setText(message)

    def _on_mask_changed(self) -> None:
        mask = self.editor.state.build()
        self._mask = mask if mask.any() else None
        self.view.set_mask(self._mask if self.overlay_action.isChecked() else None)
        with QSignalBlocker(self.invert_action):
            self.invert_action.setChecked(self.editor.state.inverted)
        self._update_mask_label()
        self._show_readout(self._hover)

    def _update_mask_label(self) -> None:
        state = self.editor.state
        n = 0 if self._mask is None else int(self._mask.sum())
        parts = [f"mask {n:,} px ({n / NPIX:.1%})"] if n else ["no mask"]
        if state.inverted:
            parts.append("inverted")
        if state.modified and not state.is_empty:
            parts.append("unsaved")
        self.mask_label.setText(" · ".join(parts))
        self.undo_action.setEnabled(state.can_undo)
        self.redo_action.setEnabled(state.can_redo)

    def _ask_clear(self) -> None:
        if self.editor.state.is_empty:
            return
        answer = QMessageBox.question(self, "Clear mask", "Remove the whole mask? (Z undoes it)")
        if answer == QMessageBox.StandardButton.Yes:
            self.editor.clear()

    def _ask_spec(self) -> None:
        text = ask_spec(self)
        if text is None or not text.strip():
            return
        try:
            self._say(self.editor.apply_spec(text))
        except ValueError as exc:
            QMessageBox.warning(self, "Mask tubes", str(exc))

    def _ask_threshold(self) -> None:
        if self._image is None:
            self._say("open a run first")
            return
        dialog = ThresholdDialog(self._image, self.tof_panel.label.text(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        low, high = dialog.limits()
        n = self.editor.threshold(self._image, low, high)
        self._say(f"threshold masked {n:,} more pixels")

    def _ask_load_mask(self) -> None:
        start = str(self.cube.path.parent) if self.cube else ""
        name, _ = QFileDialog.getOpenFileName(
            self, "Load mask", start, MASK_OPEN_FILTER, options=DIALOG_OPTIONS
        )
        if name:
            self.load_mask(Path(name))

    def load_mask(self, path: Path) -> bool:
        """Add the mask in ``path`` to the current one (one undo step)."""
        try:
            loaded = read_mask_file(path)
            self.editor.load(loaded)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Load mask", f"Could not load {path.name}:\n{exc}")
            return False
        self._say(f"loaded mask {path.name}")
        return True

    def save_mask(self) -> bool:
        """Ask where, then save in the background. False if nothing was started."""
        if self.cube is None:
            self._say("open a run first: the mask is saved against its file")
            return False
        if self._saver is not None:
            self._say("a save is already running")
            return False
        default = self.mask_output or default_output(self.cube.path)
        name, chosen = QFileDialog.getSaveFileName(
            self, "Save mask", str(default), ";;".join(MASK_SAVE_FILTERS), options=DIALOG_OPTIONS
        )
        if not name:
            return False
        out = Path(name)
        if out.suffix.lower() not in SAVE_FORMATS:
            out = out.with_name(out.name + MASK_SAVE_FILTERS.get(chosen, ".nxs"))
        self.start_save(out)
        return True

    def start_save(self, out: Path) -> None:
        """Save to ``out`` on a worker thread (Mantid's ``.nxs`` writer takes ~10 s)."""
        assert self.cube is not None
        from sansdir.mask.mantid_writer import is_drtsans_available

        how = "via Mantid, ~10 s" if out.suffix == ".nxs" and is_drtsans_available() else ""
        self._say(f"saving mask → {out.name}" + (f" ({how})…" if how else "…"))
        saver = MaskSaver(self.editor.state, self.cube.path, self.cube.run_number, out)
        saver.saved.connect(self._on_saved)
        saver.failed.connect(self._on_save_failed)
        saver.finished.connect(self._on_save_finished)
        self._saver = saver
        self.save_mask_action.setEnabled(False)
        saver.start()

    def _on_saved(self, result: SavedMask) -> None:
        self.editor.state.mark_saved()
        self.saved_any = True
        self.mask_output = result.path
        self._say(f"mask saved: {result.path} ({result.n_masked:,} px) + {result.log_path.name}")
        self._update_mask_label()

    def _on_save_failed(self, message: str) -> None:
        self._close_after_save = False
        QMessageBox.warning(self, "Save mask", f"Saving failed:\n{message}")
        self._say("mask NOT saved")

    def _on_save_finished(self) -> None:
        self._saver = None
        self.save_mask_action.setEnabled(True)
        if self._close_after_save:
            self._close_after_save = False
            self.close()

    def _unsaved_mask(self) -> bool:
        state = self.editor.state
        return state.modified and not state.is_empty

    # -- Qt plumbing -------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 — Qt override
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 — Qt override
        urls = event.mimeData().urls()
        if urls:
            self.open_path(Path(urls[0].toLocalFile()))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — Qt override
        if self._saver is not None:  # never tear a mask file
            self._close_after_save = True
            self._say("closing after the mask is saved…")
            event.ignore()
            return
        if self.ask_to_save and self._unsaved_mask():
            answer = QMessageBox.question(
                self,
                "Unsaved mask",
                "The mask has unsaved changes. Save it before closing?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.StandardButton.Save:
                event.ignore()
                if self.save_mask():
                    self._close_after_save = True
                return
        self.flush_settings()
        # A load stops within ~0.2 s; a cache write in progress (~1 s) is
        # left to finish so it is not torn.
        for loader in list(self._retired):
            loader.stop()
            loader.wait(15_000)
        super().closeEvent(event)


def local_qt_settings_dir() -> Path:
    """Node-local home for Qt's own settings: ``$XDG_RUNTIME_DIR`` (tmpfs), else the temp dir."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime and Path(runtime).is_dir() else Path(tempfile.gettempdir())
    return base / f"sansdir-qt-{os.getuid()}"


def isolate_qt_settings(directory: Path | None = None) -> Path:
    """Keep Qt's internal ``QSettings`` (e.g. ``QtProject.conf``) off the NFS home.

    Qt's file dialog saves its history through ``QSettings``, which takes a
    ``QLockFile`` next to ``~/.config/QtProject.conf``. On the cluster's NFS
    homes that lock gets stuck and every later file dialog hangs — *Load
    mask…* "failed" this way on 2026-10-21 behind a lock left at 09:50.
    Redirect them to node-local storage, where locking works. Call before
    any dialog opens.
    """
    target = directory or local_qt_settings_dir()
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, str(target))
    return target


def run(
    path: Path | None,
    *,
    nbins: int = DEFAULT_NBINS,
    use_cache: bool = True,
    benchmark: bool = False,
    mask: Path | None = None,
    output: Path | None = None,
    tool: str = "pan",
) -> int:
    """Create the application, show the window, start loading ``path``.

    Returns :data:`EXIT_SAVED` when a mask was saved (so the TUI refreshes
    its panes), otherwise the event loop's exit code (0).
    """
    t0 = time.perf_counter()
    isolate_qt_settings()
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication(sys.argv[:1])
    pg.setConfigOptions(antialias=False)
    win = MainWindow(
        nbins,
        CubeCache.default() if use_cache else None,
        default_path(),
        mask_output=output,
        ask_to_save=not benchmark,
    )
    win.show()
    win.set_tool(tool)
    if mask is not None:
        win.load_mask(mask)
        win.editor.state.mark_saved()  # loading a file is not an unsaved edit
    if benchmark:
        _attach_benchmark(app, win, t0)
    if path is not None:
        QTimer.singleShot(0, lambda: win.open_path(path))
    code = int(app.exec())
    return EXIT_SAVED if win.saved_any and code == 0 else code


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
