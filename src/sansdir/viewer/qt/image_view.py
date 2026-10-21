"""Detector image widget: image + colour bar + mask overlay + hover readout + highlight."""

from __future__ import annotations

import warnings
from typing import Protocol

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QPointF, Qt, Signal
from PySide6.QtWidgets import QApplication, QGraphicsRectItem

from sansdir.viewer.colorscale import DEFAULT_CMAP, log_ticks
from sansdir.viewer.geometry import (
    CELL_ASPECT,
    NCOLS,
    NROWS,
    PixelInfo,
    bank_columns,
    pixel_info,
)

# Not among pyqtgraph's bundled maps; matplotlib's jet stops, and a plain grey ramp.
_EXTRA_CMAPS = {
    "jet": (
        [0.0, 0.11, 0.125, 0.34, 0.35, 0.64, 0.65, 0.89, 0.91, 1.0],
        [
            (0, 0, 127),
            (0, 0, 255),
            (0, 0, 255),
            (0, 220, 255),
            (0, 229, 246),
            (240, 255, 7),
            (255, 255, 0),
            (255, 18, 0),
            (232, 0, 0),
            (127, 0, 0),
        ],
    ),
    "gray": ([0.0, 1.0], [(0, 0, 0), (255, 255, 255)]),
}
HIGHLIGHT_PEN = pg.mkPen((255, 255, 255, 200), width=1)
MASK_RGBA = (255, 40, 40, 120)


class Tool(Protocol):
    """A mask tool: gets the left-button gestures on the detector, in view coordinates."""

    def drag(self, start: QPointF, pos: QPointF, phase: str, shift: bool) -> None:
        """``phase`` is ``"start"``, ``"move"`` or ``"finish"``."""

    def click(self, pos: QPointF, double: bool, shift: bool) -> None: ...


class ToolViewBox(pg.ViewBox):
    """A ViewBox that hands left drags and clicks to :attr:`tool` when one is set.

    With no tool, left-drag pans as usual. Middle-drag pans and the wheel
    zooms in every mode, and ROIs on top still take their own drags.
    """

    def __init__(self) -> None:
        super().__init__()
        self.tool: Tool | None = None

    def mouseDragEvent(self, ev, axis=None) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self.tool is None or axis is not None or ev.button() != Qt.MouseButton.LeftButton:
            super().mouseDragEvent(ev, axis)
            return
        ev.accept()
        phase = "start" if ev.isStart() else "finish" if ev.isFinish() else "move"
        shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        self.tool.drag(self.mapToView(ev.buttonDownPos()), self.mapToView(ev.pos()), phase, shift)

    def mouseClickEvent(self, ev) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self.tool is None or ev.button() != Qt.MouseButton.LeftButton:
            super().mouseClickEvent(ev)
            return
        ev.accept()
        shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        self.tool.click(self.mapToView(ev.pos()), ev.double(), shift)


