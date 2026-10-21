"""Detector image widget: image + colour bar + hover readout + tube/bank highlight."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QPointF, Qt, Signal
from PySide6.QtWidgets import QApplication, QGraphicsRectItem

from sansdir.viewer.geometry import (
    CELL_ASPECT,
    NCOLS,
    NROWS,
    PixelInfo,
    bank_columns,
    pixel_info,
)

COLORMAP = "viridis"
HIGHLIGHT_PEN = pg.mkPen((255, 255, 255, 200), width=1)


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
        self.plot = self.addPlot()
        self.plot.setAspectLocked(True, ratio=CELL_ASPECT)
        self.plot.setLabel("bottom", "x  (tube column)")
        self.plot.setLabel("left", "y  (pixel along tube)")
        self.plot.setLimits(xMin=-20, xMax=NCOLS + 20, yMin=-20, yMax=NROWS + 20)

        self.image = pg.ImageItem(axisOrder="row-major")
        self.plot.addItem(self.image)

        self.lut = pg.HistogramLUTItem()
        self.lut.setImageItem(self.image)
        self.lut.gradient.setColorMap(pg.colormap.get(COLORMAP))
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
        self.image.setImage(values, autoLevels=False, levels=levels)
        self.lut.setLevels(*levels)

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
