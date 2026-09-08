"""Tests for sansdir.usans.desmear — the truncated Abel inversion.

The load-bearing tests are round trips against an analytic ground truth: take
a known power law, smear it with the real slit kernel, desmear it, and check
the original comes back. Slit smearing flattens a power law by exactly one
power, so ``Q^-4 -> smeared Q^-3 -> desmeared Q^-4`` is a sharp check that
catches sign errors, factor-of-two errors and a mis-scaled sigma_y at once.

Two numerical properties were found the hard way and are pinned here so they
cannot regress:

* past the top of the data the integrand must use the *model* derivative, not
  a clamped ``np.interp`` (worth >100% at the top of the range);
* the low-Q padding must carry the same relative error as the data, or the
  smoother downweights it and the first point is biased by tens of percent.
"""

from __future__ import annotations

import numpy as np
import pytest

from sansdir.usans.desmear import (
    DEFAULT_SIGMA_Y,
    DesmearError,
    _model_derivative,
    abel_invert,
    desmear,
    pick_bandwidth,
    power_law_fit,
    sigma_y_from_geometry,
    slit_nodes,
    smear,
    smooth_log,
)

# Analytic ground truth used throughout: I = A * Q^slope.
AMP = 1e-6


def power_law(slope: float):  # type: ignore[no-untyped-def]
    def fn(q):  # type: ignore[no-untyped-def]
        return AMP * np.asarray(q, dtype=float) ** slope

    return fn


def usans_q(n: int = 60) -> np.ndarray:
    """A realistic USANS abscissa: 5e-5 to 3e-3 A^-1."""
    return np.geomspace(5e-5, 3e-3, n)


def loglog_slope(q: np.ndarray, i: np.ndarray) -> float:
    return float(np.polyfit(np.log10(q), np.log10(np.maximum(i, 1e-300)), 1)[0])


# ---------------------------------------------------------------------------
# Geometry and kernel
# ---------------------------------------------------------------------------


def test_sigma_y_matches_the_papers_formula() -> None:
    """Eq. 17: sigma_y = 2*pi*H/(lambda*L)."""
    got = sigma_y_from_geometry(detector_height_cm=17.78, distance_m=2.13, wavelength_a=3.6)
    expected = 2 * np.pi * (17.78 * 1e8) / (3.6 * 2.13 * 1e10)
    assert got == pytest.approx(expected, rel=1e-12)


def test_default_sigma_y_is_the_sns_value() -> None:
    assert pytest.approx(0.13) == DEFAULT_SIGMA_Y


def test_slit_nodes_span_the_slit_and_crowd_toward_zero() -> None:
    s = slit_nodes(0.13, 100)
    assert s[0] == 0.0
    assert s[-1] == pytest.approx(0.13)
    assert np.all(np.diff(s) >= 0)
    # Cubic stretching: the first gap is far smaller than the last.
    assert np.diff(s)[0] < np.diff(s)[-1] / 100


# ---------------------------------------------------------------------------
# Forward model
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slope", [-4.0, -3.0, -2.0])
def test_smearing_flattens_a_power_law_by_exactly_one(slope: float) -> None:
    """The analytic signature of slit averaging when Q << sigma_y."""
    q = usans_q()
    smeared = smear(power_law(slope), q)
    assert loglog_slope(q, smeared) == pytest.approx(slope + 1.0, abs=0.02)


def test_smear_is_positive_and_finite() -> None:
    out = smear(power_law(-4.0), usans_q())
    assert np.all(np.isfinite(out)) and np.all(out > 0)


# ---------------------------------------------------------------------------
# Round trip — the real test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slope", [-4.0, -3.5, -3.0, -2.5, -2.0])
def test_desmear_recovers_the_true_power_law_without_sans(slope: float) -> None:
    q = usans_q()
    smeared = smear(power_law(slope), q)
    result = desmear(q, smeared, 0.02 * smeared)
    assert result.mode == "usans-only"
    assert loglog_slope(result.q, result.intensity) == pytest.approx(slope, abs=0.03)


@pytest.mark.parametrize("slope", [-4.0, -3.0])
def test_desmear_core_range_is_accurate_to_about_one_percent(slope: float) -> None:
    """Over the heart of the USANS window the inversion is essentially exact."""
    truth = power_law(slope)
    q = usans_q()
    smeared = smear(truth, q)
    result = desmear(q, smeared, 0.02 * smeared)
    core = (result.q >= 1e-4) & (result.q <= 8e-4)
    rel = np.abs(result.intensity[core] / truth(result.q[core]) - 1.0)
    assert np.median(rel) < 0.02, f"median error {np.median(rel):.1%}"


