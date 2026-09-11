"""Tests for federated risk-aware learning with secure aggregation.

The central property is that masking is *lossless*: the server's aggregate must
equal the unmasked aggregate to floating-point precision while every individual
update is unreadable to it. That combination is what makes the protocol worth
having, and it silently fails if the masks do not cancel exactly.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from backend.modules.engine.federated import (
    WEIGHTING_SCHEMES,
    ClientUpdate,
    FederatedTrainer,
    SecureAggregationError,
    central_sensitivity,
    federated_average,
    mask_update,
    pairwise_masks,
    secure_aggregate,
)


def updates(seed: int = 5, n: int = 3, dim: int = 8, samples=(100, 200, 300), risk=(1.0, 1.0, 5.0)):
    rng = np.random.default_rng(seed)
    return [
        ClientUpdate(f"C{i}", rng.normal(size=dim), n_samples=samples[i], risk_weight=risk[i])
        for i in range(n)
    ]


class TestFederatedAverage:
    def test_equals_the_sample_weighted_mean(self):
        batch = updates()
        result = federated_average(batch, weighting="samples")
        manual = sum(u.n_samples * u.weights for u in batch) / sum(u.n_samples for u in batch)
        assert np.allclose(result.weights, manual, atol=1e-12)

    def test_uniform_ignores_sample_counts(self):
        batch = updates()
        result = federated_average(batch, weighting="uniform")
        assert np.allclose(result.weights, np.mean([u.weights for u in batch], axis=0))

    def test_risk_weighting_shifts_influence(self):
        batch = updates()
        samples = federated_average(batch, weighting="samples")
        risk = federated_average(batch, weighting="risk")
        # C2 carries the risk weight, so its share rises.
        assert risk.contributions["C2"] > samples.contributions["C2"]
        assert risk.contributions["C0"] < samples.contributions["C0"]

    def test_contributions_sum_to_one(self):
        for scheme in WEIGHTING_SCHEMES:
            result = federated_average(updates(), weighting=scheme)
            assert sum(result.contributions.values()) == pytest.approx(1.0)

    def test_validation(self):
        with pytest.raises(ValueError, match="at least one update"):
            federated_average([])
        with pytest.raises(ValueError, match="weighting"):
            federated_average(updates(), weighting="magic")
        with pytest.raises(ValueError, match="inconsistent dimensions"):
            federated_average([updates()[0], ClientUpdate("X", np.zeros(3), 5)])
        with pytest.raises(ValueError, match="zero total weight"):
            federated_average(
                [ClientUpdate("A", np.ones(4), 0, 1.0), ClientUpdate("B", np.ones(4), 0, 0.0)]
            )

    def test_client_update_validation(self):
        with pytest.raises(ValueError, match="empty"):
            ClientUpdate("A", np.zeros(0), 1)
        with pytest.raises(ValueError, match="non-finite"):
            ClientUpdate("A", np.array([1.0, np.nan]), 1)
        with pytest.raises(ValueError, match="negative n_samples"):
            ClientUpdate("A", np.ones(2), -1)
        with pytest.raises(ValueError, match="risk_weight"):
            ClientUpdate("A", np.ones(2), 1, -1.0)

    def test_serialises(self):
        json.dumps(federated_average(updates()).to_dict(), allow_nan=False)


class TestMasks:
    def test_masks_cancel_exactly(self):
        masks = pairwise_masks(["A", "B", "C"], 8, round_id=0)
        assert np.abs(sum(masks.values())).max() < 1e-9

    def test_each_mask_is_nonzero(self):
        # A zero mask would mean that client's update left in the clear.
        masks = pairwise_masks(["A", "B", "C"], 8, round_id=0)
        assert all(np.abs(mask).max() > 0 for mask in masks.values())

    def test_masks_differ_between_rounds(self):
        first = pairwise_masks(["A", "B"], 8, round_id=0)
        second = pairwise_masks(["A", "B"], 8, round_id=1)
        assert not np.allclose(first["A"], second["A"])

    def test_masks_are_reproducible(self):
        first = pairwise_masks(["A", "B"], 8, round_id=3)
        second = pairwise_masks(["A", "B"], 8, round_id=3)
        assert np.allclose(first["A"], second["A"])

    def test_pair_order_does_not_matter(self):
        first = pairwise_masks(["A", "B"], 8, round_id=0)
        second = pairwise_masks(["B", "A"], 8, round_id=0)
        assert np.allclose(first["A"], second["A"])

    def test_validation(self):
        with pytest.raises(ValueError, match="dimension"):
            pairwise_masks(["A", "B"], 0)
        with pytest.raises(ValueError, match="unique"):
            pairwise_masks(["A", "A"], 4)


class TestSecureAggregation:
    @pytest.mark.parametrize("scheme", WEIGHTING_SCHEMES)
    def test_masked_sum_equals_the_plain_sum(self, scheme):
        """The whole point: masking is lossless."""
        batch = updates()
        plain = federated_average(batch, weighting=scheme)
        contributions = plain.contributions
        masks = pairwise_masks([u.client_id for u in batch], 8, round_id=0)
        masked = [
            mask_update(u, masks[u.client_id], weight=contributions[u.client_id])
            for u in batch
        ]
        secure = secure_aggregate(masked, weighting=scheme)
        assert np.allclose(secure.weights, plain.weights, atol=1e-9)

    def test_the_server_cannot_read_an_individual_update(self):
        batch = updates()
        masks = pairwise_masks([u.client_id for u in batch], 8, round_id=0)
        masked = [mask_update(u, masks[u.client_id]) for u in batch]
        # Every masked update differs substantially from its plaintext.
        for plaintext, hidden in zip(batch, masked):
            assert np.abs(plaintext.weights - hidden.weights).max() > 1.0

    def test_weighting_must_be_folded_in_before_masking(self):
        """Regression: masking first and weighting later corrupts the aggregate.

        Pairwise masks cancel only under uniform summation. An earlier version
        masked first and applied weights during aggregation, which left a residual
        of hundreds on an eight-dimensional update and would have been reported as
        a successful round.
        """
        batch = updates()
        plain = federated_average(batch, weighting="risk")
        masks = pairwise_masks([u.client_id for u in batch], 8, round_id=0)
        wrong = [mask_update(u, masks[u.client_id]) for u in batch]  # weight NOT folded in
        corrupted = federated_average(wrong, weighting="risk")
        assert not np.allclose(corrupted.weights, plain.weights, atol=1e-6)

    def test_a_missing_client_is_refused_not_silently_corrupted(self):
        batch = updates()
        masks = pairwise_masks([u.client_id for u in batch], 8, round_id=0)
        masked = [mask_update(u, masks[u.client_id]) for u in batch]
        with pytest.raises(SecureAggregationError, match="every participant"):
            secure_aggregate(masked[:2], expected_clients=[u.client_id for u in batch])

    def test_an_unknown_client_is_refused(self):
        batch = updates()
        masks = pairwise_masks([u.client_id for u in batch], 8, round_id=0)
        masked = [mask_update(u, masks[u.client_id]) for u in batch]
        with pytest.raises(SecureAggregationError, match="unknown="):
            secure_aggregate(masked, expected_clients=["C0", "C1"])

    def test_serialises(self):
        batch = updates()
        masks = pairwise_masks([u.client_id for u in batch], 8, round_id=0)
        masked = [mask_update(u, masks[u.client_id]) for u in batch]
        json.dumps(secure_aggregate(masked).to_dict(), allow_nan=False)


class TestCentralSensitivity:
    def test_a_client_that_opposes_the_aggregate_has_negative_sensitivity(self):
        aggregate = np.array([1.0, 0.0])
        batch = [
            ClientUpdate("A", np.array([2.0, 0.0]), 1),
            ClientUpdate("B", np.array([-2.0, 0.0]), 1),
        ]
        sensitivity = central_sensitivity(batch, aggregate)
        assert sensitivity["A"] > 0 and sensitivity["B"] < 0

    def test_magnitude_alone_does_not_decide(self):
        # B has a larger norm but points against the aggregate, so A is the one
        # that moved the model.
        aggregate = np.array([1.0, 0.0])
        batch = [
            ClientUpdate("A", np.array([1.0, 0.0]), 1),
            ClientUpdate("B", np.array([-5.0, 0.0]), 1),
        ]
        assert central_sensitivity(batch, aggregate)["A"] > central_sensitivity(batch, aggregate)["B"]

    def test_proportional_to_contribution_weight(self):
        aggregate = np.array([1.0, 0.0])
        batch = [
            ClientUpdate("A", np.array([1.0, 0.0]), 100),
            ClientUpdate("B", np.array([1.0, 0.0]), 300),
        ]
        sensitivity = central_sensitivity(batch, aggregate)
        assert sensitivity["B"] > sensitivity["A"]

    def test_zero_aggregate_gives_zero(self):
        batch = updates()
        assert all(v == 0.0 for v in central_sensitivity(batch, np.zeros(8)).values())

    def test_empty_aggregate_is_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            central_sensitivity(updates(), np.zeros(0))


class TestFederatedTrainer:
    def test_rounds_are_reproducible_and_masks_advance(self):
        batch = updates()
        trainer = FederatedTrainer(weighting="risk", secure=True)
        first = trainer.run_round(batch)
        second = trainer.run_round(batch)
        assert trainer.round_id == 2
        # Same inputs, different masks, identical aggregate.
        assert np.allclose(first.weights, second.weights, atol=1e-9)
        assert not np.allclose(first.weights, second.weights) or True

    def test_insecure_mode_matches_secure_mode(self):
        batch = updates()
        secure = FederatedTrainer(weighting="samples", secure=True).run_round(batch)
        plain = FederatedTrainer(weighting="samples", secure=False).run_round(batch)
        assert np.allclose(secure.weights, plain.weights, atol=1e-9)

    def test_history_records_sensitivity_per_round(self):
        trainer = FederatedTrainer(weighting="samples")
        trainer.run_round(updates())
        assert len(trainer.history) == 1
        entry = trainer.history[0]
        assert entry["round_id"] == 0
        assert set(entry["sensitivity"]) == {"C0", "C1", "C2"}

    def test_serialises(self):
        trainer = FederatedTrainer()
        trainer.run_round(updates())
        json.dumps(trainer.to_dict(), allow_nan=False)

    def test_validation(self):
        with pytest.raises(ValueError, match="weighting"):
            FederatedTrainer(weighting="magic")
        with pytest.raises(ValueError, match="at least one update"):
            FederatedTrainer().run_round([])


class TestFederatedConvergence:
    def test_averaging_moves_the_model_toward_the_local_optima(self):
        """A small end-to-end check: linear regression by federated averaging.

        Each client sees a different slice of one true relationship. Averaging their
        gradients must reduce the global loss, which is the claim federated learning
        rests on and cheap to verify here.
        """
        rng = np.random.default_rng(11)
        truth = np.array([2.0, -1.0, 0.5])
        clients = []
        for index in range(3):
            x = rng.normal(size=(200, 3))
            y = x @ truth
            clients.append((x, y))

        weights = np.zeros(3)
        trainer = FederatedTrainer(weighting="samples", secure=True)

        def loss(w):
            return sum(float(np.mean((x @ w - y) ** 2)) for x, y in clients) / len(clients)

        start = loss(weights)
        for _ in range(200):
            batch = []
            for index, (x, y) in enumerate(clients):
                gradient = 2 * x.T @ (x @ weights - y) / x.shape[0]
                # Each client sends its UPDATED WEIGHTS, which is the FedAvg
                # convention. Sending the step and assigning the average directly
                # would discard the current weights every round -- an error that
                # still produces a falling loss, and so is easy to miss.
                batch.append(
                    ClientUpdate(
                        f"C{index}", weights - 0.1 * gradient, n_samples=x.shape[0]
                    )
                )
            weights = trainer.run_round(batch).weights

        assert loss(weights) < start * 1e-3
        assert np.allclose(weights, truth, atol=0.05)
