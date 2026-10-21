"""TOF panel: whole-detector spectrum + draggable range + slider, width, play."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from sansdir.viewer import tofrange

PLAY_INTERVAL_MS = 150
SPECTRUM_PEN = pg.mkPen((90, 160, 230), width=1)
SPECTRUM_BRUSH = pg.mkBrush(90, 160, 230, 60)
REGION_BRUSH = pg.mkBrush(255, 200, 60, 50)


class TofPanel(QWidget):
    """Select the TOF bins ``[a, b)`` the detector image shows.

    Four ways in, all kept in sync: drag the shaded region (or its edges)
    on the spectrum, move the slider (window start), type a width, or
    step / play through the run in steps of one width. ``Full range``
    selects every bin (the total-counts image). Emits ``range_changed(a,
    b)`` on every change the user makes, while dragging too.

    Keys (anywhere in the window): ``[`` / ``]`` step, ``Space`` play/pause.
    """

    range_changed = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self._edges: np.ndarray | None = None  # ms
        self._nbins = 1
        self._a, self._b = 0, 1
        self._windowed = (0, 1)  # last non-full window, restored when Full is unticked
        self._syncing = False

        self.plot = pg.PlotWidget()
        self.plot.setLabel("bottom", "TOF", units="ms")
        self.plot.setLabel("left", "counts / bin")
        self.plot.setMouseEnabled(x=True, y=False)
        self.plot.getPlotItem().hideButtons()
        self.curve = self.plot.plot(
            stepMode="center", fillLevel=0, pen=SPECTRUM_PEN, brush=SPECTRUM_BRUSH
        )
        self.region = pg.LinearRegionItem(brush=REGION_BRUSH)
        self.region.setZValue(10)
        self.plot.addItem(self.region)
        self.region.sigRegionChanged.connect(self._on_region_dragged)
        self.region.sigRegionChangeFinished.connect(self._on_region_dropped)

        self.prev_button = _tool("◀", "Previous slice  [")
        self.next_button = _tool("▶", "Next slice  ]")
        self.play_button = _tool("Play", "Step through the run  (Space)")
        self.play_button.setCheckable(True)
        self.prev_button.clicked.connect(lambda: self.step(-1))
        self.next_button.clicked.connect(lambda: self.step(1))
        self.play_button.toggled.connect(self._on_play_toggled)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setToolTip("First TOF bin of the window")
        self.slider.valueChanged.connect(self._on_slider)
        self.width_box = QSpinBox()
        self.width_box.setToolTip("Window width in TOF bins")
        self.width_box.setKeyboardTracking(False)
        self.width_box.valueChanged.connect(self._on_width)
        self.full_box = QCheckBox("Full range")
        self.full_box.setToolTip("All TOF bins: the total-counts image")
        self.full_box.toggled.connect(self.set_full)
        self.label = QLabel()

        controls = QHBoxLayout()
        controls.addWidget(self.prev_button)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.next_button)
        controls.addWidget(QLabel("width"))
        controls.addWidget(self.width_box)
        controls.addWidget(self.full_box)
        controls.addWidget(self.play_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.addWidget(self.plot, 1)
        layout.addLayout(controls)
        layout.addWidget(self.label)

        self._timer = QTimer(self)
        self._timer.setInterval(PLAY_INTERVAL_MS)
        self._timer.timeout.connect(lambda: self.step(1))
        self._shortcuts = [
            QShortcut(QKeySequence("["), self, lambda: self.step(-1)),
            QShortcut(QKeySequence("]"), self, lambda: self.step(1)),
            QShortcut(QKeySequence("Space"), self, self.play_button.toggle),
        ]
        for shortcut in self._shortcuts:
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.set_cube(None, None)

    # -- public ------------------------------------------------------------

    @property
    def selection(self) -> tuple[int, int]:
        return self._a, self._b

    @property
    def has_tof(self) -> bool:
        return self._edges is not None

    def set_cube(
        self, edges_us: np.ndarray | None, spectrum: np.ndarray | None, *, keep: bool = False
    ) -> None:
        """Show a new run's spectrum. ``keep`` holds the selection (preview → full load).

        Does not emit ``range_changed``: the caller redraws for the new cube anyway.
        """
        if edges_us is None or spectrum is None:
            self._stop_play()
            self._edges = None
            self.curve.setData([], [])
            self.region.hide()
            self._enable(False)
            self.label.setText(tofrange.describe(None, 0, 1))
            return
        self._edges = np.asarray(edges_us, dtype=np.float64) / 1e3
        self._nbins = len(self._edges) - 1
        self.curve.setData(self._edges, np.asarray(spectrum, dtype=np.float64))
        self._syncing = True  # moving the region's bounds must not count as a drag
        try:
            self.region.setBounds((self._edges[0], self._edges[-1]))
        finally:
            self._syncing = False
        self.region.show()
        self._enable(True)
        with QSignalBlocker(self.width_box):
            self.width_box.setRange(1, self._nbins)
        width = tofrange.default_width(self._nbins)
        if keep:
            a, b = tofrange.clamp(self._a, self._b, self._nbins)
            wa, wb = self._windowed
            self._windowed = tofrange.clamp(wa, wb, self._nbins)
        else:
            self._stop_play()
            a, b = 0, self._nbins
            self._windowed = (0, width)
            self.plot.enableAutoRange()
        self._select(a, b, emit=False)

    def set_full(self, full: bool) -> None:
        """Tick/untick ``Full range``; unticking restores the last window."""
        if self._edges is None or self._syncing:
            return
        if full:
            self._select(0, self._nbins)
        else:
            self._select(*self._windowed)

    def step(self, n: int) -> None:
        """Move the window ``n`` widths (wraps), leaving the full range first."""
        if self._edges is None:
            return
        a, b = self._windowed if self._is_full() else (self._a, self._b)
        if not self._is_full():
            a, b = tofrange.step(a, b, self._nbins, n)
        self._select(a, b)

    # -- internals ---------------------------------------------------------

    def _is_full(self) -> bool:
        return self._a == 0 and self._b == self._nbins

    def _select(self, a: int, b: int, *, emit: bool = True, move_region: bool = True) -> None:
        a, b = tofrange.clamp(a, b, self._nbins)
        changed = (a, b) != (self._a, self._b)
        self._a, self._b = a, b
        full = self._is_full()
        if not full:
            self._windowed = (a, b)
        self._syncing = True
        try:
            with (
                QSignalBlocker(self.width_box),
                QSignalBlocker(self.slider),
                QSignalBlocker(self.full_box),
            ):
                self.width_box.setValue(b - a)
                self.slider.setRange(0, self._nbins - (b - a))
                self.slider.setValue(a)
                self.full_box.setChecked(full)
            if move_region and self._edges is not None:
                self.region.setRegion((self._edges[a], self._edges[b]))
        finally:
            self._syncing = False
        self.label.setText(tofrange.describe(self._edges_us(), a, b))
        if emit and changed:
            self.range_changed.emit(a, b)

    def _edges_us(self) -> np.ndarray | None:
        return None if self._edges is None else self._edges * 1e3

    def _on_slider(self, start: int) -> None:
        width = self._windowed[1] - self._windowed[0] if self._is_full() else self._b - self._a
        self._select(start, start + width)

    def _on_width(self, width: int) -> None:
        a = self._windowed[0] if self._is_full() else self._a
        self._select(a, a + width)

    def _on_region_dragged(self) -> None:
        if self._syncing or self._edges is None:
            return
        # Follow the drag bin by bin, but leave the region where the mouse puts it.
        self._select(*tofrange.snap(self._edges, *self.region.getRegion()), move_region=False)

    def _on_region_dropped(self) -> None:
        if self._syncing or self._edges is None:
            return
        self._select(*tofrange.snap(self._edges, *self.region.getRegion()))

    def _on_play_toggled(self, playing: bool) -> None:
        if playing and self._edges is not None:
            if self._is_full():
                self._select(*self._windowed)
            self.play_button.setText("Pause")
            self._timer.start()
        else:
            self._stop_play()

    def _stop_play(self) -> None:
        self._timer.stop()
        with QSignalBlocker(self.play_button):
            self.play_button.setChecked(False)
        self.play_button.setText("Play")

    def _enable(self, on: bool) -> None:
        for widget in (
            self.prev_button,
            self.next_button,
            self.play_button,
            self.slider,
            self.width_box,
            self.full_box,
        ):
            widget.setEnabled(on)


def _tool(text: str, tip: str) -> QToolButton:
    button = QToolButton()
    button.setText(text)
    button.setToolTip(tip)
    return button
