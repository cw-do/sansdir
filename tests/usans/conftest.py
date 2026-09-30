"""Fixtures for the USANS reduction tests.

Everything here is synthetic: a handful of fake run records and an
``autoreduce``-shaped directory of empty ARN files. That keeps the suite
runnable off-cluster, where ``/SNS/USANS`` doesn't exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import pytest

from sansdir.usans.reconcile import DETECTOR_PATTERN, MONITOR_PATTERN


@dataclass(frozen=True)
class FakeRun:
    """Minimal stand-in for :class:`sansdir.core.oncat.Datafile`."""

    run_number: int
    title: str


def make_block(start: int, title: str, n: int) -> list[FakeRun]:
    """``n`` consecutive runs sharing ``title``, starting at ``start``."""
    return [FakeRun(run_number=start + i, title=title) for i in range(n)]


def write_arn(data_dir: Path, runs: list[int]) -> None:
    """Create the two ARN files that mark each run in ``runs`` as reducible."""
    data_dir.mkdir(parents=True, exist_ok=True)
    for run in runs:
        (data_dir / MONITOR_PATTERN.format(run=run)).write_text("0,0\n", encoding="utf-8")
        (data_dir / DETECTOR_PATTERN.format(run=run)).write_text("0,0\n", encoding="utf-8")


@pytest.fixture
def runs_5x() -> list[FakeRun]:
    """A realistic IPTS shape: 5-run blocks (4 ARN scans + 1 transmission).

    Two pre-experiment test blocks, then the empty cell, then three samples.
    Mirrors IPTS-37679's structure without any of its data.
    """
    runs: list[FakeRun] = []
    runs += make_block(1000, "alignment", 3)
    runs += make_block(1003, "emptyBanjo", 5)
    runs += make_block(1008, "S0-20C 1p", 5)
    runs += make_block(1013, "S0-40C", 5)
    runs += make_block(1018, "S1-L62 0p", 5)
    return runs


@pytest.fixture
def data_dir_5x(tmp_path: Path, runs_5x: list[FakeRun]) -> Path:
    """Autoreduce folder where every block's first four runs have ARN files."""
    data_dir = tmp_path / "autoreduce"
    scans: list[int] = []
    for start in (1003, 1008, 1013, 1018):
        scans.extend(range(start, start + 4))
    write_arn(data_dir, scans)
    return data_dir


@pytest.fixture
def stub_oncat(monkeypatch):  # type: ignore[no-untyped-def]
    """Offline stand-in for :class:`~sansdir.core.oncat.OnCatClient`.

    ``usans.init_table`` fetches its run list itself when the loaded
    catalog can't supply one. No test may reach the real service, so this
    swaps the client for a stub whose returned runs the test controls and
    whose calls it can assert on::

        stub_oncat.runs = runs_5x
        ...
        assert stub_oncat.calls == [("IPTS-1", "USANS")]
    """

    class _Stub:
        runs: ClassVar[list] = []
        calls: ClassVar[list] = []

        def __init__(self, _config, **_kwargs) -> None:
            pass

        async def __aenter__(self) -> _Stub:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def list_datafiles(self, ipts, *, instrument="", **_kwargs):  # type: ignore[no-untyped-def]
            type(self).calls.append((ipts, instrument))
            return list(type(self).runs)

    _Stub.runs = []
    _Stub.calls = []
    monkeypatch.setattr("sansdir.core.oncat.OnCatClient", _Stub)
    return _Stub


# ---------------------------------------------------------------------------
# IPTS-35306 shape: a 1.2 Å first run in every block, pause runs in front of
# two blocks, and no trailing transmission run.
# ---------------------------------------------------------------------------

# (title, first run, run count) — the real IPTS-35306 blocks.
BLOCKS_35306: list[tuple[str, int, int]] = [
    ("Blank", 48219, 7),
    ("#1", 48226, 7),
    ("#2", 48233, 8),  # 48233 is a pause
    ("#3", 48241, 7),
    ("#4", 48248, 8),  # 48248 is a pause
    ("#5", 48256, 7),
    ("#6", 48263, 7),
    ("#7", 48270, 7),
    ("#8", 48277, 7),
    ("#9", 48284, 7),
    ("AO Buffer", 48291, 6),
]
PAUSES_35306: tuple[int, ...] = (48233, 48248)

# The hand-verified table (Topic_2026_oMMT_oil usans_tb/setup_tb.csv).
EXPECTED_35306: list[str] = [
    "t,Blank_T,48220,6,0.2",
    "b,Blank,48220,6,0.2",
    "s,#1,48227,6,0.2",
    "s,#2,48235,6,0.2",
    "s,#3,48242,6,0.2",
    "s,#4,48250,6,0.2",
    "s,#5,48257,6,0.2",
    "s,#6,48264,6,0.2",
    "s,#7,48271,6,0.2",
    "s,#8,48278,6,0.2",
    "s,#9,48285,6,0.2",
    "s,AO,48292,5,0.2",
]


def write_monitor(data_dir: Path, run: int, counts: int) -> None:
    """Whole-run ``USANS_<run>_monitor.txt`` in autoreduction's ``X,Y,E`` layout."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / f"USANS_{run}_monitor.txt").write_text(
        f"# X , Y , E Distribution=false\n\n5,{counts},1.0\n", encoding="utf-8"
    )


def write_wavelength(data_dir: Path, run: int, wavelength: str) -> None:
    """The ``USANS_<run>_detector_<λ>.txt`` marker autoreduction writes."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / f"USANS_{run}_detector_{wavelength}.txt").write_text("", encoding="utf-8")


@pytest.fixture
def runs_35306() -> list[FakeRun]:
    runs: list[FakeRun] = []
    for title, start, n in BLOCKS_35306:
        runs += make_block(start, title, n)
    return runs


@pytest.fixture
def data_dir_35306(tmp_path: Path) -> Path:
    """First run of each block: ARN files but only ``_1.2`` and a tiny monitor.

    Pause runs: no ARN files, monitor ~10. Every other run: a normal 3.6 Å scan.
    """
    data_dir = tmp_path / "autoreduce"
    for _title, start, n in BLOCKS_35306:
        runs = [r for r in range(start, start + n) if r not in PAUSES_35306]
        first, rest = runs[0], runs[1:]
        write_arn(data_dir, runs)
        write_wavelength(data_dir, first, "1.2")
        write_monitor(data_dir, first, 67_000)
        for r in rest:
            write_wavelength(data_dir, r, "3.6")
            write_monitor(data_dir, r, 1_100_000)
    for r in PAUSES_35306:
        write_monitor(data_dir, r, 10)
    return data_dir
