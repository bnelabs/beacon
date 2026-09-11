"""Tests for split conformal prediction.

The claim being tested is a *coverage guarantee*: for exchangeable data, the
interval contains the observation at least ``1 - alpha`` of the time, for any model
and any data distribution. That is a statistical claim, so it is checked
empirically with fixed seeds and sample sizes large enough that Monte Carlo noise
is far below the tolerance used.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from backend.modules.engine.conformal import (
    AdaptiveConformalInference,
    NormalizedConformalCalibrator,
    SplitConformalCalibrator,
    conformal_quantile,
)


class TestConformalQuantile:
    def test_returns_the_finite_sample_rank_not_the_plain_quantile(self):
        # n = 9, alpha = 0.1  ->  rank = ceil(10 * 0.9) = 9  ->  9th smallest.
        scores = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
        assert conformal_quantile(scores, 0.1) == 9.0

        # A plain empirical quantile at 0.9 would interpolate to 8.2; the (n+1)
        # correction is exactly what buys the finite-sample guarantee.
        assert conformal_quantile(scores, 0.1) != pytest.approx(np.quantile(scores, 0.9))

    def test_higher_confidence_widens_the_quantile(self):
        scores = list(range(1, 101))
        q90 = conformal_quantile(scores, 0.10)
        q95 = conformal_quantile(scores, 0.05)
        q80 = conformal_quantile(scores, 0.20)
        assert q80 < q90 < q95

    def test_returns_infinity_when_the_sample_is_too_small(self):
        # n = 5, alpha = 0.01  ->  rank = ceil(6 * 0.99) = 6  >  5.
        assert conformal_quantile([1.0, 2.0, 3.0, 4.0, 5.0], 0.01) == float("inf")

    def test_infinite_is_not_a_placeholder_for_a_narrow_interval(self):
        # The caller must be able to see that no finite guarantee is available.
        quantile = conformal_quantile([1.0, 2.0], 0.01)
        assert math.isinf(quantile)
        assert not math.isfinite(quantile)

    def test_validation(self):
        with pytest.raises(ValueError, match="alpha"):
            conformal_quantile([1.0, 2.0], 0.0)
        with pytest.raises(ValueError, match="alpha"):
            conformal_quantile([1.0, 2.0], 1.0)
        with pytest.raises(ValueError, match="empty"):
            conformal_quantile([], 0.1)
        with pytest.raises(ValueError, match="non-finite"):
            conformal_quantile([1.0, float("nan")], 0.1)


class TestSplitConformalCoverage:
    """The guarantee itself, measured rather than asserted."""

    def test_coverage_meets_target_on_exchangeable_data(self):
        rng = np.random.default_rng(20260301)
        n_cal, n_test, alpha = 4_000, 20_000, 0.1

        calibrate_y = rng.normal(size=n_cal)
        calibrate_pred = np.zeros(n_cal)
        test_y = rng.normal(size=n_test)
        test_pred = np.zeros(n_test)

        calibrator = SplitConformalCalibrator(alpha=alpha).fit(calibrate_y, calibrate_pred)
        coverage = calibrator.empirical_coverage(test_y, test_pred)

        # Binomial noise at n=20000 is sd ~0.002, so 0.01 is ~5 sigma.
        assert coverage >= (1 - alpha) - 0.01
        assert coverage <= (1 - alpha) + 0.01

    def test_coverage_holds_when_the_model_is_biased(self):
        # A deliberately bad model: the guarantee is distribution-free and does
        # not require the model to be any good.
        rng = np.random.default_rng(20260302)
        alpha = 0.1
        calibrate_pred = np.full(4_000, 7.0)
        test_pred = np.full(20_000, 7.0)

        calibrator = SplitConformalCalibrator(alpha=alpha).fit(
            rng.normal(loc=3.0, size=4_000), calibrate_pred
        )
        coverage = calibrator.empirical_coverage(
            rng.normal(loc=3.0, size=20_000), test_pred
        )
        assert coverage >= (1 - alpha) - 0.01

    @pytest.mark.parametrize(
        "name,generator",
        [
            ("student_t3_fat_tails", lambda rng, n: rng.standard_t(df=3, size=n)),
            ("uniform_platykurtic", lambda rng, n: rng.uniform(-1.0, 1.0, size=n)),
            (
                "lognormal_skewed",
                lambda rng, n: rng.lognormal(size=n) - float(np.e ** 0.5),
            ),
            (
                "mostly_quiet_with_jumps",
                lambda rng, n: rng.normal(
                    scale=np.where(rng.random(n) < 0.9, 0.05, 3.0)
                ),
            ),
        ],
    )
    def test_conformal_hits_the_target_where_a_gaussian_interval_does_not(
        self, name, generator
    ):
        """Why conformal instead of a normal approximation.

        A Gaussian interval is half-width ``z * sd``, which is the right summary
        only when the residuals are normal. For every other shape the sample
        standard deviation is the wrong scaling: fat tails inflate it far beyond
        the region that actually contains 90% of the mass, skewed and bounded
        shapes misplace it entirely. Conformal reads the empirical quantile of the
        residuals and so lands on the requested level regardless of shape.

        Measured errors in this suite are around 0.001-0.004 for conformal against
        0.03-0.06 for the Gaussian interval. A shape where the Gaussian *wins* is
        recorded separately in the discrete-score test below, so this is not
        presented as a universal claim.
        """
        rng = np.random.default_rng(20260303)
        alpha = 0.1
        n_cal, n_test = 8_000, 40_000

        calibrate_resid = generator(rng, n_cal)
        test_resid = generator(rng, n_test)

        conformal_coverage = SplitConformalCalibrator(alpha=alpha).fit(
            calibrate_resid, np.zeros(n_cal)
        ).empirical_coverage(test_resid, np.zeros(n_test))

        z = 1.6448536269514722  # standard normal 95th percentile
        gaussian_margin = z * float(np.std(calibrate_resid))
        gaussian_coverage = float(np.mean(np.abs(test_resid) <= gaussian_margin))

        conformal_error = abs(conformal_coverage - (1 - alpha))
        gaussian_error = abs(gaussian_coverage - (1 - alpha))

        assert conformal_error <= 0.01, (
            f"{name}: conformal coverage {conformal_coverage:.4f} is not within "
            "0.01 of the 0.90 target"
        )
        assert conformal_error < gaussian_error, (
            f"{name}: conformal error {conformal_error:.4f} should beat Gaussian "
            f"error {gaussian_error:.4f} (coverages {conformal_coverage:.4f} vs "
            f"{gaussian_coverage:.4f})"
        )

    def test_discrete_scores_make_conformal_conservative(self):
        """A recorded limitation, not a passing grade for conformal.

        When the nonconformity scores take few distinct values, the finite-sample
        quantile jumps past the level and the interval over-covers. Here the
        Gaussian interval is the closer of the two. Conformal's guarantee is
        one-sided -- it promises *at least* ``1 - alpha`` -- so over-coverage is
        not a violation, but it does mean wider intervals than necessary and it is
        worth knowing before applying this to discretised residuals.
        """
        rng = np.random.default_rng(20260312)
        alpha = 0.1
        n_cal, n_test = 8_000, 40_000

        def discrete(rng_, n):
            # 88% of residual magnitude 1, 12% magnitude 5: only two values.
            base = np.where(rng_.random(n) < 0.5, -1.0, 1.0)
            outlier = np.where(rng_.random(n) < 0.5, -5.0, 5.0)
            return np.where(rng_.random(n) < 0.88, base, outlier)

        calibrate_resid = discrete(rng, n_cal)
        test_resid = discrete(rng, n_test)

        conformal_coverage = SplitConformalCalibrator(alpha=alpha).fit(
            calibrate_resid, np.zeros(n_cal)
        ).empirical_coverage(test_resid, np.zeros(n_test))
        gaussian_coverage = float(
            np.mean(np.abs(test_resid) <= 1.6448536269514722 * np.std(calibrate_resid))
        )

        # The guarantee is one-sided: conformal does not under-cover.
        assert conformal_coverage >= 1 - alpha
        # But it is conservative here, and the test records that rather than
        # pretending conformal dominates in every case.
        assert conformal_coverage > gaussian_coverage
        assert abs(conformal_coverage - (1 - alpha)) > abs(gaussian_coverage - (1 - alpha))

    def test_interval_width_grows_as_confidence_rises(self):
        rng = np.random.default_rng(20260304)
        calibrator = SplitConformalCalibrator(alpha=0.1).fit(
            rng.normal(size=2_000), np.zeros(2_000)
        )
        widths = [
            calibrator.interval(0.0, alpha=a).width for a in (0.2, 0.1, 0.05, 0.01)
        ]
        assert widths == sorted(widths)
        assert widths[0] < widths[-1]

    def test_interval_contains_the_prediction_and_truth_when_calibrated(self):
        rng = np.random.default_rng(20260305)
        calibrator = SplitConformalCalibrator(alpha=0.2).fit(
            rng.normal(size=1_000), np.zeros(1_000)
        )
        interval = calibrator.interval(0.5)
        assert interval.contains(0.5)
        assert interval.lower < 0.5 < interval.upper
        assert interval.is_finite
        assert interval.width > 0


class TestNormalizedConformal:
    def test_wider_sigma_gives_a_wider_interval(self):
        rng = np.random.default_rng(20260306)
        sigma = rng.uniform(0.5, 2.0, size=3_000)
        residuals = rng.normal(scale=sigma)
        calibrator = NormalizedConformalCalibrator(alpha=0.1).fit(
            residuals, np.zeros_like(residuals), sigma
        )

        narrow = calibrator.interval(0.0, sigma=0.5)
        wide = calibrator.interval(0.0, sigma=2.0)
        assert wide.width > narrow.width
        assert wide.width == pytest.approx(4 * narrow.width, rel=1e-9)

    def test_normalized_beats_absolute_under_heteroskedasticity(self):
        """The point of normalising: one global width cannot fit all regimes."""
        rng = np.random.default_rng(20260307)
        alpha = 0.1
        n_cal, n_test = 5_000, 20_000

        cal_sigma = rng.uniform(0.2, 3.0, size=n_cal)
        test_sigma = rng.uniform(0.2, 3.0, size=n_test)
        cal_resid = rng.normal(scale=cal_sigma)
        test_resid = rng.normal(scale=test_sigma)

        normalized = NormalizedConformalCalibrator(alpha=alpha).fit(
            cal_resid, np.zeros(n_cal), cal_sigma
        )
        absolute = SplitConformalCalibrator(alpha=alpha).fit(
            cal_resid, np.zeros(n_cal)
        )

        normalized_margin = conformal_quantile(normalized.scores, alpha)
        normalized_covered = np.abs(test_resid) / test_sigma <= normalized_margin
        absolute_covered = np.abs(test_resid) <= absolute.margin

        # Both should be near the target; the normalized one should track it more
        # tightly because its width follows the local scale.
        assert float(normalized_covered.mean()) >= (1 - alpha) - 0.01
        assert abs(float(normalized_covered.mean()) - (1 - alpha)) <= abs(
            float(absolute_covered.mean()) - (1 - alpha)
        ) + 0.01

    def test_validation(self):
        with pytest.raises(ValueError, match="equal length"):
            NormalizedConformalCalibrator().fit([1.0, 2.0], [0.0], [1.0, 1.0])
        with pytest.raises(ValueError, match="strictly positive"):
            NormalizedConformalCalibrator().fit([1.0], [0.0], [0.0])
        with pytest.raises(ValueError, match="strictly positive"):
            NormalizedConformalCalibrator().fit([1.0], [0.0], [float("nan")])

        fitted = NormalizedConformalCalibrator().fit([1.0, 2.0], [0.0, 0.0], [1.0, 1.0])
        with pytest.raises(ValueError, match="strictly positive"):
            fitted.interval(0.0, sigma=-1.0)


class TestAdaptiveConformalInference:
    def test_drift_that_breaks_static_conformal_is_tracked_by_aci(self):
        """Exchangeability fails under drift; ACI pulls coverage back.

        A static interval calibrated on a calm period under-covers once the noise
        scale jumps. ACI notices the misses and raises its level, widening the
        interval until coverage returns to target.
        """
        rng = np.random.default_rng(20260309)
        alpha = 0.1
        n_calm, n_storm = 3_000, 6_000

        calm_resid = rng.normal(scale=1.0, size=n_calm)
        storm_resid = rng.normal(scale=6.0, size=n_storm)

        # Static: calibrated on the calm period only.
        static = SplitConformalCalibrator(alpha=alpha).fit(calm_resid, np.zeros(n_calm))
        static_coverage_storm = static.empirical_coverage(
            storm_resid, np.zeros(n_storm)
        )
        assert static_coverage_storm < (1 - alpha), (
            "the drift should break static conformal; otherwise this test proves nothing"
        )

        # ACI: warm up on the calm period, then run online through the storm.
        aci = AdaptiveConformalInference(alpha=alpha, gamma=0.02, buffer_size=1_000)
        for residual in calm_resid:
            margin = aci.margin() if aci.n_scores else 3.0
            aci.update(abs(float(residual)), covered=abs(float(residual)) <= margin)

        storm_covered = 0
        for residual in storm_resid:
            margin = aci.margin()
            covered = abs(float(residual)) <= margin
            storm_covered += int(covered)
            aci.update(abs(float(residual)), covered=covered)

        aci_coverage_storm = storm_covered / n_storm
        assert aci_coverage_storm > static_coverage_storm, (
            f"ACI {aci_coverage_storm:.3f} should beat static "
            f"{static_coverage_storm:.3f} under drift"
        )
        # And it should be in the neighbourhood of the target, not merely better.
        assert aci_coverage_storm >= (1 - alpha) - 0.05

    def test_level_falls_on_a_miss_and_rises_on_a_cover(self):
        """The control law's direction, which is easy to get backwards.

        ``alpha`` is the MIScoverage level, so a *smaller* alpha means a *wider*
        interval. A miss must therefore lower alpha, widening the interval and
        pushing coverage back toward the target. The update
        ``alpha <- alpha + gamma * (target - err)`` does exactly that: ``err = 1``
        makes the increment negative.
        """
        aci = AdaptiveConformalInference(alpha=0.1, gamma=0.05)
        start = aci.alpha
        after_miss = aci.update(1.0, covered=False)
        assert after_miss < start, "a miss must lower alpha, widening the interval"
        after_cover = aci.update(0.1, covered=True)
        assert after_cover > after_miss, "a cover must raise alpha, narrowing it"

    def test_level_is_bounded(self):
        aci = AdaptiveConformalInference(alpha=0.1, gamma=0.5, min_alpha=0.05, max_alpha=0.5)
        for _ in range(200):
            aci.update(1.0, covered=False)
        assert aci.alpha <= 0.5
        for _ in range(400):
            aci.update(0.0, covered=True)
        assert aci.alpha >= 0.05

    def test_buffer_is_bounded(self):
        aci = AdaptiveConformalInference(alpha=0.1, gamma=0.01, buffer_size=10)
        for i in range(100):
            aci.update(float(i), covered=True)
        assert aci.n_scores == 10
        assert aci.n_updates == 100

    def test_realised_coverage_is_nan_before_any_update(self):
        aci = AdaptiveConformalInference()
        assert math.isnan(aci.realised_coverage)

    def test_margin_requires_scores(self):
        aci = AdaptiveConformalInference()
        with pytest.raises(RuntimeError, match="no scores"):
            aci.margin()

    def test_validation(self):
        with pytest.raises(ValueError, match="alpha"):
            AdaptiveConformalInference(alpha=0.0)
        with pytest.raises(ValueError, match="gamma"):
            AdaptiveConformalInference(gamma=0.0)
        with pytest.raises(ValueError, match="buffer_size"):
            AdaptiveConformalInference(buffer_size=0)
        with pytest.raises(ValueError, match="min_alpha"):
            AdaptiveConformalInference(min_alpha=0.9, max_alpha=0.1)

        aci = AdaptiveConformalInference()
        with pytest.raises(ValueError, match="score"):
            aci.update(-1.0, covered=True)
        with pytest.raises(ValueError, match="score"):
            aci.update(float("nan"), covered=True)

    def test_report_serialises(self):
        aci = AdaptiveConformalInference(alpha=0.1)
        for i in range(50):
            aci.update(0.5, covered=i % 2 == 0)
        payload = aci.to_dict()
        json.dumps(payload, allow_nan=False)
        assert payload["target_coverage"] == pytest.approx(0.9)
        assert 0.0 <= payload["realised_coverage"] <= 1.0


class TestCalibratorLifecycle:
    def test_unfitted_calibrator_refuses_to_produce_an_interval(self):
        with pytest.raises(RuntimeError, match="not been fitted"):
            SplitConformalCalibrator().margin
        with pytest.raises(RuntimeError, match="not been fitted"):
            NormalizedConformalCalibrator().interval(0.0, sigma=1.0)
        with pytest.raises(RuntimeError, match="not been fitted"):
            NormalizedConformalCalibrator().empirical_coverage([0.0], [0.0], [1.0])

    def test_fit_validation(self):
        with pytest.raises(ValueError, match="entries"):
            SplitConformalCalibrator().fit([1.0, 2.0], [1.0])
        with pytest.raises(ValueError, match="empty"):
            SplitConformalCalibrator().fit([], [])
        with pytest.raises(ValueError, match="non-finite"):
            SplitConformalCalibrator().fit([1.0, float("nan")], [0.0, 0.0])
        with pytest.raises(ValueError, match="alpha"):
            SplitConformalCalibrator(alpha=1.5)

    def test_fit_returns_self_for_chaining(self):
        calibrator = SplitConformalCalibrator(alpha=0.1).fit([1.0, 2.0], [0.0, 0.0])
        assert calibrator.n_calibration == 2

    def test_coverage_requires_matching_lengths(self):
        calibrator = SplitConformalCalibrator().fit([1.0, 2.0], [0.0, 0.0])
        with pytest.raises(ValueError, match="non-empty and equal length"):
            calibrator.empirical_coverage([1.0], [0.0, 0.0])


class TestIntervalSerialisation:
    def test_interval_serialises_to_json(self):
        rng = np.random.default_rng(20260310)
        calibrator = SplitConformalCalibrator(alpha=0.1).fit(
            rng.normal(size=500), np.zeros(500)
        )
        interval = calibrator.interval(0.25)
        payload = interval.to_dict()
        json.dumps(payload, allow_nan=False)
        assert payload["coverage_target"] == pytest.approx(0.9)
        assert payload["method"] == "split_conformal_absolute"
        assert payload["n_calibration"] == 500

    def test_infinite_interval_reports_itself_as_not_finite(self):
        calibrator = SplitConformalCalibrator(alpha=0.001).fit([1.0, 2.0], [0.0, 0.0])
        interval = calibrator.interval(0.0)
        assert not interval.is_finite
        assert math.isinf(interval.margin)


class TestDeterminism:
    def test_repeated_calibration_is_identical(self):
        rng = np.random.default_rng(20260311)
        truth = rng.normal(size=1_000)
        pred = np.zeros(1_000)

        first = SplitConformalCalibrator(alpha=0.1).fit(truth, pred).margin
        second = SplitConformalCalibrator(alpha=0.1).fit(truth, pred).margin
        assert first == second
