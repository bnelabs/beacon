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


def test_gate_allows_constant_occurrence_marker_for_declared_event_series() -> None:
    gate = DataQualityGate(QualityPolicy(min_total_rows=5))
    attestation = gate.enforce(
        {"FILINGS": _frame(np.ones(40))},
        job_id="job-filing-events",
        event_series_codes={"FILINGS"},
    )

    check = next(
        check for check in attestation.checks if check.name == "stationarity[FILINGS.Value]"
    )
    assert check.passed is True
    assert check.severity == "warning"
    assert "event dates" in check.detail
    assert attestation.verified is True


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


# ---------------------------------------------------------------------------
# Panel grain: KPSS must assess entity series, not their interleaved mixture
# (pipeline-review finding F5 -- the validator and formatter got grain fixes
# in #100/#101; these pin the gate's scan to the same identity registry)
# ---------------------------------------------------------------------------


def _panel_frame(specs, n_obs: int) -> pd.DataFrame:
    """One edge table: ``specs`` is a list of (source, target, values)."""
    dates = pd.date_range("2023-01-01", periods=n_obs, freq="D")
    return pd.concat(
        [
            pd.DataFrame(
                {
                    "Date": dates,
                    "source_bank": source,
                    "target_bank": target,
                    "Value": values,
                }
            )
            for source, target, values in specs
        ],
        ignore_index=True,
    )


def _stationarity_check(attestation) -> "QualityCheck":  # noqa: F821
    checks = [c for c in attestation.checks if c.name.startswith("stationarity[")]
    assert checks, "the gate never ran KPSS on the payload"
    assert len(checks) == 1
    return checks[0]


def test_panel_scan_assesses_entities_not_the_mixture() -> None:
    """One random-walk edge among stationary edges is named, per entity."""
    rng = np.random.default_rng(20260920)
    panel = _panel_frame(
        [
            ("A", "B", rng.normal(size=400)),
            ("A", "C", rng.normal(size=400)),
            ("B", "C", np.cumsum(rng.normal(size=400))),  # unit root
        ],
        n_obs=400,
    )
    gate = DataQualityGate(QualityPolicy(min_total_rows=5))

    check = _stationarity_check(gate.evaluate({"EDGES": panel}, job_id="job-panel"))

    assert check.name == "stationarity[EDGES.Value]"
    assert "panel on (source_bank, target_bank)" in check.detail
    assert "assessed 3 of 3 entity series" in check.detail
    assert "1 non-stationary under both level and trend" in check.detail
    assert "2 stationary" in check.detail
    assert "('B', 'C')" in check.detail  # the offending edge is named
    # report-only by default, exactly like the scalar path
    assert check.passed is True and check.severity == "warning"


def test_panel_verdict_is_order_insensitive_within_entities() -> None:
    """Provider row order is not a time order; the scan must sort per entity."""
    rng = np.random.default_rng(20260921)
    panel = _panel_frame(
        [
            ("A", "B", rng.normal(size=300)),
            ("B", "C", np.cumsum(rng.normal(size=300))),
        ],
        n_obs=300,
    )
    shuffled = panel.sample(frac=1.0, random_state=7).reset_index(drop=True)
    gate = DataQualityGate(QualityPolicy(min_total_rows=5))

    check = _stationarity_check(gate.evaluate({"EDGES": shuffled}, job_id="job-shuffled"))

    assert "1 non-stationary under both level and trend" in check.detail
    assert "1 stationary" in check.detail


def test_wide_panels_are_sampled_deterministically_and_say_so() -> None:
    """60 entities, cap 25: the verdict must name what it actually saw."""
    rng = np.random.default_rng(20260922)
    specs = [
        (f"B{i:03d}", "HUB", rng.normal(size=12)) for i in range(60)
    ]
    panel = _panel_frame(specs, n_obs=12)
    gate = DataQualityGate(QualityPolicy(min_total_rows=5))

    first = _stationarity_check(gate.evaluate({"EDGES": panel}, job_id="job-cap-1"))
    second = _stationarity_check(gate.evaluate({"EDGES": panel}, job_id="job-cap-2"))

    assert "assessed 25 of 60 entity series" in first.detail
    assert "deterministic equispaced sample, cap 25" in first.detail
    assert first.detail == second.detail  # the sample is a function of the keys


def test_require_stationarity_blocks_on_a_nonstationary_entity() -> None:
    """The opt-in blocking policy applies per entity, same as the scalar path."""
    rng = np.random.default_rng(20260923)
    panel = _panel_frame(
        [
            ("A", "B", rng.normal(size=300)),
            ("B", "C", np.cumsum(rng.normal(size=300))),
        ],
        n_obs=300,
    )
    gate = DataQualityGate(QualityPolicy(min_total_rows=5, require_stationarity=True))

    attestation = gate.evaluate({"EDGES": panel}, job_id="job-panel-strict")
    assert attestation.verified is False
    check = _stationarity_check(attestation)
    assert check.passed is False and check.severity == "critical"

    with pytest.raises(DataQualityError) as excinfo:
        gate.enforce({"EDGES": panel}, job_id="job-panel-strict-2")
    assert excinfo.value.code == "DATA_QUALITY_FAILED"


def test_one_frozen_edge_is_counted_not_failed() -> None:
    """A constant entity inside a live panel is a count, not a rejection.

    The whole-column degeneracy failure (and the declared-event exemption)
    already cover a payload where *nothing* moves; one frozen edge among
    live ones must not void an otherwise healthy panel.
    """
    rng = np.random.default_rng(20260924)
    panel = _panel_frame(
        [
            ("A", "B", rng.normal(size=100)),
            ("F", "G", np.full(100, 3.14)),  # frozen edge
        ],
        n_obs=100,
    )
    gate = DataQualityGate(QualityPolicy(min_total_rows=5, require_stationarity=True))

    check = _stationarity_check(gate.evaluate({"EDGES": panel}, job_id="job-frozen-edge"))

    assert "1 degenerate" in check.detail
    assert "1 stationary" in check.detail
    assert check.passed is True  # strict policy: the live entity is stationary


def test_scalar_frames_keep_the_scalar_detail() -> None:
    """The panel branch must not change what a plain series reports."""
    rng = np.random.default_rng(20260925)
    gate = DataQualityGate(QualityPolicy(min_total_rows=5))

    check = _stationarity_check(
        gate.evaluate({"MACRO": _frame(rng.normal(size=200))}, job_id="job-scalar")
    )

    assert "panel on" not in check.detail
    assert "level:" in check.detail and "trend:" in check.detail