class DetectorView(pg.GraphicsLayoutWidget):
    """The ``(256, 192)`` detector image in display coordinates.

    Cell ``(col, row)`` covers ``[col, col+1) x [row, row+1)``; row 0 is
    the bottom of the tubes (Mantid ``pixel1``). Emits ``hovered`` with a
    :class:`PixelInfo` (or ``None`` off the detector). Holding Shift
    highlights the whole bank instead of one tube.
    """

    hovered = Signal(object)  # PixelInfo | None

    def __init__(self) -> None:
        super().__init__()
        self.vb = ToolViewBox()
        self.plot = self.addPlot(viewBox=self.vb)
        self.plot.setAspectLocked(True, ratio=CELL_ASPECT)
        self.plot.setLabel("bottom", "x  (tube column)")
        self.plot.setLabel("left", "y  (pixel along tube)")
        self.plot.setLimits(xMin=-20, xMax=NCOLS + 20, yMin=-20, yMax=NROWS + 20)

        self.image = pg.ImageItem(axisOrder="row-major")
        self.plot.addItem(self.image)
        self.overlay = pg.ImageItem(axisOrder="row-major")
        self.overlay.setZValue(5)
        self.plot.addItem(self.overlay)

        self.lut = pg.HistogramLUTItem()
        self.lut.setImageItem(self.image)
        self.set_cmap(DEFAULT_CMAP)
        self.addItem(self.lut)

        self._highlights: list[QGraphicsRectItem] = []
        for _ in range(4):  # a bank is 4 tubes
            rect = QGraphicsRectItem(0, 0, 1, NROWS)
            rect.setPen(HIGHLIGHT_PEN)
            rect.setZValue(10)
            rect.hide()
            self.plot.addItem(rect)
            self._highlights.append(rect)
        self._last: PixelInfo | None = None
        self.plot.scene().sigMouseMoved.connect(self._on_mouse_moved)

    def set_values(self, values: np.ndarray, levels: tuple[float, float]) -> None:
        """Show display values (already log-transformed if wanted)."""
        with warnings.catch_warnings():
            # An empty slice in log mode is all NaN; pyqtgraph's histogram warns.
            warnings.simplefilter("ignore", RuntimeWarning)
            self.image.setImage(values, autoLevels=False, levels=levels)
        self.lut.setLevels(*levels)

    def set_mask(self, mask: np.ndarray | None) -> None:
        """Draw masked cells in translucent red (``None`` or all-clear: nothing)."""
        if mask is None or not mask.any():
            self.overlay.clear()
            return
        rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
        rgba[mask] = MASK_RGBA
        self.overlay.setImage(rgba, autoLevels=False, levels=(0, 255))

    def set_cmap(self, name: str) -> None:
        """Colour map by name (pyqtgraph's bundled maps, ``jet`` or ``gray``)."""
        if name in _EXTRA_CMAPS:
            pos, colors = _EXTRA_CMAPS[name]
            cmap = pg.ColorMap(pos, colors)
        else:
            cmap = pg.colormap.get(name)
        self.lut.gradient.setColorMap(cmap)
        # One draggable marker per colour stop (256 for viridis) is repainted on
        # every frame: ~2.5 ms of a slider move. The maps are not edited here.
        self.lut.gradient.showTicks(False)

    def set_count_ticks(self, log: bool, values: np.ndarray, levels: tuple[float, float]) -> None:
        """Label the colour bar in counts: ``1, 10, 100, …`` in log mode, default otherwise."""
        if not log:
            self.lut.axis.setTicks(None)
            return
        finite = values[np.isfinite(values)]
        lo, hi = levels
        if finite.size:
            lo, hi = min(lo, float(finite.min())), max(hi, float(finite.max()))
        major, minor = log_ticks(lo - 1, hi + 1)
        self.lut.axis.setTicks([major, minor])

    def fit(self) -> None:
        """Zoom to the whole detector (aspect-locked, so one axis gets slack)."""
        self.plot.vb.setRange(xRange=(0, NCOLS), yRange=(0, NROWS), padding=0.02)

    def _on_mouse_moved(self, pos: QPointF) -> None:
        info = None
        if self.plot.vb.sceneBoundingRect().contains(pos):
            p = self.plot.vb.mapSceneToView(pos)
            info = pixel_info(p.x(), p.y())
        self._show(info)

    def _show(self, info: PixelInfo | None) -> None:
        if info is None:
            for rect in self._highlights:
                rect.hide()
        else:
            whole_bank = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
            cols = bank_columns(info.bank) if whole_bank else [info.x]
            for i, rect in enumerate(self._highlights):
                if i < len(cols):
                    rect.setRect(cols[i], 0, 1, NROWS)
                    rect.show()
                else:
                    rect.hide()
        if info != self._last:
            self._last = info
            self.hovered.emit(info)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 — Qt override
        self._show(None)
        super().leaveEvent(event)
