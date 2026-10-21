"""Tests for the pure mask-building core (Phase 9.6.1).

Order matters here: the convention test runs first and gates everything
else. Per-shape rasterise tests follow with hand-verified 10x10 fixtures
small enough to read by eye.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from sansdir.mask.core import (
    Circle,
    Ellipse,
    MaskBuilder,
    Polygon,
    Rectangle,
    shape_from_dict,
)

# ---------------------------------------------------------------------------
# 1. Convention test — gates the entire phase
# ---------------------------------------------------------------------------


def test_mask_convention_1_means_masked() -> None:
    """Mantid: 1 = masked (excluded), 0 = kept.

    Cited in the SaveMask v1 docs and matches SpecialWorkspace2D, the
    type behind MaskWorkspace. Inverting this would silently feed the
    wrong detectors to downstream reduction — pin it here first.
    """
    b = MaskBuilder((10, 10))
    b.add(Rectangle(2, 2, 5, 5))
    m = b.build()
    assert m.dtype == np.uint8
    assert m[3, 3] == 1, "interior must be masked (1)"
    assert m[0, 0] == 0, "exterior must be kept (0)"
    # 4x4 inclusive rectangle = 16 cells.
    assert m.sum() == 16


# ---------------------------------------------------------------------------
# 2. Per-shape rasterise — hand-verified 10x10 fixtures
# ---------------------------------------------------------------------------


def test_rectangle_inclusive_corners() -> None:
    m = Rectangle(0, 0, 0, 9).rasterise((10, 10))
    # Only column 0 should be inside.
    assert m[:, 0].all()
    assert not m[:, 1:].any()
    assert m.sum() == 10


def test_rectangle_swapped_corners_normalised() -> None:
    """Rectangle(x1<x0 or y1<y0) still rasterises the same region."""
    a = Rectangle(2, 3, 7, 8).rasterise((10, 10))
    b = Rectangle(7, 8, 2, 3).rasterise((10, 10))
    assert np.array_equal(a, b)


def test_circle_central() -> None:
    m = Circle(5, 5, 2).rasterise((10, 10))
    # Centre cell.
    assert m[5, 5]
    # Cells at distance 2 from centre (axes) — included.
    assert m[5, 7]
    assert m[7, 5]
    # Cell at distance > 2 — excluded.
    assert not m[8, 8]
    # Manual count: a Bresenham-ish disc of radius 2 covers 13 cells.
    assert m.sum() == 13


def test_ellipse_distinct_radii() -> None:
    m = Ellipse(5, 5, 4, 1).rasterise((10, 10))
    # Row 5 contains cols 1..9 (centre line); rows 4 and 6 each have
    # only the tangent cell at x=5; everywhere else is outside.
    assert m[5, :].sum() == 9
    assert m[4, :].sum() == 1
    assert m[6, :].sum() == 1
    assert m[3, :].sum() == 0
    assert m[7, :].sum() == 0
    assert m.sum() == 11


def test_polygon_triangle() -> None:
    """Right triangle covering ~half a 4x4 grid (lower-left).

    matplotlib's :class:`Path.contains_points` is strict about the
    boundary: vertices and edges may or may not be included. We assert
    on cells safely inside the triangle and safely outside.
    """
    m = Polygon(((0, 0), (3, 0), (0, 3))).rasterise((4, 4))
    # Strictly interior cells must be inside.
    assert m[1, 1]
    # Strictly outside the triangle (upper-right corner).
    assert not m[3, 3]
    assert not m[2, 3]
    # Total cell count is fixed by matplotlib's path algorithm.
    assert m.sum() > 0


def test_polygon_requires_three_vertices() -> None:
    with pytest.raises(ValueError, match="at least 3"):
        Polygon(((0, 0), (1, 1)))


# ---------------------------------------------------------------------------
# 3. MaskBuilder behaviour — union, inverse, remove
# ---------------------------------------------------------------------------


def test_builder_unions_overlapping_shapes() -> None:
    b = MaskBuilder((10, 10))
    b.add(Rectangle(0, 0, 4, 4))
    b.add(Rectangle(3, 3, 7, 7))
    m = b.build()
    # Union = rect-1 (5x5=25) + rect-2 (5x5=25) - overlap (2x2=4).
    assert m.sum() == 25 + 25 - 4


def test_builder_inverse_flips_final_union() -> None:
    """``inverse`` flips the *final* mask, not individual shapes."""
    b = MaskBuilder((10, 10), inverse=True)
    b.add(Rectangle(2, 2, 5, 5))
    m = b.build()
    # 100 cells total - 16 shape cells = 84 inverted "masked".
    assert m.sum() == 100 - 16
    assert m[3, 3] == 0, "shape interior is now KEPT (0) under inverse"
    assert m[0, 0] == 1, "outside the shape is now MASKED (1) under inverse"


def test_builder_remove_drops_shape() -> None:
    b = MaskBuilder((10, 10))
    b.add(Rectangle(0, 0, 4, 4))
    idx = b.add(Rectangle(5, 5, 9, 9))
    b.remove(idx)
    m = b.build()
    assert m.sum() == 25  # only the first rectangle survives


def test_builder_clear() -> None:
    b = MaskBuilder((10, 10))
    b.add(Rectangle(0, 0, 4, 4))
    b.clear()
    assert b.build().sum() == 0


# ---------------------------------------------------------------------------
# 4. Round-trip via mask_log.json
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "shape",
    [
        Rectangle(1.5, 2.5, 7.0, 8.0),
        Ellipse(5, 5, 3, 1.5),
        Circle(5, 5, 2.5),
        Polygon(((1, 1), (8, 1), (8, 8), (1, 8))),
    ],
)
def test_shape_dict_round_trip(shape) -> None:  # type: ignore[no-untyped-def]
    """``shape → dict → shape`` rasterises identically."""
    redone = shape_from_dict(shape.to_dict())
    assert np.array_equal(shape.rasterise((10, 10)), redone.rasterise((10, 10)))


def test_shape_from_dict_unknown_type_raises() -> None:
    with pytest.raises(ValueError, match="unknown shape"):
        shape_from_dict({"type": "octogram"})


def test_builder_dict_round_trip() -> None:
    b1 = MaskBuilder((20, 20), inverse=True)
    b1.add(Rectangle(2, 2, 8, 8))
    b1.add(Circle(15, 15, 3))
    data = b1.to_dict()
    # Survives a JSON encode/decode (the actual log-file path).
    data2 = json.loads(json.dumps(data))
    b2 = MaskBuilder.from_dict(data2)
    assert b2.detector_shape == b1.detector_shape
    assert b2.inverse == b1.inverse
    assert np.array_equal(b1.build(), b2.build())


def test_builder_from_log_reads_json_file(tmp_path: Path) -> None:
    log = tmp_path / "x.mask_log.json"
    payload = {
        "detector_shape": [10, 10],
        "inverse": False,
        "shapes": [{"type": "rectangle", "x0": 1, "y0": 1, "x1": 4, "y1": 4}],
    }
    log.write_text(json.dumps(payload), encoding="utf-8")
    b = MaskBuilder.from_log(log)
    assert len(b.shapes) == 1
    assert isinstance(b.shapes[0], Rectangle)


def test_from_dict_rejects_bad_detector_shape() -> None:
    with pytest.raises(ValueError, match="detector_shape"):
        MaskBuilder.from_dict({"detector_shape": [10], "shapes": []})


# ---------------------------------------------------------------------------
# PixelSet (Phase 9.10.3): brush / eraser cells from the detector viewer
# ---------------------------------------------------------------------------


def test_index_ranges_round_trip() -> None:
    from sansdir.mask.core import indices_to_text, text_to_indices

    assert indices_to_text([42, 5, 9, 10, 11, 11]) == "5,9-11,42"
    assert text_to_indices("5,9-11,42").tolist() == [5, 9, 10, 11, 42]
    assert indices_to_text([]) == "" and text_to_indices("").size == 0
    with pytest.raises(ValueError):
        text_to_indices("9-5")


def test_pixelset_masks_on_cells_and_clears_off_cells() -> None:
    from sansdir.mask.core import PixelSet

    builder = MaskBuilder(detector_shape=(4, 5))
    builder.add(Rectangle(0, 0, 4, 3))  # everything
    builder.add(PixelSet(on=(), off=(0, 6)))  # flat index = row * 5 + col
    mask = builder.build()
    assert mask.sum() == 18 and mask[0, 0] == 0 and mask[1, 1] == 0


def test_pixelset_order_matters_later_shapes_win() -> None:
    from sansdir.mask.core import PixelSet

    builder = MaskBuilder(detector_shape=(4, 5))
    builder.add(PixelSet(on=(3,), off=(0,)))
    builder.add(Rectangle(0, 0, 0, 0))  # re-masks cell 0
    assert builder.build()[0, 0] == 1 and builder.build()[0, 3] == 1


def test_pixelset_round_trips_through_dict_as_ranges() -> None:
    from sansdir.mask.core import PixelSet

    on = np.zeros((4, 5), dtype=bool)
    on[1, :] = True
    shape = PixelSet.from_cells(on, np.eye(4, 5, dtype=bool))
    data = shape.to_dict()
    assert data == {"type": "pixels", "on": "5-9", "off": "0,6,12,18"}
    assert shape_from_dict(data) == shape
    assert shape_from_dict({"type": "pixels", "on": [5, 6]}) == PixelSet(on=(5, 6))


def test_pixelset_outside_the_detector_is_an_error() -> None:
    from sansdir.mask.core import PixelSet

    with pytest.raises(ValueError, match="outside"):
        PixelSet(on=(20,)).rasterise((4, 5))
