"""Fractional differencing and the ADF test -- stationary series that keep memory.

Why this module exists
----------------------

Two shortcuts were used previously to make macro-financial levels stationary,
and both destroyed information the model needed.

1. **Integer differencing** (``y_t - y_{t-1}``) removes the unit root but also
   removes *everything* that is slow-moving. When ``d = 1`` the binomial filter
   has two terms and its transfer function is exactly zero at frequency zero,
   so the level -- the part of the series that carries the trend and the
   long-memory structure -- is annihilated. A regression on first differences
   can no longer see how far a series is from its long-run path, only how fast
   it moved last period.

2. **Forward-filling** (carrying the last observation forward across a gap) is
   worse than lossy: it copies ``y_{t-1}`` into ``y_t``, which means the value
   at ``t`` is a function of the *past*, while any statistic computed afterwards
   treats it as an observation at ``t``. It is a look-ahead construct wearing
   the costume of an imputation, and it manufactures serial correlation that is
   an artefact of the fill, not of the data.

López de Prado's alternative is to difference *fractionally*. The operator
``(1 - B)**d`` with a non-integer ``d`` in ``(0, 1)`` has a transfer function
that decays towards zero at frequency zero but does not vanish there abruptly;
choosing ``d`` is a dial between "too much memory, not stationary" and "no
memory, stationary". The aim is the smallest ``d`` that makes the series pass a
unit-root test, so that as much memory as possible survives.

The weights
-----------

Expanding ``(1 - B)**d`` binomially gives an infinite filter::

    (1 - B)**d = sum_{k >= 0} w_k B**k,
    w_0 = 1,
    w_k = w_{k-1} * (k - 1 - d) / k          (equivalently -w_{k-1} (d-k+1)/k)

For positive non-integer ``d`` the ``w_k`` are all of one sign, decay like
``k**(-d-1)``, and sum to exactly zero -- that last identity, ``(1-1)**d = 0``,
is what makes the filter blind to constants. The infinite sum cannot be applied
to a finite sample, so it is truncated at the first ``k`` whose weight is below
``threshold`` in absolute value. **The threshold is therefore what fixes the
window width.** A smaller threshold keeps more terms, which retains more of the
low-frequency memory and lengthens the warm-up region that must be discarded; a
larger threshold shortens the window at the cost of distorting the lowest
frequencies. There is no "correct" threshold, only a stated one.

Two ways to apply the filter
----------------------------

``frac_diff_ffd`` uses the truncated weights at a *fixed* width: every output
after the warm-up is a dot product of the same ``len(weights)`` terms. This is
the form used to build model features, because the window does not grow.

``frac_diff`` is the expanding-window form: at index ``i`` it uses at most
``i + 1`` terms, i.e. all the history that exists at that point. It is the
strict no-look-ahead statement of the same transform, and it is what the tests
check a fixed-width implementation against. Positions where the fixed window
does not yet fit are returned as ``NaN`` -- never imputed. A ``NaN`` that a
downstream model has to handle is honest; a fabricated number is not.

The unit-root test
------------------

``adf_statistic`` regresses ``dy_t`` on a constant, the lagged level
``y_{t-1}`` and ``p`` lagged differences, and reports the t-ratio of the lagged
level coefficient::

    dy_t = a + rho * y_{t-1} + sum_{i=1..p} b_i dy_{t-i} + e_t

Under the unit-root null ``rho = 0``. The critical values in
``ADF_CRITICAL_VALUES`` are **asymptotic MacKinnon values for the
constant-only case, used here as an approximation for finite samples**. They are
not exact critical values: the true small-sample distribution depends on the
sample size and the lag order, so the test is indicative rather than a
calibrated decision rule. That matters for ``min_frac_diff_order``, which scans
a grid and will therefore occasionally reject on a grid point by chance; the
selected order should be read as a starting point, not a p-value.

The honest caveat
-----------------

Because the filter is truncated, the retained coefficients do not sum exactly to
zero. For small ``d`` with a long window the residual low-frequency gain is
negligible, but for a *short* sample the opposite happens: the window for small
``d`` does not fit in the sample at all. ``min_frac_diff_order`` skips such
infeasible grid points and reports ``1.0`` when nothing on the grid rejects.
Consequently the selected order is sample-size dependent, and on a modest sample
the smallest *computable* order can be close to 1 even though the smallest
*present* order would be smaller. The functions say what they did; they do not
pretend the answer is sample-free.
"""

