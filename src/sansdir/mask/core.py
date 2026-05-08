"""Shape primitives and the :class:`MaskBuilder` that unions them.

Mask convention is **Mantid's** — ``1 = masked`` (excluded from
analysis), ``0 = kept``. This is the same convention
``Mantid::DataObjects::SpecialWorkspace2D`` (the type behind
``MaskWorkspace``) uses, and the same one ``Mantid::Algorithms::SaveMask``
v1 reads back when re-loading. We pin the convention with the very first
unit test in :mod:`tests.mask.test_core`; nothing else lands until that
test is green.

All coordinates are in pixel space, ``(x, y)`` with `x` running across
tubes (cols, 0..n_cols-1) and `y` running along pixels-per-tube
(rows, 0..n_rows-1). The detector image we draw on is laid out
``(n_rows, n_cols)`` to match :func:`sansdir.plot.hdf5_detector.load_eqsans_raw`.

Rasterisation is fully vectorised — no Python pixel loops — so a
256x192 detector rasterises in well under a millisecond per shape.
``Polygon`` uses :class:`matplotlib.path.Path` for the inside test;
the rest are closed-form numpy meshgrids.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

# ---------------------------------------------------------------------------
# Shape primitives
# ---------------------------------------------------------------------------


class Shape(ABC):
    """A drawable region with a vectorised rasteriser."""

    type_name: ClassVar[str]

    @abstractmethod
    def rasterise(self, detector_shape: tuple[int, int]) -> np.ndarray:
        """Return a ``bool`` array of ``detector_shape`` — ``True`` inside."""

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for ``mask_log.json`` round-trip."""


