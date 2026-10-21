"""Neighbouring runs for PgUp / PgDn and the preload policy (Phase 9.10.5, Qt-free)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sansdir.viewer import runs
from sansdir.viewer.cache import CubeCache
from sansdir.viewer.cube import load_cube
from sansdir.viewer.runs import neighbour, sibling_runs, split_run, worth_preloading
from tests.viewer.test_cube import _events, _write_raw


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    for name in [
        "EQSANS_100.nxs.h5",
        "EQSANS_101.nxs.h5",
        "EQSANS_105.nxs.h5",  # a gap: 102-104 missing
        "EQSANS_99.nxs.h5",
        "EQSANS_103.nxs",  # other suffix: not a sibling of the .nxs.h5 runs
        "BIOSANS_102.nxs.h5",  # other prefix
        "EQSANS_101_mask.nxs",
        "notes.txt",
    ]:
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "EQSANS_102.nxs.h5").mkdir()  # a folder is not a run
    return tmp_path


def test_split_run() -> None:
    assert split_run("EQSANS_176669.nxs.h5") == ("EQSANS_", 176669, ".nxs.h5")
    assert split_run("EQSANS_12.nxs") == ("EQSANS_", 12, ".nxs")
    assert split_run("mask.nxs") is None and split_run("EQSANS_1.txt") is None


def test_sibling_runs_share_prefix_and_suffix(folder: Path) -> None:
    found = [run for run, _ in sibling_runs(folder / "EQSANS_100.nxs.h5")]
    assert found == [99, 100, 101, 105]


def test_neighbour_skips_gaps_and_stops_at_the_ends(folder: Path) -> None:
    here = folder / "EQSANS_101.nxs.h5"
    assert neighbour(here, 1) == folder / "EQSANS_105.nxs.h5"
    assert neighbour(here, -1) == folder / "EQSANS_100.nxs.h5"
    assert neighbour(here, -2) == folder / "EQSANS_99.nxs.h5"
    assert neighbour(folder / "EQSANS_105.nxs.h5", 1) is None
    assert neighbour(folder / "EQSANS_99.nxs.h5", -1) is None
    assert neighbour(folder / "notes.txt", 1) is None


def test_neighbour_of_a_missing_run_still_finds_the_next(folder: Path) -> None:
    assert neighbour(folder / "EQSANS_102.nxs.h5", 1) == folder / "EQSANS_105.nxs.h5"


def test_preload_only_cached_or_small_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _write_raw(tmp_path / "EQSANS_7.nxs.h5", _events())
    cache = CubeCache(tmp_path / "cache", min_load_seconds=0.0)
    assert worth_preloading(raw, cache, 16)  # small
    monkeypatch.setattr(runs, "PRELOAD_MAX_BYTES", 10)
    assert not worth_preloading(raw, cache, 16)  # "big" and not cached
    cache.put(load_cube(raw, nbins=16), 16)
    assert worth_preloading(raw, cache, 16)  # big but cached
    assert not worth_preloading(tmp_path / "gone.nxs.h5", None, 16)
