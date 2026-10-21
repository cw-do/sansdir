"""On-disk TOF-cube cache."""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest

from sansdir.viewer.cache import (
    STALE_SECONDS,
    CubeCache,
    default_cache_dir,
    describe,
    format_bytes,
)
from sansdir.viewer.cube import TofCube, load_cube
from tests.viewer.test_cube import _events, _write_raw


@pytest.fixture
def raw_file(tmp_path: Path) -> Path:
    return _write_raw(tmp_path / "EQSANS_4242.nxs.h5", _events())


@pytest.fixture
def cache(tmp_path: Path) -> CubeCache:
    return CubeCache(tmp_path / "cache", min_load_seconds=0.0)


def _slow(cube: TofCube) -> TofCube:
    cube.timings["total"] = 99.0
    return cube


def test_round_trip(cache: CubeCache, raw_file: Path) -> None:
    cube = load_cube(raw_file, nbins=64)
    assert cache.put(cube, 64) is not None
    hit = cache.get(raw_file, 64)
    assert hit is not None
    assert np.array_equal(hit.cum, cube.cum)
    assert hit.tof_edges is not None and cube.tof_edges is not None
    assert np.array_equal(hit.tof_edges, cube.tof_edges)
    assert np.array_equal(hit.spectrum(), cube.spectrum())
    assert (hit.run_number, hit.title, hit.n_events) == ("4242", "synthetic run", 48 * 400)
    assert hit.path == raw_file and "cache_read" in hit.timings
    assert not cache.should_store(hit)  # never re-save what came from the cache


def test_changed_file_or_bins_is_a_miss(cache: CubeCache, raw_file: Path) -> None:
    cache.put(load_cube(raw_file, nbins=64), 64)
    assert cache.get(raw_file, 32) is None
    st = raw_file.stat()
    os.utime(raw_file, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))  # live run grew
    assert cache.get(raw_file, 64) is None


def test_only_slow_complete_raw_loads_are_stored(tmp_path: Path, raw_file: Path) -> None:
    cache = CubeCache(tmp_path / "c", min_load_seconds=2.0)
    cube = load_cube(raw_file, nbins=16)
    assert not cache.should_store(cube)  # fast
    assert cache.should_store(_slow(cube))
    cube.scale = 5.0
    assert not cache.should_store(cube)  # a preview


def test_corrupt_entry_is_dropped(cache: CubeCache, raw_file: Path) -> None:
    data = cache.put(load_cube(raw_file, nbins=16), 16)
    assert data is not None
    data.write_bytes(b"not a numpy file")
    assert cache.get(raw_file, 16) is None
    assert list(cache.directory.iterdir()) == []


def test_eviction_keeps_the_newest_under_the_cap(tmp_path: Path) -> None:
    files = [_write_raw(tmp_path / f"EQSANS_{i}.nxs.h5", _events(seed=i)) for i in range(3)]
    probe = CubeCache(tmp_path / "probe", min_load_seconds=0.0)
    probe.put(load_cube(files[0], nbins=16), 16)
    one_entry = sum(p.stat().st_size for p in probe.directory.iterdir())

    cache = CubeCache(tmp_path / "cache", max_bytes=int(one_entry * 2.5), min_load_seconds=0.0)
    for i, f in enumerate(files):
        cache.put(load_cube(f, nbins=16), 16)
        for p in cache.directory.iterdir():  # make put order = age order
            if p.name.startswith(f"EQSANS_{i}_"):
                os.utime(p, (time.time() - 100 + i, time.time() - 100 + i))
    assert cache.get(files[0], 16) is None
    assert cache.get(files[1], 16) is not None
    assert cache.get(files[2], 16) is not None


def test_abandoned_halves_are_cleaned(cache: CubeCache, raw_file: Path) -> None:
    cache.directory.mkdir(parents=True)
    old = time.time() - STALE_SECONDS - 10
    orphan = cache.directory / "EQSANS_1_deadbeefdeadbeef.npy"
    tmp = cache.directory / "EQSANS_1_deadbeefdeadbeef.json.123.tmp"
    fresh = cache.directory / "EQSANS_2_0123456789abcdef.npy"  # a writer mid-rename
    for p in (orphan, tmp, fresh):
        p.write_bytes(b"x")
    for p in (orphan, tmp):
        os.utime(p, (old, old))
    cache.put(load_cube(raw_file, nbins=16), 16)
    names = {p.name for p in cache.directory.iterdir()}
    assert orphan.name not in names and tmp.name not in names
    assert fresh.name in names


def test_default_dir_honours_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path))
    assert default_cache_dir() == tmp_path / "viewer"


def test_summary_and_clear(cache: CubeCache, raw_file: Path, tmp_path: Path) -> None:
    assert cache.summary() == (0, 0)
    cache.put(load_cube(raw_file, nbins=16), 16)
    other = _write_raw(tmp_path / "EQSANS_7.nxs.h5", _events(seed=9))
    cache.put(load_cube(other, nbins=16), 16)
    keep = cache.directory / "notes.txt"  # not ours: must survive
    keep.write_text("x")
    runs, size = cache.summary()
    assert runs == 2 and size > 0
    assert cache.clear() == (runs, size)
    assert cache.summary() == (0, 0)
    assert [p.name for p in cache.directory.iterdir()] == ["notes.txt"]
    assert cache.get(raw_file, 16) is None


def test_clear_on_a_missing_directory(tmp_path: Path) -> None:
    assert CubeCache(tmp_path / "never-made").clear() == (0, 0)


@pytest.mark.parametrize(
    ("n", "text"),
    [(0, "0 B"), (2048, "2.0 kB"), (93_192_320, "88.9 MB"), (1_181_116_006, "1.1 GB")],
)
def test_format_bytes(n: int, text: str) -> None:
    assert format_bytes(n) == text


def test_describe() -> None:
    assert describe(1, 2048) == "1 run, 2.0 kB"
    assert describe(12, 1_181_116_006) == "12 runs, 1.1 GB"


def test_cli_clear_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sansdir.viewer.__main__ import main

    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path / "home-cache"))
    CubeCache(default_cache_dir(), min_load_seconds=0.0).put(load_cube(raw_file, nbins=16), 16)
    assert main(["--clear-cache"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("removed 1 run, ") and str(default_cache_dir()) in out
    assert CubeCache.default().summary() == (0, 0)