def test_desmear_uncertainty_covers_the_result() -> None:
    """The quoted dI must bracket the truth nearly everywhere.

    It widens sharply at the top of the range, which is exactly where the
    high-Q extrapolation stops being trustworthy — that honesty is the point.
    """
    truth = power_law(-4.0)
    q = usans_q()
    smeared = smear(truth, q)
    r = desmear(q, smeared, 0.02 * smeared)
    z = np.abs(r.intensity - truth(r.q)) / r.sigma
    # The lowest one or two points carry a known smoother edge bias.
    assert np.mean(z <= 1.0) > 0.9
    assert r.sigma[-1] / r.intensity[-1] > 5 * r.sigma[len(r.q) // 2] / r.intensity[len(r.q) // 2]


def test_desmear_with_sans_recovers_the_power_law_and_extends_beyond_usans() -> None:
    truth = power_law(-4.0)
    q = usans_q()
    smeared = smear(truth, q)
    qe = np.geomspace(1e-3, 0.5, 80)
    r = desmear(q, smeared, 0.02 * smeared, sans=(qe, truth(qe), 0.02 * truth(qe)))
    assert r.mode == "with-sans"
    assert loglog_slope(r.q, r.intensity) == pytest.approx(-4.0, abs=0.03)
    assert r.q.max() > q.max() * 10, "with SANS the result should extend past the USANS window"
    assert r.sans_scale == pytest.approx(1.0, abs=0.05)


# ---------------------------------------------------------------------------
# The two numerical fixes, pinned
# ---------------------------------------------------------------------------


def test_model_derivative_matches_an_analytic_power_law() -> None:
    slope, q = -3.7, np.geomspace(1e-4, 1e-1, 25)
    got = _model_derivative(power_law(slope), q)
    expected = AMP * slope * q ** (slope - 1.0)
    assert np.allclose(got, expected, rtol=1e-4)


def test_tail_uses_the_model_derivative_not_a_clamped_one() -> None:
    """Regression: clamping dI/dQ past the data inflated the top of the range.

    With a clamped derivative a Q^-4 benchmark came back >100% high above
    Q ~ 1.5e-3; with the model derivative it is within tens of percent and
    inside the error bar.
    """
    truth = power_law(-4.0)
    q = usans_q()
    smeared = smear(truth, q)
    r = desmear(q, smeared, 0.02 * smeared)
    top = r.q >= 2e-3
    rel = np.abs(r.intensity[top] / truth(r.q[top]) - 1.0)
    assert rel.max() < 0.5, f"top-of-range error {rel.max():.0%} — tail derivative regressed"


def test_padding_carries_the_data_relative_error() -> None:
    """Regression: fixed 10% pad errors biased the lowest point by ~35%.

    ``smooth_log`` weights by 1/(dI/I)^2, so a pad quoted much worse than the
    data is ignored and the edge derivative goes one-sided.
    """
    truth = power_law(-4.0)
    q = usans_q()
    smeared = smear(truth, q)
    r = desmear(q, smeared, 0.02 * smeared)
    first = abs(r.intensity[0] / truth(r.q[0]) - 1.0)
    assert first < 0.15, f"lowest-Q error {first:.1%} — padding weights regressed"


def test_abel_formula_is_exact_given_an_exact_derivative() -> None:
    """Isolates eq. 15 itself from the derivative estimate."""
    truth = power_law(-4.0)
    sy = DEFAULT_SIGMA_Y
    s = slit_nodes(sy, 4000)

    def i_exp(qq: np.ndarray) -> np.ndarray:
        qq = np.atleast_1d(np.asarray(qq, dtype=float))
        vals = truth(np.sqrt(qq[:, None] ** 2 + s[None, :] ** 2))
        return np.trapezoid(vals, s, axis=1) / sy

    q = usans_q(20)
    out = np.empty_like(q)
    for k, qq in enumerate(q):
        qp = np.sqrt(qq**2 + s**2)
        eps = 1e-4
        dprime = (i_exp(qp * (1 + eps)) - i_exp(qp * (1 - eps))) / (qp * 2 * eps)
        out[k] = truth(np.sqrt(qq**2 + sy**2)) - (2 * sy / np.pi) * np.trapezoid(dprime / qp, s)
    assert np.allclose(out, truth(q), rtol=1e-3)


# ---------------------------------------------------------------------------
# Output shape and labelling
# ---------------------------------------------------------------------------


def test_usans_only_is_truncated_to_the_measured_range() -> None:
    """The chosen policy: never hand back the extrapolation-dominated tail."""
    q = usans_q()
    smeared = smear(power_law(-4.0), q)
    r = desmear(q, smeared, 0.02 * smeared)
    assert r.q.min() >= q.min() * 0.999
    assert r.q.max() <= q.max() * 1.001


def test_usans_only_warns_that_high_q_was_assumed() -> None:
    q = usans_q()
    smeared = smear(power_law(-4.0), q)
    r = desmear(q, smeared, 0.02 * smeared)
    joined = " ".join(r.warnings)
    assert "no SANS data" in joined
    assert "extrapolated" in joined
    assert np.isfinite(r.tail_slope)


def test_gain_is_greater_than_one_for_a_falling_curve() -> None:
    """Desmearing restores intensity the slit average spread out."""
    q = usans_q()
    smeared = smear(power_law(-4.0), q)
    assert desmear(q, smeared, 0.02 * smeared).gain_at_low_q > 1.0


def test_n_eval_controls_the_output_grid() -> None:
    q = usans_q()
    smeared = smear(power_law(-4.0), q)
    assert desmear(q, smeared, 0.02 * smeared, n_eval=25).n_points == 25
    assert desmear(q, smeared, 0.02 * smeared).n_points == q.size


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_too_few_points_is_refused() -> None:
    q = np.geomspace(1e-4, 1e-3, 5)
    with pytest.raises(DesmearError, match=">= 8"):
        desmear(q, q**-3.0, 0.02 * q**-3.0)


def test_a_flat_curve_is_refused() -> None:
    """No derivative to invert — both papers say desmearing is meaningless."""
    q = usans_q()
    flat = np.full_like(q, 100.0)
    with pytest.raises(DesmearError, match="flat or rising"):
        desmear(q, flat, 0.02 * flat)


def test_a_rising_curve_is_refused() -> None:
    q = usans_q()
    rising = 1e3 * (q / q[0]) ** 0.5
    with pytest.raises(DesmearError, match="flat or rising"):
        desmear(q, rising, 0.02 * rising)


def test_non_positive_points_are_dropped_not_fatal() -> None:
    q = usans_q()
    smeared = smear(power_law(-4.0), q)
    dirty = smeared.copy()
    dirty[10] = -1.0
    dirty[20] = np.nan
    r = desmear(q, dirty, 0.02 * smeared)
    assert r.n_points == q.size - 2
    assert np.all(np.isfinite(r.intensity))


def test_power_law_fit_needs_enough_points() -> None:
    q = np.geomspace(1e-4, 1e-3, 10)
    with pytest.raises(DesmearError, match="power law"):
        power_law_fit(q, q**-3.0, 1e-2, 1e-1)


# ---------------------------------------------------------------------------
# Smoother internals
# ---------------------------------------------------------------------------


def test_smooth_log_recovers_a_power_law_slope() -> None:
    q = usans_q()
    i = AMP * q**-3.0
    x = np.log(q)
    _, dly = smooth_log(x, i, 0.02 * i, 0.15)
    # d lnI / d lnQ should be the slope, away from the edges.
    assert np.median(dly[5:-5]) == pytest.approx(-3.0, abs=0.05)


def test_pick_bandwidth_returns_a_usable_width() -> None:
    q = usans_q()
    i = AMP * q**-3.0
    h, chi2 = pick_bandwidth(np.log(q), i, 0.02 * i)
    spacing = float(np.median(np.diff(np.log(q))))
    assert h >= 1.5 * spacing
    assert np.isfinite(chi2)


def test_abel_invert_accepts_an_explicit_high_q_model() -> None:
    truth = power_law(-4.0)
    q = usans_q()
    smeared = smear(truth, q)
    out, sig, h, chi2 = abel_invert(q, smeared, 0.02 * smeared, truth, q)
    assert out.shape == q.shape and sig.shape == q.shape
    assert np.isfinite(h) and np.isfinite(chi2)
    # Given the *true* high-Q side this should be very good indeed.
    core = (q >= 1e-4) & (q <= 8e-4)
    assert np.median(np.abs(out[core] / truth(q[core]) - 1)) < 0.02
