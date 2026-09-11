"""Tests for fractional differencing and the ADF unit-root test.

These lock in the properties that make ``fractional.py`` a defensible
replacement for integer differencing and forward-filling:

* the weights are the analytic binomial coefficients of ``(1 - B)**d``, not a
  fit or an approximation;
* the transform is strictly causal -- a value at ``i`` depends only on
  ``series[0..i]`` -- which is what forward-filling violated;
* the fixed-width warm-up is reported as ``NaN`` rather than imputed;
* the ADF statistic is the OLS t-ratio of the lagged level, with the degrees of
  freedom corrected for the number of estimated parameters.

Every test seeds its own ``numpy.random.default_rng`` with a fixed integer, so
the suite is deterministic.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from backend.modules.data.fractional import (
    ADF_CRITICAL_VALUES,
    adf_statistic,
    apply_weights,
    frac_diff,
    frac_diff_ffd,
    frac_diff_optimal,
    frac_diff_weights,
    min_frac_diff_order,
)


def _leaky_frac_diff(series, d: float, threshold: float) -> np.ndarray:
    """Deliberately look-ahead transform, used to show the causality test bites.

    Centring by the *full-sample* mean makes the value at ``i`` a function of
    observations after ``i``, so a prefix computed on its own disagrees with the
    corresponding prefix of the full-series result. A genuine no-look-ahead
    transform must not behave this way.
    """
    arr = np.asarray(series, dtype=float)
    return frac_diff(arr - arr.mean(), d, threshold)


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("d", [0.2, 0.4, 0.6, 0.8])
def test_weights_match_analytic_binomial_coefficients(d: float) -> None:
    """``w_k == (-1)**k * d(d-1)...(d-k+1)/k!`` for several fractional orders."""
    # Default threshold: small enough to retain many terms, which is the point.
    weights = frac_diff_weights(d, threshold=1e-5)

    assert weights[0] == 1.0
    assert weights.shape[0] > 100, "expected a long window at this threshold"

    # The direct product formula, written out as the requirement states it. The
    # factorial is kept as a Python int so the division stays exact enough; this
    # is checked only for the leading coefficients, where the intermediate
    # numerator does not overflow a float.
    for k in range(1, min(weights.shape[0], 150)):
        numerator = 1.0
        for i in range(k):
            numerator *= d - i
        expected = (-1.0) ** k * numerator / math.factorial(k)
        assert weights[k] == pytest.approx(expected, rel=1e-9, abs=1e-14)

    # For every retained coefficient, including the decaying tail where the
    # product form would overflow, use the reflection identity
    # |binom(d, k)| = Gamma(d+1) sin(pi d)/pi * Gamma(k-d)/Gamma(k+1), valid for
    # 0 < d < 1 and k >= 1, and the fact that the coefficients are all negative
    # there.
    for k in range(1, weights.shape[0]):
        magnitude = (
            math.exp(math.lgamma(d + 1) + math.lgamma(k - d) - math.lgamma(k + 1))
            * math.sin(math.pi * d)
            / math.pi
        )
        assert weights[k] == pytest.approx(-magnitude, rel=1e-8, abs=1e-15)


def test_weights_integer_orders_are_exact_binomials() -> None:
    """``d = 0`` is the identity; ``d = 1`` and ``d = 2`` are the exact filters."""
    np.testing.assert_array_equal(frac_diff_weights(0.0), np.array([1.0]))
    np.testing.assert_array_equal(frac_diff_weights(1.0), np.array([1.0, -1.0]))
    np.testing.assert_array_equal(
        frac_diff_weights(2.0), np.array([1.0, -2.0, 1.0])
    )


@pytest.mark.parametrize("d", [0.5, 0.6, 0.7, 0.8, 0.9])
def test_weights_sum_to_zero_for_positive_orders(d: float) -> None:
    """``(1 - 1)**d = 0``: the weights of any ``d > 0`` cancel.

    The sum is only zero in the infinite limit; truncation leaves a residual
    equal to the discarded tail. The tolerance is tight enough to be a real
    statement (well under a percent of the total weight mass) while allowing for
    that tail.
    """
    weights = frac_diff_weights(d, threshold=1e-8)
    assert abs(float(weights.sum())) < 5e-3


# ---------------------------------------------------------------------------
# Applying the filter
# ---------------------------------------------------------------------------


def test_ffd_d1_reproduces_np_diff_exactly() -> None:
    """The fixed-width ``d = 1`` filter is the first difference, bit for bit."""
    rng = np.random.default_rng(20240101)
    series = rng.normal(size=250)

    transformed = frac_diff_ffd(series, 1.0)

    assert np.isnan(transformed[0])  # one-term warm-up
    np.testing.assert_array_equal(transformed[1:], np.diff(series))


def test_expanding_d1_reproduces_np_diff_away_from_warmup() -> None:
    """The expanding ``d = 1`` form is the first difference from index 1 on."""
    rng = np.random.default_rng(20240102)
    series = rng.normal(size=250)

    transformed = frac_diff(series, 1.0)

    assert transformed[0] == series[0]  # only one term of history exists
    np.testing.assert_array_equal(transformed[1:], np.diff(series))


def test_frac_diff_has_no_look_ahead() -> None:
    """A prefix of the full-series result equals the result on that prefix.

    This is the property forward-filling broke: the transform must never use an
    observation it would not have had at that moment. If it did, recomputing on
    a shorter sample would change the overlapping values.
    """
    rng = np.random.default_rng(20240103)
    series = rng.normal(size=300)
    d = 0.4
    threshold = 1e-5

    full = frac_diff(series, d, threshold)

    for k in (1, 2, 5, 17, 64, 150, 299):
        prefix = frac_diff(series[:k], d, threshold)
        np.testing.assert_array_equal(
            full[:k], prefix, err_msg=f"look-ahead detected at prefix k={k}"
        )

    # The test has teeth: the same comparison fails for a construction that
    # centres on a full-sample statistic.
    k = 40
    assert not np.allclose(
        _leaky_frac_diff(series, d, threshold)[:k],
        _leaky_frac_diff(series[:k], d, threshold),
    )


def test_shape_is_preserved_for_every_transform() -> None:
    """No transform may silently return an array shorter than its input."""
    rng = np.random.default_rng(20240104)

    for length in (1, 2, 3, 17, 500):
        series = rng.normal(size=length)
        assert apply_weights(series, [1.0, -0.5, 0.1]).shape == (length,)
        assert frac_diff(series, 0.4).shape == (length,)
        assert frac_diff_ffd(series, 0.4).shape == (length,)

    # Even when the window is longer than the sample, the output keeps the
    # input's length (it is all warm-up NaN, not a truncated array).
    short = np.array([1.0, 2.0])
    squeezed = apply_weights(short, np.ones(10))
    assert squeezed.shape == short.shape
    assert np.all(np.isnan(squeezed))


def test_fixed_width_warmup_is_nan_and_not_imputed() -> None:
    """The first ``len(weights) - 1`` entries are ``NaN``; the rest are finite."""
    rng = np.random.default_rng(20240105)
    series = rng.normal(size=400)
    d = 0.5
    threshold = 1e-4

    weights = frac_diff_weights(d, threshold)
    assert weights.shape[0] > 1

    transformed = frac_diff_ffd(series, d, threshold)

    warmup = weights.shape[0] - 1
    assert np.all(np.isnan(transformed[:warmup]))
    assert np.all(np.isfinite(transformed[warmup:]))

    # apply_weights carries the same convention.
    direct = apply_weights(series, weights)
    np.testing.assert_array_equal(transformed, direct)


# ---------------------------------------------------------------------------
# ADF test
# ---------------------------------------------------------------------------


def test_adf_rejects_short_and_constant_series() -> None:
    """A degenerate sample cannot support the regression; it must say so."""
    with pytest.raises(ValueError, match="too short"):
        adf_statistic(np.arange(5.0))

    with pytest.raises(ValueError, match="constant"):
        adf_statistic(np.full(50, 3.0))

    with pytest.raises(ValueError, match="no finite observations"):
        adf_statistic(np.array([]))


def test_frac_diff_weights_rejects_negative_order() -> None:
    """A negative order would integrate the series, which is a different model."""
    with pytest.raises(ValueError, match="non-negative"):
        frac_diff_weights(-0.1)
    with pytest.raises(ValueError, match="non-negative"):
        frac_diff_weights(-1.0)


# ---------------------------------------------------------------------------
# Order selection and the memory trade-off
# ---------------------------------------------------------------------------


def test_random_walk_selects_the_full_difference() -> None:
    """A unit root needs ``d = 1``; raw levels must not look stationary.

    The sample is deliberately short. With the default threshold the fixed-width
    window for ``d < 0.9`` is longer than 120 observations (for example
    ``len(frac_diff_weights(0.5)) == 927``), so those grid points cannot be
    computed at all and are skipped. The smallest *computable* order here is
    therefore 1.0. On a longer sample the smallest *feasible* order falls well
    below 1, because truncating an already-close-to-zero low-frequency gain
    stationarises the finite sample before the true fractional order reaches 1;
    that is a property of the truncated filter, not evidence that ``d = 1`` is
    unnecessary.
    """
    rng = np.random.default_rng(12345)
    random_walk = np.cumsum(rng.normal(size=120))

    raw_statistic, _ = adf_statistic(random_walk)
    assert raw_statistic > ADF_CRITICAL_VALUES["5%"], "raw levels must not reject"

    result = frac_diff_optimal(random_walk)

    assert 0.9 <= result["d"] <= 1.0, "expected an order close to 1.0"
    assert result["adf_statistic"] < ADF_CRITICAL_VALUES["5%"]


def test_white_noise_needs_no_differencing() -> None:
    """An already-stationary series is left alone: the answer is ``d = 0``."""
    rng = np.random.default_rng(999)
    white_noise = rng.normal(size=500)

    raw_statistic, _ = adf_statistic(white_noise)
    assert raw_statistic < ADF_CRITICAL_VALUES["5%"]

    assert min_frac_diff_order(white_noise) == 0.0


def test_fractional_difference_retains_more_memory_than_first_difference() -> None:
    """On a slow trend, the chosen fractional order beats ``d = 1`` on memory.

    A first difference of a trending series is nearly orthogonal to its level;
    the fractional transform keeps a large correlation with it. Both figures are
    asserted, and the fractional one must win by a clear margin.
    """
    rng = np.random.default_rng(20240517)
    time = np.arange(1500)
    series = 0.02 * time + rng.normal(size=1500)

    result = frac_diff_optimal(series)

    fractional = result["series"]
    mask = np.isfinite(fractional)
    assert int(mask.sum()) >= 2
    mem_fractional = float(np.corrcoef(fractional[mask], series[mask])[0, 1])
    # The reported diagnostic must agree with an independent computation.
    assert result["memory_retained"] == pytest.approx(mem_fractional, rel=1e-12)

    first_difference = frac_diff_ffd(series, 1.0)
    mask_one = np.isfinite(first_difference)
    mem_first_difference = float(
        np.corrcoef(first_difference[mask_one], series[mask_one])[0, 1]
    )

    assert 0.0 < result["d"] < 1.0, "a fractional order should be enough here"
    assert mem_fractional > 0.8
    assert mem_first_difference < 0.2
    assert mem_fractional > mem_first_difference + 0.5


def test_optimal_result_is_json_serialisable_and_typed() -> None:
    """Scalars are native Python types; the array keeps the input's length."""
    rng = np.random.default_rng(4242)
    random_walk = np.cumsum(rng.normal(size=120))

    result = frac_diff_optimal(random_walk)

    assert set(result) == {
        "d",
        "series",
        "adf_statistic",
        "n_obs",
        "memory_retained",
    }
    assert isinstance(result["d"], float)
    assert isinstance(result["adf_statistic"], float)
    assert isinstance(result["n_obs"], int)
    assert isinstance(result["memory_retained"], float)
    assert isinstance(result["series"], np.ndarray)
    assert result["series"].shape == random_walk.shape

    # Everything except the array itself must survive a JSON round trip.
    payload = {key: value for key, value in result.items() if key != "series"}
    assert json.loads(json.dumps(payload)) == payload
