"""``V`` / ``:viewer`` and ``K`` — launch the Qt detector viewer (Phase 9.10).

``subprocess.Popen`` is replaced, so no viewer window is ever opened.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sansdir.app import SansdirApp
from sansdir.commands import builtins
from sansdir.core.history import CommandHistory
from tests.test_phase8 import _write_nx

_REAL_POPEN = subprocess.Popen


class _FakePopen:
    """Stands in for the viewer subprocess; any other command really runs."""

    calls: list[list[str]]
    rc = 0
    stderr_text = ""

    def __new__(cls, cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        if "sansdir.viewer" not in list(cmd):
            return _REAL_POPEN(cmd, *args, **kwargs)  # e.g. h5py's first import
        return super().__new__(cls)

    def __init__(self, cmd, stderr=None, **_kwargs):  # type: ignore[no-untyped-def]
        type(self).calls.append(list(cmd))
        if stderr is not None and self.stderr_text:
            stderr.write(self.stderr_text)
            stderr.flush()

    def wait(self) -> int:
        return self.rc


@pytest.fixture
def popen(monkeypatch: pytest.MonkeyPatch) -> type[_FakePopen]:
    fake = type("FakePopen", (_FakePopen,), {"calls": []})
    monkeypatch.setattr("subprocess.Popen", fake)
    monkeypatch.setattr("sansdir.plot.backend.has_display", lambda: True)
    monkeypatch.setattr(builtins, "viewer_available", lambda: True)
    return fake


def _viewer_cmd(nexus: Path, right: Path, *tool: str) -> list[str]:
    out = right / f"{nexus.stem}_mask.nxs"
    return ["-m", "sansdir.viewer", str(nexus), "--output", str(out), *tool]


def _app(tmp_path: Path) -> tuple[SansdirApp, Path]:
    left = tmp_path / "L"
    right = tmp_path / "R"
    left.mkdir()
    right.mkdir()
    nexus = left / "EQSANS_001.nxs.h5"
    _write_nx(nexus, temperature=298.0, duration=600.0)
    (left / "notes.txt").write_text("hello\n")
    app = SansdirApp(
        start_path=left,
        right_path=right,
        history=CommandHistory(path=tmp_path / "hist", load=False),
    )
    return app, nexus


async def _press_v_on(app: SansdirApp, path: Path, key: str = "V") -> list[str]:
    notes: list[str] = []
    async with app.run_test() as pilot:
        await pilot.pause()
        original = app.notify_user

        def record(message: str, **kwargs):  # type: ignore[no-untyped-def]
            notes.append(message)
            return original(message, **kwargs)

        app.notify_user = record  # type: ignore[method-assign]
        assert app.active_panel.move_cursor_to_path(path)
        await pilot.press(key)
        await pilot.pause()
        await pilot.pause(0.3)
        app._names_after = {e.name for e in app.inactive_panel._all_entries}  # type: ignore[attr-defined]
        await pilot.press("q")
    return notes


async def test_v_opens_the_viewer_on_the_cursor_file(
    tmp_path: Path, popen: type[_FakePopen]
) -> None:
    app, nexus = _app(tmp_path)
    notes = await _press_v_on(app, nexus)
    assert len(popen.calls) == 1
    # Save mask defaults to the other pane, as K's editor always did.
    assert popen.calls[0][1:] == _viewer_cmd(nexus, tmp_path / "R")
    assert any("detector viewer opened on EQSANS_001.nxs.h5" in n for n in notes)
    assert not any("mask saved" in n for n in notes)  # rc 0: closed, nothing saved


async def test_k_opens_the_viewer_on_the_rectangle_tool(
    tmp_path: Path, popen: type[_FakePopen]
) -> None:
    app, nexus = _app(tmp_path)
    await _press_v_on(app, nexus, "K")
    assert popen.calls[0][1:] == _viewer_cmd(nexus, tmp_path / "R", "--tool", "rect")


async def test_k_falls_back_to_the_matplotlib_editor(
    tmp_path: Path, popen: type[_FakePopen], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builtins, "viewer_available", lambda: False)
    calls: list[list[str]] = []

    class _Gui:
        def __init__(self, cmd, **_kwargs):  # type: ignore[no-untyped-def]
            calls.append(list(cmd))

        def wait(self) -> int:
            return 1

    monkeypatch.setattr("subprocess.Popen", _Gui)
    app, nexus = _app(tmp_path)
    notes = await _press_v_on(app, nexus, "K")
    assert calls and "sansdir.mask.gui" in calls[0]
    assert any("using the matplotlib mask editor" in n for n in notes)


async def test_a_saved_mask_refreshes_the_panes(tmp_path: Path, popen: type[_FakePopen]) -> None:
    from sansdir.viewer import EXIT_SAVED

    popen.rc = EXIT_SAVED
    app, nexus = _app(tmp_path)
    original = popen.__init__

    def write_mask(self, cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        original(self, cmd, *args, **kwargs)
        (tmp_path / "R" / "EQSANS_001.nxs_mask.nxs").write_bytes(b"")  # as the viewer would

    popen.__init__ = write_mask  # type: ignore[method-assign]
    notes = await _press_v_on(app, nexus, "K")
    assert "EQSANS_001.nxs_mask.nxs" in app._names_after  # type: ignore[attr-defined]
    assert any("mask saved (panes refreshed)" in n for n in notes)


async def test_v_refuses_a_non_nexus_file(tmp_path: Path, popen: type[_FakePopen]) -> None:
    app, nexus = _app(tmp_path)
    notes = await _press_v_on(app, nexus.parent / "notes.txt")
    assert popen.calls == []
    assert any("opens NeXus" in n for n in notes)


async def test_v_explains_a_missing_viewer_extra(
    tmp_path: Path, popen: type[_FakePopen], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builtins, "viewer_available", lambda: False)
    app, nexus = _app(tmp_path)
    notes = await _press_v_on(app, nexus)
    assert popen.calls == []
    assert any("sansdir[viewer]" in n for n in notes)


async def test_a_viewer_crash_is_reported(tmp_path: Path, popen: type[_FakePopen]) -> None:
    popen.rc = 1
    popen.stderr_text = "Traceback …\nRuntimeError: boom\n"
    app, nexus = _app(tmp_path)
    notes = await _press_v_on(app, nexus)
    assert any("detector viewer failed (rc=1): RuntimeError: boom" in n for n in notes)


async def test_catalog_v_opens_the_viewer_for_the_cursor_run(
    tmp_path: Path, popen: type[_FakePopen]
) -> None:
    from sansdir.core.oncat import Datafile

    fake_root = tmp_path / "FAKE"
    nx_dir = fake_root / "EQSANS" / "IPTS-99999" / "nexus"
    nx_dir.mkdir(parents=True)
    nexus = nx_dir / "EQSANS_100.nxs.h5"
    _write_nx(nexus, temperature=298.0, duration=600.0)
    runs = [
        Datafile(
            run_number=100,
            title="sample",
            start_time="",
            duration_s=600,
            detector_distance_mm=2500.0,
            wavelength_a=2.5,
            total_counts=1000,
        )
    ]
    app, _ = _app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        slot = app._inactive_slot
        slot.show_catalog("IPTS-99999", runs, instrument="EQSANS", facility=str(fake_root)[1:])
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        await pilot.press("V")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("q")
    assert popen.calls and popen.calls[0][:4][1:] == ["-m", "sansdir.viewer", str(nexus)]


def test_viewer_available_finds_the_extra_without_importing_qt() -> None:
    import sys

    pytest.importorskip("PySide6")
    pytest.importorskip("pyqtgraph")
    loaded = {m for m in sys.modules if m.startswith(("PySide6", "pyqtgraph"))}
    assert builtins.viewer_available()
    assert {m for m in sys.modules if m.startswith(("PySide6", "pyqtgraph"))} == loaded
