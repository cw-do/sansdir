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
from PySide6.QtWidgets import QApplication

from sansdir.viewer.cube import load_cube
from sansdir.viewer.geometry import info_for_detid
from sansdir.viewer.qt.main_window import MainWindow
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


def test_background_load_shows_the_run(
    qapp: QApplication, window: MainWindow, raw_file: Path
) -> None:
    loop = QEventLoop()
    window.open_path(raw_file)
    assert window._loader is not None
    window._loader.loaded.connect(lambda _c: QTimer.singleShot(0, loop.quit))
    QTimer.singleShot(20_000, loop.quit)
    loop.exec()
    assert window.cube is not None and window.cube.run_number == "4242"
    assert "run 4242" in window.windowTitle()
    assert window.progress.isHidden()


def test_log_toggle_keeps_the_image(qapp: QApplication, window: MainWindow, raw_file: Path) -> None:
    window._set_cube(load_cube(raw_file))
    window.log_action.toggle()
    assert window.view.image.image is not None
    assert not window._log


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
