"""Desmear slit-smeared USANS I(Q) by truncated Abel inversion.

Bonse-Hart USANS uses slit collimation, so what the instrument records is an
average of the true intensity over a tall vertical acceptance:

    I_exp(Q) = (1/sigma_y) * int_0^{sigma_y} I( sqrt(Q^2 + s^2) ) ds        (1)

``sigma_y`` is the vertical resolution half-width, set by the post-sample
geometry: ``sigma_y = 2*pi*H / (lambda*L)`` for detector height ``H``, sample
-detector distance ``L`` and wavelength ``lambda``. For the SNS instrument
(H = 17.78 cm, L = 2.13 m, lambda = 3.6 A) that is **0.13 A^-1** — two decades
above the top of the measured USANS window.

Inverting (1) is the desmearing problem. This module implements the truncated
Abel inversion of Huang et al., *J. Appl. Cryst.* **59**, 1083 (2026), eq. 15:

    I(Q) = I(Q_m) - (2*sigma_y/pi) * int_Q^{Q_m} I'_exp(Q_x)/sqrt(Q_x^2 - Q^2) dQ_x
    Q_m  = sqrt(Q^2 + sigma_y^2)                                            (15)

It is closed-form and non-iterative, unlike the Lake algorithm it replaces, so
uncertainties propagate through one linear operator instead of accumulating
over iterations.

Every integral here uses the substitution ``Q_x = sqrt(Q^2 + s^2)``, which
removes the ``1/sqrt(Q_x^2 - Q^2)`` singularity: ``dQ_x/sqrt(Q_x^2-Q^2)``
becomes simply ``ds/Q_x``, and the integration range becomes ``s`` in
``[0, sigma_y]``.

**The high-Q problem.** Eq. 15 evaluates ``I`` at ``Q_m ~ sigma_y``, and the
integral spans the whole way out to there. Both are far outside the USANS
window. Huang et al. §3.1.1 and Fig. 2 show what happens without that
information: the reconstruction tracks the truth at low Q, then deviates and
collapses. So this module runs in one of two modes:

``with-sans``
    A companion pinhole SANS curve supplies the high-Q side, following the
    six-step recipe of Huang et al. §3.2 — smear the SANS onto the same slit
    basis, scale-match the two halves, interpolate the gap, then invert.

``usans-only``
    No SANS. The high-Q side is a power law fitted to the top of the USANS
    data and extended to ``sigma_y``. This is what the NIST Igor/Irena package
    does (Kline 2006) and it is a real approximation, not a free lunch: the
    result is reported **only over the measured USANS range**, and the header
    of the written file says so.

Pure and numpy-only: no UI, no network, no scipy. See
:mod:`sansdir.usans.desmear_io` for reading and writing the curve files.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

# ``np.trapz`` was removed in numpy 2.0 in favour of ``np.trapezoid``; sansdir
# supports numpy >= 1.24, so bind whichever this install has.
_trapezoid = getattr(np, "trapezoid", None) or np.trapz  # type: ignore[attr-defined]

# Vertical resolution half-width of the SNS Bonse-Hart USANS, eq. 17 of
# Huang et al. Override via ``[usans].sigma_y`` or :func:`sigma_y_from_geometry`.
DEFAULT_SIGMA_Y: float = 0.13

# Quadrature nodes across the slit. Cubic-stretched toward s = 0: on a uniform
# grid the first step is larger than the lowest measured Q, where the integrand
# changes by ~40x between neighbouring nodes, and the trapezoid rule then
# overestimates every integral at low Q (5x at Q = 1e-4 on a Q^-3 benchmark).
N_SLIT_NODES: int = 400

# Relative uncertainty assigned to points interpolated across the USANS/SANS
# gap. They are not measurements; this keeps them from driving the fit.
GAP_REL_ERR: float = 0.5

# Number of interpolated points placed across the gap.
N_GAP_POINTS: int = 8

# Never let a quoted uncertainty fall below this fraction of the intensity.
# The engine's errors are counting statistics only.
MIN_REL_ERR: float = 0.01


class DesmearError(ValueError):
    """Raised when a curve cannot be desmeared and saying why is useful."""


@dataclass(frozen=True)
class DesmearResult:
    """One desmeared curve plus everything needed to judge it.

    Attributes:
        q: Momentum transfer of the desmeared curve, ascending.
        intensity: Desmeared I(Q).
        sigma: Propagated uncertainty on ``intensity``.
        mode: ``"with-sans"`` or ``"usans-only"``.
        sigma_y: Slit half-width actually used, in A^-1.
        bandwidth: Gaussian smoother width ``h`` in ln Q, chosen by
            leave-one-out cross-validation.
        chi2: Reduced chi-squared of the smoothed curve against the input.
        tail_slope: log-log slope of the high-Q extension. In ``usans-only``
            mode this is the extrapolation that carries the whole high-Q side.
        sans_scale: Multiplicative factor applied to the USANS to line it up
            with the smeared SANS; 1.0 in ``usans-only`` mode.
        join_rms: Scatter (dex) of the two halves about one power law in the
            smeared basis; NaN when there is no SANS.
        warnings: Human-readable caveats to surface to the user.
    """

    q: np.ndarray
    intensity: np.ndarray
    sigma: np.ndarray
    mode: str
    sigma_y: float
    bandwidth: float
    chi2: float
    tail_slope: float
    sans_scale: float = 1.0
    join_rms: float = float("nan")
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def n_points(self) -> int:
        """How many Q points the desmeared curve carries."""
        return int(self.q.size)

    @property
    def gain_at_low_q(self) -> float:
        """Ratio of desmeared to smeared intensity at the lowest Q.

        Slit desmearing recovers intensity that the slit average spread out,
        so this is > 1 for a falling curve. A value near 1 means the
        correction did essentially nothing; a huge value means the derivative
        was steep and the result deserves a second look.
        """
        return float(self._gain)

    _gain: float = 1.0


def sigma_y_from_geometry(
    detector_height_cm: float = 17.78,
    distance_m: float = 2.13,
    wavelength_a: float = 3.6,
) -> float:
    """Slit half-width from instrument geometry, eq. 17 of Huang et al.

    ``sigma_y = 2*pi*H / (lambda*L)``. Defaults are the SNS Bonse-Hart values
    quoted in the paper, which give 0.13 A^-1.

    Args:
        detector_height_cm: Detector tube height ``H``.
        distance_m: Sample-detector distance ``L``.
        wavelength_a: Incident wavelength ``lambda``.

    Returns:
        ``sigma_y`` in A^-1.
    """
    h_a = detector_height_cm * 1e8  # cm -> angstrom
    l_a = distance_m * 1e10  # m  -> angstrom
    return float(2.0 * np.pi * h_a / (wavelength_a * l_a))


def slit_nodes(sigma_y: float, n: int = N_SLIT_NODES) -> np.ndarray:
    """Quadrature nodes in ``s`` over ``[0, sigma_y]``, crowded toward zero."""
    return sigma_y * np.linspace(0.0, 1.0, n) ** 3


# ---------------------------------------------------------------------------
# Forward model
# ---------------------------------------------------------------------------


def smear(
    i_true: Callable[[np.ndarray], np.ndarray],
    q: np.ndarray,
    *,
    sigma_y: float = DEFAULT_SIGMA_Y,
    nodes: np.ndarray | None = None,
) -> np.ndarray:
    """Apply the slit average of eq. 1 to a callable intensity.

    Used to put a pinhole SANS curve onto the same smearing basis as the
    USANS before the two are joined, and to re-smear a desmeared result as a
    consistency check.

    Args:
        i_true: Vectorised ``I(Q)``; must accept and return 1-D arrays.
        q: Where to evaluate the smeared intensity.
        sigma_y: Slit half-width.
        nodes: Precomputed :func:`slit_nodes`; built on demand when omitted.

    Returns:
        ``I_exp`` at each ``q``.
    """
    s = slit_nodes(sigma_y) if nodes is None else nodes
    q = np.atleast_1d(np.asarray(q, dtype=float))
    qp = np.sqrt(q[:, None] ** 2 + s[None, :] ** 2)
    vals = np.asarray(i_true(qp.ravel()), dtype=float).reshape(qp.shape)
    return np.asarray(_trapezoid(vals, s, axis=1) / sigma_y)


# ---------------------------------------------------------------------------
# Derivative estimation
# ---------------------------------------------------------------------------


def smooth_log(
    x: np.ndarray, y: np.ndarray, dy: np.ndarray, h: float
) -> tuple[np.ndarray, np.ndarray]:
    """Gaussian-kernel smoothing of ``ln y`` against ``x = ln Q``.

    Eq. 20 of Huang et al. in spirit: the derivative that eq. 15 needs is
    estimated by convolving with a derivative-of-Gaussian rather than by
    finite differences, which would amplify the noise the inversion then
    integrates.

    Points are weighted by ``1/(dy/y)^2`` so a noisy tail does not drag the
    smooth curve toward it.

    Args:
        x: ``ln Q``, ascending.
        y: Intensity, strictly positive.
        dy: Uncertainty on ``y``.
        h: Kernel width in ``ln Q``.

    Returns:
        ``(ln y_smoothed, d ln y / d ln Q)``.
    """
    w = 1.0 / np.maximum(dy / y, 1e-3) ** 2
    ly = np.log(y)
    d = x[:, None] - x[None, :]
    g = np.exp(-0.5 * (d / h) ** 2) * w[None, :]
    norm = g.sum(axis=1, keepdims=True)
    ly_s = (g @ ly) / norm[:, 0]
    # Differentiate the smoother analytically rather than the data.
    dg = (-d / h**2) * g
    dnorm = dg.sum(axis=1, keepdims=True)
    dly = (dg @ ly) / norm[:, 0] - ly_s * dnorm[:, 0] / norm[:, 0]
    return ly_s, dly


def pick_bandwidth(x: np.ndarray, y: np.ndarray, dy: np.ndarray) -> tuple[float, float]:
    """Choose the smoother width by leave-one-out cross-validation.

    The obvious rule — the ``h`` at which the smoothed curve reaches
    chi^2 ~ 1 — picks a width smaller than the spacing of the USANS points,
    which is interpolation rather than smoothing, and the derivative then
    follows the noise point by point. Cross-validation instead asks which
    ``h`` best predicts each point *from its neighbours*: still small on
    smooth data, honestly larger on noisy data.

    Returns:
        ``(h, chi2)`` — the chosen width and the resulting reduced chi-squared.
    """
    w = 1.0 / np.maximum(dy / y, 1e-3) ** 2
    ly = np.log(y)
    d = x[:, None] - x[None, :]
    spacing = float(np.median(np.diff(np.sort(x))))
    best: tuple[float, float] | None = None
    for h in np.geomspace(max(0.03, 1.5 * spacing), 1.2, 40):
        g = np.exp(-0.5 * (d / h) ** 2) * w[None, :]
        np.fill_diagonal(g, 0.0)
        denom = g.sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            pred = (g @ ly) / denom
        ok = np.isfinite(pred)
        if not ok.any():
            continue
        cv = float(np.sum(w[ok] * (ly[ok] - pred[ok]) ** 2) / np.sum(w[ok]))
        if best is None or cv < best[0]:
            best = (cv, float(h))
    if best is None:  # pragma: no cover — needs a degenerate single-point set
        raise DesmearError("could not choose a smoothing bandwidth")
    h = best[1]
    ly_s, _ = smooth_log(x, y, dy, h)
    chi2 = float(np.mean(((np.exp(ly_s) - y) / dy) ** 2))
    return h, chi2


def loglog_interp(q: np.ndarray, qp: np.ndarray, ip: np.ndarray) -> np.ndarray:
    """Power-law (log-log linear) interpolation. ``qp`` ascending, ``ip`` > 0."""
    return np.asarray(np.exp(np.interp(np.log(q), np.log(qp), np.log(ip))), dtype=float)


def power_law_fit(q: np.ndarray, i: np.ndarray, lo: float, hi: float) -> tuple[float, float]:
    """Fit ``ln I = m ln Q + c`` over ``[lo, hi]``.

    Raises:
        DesmearError: When fewer than four positive points fall in the window.
    """
    w = (q >= lo) & (q <= hi) & (i > 0) & np.isfinite(i)
    if w.sum() < 4:
        raise DesmearError(
            f"need >= 4 positive points in Q = [{lo:.3g}, {hi:.3g}] to fit a "
            f"power law; found {int(w.sum())}"
        )
    m, c = np.polyfit(np.log(q[w]), np.log(i[w]), 1)
    return float(m), float(c)


# ---------------------------------------------------------------------------
# The inversion
# ---------------------------------------------------------------------------


def _model_derivative(
    i_model: Callable[[np.ndarray], np.ndarray], q: np.ndarray, rel_step: float = 1e-3
) -> np.ndarray:
    """``dI/dQ`` of a smooth model curve, by central difference in ``ln Q``.

    Used past the top of the measured data, where the smoothed empirical
    derivative has nothing to stand on. Works for any positive callable —
    a power law, or a log-log interpolation of a real SANS curve.
    """
    q = np.asarray(q, dtype=float)
    lo = np.asarray(i_model(q * (1.0 - rel_step)), dtype=float)
    hi = np.asarray(i_model(q * (1.0 + rel_step)), dtype=float)
    mid = np.asarray(i_model(q), dtype=float)
    # d(lnI)/d(lnQ) over the symmetric step; the denominator is exactly
    # ln((1+e)/(1-e)), not 2e.
    span = float(np.log((1.0 + rel_step) / (1.0 - rel_step)))
    with np.errstate(invalid="ignore", divide="ignore"):
        out = mid * ((np.log(hi) - np.log(lo)) / span) / q
    return np.asarray(np.nan_to_num(out), dtype=float)


def abel_invert(
    q_obs: np.ndarray,
    i_obs: np.ndarray,
    di_obs: np.ndarray,
    i_high: Callable[[np.ndarray], np.ndarray],
    q_eval: np.ndarray,
    *,
    sigma_y: float = DEFAULT_SIGMA_Y,
) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Truncated Abel inversion, eq. 15, with the ``s`` substitution.

    Args:
        q_obs: Q of the slit-smeared observations, ascending.
        i_obs: Smeared intensity, strictly positive.
        di_obs: Uncertainty on ``i_obs``.
        i_high: The *unsmeared* intensity at high Q, used for the ``I(Q_m)``
            anchor. Must be valid up to ``sqrt(q_eval.max()^2 + sigma_y^2)``.
        q_eval: Where to report the desmeared curve.
        sigma_y: Slit half-width.

    Returns:
        ``(I, dI, h, chi2)``.
    """
    q_obs = np.asarray(q_obs, dtype=float)
    i_obs = np.asarray(i_obs, dtype=float)
    di_obs = np.asarray(di_obs, dtype=float)

    # Pad below the first point with a power law fitted to the first half
    # decade. The Gaussian smoother is truncated at the edge of the data,
    # which biases the derivative exactly where the Abel integral weights it
    # most for the lowest Q. On a Q^-3 benchmark the unpadded version
    # overshoots ~5x at Q = 1e-4 and is exact by 5e-4; padding removes that.
    lo_mask = q_obs <= q_obs[0] * 10**0.7
    if lo_mask.sum() >= 4:
        m, c = np.polyfit(np.log(q_obs[lo_mask]), np.log(i_obs[lo_mask]), 1)
        q_pad = np.logspace(np.log10(q_obs[0]) - 0.6, np.log10(q_obs[0]) - 0.03, 14)
        i_pad = np.exp(m * np.log(q_pad) + c)
        # The pad must carry the same *relative* error as the data it
        # continues. ``smooth_log`` weights by 1/(dI/I)^2, so padding quoted
        # at a fixed 10% against 2% data is downweighted 25x, the smoothing
        # window at the first point goes effectively one-sided, and the
        # derivative there is biased. On a Q^-4 benchmark that cost -35% at
        # the lowest Q — the single most valuable point of a USANS run —
        # against -6.7% once the weights match.
        pad_rel = float(np.median(di_obs[lo_mask] / i_obs[lo_mask]))
        if not np.isfinite(pad_rel) or pad_rel <= 0:
            pad_rel = 0.05
        q_all = np.concatenate([q_pad, q_obs])
        i_all = np.concatenate([i_pad, i_obs])
        d_all = np.concatenate([pad_rel * i_pad, di_obs])
    else:
        q_all, i_all, d_all = q_obs, i_obs, di_obs

    x = np.log(q_all)
    h, chi2 = pick_bandwidth(x, i_all, d_all)
    ly_s, dly = smooth_log(x, i_all, d_all, h)
    i_s = np.exp(ly_s)
    # dI/dQ = (I/Q) * dlnI/dlnQ
    di_dq = i_s / q_all * dly

    # The slit integral runs all the way to sigma_y, which is far above the
    # top of the data. ``np.interp`` *clamps* beyond its range, which would
    # hold dI/dQ constant out to sigma_y instead of letting it decay — and
    # since most of the integrand lives beyond the data, that error dominates
    # the result at the top of the measured range (it inflated a Q^-4
    # benchmark by >100% above Q ~ 1.5e-3). Past the data we therefore
    # differentiate the high-Q model itself, which is the only thing that
    # knows how the curve continues.
    q_top = float(q_all[-1])

    def dprime(qq: np.ndarray) -> np.ndarray:
        vals = np.interp(np.log(qq), x, di_dq)
        beyond = qq > q_top
        if beyond.any():
            vals = np.asarray(vals, dtype=float).copy()
            vals[beyond] = _model_derivative(i_high, qq[beyond])
        return np.asarray(vals, dtype=float)

    s = slit_nodes(sigma_y)
    q_eval = np.asarray(q_eval, dtype=float)
    out = np.empty_like(q_eval)
    for k, q in enumerate(q_eval):
        qp = np.sqrt(q**2 + s**2)
        integral = _trapezoid(dprime(qp) / qp, s)
        qm = np.sqrt(q**2 + sigma_y**2)
        out[k] = float(np.asarray(i_high(np.array([qm])))[0]) - (2 * sigma_y / np.pi) * integral

    # Uncertainty: eq. 23 in spirit. Propagate dI through the same linear
    # operator numerically, ignoring cross terms between observations.
    var = np.zeros_like(q_eval)
    for k, q in enumerate(q_eval):
        qp = np.sqrt(q**2 + s**2)
        xq = np.log(qp)
        d = xq[:, None] - x[None, :]
        gauss = np.exp(-0.5 * (d / h) ** 2)
        denom = gauss.sum(axis=1, keepdims=True)
        with np.errstate(invalid="ignore", divide="ignore"):
            g = (-d / h**2) * gauss / denom
        g = np.nan_to_num(g)
        sens = (np.interp(xq, x, i_s) / qp)[:, None] * g / i_all[None, :]
        a = _trapezoid(sens / qp[:, None], s, axis=0) * (2 * sigma_y / np.pi)
        var[k] = float(np.sum((a * d_all) ** 2))
    return out, np.sqrt(var), h, chi2


