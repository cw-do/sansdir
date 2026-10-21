"""The viewer's mask state, mask-file readers and save (Phase 9.10.3, Qt-free)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from sansdir.mask.core import Circle, MaskBuilder, PixelSet, Rectangle
from sansdir.mask.detector import SourceMeta
from sansdir.mask.writers import write_npy, write_nxs, write_xml
from sansdir.viewer.geometry import detector_ids, info_for_detid
from sansdir.viewer.masking import (
    DETECTOR_SHAPE,
    MaskState,
    brush_cells,
    cells_for_detids,
    default_output,
    read_mask_file,
    save_mask,
    threshold_cells,
)

REAL_MASK = Path(__file__).parents[1] / "data" / "mask_4m2.nxs"


def _cells(rows: slice, cols: slice) -> np.ndarray:
    cells = np.zeros(DETECTOR_SHAPE, dtype=bool)
    cells[rows, cols] = True
    return cells


def _meta(tmp_path: Path) -> SourceMeta:
    return SourceMeta(
        source_path=tmp_path / "EQSANS_1.nxs.h5",
        instrument_name="EQSANS",
        detector_shape=DETECTOR_SHAPE,
        pixel_ids=detector_ids().reshape(-1),
        run_number="1",
    )


# -- the mask model --------------------------------------------------------------


def test_eraser_beats_shapes_and_brush_adds_to_them() -> None:
    state = MaskState()
    state.add_shape(Rectangle(0, 0, 9, 9))  # cells 0..9 inclusive
    state.paint(_cells(slice(0, 2), slice(0, 2)), masked=False)
    state.paint(_cells(slice(100, 101), slice(50, 52)), masked=True)
    mask = state.build()
    assert mask.sum() == 100 - 4 + 2
    assert not mask[0, 0] and mask[5, 5] and mask[100, 51]


def test_brushing_an_erased_cell_masks_it_again() -> None:
    state = MaskState()
    cell = _cells(slice(3, 4), slice(3, 4))
    state.paint(cell, masked=False)
    state.paint(cell, masked=True)
    assert state.build()[3, 3] and not state.off.any()


def test_invert_flips_the_final_mask() -> None:
    state = MaskState()
    state.add_shape(Rectangle(0, 0, 191, 127))  # bottom half
    state.set_inverted(True)
    mask = state.build()
    assert not mask[0].any() and mask[255].all()


def test_undo_redo_walk_the_history() -> None:
    state = MaskState()
    assert not state.can_undo and not state.modified
    state.add_shape(Circle(96, 128, 5))
    state.paint(_cells(slice(0, 1), slice(0, 192)), masked=True)
    full = state.build().copy()
    assert state.undo() and state.build().sum() < full.sum()
    assert state.undo() and not state.build().any()
    assert not state.undo()
    assert state.redo() and state.redo() and not state.redo()
    np.testing.assert_array_equal(state.build(), full)
    state.undo()
    state.set_inverted(True)  # a new edit drops the redo branch
    assert not state.can_redo


def test_a_drag_is_one_undo_step() -> None:
    state = MaskState()
    state.add_shape(Rectangle(0, 0, 5, 5))
    state.checkpoint()  # drag starts
    for dx in range(1, 6):
        state.set_shape(0, Rectangle(dx, 0, 5 + dx, 5), record=False)
    state.undo()
    assert state.shapes == [Rectangle(0, 0, 5, 5)]


def test_modified_tracks_saves() -> None:
    state = MaskState()
    state.add_shape(Rectangle(0, 0, 1, 1))
    assert state.modified
    state.mark_saved()
    assert not state.modified
    state.undo()
    assert state.modified


def test_tube_click_toggles() -> None:
    state = MaskState()
    assert state.toggle_columns([7]) is True
    assert state.build()[:, 7].all() and state.build().sum() == 256
    assert state.toggle_columns([7]) is False
    assert not state.build().any()
    state.add_shape(Rectangle(4, 0, 4, 100))  # part of tube 4
    assert state.toggle_columns([4, 5]) is True  # not all masked yet → mask
    assert state.build()[:, 4:6].all()


def test_threshold_masks_dead_and_hot_cells() -> None:
    image = np.full(DETECTOR_SHAPE, 50.0)
    image[0, :10] = 0
    image[10, 10] = 1e6
    assert threshold_cells(image, low=0).sum() == 10
    assert threshold_cells(image, high=1e5).sum() == 1
    assert not threshold_cells(image).any()
    state = MaskState()
    state.paint(_cells(slice(0, 1), slice(0, 5)), masked=True)
    assert state.threshold(image, low=0, high=1e5) == 6  # 5 were already masked
    assert state.build().sum() == 11


def test_brush_cells() -> None:
    assert brush_cells(10.2, 20.7, 0).sum() == 1 and brush_cells(10.2, 20.7, 0)[20, 10]
    disc = brush_cells(50.5, 50.5, 2)  # centred on cell (50, 50)
    assert disc[50, 50] and disc[52, 50] and not disc[53, 50] and disc.sum() == 13
    assert not brush_cells(-5, -5, 0).any()


def test_to_builder_reproduces_the_mask() -> None:
    state = MaskState()
    state.add_shape(Rectangle(10, 10, 60, 60))
    state.paint(_cells(slice(20, 30), slice(20, 30)), masked=False)
    state.paint(_cells(slice(200, 210), slice(150, 160)), masked=True)
    state.set_inverted(True)
    builder = state.to_builder()
    assert isinstance(builder.shapes[-1], PixelSet) and builder.inverse
    np.testing.assert_array_equal(builder.build().astype(bool), state.build())
    restored = MaskState()
    restored.load(MaskBuilder.from_dict(json.loads(json.dumps(builder.to_dict()))))
    np.testing.assert_array_equal(restored.build(), state.build())
    assert restored.shapes == [Rectangle(10, 10, 60, 60)]  # still editable


def test_loading_merges_and_keeps_inverse_only_when_empty() -> None:
    state = MaskState()
    state.add_shape(Rectangle(0, 0, 1, 1))
    other = MaskBuilder(DETECTOR_SHAPE, inverse=True)
    other.add(Circle(96, 128, 3))
    state.load(other)
    assert len(state.shapes) == 2 and not state.inverted
    state.load(_cells(slice(5, 6), slice(5, 6)))
    assert state.build()[5, 5]
    with pytest.raises(ValueError, match="detector"):
        state.load(MaskBuilder((4, 4)))


# -- reading mask files --------------------------------------------------------------


@pytest.mark.parametrize("writer", [write_xml, write_npy])
def test_read_back_what_the_writers_write(tmp_path: Path, writer) -> None:  # type: ignore[no-untyped-def]
    mask = _cells(slice(0, 40), slice(100, 120)) | _cells(slice(250, 256), slice(0, 192))
    suffix = ".xml" if writer is write_xml else ".npy"
    path = writer(tmp_path / f"m{suffix}", mask.astype(np.uint8), _meta(tmp_path))
    np.testing.assert_array_equal(read_mask_file(path), mask)


def test_read_back_the_legacy_nxs_writer(tmp_path: Path) -> None:
    mask = _cells(slice(0, 40), slice(100, 120))
    path = write_nxs(tmp_path / "m.nxs", mask.astype(np.uint8), _meta(tmp_path))
    np.testing.assert_array_equal(read_mask_file(path), mask)


@pytest.mark.skipif(not REAL_MASK.exists(), reason="tests/data/mask_4m2.nxs not present")
def test_read_a_real_mantid_mask() -> None:
    cells = read_mask_file(REAL_MASK)
    assert isinstance(cells, np.ndarray) and cells.sum() == 6380
    # The first flagged ID in the file's parameter map lands on its own cell.
    info = info_for_detid(35338)
    assert cells[info.y, info.x]


def test_read_mask_log_keeps_shapes(tmp_path: Path) -> None:
    builder = MaskBuilder(DETECTOR_SHAPE)
    builder.add(Circle(96, 128, 10))
    log = tmp_path / "x.mask_log.json"
    log.write_text(json.dumps({"sansdir_version": "x", **builder.to_dict()}))
    loaded = read_mask_file(log)
    assert isinstance(loaded, MaskBuilder) and loaded.shapes == [Circle(96, 128, 10)]


def test_read_rejects_non_masks(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "b.xml").write_text("<nothing/>")
    np.save(tmp_path / "c.npy", np.zeros((3, 3)))
    for name, match in [("a.txt", "not a mask"), ("b.xml", "detids"), ("c.npy", "shape")]:
        with pytest.raises(ValueError, match=match):
            read_mask_file(tmp_path / name)


def test_cells_for_detids_ignores_out_of_range() -> None:
    cells = cells_for_detids(np.array([0, 49151, 49152, -1]))
    assert cells.sum() == 2


# -- saving ------------------------------------------------------------------------


@pytest.mark.parametrize("suffix", [".nxs", ".xml", ".npy"])
def test_save_mask_writes_the_file_and_its_log(tmp_path: Path, suffix: str) -> None:
    state = MaskState()
    state.add_shape(Rectangle(0, 0, 191, 3))
    state.paint(_cells(slice(100, 110), slice(90, 100)), masked=True)
    saved = save_mask(state, tmp_path / "EQSANS_7.nxs.h5", "7", tmp_path / f"out{suffix}")
    assert saved.path.exists() and saved.log_path.name == "out.mask_log.json"
    assert saved.n_masked == 4 * 192 + 100
    np.testing.assert_array_equal(read_mask_file(saved.path), state.build())
    log = json.loads(saved.log_path.read_text())
    assert [s["type"] for s in log["shapes"]] == ["rectangle", "pixels"]


def test_save_mask_rejects_an_unknown_format(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="save as"):
        save_mask(MaskState(), tmp_path / "s.nxs.h5", "", tmp_path / "out.png")


def test_default_output() -> None:
    src = Path("/data/EQSANS_12.nxs.h5")
    assert default_output(src) == Path("/data/EQSANS_12.nxs_mask.nxs")
    assert default_output(src, Path("/tmp/x")) == Path("/tmp/x/EQSANS_12.nxs_mask.nxs")
