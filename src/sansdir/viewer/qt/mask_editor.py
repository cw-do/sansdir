"""Mask editing on the detector view: tools, editable ROIs, undo/redo.

The model is :class:`~sansdir.viewer.masking.MaskState`; this controller
turns gestures into state changes and keeps one editable ROI per shape.
Emits ``changed`` after every change so the window can redraw the overlay.

Tools (``tool`` names): ``pan`` (no tool — left-drag pans; ROIs can still be
moved and resized), ``rect``, ``ellipse``, ``circle``, ``polygon`` (click the
corners, double-click or Enter to close), ``brush`` / ``eraser`` (click or
drag; radius in cells), ``tube`` (click toggles the tube; Shift-click the
whole Mantid bank).
"""

from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsRectItem,
)

from sansdir.mask.banktube import cols_to_runs, parse_spec
from sansdir.mask.core import Circle, Ellipse, MaskBuilder, Polygon, Rectangle, Shape
from sansdir.viewer.geometry import NCOLS, NROWS, bank_columns, pixel_info
from sansdir.viewer.masking import MASK_TOOLS, VIEW_OFFSET, MaskState, brush_cells
from sansdir.viewer.qt.image_view import DetectorView
from sansdir.viewer.qt.roi_tools import ROI_PEN, SELECTED_PEN, roi_for_shape, shape_for_roi

SHAPE_TOOLS = ("rect", "ellipse", "circle")
MIN_SIZE = 0.5  # cells: a smaller drag is a click, not a shape
RUBBER_PEN = pg.mkPen((255, 225, 0), width=1, style=Qt.PenStyle.DashLine)


