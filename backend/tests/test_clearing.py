"""Tests for multiplex sequential (Eisenberg-Noe) clearing.

These lock in the properties that make the clearing vector a defensible
replacement for the additive contagion rule that previously lived in
``NetworkExplainer`` (``new_risk = current_risk + min(exposure / 1e9, 0.5)``).

The additive rule is checked against directly: a mutually-indebted ring with no
endowment clears in full under Eisenberg-Noe, because each bank's claim on its
debtor funds its obligation to its creditor. The additive rule assigned every
bank a shock proportional to its failed counterparty's gross exposure and so
flagged a network that nets to zero.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.modules.risk.clearing import (
    CAUSE_ILLIQUIDITY,
    CAUSE_INSOLVENCY,
    MultiplexClearingEngine,
    NetworkLayer,
    clear_multiplex,
    sequential_clearing,
)


def reference_map(
    layers,
    endowments,
    payments,
):
    """Independent implementation of the clearing map, for fixed-point checks.

    Deliberately written from the definition rather than reusing the engine's
    internals, so an error in the engine cannot satisfy its own test.
    """
    n = len(endowments)
    receipts = np.zeros(n)
    for layer in layers:
        liabilities = np.asarray(layer.liabilities, dtype=float)
        nominal = liabilities.sum(axis=1)
        ratios = np.divide(
            payments[layer.name], nominal, out=np.zeros(n), where=nominal > 0
        )
        receipts += liabilities.T @ ratios

    resources = np.asarray(endowments, dtype=float) + receipts
    ordered = sorted(layers, key=lambda layer: layer.seniority)
    out = {}
    remaining = np.maximum(resources, 0.0)
    for layer in ordered:
        nominal = np.asarray(layer.liabilities, dtype=float).sum(axis=1)
        pay = np.minimum(nominal, remaining)
        out[layer.name] = pay
        remaining = remaining - pay
    return out, resources


class TestSingleLayerClearing:
    def test_absolute_priority_never_pays_more_than_owed(self):
        liabilities = np.array([[0.0, 10.0, 0.0], [0.0, 0.0, 7.0], [4.0, 0.0, 0.0]])
        result = sequential_clearing(liabilities, [3.0, 1.0, 2.0])

        assert np.all(result.payments <= result.nominal_liabilities + 1e-12)

    def test_limited_liability_holds_at_the_solution(self):
        # A bank can never pay more than its endowment plus realised receipts.
        liabilities = np.array([[0.0, 10.0, 0.0], [0.0, 0.0, 7.0], [4.0, 0.0, 0.0]])
        endowments = [3.0, 1.0, 2.0]
        result = sequential_clearing(liabilities, endowments)

        layer = NetworkLayer(name="interbank", liabilities=liabilities, seniority=0)
        recomputed, _ = reference_map([layer], endowments, result.layer_payments)
        assert np.allclose(recomputed["interbank"], result.payments, atol=1e-9)

    def test_result_is_a_fixed_point_of_the_clearing_map(self):
        rng = np.random.default_rng(20260101)
        raw = rng.random((6, 6)) * 20.0
        liabilities = raw * (1.0 - np.eye(6))
        endowments = rng.random(6) * 15.0

        result = sequential_clearing(liabilities, endowments)
        layer = NetworkLayer(name="interbank", liabilities=liabilities, seniority=0)
        recomputed, resources = reference_map(
            [layer], endowments, result.layer_payments
        )

        assert result.converged
        assert np.allclose(recomputed["interbank"], result.payments, atol=1e-6)
        assert np.allclose(resources, result.resources, atol=1e-6)

    def test_payments_are_conserved_never_exceed_resources(self):
        rng = np.random.default_rng(7)
        liabilities = rng.random((5, 5)) * 10.0
        endowments = rng.random(5) * 10.0
        result = sequential_clearing(liabilities, endowments)

        # Total paid out cannot exceed what the system holds.
        assert result.payments.sum() <= result.resources.sum() + 1e-9
        # Nor can it exceed what was owed.
        assert result.payments.sum() <= result.nominal_liabilities.sum() + 1e-9

    def test_mutual_ring_nets_out_with_no_defaults(self):
        """The case the additive rule got wrong.

        Two banks each owe the other 20 with no external assets. Nothing is
        lost: each bank's incoming claim settles its outgoing obligation. The
        additive rule gave both a positive shock scaled by gross exposure and
        reported a cascade.
        """
        liabilities = np.array([[0.0, 20.0], [20.0, 0.0]])
        result = sequential_clearing(liabilities, [0.0, 0.0])

        assert result.n_defaults == 0
        assert np.allclose(result.payments, [20.0, 20.0])
        assert result.total_shortfall == pytest.approx(0.0)

    def test_gross_exposure_alone_does_not_create_a_default(self):
        # A long chain of fully-funded obligations clears, however large the
        # gross notional. Contagion depends on net position and capital, not on
        # the size of the exposure column.
        n = 12
        liabilities = np.zeros((n, n))
        for i in range(n - 1):
            liabilities[i, i + 1] = 1_000_000.0
        endowments = np.zeros(n)
        # Give the chain's terminal debtor enough to settle its obligation.
        endowments[0] = 1_000_000.0

        result = sequential_clearing(liabilities, endowments)
        assert result.n_defaults == 0
        assert result.total_shortfall == pytest.approx(0.0)


class TestDefaultClassification:
    def test_insolvency_when_assets_are_below_liabilities_at_par(self):
        # Owes 10, holds 4, is owed nothing: fails even if everyone else pays.
        result = sequential_clearing(
            np.array([[0.0, 10.0], [0.0, 0.0]]), [4.0, 0.0]
        )

        assert result.defaulted[0]
        assert result.causes[0] == CAUSE_INSOLVENCY
        assert result.payments[0] == pytest.approx(4.0)


def test_illiquidity_when_solvent_at_par_but_hit_by_a_counterparty():
    """Solvency and liquidity are distinguished.

    ``C`` owes ``A`` 10 and holds nothing, so it is insolvent regardless of
    anyone else. ``A`` is owed exactly 10 by ``C`` and also owes ``B`` 10, so
    with all claims honoured ``A`` is solvent. ``A`` fails only because ``C``
    did not pay: that failure is transmitted, and classified as illiquidity.
    """
    # 0 = A, 1 = B, 2 = C
    liabilities = np.array([
        [0.0, 10.0, 0.0],   # A owes B 10
        [0.0, 0.0, 0.0],    # B owes nothing
        [10.0, 0.0, 0.0],   # C owes A 10
    ])
    result = sequential_clearing(liabilities, [0.0, 0.0, 0.0])

    assert result.causes[2] == CAUSE_INSOLVENCY
    assert result.causes[0] == CAUSE_ILLIQUIDITY
    assert not result.defaulted[1]

    # The cascade runs from the fundamental failure outward.
    assert result.default_sequence() == ["node_2", "node_0"]


def test_propagation_order_is_recorded_in_rounds():
    liabilities = np.array([
        [0.0, 10.0, 0.0],
        [0.0, 0.0, 0.0],
        [10.0, 0.0, 0.0],
    ])
    result = sequential_clearing(liabilities, [0.0, 0.0, 0.0])

    assert len(result.default_rounds) == 2
    assert result.default_rounds[0] == [2]
    assert result.default_rounds[1] == [0]


def test_contagion_edges_name_the_transmitting_claim():
    liabilities = np.array([
        [0.0, 10.0, 0.0],   # A owes B 10
        [0.0, 0.0, 0.0],
        [10.0, 0.0, 0.0],   # C owes A 10
    ])
    result = sequential_clearing(
        liabilities, [0.0, 0.0, 0.0], node_ids=["A", "B", "C"]
    )

    edges = {(edge.source_id, edge.target_id): edge for edge in result.contagion_edges}
    assert ("C", "A") in edges, "C's failure must be traced into A"
    assert ("A", "B") in edges, "A's shortfall must be traced into B"
    assert edges[("C", "A")].loss == pytest.approx(10.0)


def test_losses_are_borne_by_creditors_in_proportion_to_claims():
    # Bank 1 and bank 2 each hold half of bank 0's 10 of liabilities; bank 0
    # holds 5, so each absorbs 2.5.
    liabilities = np.array([
        [0.0, 5.0, 5.0],
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
    ])
    result = sequential_clearing(liabilities, [5.0, 0.0, 0.0])

    assert result.losses_by_creditor[1] == pytest.approx(2.5)
    assert result.losses_by_creditor[2] == pytest.approx(2.5)


class TestMultiplexSeniority:
    def test_senior_layer_is_paid_before_junior_layer(self):
        senior = NetworkLayer(
            name="secured",
            liabilities=np.array([[0.0, 10.0], [0.0, 0.0]]),
            seniority=0,
        )
        junior = NetworkLayer(
            name="unsecured",
            liabilities=np.array([[0.0, 10.0], [0.0, 0.0]]),
            seniority=1,
        )
        result = clear_multiplex([senior, junior], [10.0, 0.0], node_ids=["A", "B"])

        # A holds 10 and owes 10 in each layer. Senior is satisfied in full.
        assert result.layer_payments["secured"][0] == pytest.approx(10.0)
        assert result.layer_payments["unsecured"][0] == pytest.approx(0.0)
        assert result.payments[0] == pytest.approx(10.0)

    def test_seniority_is_independent_of_declaration_order(self):
        senior = NetworkLayer(
            name="secured",
            liabilities=np.array([[0.0, 10.0], [0.0, 0.0]]),
            seniority=0,
        )
        junior = NetworkLayer(
            name="unsecured",
            liabilities=np.array([[0.0, 10.0], [0.0, 0.0]]),
            seniority=1,
        )

        declared_junior_first = clear_multiplex([junior, senior], [10.0, 0.0])
        declared_senior_first = clear_multiplex([senior, junior], [10.0, 0.0])

        assert np.allclose(
            declared_junior_first.payments, declared_senior_first.payments
        )
        assert declared_junior_first.layer_payments["secured"][0] == pytest.approx(10.0)

    def test_equal_seniority_layers_split_available_resources(self):
        first = NetworkLayer(
            name="a", liabilities=np.array([[0.0, 10.0], [0.0, 0.0]]), seniority=0
        )
        second = NetworkLayer(
            name="b", liabilities=np.array([[0.0, 10.0], [0.0, 0.0]]), seniority=0
        )
        result = clear_multiplex([first, second], [10.0, 0.0])

        # 10 of resources against 20 of same-rank claims: each layer receives the
        # shortfall pro rata, which for equal claims means 5 each.
        assert result.layer_payments["a"][0] == pytest.approx(5.0)
        assert result.layer_payments["b"][0] == pytest.approx(5.0)

    def test_multiplex_reduces_to_single_layer_when_only_one_layer(self):
        liabilities = np.array([[0.0, 10.0], [5.0, 0.0]])
        nodes = ["A", "B"]
        single = sequential_clearing(liabilities, [3.0, 2.0], node_ids=nodes)
        multiplex = clear_multiplex(
            [NetworkLayer(name="only", liabilities=liabilities, seniority=0)],
            [3.0, 2.0],
            node_ids=nodes,
        )

        assert np.allclose(single.payments, multiplex.payments)
        assert single.defaulted.tolist() == multiplex.defaulted.tolist()

    def test_receipts_are_pooled_across_layers(self):
        # B owes nothing in 'secured' but receives 10 in 'unsecured'; it uses
        # that receipt to pay its own 'secured' obligation to A.
        secured = NetworkLayer(
            name="secured",
            liabilities=np.array([[0.0, 0.0], [10.0, 0.0]]),
            seniority=0,
        )
        unsecured = NetworkLayer(
            name="unsecured",
            liabilities=np.array([[0.0, 10.0], [0.0, 0.0]]),
            seniority=1,
        )
        result = clear_multiplex([secured, unsecured], [0.0, 0.0], node_ids=["A", "B"])

        # A pays 10 to B in unsecured; B passes that 10 to A in secured.
        assert result.payments[0] == pytest.approx(10.0)
        assert result.payments[1] == pytest.approx(10.0)
        assert result.n_defaults == 0


class TestValidation:
    def test_negative_liabilities_are_rejected(self):
        with pytest.raises(ValueError, match="negative"):
            NetworkLayer("bad", np.array([[0.0, -1.0], [0.0, 0.0]]))

    def test_non_square_liabilities_are_rejected(self):
        with pytest.raises(ValueError):
            NetworkLayer("bad", np.array([[0.0, 1.0, 2.0], [0.0, 0.0, 0.0]]))

    def test_non_finite_liabilities_are_rejected(self):
        with pytest.raises(ValueError, match="non-finite"):
            NetworkLayer("bad", np.array([[0.0, np.nan], [0.0, 0.0]]))

    def test_negative_endowments_are_rejected(self):
        liabilities = np.array([[0.0, 1.0], [0.0, 0.0]])
        with pytest.raises(ValueError, match="non-negative"):
            sequential_clearing(liabilities, [-1.0, 0.0])

    def test_mismatched_endowment_length_is_rejected(self):
        liabilities = np.array([[0.0, 1.0], [0.0, 0.0]])
        with pytest.raises(ValueError, match="length"):
            sequential_clearing(liabilities, [1.0, 2.0, 3.0])

    def test_mismatched_layer_sizes_are_rejected(self):
        with pytest.raises(ValueError, match="node count"):
            MultiplexClearingEngine([
                NetworkLayer("a", np.zeros((2, 2))),
                NetworkLayer("b", np.zeros((3, 3))),
            ])

    def test_mismatched_node_ids_are_rejected(self):
        with pytest.raises(ValueError, match="node_ids"):
            MultiplexClearingEngine([NetworkLayer("a", np.zeros((2, 2)))], node_ids=["x"])

    def test_empty_network_is_rejected(self):
        with pytest.raises(ValueError):
            MultiplexClearingEngine([])


class TestResultShapes:
    def test_to_dict_is_json_serialisable(self):
        import json

        result = sequential_clearing(
            np.array([[0.0, 10.0], [0.0, 0.0]]), [4.0, 0.0], node_ids=["A", "B"]
        )
        json.dumps(result.to_dict(), allow_nan=False)

    def test_zero_liability_system_reports_no_defaults(self):
        result = sequential_clearing(np.zeros((3, 3)), [1.0, 2.0, 3.0])

        assert result.n_defaults == 0
        assert result.total_shortfall == pytest.approx(0.0)
        assert result.converged

    def test_isolated_node_keeps_its_endowment(self):
        # No liabilities at all: nothing is paid to anyone, and equity equals the
        # endowment.
        result = sequential_clearing(np.zeros((2, 2)), [7.0, 0.5])

        assert np.allclose(result.payments, [0.0, 0.0])
        assert np.allclose(result.equity, [7.0, 0.5])
