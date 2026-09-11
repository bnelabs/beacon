"""Tests for threshold-secret-sharing dropout recovery in secure aggregation.

The properties that matter, and that are easy to get subtly wrong:

1. **Exactness is not lost.** With no dropout the DH-based masked round must still
   unmask to the plain weighted mean to floating-point precision, exactly as the
   deterministic pairwise construction did.
2. **Recovery is correct.** With up to ``n - threshold`` participants missing, the
   server reconstructs the missing keys from verified shares and returns the mean
   over the participants that did submit.
3. **Recovery is exact.** The recovered aggregate equals the aggregate of a
   no-dropout run over the same participants -- not merely approximately. The
   field/float boundary is the place this could quietly fail, so it is tested
   directly.
4. **It fails closed.** Above the dropout limit, or with too few/forged shares, it
   raises instead of returning a corrupted number.

Shamir secrecy itself (fewer than ``threshold`` shares reveal nothing) is
information-theoretic and is not proven by an execution test; what is tested here
is that reconstruction *refuses* below the threshold and that a corrupted share
is detected by the Feldman commitments.
"""

from __future__ import annotations

import json
from dataclasses import replace
from itertools import combinations

import numpy as np
import pytest

from backend.modules.engine.federated import (
    FIELD_GENERATOR,
    FIELD_PRIME,
    SHARING_PRIME,
    WEIGHTING_SCHEMES,
    ClientUpdate,
    SecureAggregationError,
    federated_average,
    plan_secure_round,
    secure_aggregate_with_dropout,
    shamir_reconstruct,
    shamir_split,
)
from backend.modules.engine.federated import ShamirShare


def make_updates(seed: int = 7, n: int = 5, dim: int = 6):
    """A deterministic batch of plaintext updates with distinct weights."""
    rng = np.random.default_rng(seed)
    return [
        ClientUpdate(
            f"C{i}",
            rng.normal(size=dim),
            n_samples=100 * (i + 1),
            risk_weight=1.0 + 0.5 * i,
        )
        for i in range(n)
    ]


def run_recovery(plan, present_ids, *, renormalize: bool = True, shares=None):
    """Drive the server side: receive ``present_ids`` and recover the rest."""
    present = list(present_ids)
    received = [plan.masked_updates[cid] for cid in present]
    dropped = [cid for cid in plan.client_ids if cid not in set(present)]
    if shares is None:
        shares = plan.recovery_shares(dropped, present)
    return secure_aggregate_with_dropout(
        received,
        plan.server_state(),
        recovery_shares=shares,
        renormalize=renormalize,
    )


class TestShamirSecretSharing:
    @pytest.mark.parametrize("n,threshold", [(3, 2), (5, 2), (5, 3), (5, 5), (8, 3), (6, 4)])
    def test_every_threshold_subset_recovers_the_secret(self, n, threshold):
        secret = 123456789
        dealing = shamir_split(secret, n, threshold, rng=np.random.default_rng(0))
        for subset in combinations(dealing.shares, threshold):
            assert shamir_reconstruct(list(subset), threshold=threshold) == secret

    def test_large_field_secret_round_trips_exactly(self):
        secret = SHARING_PRIME - 1
        dealing = shamir_split(secret, 5, 3, rng=np.random.default_rng(1))
        assert shamir_reconstruct(list(dealing.shares[:3]), threshold=3) == secret

    def test_fewer_than_threshold_shares_raise(self):
        dealing = shamir_split(42, 5, 3, rng=np.random.default_rng(2))
        with pytest.raises(SecureAggregationError, match="need 3 distinct valid shares"):
            shamir_reconstruct(list(dealing.shares[:2]), threshold=3)

    def test_conflicting_shares_for_the_same_index_raise(self):
        dealing = shamir_split(42, 5, 2, rng=np.random.default_rng(3))
        first = dealing.shares[0]
        conflict = ShamirShare(first.x, (first.y + 1) % SHARING_PRIME)
        with pytest.raises(SecureAggregationError, match="conflicting shares"):
            shamir_reconstruct([first, conflict, dealing.shares[1]], threshold=2)

    def test_duplicate_identical_shares_are_harmless(self):
        dealing = shamir_split(42, 5, 2, rng=np.random.default_rng(4))
        shares = [dealing.shares[0], dealing.shares[0], dealing.shares[1]]
        assert shamir_reconstruct(shares, threshold=2) == 42

    def test_all_shares_lie_on_the_committed_polynomial(self):
        dealing = shamir_split(987654321, 6, 4, rng=np.random.default_rng(5))
        assert all(dealing.commitments.verify(share) for share in dealing.shares)

    def test_a_tampered_share_fails_verification(self):
        dealing = shamir_split(987654321, 5, 3, rng=np.random.default_rng(5))
        original = dealing.shares[0]
        tampered = ShamirShare(original.x, (original.y + 1) % SHARING_PRIME)
        assert not dealing.commitments.verify(tampered)

    def test_a_forged_index_fails_verification(self):
        dealing = shamir_split(987654321, 5, 3, rng=np.random.default_rng(5))
        # Holder 1's value offered as if it were holder 2's.
        forged = ShamirShare(dealing.shares[1].x, dealing.shares[0].y)
        assert not dealing.commitments.verify(forged)

    def test_the_constant_commitment_is_the_public_key(self):
        secret = 555555555
        dealing = shamir_split(secret, 5, 3, rng=np.random.default_rng(6))
        assert dealing.commitments.commitments[0] == pow(
            FIELD_GENERATOR, secret, FIELD_PRIME
        )

    def test_parameter_validation(self):
        with pytest.raises(ValueError, match="threshold"):
            shamir_split(1, 4, 0, rng=np.random.default_rng(0))
        with pytest.raises(ValueError, match="threshold"):
            shamir_split(1, 4, 5, rng=np.random.default_rng(0))
        with pytest.raises(ValueError, match="field element"):
            shamir_split(SHARING_PRIME, 4, 2, rng=np.random.default_rng(0))
        with pytest.raises(ValueError, match="positive"):
            shamir_split(1, 0, 1, rng=np.random.default_rng(0))


