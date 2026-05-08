"""Tests for the mask editor's controller (Phase 9.6.4).

The matplotlib widgets / event loop are not exercised here — the
:class:`MaskController` is wired to a real (in-memory) matplotlib
``Axes`` because that's the simplest and cheapest way to test the
patch-add / undo / clear plumbing. ``Agg`` backend keeps it headless.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg", force=True)

import matplotlib.pyplot as plt
import numpy as np
import pytest

from sansdir.mask.core import (
    Circle,
    MaskBuilder,
    Rectangle,
)
from sansdir.mask.detector import SourceMeta
from sansdir.mask.gui import MaskController


@pytest.fixture
def fig_ax():  # type: ignore[no-untyped-def]
    fig, ax = plt.subplots()
    yield ax
    plt.close(fig)


def _meta() -> SourceMeta:
    return SourceMeta(
        source_path=Path("/SNS/EQSANS/IPTS-12345/nexus/EQSANS_172749.nxs.h5"),
        instrument_name="EQ-SANS",
        detector_shape=(20, 20),
        pixel_ids=np.arange(400, dtype=np.int64),
        run_number="172749",
    )


# ---------------------------------------------------------------------------
# 1. Mode switching
# ---------------------------------------------------------------------------


def test_set_mode_accepts_known_modes(fig_ax) -> None:  # type: ignore[no-untyped-def]
    c = MaskController(fig_ax, MaskBuilder((20, 20)))
    for m in ("rectangle", "ellipse", "circle", "polygon", "edit"):
        c.set_mode(m)
        assert c.mode == m


def test_set_mode_rejects_unknown(fig_ax) -> None:  # type: ignore[no-untyped-def]
    c = MaskController(fig_ax, MaskBuilder((20, 20)))
    with pytest.raises(ValueError, match="unknown mode"):
        c.set_mode("octogram")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. Shape-add lockstep — builder gets a Shape, axes gets a Patch
# ---------------------------------------------------------------------------


def test_add_rectangle_appends_to_builder_and_axes(fig_ax) -> None:  # type: ignore[no-untyped-def]
    builder = MaskBuilder((20, 20))
    c = MaskController(fig_ax, builder)
    c.add_rectangle(2, 3, 7, 8)
    assert len(builder.shapes) == 1
    assert isinstance(builder.shapes[0], Rectangle)
    # The axes now carries one extra patch (over the imshow image).
    assert any(p.get_alpha() == 0.35 for p in fig_ax.patches)


def test_add_ellipse_circle_polygon(fig_ax) -> None:  # type: ignore[no-untyped-def]
    builder = MaskBuilder((20, 20))
    c = MaskController(fig_ax, builder)
    c.add_ellipse(10, 10, 4, 2)
    c.add_circle(5, 5, 3)
    c.add_polygon([(1, 1), (5, 1), (5, 5)])
    types = [type(s).__name__ for s in builder.shapes]
    assert types == ["Ellipse", "Circle", "Polygon"]


def test_add_polygon_requires_three_vertices(fig_ax) -> None:  # type: ignore[no-untyped-def]
    c = MaskController(fig_ax, MaskBuilder((20, 20)))
    with pytest.raises(ValueError, match="≥ 3"):
        c.add_polygon([(0, 0), (1, 1)])


# ---------------------------------------------------------------------------
# 3. Undo / clear / inverse
# ---------------------------------------------------------------------------


def test_undo_drops_last_shape_and_patch(fig_ax) -> None:  # type: ignore[no-untyped-def]
    builder = MaskBuilder((20, 20))
    c = MaskController(fig_ax, builder)
    c.add_rectangle(0, 0, 4, 4)
    c.add_circle(10, 10, 3)
    n_patches_before = len(fig_ax.patches)
    popped = c.undo()
    assert isinstance(popped, Circle)
    assert len(builder.shapes) == 1
    assert len(fig_ax.patches) == n_patches_before - 1


def test_undo_returns_none_when_empty(fig_ax) -> None:  # type: ignore[no-untyped-def]
    c = MaskController(fig_ax, MaskBuilder((20, 20)))
    assert c.undo() is None


def test_clear_drops_all_shapes_and_patches(fig_ax) -> None:  # type: ignore[no-untyped-def]
    builder = MaskBuilder((20, 20))
    c = MaskController(fig_ax, builder)
    c.add_rectangle(0, 0, 4, 4)
    c.add_circle(10, 10, 3)
    c.clear()
    assert builder.shapes == []
    # All overlay patches gone (some other patches may exist if this
    # ax had decorations, but ours are removed).
    overlays = [p for p in fig_ax.patches if p.get_alpha() == 0.35]
    assert overlays == []


def test_toggle_inverse_round_trip(fig_ax) -> None:  # type: ignore[no-untyped-def]
    c = MaskController(fig_ax, MaskBuilder((20, 20)))
    assert c.toggle_inverse() is True
    assert c.toggle_inverse() is False


# ---------------------------------------------------------------------------
# 4. Save — produces a Mantid-loadable file + the log sidecar
# ---------------------------------------------------------------------------


def test_save_writes_nxs_and_log(tmp_path, fig_ax) -> None:  # type: ignore[no-untyped-def]
    builder = MaskBuilder((20, 20))
    c = MaskController(fig_ax, builder)
    c.add_rectangle(2, 2, 5, 5)
    c.add_circle(15, 15, 3)
    out_path = tmp_path / "test_mask.nxs"
    out, log, stats = c.save(_meta(), out_path, "nxs")
    assert out == out_path
    assert out.exists()
    assert log.exists()
    payload = json.loads(log.read_text(encoding="utf-8"))
    # Round-trips via from_log → identical builder → identical mask.
    rebuilt = MaskBuilder.from_log(log)
    assert np.array_equal(rebuilt.build(), builder.build())
    assert payload["stats"]["masked_pixels"] == stats["masked_pixels"]


def test_save_xml(tmp_path, fig_ax) -> None:  # type: ignore[no-untyped-def]
    builder = MaskBuilder((20, 20))
    c = MaskController(fig_ax, builder)
    c.add_rectangle(0, 0, 3, 3)
    out, log, stats = c.save(_meta(), tmp_path / "m.xml", "xml")
    assert out.exists() and log.exists()
    text = out.read_text(encoding="utf-8")
    assert "<detector-masking>" in text
    # 4x4 rectangle at the corner = 16 masked pixels.
    assert stats["masked_pixels"] == 16


def test_save_npy(tmp_path, fig_ax) -> None:  # type: ignore[no-untyped-def]
    builder = MaskBuilder((20, 20))
    c = MaskController(fig_ax, builder)
    c.add_rectangle(0, 0, 1, 1)
    out, _log, _ = c.save(_meta(), tmp_path / "m.npy", "npy")
    arr = np.load(out)
    assert arr.shape == (20, 20)
    # 2x2 inclusive rectangle = 4 cells.
    assert arr.sum() == 4


def test_save_unknown_format_raises(tmp_path, fig_ax) -> None:  # type: ignore[no-untyped-def]
    c = MaskController(fig_ax, MaskBuilder((20, 20)))
    c.add_rectangle(0, 0, 2, 2)
    with pytest.raises(ValueError, match="unknown format"):
        c.save(_meta(), tmp_path / "m.bogus", "bogus")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 5. End-to-end: build → save → reload → matches
# ---------------------------------------------------------------------------


def test_round_trip_nxs_via_h5py(tmp_path, fig_ax) -> None:  # type: ignore[no-untyped-def]
    """The masked-spectra count in the .nxs equals the builder's mask sum."""
    import h5py

    builder = MaskBuilder((20, 20))
    c = MaskController(fig_ax, builder)
    c.add_circle(10, 10, 4)
    c.add_rectangle(0, 0, 1, 1)
    out_path = tmp_path / "rt.nxs"
    c.save(_meta(), out_path, "nxs")
    n_total = _meta().pixel_ids.size
    expected_unmasked = n_total - int(builder.build().sum())
    with h5py.File(out_path, "r") as f:
        # On-disk encoding is inverted: ``diff(indices)`` is the
        # per-detector *unmasked* flag (1 = kept, 0 = masked) so that
        # masked regions plot grey, matching mask_4m2.nxs.
        indices = f["mantid_workspace_1/event_workspace/indices"][()]
    assert int(np.diff(indices).sum()) == expected_unmasked