from __future__ import annotations

import math
from typing import Dict, Optional, Sequence, Tuple, Union

import numpy as np

__all__ = [
    "frac_diff_weights",
    "apply_weights",
    "frac_diff",
    "frac_diff_ffd",
    "adf_statistic",
    "ADF_CRITICAL_VALUES",
    "min_frac_diff_order",
    "frac_diff_optimal",
]

ArrayLike = Union[Sequence[float], np.ndarray]

#: Asymptotic MacKinnon critical values for the ADF test with a constant and no
#: time trend. These are *asymptotic* values used as an approximation for finite
#: samples: the finite-sample distribution depends on the sample size and lag
#: order, so a comparison against them is indicative, not an exact test.
#: They are reproduced here rather than computed so the module stays
#: dependency-free beyond numpy.
ADF_CRITICAL_VALUES: Dict[str, float] = {
    "1%": -3.43,
    "5%": -2.86,
    "10%": -2.57,
}

#: Refuse to build absurdly long windows rather than exhaust memory silently.
_MAX_WEIGHT_TERMS = 5_000_000

#: Minimum usable sample for the ADF regression. Below this the constant, the
#: lagged level and even one lag leave no residual degrees of freedom.
_MIN_ADF_OBSERVATIONS = 10


def _as_1d(series: ArrayLike, name: str = "series") -> np.ndarray:
    """Coerce an input to a finite-checked 1-D float array (shape only)."""
    arr = np.asarray(series, dtype=float)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional, got shape {arr.shape}")
    return arr


def frac_diff_weights(d: float, threshold: float = 1e-5) -> np.ndarray:
    """Binomial coefficients of ``(1 - B)**d``, truncated by ``threshold``.

    The recurrence is ``w_0 = 1`` and, for ``k >= 1``,
    ``w_k = -w_{k-1} * (d - k + 1) / k``. Coefficients are accumulated until the
    first one whose absolute value is below ``threshold``; that term is *not*
    included. The length of the returned array is therefore the window width,
    and the threshold is the parameter that sets it: a smaller threshold retains
    more memory and lengthens the warm-up that ``apply_weights`` marks ``NaN``.

    Args:
        d: Differencing order. Must be finite and non-negative. ``d = 0``
            returns ``array([1.0])`` -- the identity filter.
        threshold: Stop once ``abs(w_k) < threshold``. Must be positive.

    Returns:
        A 1-D float array of weights starting at ``1.0``.

    Raises:
        ValueError: If ``d`` is negative or non-finite, if it is not a real
            number, or if ``threshold`` is not positive, or if the window would
            exceed ``_MAX_WEIGHT_TERMS`` coefficients.
    """
    order = float(d)
    if not math.isfinite(order):
        raise ValueError(f"d must be finite, got {d!r}")
    if order < 0:
        raise ValueError(
            f"d must be non-negative for fractional differencing, got {d!r}"
        )

    cut = float(threshold)
    if not math.isfinite(cut) or cut <= 0:
        raise ValueError(f"threshold must be a positive finite number, got {threshold!r}")

    if order == 0.0:
        return np.array([1.0], dtype=float)

    weights = [1.0]
    k = 1
    while True:
        weight = -weights[-1] * (order - k + 1) / k
        if abs(weight) < cut:
            break
        weights.append(weight)
        k += 1
        if k > _MAX_WEIGHT_TERMS:
            raise ValueError(
                f"threshold {threshold!r} is too small for d={d!r}: more than "
                f"{_MAX_WEIGHT_TERMS} coefficients would be needed"
            )

    return np.asarray(weights, dtype=float)