class TestExactnessWithoutDropout:
    @pytest.mark.parametrize("scheme", WEIGHTING_SCHEMES)
    def test_masked_round_unmasks_to_the_plain_mean(self, scheme):
        """The dropout machinery must not cost the original exactness property."""
        batch = make_updates()
        plan = plan_secure_round(batch, weighting=scheme, round_id=0, seed=9)
        result = run_recovery(plan, plan.client_ids)
        plain = federated_average(batch, weighting=scheme)
        assert result.dropped_clients == ()
        assert result.n_clients == len(batch)
        assert np.allclose(result.weights, plain.weights, atol=1e-9)

    def test_dh_pairwise_masks_cancel_exactly(self):
        batch = make_updates(n=6, dim=8)
        plan = plan_secure_round(batch, weighting="uniform", seed=2)
        total_mask = np.zeros(8)
        for update in batch:
            weight = plan.contributions[update.client_id]
            total_mask += plan.masked_updates[update.client_id].weights - weight * update.weights
        assert np.abs(total_mask).max() < 1e-9

    def test_masked_updates_are_not_the_plaintext(self):
        batch = make_updates()
        plan = plan_secure_round(batch, weighting="samples", seed=3)
        for update in batch:
            weight = plan.contributions[update.client_id]
            hidden = plan.masked_updates[update.client_id].weights
            assert np.abs(hidden - weight * update.weights).max() > 1.0


class TestDropoutRecovery:
    @pytest.mark.parametrize(
        "n,threshold,dropped",
        [
            (5, 2, 3),  # at the limit
            (5, 2, 2),  # just below
            (5, 3, 2),  # at the limit
            (5, 3, 1),  # just below
            (6, 4, 2),
            (6, 4, 1),
            (7, 2, 5),
            (4, 2, 2),
        ],
    )
    def test_recovery_at_and_below_the_dropout_limit(self, n, threshold, dropped):
        """Tolerating ``n - threshold`` dropouts, exactly."""
        batch = make_updates(n=n, dim=7)
        plan = plan_secure_round(
            batch, weighting="risk", round_id=3, threshold=threshold, seed=11
        )
        present = list(plan.client_ids[: n - dropped])
        missing = tuple(cid for cid in plan.client_ids if cid not in set(present))

        result = run_recovery(plan, present)

        assert result.dropped_clients == missing
        assert result.n_clients == len(present)
        present_updates = [u for u in batch if u.client_id in set(present)]
        plain = federated_average(present_updates, weighting="risk")
        assert np.allclose(result.weights, plain.weights, atol=1e-9)

    def test_recovery_works_for_an_arbitrary_dropout_pattern(self):
        """Not just a suffix: drop spread-out participants."""
        batch = make_updates(n=6, dim=7)
        plan = plan_secure_round(batch, weighting="samples", threshold=3, seed=12)
        present = ["C0", "C2", "C5"]  # three dropped, threshold 3, at the limit
        result = run_recovery(plan, present)
        assert set(result.dropped_clients) == {"C1", "C3", "C4"}
        present_updates = [u for u in batch if u.client_id in set(present)]
        assert np.allclose(
            result.weights,
            federated_average(present_updates, weighting="samples").weights,
            atol=1e-9,
        )

    def test_recovered_aggregate_equals_a_no_dropout_run_over_the_same_participants(self):
        """Requirement (d): recovery is exact, not an approximation.

        The recovered value is compared against a *separate* no-dropout round run
        over exactly the surviving participants, and against the unmasked
        baseline. Both must agree to floating-point precision.
        """
        batch = make_updates(n=6, dim=7)
        full_plan = plan_secure_round(
            batch, weighting="risk", round_id=4, threshold=3, seed=13
        )
        present = ["C1", "C2", "C4", "C5"]
        recovered = run_recovery(full_plan, present)

        survivors = [u for u in batch if u.client_id in set(present)]
        clean_plan = plan_secure_round(
            survivors, weighting="risk", round_id=4, threshold=3, seed=999
        )
        clean = run_recovery(clean_plan, present)

        assert np.allclose(recovered.weights, clean.weights, atol=1e-9)
        assert np.allclose(
            recovered.weights,
            federated_average(survivors, weighting="risk").weights,
            atol=1e-9,
        )

    def test_renormalization_can_be_disabled_to_get_the_weighted_sum(self):
        batch = make_updates(n=5, dim=6)
        plan = plan_secure_round(batch, weighting="samples", threshold=3, seed=14)
        present = ["C0", "C1", "C2", "C3"]
        raw = run_recovery(plan, present, renormalize=False)
        reference = sum(
            plan.contributions[u.client_id] * u.weights
            for u in batch
            if u.client_id in set(present)
        )
        assert np.allclose(raw.weights, reference, atol=1e-9)

    @pytest.mark.parametrize(
        "n,threshold,dropped",
        [(5, 2, 4), (5, 3, 3), (6, 4, 3), (4, 2, 3), (7, 4, 4)],
    )
    def test_above_the_dropout_limit_is_refused(self, n, threshold, dropped):
        batch = make_updates(n=n, dim=6)
        plan = plan_secure_round(
            batch, weighting="samples", threshold=threshold, seed=15
        )
        present = list(plan.client_ids[: n - dropped])
        with pytest.raises(SecureAggregationError, match="unrecoverable"):
            run_recovery(plan, present, shares={})

    def test_missing_recovery_shares_are_refused(self):
        plan = plan_secure_round(make_updates(n=5), threshold=3, seed=16)
        present = list(plan.client_ids[:3])
        # Exactly at the survival limit, but the server collected no shares.
        with pytest.raises(SecureAggregationError, match="valid shares"):
            run_recovery(plan, present, shares={})

    def test_unknown_client_is_refused(self):
        plan = plan_secure_round(make_updates(n=4), threshold=2, seed=17)
        stranger = ClientUpdate("ZZ", np.ones(6), n_samples=1)
        with pytest.raises(SecureAggregationError, match="unknown clients"):
            secure_aggregate_with_dropout([stranger], plan.server_state())

    def test_result_serialises(self):
        plan = plan_secure_round(make_updates(n=5), weighting="risk", threshold=3, seed=18)
        present = list(plan.client_ids[:3])
        result = run_recovery(plan, present)
        json.dumps(result.to_dict(), allow_nan=False)


