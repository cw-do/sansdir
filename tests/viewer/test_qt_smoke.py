"""Qt smoke tests for the viewer window (offscreen; skip without PySide6).

Also guards the PySide6 6.12.0 regression: with pyqtgraph 0.14 it
leaked references to ``True`` on every repaint until the interpreter
aborted, so a few thousand hovers must leave the count stable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("pyqtgraph")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QPointF, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from sansdir.viewer.cache import CubeCache
from sansdir.viewer.cube import load_cube
from sansdir.viewer.geometry import info_for_detid
from sansdir.viewer.qt.main_window import MainWindow
from sansdir.viewer.qt.progress import (
    LoadProgress,
    eta_seconds,
    format_count,
    format_duration,
)
from tests.viewer.test_cube import _events, _write_raw


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    return app


@pytest.fixture
def raw_file(tmp_path: Path) -> Path:
    return _write_raw(tmp_path / "EQSANS_4242.nxs.h5", _events())


@pytest.fixture
def window(qapp: QApplication):  # type: ignore[no-untyped-def]
    win = MainWindow()
    win.show()
    yield win
    win.close()


def _hover(win: MainWindow, x: float, y: float) -> None:
    vb = win.view.plot.vb
    win.view._on_mouse_moved(vb.mapViewToScene(QPointF(x, y)))


def test_hover_readout_names_the_pixel(
    qapp: QApplication, window: MainWindow, raw_file: Path
) -> None:
    window._set_cube(load_cube(raw_file))
    info = info_for_detid(14466)  # Mantid: front-panel/bank8/tube1/pixel131
    _hover(window, info.x + 0.5, info.y + 0.5)
    text = window.readout.text()
    assert "front bank8 tube1 pixel131" in text
    assert "ID 14466" in text and "DAS bank15" in text
    _hover(window, -5, -5)
    assert window.readout.text() == ""


def _open_and_wait(win: MainWindow, path: Path) -> list[str]:
    """Open ``path`` and run the event loop until its loader thread ends."""
    loop = QEventLoop()
    win.open_path(path)
    loader = win._loader
    assert loader is not None
    stages: list[str] = []
    loader.progressed.connect(lambda stage, _d, _t: stages.append(stage))
    loader.finished.connect(lambda: QTimer.singleShot(0, loop.quit))
    QTimer.singleShot(20_000, loop.quit)
    loop.exec()
    return stages


def test_background_load_shows_the_run(
    qapp: QApplication, window: MainWindow, raw_file: Path
) -> None:
    stages = _open_and_wait(window, raw_file)
    assert window.cube is not None and window.cube.run_number == "4242"
    assert "run 4242" in window.windowTitle() and "%]" not in window.windowTitle()
    assert window.loading.isHidden() and window._loader is None
    assert stages[-1] == "loading"


def test_second_open_comes_from_the_cache(
    qapp: QApplication, raw_file: Path, tmp_path: Path
) -> None:
    win = MainWindow(cache=CubeCache(tmp_path / "cache", min_load_seconds=0.0))
    win.show()
    try:
        first = _open_and_wait(win, raw_file)
        assert "cache-write" in first
        assert win.cube is not None and "cache_read" not in win.cube.timings
        second = _open_and_wait(win, raw_file)
        assert second == ["cache-read"]
        assert win.cube is not None and "cache_read" in win.cube.timings
        assert "from cache" in win.info.text()
    finally:
        win.close()


def test_cancel_stops_and_hides_the_progress(
    qapp: QApplication, window: MainWindow, raw_file: Path
) -> None:
    window.open_path(raw_file)
    assert window.loading.isVisible()
    window.cancel_load()
    assert window._loader is None and window.loading.isHidden()
    assert window.info.text() == "loading cancelled"
    window.cancel_load()  # nothing loading: harmless


def test_progress_panel_text(qapp: QApplication) -> None:
    panel = LoadProgress()
    panel.start("EQSANS_1.nxs.h5")
    assert "Opening EQSANS_1" in panel.label.text() and panel.percent is None
    panel.update_stage("preview", 0, 7.67e9)
    assert panel.label.text() == "Preview: sampling 7.67 G events…"
    panel.update_stage("loading", 2.5e9, 1e10)
    assert panel.percent == 25
    assert panel.label.text().startswith("Loading 2.50 G / 10 G events")
    panel.update_stage("cache-write", 0, 0)
    assert panel.label.text().startswith("Saving to cache") and panel.percent is None
    panel.finish()
    assert panel.isHidden()


@pytest.mark.parametrize(
    ("n", "text"), [(7.674e9, "7.67 G"), (2.0e7, "20 M"), (745_353, "745 k"), (12, "12")]
)
def test_format_count(n: float, text: str) -> None:
    assert format_count(n) == text


def test_eta_waits_for_enough_data() -> None:
    assert eta_seconds(1, 100, 10.0) is None  # 1 % done
    assert eta_seconds(50, 100, 0.5) is None  # under a second
    assert eta_seconds(25, 100, 10.0) == pytest.approx(30.0)
    assert format_duration(30.4) == "30 s" and format_duration(125) == "2 min 05 s"


def test_log_toggle_keeps_the_image(qapp: QApplication, window: MainWindow, raw_file: Path) -> None:
    window._set_cube(load_cube(raw_file))
    window.log_action.toggle()
    assert window.view.image.image is not None
    assert not window.scale.log


def test_hovering_does_not_leak_true(
    qapp: QApplication, window: MainWindow, raw_file: Path
) -> None:
    window._set_cube(load_cube(raw_file))
    qapp.processEvents()
    before = sys.getrefcount(True)
    for k in range(3000):
        _hover(window, 5 + k % 180, 5 + k % 240)
        if k % 10 == 0:
            qapp.processEvents()
    # 6.12.0 lost ~0.85 per hover; allow a little GC noise.
    assert sys.getrefcount(True) - before > -50


def test_clear_cache_menu(
    qapp: QApplication, raw_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = CubeCache(tmp_path / "cache", min_load_seconds=0.0)
    win = MainWindow(cache=cache)
    try:
        assert win.clear_cache_action.isEnabled()
        told: list[str] = []
        monkeypatch.setattr(
            QMessageBox, "information", lambda _parent, _title, text: told.append(text)
        )
        win.clear_cache()
        assert told == ["The viewer cache is already empty."]

        cache.put(load_cube(raw_file, nbins=16), 16)
        asked: list[str] = []

        def answer(reply: QMessageBox.StandardButton):  # type: ignore[no-untyped-def]
            def question(_parent, _title, text):  # type: ignore[no-untyped-def]
                asked.append(text)
                return reply

            return question

        monkeypatch.setattr(QMessageBox, "question", answer(QMessageBox.StandardButton.No))
        win.clear_cache()
        assert "1 run," in asked[-1] and cache.summary()[0] == 1  # declined: kept

        monkeypatch.setattr(QMessageBox, "question", answer(QMessageBox.StandardButton.Yes))
        win.clear_cache()
        assert cache.summary() == (0, 0)
        assert win.info.text().startswith("cache cleared: 1 run, ")
    finally:
        win.close()


def test_clear_cache_disabled_without_cache(qapp: QApplication, window: MainWindow) -> None:
    assert not window.clear_cache_action.isEnabled()


def test_qt_settings_stay_off_the_home_directory(qapp: QApplication, tmp_path: Path) -> None:
    """Qt's file dialog keeps history in QSettings("QtProject"), whose lock file hung
    on the NFS home (2026-10-21); the viewer redirects it to node-local storage."""
    from PySide6.QtCore import QSettings

    from sansdir.viewer.qt.main_window import isolate_qt_settings, local_qt_settings_dir

    target = isolate_qt_settings(tmp_path / "qt")
    try:
        name = QSettings(QSettings.Scope.UserScope, "QtProject").fileName()
        assert name == str(tmp_path / "qt" / "QtProject.conf")
    finally:
        isolate_qt_settings(local_qt_settings_dir())  # keep later tests off tmp_path
    assert target.is_dir()
    assert str(local_qt_settings_dir()).startswith(
        (os.environ.get("XDG_RUNTIME_DIR") or "/", "/tmp")
    )
