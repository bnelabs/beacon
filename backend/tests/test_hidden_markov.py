"""Tests for the Gaussian-emission hidden Markov regime model.

These lock in the properties that make ``GaussianHMM`` usable as the estimator
behind the network attestation gate's ``known_regimes`` tuple. The gate fails
closed on an unseen regime label, so the estimator must be stable (no ``-inf``
log-likelihoods), reproducible (a label cannot depend on which random restart
won), and its state integers must not leak into the label -- EM's label-switching
symmetry means the integer a state receives is arbitrary and so cannot be the
regime identity.

The central test is EM monotonicity. Baum-Welch increases the likelihood at
every iteration *given a correct E-step and M-step*; a wrong ``xi``, a missing
normalisation, or the wrong denominator in the transition update all break that,
and they break it by small amounts long before the final answer looks wrong. So
the whole history is asserted term-by-term rather than only comparing the first
and last entries.

Every test seeds ``numpy`` explicitly. No test depends on wall-clock time or on
the order pytest happens to run them in.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from backend.modules.engine.hidden_markov import (
    DEFAULT_REGIME_LABELS,
    GaussianHMM,
    label_states,
    order_states_by_volatility,
)

# Fixed seeds, so a failure is a failure of the code rather than of a draw.
FIT_SEED = 20260101

TWO_STATE_TRANSITION = np.array([[0.95, 0.05], [0.05, 0.95]])
THREE_STATE_TRANSITION = np.array(
    [
        [0.90, 0.07, 0.03],
        [0.06, 0.88, 0.06],
        [0.03, 0.09, 0.88],
    ]
)


def _as_state_matrix(values) -> np.ndarray:
    """``(n_states,)`` becomes ``(n_states, 1)``; ``(n_states, n_features)`` stays."""
    array = np.asarray(values, dtype=float)
    return array.reshape(-1, 1) if array.ndim == 1 else array


def sample_hmm(
    seed: int,
    n_observations: int,
    means,
    variances,
    transition,
    initial=None,
):
    """Draw ``(observations, hidden_states)`` from a known Gaussian HMM.

    Written from the generative definition so the model is tested against data
    whose truth is known independently of the estimator.
    """
    mean_matrix = _as_state_matrix(means)
    variance_matrix = _as_state_matrix(variances)
    n_states = mean_matrix.shape[0]

    transition = np.asarray(transition, dtype=float)
    if initial is None:
        initial = np.full(n_states, 1.0 / n_states)
    initial = np.asarray(initial, dtype=float)

    rng = np.random.default_rng(seed)
    states = np.empty(n_observations, dtype=int)
    states[0] = rng.choice(n_states, p=initial)
    for step in range(1, n_observations):
        states[step] = rng.choice(n_states, p=transition[states[step - 1]])

    observations = rng.normal(
        loc=mean_matrix[states], scale=np.sqrt(variance_matrix[states])
    )
    return observations, states


def two_state_data(seed: int = 11, n_observations: int = 2000):
    """Well-separated two-state data: means -3 / +3, unit variance."""
    return sample_hmm(
        seed,
        n_observations,
        means=[-3.0, 3.0],
        variances=[1.0, 1.0],
        transition=TWO_STATE_TRANSITION,
    )


def mapping_accuracy(path: np.ndarray, truth: np.ndarray) -> float:
    """Agreement after relabelling each fitted state by its majority true state.

    The hidden state indices carry no meaning, so accuracy is only defined up to
    a permutation. Mapping by majority is the lenient, standard convention.
    """
    mapping = {}
    for state in np.unique(path):
        values, counts = np.unique(truth[path == state], return_counts=True)
        mapping[int(state)] = int(values[int(np.argmax(counts))])
    predicted = np.array([mapping[int(state)] for state in path])
    return float(np.mean(predicted == truth))


class TestEMMonotonicity:
    """Baum-Welch must never lower the likelihood from one iteration to the next."""

    @pytest.mark.parametrize("data_seed", [0, 1, 2, 3, 4])
    def test_two_state_history_is_term_by_term_non_decreasing(self, data_seed):
        observations, _ = two_state_data(seed=data_seed, n_observations=800)

        model = GaussianHMM(2, seed=data_seed)
        history = model.fit(
            observations, max_iterations=120, tolerance=1e-12
        )

        assert len(history) >= 4, "the trajectory is too short to test monotonicity"
        assert all(np.isfinite(history))
        increments = np.diff(history)
        # Term-by-term, not first-versus-last. The tolerance is absolute and
        # tiny; a genuine E-step or M-step error produces drops far larger than
        # this, while floating-point round-off stays at or below it.
        assert np.all(increments >= -1e-9), (
            f"log-likelihood decreased between iterations: min increment "
            f"{float(increments.min()):.3e}"
        )

    def test_three_state_history_is_monotonic(self):
        observations, _ = sample_hmm(
            22,
            3000,
            means=[-4.0, 0.0, 4.0],
            variances=[0.5, 1.0, 2.0],
            transition=THREE_STATE_TRANSITION,
        )
        model = GaussianHMM(3, seed=FIT_SEED)
        history = model.fit(observations, max_iterations=200, tolerance=1e-12)

        assert len(history) >= 4
        assert np.all(np.diff(history) >= -1e-9)

    def test_multivariate_history_is_monotonic(self):
        observations, _ = sample_hmm(
            33,
            1500,
            means=[[-2.0, 0.0, 1.0], [2.0, -1.0, -2.0]],
            variances=[[1.0, 1.0, 1.0], [2.0, 2.0, 2.0]],
            transition=TWO_STATE_TRANSITION,
        )
        model = GaussianHMM(2, n_features=3, seed=FIT_SEED)
        history = model.fit(observations, max_iterations=150, tolerance=1e-12)

        assert len(history) >= 4
        assert np.all(np.diff(history) >= -1e-9)

    def test_final_history_entry_matches_log_likelihood_of_returned_parameters(self):
        # _fit_once scores the returned parameters exactly once, after the EM
        # loop, so the last entry must be the likelihood of precisely those
        # parameters. The entries before it are the likelihoods that *entered*
        # each M-step -- the E-step's own forward normalisers, which is what
        # makes the second per-iteration forward pass unnecessary. If a future
        # change dropped the final score, or scored a stale parameter set, this
        # would drift.
        observations, _ = two_state_data(seed=5, n_observations=1000)
        model = GaussianHMM(2, seed=FIT_SEED)
        history = model.fit(observations, max_iterations=150, tolerance=1e-12)

        assert history[-1] == pytest.approx(
            model.log_likelihood(observations), rel=1e-12
        )


class TestParameterRecovery:
    """Fit known data and check the fitted parameters match the truth."""

    def test_two_state_means_variances_and_transition_recovered(self):
        observations, _ = two_state_data(seed=11, n_observations=2000)
        model = GaussianHMM(2, seed=FIT_SEED)
        model.fit(observations, max_iterations=200, tolerance=1e-10)

        fitted_means = np.sort(model.means.ravel())
        assert fitted_means == pytest.approx([-3.0, 3.0], abs=0.15)

        fitted_variances = np.sort(model.variances.ravel())
        assert fitted_variances == pytest.approx([1.0, 1.0], abs=0.1)

        # The state indices are arbitrary, so match the transition matrix by
        # ordering states by mean, which is the truth's own ordering.
        order = np.argsort(model.means.ravel())
        reordered = model.transition[np.ix_(order, order)]
        assert reordered == pytest.approx(TWO_STATE_TRANSITION, abs=0.05)

        assert model.transition.sum(axis=1) == pytest.approx(np.ones(2), abs=1e-12)
        assert model.initial.sum() == pytest.approx(1.0, abs=1e-9)

    def test_three_state_means_variances_and_transition_recovered(self):
        observations, _ = sample_hmm(
            22,
            3000,
            means=[-4.0, 0.0, 4.0],
            variances=[0.5, 1.0, 2.0],
            transition=THREE_STATE_TRANSITION,
        )
        model = GaussianHMM(3, seed=FIT_SEED)
        model.fit(observations, max_iterations=300, tolerance=1e-10)

        order = np.argsort(model.means.ravel())
        assert np.sort(model.means.ravel()) == pytest.approx(
            [-4.0, 0.0, 4.0], abs=0.15
        )
        assert model.variances.ravel()[order] == pytest.approx(
            [0.5, 1.0, 2.0], abs=0.2
        )

        reordered = model.transition[np.ix_(order, order)]
        assert reordered == pytest.approx(THREE_STATE_TRANSITION, abs=0.05)


class TestViterbi:
    def test_viterbi_path_recovers_the_true_states(self):
        observations, truth = two_state_data(seed=11, n_observations=2000)
        model = GaussianHMM(2, seed=FIT_SEED)
        model.fit(observations, max_iterations=200, tolerance=1e-10)

        path = model.viterbi(observations)

        assert path.shape == (observations.shape[0],)
        assert path.dtype.kind in "iu"
        assert set(np.unique(path).tolist()) <= {0, 1}
        assert mapping_accuracy(path, truth) >= 0.95

    def test_viterbi_recovers_states_on_three_separated_states(self):
        observations, truth = sample_hmm(
            22,
            3000,
            means=[-4.0, 0.0, 4.0],
            variances=[0.5, 1.0, 2.0],
            transition=THREE_STATE_TRANSITION,
        )
        model = GaussianHMM(3, seed=FIT_SEED)
        model.fit(observations, max_iterations=300, tolerance=1e-10)

        assert mapping_accuracy(model.viterbi(observations), truth) >= 0.95

    def test_predict_is_an_alias_for_viterbi(self):
        observations, _ = two_state_data(seed=11, n_observations=500)
        model = GaussianHMM(2, seed=FIT_SEED)
        model.fit(observations, max_iterations=100, tolerance=1e-9)

        assert np.array_equal(model.predict(observations), model.viterbi(observations))


class TestPosteriors:
    def test_shape_bounds_and_row_normalisation(self):
        observations, _ = two_state_data(seed=11, n_observations=2000)
        model = GaussianHMM(2, seed=FIT_SEED)
        model.fit(observations, max_iterations=200, tolerance=1e-10)

        posteriors = model.posteriors(observations)

        assert posteriors.shape == (observations.shape[0], 2)
        assert np.all(np.isfinite(posteriors))
        assert np.all(posteriors >= 0.0) and np.all(posteriors <= 1.0)
        assert np.allclose(posteriors.sum(axis=1), 1.0, atol=1e-9)

    def test_posterior_argmax_agrees_with_viterbi_for_the_majority(self):
        observations, _ = two_state_data(seed=11, n_observations=2000)
        model = GaussianHMM(2, seed=FIT_SEED)
        model.fit(observations, max_iterations=200, tolerance=1e-10)

        agreement = np.mean(
            model.posteriors(observations).argmax(axis=1) == model.viterbi(observations)
        )
        assert agreement >= 0.9


class TestNumericalStability:
    def test_long_sequence_log_likelihood_is_finite(self):
        # The regression test for the scaled/log-space forward pass. A naive
        # product of transition and emission probabilities underflows to zero
        # long before T = 5000 and returns -inf here.
        observations, _ = two_state_data(seed=33, n_observations=5000)
        model = GaussianHMM(2, seed=FIT_SEED)
        history = model.fit(observations, max_iterations=60, tolerance=1e-8)

        likelihood = model.log_likelihood(observations)
        assert np.isfinite(likelihood)
        assert not np.isnan(likelihood)
        assert all(np.isfinite(history))

        posteriors = model.posteriors(observations)
        assert np.all(np.isfinite(posteriors))
        assert np.allclose(posteriors.sum(axis=1), 1.0, atol=1e-9)

    def test_variance_floor_protects_a_degenerate_state(self):
        # Every observation identical: the maximum-likelihood variance is zero,
        # which would send the likelihood to infinity without the floor.
        observations = np.zeros((50, 1))
        floor = 1e-6
        model = GaussianHMM(2, seed=FIT_SEED, variance_floor=floor)
        history = model.fit(observations, max_iterations=30, tolerance=1e-12)

        assert np.all(model.variances >= floor)
        assert all(np.isfinite(history))
        assert np.isfinite(model.log_likelihood(observations))
        assert np.all(np.isfinite(model.posteriors(observations)))

    def test_a_larger_floor_is_respected(self):
        observations = np.zeros((40, 1))
        floor = 0.25
        model = GaussianHMM(2, seed=FIT_SEED, variance_floor=floor)
        model.fit(observations, max_iterations=30, tolerance=1e-12)

        assert np.all(model.variances >= floor)


class TestMultivariate:
    def test_three_feature_model_has_correct_shapes_and_finite_likelihood(self):
        observations, _ = sample_hmm(
            33,
            1500,
            means=[[-2.0, 0.0, 1.0], [2.0, -1.0, -2.0]],
            variances=[[1.0, 1.0, 1.0], [2.0, 2.0, 2.0]],
            transition=TWO_STATE_TRANSITION,
        )
        model = GaussianHMM(2, n_features=3, seed=FIT_SEED)
        model.fit(observations, max_iterations=150, tolerance=1e-10)

        assert model.means.shape == (2, 3)
        assert model.variances.shape == (2, 3)
        assert model.transition.shape == (2, 2)
        assert np.isfinite(model.log_likelihood(observations))

        posteriors = model.posteriors(observations)
        assert posteriors.shape == (observations.shape[0], 2)
        assert np.allclose(posteriors.sum(axis=1), 1.0, atol=1e-9)

    def test_multivariate_viterbi_has_valid_state_indices(self):
        observations, _ = sample_hmm(
            33,
            600,
            means=[[-2.0, 0.0, 1.0], [2.0, -1.0, -2.0]],
            variances=[[1.0, 1.0, 1.0], [2.0, 2.0, 2.0]],
            transition=TWO_STATE_TRANSITION,
        )
        model = GaussianHMM(2, n_features=3, seed=FIT_SEED)
        model.fit(observations, max_iterations=100, tolerance=1e-9)

        path = model.viterbi(observations)
        assert path.shape == (observations.shape[0],)
        assert set(np.unique(path).tolist()) <= {0, 1}


class TestDeterminismAndRestarts:
    def test_same_seed_reproduces_the_same_fit_exactly(self):
        observations, _ = two_state_data(seed=44, n_observations=800)

        first = GaussianHMM(2, seed=99)
        first_history = first.fit(
            observations, max_iterations=60, tolerance=1e-9, n_restarts=3
        )
        second = GaussianHMM(2, seed=99)
        second_history = second.fit(
            observations, max_iterations=60, tolerance=1e-9, n_restarts=3
        )

        assert first_history == second_history
        assert np.array_equal(first.means, second.means)
        assert np.array_equal(first.variances, second.variances)
        assert np.array_equal(first.transition, second.transition)
        assert np.array_equal(first.initial, second.initial)
        assert first.restart_log_likelihoods == second.restart_log_likelihoods

    def test_different_seeds_are_permitted_to_differ(self):
        # Not a correctness claim about the fit, only evidence that the seed is
        # actually plumbed through rather than ignored.
        observations, _ = sample_hmm(
            55,
            400,
            means=[-3.0, 3.0],
            variances=[1.0, 1.0],
            transition=TWO_STATE_TRANSITION,
        )
        first = GaussianHMM(4, seed=1)
        first.fit(observations, max_iterations=25, tolerance=1e-12, n_restarts=3)
        second = GaussianHMM(4, seed=2)
        second.fit(observations, max_iterations=25, tolerance=1e-12, n_restarts=3)

        assert first.restart_log_likelihoods != second.restart_log_likelihoods

    def test_best_restart_is_retained_rather_than_the_last(self):
        # A deliberately over-specified model (four states on two-state data)
        # has a rough likelihood surface, so restarts land on genuinely
        # different optima. That makes best-of selection observable: if the
        # implementation kept the last restart, or the first, these assertions
        # would fail rather than pass vacuously.
        observations, _ = sample_hmm(
            2024,
            400,
            means=[-3.0, 3.0],
            variances=[1.0, 1.0],
            transition=TWO_STATE_TRANSITION,
        )

        single_model = GaussianHMM(4, seed=0)
        single_history = single_model.fit(
            observations, max_iterations=30, tolerance=1e-12, n_restarts=1
        )
        multi_model = GaussianHMM(4, seed=0)
        multi_history = multi_model.fit(
            observations, max_iterations=30, tolerance=1e-12, n_restarts=6
        )

        finals = multi_model.restart_log_likelihoods
        assert len(finals) == 6

        # The first restart of an n_restarts run draws from the same stream as a
        # one-restart run, so it must reproduce it exactly. This is what makes
        # the comparison below meaningful rather than two unrelated fits.
        assert finals[0] == pytest.approx(single_history[-1], rel=1e-12)

        # The retained history is the best restart's, not the last one's.
        assert multi_history[-1] == pytest.approx(max(finals), rel=1e-12)
        assert multi_model.log_likelihood_history == multi_history

        # And on this surface the best restart beats the first and the last, so
        # the selection step changed the answer.
        assert multi_history[-1] > single_history[-1] + 1e-6
        assert len({round(value, 9) for value in finals}) >= 2


class TestLabelling:
    def test_order_is_by_average_variance_not_by_integer_index(self):
        means = np.array([[5.0], [1.0], [-2.0], [0.5]])
        variances = np.array([[9.0], [2.0], [0.25], [4.0]])

        order = order_states_by_volatility(means, variances)

        assert order.tolist() == [2, 1, 3, 0]

    def test_labels_follow_variance_rank_for_scrambled_indices(self):
        means = np.array([[5.0], [1.0], [-2.0], [0.5]])
        variances = np.array([[9.0], [2.0], [0.25], [4.0]])

        labels = label_states(means, variances)

        assert labels[2] == "calm"  # lowest variance, index 2
        assert labels[1] == "elevated"
        assert labels[3] == "stressed"
        assert labels[0] == "crisis"  # highest variance, index 0
        assert set(labels.values()) == set(DEFAULT_REGIME_LABELS)

    def test_labelling_is_deterministic(self):
        means = np.array([[5.0], [1.0], [-2.0], [0.5]])
        variances = np.array([[9.0], [2.0], [0.25], [4.0]])

        assert label_states(means, variances) == label_states(means, variances)

    def test_fewer_states_than_labels_keeps_the_extremes(self):
        # Two states over the default four labels must still reach "crisis" at
        # the top; truncating the tuple would label the most volatile state
        # "elevated" and the gate would never see a crisis.
        two_state_labels = label_states(
            np.array([[5.0], [1.0]]), np.array([[9.0], [0.25]])
        )
        assert two_state_labels[1] == "calm"
        assert two_state_labels[0] == "crisis"

        three_state_labels = label_states(
            np.array([[5.0], [1.0], [-2.0]]), np.array([[9.0], [2.0], [0.25]])
        )
        assert three_state_labels[2] == "calm"
        assert three_state_labels[0] == "crisis"

    def test_custom_labels_are_used(self):
        labels = label_states(
            np.array([[5.0], [1.0]]),
            np.array([[9.0], [0.25]]),
            labels=("quiet", "loud"),
        )
        assert labels == {1: "quiet", 0: "loud"}

    def test_too_few_labels_is_rejected(self):
        with pytest.raises(ValueError, match="labels"):
            label_states(
                np.array([[5.0], [1.0], [-2.0]]),
                np.array([[9.0], [2.0], [0.25]]),
                labels=("only_one",),
            )

    def test_empty_labels_is_rejected(self):
        with pytest.raises(ValueError, match="labels"):
            label_states(
                np.array([[5.0], [1.0]]), np.array([[9.0], [0.25]]), labels=()
            )


class TestValidation:
    @pytest.mark.parametrize(
        "kwargs, message",
        [
            ({"n_states": 0}, "n_states"),
            ({"n_states": -3}, "n_states"),
            ({"n_states": 2, "n_features": 0}, "n_features"),
            ({"n_states": 2, "variance_floor": 0.0}, "variance_floor"),
            ({"n_states": 2, "variance_floor": -1e-6}, "variance_floor"),
        ],
    )
    def test_constructor_rejects_invalid_settings(self, kwargs, message):
        with pytest.raises(ValueError, match=message):
            GaussianHMM(**kwargs)

    def test_fit_rejects_wrong_number_of_columns(self):
        model = GaussianHMM(2, n_features=2)
        with pytest.raises(ValueError, match="feature column"):
            model.fit(np.zeros((10, 3)))

    def test_fit_rejects_empty_observations(self):
        model = GaussianHMM(2)
        with pytest.raises(ValueError, match="empty"):
            model.fit(np.empty((0, 1)))

    @pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
    def test_fit_rejects_non_finite_observations(self, bad):
        model = GaussianHMM(2)
        observations = np.zeros((10, 1))
        observations[3, 0] = bad
        with pytest.raises(ValueError, match="non-finite"):
            model.fit(observations)

    @pytest.mark.parametrize(
        "controls, message",
        [
            ({"n_restarts": 0}, "n_restarts"),
            ({"n_restarts": -2}, "n_restarts"),
            ({"max_iterations": 0}, "max_iterations"),
            ({"tolerance": 0.0}, "tolerance"),
            ({"tolerance": -1e-6}, "tolerance"),
        ],
    )
    def test_fit_rejects_invalid_controls(self, controls, message):
        model = GaussianHMM(2)
        with pytest.raises(ValueError, match=message):
            model.fit(np.zeros((10, 1)), **controls)

    @pytest.mark.parametrize(
        "method", ["posteriors", "viterbi", "predict", "log_likelihood"]
    )
    def test_inference_before_fit_is_rejected(self, method):
        model = GaussianHMM(2)
        with pytest.raises(ValueError, match="not fitted"):
            getattr(model, method)(np.zeros((5, 1)))

    def test_to_dict_before_fit_is_rejected(self):
        with pytest.raises(ValueError, match="not fitted"):
            GaussianHMM(2).to_dict()

    def test_state_accessors_before_fit_are_rejected(self):
        model = GaussianHMM(2)
        with pytest.raises(ValueError, match="not fitted"):
            model.state_means()
        with pytest.raises(ValueError, match="not fitted"):
            model.state_variances()

    def test_order_states_rejects_one_dimensional_parameters(self):
        with pytest.raises(ValueError, match="2-D"):
            order_states_by_volatility(np.zeros(3), np.zeros(3))

    def test_order_states_rejects_mismatched_shapes(self):
        with pytest.raises(ValueError, match="same shape"):
            order_states_by_volatility(np.zeros((3, 1)), np.zeros((2, 1)))

    def test_order_states_rejects_non_finite_parameters(self):
        means = np.array([[0.0], [1.0]])
        variances = np.array([[1.0], [np.nan]])
        with pytest.raises(ValueError, match="non-finite"):
            order_states_by_volatility(means, variances)

    def test_order_states_rejects_negative_variances(self):
        with pytest.raises(ValueError, match="non-negative"):
            order_states_by_volatility(
                np.array([[0.0], [1.0]]), np.array([[1.0], [-0.5]])
            )


class TestSerialisation:
    def test_to_dict_round_trips_through_json_without_numpy_scalars(self):
        observations, _ = two_state_data(seed=11, n_observations=800)
        model = GaussianHMM(2, seed=FIT_SEED)
        model.fit(observations, max_iterations=100, tolerance=1e-9)

        payload = model.to_dict()
        encoded = json.dumps(payload, allow_nan=False)
        decoded = json.loads(encoded)

        assert decoded["n_states"] == 2
        assert decoded["n_features"] == 1
        assert np.asarray(decoded["means"]) == pytest.approx(model.means)
        assert np.asarray(decoded["variances"]) == pytest.approx(model.variances)
        assert np.asarray(decoded["transition"]) == pytest.approx(model.transition)
        assert np.asarray(decoded["initial"]) == pytest.approx(model.initial)
        assert decoded["log_likelihood"] == pytest.approx(
            model.log_likelihood_history[-1]
        )
        assert decoded["fitted"] is True

        # Plain Python floats, so json.dumps cannot silently emit numpy reprs.
        assert all(type(value) is float for row in payload["means"] for value in row)
        assert all(
            type(value) is float for row in payload["variances"] for value in row
        )
        assert all(
            type(value) is float for row in payload["transition"] for value in row
        )
        assert all(type(value) is float for value in payload["initial"])
        assert all(
            type(value) is float for value in payload["log_likelihood_history"]
        )
        assert all(type(value) is int for value in payload["state_order"])


class TestEndToEnd:
    def test_estimated_labels_feed_the_regime_gate(self):
        observations, _ = two_state_data(seed=11, n_observations=2000)
        model = GaussianHMM(2, seed=FIT_SEED)
        model.fit(observations, max_iterations=200, tolerance=1e-10)

        series = model.label_series(observations)

        assert series.shape == (observations.shape[0],)
        assert set(series.tolist()) <= set(DEFAULT_REGIME_LABELS)

        # The series is exactly the Viterbi path under the deterministic
        # variance-ranked mapping -- not a second, different labelling rule.
        mapping = label_states(model.means, model.variances)
        expected = np.array([mapping[int(state)] for state in model.viterbi(observations)])
        assert np.array_equal(series, expected)

        # And the gate accepts every label the estimator produced when the
        # training regimes are declared, while still blocking an unseen one.
        from backend.modules.data.network_gate import NetworkQualityGate

        gate = NetworkQualityGate(known_regimes=DEFAULT_REGIME_LABELS)
        accepted = gate.evaluate(
            job_id="hmgm-end-to-end", regime_label=str(series[0])
        )
        assert accepted.verified

        blocked = gate.evaluate(job_id="hmgm-end-to-end", regime_label="meltdown")
        assert not blocked.verified

    def test_custom_labels_reach_the_series(self):
        observations, _ = two_state_data(seed=11, n_observations=800)
        model = GaussianHMM(2, seed=FIT_SEED)
        model.fit(observations, max_iterations=100, tolerance=1e-9)

        series = model.label_series(observations, labels=("quiet", "turbulent"))

        assert series.shape == (observations.shape[0],)
        assert set(series.tolist()) <= {"quiet", "turbulent"}


class TestEMIterationBookkeeping:
    """The EM loop must not pay for its own bookkeeping.

    ``_fit_once`` used to run a *second* forward pass after every M-step purely
    to record the updated parameters' likelihood, which put two forward passes
    and one backward pass in the innermost loop of the slowest module on the
    prediction path. The E-step's forward pass already returns the per-step
    normalisers, and their sum is ``log p(X)`` under the parameters that
    produced them, so the recorded likelihood is now free and the parameters are
    scored exactly once, after the loop.

    These tests pin the two halves of that trade: the invariant that survived
    (``history[-1]`` is the likelihood of the returned parameters) and the cost
    that was removed (forward passes per iteration must not grow with ``T``).
    """

    def test_e_step_normalisers_are_the_likelihood_of_the_incoming_parameters(self):
        # The identity the change rests on: sum(log_scale) from the E-step's own
        # forward pass equals an independent forward pass under the same
        # parameters. If this ever stops holding, the recorded history is no
        # longer a likelihood and the monotonicity tests lose their meaning.
        observations, _ = two_state_data(seed=17, n_observations=400)
        model = GaussianHMM(2, seed=FIT_SEED)
        model.fit(observations, max_iterations=10, tolerance=1e-12)

        data = model._as_observations(observations)
        log_emission = model._log_emission(data, model.means, model.variances)
        _, log_scale = model._forward(log_emission, model.initial, model.transition)

        assert float(np.sum(log_scale)) == pytest.approx(
            model.log_likelihood(observations), rel=1e-12
        )

    def test_one_forward_pass_per_iteration_plus_one_final_score(self):
        # The cost invariant, counted rather than timed so a loaded CI runner
        # cannot flake it. The E-step's forward pass returns the per-step
        # normalisers whose sum is log p(X) under the parameters that produced
        # them, so scoring the iteration needs no second pass. With E E-steps
        # the fit must call _forward exactly E + 1 times: once per E-step, plus
        # the single post-loop score of the parameters being returned.
        #
        # This is a genuine regression test -- the pre-fix loop scored after
        # every M-step as well and called _forward 2E + 1 times, so it fails on
        # the old code by construction.
        import types

        observations, _ = two_state_data(seed=37, n_observations=300)
        model = GaussianHMM(2, seed=FIT_SEED)

        calls = {"forward": 0}
        original = GaussianHMM._forward

        def counting_forward(self, *args, **kwargs):
            calls["forward"] += 1
            return original(self, *args, **kwargs)

        model._forward = types.MethodType(counting_forward, model)

        # The cap is not reached -- a converged EM produces an improvement of
        # exactly 0.0, which is below every positive tolerance -- so E is read
        # from the returned history rather than assumed. The assertion is the
        # relation between passes and E-steps, which is what actually regressed.
        max_iterations = 12
        history = model.fit(
            observations, max_iterations=max_iterations, tolerance=1e-14
        )
        e_steps = len(history) - 1  # the post-loop score is not an E-step

        assert 1 <= e_steps <= max_iterations
        assert calls["forward"] == e_steps + 1, (
            f"{calls['forward']} forward passes for {e_steps} E-steps; expected "
            f"{e_steps + 1}: one per E-step, whose normalisers already sum to "
            "log p(X), plus the single post-loop score of the parameters being "
            f"returned. The pre-fix loop re-scored after every M-step and made "
            f"{2 * e_steps + 1}."
        )

    def test_convergence_threshold_is_relative_to_the_objective_scale(self):
        # The objective is a log-likelihood summed over T observations, so its
        # magnitude grows with the series and with the units the data happens to
        # be expressed in. A fixed absolute threshold therefore means a
        # different stopping rule for every length and scale: on the production
        # Student-t nowcast (T=1000, objective of order -800) a 1e-6 absolute
        # test is a relative tolerance of ~1e-9, which the EM tail never
        # reaches. The threshold is now scaled by the objective.
        #
        # Honest scope, because this repository does not accept a claim that was
        # not reproduced: on every dataset tried the absolute test also
        # converged, so this is a latent-defect fix and NOT the source of the
        # measured speedup -- that is the forward pass above. What is asserted
        # here is the property, not a win: the improvement that ends the loop
        # must lie inside the scale-relative band, and the same data expressed
        # in different units must not change the iteration count by more than
        # the one-iteration lag the recorded trajectory can carry.
        observations, _ = two_state_data(seed=23, n_observations=4000)

        def fit_scaled(scale: float) -> tuple:
            model = GaussianHMM(2, seed=FIT_SEED)
            history = model.fit(
                observations * scale, max_iterations=200, tolerance=1e-6
            )
            entering = np.asarray(history[:-1], dtype=float)
            return len(entering), float(entering[-1] - entering[-2]), float(
                entering[-1]
            )

        e_steps, improvement, objective = fit_scaled(1.0)
        assert e_steps < 200, (
            "the fit ran to the cap: the convergence test never fired"
        )
        assert improvement < 1e-6 * max(1.0, abs(objective)), (
            f"the loop ended on an improvement of {improvement:.3e}, outside the "
            f"scale-relative band {1e-6 * max(1.0, abs(objective)):.3e}"
        )

        # Same data, different units (e.g. percent vs basis points). Under an
        # absolute threshold the objective grows by log(1000) * T and the
        # stopping rule with it.
        scaled_steps, _, _ = fit_scaled(1000.0)
        assert abs(scaled_steps - e_steps) <= 1, (
            f"rescaling the data changed the iteration count from {e_steps} to "
            f"{scaled_steps}: the convergence test is still scale-dependent"
        )

    def test_a_converged_fit_stops_before_the_iteration_cap(self):
        # The companion to the test above: with a tolerance the EM tail can
        # actually reach, the cap is not the thing that ends the loop.
        observations, _ = two_state_data(seed=29, n_observations=600)
        model = GaussianHMM(2, seed=FIT_SEED)
        history = model.fit(observations, max_iterations=500, tolerance=1e-4)

        # One entry per iteration run, plus the single post-loop score.
        assert len(history) < 500, "the fit ran to the cap despite a loose tolerance"
        assert history[-1] == pytest.approx(
            model.log_likelihood(observations), rel=1e-12
        )
        assert np.all(np.diff(history) >= -1e-9)
