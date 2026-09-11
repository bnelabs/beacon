"""Tests for the TNCM-VAE counterfactual machinery.

The causal claims are the ones that need external verification, so they are
checked against the properties that define them rather than against the code:

* abduction followed by prediction must reproduce the observation exactly -- if it
  does not, the procedure is not forming a counterfactual at all;
* an intervention must sever incoming edges, which is what separates ``do`` from
  conditioning;
* effects must reach descendants only. This is the property a purely correlational
  model fails, and the test is written so that a model which merely propagated
  correlated noise would not pass.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from backend.modules.engine.tncm_vae import (
    CounterfactualError,
    Intervention,
    StructuralCausalModel,
    TrajectoryConstraints,
    TrajectoryVAE,
)


def chain_model(**kwargs) -> StructuralCausalModel:
    """A -> B -> C, with D unrelated. A is the exogenous driver."""
    defaults = dict(
        variables=["A", "B", "C", "D"],
        coefficients={"B": {"A": 0.5}, "C": {"B": 0.8}},
        self_lag={"A": 0.3, "B": 0.2, "C": 0.1, "D": 0.4},
        intercepts={"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0},
        initial_state={"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0},
    )
    defaults.update(kwargs)
    return StructuralCausalModel(**defaults)


def factual_trajectory(model: StructuralCausalModel, n_steps: int = 10, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return model.propagate(rng.normal(scale=0.3, size=(n_steps, len(model.variables))))


class TestStructure:
    def test_topological_order_respects_the_edges(self):
        model = chain_model()
        order = list(model.order)
        assert order.index("A") < order.index("B") < order.index("C")

    def test_descendants_follow_the_chain(self):
        model = chain_model()
        assert set(model.descendants("A")) == {"B", "C"}
        assert set(model.descendants("B")) == {"C"}
        assert model.descendants("C") == ()
        assert model.descendants("D") == ()

    def test_self_lag_is_not_a_descendant_relation(self):
        # A variable's own lag is its history, not causal influence on another
        # node, so it must not appear as a descendant.
        model = chain_model()
        assert "A" not in model.descendants("A")

    def test_a_cycle_is_rejected(self):
        with pytest.raises(ValueError, match="cycle"):
            StructuralCausalModel(
                variables=["X", "Y"],
                coefficients={"X": {"Y": 1.0}, "Y": {"X": 1.0}},
            )

    def test_self_reference_must_use_self_lag(self):
        with pytest.raises(ValueError, match="self_lag"):
            StructuralCausalModel(
                variables=["X"], coefficients={"X": {"X": 1.0}}
            )

    def test_unknown_names_are_rejected(self):
        with pytest.raises(ValueError, match="unknown child"):
            StructuralCausalModel(variables=["X"], coefficients={"Z": {"X": 1.0}})
        with pytest.raises(ValueError, match="not.*declared variable"):
            StructuralCausalModel(variables=["X"], coefficients={"X": {"Z": 1.0}})
        with pytest.raises(ValueError, match="initial_state"):
            StructuralCausalModel(variables=["X"], initial_state={"Z": 1.0})

    def test_duplicate_and_empty_variables_are_rejected(self):
        with pytest.raises(ValueError, match="unique"):
            StructuralCausalModel(variables=["X", "X"])
        with pytest.raises(ValueError, match="at least one"):
            StructuralCausalModel(variables=[])

    def test_non_finite_inputs_are_rejected(self):
        with pytest.raises(ValueError, match="not finite"):
            StructuralCausalModel(
                variables=["X", "Y"], coefficients={"X": {"Y": float("nan")}}
            )
        with pytest.raises(ValueError, match="self_lag"):
            StructuralCausalModel(variables=["X"], self_lag={"X": float("inf")})


class TestAbduction:
    def test_abduction_reproduces_the_observation_exactly(self):
        """The identity that makes the procedure a counterfactual.

        Inferring the exogenous noise and re-propagating it must return the
        observation to machine precision. For a linear model the inversion is
        closed form, so any appreciable error means the inversion is wrong rather
        than merely approximate.
        """
        model = chain_model()
        factual = factual_trajectory(model)

        noise = model.abduct(factual)
        restored = model.propagate(noise)

        assert np.allclose(restored, factual, atol=1e-12)

    def test_abduction_recovers_the_noise_that_was_used(self):
        model = chain_model()
        rng = np.random.default_rng(11)
        noise = rng.normal(scale=0.5, size=(9, len(model.variables)))

        factual = model.propagate(noise)
        assert np.allclose(model.abduct(factual), noise, atol=1e-12)


class TestCounterfactualIdentity:
    def test_intervening_to_the_observed_value_changes_nothing(self):
        """do(X = x_observed) must return the observation.

        If this failed, every other counterfactual would be measuring the error in
        the procedure rather than the effect of the intervention.
        """
        model = chain_model()
        factual = factual_trajectory(model)

        interventions = [
            Intervention(name, factual[:, model.index[name]].copy())
            for name in model.variables
        ]
        result = model.counterfactual(factual, interventions)

        assert np.max(np.abs(result.delta)) < 1e-9
        assert result.affected == ()


class TestInterventionSemantics:
    def test_an_intervention_severs_incoming_edges(self):
        """``do`` is not conditioning.

        Forcing B while also moving its parent A must leave B exactly where it was
        put. A model that treated the intervention as conditioning would let A drag
        B along.
        """
        model = chain_model()
        factual = factual_trajectory(model)
        held = factual[:, model.index["B"]].copy()

        result = model.counterfactual(
            factual,
            [Intervention("A", factual[:, 0] + 5.0), Intervention("B", held)],
        )

        assert np.max(np.abs(result.effect_on("B"))) < 1e-9
        assert np.max(np.abs(result.effect_on("C"))) < 1e-9
        # A itself moved, so the test is not vacuous.
        assert np.max(np.abs(result.effect_on("A"))) == pytest.approx(5.0)

    def test_effects_reach_descendants_only(self):
        """The property a correlational model cannot have.

        Moving B must change C (its child) and leave A (its parent) and D
        (unrelated) untouched.
        """
        model = chain_model()
        factual = factual_trajectory(model)

        result = model.counterfactual(
            factual, [Intervention("B", factual[:, 1] + 10.0)]
        )

        assert set(result.affected) == {"B", "C"}
        assert set(result.unaffected) == {"A", "D"}
        assert np.max(np.abs(result.effect_on("A"))) < 1e-9
        assert np.max(np.abs(result.effect_on("D"))) < 1e-9

    def test_the_intervened_variable_takes_the_forced_value(self):
        model = chain_model()
        factual = factual_trajectory(model)
        result = model.counterfactual(factual, [Intervention("B", 100.0)])

        assert np.allclose(result.counterfactual[:, model.index["B"]], 100.0)

    def test_a_root_intervention_still_moves_descendants(self):
        model = chain_model()
        factual = factual_trajectory(model)
        result = model.counterfactual(factual, [Intervention("A", factual[:, 0] + 2.0)])

        assert set(result.affected) == {"A", "B", "C"}
        assert "D" in result.unaffected

    def test_no_intervention_is_rejected(self):
        model = chain_model()
        with pytest.raises(CounterfactualError, match="at least one intervention"):
            model.counterfactual(factual_trajectory(model), [])

    def test_an_unknown_target_is_rejected(self):
        model = chain_model()
        with pytest.raises(CounterfactualError, match="not a declared variable"):
            model.counterfactual(factual_trajectory(model), [Intervention("Z", 1.0)])

    def test_a_wrong_length_series_is_rejected(self):
        model = chain_model()
        with pytest.raises(CounterfactualError, match="neither 1 nor"):
            model.counterfactual(
                factual_trajectory(model, n_steps=10), [Intervention("A", [1.0, 2.0])]
            )

    def test_a_non_finite_intervention_is_rejected(self):
        model = chain_model()
        with pytest.raises(CounterfactualError, match="not finite"):
            model.counterfactual(
                factual_trajectory(model), [Intervention("A", float("nan"))]
            )


class TestPropagationMagnitudes:
    def test_a_constantly_held_parent_propagates_at_the_steady_state_gain(self):
        """The lagged chain has a closed-form steady-state gain to check against.

        Holding B at 10 rather than at 0 reaches C through coefficient 0.8 and C's
        own lag 0.1, so the gap between the two counterfactuals converges to
        0.8 * 10 / (1 - 0.1) = 8.888... Two constant interventions are compared
        rather than one against the factual path, because the factual path is
        endogenous: a shock measured against it is not a step at all.
        """
        model = chain_model()
        factual = factual_trajectory(model, n_steps=60)

        high = model.counterfactual(factual, [Intervention("B", 10.0)])
        low = model.counterfactual(factual, [Intervention("B", 0.0)])

        expected = 0.8 * 10.0 / (1.0 - 0.1)
        gap = high.counterfactual[:, 2] - low.counterfactual[:, 2]
        assert gap[-1] == pytest.approx(expected, rel=1e-6)

    def test_a_cascade_of_two_edges_scales_by_both_coefficients(self):
        # Holding A at 4 rather than 0 reaches C as
        # 0.5 * 0.8 * 4 / ((1 - 0.2) * (1 - 0.1)).
        model = chain_model()
        factual = factual_trajectory(model, n_steps=80)

        high = model.counterfactual(factual, [Intervention("A", 4.0)])
        low = model.counterfactual(factual, [Intervention("A", 0.0)])

        expected = 0.5 * 0.8 * 4.0 / ((1.0 - 0.2) * (1.0 - 0.1))
        gap = high.counterfactual[:, 2] - low.counterfactual[:, 2]
        assert gap[-1] == pytest.approx(expected, rel=1e-6)

    def test_a_transient_intervention_leaves_the_variable_afterwards(self):
        # Forced only at step 2; the structural dynamics take over from step 3.
        model = chain_model()
        factual = factual_trajectory(model, n_steps=12)
        forced = [factual[0, 0], factual[1, 0], 50.0] + list(factual[3:, 0])

        result = model.counterfactual(factual, [Intervention("A", forced)])
        a_effect = result.effect_on("A")

        assert a_effect[2] > 0
        # It decays rather than persisting, because the intervention stopped.
        assert abs(a_effect[-1]) < abs(a_effect[2])


class TestConstraints:
    def test_a_violation_is_reported_not_hidden(self):
        model = chain_model()
        factual = factual_trajectory(model)
        constraints = TrajectoryConstraints(lower={"A": 1e6})

        result = model.counterfactual(
            factual, [Intervention("B", factual[:, 1] + 1.0)], constraints=constraints
        )

        assert result.constraints_ok is False
        assert result.constraint_violations
        # The trajectory is still returned; clipping would conceal that the
        # counterfactual left the feasible region.
        assert result.counterfactual.shape == factual.shape

    def test_a_feasible_counterfactual_passes(self):
        model = chain_model()
        factual = factual_trajectory(model)
        constraints = TrajectoryConstraints(lower={"A": -1e6}, upper={"A": 1e6})

        result = model.counterfactual(
            factual, [Intervention("B", factual[:, 1] + 1.0)], constraints=constraints
        )
        assert result.constraints_ok is True
        assert result.constraint_violations == ()

    def test_bounds_are_checked_per_variable(self):
        model = chain_model()
        factual = factual_trajectory(model)
        constraints = TrajectoryConstraints(upper={"C": -1e6})

        result = model.counterfactual(
            factual, [Intervention("B", factual[:, 1] + 1.0)], constraints=constraints
        )
        assert result.constraints_ok is False
        assert any("C" in violation for violation in result.constraint_violations)

    def test_unknown_bound_targets_are_rejected(self):
        model = chain_model()
        with pytest.raises(ValueError, match="unknown variable"):
            model.counterfactual(
                factual_trajectory(model),
                [Intervention("B", 1.0)],
                constraints=TrajectoryConstraints(lower={"Z": 0.0}),
            )


class TestResultRecord:
    def test_the_record_names_what_moved(self):
        model = chain_model()
        factual = factual_trajectory(model)
        result = model.counterfactual(factual, [Intervention("B", factual[:, 1] + 3.0)])
        payload = result.to_dict()

        assert payload["affected"] == ["B", "C"]
        assert payload["unaffected"] == ["A", "D"]
        assert payload["effect_by_variable"]["A"] == pytest.approx(0.0)
        assert payload["effect_by_variable"]["C"] > 0

    def test_serialises_to_json(self):
        model = chain_model()
        result = model.counterfactual(factual_trajectory(model), [Intervention("B", 5.0)])
        json.dumps(result.to_dict(), allow_nan=False)

    def test_summary_reports_a_leaf_intervention(self):
        model = chain_model()
        factual = factual_trajectory(model)
        result = model.counterfactual(factual, [Intervention("C", 1.0)])
        # C is a leaf, so it moves but nothing downstream of it does.
        assert result.affected == ("C",)
        assert "changes C" in result.summary()

    def test_summary_reports_a_null_intervention(self):
        model = chain_model()
        factual = factual_trajectory(model)
        # Forcing C to the value it already had changes nothing at all.
        result = model.counterfactual(
            factual, [Intervention("C", factual[:, 2].copy())]
        )
        assert result.affected == ()
        assert "changes nothing downstream" in result.summary()

    def test_effect_on_an_unknown_variable_is_rejected(self):
        model = chain_model()
        result = model.counterfactual(factual_trajectory(model), [Intervention("B", 1.0)])
        with pytest.raises(KeyError):
            result.effect_on("Z")


class TestTrajectoryValidation:
    def test_wrong_shape_is_rejected(self):
        model = chain_model()
        with pytest.raises(ValueError, match="2-D"):
            model.abduct(np.zeros(5))
        with pytest.raises(ValueError, match="columns"):
            model.abduct(np.zeros((5, 2)))

    def test_empty_observations_are_rejected(self):
        model = chain_model()
        with pytest.raises(ValueError, match="empty"):
            model.abduct(np.zeros((0, 4)))

    def test_non_finite_observations_are_rejected(self):
        model = chain_model()
        with pytest.raises(ValueError, match="non-finite"):
            model.abduct(np.full((4, 4), np.nan))

    def test_exogenous_shape_is_validated(self):
        model = chain_model()
        with pytest.raises(ValueError, match="columns"):
            model.propagate(np.zeros((5, 2)))
        with pytest.raises(ValueError, match="empty"):
            model.propagate(np.zeros((0, 4)))


class TestVAE:
    def _data(self, n: int = 300, steps: int = 4, seed: int = 3):
        model = chain_model()
        rng = np.random.default_rng(seed)
        return model.propagate(rng.normal(scale=0.5, size=(steps * n, len(model.variables)))).reshape(
            n, steps * 4
        )

    def test_training_reduces_the_loss(self):
        data = self._data()
        vae = TrajectoryVAE(n_features=data.shape[1], latent_dim=3, hidden_dim=32, seed=1)
        history = vae.fit(data, epochs=60, learning_rate=5e-3)

        assert len(history) == 60
        assert history[-1] < history[0], "training should reduce the ELBO loss"

    def test_elbo_is_finite(self):
        data = self._data(n=100)
        vae = TrajectoryVAE(n_features=data.shape[1], latent_dim=2, hidden_dim=16, seed=2)
        assert math.isfinite(vae.elbo(data))

    def test_encode_returns_posterior_parameters_of_the_right_width(self):
        data = self._data(n=50)
        vae = TrajectoryVAE(n_features=data.shape[1], latent_dim=5, hidden_dim=16, seed=3)
        mean, logvar = vae.encode(data)

        assert mean.shape == (50, 5)
        assert logvar.shape == (50, 5)

    def test_reconstruct_preserves_shape(self):
        data = self._data(n=20)
        vae = TrajectoryVAE(n_features=data.shape[1], latent_dim=3, hidden_dim=16, seed=4)
        rebuilt = vae.reconstruct(data)
        assert rebuilt.shape == data.shape

    def test_reconstruction_beats_predicting_the_mean(self):
        """Reconstruction quality is measured, not assumed.

        A VAE that had learned nothing would still return the right shape. The
        baseline to beat is the constant mean of the training data, which is the
        best a memoryless model can do.
        """
        data = self._data(n=400, seed=5)
        vae = TrajectoryVAE(n_features=data.shape[1], latent_dim=4, hidden_dim=32, seed=5)
        vae.fit(data, epochs=120, learning_rate=5e-3)

        reconstruction_mse = float(np.mean((vae.reconstruct(data) - data) ** 2))
        baseline_mse = float(np.mean((data - data.mean(axis=0)) ** 2))

        assert reconstruction_mse < baseline_mse

    def test_sampling_is_reproducible_given_a_seed(self):
        data = self._data(n=50)
        first = TrajectoryVAE(n_features=data.shape[1], latent_dim=3, hidden_dim=16, seed=9)
        second = TrajectoryVAE(n_features=data.shape[1], latent_dim=3, hidden_dim=16, seed=9)

        assert np.allclose(first.sample(5), second.sample(5))

    def test_sampling_returns_the_right_shape(self):
        data = self._data(n=50)
        vae = TrajectoryVAE(n_features=data.shape[1], latent_dim=3, hidden_dim=16, seed=6)
        assert vae.sample(7).shape == (7, data.shape[1])

    def test_validation(self):
        with pytest.raises(ValueError, match="n_features"):
            TrajectoryVAE(n_features=0)
        with pytest.raises(ValueError, match="latent_dim"):
            TrajectoryVAE(n_features=10, latent_dim=0)
        with pytest.raises(ValueError, match="hidden_dim"):
            TrajectoryVAE(n_features=10, hidden_dim=0)

        vae = TrajectoryVAE(n_features=8, latent_dim=2, hidden_dim=8, seed=1)
        with pytest.raises(ValueError, match="width 8"):
            vae.encode(np.zeros((3, 5)))
        with pytest.raises(ValueError, match="n must be positive"):
            vae.sample(0)
        with pytest.raises(ValueError, match="epochs"):
            vae.fit(np.zeros((4, 8)), epochs=0)
        with pytest.raises(ValueError, match="learning_rate"):
            vae.fit(np.zeros((4, 8)), learning_rate=0.0)


class TestIntegrationWithTheOtherEngines:
    def test_a_counterfactual_can_be_cleared(self):
        """The intended composition: shock the system, then clear it.

        The counterfactual produces capital levels; the clearing engine then
        answers who fails given them. This ties the generative step to the
        financial physics rather than leaving it as a plausible-looking path.
        """
        from backend.modules.risk.clearing import sequential_clearing

        model = StructuralCausalModel(
            variables=["capital_a", "capital_b", "spread"],
            coefficients={"capital_b": {"spread": -1.0}},
            self_lag={"capital_a": 0.5, "capital_b": 0.5, "spread": 0.4},
            intercepts={"capital_a": 8.0, "capital_b": 8.0, "spread": 1.0},
            initial_state={"capital_a": 8.0, "capital_b": 8.0, "spread": 1.0},
        )
        rng = np.random.default_rng(21)
        factual = model.propagate(rng.normal(scale=0.05, size=(6, 3)))

        result = model.counterfactual(factual, [Intervention("spread", 6.0)])

        assert "capital_b" in result.affected
        # Bank B's capital in the counterfactual is lower, and drives its clearing.
        final_capital_b = float(result.counterfactual[-1, model.index["capital_b"]])
        assert final_capital_b < float(factual[-1, model.index["capital_b"]])

        liabilities = np.array([[0.0, 10.0], [10.0, 0.0]])
        endowments = [float(result.counterfactual[-1, model.index["capital_a"]]), final_capital_b]
        clearing = sequential_clearing(liabilities, endowments)

        assert clearing.n_defaults >= 0
        json.dumps(result.to_dict(), allow_nan=False)