# ---------------------------------------------------------------------------
# High-Q side
# ---------------------------------------------------------------------------


def _extend_sans(
    q: np.ndarray, i: np.ndarray, fit_lo: float = 0.15, fit_hi: float = 0.4
) -> Callable[[np.ndarray], np.ndarray]:
    """Pinhole SANS extended to 1 A^-1 as a power law, for the ``I(Q_m)`` anchor."""
    try:
        m, c = power_law_fit(q, i, fit_lo, fit_hi)
        m = min(m, -2.0)  # never extend flatter than Q^-2
    except DesmearError:
        m, c = -4.0, float(np.log(i[-1]) + 4.0 * np.log(q[-1]))
    tail_q = np.logspace(np.log10(q[-1]) + 0.02, 0.0, 30)
    q_ext = np.concatenate([q, tail_q])
    i_ext = np.concatenate([i, np.exp(m * np.log(tail_q) + c)])

    def fn(qq: np.ndarray) -> np.ndarray:
        return loglog_interp(np.asarray(qq, dtype=float), q_ext, i_ext)

    return fn


def _extrapolated_high_q(
    q: np.ndarray, i: np.ndarray
) -> tuple[Callable[[np.ndarray], np.ndarray], float]:
    """Power-law high-Q side fitted to the top of the USANS itself.

    The USANS-only fallback, matching what NIST Igor/Irena does (Kline 2006):
    extrapolate the measured intensity up to the slit width so the integral
    kernel has something to integrate. It is an assumption, and
    :func:`desmear` labels the result accordingly.

    Returns:
        ``(callable, slope)``.
    """
    top = q.max()
    m, c = power_law_fit(q, i, top / 10.0, top)
    # A slit-smeared power law is one power shallower than the true one, so
    # the unsmeared high-Q side is steeper by one. Guard against a flat or
    # rising fit, which would put intensity *above* the data at high Q.
    slope = min(m - 1.0, -2.0)
    anchor = float(np.exp(m * np.log(top) + c))

    def fn(qq: np.ndarray) -> np.ndarray:
        qq = np.asarray(qq, dtype=float)
        return np.asarray(anchor * (qq / top) ** slope, dtype=float)

    return fn, slope


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def desmear(
    q: np.ndarray,
    intensity: np.ndarray,
    sigma: np.ndarray,
    *,
    sans: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None,
    sigma_y: float = DEFAULT_SIGMA_Y,
    n_eval: int = 0,
) -> DesmearResult:
    """Desmear one slit-smeared USANS curve.

    Args:
        q: USANS Q, ascending.
        intensity: Slit-smeared I(Q) as reduced (background subtracted).
        sigma: Uncertainty on ``intensity``.
        sans: Optional ``(q, I, dI)`` from a companion pinhole SANS
            measurement. When given, it supplies the high-Q side properly and
            the result is reported over the joined range.
        sigma_y: Slit half-width in A^-1.
        n_eval: Points in the output grid. ``0`` reports on the input Q values
            in ``usans-only`` mode, or a 200-point log grid with SANS.

    Returns:
        A :class:`DesmearResult`.

    Raises:
        DesmearError: When the curve has too few usable points, or is flat or
            rising so that no derivative worth inverting exists.
    """
    q = np.asarray(q, dtype=float)
    intensity = np.asarray(intensity, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    ok = np.isfinite(q) & np.isfinite(intensity) & (q > 0) & (intensity > 0)
    if sigma.size != q.size:
        sigma = np.full_like(q, np.nan)
    q, intensity = q[ok], intensity[ok]
    sigma = np.where(np.isfinite(sigma[ok]), sigma[ok], 0.05 * intensity)
    if q.size < 8:
        raise DesmearError(
            f"need >= 8 positive points to desmear; got {q.size}. "
            "Is this a background-subtracted USANS curve?"
        )
    order = np.argsort(q)
    q, intensity, sigma = q[order], intensity[order], sigma[order]
    sigma = np.maximum(sigma, MIN_REL_ERR * intensity)

    warnings: list[str] = []
    # Both papers make the same point: where the first derivative cannot be
    # estimated, desmearing is not meaningful. A flat or rising slit-smeared
    # curve has nothing to invert.
    top = q.max()
    try:
        slope_lo, _ = power_law_fit(q, intensity, q.min(), min(q.min() * 10, top))
    except DesmearError:
        slope_lo = float("nan")
    if np.isfinite(slope_lo) and slope_lo > -0.5:
        raise DesmearError(
            f"curve is flat or rising at low Q (slope {slope_lo:+.2f}); slit "
            "desmearing inverts the derivative and has nothing to work with"
        )

    if sans is not None:
        result = _desmear_with_sans(q, intensity, sigma, sans, sigma_y, n_eval, warnings)
    else:
        result = _desmear_usans_only(q, intensity, sigma, sigma_y, n_eval, warnings)
    return result


def _finish(
    q_eval: np.ndarray,
    i_out: np.ndarray,
    d_out: np.ndarray,
    *,
    q_in: np.ndarray,
    i_in: np.ndarray,
    mode: str,
    sigma_y: float,
    h: float,
    chi2: float,
    tail_slope: float,
    sans_scale: float,
    join_rms: float,
    warnings: list[str],
) -> DesmearResult:
    """Trim non-finite points, compute the low-Q gain, and package the result."""
    good = np.isfinite(i_out) & np.isfinite(d_out)
    if not good.any():
        raise DesmearError("inversion produced no finite points")
    if (~good).any():
        warnings.append(f"dropped {int((~good).sum())} non-finite point(s) from the result")
    q_eval, i_out, d_out = q_eval[good], i_out[good], d_out[good]
    negative = i_out <= 0
    if negative.any():
        warnings.append(
            f"{int(negative.sum())} of {i_out.size} desmeared points are <= 0 "
            "(they cannot be drawn on a log-log plot)"
        )
    gain = float(i_out[0] / np.interp(q_eval[0], q_in, i_in)) if i_out.size else 1.0
    return DesmearResult(
        q=q_eval,
        intensity=i_out,
        sigma=d_out,
        mode=mode,
        sigma_y=sigma_y,
        bandwidth=h,
        chi2=chi2,
        tail_slope=tail_slope,
        sans_scale=sans_scale,
        join_rms=join_rms,
        warnings=tuple(warnings),
        _gain=gain,
    )


def _desmear_usans_only(
    q: np.ndarray,
    i: np.ndarray,
    d: np.ndarray,
    sigma_y: float,
    n_eval: int,
    warnings: list[str],
) -> DesmearResult:
    """No SANS: extrapolate the high-Q side, and report only the measured range."""
    i_high, slope = _extrapolated_high_q(q, i)
    warnings.append(
        f"no SANS data: the high-Q side was extrapolated as Q^{slope:.2f} out to "
        f"sigma_y={sigma_y:g} A^-1. Trustworthy over the measured USANS range only "
        "(Huang 2026, Fig. 2)."
    )
    q_eval = q if n_eval <= 0 else np.geomspace(q.min(), q.max(), n_eval)
    i_out, d_out, h, chi2 = abel_invert(q, i, d, i_high, q_eval, sigma_y=sigma_y)
    return _finish(
        q_eval,
        i_out,
        d_out,
        q_in=q,
        i_in=i,
        mode="usans-only",
        sigma_y=sigma_y,
        h=h,
        chi2=chi2,
        tail_slope=slope,
        sans_scale=1.0,
        join_rms=float("nan"),
        warnings=warnings,
    )


def _desmear_with_sans(
    q: np.ndarray,
    i: np.ndarray,
    d: np.ndarray,
    sans: tuple[np.ndarray, np.ndarray, np.ndarray],
    sigma_y: float,
    n_eval: int,
    warnings: list[str],
) -> DesmearResult:
    """Six-step recipe of Huang et al. §3.2 with a companion SANS curve."""
    qe = np.asarray(sans[0], dtype=float)
    ie = np.asarray(sans[1], dtype=float)
    de = np.asarray(sans[2], dtype=float)
    ok = np.isfinite(qe) & np.isfinite(ie) & (qe > 0) & (ie > 0)
    qe, ie = qe[ok], ie[ok]
    de = np.where(np.isfinite(de[ok]), de[ok], 0.05 * ie) if de.size == ok.size else 0.05 * ie
    if qe.size < 8:
        raise DesmearError(f"SANS curve has only {qe.size} usable points")
    order = np.argsort(qe)
    qe, ie, de = qe[order], ie[order], de[order]

    # 1-2. Extend the SANS as a power law, then smear it onto the slit basis
    #      so both halves sit on the same footing before they are joined.
    i_high = _extend_sans(qe, ie)
    ie_sm = smear(i_high, qe, sigma_y=sigma_y)
    de_sm = ie_sm * (de / ie)

    # Scale the USANS onto the smeared SANS: one power law through both, with
    # a free offset for the USANS half.
    wu, we = q >= 3e-4, qe <= 1.2e-2
    if wu.sum() >= 4 and we.sum() >= 4:
        qq = np.concatenate([q[wu], qe[we]])
        ii = np.concatenate([i[wu], ie_sm[we]])
        flag = np.concatenate([np.ones(int(wu.sum())), np.zeros(int(we.sum()))])
        amat = np.column_stack([np.log10(qq), np.ones_like(qq), flag])
        coef, *_ = np.linalg.lstsq(amat, np.log10(ii), rcond=None)
        k_sm = float(10 ** (-coef[2]))
        join_rms = float((np.log10(ii) - amat @ coef).std())
    else:
        k_sm, join_rms = 1.0, float("nan")
        warnings.append("USANS and SANS do not overlap enough to scale-match; using k = 1")
    if np.isfinite(join_rms) and join_rms > 0.25:
        warnings.append(
            f"USANS/SANS join scatters {join_rms:.2f} dex about one power law — "
            "check that these two curves are the same sample"
        )

    # 3. Concatenate, interpolating across the instrument gap.
    q_gap = np.logspace(np.log10(q[-1]) + 0.05, np.log10(qe[0]) - 0.05, N_GAP_POINTS)
    i_gap = loglog_interp(q_gap, np.array([q[-1], qe[0]]), np.array([i[-1] * k_sm, ie_sm[0]]))
    q_obs = np.concatenate([q * 1.0, q_gap, qe])
    i_obs = np.concatenate([i * k_sm, i_gap, ie_sm])
    d_obs = np.concatenate([d * k_sm, GAP_REL_ERR * i_gap, de_sm])
    order = np.argsort(q_obs)
    q_obs, i_obs, d_obs = q_obs[order], i_obs[order], d_obs[order]
    keep = np.isfinite(q_obs) & np.isfinite(i_obs) & np.isfinite(d_obs) & (i_obs > 0)
    q_obs, i_obs, d_obs = q_obs[keep], i_obs[keep], d_obs[keep]
    d_obs = np.maximum(d_obs, MIN_REL_ERR * i_obs)

    top = min(float(qe.max()), 0.46)
    n = n_eval if n_eval > 0 else 200
    q_eval = np.geomspace(q.min(), top, n)
    i_out, d_out, h, chi2 = abel_invert(q_obs, i_obs, d_obs, i_high, q_eval, sigma_y=sigma_y)
    return _finish(
        q_eval,
        i_out,
        d_out,
        q_in=q,
        i_in=i * k_sm,
        mode="with-sans",
        sigma_y=sigma_y,
        h=h,
        chi2=chi2,
        tail_slope=float("nan"),
        sans_scale=k_sm,
        join_rms=join_rms,
        warnings=warnings,
    )