# ---------------------------------------------------------------------------
# 6. Edit mode — delete-by-index, translate, patch indexing
# ---------------------------------------------------------------------------


def test_delete_by_index_drops_correct_shape_and_patch(fig_ax) -> None:  # type: ignore[no-untyped-def]
    builder = MaskBuilder((20, 20))
    c = MaskController(fig_ax, builder)
    c.add_rectangle(0, 0, 4, 4)
    c.add_circle(10, 10, 3)
    c.add_rectangle(15, 15, 18, 18)
    popped = c.delete(1)  # the middle one (the circle)
    assert isinstance(popped, Circle)
    assert len(builder.shapes) == 2
    assert isinstance(builder.shapes[0], Rectangle)
    assert isinstance(builder.shapes[1], Rectangle)
    overlays = [p for p in fig_ax.patches if p.get_alpha() == 0.35]
    assert len(overlays) == 2


def test_delete_out_of_range_returns_none(fig_ax) -> None:  # type: ignore[no-untyped-def]
    c = MaskController(fig_ax, MaskBuilder((20, 20)))
    c.add_rectangle(0, 0, 1, 1)
    assert c.delete(99) is None
    assert c.delete(-1) is None
    assert len(c.builder.shapes) == 1


def test_index_of_patch_finds_the_overlay(fig_ax) -> None:  # type: ignore[no-untyped-def]
    c = MaskController(fig_ax, MaskBuilder((20, 20)))
    c.add_rectangle(0, 0, 4, 4)
    c.add_circle(10, 10, 3)
    overlay_patches = c.patches
    assert c.index_of_patch(overlay_patches[1]) == 1
    # An unrelated patch isn't in the list.
    from matplotlib.patches import Rectangle as MplRect
    other = MplRect((0, 0), 1, 1)
    assert c.index_of_patch(other) is None


