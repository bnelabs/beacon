"""Tests for the Student-t hidden Markov regime model.

The class exists to fix one specific, directional failure of the Gaussian model:
it under-assigns probability to extreme observations, so the state that should
light up in a crisis does not. A test that merely checked "it runs" would not
distinguish the fix from a reparameterisation, so the central tests are written
against *independent* routes to the same quantity:

* the univariate density against ``scipy.stats.t``, which is a different
  implementation of the same closed form;
* the multivariate density against numerical integration of its own definition
  as a Gaussian scale mixture -- this is the only check available on the
  normalising constant when there is more than one feature;
* the fitted model against ``scipy.stats.t.fit``, an independent optimiser for
  the one-state maximum-likelihood problem;
* the Gaussian limit, where the Student-t must reduce to ``GaussianHMM``;
* and the headline claim itself: on fat-tailed data the Student-t model must
  achieve a higher observed likelihood than the Gaussian model on the same data.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
from scipy.integrate import quad
from scipy.stats import gamma as gamma_distribution
from scipy.stats import multivariate_normal
from scipy.stats import t as student_t

from backend.modules.engine.hidden_markov import (
    GaussianHMM,
    StudentTHMM,
    label_states,
)


def two_regime_data(
    rng: np.random.Generator,
    *,
    n: int = 600,
    calm_scale: float = 0.5,
    crisis_scale: float = 4.0,
    df: float = 5.0,
    seed_df: float = 5.0,
) -> np.ndarray:
    """A two-state chain with Student-t emissions of very different scale."""
    transition = np.array([[0.97, 0.03], [0.10, 0.90]])
    state = 0
    values = np.empty(n, dtype=float)
    for step in range(n):
        state = int(rng.choice(2, p=transition[state]))
        scale = calm_scale if state == 0 else crisis_scale
        values[step] = student_t.rvs(
            df=seed_df, loc=0.0, scale=scale, random_state=rng
        )
    return values.reshape(-1, 1)


class TestDensityAgainstIndependentRoutes:
    """The emission log-density, checked three ways."""

    def test_univariate_density_matches_scipy(self):
        rng = np.random.default_rng(1)
        data = rng.normal(size=(60, 1))
        means = np.array([[0.3]])
        variances = np.array([[2.0]])
        for nu in (2.5, 4.0, 5.0, 30.0):
            model = StudentTHMM(
                1,
                degrees_of_freedom=nu,
                max_degrees_of_freedom=500.0,
            )
            ours = model._log_emission(data, means, variances)[:, 0]
            reference = student_t.logpdf(
                data[:, 0], df=nu, loc=0.3, scale=math.sqrt(2.0)
            )
            assert np.allclose(ours, reference, rtol=1e-10, atol=1e-10), nu

    def test_multivariate_density_matches_the_scale_mixture_definition(self):
        """d > 1 is not a product of univariate t densities.

        The features share a single latent scale ``u``, so the only honest check
        on the normalising constant is to integrate the defining mixture::

            p(x) = integral N(x; mu, Sigma / u) Gamma(u; nu/2, 2/nu) du
        """
        means = np.array([[0.4, -0.7]])
        variances = np.array([[1.3, 0.6]])
        nu = 4.5
        model = StudentTHMM(1, n_features=2, degrees_of_freedom=nu)

        for point in (np.array([[0.4, -0.7]]), np.array([[1.9, 0.2]])):
            def integrand(u: float) -> float:
                density = multivariate_normal.pdf(
                    point[0],
                    mean=means[0],
                    cov=np.diag(variances[0] / u),
                )
                return density * gamma_distribution.pdf(
                    u, a=nu / 2.0, scale=2.0 / nu
                )

            value, _ = quad(integrand, 1e-12, np.inf, limit=400)
            ours = model._log_emission(point, means, variances)[0, 0]
            assert ours == pytest.approx(math.log(value), rel=1e-6, abs=1e-9)

    def test_density_reduces_to_the_gaussian_at_large_degrees_of_freedom(self):
        rng = np.random.default_rng(2)
        data = rng.normal(size=(200, 1))
        means = np.array([[0.0]])
        variances = np.array([[1.0]])
        huge = StudentTHMM(
            1, degrees_of_freedom=1e9, max_degrees_of_freedom=1e9
        )
        gaussian = GaussianHMM(1)
        assert np.allclose(
            huge._log_emission(data, means, variances),
            gaussian._log_emission(data, means, variances),
            rtol=1e-6,
            atol=1e-6,
        )

    def test_the_default_upper_bound_is_close_to_the_gaussian(self):
        """At nu = 200 the gap is the expected O(1/nu), not a bug.

        Expanding both densities in 1/nu gives a pointwise gap of
        `(1/nu) * (delta^2/4 - delta/2 - 1/4)`, so the tolerance is stated as the
        magnitude that expansion actually predicts at the sample's largest
        deviation rather than as a number that happens to pass.
        """
        rng = np.random.default_rng(3)
        data = rng.normal(size=(200, 1))
        means = np.array([[0.0]])
        variances = np.array([[1.0]])
        # `degrees_of_freedom` is the *starting* value for a fit, so it must be set
        # explicitly here: the class default of 5 is a sensible initialisation for
        # fitting, not the Gaussian limit this test is about.
        at_bound = StudentTHMM(1, degrees_of_freedom=200.0)
        gaussian = GaussianHMM(1)

        delta = data**2
        predicted = (1.0 / 200.0) * (delta**2 / 4.0 - delta / 2.0 - 0.25)
        gap = np.abs(
            at_bound._log_emission(data, means, variances)
            - gaussian._log_emission(data, means, variances)
        )
        # Both the gap and its expansion are monotone in delta, so the largest
        # sample is also the one where the approximation is most severely tested.
        assert np.max(gap) == pytest.approx(float(np.max(np.abs(predicted))), rel=0.3)
        assert np.max(gap) < 0.2

    def test_an_extreme_observation_gets_more_mass_than_under_a_gaussian(self):
        """The entire reason the class exists, stated as one inequality."""
        means = np.array([[0.0]])
        variances = np.array([[1.0]])
        extreme = np.array([[6.0]])
        heavy = StudentTHMM(1, degrees_of_freedom=4.0)
        gaussian = GaussianHMM(1)
        heavy_logp = heavy._log_emission(extreme, means, variances)[0, 0]
        gaussian_logp = gaussian._log_emission(extreme, means, variances)[0, 0]
        assert heavy_logp > gaussian_logp
        # And not by a rounding-error margin: the tail mass differs by orders of
        # magnitude at six standard deviations.
        assert heavy_logp - gaussian_logp > 10.0

    def test_the_df_root_is_monotone_and_bracketed(self):
        from backend.modules.engine.hidden_markov import _student_t_df_residual

        values = [
            _student_t_df_residual(nu, target=-1.2131)
            for nu in (2.5, 5.0, 10.0, 50.0, 200.0)
        ]
        assert all(a > b for a, b in zip(values, values[1:]))
        assert _student_t_df_residual(5.0, -1.2131) == pytest.approx(0.0, abs=1e-3)


class TestFitting:
    def test_log_likelihood_history_is_non_decreasing(self):
        rng = np.random.default_rng(4)
        data = two_regime_data(rng, n=400)
        model = StudentTHMM(2, seed=1)
        history = model.fit(data, max_iterations=60, tolerance=1e-9)
        assert len(history) > 1
        assert all(b >= a - 1e-6 for a, b in zip(history, history[1:]))

    def test_parameters_stay_inside_their_documented_bounds(self):
        rng = np.random.default_rng(5)
        data = two_regime_data(rng, n=400)
        model = StudentTHMM(2, seed=2, degrees_of_freedom=6.0)
        model.fit(data, max_iterations=60)

        assert np.all(np.isfinite(model.means))
        assert np.all(np.isfinite(model.variances))
        assert np.all(model.variances >= model.variance_floor)
        assert np.allclose(model.transition.sum(axis=1), 1.0)
        assert model.initial.sum() == pytest.approx(1.0)

        df = model.degrees_of_freedom_per_state
        assert df.shape == (2,)
        assert np.all(df >= model.min_degrees_of_freedom)
        assert np.all(df <= model.max_degrees_of_freedom)

    def test_it_beats_the_gaussian_on_fat_tailed_data(self):
        """The headline claim, tested rather than asserted in a docstring."""
        rng = np.random.default_rng(6)
        data = two_regime_data(rng, n=800, df=4.0, seed_df=4.0)

        gaussian = GaussianHMM(2, seed=3)
        gaussian.fit(data, max_iterations=80, n_restarts=2)
        heavy = StudentTHMM(2, seed=3, degrees_of_freedom=4.0)
        heavy.fit(data, max_iterations=80, n_restarts=2)

        assert heavy.log_likelihood(data) > gaussian.log_likelihood(data)

    def test_it_detects_fat_tails_rather_than_defaulting_to_the_bound(self):
        rng = np.random.default_rng(7)
        data = two_regime_data(rng, n=800, df=4.0, seed_df=4.0)
        model = StudentTHMM(2, seed=4, degrees_of_freedom=4.0)
        model.fit(data, max_iterations=80)
        df = model.degrees_of_freedom_per_state
        # Not pinned at the Gaussian limit: the data really are heavy-tailed.
        assert np.all(df < model.max_degrees_of_freedom)

    def test_an_outlier_distorts_the_location_less_than_under_a_gaussian(self):
        rng = np.random.default_rng(8)
        clean = rng.normal(0.0, 1.0, size=(40, 1))
        data = np.vstack([clean, np.array([[100.0]])])

        gaussian = GaussianHMM(1, seed=5)
        gaussian.fit(data, max_iterations=200)
        heavy = StudentTHMM(1, seed=5, degrees_of_freedom=5.0)
        heavy.fit(data, max_iterations=200)

        gaussian_location = abs(float(gaussian.means[0, 0]))
        heavy_location = abs(float(heavy.means[0, 0]))
        assert gaussian_location > 1.0
        assert heavy_location < gaussian_location / 2.0

    def test_a_single_state_fit_matches_the_scipy_maximum_likelihood(self):
        """scipy.stats.t.fit is an independent optimiser for the same problem.

        With one state there is no Markov structure left, so the EM fixed point
        must be the maximum-likelihood estimate of a Student-t location, scale
        and degrees of freedom that scipy computes directly.
        """
        rng = np.random.default_rng(9)
        data = student_t.rvs(
            df=6.0, loc=0.5, scale=1.5, size=1200, random_state=rng
        ).reshape(-1, 1)

        model = StudentTHMM(1, seed=6, degrees_of_freedom=6.0)
        model.fit(data, max_iterations=400, tolerance=1e-10)

        reference_df, reference_loc, reference_scale = student_t.fit(data[:, 0])
        assert model.degrees_of_freedom_per_state[0] == pytest.approx(
            reference_df, rel=0.2
        )
        assert float(model.means[0, 0]) == pytest.approx(reference_loc, abs=0.1)
        assert math.sqrt(float(model.variances[0, 0])) == pytest.approx(
            reference_scale, rel=0.15
        )

    def test_the_retained_model_is_the_best_restart_including_its_tail_weight(self):
        """Guards the restart bookkeeping, which is easy to get subtly wrong.

        The degrees of freedom are updated in place during each restart, so a
        model that kept the last restart's ``nu`` while reporting the best
        restart's other parameters would report a likelihood that does not match
        its own parameters. Recomputing the likelihood from the retained
        parameters catches exactly that.
        """
        rng = np.random.default_rng(10)
        data = two_regime_data(rng, n=500)
        model = StudentTHMM(2, seed=7, degrees_of_freedom=6.0)
        model.fit(data, max_iterations=50, n_restarts=3)

        assert len(model.restart_log_likelihoods) == 3
        assert model.log_likelihood(data) == pytest.approx(
            max(model.restart_log_likelihoods), rel=1e-9
        )

    def test_a_seeded_fit_is_exactly_reproducible(self):
        rng = np.random.default_rng(11)
        data = two_regime_data(rng, n=300)
        first = StudentTHMM(2, seed=8)
        first.fit(data, max_iterations=40, n_restarts=2)
        second = StudentTHMM(2, seed=8)
        second.fit(data, max_iterations=40, n_restarts=2)
        assert first.to_dict() == second.to_dict()


class TestRegimeLabels:
    def test_the_higher_variance_state_is_labelled_as_the_stressed_one(self):
        rng = np.random.default_rng(12)
        data = two_regime_data(rng, n=800, calm_scale=0.4, crisis_scale=5.0)
        model = StudentTHMM(2, seed=9, degrees_of_freedom=5.0)
        model.fit(data, max_iterations=80, n_restarts=2)

        labels = model.label_series(data)
        assert set(np.unique(labels)) <= {"calm", "elevated", "stressed", "crisis"}
        # The calm label must sit on the low-variance state, so the majority of
        # the quiet observations receive it.
        quiet = labels[np.abs(data[:, 0]) < 1.0]
        assert np.mean(quiet == "calm") > 0.8

    def test_label_states_orders_by_scale(self):
        means = np.array([[0.0], [0.0]])
        variances = np.array([[9.0], [0.25]])
        mapping = label_states(means, variances, ("calm", "crisis"))
        assert mapping[1] == "calm"
        assert mapping[0] == "crisis"


class TestSerialisationAndValidation:
    def test_snapshot_names_the_emission_law_and_is_json_safe(self):
        rng = np.random.default_rng(13)
        data = two_regime_data(rng, n=300)
        model = StudentTHMM(2, seed=10)
        model.fit(data, max_iterations=40)
        snapshot = model.to_dict()

        assert snapshot["emission"] == "student_t"
        assert len(snapshot["degrees_of_freedom"]) == 2
        assert snapshot["fitted"] is True
        json.dumps(snapshot, allow_nan=False)

    def test_unfitted_access_raises(self):
        model = StudentTHMM(2)
        with pytest.raises(ValueError, match="not fitted"):
            model.degrees_of_freedom_per_state
        with pytest.raises(ValueError, match="not fitted"):
            model.to_dict()

    def test_constructor_rejects_impossible_degrees_of_freedom(self):
        with pytest.raises(ValueError, match="degrees_of_freedom must lie within"):
            StudentTHMM(2, degrees_of_freedom=1.5)
        with pytest.raises(ValueError, match="must be below"):
            StudentTHMM(2, min_degrees_of_freedom=10.0, max_degrees_of_freedom=5.0)
        with pytest.raises(ValueError, match="positive finite"):
            StudentTHMM(2, degrees_of_freedom=float("nan"))
        with pytest.raises(ValueError, match="positive finite"):
            StudentTHMM(2, min_degrees_of_freedom=-1.0)

    def test_malformed_observations_raise(self):
        model = StudentTHMM(2, seed=11)
        with pytest.raises(ValueError, match="non-finite"):
            model.fit(np.array([[1.0], [np.nan], [2.0]]))
        with pytest.raises(ValueError, match="empty"):
            model.fit(np.empty((0, 1)))

    def test_it_inherits_the_gaussian_interface(self):
        """Every method the gate consumes must work unchanged."""
        rng = np.random.default_rng(14)
        data = two_regime_data(rng, n=200)
        model = StudentTHMM(2, seed=12)
        model.fit(data, max_iterations=30)

        assert model.posteriors(data).shape == (200, 2)
        assert model.viterbi(data).shape == (200,)
        assert np.array_equal(model.predict(data), model.viterbi(data))
        assert isinstance(model.log_likelihood(data), float)
        assert model.is_fitted
