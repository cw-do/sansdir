"""Colour-scale helpers (Phase 9.10.1; the panel itself is 9.10.2)."""

from __future__ import annotations

import numpy as np
import pytest

from sansdir.viewer.colorscale import auto_limits, display_levels, display_values


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
