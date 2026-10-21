"""TOF panel + colour-scale panel in the viewer window (offscreen; skip without PySide6)."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("pyqtgraph")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QSettings
from PySide6.QtWidgets import QApplication

from sansdir.viewer.colorscale import display_levels
from sansdir.viewer.cube import TofCube, load_cube
from sansdir.viewer.qt.main_window import MainWindow
from sansdir.viewer.qt.scale_panel import CountBox, parse_count
from tests.viewer.test_cube import _events, _write_raw


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


def _shown(win: MainWindow) -> np.ndarray:
    assert win._image is not None
    return win._image


# -- TOF panel ---------------------------------------------------------------


def test_a_new_run_opens_on_the_full_range(window: MainWindow, cube: TofCube) -> None:
    panel = window.tof_panel
    assert panel.selection == (0, cube.nbins) and panel.full_box.isChecked()
    np.testing.assert_array_equal(_shown(window), cube.image())
    assert panel.label.text().startswith("all TOF")


def test_slider_shows_that_slice(window: MainWindow, cube: TofCube) -> None:
    panel = window.tof_panel
    panel.full_box.setChecked(False)
    width = panel.selection[1] - panel.selection[0]
    panel.slider.setValue(10)
    assert panel.selection == (10, 10 + width) and not panel.full_box.isChecked()
    np.testing.assert_array_equal(_shown(window), cube.image(10, 10 + width))
    lo, hi = panel.region.getRegion()
    assert (lo, hi) == pytest.approx((cube.tof_edges[10] / 1e3, cube.tof_edges[10 + width] / 1e3))


def test_width_box_and_full_range(window: MainWindow, cube: TofCube) -> None:
    panel = window.tof_panel
    panel.full_box.setChecked(False)
    panel.slider.setValue(5)
    panel.width_box.setValue(7)
    assert panel.selection == (5, 12)
    assert panel.slider.maximum() == cube.nbins - 7
    panel.full_box.setChecked(True)
    np.testing.assert_array_equal(_shown(window), cube.image())
    panel.full_box.setChecked(False)  # the last window comes back
    assert panel.selection == (5, 12)


def test_dragging_the_region_snaps_to_bins(window: MainWindow, cube: TofCube) -> None:
    panel = window.tof_panel
    edges_ms = cube.tof_edges / 1e3
    panel.region.setRegion((edges_ms[3] + 0.01, edges_ms[9] - 0.01))  # as a drag would
    assert panel.selection == (3, 9)
    np.testing.assert_array_equal(_shown(window), cube.image(3, 9))
    panel._on_region_dropped()
    assert panel.region.getRegion() == pytest.approx((edges_ms[3], edges_ms[9]))


def test_step_and_play_walk_through_the_run(window: MainWindow, cube: TofCube) -> None:
    panel = window.tof_panel
    panel.full_box.setChecked(False)
    panel.width_box.setValue(10)
    panel.slider.setValue(0)
    panel.step(1)
    assert panel.selection == (10, 20)
    panel.next_button.click()
    assert panel.selection == (20, 30)
    panel.prev_button.click()
    assert panel.selection == (10, 20)
    panel.full_box.setChecked(True)
    panel.play_button.click()  # play leaves the full range for the last window
    assert panel._timer.isActive() and panel.selection == (10, 20)
    panel._timer.timeout.emit()
    assert panel.selection == (20, 30)
    panel.play_button.click()
    assert not panel._timer.isActive() and panel.play_button.text() == "Play"


def test_preview_to_full_load_keeps_the_selection(window: MainWindow, cube: TofCube) -> None:
    panel = window.tof_panel
    panel.full_box.setChecked(False)
    panel.width_box.setValue(4)
    panel.slider.setValue(8)
    window._set_cube(cube)  # same path: as when the full load replaces a preview
    assert panel.selection == (8, 12)
    np.testing.assert_array_equal(_shown(window), cube.image(8, 12))


def test_readout_counts_follow_the_slice(window: MainWindow, cube: TofCube) -> None:
    image = cube.image()
    y, x = np.unravel_index(int(np.argmax(image)), image.shape)
    vb = window.view.plot.vb
    window.view._on_mouse_moved(vb.mapViewToScene(QPointF(x + 0.5, y + 0.5)))
    assert f"{image[y, x]:,.0f} counts" in window.readout.text()
    panel = window.tof_panel
    panel.full_box.setChecked(False)
    panel.width_box.setValue(1)
    panel.slider.setValue(0)
    in_slice = cube.image(0, 1)[y, x]
    assert window.readout.text().endswith(f"{in_slice:,.0f} counts")


def test_processed_file_disables_the_tof_panel(window: MainWindow, cube: TofCube) -> None:
    flat = TofCube(
        path=Path("processed.nxs"),
        run_number="",
        title="",
        source="processed",
        cum=cube.cum[[0, -1]],
        tof_edges=None,
    )
    window._set_cube(flat)
    panel = window.tof_panel
    assert not panel.has_tof and not panel.slider.isEnabled() and not panel.play_button.isEnabled()
    assert panel.label.text() == "no TOF (processed file)"
    panel.step(1)  # harmless
    np.testing.assert_array_equal(_shown(window), cube.image())


# -- colour scale --------------------------------------------------------------


def test_typed_limits_set_the_colour_bar_and_lock(window: MainWindow) -> None:
    panel = window.scale_panel
    assert not window.scale.locked
    panel.max_box.setValue(50)  # what Enter does
    assert window.scale.vmax == 50 and window.scale.locked and panel.lock_box.isChecked()
    _lo, hi = window.view.lut.getLevels()
    assert hi == pytest.approx(np.log10(50))
    window.tof_panel.full_box.setChecked(False)  # locked: a new slice keeps the limits
    assert window.scale.vmax == 50


def test_unlocked_limits_follow_each_slice(window: MainWindow) -> None:
    window.scale_panel.phi_box.setValue(100)  # refreshes with the new percentile
    full_max = window.scale.vmax
    assert full_max == _shown(window).max()
    panel = window.tof_panel
    panel.full_box.setChecked(False)
    panel.width_box.setValue(1)
    panel.slider.setValue(20)  # a populated bin (synthetic events start at 500 µs)
    assert window.scale.vmax == _shown(window).max() < full_max
    assert window.scale_panel.max_box.value() == pytest.approx(window.scale.vmax, abs=1e-3)


def test_dragging_the_colour_bar_updates_the_boxes(window: MainWindow) -> None:
    window.view.lut.setLevels(*display_levels(3, 300, log=True))  # as a handle drag
    assert window.scale.locked
    assert window.scale_panel.min_box.value() == pytest.approx(3)
    assert window.scale_panel.max_box.value() == pytest.approx(300)


def test_auto_and_reset_buttons(window: MainWindow) -> None:
    image = _shown(window)
    positive = image[image > 0]
    window.scale_panel.reset_button.click()
    assert (window.scale.vmin, window.scale.vmax) == (positive.min(), positive.max())
    window.scale_panel.max_box.setValue(1)
    window.scale_panel.auto_button.click()
    assert window.scale.vmax == pytest.approx(np.percentile(positive, 99.5))


def test_log_key_and_button_stay_in_sync(window: MainWindow) -> None:
    window.log_action.trigger()  # `L`
    assert not window.scale.log and not window.scale_panel.log_button.isChecked()
    assert window.scale_panel.log_button.text() == "Linear scale"
    assert window.view.lut.axis._tickLevels is None  # linear: pyqtgraph's own ticks
    window.scale_panel.log_button.click()
    assert window.scale.log and window.log_action.isChecked()
    major = window.view.lut.axis._tickLevels[0]
    assert [label for pos, label in major if pos == 0] == ["1"]


def test_colour_map_picker(window: MainWindow) -> None:
    window.scale_panel.cmap_box.setCurrentText("jet")
    assert window.scale.cmap == "jet"
    window.scale_panel.cmap_box.setCurrentText("gray")
    lut = window.view.lut.gradient.colorMap().getLookupTable(nPts=2)
    assert lut[0].tolist() == [0, 0, 0] and lut[-1].tolist() == [255, 255, 255]


def test_scale_settings_persist(qapp: QApplication, cube: TofCube, tmp_path: Path) -> None:
    ini = str(tmp_path / "viewer.ini")
    first = MainWindow(settings=QSettings(ini, QSettings.Format.IniFormat))
    first._set_cube(cube)
    first.scale_panel.cmap_box.setCurrentText("magma")
    first.scale_panel.max_box.setValue(77)  # locks
    first.log_action.trigger()
    first.settings.sync()
    first.close()
    second = MainWindow(settings=QSettings(ini, QSettings.Format.IniFormat))
    try:
        state = second.scale
        assert (state.cmap, state.log, state.locked, state.vmax) == ("magma", False, True, 77)
        assert second.scale_panel.cmap_box.currentText() == "magma"
    finally:
        second.close()


def test_bad_settings_fall_back_to_defaults(qapp: QApplication, tmp_path: Path) -> None:
    ini = tmp_path / "viewer.ini"
    ini.write_text("[scale]\ncmap=nope\nvmin=abc\nlog=false\n")
    win = MainWindow(settings=QSettings(str(ini), QSettings.Format.IniFormat))
    try:
        assert win.scale.cmap == "viridis" and win.scale.vmin == 1.0 and not win.scale.log
    finally:
        win.close()


@pytest.mark.parametrize(
    ("text", "value"),
    [("1500", 1500.0), ("1,500", 1500.0), ("1.5e3", 1500.0), ("1.5k", 1500.0), ("2M", 2e6),
     ("abc", None), ("", None), ("-3", None), ("inf", None)],
)  # fmt: skip
def test_parse_count(text: str, value: float | None) -> None:
    assert parse_count(text) == value


def test_count_box_steps_by_decades_in_log_mode(qapp: QApplication) -> None:
    box = CountBox("tip")
    box.setValue(100)
    box.stepBy(10)  # ten wheel clicks = one decade
    assert box.value() == pytest.approx(1000)
    box.log_steps = False
    box.setValue(100)
    box.stepBy(1)
    assert box.value() == pytest.approx(110)
