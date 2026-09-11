"""Tests for the KPSS stationarity test and its enforcement in the quality gate.

Why this file exists
--------------------

Before it, the platform had only the ADF test, whose null is a unit root. ADF
has low power in short samples, so a series could pass order selection on "ADF
did not reject" evidence alone and still be non-stationary. KPSS turns the null
around -- stationarity is the null, a unit root is the alternative -- so the two
tests are complementary rather than redundant.

These tests lock in three things:

* The KPSS statistic matches its definition (the LM statistic with a
  Newey-West / Bartlett long-run variance), not merely "some number comes out".
* The verdicts on known processes are right: white noise is not rejected, a
  random walk is rejected under both variants, and a deterministic trend is
  rejected by the level variant while the trend variant accepts it.
* The quality gate actually **consumes** the test on its production path. A
  random walk handed to ``DataQualityGate.enforce`` -- the method the DATA
  orchestrator calls -- must carry a stationarity finding in the attestation,
  and that finding must be able to block certification when policy demands.

The empty-payload guarantee from section 2A of the executive review is re-tested
here because the stationarity scan must not open a path around it.

Every test seeds its own ``numpy.random.default_rng`` with a fixed integer, so
the suite is deterministic.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from backend.exceptions import DataQualityError, EmptyDatasetError
from backend.modules.data.fractional import (
    KPSS_CRITICAL_VALUES,
    KPSS_MIN_OBSERVATIONS,
    KPSSResult,
    adf_statistic,
    kpss_statistic,
    kpss_test,
)
from backend.modules.data.quality_gate import DataQualityGate, QualityPolicy


def _frame(values) -> pd.DataFrame:
    """A payload shaped like the DATA pipeline's: a Date column and a value."""
    return pd.DataFrame(
        {
            "Date": pd.date_range("2023-01-01", periods=len(values), freq="D"),
            "Value": list(values),
        }
    )


# ---------------------------------------------------------------------------
# The statistic matches its definition
# ---------------------------------------------------------------------------


def test_kpss_level_statistic_matches_the_direct_definition() -> None:
    """The returned number is the LM statistic, recomputed independently.

    ``eta = T**-2 * sum(S_t**2)`` and ``s2(l)`` is the Bartlett-weighted sum of
    autocovariances. With ``l = 0`` the estimator collapses to ``gamma_0``, so
    the check is unambiguous; a second case with ``l = 3`` exercises the decay
    weights ``1 - j/(l+1)``.
    """
    rng = np.random.default_rng(20240603)
    series = rng.normal(size=60)
    residuals = series - series.mean()

    eta = float(np.sum(np.cumsum(residuals) ** 2)) / series.size**2

    # l = 0: the long-run variance is the contemporaneous variance.
    gamma_0 = float(residuals @ residuals) / series.size
    assert kpss_statistic(series, regression="level", max_lag=0)[0] == pytest.approx(
        eta / gamma_0, rel=1e-12
    )

    # l = 3: gamma_0 plus two-times each Bartlett-weighted autocovariance.
    lag = 3
    long_run = gamma_0
    for j in range(1, lag + 1):
        gamma_j = float(residuals[j:] @ residuals[:-j]) / series.size
        long_run += 2.0 * (1.0 - j / (lag + 1)) * gamma_j
    statistic, lag_used = kpss_statistic(series, regression="level", max_lag=lag)
    assert lag_used == lag
    assert statistic == pytest.approx(eta / long_run, rel=1e-12)


def test_kpss_statistic_mirrors_the_adf_return_shape() -> None:
    """Both unit-root tests return ``(float, int)`` -- statistic then lag."""
    rng = np.random.default_rng(20240604)
    series = rng.normal(size=200)

    kpss_value = kpss_statistic(series, regression="level")
    adf_value = adf_statistic(series)

    assert isinstance(kpss_value, tuple) and len(kpss_value) == 2
    assert isinstance(kpss_value[0], float) and isinstance(kpss_value[1], int)
    assert isinstance(adf_value, tuple) and len(adf_value) == 2
    # The two tests must disagree in sign of the evidence: KPSS is upper-tailed,
    # ADF lower-tailed, so a stationary series has a small KPSS statistic and a
    # negative ADF one.
    assert kpss_value[0] < KPSS_CRITICAL_VALUES["level"]["5%"]
    assert adf_value[0] < 0.0


