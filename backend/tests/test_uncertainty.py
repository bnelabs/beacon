"""Tests for the aleatoric/epistemic uncertainty decomposition.

The decomposition has an exact definition -- the law of total variance -- so the
tests verify it against an independently derived closed form rather than against
itself, and then check that a synthetic ensemble with a *known* noise level and a
*known* spread of member means recovers both.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from backend.modules.engine.uncertainty import (
    DeepEnsemble,
    EpistemicReference,
    UncertaintyDecomposition,
    assess_uncertainty,
    decompose_variance,
)


class StubMember:
    """A fitted predictor returning a constant, for exercising the decomposition."""

    def __init__(self, value: float, variance: float | None = None) -> None:
        self.value = float(value)
        self.variance = variance

    def predict(self, X):
        size = len(X) if hasattr(X, "__len__") else 1
        return np.full(size, self.value, dtype=float)


def decomposition(aleatoric, epistemic, mean=0.0, n_members=5) -> UncertaintyDecomposition:
    return UncertaintyDecomposition(
        mean=mean,
        aleatoric=aleatoric,
        epistemic=epistemic,
        n_members=n_members,
        method="test",
        ddof=1,
    )


class TestLawOfTotalVariance:
    def test_matches_an_independently_derived_closed_form(self):
        """The identity, checked against the second-moment form.

        The implementation sums an average within-member variance and a variance
        of member means. The independent derivation expands the mixture's second
        moment directly:

            Var(Y) = sum_m w_m (sigma_m^2 + mu_m^2) - (sum_m w_m mu_m)^2

        These are algebraically equal, so agreement is evidence the code computes
        what it claims rather than a restatement of it.
        """
        means = np.array([1.0, 2.0, 4.0, 8.0])
        variances = np.array([0.5, 2.0, 0.25, 3.0])
        weights = np.full(means.size, 1.0 / means.size)

        aleatoric, epistemic = decompose_variance(means, variances, ddof=0)
        analytic_total = float(
            np.sum(weights * (variances + means ** 2))
            - (np.sum(weights * means)) ** 2
        )

        assert aleatoric + epistemic == pytest.approx(analytic_total)
        assert aleatoric == pytest.approx(float(np.mean(variances)))
        assert epistemic == pytest.approx(float(np.var(means, ddof=0)))

    def test_the_two_terms_add_to_the_total(self):
        aleatoric, epistemic = decompose_variance([0.0, 1.0, 5.0], [1.0, 1.0, 1.0], ddof=0)
        assert decomposition(aleatoric, epistemic).total == pytest.approx(aleatoric + epistemic)

    def test_ddof_zero_and_one_differ_by_the_known_factor(self):
        means = [1.0, 2.0, 3.0, 4.0, 5.0]
        _, population = decompose_variance(means, ddof=0)
        _, unbiased = decompose_variance(means, ddof=1)
        # Population variance is (M-1)/M of the unbiased one.
        assert population == pytest.approx(unbiased * (len(means) - 1) / len(means))
        assert unbiased > population


class TestSyntheticRecovery:
    def test_recovers_a_known_noise_level_and_model_spread(self):
        """Draw member means from N(0, tau^2) with known within-member variance.

        With ddof=1 the epistemic term is unbiased for tau^2 and the aleatoric
        term for sigma^2, so averaging over many independent ensembles must
        recover both. This is the claim the whole module rests on.
        """
        rng = np.random.default_rng(20260401)
        tau_squared = 4.0
        sigma_squared = 1.5
        n_members = 10
        replicates = 2_000

        epistemic_unbiased = []
        epistemic_population = []
        aleatoric = []

        for _ in range(replicates):
            member_means = rng.normal(scale=math.sqrt(tau_squared), size=n_members)
            member_variances = np.full(n_members, sigma_squared)

            a, e1 = decompose_variance(member_means, member_variances, ddof=1)
            _, e0 = decompose_variance(member_means, member_variances, ddof=0)

            aleatoric.append(a)
            epistemic_unbiased.append(e1)
            epistemic_population.append(e0)

        assert np.mean(aleatoric) == pytest.approx(sigma_squared, abs=0.05)
        assert np.mean(epistemic_unbiased) == pytest.approx(tau_squared, abs=0.25)
        # The population form is biased low by (M-1)/M, and the test says so.
        assert np.mean(epistemic_population) == pytest.approx(
            tau_squared * (n_members - 1) / n_members, abs=0.25
        )

    def test_a_truthful_ensemble_attributes_variance_correctly(self):
        """With no spread in member means, all variance is aleatoric."""
        rng = np.random.default_rng(20260402)
        member_means = np.full(8, 3.0)
        member_variances = rng.uniform(0.5, 2.0, size=8)

        aleatoric, epistemic = decompose_variance(member_means, member_variances)
        assert aleatoric > 0
        assert epistemic == pytest.approx(0.0)

    def test_disagreement_is_epistemic(self):
        """With identical within-member variance and no noise, spread is epistemic."""
        means = np.array([1.0, 2.0, 3.0, 4.0])
        variances = np.zeros(4)
        aleatoric, epistemic = decompose_variance(means, variances)
        assert aleatoric == pytest.approx(0.0)
        assert epistemic > 0


class TestDecomposeValidation:
    def test_empty_means_is_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            decompose_variance([])

    def test_non_finite_means_are_rejected(self):
        with pytest.raises(ValueError, match="non-finite"):
            decompose_variance([1.0, float("nan")])

    def test_length_mismatch_is_rejected(self):
        with pytest.raises(ValueError, match="entries"):
            decompose_variance([1.0, 2.0], [1.0])

    def test_negative_variance_is_rejected(self):
        with pytest.raises(ValueError, match="negative"):
            decompose_variance([1.0, 2.0], [1.0, -1.0])

    def test_non_finite_variance_is_rejected(self):
        with pytest.raises(ValueError, match="non-finite"):
            decompose_variance([1.0, 2.0], [1.0, float("inf")])

    def test_invalid_ddof_is_rejected(self):
        with pytest.raises(ValueError, match="ddof"):
            decompose_variance([1.0, 2.0], ddof=2)

    def test_ddof_one_with_a_single_member_is_rejected(self):
        with pytest.raises(ValueError, match="at least two members"):
            decompose_variance([1.0], ddof=1)

    def test_missing_variances_give_zero_aleatoric(self):
        # Nothing to attribute to the world, so nothing is attributed.
        aleatoric, epistemic = decompose_variance([1.0, 2.0, 3.0])
        assert aleatoric == pytest.approx(0.0)
        assert epistemic > 0


class TestShares:
    def test_shares_sum_to_one(self):
        value = decomposition(aleatoric=3.0, epistemic=1.0)
        assert value.aleatoric_share + value.epistemic_share == pytest.approx(1.0)

    def test_shares_are_the_right_proportions(self):
        value = decomposition(aleatoric=3.0, epistemic=1.0)
        assert value.aleatoric_share == pytest.approx(0.75)
        assert value.epistemic_share == pytest.approx(0.25)

    def test_zero_variance_is_degenerate_not_certain(self):
        value = decomposition(aleatoric=0.0, epistemic=0.0)
        assert value.is_degenerate is True
        # A zero-variance ensemble is a broken ensemble, and the shares do not
        # fabricate a split.
        assert value.aleatoric_share == pytest.approx(0.0)
        assert value.epistemic_share == pytest.approx(0.0)

    def test_standard_deviations_are_square_roots(self):
        value = decomposition(aleatoric=4.0, epistemic=9.0)
        assert value.aleatoric_std == pytest.approx(2.0)
        assert value.epistemic_std == pytest.approx(3.0)
        assert value.total_std == pytest.approx(math.sqrt(13.0))

    def test_serialises_to_json(self):
        json.dumps(decomposition(1.0, 2.0).to_dict(), allow_nan=False)


class TestDeepEnsemble:
    def test_members_with_variance_functions(self):
        members = [StubMember(1.0, 0.5), StubMember(3.0, 0.5)]
        ensemble = DeepEnsemble(
            members, member_variance_fn=lambda member, X: np.full(len(X), member.variance)
        )
        results = ensemble.decompose(np.zeros((2, 1)))

        assert len(results) == 2
        assert results[0].mean == pytest.approx(2.0)
        assert results[0].aleatoric == pytest.approx(0.5)
        assert results[0].epistemic == pytest.approx(2.0)  # var([1, 3], ddof=1) = 2
        assert results[0].n_members == 2

    def test_residual_calibration_supplies_the_aleatoric_term(self):
        members = [StubMember(1.0), StubMember(3.0)]
        ensemble = DeepEnsemble(members)

        rng = np.random.default_rng(20260403)
        X = np.zeros((500, 1))
        # Truth centred on the ensemble mean with known noise variance.
        y = 2.0 + rng.normal(scale=2.0, size=500)

        variance = ensemble.calibrate_residual_variance(X, y)
        assert variance == pytest.approx(4.0, rel=0.2)

        result = ensemble.decompose_one(np.zeros((1, 1)))
        assert result.aleatoric == pytest.approx(4.0, rel=0.2)
        assert result.epistemic == pytest.approx(2.0)
        assert result.method == "ensemble_with_calibrated_residual_variance"

    def test_without_variance_information_aleatoric_is_zero(self):
        ensemble = DeepEnsemble([StubMember(1.0), StubMember(2.0)])
        result = ensemble.decompose_one(np.zeros((1, 1)))
        assert result.aleatoric == pytest.approx(0.0)
        assert result.epistemic > 0

    def test_predict_mean(self):
        ensemble = DeepEnsemble([StubMember(1.0), StubMember(3.0)])
        assert np.allclose(ensemble.predict_mean(np.zeros((3, 1))), 2.0)

    def test_validation(self):
        with pytest.raises(ValueError, match="at least one member"):
            DeepEnsemble([])
        with pytest.raises(ValueError, match="at least two members"):
            DeepEnsemble([StubMember(1.0)], ddof=1)
        with pytest.raises(ValueError, match="ddof"):
            DeepEnsemble([StubMember(1.0), StubMember(2.0)], ddof=3)
        with pytest.raises(TypeError, match="predict"):
            DeepEnsemble([object(), object()])

    def test_calibration_length_mismatch_is_rejected(self):
        ensemble = DeepEnsemble([StubMember(1.0), StubMember(2.0)])
        with pytest.raises(ValueError, match="entries"):
            ensemble.calibrate_residual_variance(np.zeros((3, 1)), [1.0, 2.0])

    def test_inconsistent_member_output_lengths_are_rejected(self):
        class OddMember:
            def predict(self, X):
                return np.zeros(3)

        ensemble = DeepEnsemble([StubMember(1.0), OddMember()])
        with pytest.raises(ValueError, match="inconsistent"):
            ensemble.decompose(np.zeros((2, 1)))

    def test_decompose_one_rejects_multiple_rows(self):
        ensemble = DeepEnsemble([StubMember(1.0), StubMember(2.0)])
        with pytest.raises(ValueError, match="exactly one row"):
            ensemble.decompose_one(np.zeros((3, 1)))

    def test_more_disagreement_means_more_epistemic_uncertainty(self):
        tight = DeepEnsemble([StubMember(1.0), StubMember(1.1)]).decompose_one(np.zeros((1, 1)))
        loose = DeepEnsemble([StubMember(0.0), StubMember(9.0)]).decompose_one(np.zeros((1, 1)))
        assert loose.epistemic > tight.epistemic


class TestEpistemicReference:
    def test_threshold_is_the_empirical_quantile(self):
        values = list(range(1, 101))
        reference = EpistemicReference(values, level=0.9)
        assert reference.threshold == pytest.approx(91.0)

    def test_spike_detection(self):
        reference = EpistemicReference(list(range(1, 101)), level=0.9)
        assert reference.assess(5.0)["spiked"] is False
        assert reference.assess(500.0)["spiked"] is True
        assert reference.assess(500.0)["ratio"] > 1.0

    def test_single_value_reference_is_flagged_as_uncalibratable(self):
        reference = EpistemicReference([2.0], level=0.9)
        assert reference.is_calibratable is False
        assert reference.assess(1.9)["calibratable"] is False

    def test_validation(self):
        with pytest.raises(ValueError, match="at least one"):
            EpistemicReference([])
        with pytest.raises(ValueError, match="non-finite"):
            EpistemicReference([1.0, float("nan")])
        with pytest.raises(ValueError, match="negative"):
            EpistemicReference([1.0, -1.0])
        with pytest.raises(ValueError, match="level"):
            EpistemicReference([1.0], level=0.0)

        reference = EpistemicReference([1.0, 2.0])
        with pytest.raises(ValueError, match="non-negative"):
            reference.assess(-0.5)
        with pytest.raises(ValueError, match="non-negative"):
            reference.assess(float("nan"))


class TestAssessUncertainty:
    def _reference(self):
        return EpistemicReference(list(np.linspace(0.01, 1.0, 200)), level=0.99)

    def test_a_calm_prediction_is_reliable(self):
        assessment = assess_uncertainty(decomposition(aleatoric=1.0, epistemic=0.05))
        assert assessment.reliable is True
        assert assessment.reasons == []
        assert "reliable" in assessment.summary()

    def test_an_epistemic_spike_flags_unreliable(self):
        assessment = assess_uncertainty(
            decomposition(aleatoric=0.1, epistemic=50.0), self._reference()
        )
        assert assessment.reliable is False
        assert assessment.epistemic_spiked is True
        assert any("extrapolating" in reason for reason in assessment.reasons)

    def test_a_large_aleatoric_term_does_not_by_itself_flag(self):
        """The operational point of the decomposition.

        Genuine market turbulence makes the interval wide, but the model is not
        ignorant -- it is reporting a noisy world. Flagging that as model failure
        would make the signal useless exactly when it matters.
        """
        assessment = assess_uncertainty(
            decomposition(aleatoric=50.0, epistemic=0.01), self._reference()
        )
        assert assessment.epistemic_spiked is False
        assert assessment.reliable is True

    def test_max_epistemic_share_flags_model_ignorance(self):
        assessment = assess_uncertainty(
            decomposition(aleatoric=1.0, epistemic=9.0), max_epistemic_share=0.5
        )
        assert assessment.reliable is False
        assert any("model ignorance" in reason for reason in assessment.reasons)

    def test_epistemic_share_below_the_ceiling_passes(self):
        assessment = assess_uncertainty(
            decomposition(aleatoric=9.0, epistemic=1.0), max_epistemic_share=0.5
        )
        assert assessment.reliable is True

    def test_missing_reference_is_a_silent_skip_by_default(self):
        assessment = assess_uncertainty(decomposition(1.0, 0.1))
        assert assessment.reliable is True
        assert assessment.epistemic_check == {}

    def test_missing_reference_blocks_when_required(self):
        assessment = assess_uncertainty(
            decomposition(1.0, 0.1), None, require_epistemic_reference=True
        )
        assert assessment.reliable is False
        assert any("could not be tested" in reason for reason in assessment.reasons)

    def test_zero_variance_is_flagged_as_a_broken_ensemble(self):
        assessment = assess_uncertainty(decomposition(0.0, 0.0))
        assert assessment.reliable is False
        assert any("exactly zero" in reason for reason in assessment.reasons)

    def test_non_finite_variance_is_flagged(self):
        assessment = assess_uncertainty(decomposition(float("nan"), 1.0))
        assert assessment.reliable is False
        assert any("non-finite" in reason for reason in assessment.reasons)

    def test_multiple_reasons_accumulate(self):
        assessment = assess_uncertainty(
            decomposition(aleatoric=1.0, epistemic=50.0),
            self._reference(),
            max_epistemic_share=0.05,
        )
        assert assessment.reliable is False
        assert len(assessment.reasons) >= 2

    def test_invalid_share_ceiling_is_rejected(self):
        with pytest.raises(ValueError, match="max_epistemic_share"):
            assess_uncertainty(decomposition(1.0, 1.0), max_epistemic_share=1.5)

    def test_serialises_to_json(self):
        json.dumps(
            assess_uncertainty(decomposition(1.0, 0.5), self._reference()).to_dict(),
            allow_nan=False,
        )

    def test_summary_names_the_reason(self):
        assessment = assess_uncertainty(
            decomposition(aleatoric=0.1, epistemic=50.0), self._reference()
        )
        assert "flagged unreliable" in assessment.summary()
        assert "epistemic" in assessment.summary()


class TestEndToEnd:
    def test_ensemble_to_verdict(self):
        """The full path: members, calibration, decomposition, verdict."""
        rng = np.random.default_rng(20260404)

        # Three members that agree closely, plus a noise floor.
        members = [StubMember(value) for value in (1.0, 1.1, 0.9)]
        ensemble = DeepEnsemble(
            members, member_variance_fn=lambda member, X: np.full(len(X), 0.25)
        )

        X = np.zeros((200, 1))
        y = 1.0 + rng.normal(scale=0.5, size=200)
        ensemble.calibrate_residual_variance(X, y)

        # Reference built from the ensemble's own validation-time epistemic spread.
        validation_epistemic = [
            ensemble.decompose_one(np.zeros((1, 1))).epistemic for _ in range(50)
        ]
        reference = EpistemicReference(validation_epistemic, level=0.99)

        calm = assess_uncertainty(ensemble.decompose_one(np.zeros((1, 1))), reference)
        assert calm.reliable is True

        # A badly disagreeing ensemble should be flagged.
        divided = DeepEnsemble(
            [StubMember(0.0), StubMember(10.0), StubMember(20.0)],
            member_variance_fn=lambda member, X: np.full(len(X), 0.25),
        )
        alerted = assess_uncertainty(
            divided.decompose_one(np.zeros((1, 1))), reference
        )
        assert alerted.reliable is False
        assert alerted.epistemic_spiked is True