class MaskEditor(QObject):
    changed = Signal()  # the mask (or its shapes) changed
    message = Signal(str)  # one-line feedback for the status bar

    def __init__(self, view: DetectorView) -> None:
        super().__init__()
        self.view = view
        self.state = MaskState()
        self.tool = "pan"
        self.brush_radius = 0.0
        self._rois: list[pg.ROI] = []
        self._selected: pg.ROI | None = None
        self._syncing = False
        self._rubber: QGraphicsRectItem | QGraphicsEllipseItem | None = None
        self._last_paint: QPointF | None = None
        self._paint_masked = True
        self._poly: list[QPointF] = []
        self._poly_line = pg.PlotDataItem(pen=RUBBER_PEN, symbol="o", symbolSize=5)
        self._poly_line.setZValue(20)
        self.view.plot.addItem(self._poly_line)

    # -- tools -----------------------------------------------------------------

    def set_tool(self, name: str) -> None:
        if name not in MASK_TOOLS:
            raise ValueError(f"unknown tool {name!r}")
        self.cancel()
        self.tool = name
        self.view.vb.tool = None if name == "pan" else self

    def cancel(self) -> bool:
        """Drop a half-drawn shape (Esc). True if there was one."""
        busy = bool(self._poly) or self._rubber is not None
        self._poly.clear()
        self._poly_line.setData([], [])
        self._drop_rubber()
        return busy

    def drag(self, start: QPointF, pos: QPointF, phase: str, shift: bool) -> None:
        if self.tool in SHAPE_TOOLS:
            self._drag_shape(start, pos, phase)
        elif self.tool in ("brush", "eraser"):
            self._drag_paint(pos, phase)

    def click(self, pos: QPointF, double: bool, shift: bool) -> None:
        if self.tool in ("brush", "eraser"):
            self.state.paint(self._cells(pos), masked=self.tool == "brush")
            self.changed.emit()
        elif self.tool == "tube":
            self._click_tube(pos, shift)
        elif self.tool == "polygon":
            self._click_polygon(pos, double)

    def _drag_shape(self, start: QPointF, pos: QPointF, phase: str) -> None:
        if phase == "start":
            self._drop_rubber()
            item = QGraphicsEllipseItem() if self.tool != "rect" else QGraphicsRectItem()
            item.setPen(RUBBER_PEN)
            item.setZValue(20)
            self.view.plot.addItem(item)
            self._rubber = item
        if self._rubber is not None:
            self._rubber.setRect(self._rubber_rect(start, pos))
        if phase == "finish":
            self._drop_rubber()
            shape = self._shape_from_drag(start, pos)
            if shape is not None:
                self.add_shape(shape)

    def _rubber_rect(self, start: QPointF, pos: QPointF) -> QRectF:
        if self.tool == "circle":
            r = math.hypot(pos.x() - start.x(), pos.y() - start.y())
            return QRectF(start.x() - r, start.y() - r, 2 * r, 2 * r)
        return QRectF(start, pos).normalized()

    def _shape_from_drag(self, start: QPointF, pos: QPointF) -> Shape | None:
        o = VIEW_OFFSET
        rect = self._rubber_rect(start, pos)
        if rect.width() < MIN_SIZE or rect.height() < MIN_SIZE:
            return None
        if self.tool == "rect":
            return Rectangle(rect.left() - o, rect.top() - o, rect.right() - o, rect.bottom() - o)
        cx, cy = rect.center().x() - o, rect.center().y() - o
        if self.tool == "circle":
            return Circle(cx, cy, rect.width() / 2)
        return Ellipse(cx, cy, rect.width() / 2, rect.height() / 2)

    def _drop_rubber(self) -> None:
        if self._rubber is not None:
            self.view.plot.removeItem(self._rubber)
            self._rubber = None

    def _cells(self, pos: QPointF) -> np.ndarray:
        return brush_cells(pos.x(), pos.y(), self.brush_radius)

    def _drag_paint(self, pos: QPointF, phase: str) -> None:
        if phase == "start":
            self.state.checkpoint()  # the whole stroke is one undo step
            self._last_paint = pos
        last = self._last_paint or pos
        # Fill the gap since the last mouse event so a fast stroke has no holes.
        steps = max(1, math.ceil(math.hypot(pos.x() - last.x(), pos.y() - last.y()) / 0.5))
        cells = np.zeros((NROWS, NCOLS), dtype=bool)
        for k in range(steps + 1):
            t = k / steps
            p = QPointF(last.x() + t * (pos.x() - last.x()), last.y() + t * (pos.y() - last.y()))
            cells |= self._cells(p)
        self.state.paint(cells, masked=self.tool == "brush", record=False)
        self._last_paint = None if phase == "finish" else pos
        self.changed.emit()

    def _click_tube(self, pos: QPointF, shift: bool) -> None:
        info = pixel_info(pos.x(), pos.y())
        if info is None:
            return
        cols = bank_columns(info.bank) if shift else [info.x]
        masked = self.state.toggle_columns(cols)
        what = f"{info.panel} bank{info.bank}" if shift else f"tube x={info.x}"
        self.message.emit(f"{'masked' if masked else 'unmasked'} {what}")
        self.changed.emit()

    def _click_polygon(self, pos: QPointF, double: bool) -> None:
        if double:
            self.finish_polygon()
            return
        self._poly.append(pos)
        xs = [p.x() for p in self._poly]
        ys = [p.y() for p in self._poly]
        self._poly_line.setData(xs + xs[:1], ys + ys[:1])

    def finish_polygon(self) -> bool:
        """Close the polygon being drawn (double-click / Enter). False if < 3 corners."""
        points = self._dedupe(self._poly)
        self.cancel()
        if len(points) < 3:
            if points:
                self.message.emit("a polygon needs at least 3 corners")
            return False
        o = VIEW_OFFSET
        self.add_shape(Polygon(tuple((p.x() - o, p.y() - o) for p in points)))
        return True

    @staticmethod
    def _dedupe(points: list[QPointF]) -> list[QPointF]:
        out: list[QPointF] = []
        for p in points:
            if not out or math.hypot(p.x() - out[-1].x(), p.y() - out[-1].y()) > 1e-6:
                out.append(p)
        return out

    # -- shapes and ROIs ------------------------------------------------------------

    def add_shape(self, shape: Shape) -> None:
        self.state.add_shape(shape)
        self._add_roi(shape)
        self.changed.emit()

    def _add_roi(self, shape: Shape) -> None:
        roi = roi_for_shape(shape)
        roi.sigRegionChangeStarted.connect(self._on_roi_started)
        roi.sigRegionChanged.connect(self._on_roi_changed)
        roi.sigRemoveRequested.connect(self._on_roi_remove)
        roi.sigClicked.connect(self._on_roi_clicked)
        roi.setZValue(15)
        self.view.plot.addItem(roi)
        self._rois.append(roi)

    def sync_rois(self) -> None:
        """Rebuild every ROI from the state's shapes (after undo, redo, load, clear)."""
        self._syncing = True
        try:
            for roi in self._rois:
                self.view.plot.removeItem(roi)
            self._rois.clear()
            self._selected = None
            for shape in self.state.shapes:
                self._add_roi(shape)
        finally:
            self._syncing = False

    @property
    def rois(self) -> list[pg.ROI]:
        return list(self._rois)

    def _on_roi_started(self, roi: pg.ROI) -> None:
        if not self._syncing:
            self.state.checkpoint()  # one undo step per move / resize

    def _on_roi_changed(self, roi: pg.ROI) -> None:
        if self._syncing or roi not in self._rois:
            return
        self.state.set_shape(self._rois.index(roi), shape_for_roi(roi), record=False)
        self.changed.emit()

    def _on_roi_clicked(self, roi: pg.ROI) -> None:
        self.select(roi)

    def select(self, roi: pg.ROI | None) -> None:
        if self._selected is not None and self._selected in self._rois:
            self._selected.setPen(ROI_PEN)
        self._selected = roi
        if roi is not None:
            roi.setPen(SELECTED_PEN)

    def _on_roi_remove(self, roi: pg.ROI) -> None:
        if roi in self._rois:
            self.remove_roi(roi)

    def remove_roi(self, roi: pg.ROI) -> None:
        index = self._rois.index(roi)
        self.state.remove_shape(index)
        self.view.plot.removeItem(roi)
        self._rois.pop(index)
        if self._selected is roi:
            self._selected = None
        self.changed.emit()

    def delete_selected(self) -> bool:
        if self._selected is None or self._selected not in self._rois:
            self.message.emit("click a shape first to select it")
            return False
        self.remove_roi(self._selected)
        return True

    # -- whole-mask actions ------------------------------------------------------------

    def undo(self) -> bool:
        return self._history(self.state.undo(), "nothing to undo")

    def redo(self) -> bool:
        return self._history(self.state.redo(), "nothing to redo")

    def _history(self, done: bool, otherwise: str) -> bool:
        if not done:
            self.message.emit(otherwise)
            return False
        self.cancel()
        self.sync_rois()
        self.changed.emit()
        return True

    def set_inverted(self, inverted: bool) -> None:
        if inverted != self.state.inverted:
            self.state.set_inverted(inverted)
            self.changed.emit()

    def clear(self) -> None:
        if self.state.is_empty:
            return
        self.state.clear()
        self.sync_rois()
        self.changed.emit()

    def apply_spec(self, text: str) -> str:
        """``b3 t10-12`` → one full-height rectangle per run of columns (one undo step)."""
        cols = [c for c in parse_spec(text) if 0 <= c < NCOLS]  # ValueError on bad input
        runs = cols_to_runs(cols)
        if not runs:
            return f"no columns in {text!r}"
        o = VIEW_OFFSET
        self.state.checkpoint()
        for lo, hi in runs:
            shape = Rectangle(lo - o, -o, hi + o, NROWS - o)
            self.state.add_shape(shape, record=False)
            self._add_roi(shape)
        self.changed.emit()
        return f"+{len(runs)} rectangle{'s' if len(runs) != 1 else ''} over {len(cols)} tubes"

    def threshold(self, image: np.ndarray, low: float | None, high: float | None) -> int:
        n = self.state.threshold(image, low=low, high=high)
        self.changed.emit()
        return n

    def load(self, loaded: MaskBuilder | np.ndarray) -> None:
        self.state.load(loaded)
        self.sync_rois()
        self.changed.emit()


__all__ = ["MaskEditor"]