def test_kpss_critical_values_are_the_verified_table() -> None:
    """Lock the numbers so a silent transcription change cannot pass review.

    The values are Table 1 of Kwiatkowski, Phillips, Schmidt and Shin (1992).
    They were verified against the original paper and against the ``statsmodels``
    ``kpss`` implementation, which hard-codes the identical table; this test
    records that agreement so any edit is deliberate.
    """
    assert KPSS_CRITICAL_VALUES == {
        "level": {"10%": 0.347, "5%": 0.463, "2.5%": 0.574, "1%": 0.739},
        "trend": {"10%": 0.119, "5%": 0.146, "2.5%": 0.176, "1%": 0.216},
    }


# ---------------------------------------------------------------------------
# Known processes
# ---------------------------------------------------------------------------


def test_kpss_does_not_reject_white_noise() -> None:
    """White noise is stationary, so the stationary null must survive."""
    rng = np.random.default_rng(20240602)
    white_noise = rng.normal(size=500)

    level = kpss_test(white_noise, regression="level")
    trend = kpss_test(white_noise, regression="trend")

    assert level.stationary is True
    assert trend.stationary is True
    assert level.statistic <= KPSS_CRITICAL_VALUES["level"]["5%"]
    assert level.p_value > 0.05


def test_kpss_rejects_a_random_walk() -> None:
    """A unit root is the alternative, so both variants must reject it."""
    rng = np.random.default_rng(20240606)
    random_walk = np.cumsum(rng.normal(size=500))

    level = kpss_test(random_walk, regression="level")
    trend = kpss_test(random_walk, regression="trend")

    assert level.stationary is False
    assert trend.stationary is False
    assert level.statistic > KPSS_CRITICAL_VALUES["level"]["5%"]
    assert trend.statistic > KPSS_CRITICAL_VALUES["trend"]["5%"]
    # Both tests agree with the same evidence: ADF cannot reject a unit root.
    assert adf_statistic(random_walk)[0] > -2.86


def test_kpss_deterministic_trend_rejects_level_but_not_trend() -> None:
    """The two variants are not interchangeable, which is why both exist.

    A trend-stationary series is *not* stationary around a constant, so the
    level variant rejects; it *is* stationary once the deterministic trend is
    removed, so the trend variant accepts. Running only the level variant would
    have mislabelled every trending macro series as a unit root.
    """
    rng = np.random.default_rng(20240517)
    trend = np.arange(500.0) + rng.normal(size=500)

    level = kpss_test(trend, regression="level")
    detrended = kpss_test(trend, regression="trend")

    assert level.stationary is False
    assert detrended.stationary is True
    assert level.statistic > KPSS_CRITICAL_VALUES["level"]["5%"]
    assert detrended.statistic <= KPSS_CRITICAL_VALUES["trend"]["5%"]


def test_kpss_refuses_to_score_a_perfectly_deterministic_series() -> None:
    """A noiseless line leaves floating-point dust, not data.

    The residuals are ~1e-31, so the LM ratio is a 0/0 artefact of summation
    order -- an earlier version scored 3.3 on it and would have called a pure
    line a decisive unit root. The level variant is still computable (the line
    is not stationary around a constant) and must reject; the trend variant must
    decline rather than invent a number.
    """
    exact_line = np.arange(40.0)

    assert kpss_test(exact_line, regression="level").stationary is False
    with pytest.raises(ValueError, match="explained exactly"):
        kpss_test(exact_line, regression="trend")


# ---------------------------------------------------------------------------
# Degenerate input and argument validation
# ---------------------------------------------------------------------------


def test_kpss_rejects_short_and_constant_series() -> None:
    """A degenerate sample cannot support the test; it must say so."""
    with pytest.raises(ValueError, match="too short"):
        kpss_test(np.arange(float(KPSS_MIN_OBSERVATIONS - 1)))

    with pytest.raises(ValueError, match="constant"):
        kpss_test(np.full(50, 3.0))

    with pytest.raises(ValueError, match="no finite observations"):
        kpss_test(np.array([]))


def test_kpss_rejects_unknown_regression_and_significance() -> None:
    rng = np.random.default_rng(20240607)
    series = rng.normal(size=100)

    with pytest.raises(ValueError, match="unknown KPSS regression"):
        kpss_test(series, regression="quadratic")
    with pytest.raises(ValueError, match="unknown significance"):
        kpss_test(series, significance="7%")
    with pytest.raises(ValueError, match="non-negative"):
        kpss_statistic(series, max_lag=-1)


def test_kpss_accepts_the_statsmodels_regression_aliases() -> None:
    """``c``/``ct`` name the same models as ``level``/``trend``."""
    rng = np.random.default_rng(20240608)
    series = rng.normal(size=200)

    assert kpss_test(series, regression="c").regression == "level"
    assert kpss_test(series, regression="ct").regression == "trend"


