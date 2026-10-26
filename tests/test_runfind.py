"""``f`` / ``:find`` — find a run's raw file by number alone, across IPTS folders."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import ClassVar

import pytest

from sansdir.app import SansdirApp
from sansdir.commands import builtins
from sansdir.core import runfind
from sansdir.core.history import CommandHistory
from sansdir.core.runfind import find_run, ipts_dirs, ipts_of, parse_run

_REAL_POPEN = subprocess.Popen


@pytest.fixture(autouse=True)
def _fresh_hint() -> None:
    runfind._last_hit_ipts = None


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A fake /SNS/EQSANS: current and older layouts, plus noise."""
    root = tmp_path / "EQSANS"
    for ipts, rel in [
        ("IPTS-37425", "nexus/EQSANS_176669.nxs.h5"),
        ("IPTS-37425", "nexus/EQSANS_176670.nxs.h5"),
        ("IPTS-21605", "nexus/EQSANS_109879.nxs.h5"),
        ("IPTS-7181", "data/EQSANS_16470_event.nxs"),
        ("IPTS-7181", "data/EQSANS_16470_histo.nxs"),
        ("IPTS-0000", "nexus/EQSANS_92441.nxs.h5"),
        ("IPTS-38269", "shared/EQSANS_176669.nxs.h5"),  # a copy in shared/: not a raw file
    ]:
        path = root / ipts / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    (root / "2010_2_6_SCI").mkdir()
    (root / "IPTS-99999").mkdir()  # empty
    return root


@pytest.mark.parametrize(
    ("text", "run"),
    [("176669", 176669), ("EQSANS_176669", 176669), (" run 16470 ", 16470), ("abc", None)],
)
def test_parse_run(text: str, run: int | None) -> None:
    assert parse_run(text) == run


def test_finds_both_layouts(tree: Path) -> None:
    assert find_run(176669, root=tree) == [tree / "IPTS-37425/nexus/EQSANS_176669.nxs.h5"]
    assert find_run(16470, root=tree) == [tree / "IPTS-7181/data/EQSANS_16470_event.nxs"]
    assert find_run(92441, root=tree) == [tree / "IPTS-0000/nexus/EQSANS_92441.nxs.h5"]
    assert find_run(5, root=tree) == []


def test_ipts_folders_newest_first(tree: Path) -> None:
    assert [d.name for d in ipts_dirs(tree)] == [
        "IPTS-99999", "IPTS-38269", "IPTS-37425", "IPTS-21605", "IPTS-7181", "IPTS-0000",
    ]  # fmt: skip
    assert ipts_dirs(tree / "missing") == []


def test_ipts_of(tree: Path) -> None:
    assert ipts_of(tree / "IPTS-37425/shared/sub") == tree / "IPTS-37425"
    assert ipts_of(tree / "IPTS-37425") == tree / "IPTS-37425"
    assert ipts_of(tree) is None and ipts_of(None) is None


def test_hints_skip_the_full_scan(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    near = tree / "IPTS-37425" / "shared"
    assert find_run(176670, root=tree, near=near)[0].name == "EQSANS_176670.nxs.h5"

    def no_scan(_root: Path) -> list[Path]:
        raise AssertionError("full scan not expected")

    monkeypatch.setattr(runfind, "ipts_dirs", no_scan)
    assert find_run(176669, root=tree)  # the last hit's IPTS answers first
    monkeypatch.undo()
    assert find_run(109879, root=tree, near=near)  # a hint miss falls back to the scan


def test_root_from_environment(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(runfind.ROOT_ENV, str(tree))
    assert find_run(109879)[0].parent == tree / "IPTS-21605/nexus"


# -- the TUI: f → find 176669 → right pane + viewer ---------------------------------


class _FakePopen:
    calls: ClassVar[list[list[str]]] = []

    def __new__(cls, cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        if "sansdir.viewer" not in list(cmd):
            return _REAL_POPEN(cmd, *args, **kwargs)
        return super().__new__(cls)

    def __init__(self, cmd, **_kwargs):  # type: ignore[no-untyped-def]
        type(self).calls.append(list(cmd))

    def wait(self) -> int:
        return 0


@pytest.fixture
def app_in(tmp_path: Path, tree: Path, monkeypatch: pytest.MonkeyPatch) -> SansdirApp:
    monkeypatch.setenv(runfind.ROOT_ENV, str(tree))
    monkeypatch.setattr("subprocess.Popen", _FakePopen)
    monkeypatch.setattr("sansdir.plot.backend.has_display", lambda: True)
    monkeypatch.setattr(builtins, "viewer_available", lambda: True)
    _FakePopen.calls = []
    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir()
    right.mkdir()
    return SansdirApp(
        start_path=left,
        right_path=right,
        history=CommandHistory(path=tmp_path / "hist", load=False),
    )


async def _find(app: SansdirApp, text: str) -> list[str]:
    notes: list[str] = []
    async with app.run_test() as pilot:
        await pilot.pause()
        original = app.notify_user

        def record(message: str, **kwargs):  # type: ignore[no-untyped-def]
            notes.append(message)
            return original(message, **kwargs)

        app.notify_user = record  # type: ignore[method-assign]
        await pilot.press("f")
        await pilot.pause()
        assert app._cmdline.value == "find "
        for ch in text:
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause(0.3)
        app._state = (  # type: ignore[attr-defined]
            app._active_id,
            app._right.cwd,
            app._right.cursor_path,
        )
        await pilot.press("q")
    return notes


async def test_f_finds_the_run_and_opens_it(app_in: SansdirApp, tree: Path) -> None:
    notes = await _find(app_in, "176669")
    active, right_cwd, cursor = app_in._state  # type: ignore[attr-defined]
    nexus = (tree / "IPTS-37425" / "nexus").resolve()
    assert active == "right" and right_cwd == nexus
    assert cursor == nexus / "EQSANS_176669.nxs.h5"
    assert any("run 176669: IPTS-37425/nexus/EQSANS_176669.nxs.h5" in n for n in notes)
    assert _FakePopen.calls and _FakePopen.calls[0][3:5] == [
        "sansdir.viewer",
        str(tree / "IPTS-37425/nexus/EQSANS_176669.nxs.h5"),
    ]


async def test_f_lands_on_an_older_symlinked_run(app_in: SansdirApp, tree: Path) -> None:
    link_target = tree / "IPTS-7181" / "0" / "16471" / "NeXus" / "EQSANS_16471_event.nxs"
    link_target.parent.mkdir(parents=True)
    link_target.write_bytes(b"x")
    (tree / "IPTS-7181" / "data" / "EQSANS_16471_event.nxs").symlink_to(link_target)
    await _find(app_in, "16471")
    _active, right_cwd, cursor = app_in._state  # type: ignore[attr-defined]
    assert right_cwd == (tree / "IPTS-7181" / "data").resolve()  # not the link's target
    assert cursor is not None and cursor.name == "EQSANS_16471_event.nxs"


async def test_f_says_when_a_run_is_not_found(app_in: SansdirApp) -> None:
    notes = await _find(app_in, "5")
    assert any("run 5: no EQSANS_5.nxs.h5" in n for n in notes)
    assert _FakePopen.calls == []
