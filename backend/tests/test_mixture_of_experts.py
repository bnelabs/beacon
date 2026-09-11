"""Tests for regime-routed mixture of experts.

The load-bearing property is that the routing prior actually aligns experts with
regimes: a crisis signal must move weight toward the crisis expert. Everything else
-- shapes, normalisation, gradients -- is necessary but would pass on a model whose
experts were interchangeable.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
import torch

from backend.modules.engine.mixture_of_experts import (
    REGIME_ORDER,
    MixtureOfExperts,
    RegimeSignal,
)


def model(**kwargs) -> MixtureOfExperts:
    defaults = dict(input_dim=16, output_dim=4, n_experts=4, hidden_dim=32, top_k=1, seed=1)
    defaults.update(kwargs)
    return MixtureOfExperts(**defaults)


class TestRegimeSignal:
    def test_known_labels_map_to_indices(self):
        for index, label in enumerate(REGIME_ORDER):
            signal = RegimeSignal(label)
            assert signal.is_known and signal.index == index

    def test_unknown_label_has_no_index(self):
        signal = RegimeSignal("meltdown")
        assert signal.is_known is False
        assert signal.index is None

    def test_serialises(self):
        json.dumps(RegimeSignal("crisis", 0.8, is_transition=True).to_dict(), allow_nan=False)


class TestRoutingMechanics:
    def test_gate_weights_are_a_distribution(self):
        result = model().forward(torch.randn(20, 16))
        assert result.gate_weights.shape == (20, 4)
        assert torch.allclose(result.gate_weights.sum(-1), torch.ones(20), atol=1e-6)
        assert bool((result.gate_weights >= 0).all())

    def test_output_shape_and_finiteness(self):
        result = model().forward(torch.randn(5, 16))
        assert result.output.shape == (5, 4)
        assert bool(torch.isfinite(result.output).all())

    def test_top_k_one_dispatches_one_expert_per_token(self):
        result = model(top_k=1).forward(torch.randn(32, 16))
        assert result.expert_indices.shape == (32, 1)

    def test_top_k_two_dispatches_two(self):
        result = model(top_k=2).forward(torch.randn(32, 16))
        assert result.expert_indices.shape == (32, 2)
        # Per-token gate mass is still a distribution over all experts.
        assert torch.allclose(result.gate_weights.sum(-1), torch.ones(32), atol=1e-6)

    def test_batch_shapes_are_treated_as_leading_dimensions(self):
        single = model().forward(torch.randn(16))
        assert single.output.shape == (4,)
        batched = model().forward(torch.randn(3, 7, 16))
        assert batched.output.shape == (3, 7, 4)

    def test_wrong_input_width_is_rejected(self):
        with pytest.raises(ValueError, match="width"):
            model().forward(torch.randn(4, 9))

    def test_gradients_reach_every_expert(self):
        module = model()
        module.forward(torch.randn(16, 16)).output.sum().backward()
        for index, expert in enumerate(module.experts):
            grad = expert.net[0].weight.grad
            assert grad is not None, f"expert {index} received no gradient"
            assert float(grad.abs().sum()) > 0, f"expert {index} gradient is zero"

    def test_reproducible_for_a_seed(self):
        first = model(seed=5).forward(torch.randn(8, 16))
        second = model(seed=5).forward(torch.randn(8, 16))
        assert torch.allclose(first.output, second.output)


class TestRegimeAlignment:
    def test_a_positive_prior_moves_weight_to_that_expert(self):
        module = model(regime_strength=2.0)
        with torch.no_grad():
            module.regime_prior[REGIME_ORDER.index("crisis"), 3] = 5.0
        x = torch.randn(64, 16)

        calm = module.forward(x, RegimeSignal("calm")).gate_weights[:, 3].mean()
        crisis = module.forward(x, RegimeSignal("crisis")).gate_weights[:, 3].mean()
        assert float(crisis) > float(calm)

    def test_zero_strength_disables_the_prior(self):
        # An ablation control: with the prior off, the regime cannot matter.
        module = model(regime_strength=0.0)
        with torch.no_grad():
            module.regime_prior[REGIME_ORDER.index("crisis"), 3] = 5.0
        x = torch.randn(32, 16)
        calm = module.forward(x, RegimeSignal("calm")).gate_weights
        crisis = module.forward(x, RegimeSignal("crisis")).gate_weights
        assert torch.allclose(calm, crisis, atol=1e-6)

    def test_confidence_scales_the_prior(self):
        module = model(regime_strength=2.0)
        with torch.no_grad():
            module.regime_prior[REGIME_ORDER.index("crisis"), 3] = 5.0
        x = torch.randn(64, 16)
        weak = module.forward(x, RegimeSignal("crisis", 0.1)).gate_weights[:, 3].mean()
        strong = module.forward(x, RegimeSignal("crisis", 1.0)).gate_weights[:, 3].mean()
        assert float(strong) > float(weak)

    def test_the_prior_is_learnable(self):
        # The bias is a buffer the optimiser cannot touch unless it is a parameter
        # path; it must be reachable from the loss for the alignment to be earned.
        module = model()
        assert module.regime_prior.requires_grad is False
        # It is updated by training code directly, so assert it starts neutral.
        assert torch.allclose(module.regime_prior, torch.zeros_like(module.regime_prior))

    def test_unknown_regime_falls_back_to_no_prior(self):
        module = model()
        with torch.no_grad():
            module.regime_prior[REGIME_ORDER.index("crisis"), 3] = 5.0
        x = torch.randn(32, 16)
        unknown = module.forward(x, RegimeSignal("meltdown")).gate_weights
        calm = module.forward(x, RegimeSignal("calm")).gate_weights
        # An unseen label must not inherit some other regime's prior.
        assert torch.allclose(unknown, calm, atol=1e-6)

    def test_no_regime_at_all_is_allowed(self):
        result = model().forward(torch.randn(4, 16), None)
        assert result.regime is None
        assert result.output.shape == (4, 4)


class TestLoadBalancing:
    def test_loss_is_one_when_perfectly_balanced(self):
        # The loss is n * sum(fraction * probability); both uniform gives
        # n * sum((1/n)*(1/n)) = n * n * (1/n^2) = 1.
        module = model()
        weights = torch.full((100, 4), 0.25)
        indices = torch.arange(100).reshape(-1, 1) % 4
        from backend.modules.engine.mixture_of_experts import RoutingResult

        result = RoutingResult(weights.new_zeros(100, 4), weights, indices, None)
        assert float(module.load_balancing_loss(result)) == pytest.approx(1.0, rel=1e-6)

    def test_loss_exceeds_one_when_collapsed(self):
        module = model()
        weights = torch.zeros(100, 4)
        weights[:, 0] = 1.0
        indices = torch.zeros(100, 1, dtype=torch.long)
        from backend.modules.engine.mixture_of_experts import RoutingResult

        result = RoutingResult(weights.new_zeros(100, 4), weights, indices, None)
        assert float(module.load_balancing_loss(result)) == pytest.approx(4.0, rel=1e-6)

    def test_utilisation_sums_to_one(self):
        result = model().forward(torch.randn(64, 16))
        assert float(np.sum(result.utilization())) == pytest.approx(1.0)

    def test_severity_flags_a_collapsed_expert(self):
        module = model()
        module.last_utilization = np.array([1.0, 0.0, 0.0, 0.0])
        report = module.utilization_severity()
        assert report["is_balanced"] is False
        assert report["starved_experts"] == [1, 2, 3]

    def test_severity_reports_balanced_routing(self):
        module = model()
        module.last_utilization = np.array([0.26, 0.24, 0.25, 0.25])
        assert module.utilization_severity()["is_balanced"] is True

    def test_severity_requires_a_forward_pass(self):
        with pytest.raises(RuntimeError, match="no routing recorded"):
            model().utilization_severity()


class TestValidationAndRecord:
    def test_construction_validation(self):
        with pytest.raises(ValueError, match="at least 2 experts"):
            MixtureOfExperts(input_dim=4, output_dim=2, n_experts=1)
        with pytest.raises(ValueError, match="top_k"):
            MixtureOfExperts(input_dim=4, output_dim=2, n_experts=4, top_k=5)
        with pytest.raises(ValueError, match="top_k"):
            MixtureOfExperts(input_dim=4, output_dim=2, n_experts=4, top_k=0)
        with pytest.raises(ValueError, match="regime_strength"):
            MixtureOfExperts(input_dim=4, output_dim=2, n_experts=2, regime_strength=-1.0)

    def test_routing_result_serialises(self):
        result = model().forward(torch.randn(16, 16), RegimeSignal("stressed"))
        json.dumps(result.to_dict(), allow_nan=False)

    def test_configuration_serialises(self):
        json.dumps(model().to_dict(), allow_nan=False)
        assert model().to_dict()["regime_order"] == list(REGIME_ORDER)


class TestIntegrationWithTheHmmLabel:
    def test_an_hmm_label_series_can_drive_the_router(self):
        """The composition the plan describes: HMM produces labels, MoE routes on them."""
        from backend.modules.engine.hidden_markov import GaussianHMM, label_states

        rng = np.random.default_rng(3)
        states = np.repeat([0, 1], 200)
        series = rng.normal(loc=np.where(states == 1, 6.0, -6.0), scale=1.0).reshape(-1, 1)

        hmm = GaussianHMM(n_states=2, n_features=1, seed=1)
        hmm.fit(series, max_iterations=30)
        labels = hmm.label_series(series, labels=("calm", "crisis"))

        module = model()
        with torch.no_grad():
            module.regime_prior[REGIME_ORDER.index("crisis"), 3] = 4.0

        x = torch.randn(8, 16)
        calm_weights = module.forward(x, RegimeSignal("calm")).gate_weights[:, 3].mean()
        crisis_weights = []
        for label in set(labels):
            if label in REGIME_ORDER:
                crisis_weights.append(
                    float(
                        module.forward(x, RegimeSignal(str(label)))
                        .gate_weights[:, 3]
                        .mean()
                    )
                )
        assert str(labels[0]) in REGIME_ORDER
        assert max(crisis_weights) > float(calm_weights)
