"""Colour-scale maths and :class:`ScaleState` (Phases 9.10.1-9.10.2)."""

from __future__ import annotations

import numpy as np
import pytest

from sansdir.viewer.colorscale import (
    LOG_FLOOR,
    ScaleState,
    auto_limits,
    count_label,
    counts_from_levels,
    display_levels,
    display_values,
    full_limits,
    log_ticks,
)


def test_log_display_hides_zero_counts() -> None:
    shown = display_values(np.array([[0, 1, 100]]), log=True)
    assert np.isnan(shown[0, 0])
    assert shown[0, 1:].tolist() == pytest.approx([0.0, 2.0])


def test_linear_display_is_unchanged() -> None:
    assert display_values(np.array([[0, 5]]), log=False).tolist() == [[0.0, 5.0]]


def test_levels_are_counts_in_both_modes() -> None:
    assert display_levels(10, 1000, log=True) == pytest.approx((1.0, 3.0))
    assert display_levels(10, 1000, log=False) == (10.0, 1000.0)


def test_auto_limits_ignore_zeros_and_masked_pixels() -> None:
    image = np.zeros((10, 10))
    image[0, :] = np.arange(1, 11)
    image[5, 5] = 1e9
    mask = np.zeros_like(image, dtype=bool)
    mask[5, 5] = True
    lo, hi = auto_limits(image, percentiles=(0, 100), mask=mask)
    assert (lo, hi) == (1.0, 10.0)


def test_auto_limits_on_an_empty_image() -> None:
    assert auto_limits(np.zeros((4, 4)), log=True) == (1.0, 10.0)


def test_levels_round_trip_to_counts() -> None:
    levels = display_levels(5, 5000, log=True)
    assert counts_from_levels(*levels, log=True) == pytest.approx((5, 5000))
    assert counts_from_levels(2, 7, log=False) == (2, 7)


def test_full_limits_span_the_data() -> None:
    image = np.array([[0, 3, 40], [7, 0, 900]])
    assert full_limits(image, log=True) == (3.0, 900.0)
    assert full_limits(image, log=False) == (0.0, 900.0)
    assert full_limits(np.zeros((2, 2)), log=True) == (1.0, 10.0)


@pytest.mark.parametrize(
    ("value", "text"),
    [(0.01, "0.01"), (1, "1"), (50, "50"), (100, "100"), (1000, "1k"), (2.5e4, "25k"),
     (1e6, "1M"), (3e9, "3G")],
)  # fmt: skip
def test_count_label(value: float, text: str) -> None:
    assert count_label(value) == text


def test_log_ticks_label_decades_in_counts() -> None:
    major, minor = log_ticks(-0.5, 3.2)  # 0.3 … 1600 counts, > 2 decades
    assert [label for _, label in major] == ["0.1", "1", "10", "100", "1k", "10k"]
    assert [pos for pos, _ in major] == [-1, 0, 1, 2, 3, 4]
    assert all(label == "" for _, label in minor)
    assert any(pos == pytest.approx(np.log10(20)) for pos, _ in minor)


def test_log_ticks_label_2_and_5_on_a_narrow_range() -> None:
    major, _ = log_ticks(1.1, 2.6)
    labels = [label for _, label in major]
    assert {"20", "50", "100", "200", "500"} <= set(labels)


def test_log_ticks_on_an_empty_image() -> None:
    assert log_ticks(float("nan"), 1.0) == ([], [])


def test_unlocked_state_re_autos_every_image() -> None:
    state = ScaleState(percentiles=(0, 100))
    assert state.limits_for(np.array([[1.0, 10.0]])) == (1.0, 10.0)
    assert state.limits_for(np.array([[5.0, 500.0]])) == (5.0, 500.0)


def test_locked_state_keeps_its_limits() -> None:
    state = ScaleState(percentiles=(0, 100))
    state.set_limits(2, 20)
    state.locked = True
    assert state.limits_for(np.array([[5.0, 500.0]])) == (2.0, 20.0)
    state.auto(np.array([[5.0, 500.0]]))  # the Auto button still works while locked
    assert (state.vmin, state.vmax) == (5.0, 500.0)
    state.reset(np.array([[0.0, 4.0, 8.0]]))
    assert (state.vmin, state.vmax) == (4.0, 8.0)


def test_set_limits_keeps_them_valid() -> None:
    state = ScaleState(log=True)
    state.set_limits(0, 50)  # 0 cannot be shown in log
    assert state.vmin == LOG_FLOOR and state.vmax == 50
    state.set_limits(30, 10)  # max below min
    assert (state.vmin, state.vmax) == (30, 300)
    state.log = False
    state.set_limits(-4, 10)
    assert (state.vmin, state.vmax) == (0, 10)


def test_switching_to_log_replaces_a_zero_minimum() -> None:
    image = np.array([[0.0, 2.0, 8.0, 100.0]])
    state = ScaleState(log=False, locked=True, percentiles=(0, 100))
    state.set_limits(0, 100)
    state.set_log(True, image)
    assert state.log and state.vmin == 2.0 and state.vmax == 100.0


def test_percentiles_are_sorted_and_clipped() -> None:
    state = ScaleState()
    state.set_percentiles(99.5, -3)
    assert state.percentiles == (0.0, 99.5)