def test_translate_rectangle_moves_shape_and_patch(fig_ax) -> None:  # type: ignore[no-untyped-def]
    builder = MaskBuilder((20, 20))
    c = MaskController(fig_ax, builder)
    c.add_rectangle(2, 3, 7, 8)
    new_shape = c.translate(0, dx=4, dy=2)
    assert isinstance(new_shape, Rectangle)
    assert (new_shape.x0, new_shape.y0, new_shape.x1, new_shape.y1) == (6, 5, 11, 10)
    # Builder state mirrors the translated shape.
    rect = builder.shapes[0]
    assert isinstance(rect, Rectangle)
    assert (rect.x0, rect.y0) == (6, 5)


def test_translate_circle_moves_centre_only(fig_ax) -> None:  # type: ignore[no-untyped-def]
    builder = MaskBuilder((30, 30))
    c = MaskController(fig_ax, builder)
    c.add_circle(10, 10, 5)
    new_shape = c.translate(0, dx=2, dy=-3)
    assert isinstance(new_shape, Circle)
    assert (new_shape.xc, new_shape.yc, new_shape.r) == (12, 7, 5)


def test_translate_ellipse_polygon(fig_ax) -> None:  # type: ignore[no-untyped-def]
    builder = MaskBuilder((30, 30))
    c = MaskController(fig_ax, builder)
    from sansdir.mask.core import Ellipse, Polygon

    c.add_ellipse(10, 10, 4, 2)
    c.add_polygon([(0, 0), (5, 0), (5, 5)])
    e = c.translate(0, 1, 1)
    assert isinstance(e, Ellipse)
    assert (e.xc, e.yc, e.rx, e.ry) == (11, 11, 4, 2)
    p = c.translate(1, 2, 0)
    assert isinstance(p, Polygon)
    assert p.vertices == ((2, 0), (7, 0), (7, 5))


def test_translate_invalid_index_returns_none(fig_ax) -> None:  # type: ignore[no-untyped-def]
    c = MaskController(fig_ax, MaskBuilder((20, 20)))
    assert c.translate(0, 1, 1) is None  # nothing to translate


def test_translate_then_build_reflects_new_position(fig_ax) -> None:  # type: ignore[no-untyped-def]
    """``MaskBuilder.build()`` after a translate sees the moved shape."""
    builder = MaskBuilder((20, 20))
    c = MaskController(fig_ax, builder)
    c.add_rectangle(0, 0, 3, 3)  # 4x4 inclusive at origin
    before = builder.build().copy()
    c.translate(0, dx=10, dy=10)
    after = builder.build()
    assert before.sum() == after.sum() == 16
    # The masked region moved from the corner to (10..13, 10..13).
    assert before[0, 0] == 1 and after[0, 0] == 0
    assert after[10, 10] == 1


def test_undo_uses_delete_so_the_two_paths_agree(fig_ax) -> None:  # type: ignore[no-untyped-def]
    """``undo`` and ``delete(last_index)`` are equivalent."""
    builder = MaskBuilder((20, 20))
    c = MaskController(fig_ax, builder)
    c.add_rectangle(0, 0, 1, 1)
    c.add_circle(5, 5, 2)
    last = c.undo()
    assert isinstance(last, Circle)
    assert len(builder.shapes) == 1
