"""Contract tests for the pre-registered evaluation runner's pure helpers.

The runner itself (scripts/run_preregistered_eval.py) executes tagged
protocols under a single-run rule, so it is not exercised end-to-end here --
that would be a second run. What IS pinned are the helpers whose correctness
the published verdicts depend on:

* ``_holm``: the step-down propagation (a failure rejects everything after
  it -- getting this wrong would let a non-significant AP "pass" criterion 4);
* ``_wilson_ci``: the interval the reports quote for precision at alarm;
* ``_hazard_logit_scores``: protocol v3's second declared scorer -- fit/label
  mechanics, the no-onsets refusal (absence, not zero signal), determinism
  (a frozen scorer that is not reproducible is not auditable), and the
  learnability smoke (scores before a training-span stress plateau must
  average above quiet-baseline scores -- weak, structural, and deliberately
  not a performance claim).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]


def _runner():
    spec = importlib.util.spec_from_file_location(
        "prereg_runner", REPO / "scripts" / "run_preregistered_eval.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runner():
    return _runner()


class TestHolm:
    def test_propagation_rejects_everything_after_the_first_failure(self, runner):
        # 2*0.03 = 0.06 > 0.05 fails first (step-down order), so 0.04 fails
        # with it even though 3*... would not have: propagation is the point.
        assert runner._holm({"a": 0.04, "b": 0.03}, 0.05) == {"a": False, "b": False}

    def test_survivors_when_adjusted_values_hold(self, runner):
        result = runner._holm({"a": 0.01, "b": 0.02, "c": 0.20}, 0.05)
        assert result == {"a": True, "b": True, "c": False}

    def test_empty_pool(self, runner):
        assert runner._holm({}, 0.05) == {}


class TestWilson:
    def test_midpoint_case(self, runner):
        lo, hi = runner._wilson_ci(50, 100)
        assert 0.39 < lo < 0.42 and 0.58 < hi < 0.61

    def test_extremes_stay_in_unit_interval(self, runner):
        lo, hi = runner._wilson_ci(0, 40)
        assert lo == 0.0 and 0.0 < hi < 0.2
        lo, hi = runner._wilson_ci(40, 40)
        assert hi == 1.0 and lo > 0.8

    def test_zero_trials_is_nan_not_a_number(self, runner):
        lo, hi = runner._wilson_ci(0, 0)
        assert np.isnan(lo) and np.isnan(hi)


class TestHazardLogit:
    @staticmethod
    def _train_series(seed: int = 1) -> np.ndarray:
        rng = np.random.default_rng(seed)
        train = rng.normal(0.0, 1.0, 1500)
        # Two sustained stress plateaus: the labeller's persistence rule
        # (min_duration=5, horizon 21) turns these into episodes with onsets.
        train[400:460] += 4.0
        train[900:960] += 4.0
        return train

    @staticmethod
    def _definition():
        from backend.modules.data.event_labeller import EventDefinition

        return EventDefinition(direction="up", quantile=0.95, horizon=21, min_duration=5)

    def test_returns_finite_scores_on_the_requested_grid(self, runner):
        train = self._train_series()
        offsets = np.arange(30, 1200)
        scores = runner._hazard_logit_scores(
            train, float(train.mean()), float(train.std()), 1.0,
            self._definition(), train, offsets,
        )
        assert scores is not None
        assert scores.shape == (offsets.size,)
        assert np.all(np.isfinite(scores))

    def test_no_training_onsets_is_declared_absence(self, runner):
        rng = np.random.default_rng(2)
        flat = rng.normal(0.0, 1.0, 1500) * 0.001  # never crosses its own q95 move
        result = runner._hazard_logit_scores(
            flat, float(flat.mean()), float(flat.std()) or 1.0, 1.0,
            self._definition(), flat, np.arange(30, 1200),
        )
        assert result is None

    def test_frozen_scorer_is_deterministic(self, runner):
        train = self._train_series()
        offsets = np.arange(30, 1200)
        args = (train, float(train.mean()), float(train.std()), 1.0,
                self._definition(), train, offsets)
        first = runner._hazard_logit_scores(*args)
        second = runner._hazard_logit_scores(*args)
        assert np.array_equal(first, second)

    def test_scores_anticipate_training_plateaus(self, runner):
        """Structural learnability, not a performance claim: inside the
        training span, the window leading into a plateau must average a
        higher hazard score than a quiet baseline window."""
        train = self._train_series()
        offsets = np.arange(30, 1400)
        scores = runner._hazard_logit_scores(
            train, float(train.mean()), float(train.std()), 1.0,
            self._definition(), train, offsets,
        )
        pre_plateau = scores[(offsets >= 379) & (offsets < 400)]
        baseline = scores[(offsets >= 100) & (offsets < 300)]
        assert pre_plateau.mean() > baseline.mean()

    def test_nan_values_are_imputed_not_propagated(self, runner):
        train = self._train_series()
        train[500:505] = np.nan
        offsets = np.arange(30, 1200)
        scores = runner._hazard_logit_scores(
            train, float(np.nanmean(train)), float(np.nanstd(train)), 1.0,
            self._definition(), train, offsets,
        )
        assert scores is not None and np.all(np.isfinite(scores))


class TestProtocolTableIntegrity:
    """The tag wins: version constants that published runs depended on must
    not drift when the runner evolves."""

    def test_v1_v2_constants_stay_frozen(self, runner):
        for version in ("v1", "v2"):
            proto = runner.PROTOCOLS[version]
            assert proto["alarm_quantile"] == 0.95
            assert proto["scorers"] == ("tan_frozen",)
        assert runner.QUANTILE == 0.95
        assert runner.HORIZON == 21
        assert runner.MIN_DURATION == 5
        assert runner.MIN_MEDIAN_LEAD == 10
        assert runner.MAX_FALSE_ALARMS_PER_QUIET_YEAR == 4.0
        assert runner.PERM_SEED == 20260917
        assert runner.MIN_TESTABLE_FAMILY == 3

    def test_v3_declares_its_changes_and_only_its_changes(self, runner):
        proto = runner.PROTOCOLS["v3"]
        assert proto["alarm_quantile"] == 0.98
        assert proto["scorers"] == ("tan_frozen", "hazard_logit")
        # family identical to v2's object -- v3 changes the operating point
        # and the scorer set, never the family dispositions.
        assert proto["family"] is runner.FAMILY_V2