def _grid(detector_shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(xs, ys)`` index meshgrids of shape ``detector_shape``."""
    n_rows, n_cols = detector_shape
    ys = np.arange(n_rows, dtype=np.float64)[:, None]
    xs = np.arange(n_cols, dtype=np.float64)[None, :]
    return xs, ys


@dataclass(frozen=True, slots=True)
class Rectangle(Shape):
    """Axis-aligned rectangle. Inclusive of both corners."""

    x0: float
    y0: float
    x1: float
    y1: float

    type_name: ClassVar[str] = "rectangle"

    def rasterise(self, detector_shape: tuple[int, int]) -> np.ndarray:
        xs, ys = _grid(detector_shape)
        x_lo, x_hi = sorted((self.x0, self.x1))
        y_lo, y_hi = sorted((self.y0, self.y1))
        return (xs >= x_lo) & (xs <= x_hi) & (ys >= y_lo) & (ys <= y_hi)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type_name,
            "x0": float(self.x0),
            "y0": float(self.y0),
            "x1": float(self.x1),
            "y1": float(self.y1),
        }


@dataclass(frozen=True, slots=True)
class Ellipse(Shape):
    """Axis-aligned ellipse with separate x/y radii."""

    xc: float
    yc: float
    rx: float
    ry: float

    type_name: ClassVar[str] = "ellipse"

    def rasterise(self, detector_shape: tuple[int, int]) -> np.ndarray:
        xs, ys = _grid(detector_shape)
        rx = max(self.rx, 1e-12)
        ry = max(self.ry, 1e-12)
        return ((xs - self.xc) / rx) ** 2 + ((ys - self.yc) / ry) ** 2 <= 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type_name,
            "xc": float(self.xc),
            "yc": float(self.yc),
            "rx": float(self.rx),
            "ry": float(self.ry),
        }


@dataclass(frozen=True, slots=True)
class Circle(Shape):
    """Circle. Implemented as :class:`Ellipse` with ``rx == ry``."""

    xc: float
    yc: float
    r: float

    type_name: ClassVar[str] = "circle"

    def rasterise(self, detector_shape: tuple[int, int]) -> np.ndarray:
        xs, ys = _grid(detector_shape)
        r = max(self.r, 1e-12)
        return ((xs - self.xc) ** 2 + (ys - self.yc) ** 2) <= r * r

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type_name,
            "xc": float(self.xc),
            "yc": float(self.yc),
            "r": float(self.r),
        }


@dataclass(frozen=True, slots=True)
class Polygon(Shape):
    """Closed polygon. Inside test via :class:`matplotlib.path.Path`."""

    vertices: tuple[tuple[float, float], ...]

    type_name: ClassVar[str] = "polygon"

    def __post_init__(self) -> None:
        if len(self.vertices) < 3:
            raise ValueError(
                f"Polygon needs at least 3 vertices, got {len(self.vertices)}"
            )

    def rasterise(self, detector_shape: tuple[int, int]) -> np.ndarray:
        # Lazy-import: matplotlib.path is light but we keep it out of the
        # cold-start budget for users who don't touch the mask module.
        from matplotlib.path import Path as MplPath

        n_rows, n_cols = detector_shape
        xs, ys = np.meshgrid(
            np.arange(n_cols, dtype=np.float64),
            np.arange(n_rows, dtype=np.float64),
        )
        points = np.column_stack([xs.ravel(), ys.ravel()])
        verts = np.asarray(self.vertices, dtype=np.float64)
        inside = MplPath(verts).contains_points(points)
        return inside.reshape(n_rows, n_cols)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type_name,
            "vertices": [[float(x), float(y)] for x, y in self.vertices],
        }


_SHAPE_REGISTRY: dict[str, type[Shape]] = {
    Rectangle.type_name: Rectangle,
    Ellipse.type_name: Ellipse,
    Circle.type_name: Circle,
    Polygon.type_name: Polygon,
}


def shape_from_dict(data: dict[str, Any]) -> Shape:
    """Inverse of :meth:`Shape.to_dict`. Raises ``ValueError`` on unknown type."""
    type_name = data.get("type")
    cls = _SHAPE_REGISTRY.get(type_name) if isinstance(type_name, str) else None
    if cls is None:
        raise ValueError(f"unknown shape type: {type_name!r}")
    if cls is Polygon:
        return Polygon(
            vertices=tuple(
                (float(x), float(y))
                for x, y in data.get("vertices", [])
            )
        )
    payload = {k: v for k, v in data.items() if k != "type"}
    return cls(**payload)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


@dataclass
class MaskBuilder:
    """Accumulates :class:`Shape`s and produces the binary mask.

    Layout convention: shape coordinates are pixel-space ``(x, y)``;
    detector_shape is ``(n_rows, n_cols)``; the produced mask has
    ``mask[y, x]`` indexing — same as the displayed heatmap.

    The ``inverse`` flag flips the *final union* (not individual
    shapes), so toggling it is cheap and reversible.
    """

    detector_shape: tuple[int, int]
    inverse: bool = False
    shapes: list[Shape] = field(default_factory=list)

    def add(self, shape: Shape) -> int:
        """Append ``shape`` and return its index."""
        self.shapes.append(shape)
        return len(self.shapes) - 1

    def remove(self, index: int) -> Shape:
        """Pop the shape at ``index``."""
        return self.shapes.pop(index)

    def clear(self) -> None:
        self.shapes.clear()

    def build(self) -> np.ndarray:
        """Union all shapes, apply ``inverse``, return ``uint8`` ``(rows, cols)``.

        Convention: ``1 == masked`` (excluded from analysis), ``0 == kept``.
        Mirrors Mantid's :class:`SpecialWorkspace2D` which is the
        underlying type of a ``MaskWorkspace`` and the format
        :func:`Mantid::Algorithms::SaveMask` v1 reads back.
        """
        out = np.zeros(self.detector_shape, dtype=bool)
        for shape in self.shapes:
            out |= shape.rasterise(self.detector_shape)
        if self.inverse:
            out = ~out
        return out.astype(np.uint8)

    # ------------------------------------------------------------------
    # Round-trip via mask_log.json
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector_shape": list(self.detector_shape),
            "inverse": bool(self.inverse),
            "shapes": [s.to_dict() for s in self.shapes],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MaskBuilder:
        ds = data.get("detector_shape")
        if not (isinstance(ds, Sequence) and len(ds) == 2):
            raise ValueError("from_dict: detector_shape must be a 2-tuple")
        b = cls(detector_shape=(int(ds[0]), int(ds[1])), inverse=bool(data.get("inverse", False)))
        for sd in data.get("shapes", []):
            b.add(shape_from_dict(sd))
        return b

    @classmethod
    def from_log(cls, path: Path | str) -> MaskBuilder:
        """Reconstruct from a ``mask_log.json`` written by :mod:`writers`."""
        text = Path(path).read_text(encoding="utf-8")
        data = json.loads(text)
        return cls.from_dict(data)


__all__ = [
    "Circle",
    "Ellipse",
    "MaskBuilder",
    "Polygon",
    "Rectangle",
    "Shape",
    "shape_from_dict",
]
