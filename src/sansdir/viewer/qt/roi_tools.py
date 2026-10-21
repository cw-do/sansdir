"""pyqtgraph ROIs ↔ :mod:`sansdir.mask.core` shapes.

Shapes live in the mask engine's pixel space (cell ``(col, row)`` centred on
the integer point); ROIs live in view space (the cell spans
``[col, col+1) x [row, row+1)``). The two differ by
:data:`~sansdir.viewer.masking.VIEW_OFFSET`. Every ROI is axis-aligned
(no rotate handles), because the engine's shapes are.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt

from sansdir.mask.core import Circle, Ellipse, Polygon, Rectangle, Shape
from sansdir.viewer.masking import VIEW_OFFSET

ROI_PEN = pg.mkPen((255, 225, 0), width=2)
SELECTED_PEN = pg.mkPen((0, 230, 255), width=3)
HOVER_PEN = pg.mkPen((255, 255, 255), width=2)


def roi_for_shape(shape: Shape) -> pg.ROI:
    """An editable ROI drawing ``shape``. Raises ``TypeError`` for non-geometric shapes."""
    o = VIEW_OFFSET
    common = {"pen": ROI_PEN, "hoverPen": HOVER_PEN, "removable": True}
    roi: pg.ROI
    if isinstance(shape, Rectangle):
        x_lo, x_hi = sorted((shape.x0, shape.x1))
        y_lo, y_hi = sorted((shape.y0, shape.y1))
        roi = pg.RectROI(
            (x_lo + o, y_lo + o), (x_hi - x_lo, y_hi - y_lo), sideScalers=True, **common
        )
        roi.addScaleHandle([0, 0], [1, 1])
    elif isinstance(shape, Circle):
        r = shape.r
        roi = pg.CircleROI((shape.xc - r + o, shape.yc - r + o), (2 * r, 2 * r), **common)
    elif isinstance(shape, Ellipse):
        pos = (shape.xc - shape.rx + o, shape.yc - shape.ry + o)
        roi = pg.EllipseROI(pos, (2 * shape.rx, 2 * shape.ry), **common)
        for handle in [h["item"] for h in roi.handles if h["type"] == "r"]:
            roi.removeHandle(handle)
        roi.addScaleHandle([1, 0.5], [0.5, 0.5])
        roi.addScaleHandle([0.5, 1], [0.5, 0.5])
    elif isinstance(shape, Polygon):
        points = [(x + o, y + o) for x, y in shape.vertices]
        roi = pg.PolyLineROI(points, closed=True, **common)
    else:
        raise TypeError(f"no ROI for {type(shape).__name__}")
    roi.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
    return roi


def shape_for_roi(roi: pg.ROI) -> Shape:
    """The shape an ROI currently describes (after a move or resize)."""
    o = VIEW_OFFSET
    if isinstance(roi, pg.PolyLineROI):
        verts = []
        for handle in roi.getHandles():
            p = roi.mapToParent(handle.pos())
            verts.append((p.x() - o, p.y() - o))
        return Polygon(tuple(verts))
    pos, size = roi.pos(), roi.size()
    w, h = abs(size.x()), abs(size.y())
    x_lo, y_lo = min(pos.x(), pos.x() + size.x()), min(pos.y(), pos.y() + size.y())
    if isinstance(roi, pg.CircleROI):
        return Circle(x_lo + w / 2 - o, y_lo + h / 2 - o, w / 2)
    if isinstance(roi, pg.EllipseROI):
        return Ellipse(x_lo + w / 2 - o, y_lo + h / 2 - o, w / 2, h / 2)
    return Rectangle(x_lo - o, y_lo - o, x_lo + w - o, y_lo + h - o)


__all__ = ["ROI_PEN", "SELECTED_PEN", "roi_for_shape", "shape_for_roi"]
