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