class TestMaliciousSharesAndDealers:
    def test_a_single_corrupted_share_is_discarded_and_recovery_stays_exact(self):
        batch = make_updates(n=5, dim=6)
        plan = plan_secure_round(batch, weighting="samples", threshold=2, seed=19)
        present = ["C0", "C1", "C2", "C3"]  # four survivors, C4 dropped
        good = plan.recovery_shares(["C4"], present)["C4"]
        corrupted = list(good)
        corrupted[0] = ShamirShare(
            corrupted[0].x, (corrupted[0].y + 1) % SHARING_PRIME
        )

        result = run_recovery(plan, present, shares={"C4": corrupted})

        present_updates = [u for u in batch if u.client_id in set(present)]
        assert np.allclose(
            result.weights,
            federated_average(present_updates, weighting="samples").weights,
            atol=1e-9,
        )

    def test_corruption_that_drops_below_threshold_is_refused(self):
        plan = plan_secure_round(make_updates(n=5), threshold=2, seed=20)
        present = ["C0", "C1", "C2", "C3"]
        good = list(plan.recovery_shares(["C4"], present)["C4"])
        for index in range(3):
            good[index] = ShamirShare(
                good[index].x, (good[index].y + 1) % SHARING_PRIME
            )
        with pytest.raises(SecureAggregationError, match="valid shares"):
            run_recovery(plan, present, shares={"C4": good})

    def test_a_commitment_inconsistent_with_the_public_key_is_refused(self):
        """A dealer that shares a different polynomial is caught before use."""
        plan = plan_secure_round(make_updates(n=4), threshold=2, seed=21)
        state = plan.server_state()
        swapped = dict(state.commitments)
        swapped["C3"] = state.commitments["C2"]
        forged_state = replace(state, commitments=swapped)
        present = ["C0", "C1", "C2"]
        shares = plan.recovery_shares(["C3"], present)

        with pytest.raises(SecureAggregationError, match="inconsistent with its public key"):
            secure_aggregate_with_dropout(
                [plan.masked_updates[c] for c in present],
                forged_state,
                recovery_shares=shares,
            )

    def test_a_corrupted_share_cannot_forge_a_consistent_dealing(self):
        """Only shares on the committed polynomial survive verification.

        A holder cannot invent a share that satisfies the dealer's commitments
        without knowing the polynomial, which is what ``threshold`` protects.
        """
        dealing = shamir_split(777, 5, 3, rng=np.random.default_rng(22))
        for index in range(5):
            fabricated = ShamirShare(
                dealing.shares[index].x,
                (dealing.shares[index].y + 12345) % SHARING_PRIME,
            )
            assert not dealing.commitments.verify(fabricated)
