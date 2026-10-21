"""Mask editing in the viewer window (Phase 9.10.3; offscreen, skip without PySide6)."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("pyqtgraph")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QPointF, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from sansdir.mask.core import Circle, Ellipse, Polygon, Rectangle
from sansdir.viewer.cube import TofCube, load_cube
from sansdir.viewer.geometry import bank_columns, pixel_info
from sansdir.viewer.masking import MaskState, read_mask_file, save_mask
from sansdir.viewer.qt import main_window as mw
from sansdir.viewer.qt.dialogs import ThresholdDialog
from sansdir.viewer.qt.main_window import MainWindow
from sansdir.viewer.qt.roi_tools import roi_for_shape, shape_for_roi
from tests.viewer.test_cube import _events, _write_raw

P = QPointF


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    return app


@pytest.fixture
def cube(tmp_path: Path) -> TofCube:
    raw = _write_raw(tmp_path / "EQSANS_4242.nxs.h5", _events(per_bank=4000))
    return load_cube(raw, nbins=50)


@pytest.fixture
def window(qapp: QApplication, cube: TofCube):  # type: ignore[no-untyped-def]
    win = MainWindow()
    win.show()
    win._set_cube(cube)
    yield win
    win.close()


def _drag(win: MainWindow, tool: str, a: tuple[float, float], b: tuple[float, float]) -> None:
    win.set_tool(tool)
    start = P(*a)
    win.editor.drag(start, start, "start", False)
    win.editor.drag(start, P(*b), "move", False)
    win.editor.drag(start, P(*b), "finish", False)


def _mask(win: MainWindow) -> np.ndarray:
    return win.editor.state.build()


# -- drawing -------------------------------------------------------------------------


def test_rectangle_covers_the_cells_under_the_drag(window: MainWindow) -> None:
    _drag(window, "rect", (10, 20), (20, 30))
    assert window.editor.state.shapes == [Rectangle(9.5, 19.5, 19.5, 29.5)]
    mask = _mask(window)
    assert mask.sum() == 100 and mask[20:30, 10:20].all()
    assert len(window.editor.rois) == 1
    assert "mask 100 px" in window.mask_label.text() and "unsaved" in window.mask_label.text()


def test_ellipse_circle_and_a_click_that_is_not_a_drag(window: MainWindow) -> None:
    _drag(window, "ellipse", (50, 50), (60, 70))
    _drag(window, "circle", (100.5, 100.5), (103.5, 100.5))
    _drag(window, "rect", (5, 5), (5.2, 5.1))  # too small: ignored
    shapes = window.editor.state.shapes
    assert shapes == [Ellipse(54.5, 59.5, 5, 10), Circle(100, 100, 3)]
    assert _mask(window)[100, 100] and _mask(window)[100, 103] and not _mask(window)[100, 104]


def test_polygon_closes_on_double_click_and_esc_cancels(window: MainWindow) -> None:
    window.set_tool("polygon")
    for x, y in [(10, 10), (40, 10), (10, 40)]:
        window.editor.click(P(x, y), False, False)
    window.editor.click(P(10, 40), True, False)
    assert window.editor.state.shapes == [Polygon(((9.5, 9.5), (39.5, 9.5), (9.5, 39.5)))]
    window.editor.click(P(100, 100), False, False)
    window._on_escape()  # drops the half-drawn polygon, does not touch the load
    window.editor.click(P(110, 100), True, False)
    assert len(window.editor.state.shapes) == 1


def test_brush_stroke_has_no_gaps_and_is_one_undo_step(window: MainWindow) -> None:
    _drag(window, "brush", (10.5, 10.5), (40.5, 10.5))
    assert _mask(window)[10, 10:41].all() and _mask(window).sum() == 31
    window.undo_action.trigger()
    assert not _mask(window).any()


def test_eraser_unmasks_inside_a_shape(window: MainWindow) -> None:
    _drag(window, "rect", (0, 0), (10, 10))
    window.set_tool("eraser")
    window.editor.click(P(5.5, 5.5), False, False)
    assert not _mask(window)[5, 5] and _mask(window).sum() == 99


def test_tube_click_toggles_and_shift_takes_the_bank(window: MainWindow) -> None:
    window.set_tool("tube")
    window.editor.click(P(30.5, 100), False, False)
    assert _mask(window)[:, 30].all() and _mask(window).sum() == 256
    window.editor.click(P(30.5, 100), False, False)
    assert not _mask(window).any()
    window.editor.click(P(30.5, 100), False, True)
    info = pixel_info(30.5, 100)
    assert info is not None
    cols = bank_columns(info.bank)
    assert _mask(window)[:, cols].all() and _mask(window).sum() == 4 * 256
    assert f"bank{info.bank}" in window.info.text()


# -- editing shapes ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "shape",
    [
        Rectangle(9.5, 19.5, 19.5, 29.5),
        Ellipse(50, 60, 4, 9),
        Circle(96, 128, 7),
        Polygon(((0, 0), (20, 0), (0, 30))),
    ],
)
def test_roi_round_trips_its_shape(qapp: QApplication, shape) -> None:  # type: ignore[no-untyped-def]
    back = shape_for_roi(roi_for_shape(shape))
    assert type(back) is type(shape)
    np.testing.assert_allclose(
        np.array(list(back.to_dict().values())[1:], dtype=object).tolist(),
        np.array(list(shape.to_dict().values())[1:], dtype=object).tolist(),
    )


def test_ellipse_roi_cannot_rotate(qapp: QApplication) -> None:
    roi = roi_for_shape(Ellipse(50, 60, 4, 9))
    assert all(h["type"] != "r" for h in roi.handles)


def test_moving_a_roi_moves_the_mask_as_one_undo_step(window: MainWindow) -> None:
    _drag(window, "rect", (10, 10), (20, 20))
    roi = window.editor.rois[0]
    window.editor._on_roi_started(roi)  # what a mouse drag on the ROI emits first
    roi.setPos(P(110, 10))
    roi.setPos(P(120, 10))
    assert window.editor.state.shapes == [Rectangle(119.5, 9.5, 129.5, 19.5)]
    assert _mask(window)[10:20, 120:130].all() and not _mask(window)[15, 15]
    window.undo_action.trigger()
    assert window.editor.state.shapes == [Rectangle(9.5, 9.5, 19.5, 19.5)]
    assert shape_for_roi(window.editor.rois[0]) == Rectangle(9.5, 9.5, 19.5, 19.5)


def test_delete_the_selected_shape(window: MainWindow) -> None:
    _drag(window, "rect", (10, 10), (20, 20))
    _drag(window, "rect", (50, 50), (60, 60))
    window.delete_action.trigger()  # nothing selected yet
    assert len(window.editor.state.shapes) == 2 and "select" in window.info.text()
    window.editor.select(window.editor.rois[0])
    window.delete_action.trigger()
    assert window.editor.state.shapes == [Rectangle(49.5, 49.5, 59.5, 59.5)]
    window.editor.rois[0].sigRemoveRequested.emit(window.editor.rois[0])  # context menu
    assert window.editor.state.shapes == [] and window.editor.rois == []


def test_undo_redo_rebuild_the_rois(window: MainWindow) -> None:
    _drag(window, "circle", (50, 50), (55, 50))
    window.undo_action.trigger()
    assert window.editor.rois == [] and window.redo_action.isEnabled()
    window.redo_action.trigger()
    assert len(window.editor.rois) == 1 and window.editor.state.shapes == [Circle(49.5, 49.5, 5)]


# -- whole-mask actions -------------------------------------------------------------------


def test_invert_and_clear(window: MainWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    _drag(window, "rect", (0, 0), (192, 128))
    window.invert_action.trigger()
    assert window.editor.state.inverted and "inverted" in window.mask_label.text()
    assert _mask(window)[200].all() and not _mask(window)[10].any()
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes)
    window.clear_action.trigger()
    assert window.editor.state.is_empty and window.editor.rois == []
    assert not window.invert_action.isChecked() and window.mask_label.text().startswith("no mask")


def test_tube_spec_adds_full_height_rectangles(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mw, "ask_spec", lambda _parent: "t10-12, t50")
    window.spec_action.trigger()
    assert window.editor.state.shapes == [
        Rectangle(9.5, -0.5, 12.5, 255.5),
        Rectangle(49.5, -0.5, 50.5, 255.5),
    ]
    assert _mask(window).sum() == 4 * 256 and "+2 rectangles over 4 tubes" in window.info.text()
    window.undo_action.trigger()  # the whole spec is one step
    assert window.editor.state.shapes == []
    warned: list[str] = []
    monkeypatch.setattr(mw, "ask_spec", lambda _parent: "q7")
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text: warned.append(text))
    window.spec_action.trigger()
    assert warned and "'b' or 't'" in warned[0]


def test_threshold_dialog_counts_and_masks(window: MainWindow) -> None:
    image = window._image
    assert image is not None
    dialog = ThresholdDialog(image, "all TOF")
    zeros = int((image <= 0).sum())
    assert dialog.count.text() == f"{zeros:,} pixels match"
    dialog.high_box.setChecked(True)
    dialog.high.setValue(float(image.max()))
    low, high = dialog.limits()
    assert low == 0 and high == image.max()
    n = window.editor.threshold(image, low, high)
    assert n == zeros + int((image >= image.max()).sum())


def test_overlay_toggle_readout_and_limits_skip_masked_pixels(window: MainWindow) -> None:
    image = window._image
    assert image is not None
    window.scale.set_percentiles(0, 100)
    window._refresh()
    window.editor.threshold(image, None, float(image.max()))  # mask every hottest pixel
    rows, cols = np.nonzero(image >= image.max())
    row, col = int(rows[0]), int(cols[0])
    assert window.view.overlay.image is not None
    window.overlay_action.toggle()
    assert window.view.overlay.image is None
    window._show_readout(pixel_info(col + 0.5, row + 0.5))
    assert window.readout.text().endswith("MASKED")
    window._refresh()
    assert window.scale.vmax < image.max()  # the masked hot pixel no longer sets Max


def test_tool_keys_do_not_fire_while_typing_a_limit(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[bool] = []
    monkeypatch.setattr(mw, "ask_spec", lambda _parent: asked.append(True))
    window.activateWindow()
    assert QTest.qWaitForWindowActive(window, 2000)
    window.view.setFocus()
    QTest.keyClick(window.view, Qt.Key.Key_R)
    assert window.editor.tool == "rect" and window.tool_actions["rect"].isChecked()
    box = window.scale_panel.min_box
    box.setFocus()
    QTest.keyClicks(box, "2k")
    assert asked == [] and window.editor.tool == "rect"


# -- load / save / close ----------------------------------------------------------------------


def _wait_for_save(win: MainWindow) -> None:
    saver = win._saver
    if saver is None:
        return
    loop = QEventLoop()
    saver.finished.connect(lambda: QTimer.singleShot(0, loop.quit))
    QTimer.singleShot(20_000, loop.quit)
    if win._saver is not None:
        loop.exec()


def test_load_a_saved_mask(window: MainWindow, tmp_path: Path, cube: TofCube) -> None:
    state = MaskState()
    state.add_shape(Rectangle(0, 0, 50, 50))
    saved = save_mask(state, cube.path, "4242", tmp_path / "m.xml")
    assert window.load_mask(saved.path)
    np.testing.assert_array_equal(_mask(window), state.build())
    assert window.editor.rois == []  # an XML mask is cells, not shapes
    assert window.load_mask(saved.log_path)  # mask_log.json: editable shapes
    assert len(window.editor.rois) == 1


def test_loading_a_bad_file_warns(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    warned: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text: warned.append(text))
    (tmp_path / "x.txt").write_text("hi")
    assert not window.load_mask(tmp_path / "x.txt")
    assert warned and "not a mask" in warned[0]


def test_save_adds_the_suffix_and_marks_saved(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _drag(window, "rect", (0, 0), (192, 4))
    monkeypatch.setattr(
        mw.QFileDialog,
        "getSaveFileName",
        lambda *_a, **_k: (str(tmp_path / "beamstop"), "Mantid mask XML (*.xml)"),
    )
    assert window.save_mask()
    _wait_for_save(window)
    out = tmp_path / "beamstop.xml"
    np.testing.assert_array_equal(read_mask_file(out), _mask(window))
    assert (tmp_path / "beamstop.mask_log.json").exists()
    assert window.saved_any and "unsaved" not in window.mask_label.text()
    assert window.mask_output == out and "mask saved" in window.info.text()


def test_save_needs_a_run(qapp: QApplication) -> None:
    win = MainWindow()
    try:
        assert not win.save_mask() and "open a run" in win.info.text()
    finally:
        win.close()


def test_closing_with_unsaved_edits_asks(
    qapp: QApplication, cube: TofCube, monkeypatch: pytest.MonkeyPatch
) -> None:
    win = MainWindow(ask_to_save=True)
    win.show()
    win._set_cube(cube)
    _drag(win, "rect", (0, 0), (10, 10))
    answers = iter([QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Discard])
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: next(answers))
    win.close()
    assert win.isVisible()  # cancelled
    win.close()
    assert not win.isVisible()  # discarded
