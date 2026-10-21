"""TOF selection maths behind the viewer's TOF panel (Phase 9.10.2)."""

from __future__ import annotations

import numpy as np
import pytest

from sansdir.viewer.tofrange import clamp, default_width, describe, snap, step

EDGES = np.arange(0.0, 1001.0, 100.0)  # 10 bins of 100 µs


def test_snap_goes_to_the_nearest_edges() -> None:
    assert snap(EDGES, 140, 360) == (1, 4)
    assert snap(EDGES, 360, 140) == (1, 4)  # either order
    assert snap(EDGES, -50, 2000) == (0, 10)


def test_snap_never_returns_an_empty_range() -> None:
    assert snap(EDGES, 310, 330) == (3, 4)
    assert snap(EDGES, 990, 1000) == (9, 10)


def test_clamp_keeps_the_width_inside_the_run() -> None:
    assert clamp(8, 12, 10) == (6, 10)
    assert clamp(-3, 2, 10) == (0, 5)
    assert clamp(4, 4, 10) == (4, 5)
    assert clamp(0, 50, 10) == (0, 10)


def test_step_moves_by_one_width() -> None:
    assert step(0, 3, 10) == (3, 6)
    assert step(3, 6, 10, -1) == (0, 3)
    assert step(0, 3, 10, 2) == (6, 9)


def test_step_reaches_the_end_then_wraps() -> None:
    assert step(6, 9, 10) == (7, 10)  # partial step to the last full window
    assert step(7, 10, 10) == (0, 3)  # then back to the start
    assert step(0, 3, 10, -1) == (7, 10)
    assert step(7, 10, 10, wrap=False) == (7, 10)


def test_default_width() -> None:
    assert default_width(500) == 20
    assert default_width(10) == 1


@pytest.mark.parametrize(
    ("a", "b", "text"),
    [
        (0, 10, "all TOF 0.00-1.00 ms · 10 bins"),
        (2, 5, "TOF 0.200-0.500 ms · bins 2-4 of 10"),
        (7, 8, "TOF 0.700-0.800 ms · bin 7 of 10"),
    ],
)
def test_describe(a: int, b: int, text: str) -> None:
    assert describe(EDGES, a, b) == text


def test_describe_without_tof() -> None:
    assert describe(None, 0, 1) == "no TOF (processed file)"
