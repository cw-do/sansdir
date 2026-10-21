"""Viewer preferences file (replaces QSettings, whose lock file froze the window on NFS)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sansdir.viewer.colorscale import ScaleState
from sansdir.viewer.settings import default_path, load_scale, save_scale


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "viewer.json"
    state = ScaleState(log=False, locked=True, cmap="jet", percentiles=(2.0, 98.0))
    state.set_limits(3, 300)
    assert save_scale(path, state)
    assert load_scale(path) == state
    assert [p.name for p in path.parent.iterdir()] == ["viewer.json"]  # no temp files left


def test_missing_or_bad_files_give_defaults(tmp_path: Path) -> None:
    assert load_scale(tmp_path / "none.json") == ScaleState()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load_scale(bad) == ScaleState()
    odd = tmp_path / "odd.json"
    odd.write_text(json.dumps({"scale": {"cmap": "nope", "vmin": "abc", "log": False}}))
    state = load_scale(odd)
    assert state.cmap == "viridis" and state.vmin == 1.0 and not state.log


def test_an_unwritable_place_is_reported_not_raised(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert not save_scale(blocker / "viewer.json", ScaleState())


def test_default_path_follows_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert default_path() == tmp_path / "sansdir" / "viewer.json"