def test_kpss_result_is_typed_and_serialisable() -> None:
    rng = np.random.default_rng(20240609)
    result = kpss_test(rng.normal(size=300), regression="level")

    assert isinstance(result, KPSSResult)
    payload = result.to_dict()
    assert payload["regression"] == "level"
    assert payload["verdict"] == result.verdict
    assert isinstance(payload["statistic"], float)
    assert isinstance(payload["lags"], int)
    assert json.loads(json.dumps(payload)) == payload


# ---------------------------------------------------------------------------
# The gate consumes the check (reachability from the production path)
# ---------------------------------------------------------------------------


def test_quality_gate_consumes_kpss_on_the_production_path() -> None:
    """A random walk must carry a stationarity finding out of ``enforce``.

    ``enforce`` is what the DATA orchestrator calls before certifying, so a
    finding here is a finding in production -- not an orphaned helper.
    """
    rng = np.random.default_rng(20240610)
    random_walk = np.cumsum(rng.normal(size=400))
    gate = DataQualityGate(QualityPolicy(min_total_rows=5))

    attestation = gate.enforce({"MACRO": _frame(random_walk)}, job_id="job-kpss")

    stationarity = [
        check for check in attestation.checks if check.name.startswith("stationarity[")
    ]
    assert stationarity, "the gate never ran KPSS on the payload"
    check = stationarity[0]
    assert check.name == "stationarity[MACRO.Value]"
    assert "non-stationary" in check.detail
    # Report-only by default: the finding is recorded, certification untouched.
    assert check.passed is True and check.severity == "warning"
    assert check not in attestation.failures
    assert attestation.verified is True


def test_require_stationarity_makes_the_finding_blocking() -> None:
    """The same payload fails when the policy demands stationarity."""
    rng = np.random.default_rng(20240611)
    random_walk = np.cumsum(rng.normal(size=400))
    gate = DataQualityGate(QualityPolicy(min_total_rows=5, require_stationarity=True))

    attestation = gate.evaluate({"MACRO": _frame(random_walk)}, job_id="job-kpss-strict")
    assert attestation.verified is False
    assert "stationarity[MACRO.Value]" in {check.name for check in attestation.failures}

    with pytest.raises(DataQualityError) as excinfo:
        gate.enforce({"MACRO": _frame(random_walk)}, job_id="job-kpss-strict-2")
    assert excinfo.value.code == "DATA_QUALITY_FAILED"


def test_gate_certifies_a_stationary_payload_under_strict_policy() -> None:
    """The strict policy is not a blanket rejection: white noise still passes."""
    rng = np.random.default_rng(20240612)
    gate = DataQualityGate(QualityPolicy(min_total_rows=5, require_stationarity=True))

    attestation = gate.enforce(
        {"MACRO": _frame(rng.normal(size=400))}, job_id="job-kpss-white"
    )

    assert attestation.verified is True
    check = next(
        check for check in attestation.checks if check.name.startswith("stationarity[")
    )
    assert "stationarity not rejected" in check.detail


def test_gate_fails_a_constant_value_column_as_degenerate() -> None:
    """A degenerate column carries no information and must not be certified."""
    gate = DataQualityGate(QualityPolicy(min_total_rows=5))
    attestation = gate.evaluate(
        {"MACRO": _frame(np.full(40, 3.0))}, job_id="job-constant"
    )

    check = next(
        check for check in attestation.checks if check.name.startswith("stationarity[")
    )
    assert check.passed is False
    assert check.severity == "critical"
    assert attestation.verified is False


def test_stationarity_scan_can_be_disabled() -> None:
    gate = DataQualityGate(QualityPolicy(min_total_rows=5, check_stationarity=False))
    attestation = gate.evaluate({"MACRO": _frame(range(40))}, job_id="job-off")
    assert [c for c in attestation.checks if c.name.startswith("stationarity[")] == []


def test_gate_rejects_a_bad_stationarity_significance() -> None:
    gate = DataQualityGate(QualityPolicy(stationarity_significance="7%"))
    with pytest.raises(ValueError, match="not a tabulated KPSS level"):
        gate.evaluate({"MACRO": _frame(range(40))}, job_id="job-bad-sig")


def test_gate_still_rejects_an_empty_payload() -> None:
    """Section 2A's guarantee survives the stationarity scan, even if blocking."""
    gate = DataQualityGate(
        QualityPolicy(require_stationarity=True, check_stationarity=True)
    )

    with pytest.raises(EmptyDatasetError) as excinfo:
        gate.enforce({"A": pd.DataFrame()}, job_id="job-empty")

    assert excinfo.value.code == "EMPTY_DATASET"