def apply_weights(series: ArrayLike, weights: ArrayLike) -> np.ndarray:
    """Fixed-width convolution of ``series`` with ``weights``.

    For index ``i`` the output is ``sum_j weights[j] * series[i - j]``. The first
    ``len(weights) - 1`` positions do not have enough history and are returned as
    ``NaN`` -- the warm-up region. Nothing is imputed: a value that is not
    supported by data is reported as missing. If ``weights`` is longer than the
    series, every position is warm-up and the whole result is ``NaN``.

    Args:
        series: The input series.
        weights: Filter coefficients, e.g. from :func:`frac_diff_weights`.

    Returns:
        A float array with the same length as ``series``.

    Raises:
        ValueError: If ``weights`` is empty.
    """
    arr = _as_1d(series)
    coeffs = _as_1d(weights, name="weights")
    if coeffs.shape[0] == 0:
        raise ValueError("weights must contain at least one coefficient")

    n = arr.shape[0]
    m = coeffs.shape[0]
    out = np.zeros(n, dtype=float)

    # Only coefficients that can reach the sample contribute; the rest are
    # absorbed by the warm-up mask below.
    for j in range(min(m, n)):
        out[j:] += coeffs[j] * arr[: n - j]

    if m > 1:
        out[: m - 1] = np.nan
    return out


def frac_diff(series: ArrayLike, d: float, threshold: float = 1e-5) -> np.ndarray:
    """Expanding-window fractional differencing -- the no-look-ahead form.

    At index ``i`` the value uses all history available up to ``i``, i.e. the
    truncated weights are cut to at most ``i + 1`` terms. Unlike
    :func:`frac_diff_ffd` this produces no warm-up ``NaN`` (at ``i = 0`` it
    returns ``series[0]``), because there is no fixed window that has to fit.
    The cost is that the early, short-window values are partial filters and
    should be treated with care.

    This is the form to verify against: ``frac_diff(series)[:k]`` must equal
    ``frac_diff(series[:k])`` exactly, because a value at ``i`` may depend only
    on ``series[0..i]``.

    Args:
        series: The input series.
        d: Differencing order, non-negative.
        threshold: Weight truncation threshold; see :func:`frac_diff_weights`.

    Returns:
        A float array with the same length as ``series``.
    """
    arr = _as_1d(series)
    n = arr.shape[0]
    coeffs = frac_diff_weights(d, threshold)
    out = np.full(n, np.nan, dtype=float)

    for i in range(n):
        m = min(coeffs.shape[0], i + 1)
        out[i] = float(np.dot(coeffs[:m], arr[i - m + 1 : i + 1][::-1]))

    return out


def frac_diff_ffd(series: ArrayLike, d: float, threshold: float = 1e-5) -> np.ndarray:
    """Fixed-width fractional differencing (FFD).

    Applies :func:`apply_weights` with the truncated coefficients from
    :func:`frac_diff_weights`. This is the production form used to build model
    features: the window width is constant, so the transform is a fixed linear
    filter once the warm-up has passed. The warm-up region is ``NaN``.

    Args:
        series: The input series.
        d: Differencing order, non-negative.
        threshold: Weight truncation threshold; see :func:`frac_diff_weights`.

    Returns:
        A float array with the same length as ``series``.
    """
    return apply_weights(series, frac_diff_weights(d, threshold))


def _trim_leading_nonfinite(arr: np.ndarray) -> np.ndarray:
    """Drop the leading ``NaN`` warm-up, then insist the rest is finite."""
    finite = np.isfinite(arr)
    if not finite.any():
        raise ValueError("series contains no finite observations")
    first = int(np.argmax(finite))
    trimmed = arr[first:]
    if not np.all(np.isfinite(trimmed)):
        raise ValueError(
            "series contains non-finite values after the leading warm-up region; "
            "the ADF regression needs a contiguous sample"
        )
    return trimmed


def adf_statistic(
    series: ArrayLike, max_lag: Optional[int] = None
) -> Tuple[float, int]:
    """Augmented Dickey-Fuller t-statistic for a unit root, with drift only.

    The regression is

        dy_t = a + rho * y_{t-1} + sum_{i=1..p} b_i dy_{t-i} + e_t

    estimated by ordinary least squares with ``numpy.linalg.lstsq``. The returned
    statistic is the t-ratio ``rho_hat / se(rho_hat)``, where the standard error
    uses the residual variance with ``n_obs - n_params`` degrees of freedom. A
    leading run of ``NaN`` (the fractional-difference warm-up) is dropped before
    estimation; interior non-finite values are an error.

    The null is a unit root, so a *more negative* statistic is evidence against
    the null. Compare it against :data:`ADF_CRITICAL_VALUES` -- asymptotic values
    used as a finite-sample approximation, not exact critical values.

    Args:
        series: The series to test.
        max_lag: Number of lagged differences ``p``. If ``None`` the Schwert
            rule ``p = floor(4 * (T/100)**0.25)`` is used, where ``T`` is the
            usable sample length. In both cases ``p`` is capped so the
            regression keeps at least one residual degree of freedom.

    Returns:
        ``(statistic, lag_used)`` as Python ``float`` and ``int``.

    Raises:
        ValueError: If the series has no finite observations, contains non-finite
            values after the warm-up, is too short, is constant, has non-positive
            residual variance, or leaves no residual degrees of freedom.
    """
    arr = _as_1d(series)
    arr = _trim_leading_nonfinite(arr)
    n = arr.shape[0]

    if n < _MIN_ADF_OBSERVATIONS:
        raise ValueError(
            f"series is too short for the ADF test: need at least "
            f"{_MIN_ADF_OBSERVATIONS} finite observations, got {n}"
        )
    if float(np.ptp(arr)) == 0.0:
        raise ValueError(
            "series is constant; the ADF regression is not identified and the "
            "unit-root null is meaningless"
        )

    if max_lag is None:
        lag = int(math.floor(4.0 * (n / 100.0) ** 0.25))
    else:
        lag = int(max_lag)
        if lag < 0:
            raise ValueError(f"max_lag must be non-negative, got {max_lag!r}")

    # Need t = p+1 .. T-1, i.e. T-1-p rows, and n_params = p+2 columns.
    lag = min(lag, max(0, (n - 4) // 2))

    difference = np.diff(arr)
    t_index = np.arange(lag + 1, n)
    n_obs = int(t_index.shape[0])

    dependent = difference[t_index - 1]
    columns = [np.ones(n_obs), arr[t_index - 1]]
    for i in range(1, lag + 1):
        columns.append(difference[t_index - 1 - i])
    design = np.column_stack(columns)

    n_params = int(design.shape[1])
    dof = n_obs - n_params
    if dof < 1:
        raise ValueError(
            f"series is too short for the ADF test with {lag} lag(s): "
            f"{n_obs} observations and {n_params} parameters leave no residual "
            f"degrees of freedom"
        )

    beta, _, _, _ = np.linalg.lstsq(design, dependent, rcond=None)
    residual = dependent - design @ beta
    sigma2 = float(residual @ residual) / dof
    if not sigma2 > 0.0:
        raise ValueError(
            "ADF regression has zero residual variance; the series is perfectly "
            "deterministic and the t-ratio is undefined"
        )

    # pinv is used rather than inv so a rank-deficient design (for example a
    # pure linear trend, whose differences are collinear with the constant)
    # yields a defined standard error instead of raising.
    xtx_inverse = np.linalg.pinv(design.T @ design)
    standard_error = math.sqrt(sigma2 * float(xtx_inverse[1, 1]))
    if standard_error <= 0.0 or not math.isfinite(standard_error):
        raise ValueError(
            "ADF regression produced a degenerate standard error for the "
            "lagged-level coefficient"
        )

    return float(beta[1] / standard_error), int(lag)


def _validate_series_for_order_search(arr: np.ndarray) -> np.ndarray:
    """Reject degenerate input early, before the grid is scanned."""
    trimmed = _trim_leading_nonfinite(arr)
    if trimmed.shape[0] < _MIN_ADF_OBSERVATIONS:
        raise ValueError(
            f"series is too short for order selection: need at least "
            f"{_MIN_ADF_OBSERVATIONS} finite observations, got {trimmed.shape[0]}"
        )
    if float(np.ptp(trimmed)) == 0.0:
        raise ValueError("series is constant; no differencing order is meaningful")
    return trimmed


def min_frac_diff_order(
    series: ArrayLike,
    d_grid: Optional[Sequence[float]] = None,
    threshold: float = 1e-5,
    significance: str = "5%",
) -> float:
    """Smallest grid order whose fractional difference passes the ADF test.

    Every candidate ``d`` is applied with :func:`frac_diff_ffd` and tested with
    :func:`adf_statistic`; the first (smallest) ``d`` whose statistic falls below
    the chosen critical value is returned. If the raw series already rejects at
    ``d = 0`` the answer is ``0.0`` -- no differencing is needed. If nothing on
    the grid rejects, ``1.0`` is returned as the conservative fallback (plain
    first differencing).

    Grid points whose filter window is longer than the sample, or whose
    differenced series is otherwise untestable, are skipped; they carry no
    information about stationarity. The critical values are the *asymptotic*
    ones in :data:`ADF_CRITICAL_VALUES`, so a rejection is indicative rather than
    exact, and scanning several grid points gives more than one chance to reject.
    Treat the result as a sensible starting order, not as a test decision.

    Args:
        series: The series to make stationary.
        d_grid: Candidate orders. Defaults to ``np.arange(0, 1.05, 0.05)``, which
            includes ``1.0``. Values are sorted and de-duplicated.
        threshold: Weight truncation threshold; see :func:`frac_diff_weights`.
        significance: Key into :data:`ADF_CRITICAL_VALUES`, e.g. ``"5%"``.

    Returns:
        The selected order as a Python ``float``.

    Raises:
        ValueError: If ``significance`` is unknown, or the input series is
            constant or too short to test.
    """
    if significance not in ADF_CRITICAL_VALUES:
        raise ValueError(
            f"unknown significance {significance!r}; expected one of "
            f"{sorted(ADF_CRITICAL_VALUES)}"
        )
    critical = ADF_CRITICAL_VALUES[significance]

    arr = _validate_series_for_order_search(_as_1d(series))

    if d_grid is None:
        grid = np.arange(0.0, 1.05, 0.05)
    else:
        grid = np.asarray(d_grid, dtype=float).reshape(-1)
        grid = np.unique(grid[np.isfinite(grid)])
        if grid.size == 0:
            raise ValueError("d_grid must contain at least one finite value")
        grid = np.sort(grid)

    for candidate in grid:
        d = float(candidate)
        if d < 0:
            raise ValueError(f"d_grid values must be non-negative, got {d!r}")
        transformed = frac_diff_ffd(arr, d, threshold)
        try:
            statistic, _ = adf_statistic(transformed)
        except ValueError:
            # Either the window does not fit the sample or the difference is
            # degenerate; neither is evidence that the series is stationary.
            continue
        if statistic < critical:
            return d

    return 1.0


def _pearson_overlap(original: np.ndarray, transformed: np.ndarray) -> float:
    """Pearson correlation over the common finite region, ``0.0`` if undefined."""
    mask = np.isfinite(original) & np.isfinite(transformed)
    if int(mask.sum()) < 2:
        return 0.0
    left = transformed[mask]
    right = original[mask]
    if float(np.std(left)) == 0.0 or float(np.std(right)) == 0.0:
        return 0.0
    corr = float(np.corrcoef(left, right)[0, 1])
    return corr if math.isfinite(corr) else 0.0


def frac_diff_optimal(
    series: ArrayLike,
    d_grid: Optional[Sequence[float]] = None,
    threshold: float = 1e-5,
) -> Dict[str, object]:
    """Fractionally difference a series at its smallest stationary order.

    A convenience wrapper: pick ``d`` with :func:`min_frac_diff_order`, apply it
    with :func:`frac_diff_ffd`, and report the result. ``memory_retained`` is the
    Pearson correlation between the differenced series and the original over
    their overlapping finite region -- a simple, interpretable proxy for how much
    of the level information survived (``1.0`` means none was lost, ``0.0`` means
    the correlation is undefined or absent). It is a diagnostic, not a
    theoretical memory measure.

    Args:
        series: The series to difference.
        d_grid: Candidate orders, forwarded to :func:`min_frac_diff_order`.
        threshold: Weight truncation threshold; see :func:`frac_diff_weights`.

    Returns:
        A dict with keys ``"d"`` (float), ``"series"`` (the differenced
        ``numpy.ndarray``), ``"adf_statistic"`` (float), ``"n_obs"`` (int) and
        ``"memory_retained"`` (float). Every scalar is a native Python type, so
        the dict serialises to JSON apart from the ``"series"`` array itself.
    """
    arr = _as_1d(series)
    d = min_frac_diff_order(arr, d_grid=d_grid, threshold=threshold)
    transformed = frac_diff_ffd(arr, d, threshold)
    statistic, _ = adf_statistic(transformed)

    return {
        "d": float(d),
        "series": transformed,
        "adf_statistic": float(statistic),
        "n_obs": int(np.isfinite(transformed).sum()),
        "memory_retained": float(_pearson_overlap(arr, transformed)),
    }
