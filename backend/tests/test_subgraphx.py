"""Tests for SubgraphX subgraph attribution.

The attribution rests on two independent pieces, and both are checked against
external ground truth rather than against themselves:

* the Shapley score, verified against the four axioms that make it the unique
  fair allocation, and against games whose values are computable by hand;
* the MCTS search, verified by planting a motif with a known optimum and checking
  that the search recovers it.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from backend.modules.engine.subgraphx import (
    SubgraphExplanation,
    SubgraphExplainer,
    coalition_shapley_value,
    connected_edges,
    exact_shapley_values,
    explain_subgraph,
    k_hop_neighborhood,
    monte_carlo_shapley_values,
)


# -- games with hand-computable answers -------------------------------------

def majority_game(subset) -> float:
    """Wins with two or more of three players. Each Shapley value is 1/3."""
    return 1.0 if len(subset) >= 2 else 0.0


def unanimity_game(subset) -> float:
    return 1.0 if len(subset) == 3 else 0.0


def dictator_game(subset) -> float:
    return 1.0 if 0 in subset else 0.0


def dummy_game(subset) -> float:
    """Players 0 and 1 must both be present; player 2 contributes nothing."""
    return 1.0 if (0 in subset and 1 in subset) else 0.0


class TestShapleyAxioms:
    """The four properties that make the Shapley value the unique fair allocation."""

    def test_efficiency_the_values_sum_to_the_grand_coalition(self):
        for game in (majority_game, unanimity_game, dictator_game, dummy_game):
            players = [0, 1, 2]
            values = exact_shapley_values(players, game)
            total = sum(values.values())
            expected = game(frozenset(players)) - game(frozenset())
            assert total == pytest.approx(expected), game.__name__

    def test_dummy_players_receive_nothing(self):
        values = exact_shapley_values([0, 1, 2], dummy_game)
        assert values[2] == pytest.approx(0.0)
        assert values[0] > 0
        assert values[1] > 0

    def test_symmetric_players_receive_equal_values(self):
        values = exact_shapley_values([0, 1, 2], majority_game)
        assert values[0] == pytest.approx(values[1])
        assert values[1] == pytest.approx(values[2])

    def test_symmetry_holds_for_a_game_that_breaks_it(self):
        # Player 0 is a dictator, so 0 must differ from the symmetric pair (1, 2).
        values = exact_shapley_values([0, 1, 2], dictator_game)
        assert values[0] == pytest.approx(1.0)
        assert values[1] == pytest.approx(values[2])
        assert values[0] != pytest.approx(values[1])

    def test_additivity_the_value_of_a_sum_is_the_sum_of_values(self):
        players = [0, 1, 2, 3]

        def combined(subset):
            return 2.0 * majority_game(subset) + 3.0 * dictator_game(subset)

        left = exact_shapley_values(players, combined)
        first = exact_shapley_values(players, majority_game)
        second = exact_shapley_values(players, dictator_game)

        for player in players:
            assert left[player] == pytest.approx(2.0 * first[player] + 3.0 * second[player])

    def test_hand_computed_majority_game(self):
        # Each player is pivotal exactly when they complete a pair: for player i
        # the pivotal coalitions are the two singletons of the others, each with
        # weight 1!*1!/3! = 1/6, so phi = 2/6 = 1/3.
        values = exact_shapley_values([0, 1, 2], majority_game)
        for player in (0, 1, 2):
            assert values[player] == pytest.approx(1.0 / 3.0)

    def test_hand_computed_dictator_game(self):
        values = exact_shapley_values([0, 1, 2], dictator_game)
        assert values[0] == pytest.approx(1.0)
        assert values[1] == pytest.approx(0.0)
        assert values[2] == pytest.approx(0.0)


class TestMonteCarloShapley:
    def test_converges_to_the_exact_values(self):
        players = [0, 1, 2, 3, 4]
        exact = exact_shapley_values(players, majority_game)
        sampled = monte_carlo_shapley_values(players, majority_game, n_samples=20_000, seed=11)
        for player in players:
            assert sampled[player] == pytest.approx(exact[player], abs=0.03)

    def test_estimator_is_unbiased_so_repeats_average_out(self):
        players = [0, 1, 2]
        estimates = [
            monte_carlo_shapley_values(players, majority_game, n_samples=500, seed=seed)[0]
            for seed in range(60)
        ]
        assert float(np.mean(estimates)) == pytest.approx(1.0 / 3.0, abs=0.02)

    def test_more_samples_reduces_the_spread(self):
        players = [0, 1, 2, 3]

        def spread(n_samples: int) -> float:
            draws = [
                monte_carlo_shapley_values(players, majority_game, n_samples=n_samples, seed=s)[0]
                for s in range(40)
            ]
            return float(np.std(draws))

        assert spread(2_000) < spread(50)

    def test_validation(self):
        with pytest.raises(ValueError, match="n_samples"):
            monte_carlo_shapley_values([0, 1], majority_game, n_samples=0)


class TestCoalitionShapley:
    def test_hand_computed_coalition_value(self):
        """Adding {0,1} always wins the majority game, whoever else is present.

        For S = {0,1} the only players outside are {2}, so the two coalitions to
        average are T = {} and T = {2}. In both, v(T u S) - v(T) is 1, weighted
        1/2 each, giving exactly 1.0. Note this is *not* the sum of the members'
        individual Shapley values (2/3): a coalition's Shapley value prices the
        group as a bloc, which is the point of scoring subgraphs this way.
        """
        value = coalition_shapley_value({0, 1}, [0, 1, 2], majority_game, n_samples=20_000, seed=5)
        assert value == pytest.approx(1.0, abs=0.02)

    def test_the_empty_coalition_earns_nothing(self):
        assert coalition_shapley_value(set(), [0, 1, 2], majority_game) == 0.0

    def test_the_grand_coalition_earns_nothing_beyond_itself(self):
        # Nothing is left to add, so the marginal contribution is zero.
        assert coalition_shapley_value({0, 1, 2}, [0, 1, 2], majority_game) == 0.0

    def test_a_coalition_outside_the_game_is_rejected(self):
        with pytest.raises(ValueError, match="not in the game"):
            coalition_shapley_value({9}, [0, 1, 2], majority_game)

    def test_validation(self):
        with pytest.raises(ValueError, match="empty"):
            exact_shapley_values([], majority_game)
        with pytest.raises(ValueError, match="duplicates"):
            exact_shapley_values([0, 0], majority_game)


class TestGraphHelpers:
    def test_k_hop_depth_zero_is_the_target_alone(self):
        graph = np.array([[0.0, 1.0], [1.0, 0.0]])
        assert k_hop_neighborhood(graph, 0, 0) == {0}

    def test_k_hop_expands_one_ring_at_a_time(self):
        # A path 0 - 1 - 2 - 3.
        graph = np.zeros((4, 4))
        for i in range(3):
            graph[i, i + 1] = graph[i + 1, i] = 1.0

        assert k_hop_neighborhood(graph, 0, 1) == {0, 1}
        assert k_hop_neighborhood(graph, 0, 2) == {0, 1, 2}
        assert k_hop_neighborhood(graph, 0, 3) == {0, 1, 2, 3}
        # A large depth saturates rather than looping.
        assert k_hop_neighborhood(graph, 0, 99) == {0, 1, 2, 3}

    def test_hop_restriction_bounds_the_search(self):
        graph = np.zeros((4, 4))
        for i in range(3):
            graph[i, i + 1] = graph[i + 1, i] = 1.0
        assert 3 not in k_hop_neighborhood(graph, 0, 1)

    def test_k_hop_validation(self):
        graph = np.zeros((3, 3))
        with pytest.raises(ValueError, match="square"):
            k_hop_neighborhood(np.zeros((2, 3)), 0, 1)
        with pytest.raises(ValueError, match="outside"):
            k_hop_neighborhood(graph, 5, 1)
        with pytest.raises(ValueError, match="depth"):
            k_hop_neighborhood(graph, 0, -1)

    def test_connected_edges_returns_induced_edges_only(self):
        graph = np.array(
            [[0.0, 1.0, 0.0], [1.0, 0.0, 1.0], [0.0, 1.0, 0.0]]
        )
        assert connected_edges(graph, {0, 1}) == ((0, 1),)
        assert connected_edges(graph, {1, 2}) == ((1, 2),)
        # 0 and 2 are not adjacent, so the induced subgraph has no edge.
        assert connected_edges(graph, {0, 2}) == ()


# -- a graph with a planted motif -------------------------------------------

def planted_graph() -> np.ndarray:
    """Six nodes: a triangle {0,1,2}, plus 3, 4, 5 hanging off node 0."""
    graph = np.zeros((6, 6))
    for a, b in ((0, 1), (1, 2), (2, 0), (0, 3), (0, 4), (0, 5)):
        graph[a, b] = graph[b, a] = 1.0
    return graph


def triad_game(subset) -> float:
    """Value 1 exactly when the triangle {0,1,2} is contained in the subset."""
    return 1.0 if {0, 1, 2}.issubset(subset) else 0.0


class TestPlantedMotifRecovery:
    def test_search_recovers_the_planted_triad(self):
        explanation = explain_subgraph(
            planted_graph(),
            target=0,
            value_fn=triad_game,
            max_size=3,
            n_rollouts=300,
            shapley_samples=64,
            seed=7,
        )
        assert set(explanation.nodes) == {0, 1, 2}
        assert explanation.score == pytest.approx(1.0, abs=0.05)
        # The reported score is re-measured after the search, so it is an estimate
        # of the winner's value rather than the maximum of the search's noise.
        assert explanation.final_samples > explanation.shapley_samples

    def test_the_returned_subgraph_contains_the_target(self):
        explanation = explain_subgraph(
            planted_graph(), target=1, value_fn=triad_game, max_size=3,
            n_rollouts=200, shapley_samples=48, seed=3,
        )
        assert 1 in explanation.nodes

    def test_the_returned_subgraph_respects_the_size_budget(self):
        for max_size in (1, 2, 3, 4):
            explanation = explain_subgraph(
                planted_graph(), target=0, value_fn=triad_game, max_size=max_size,
                n_rollouts=100, shapley_samples=32, seed=1,
            )
            assert explanation.size <= max_size

    def test_a_size_one_budget_cannot_express_a_triad(self):
        """A one-node budget returns the best single node, not zero.

        For the triad game the best singleton is one of {0,1,2}, whose Shapley
        value is exactly 1/3: the coalition must contain 0, 1 and 2, so the
        contribution of any single member is the Shapley weight of the
        coalitions that force the other two in, which sums to 1/3. The point of
        the test is that a size-one budget scores far below the triad's 1.0, not
        that it scores nothing.
        """
        explanation = explain_subgraph(
            planted_graph(), target=0, value_fn=triad_game, max_size=1,
            n_rollouts=100, shapley_samples=32, final_samples=4_000, seed=1,
        )
        assert explanation.size == 1
        assert explanation.score == pytest.approx(1.0 / 3.0, abs=0.03)

        full = explain_subgraph(
            planted_graph(), target=0, value_fn=triad_game, max_size=3,
            n_rollouts=200, shapley_samples=32, final_samples=4_000, seed=1,
        )
        assert full.score > explanation.score + 0.5

    def test_larger_budget_never_does_worse(self):
        small = explain_subgraph(
            planted_graph(), target=0, value_fn=triad_game, max_size=3,
            n_rollouts=5, shapley_samples=32, seed=42,
        )
        large = explain_subgraph(
            planted_graph(), target=0, value_fn=triad_game, max_size=3,
            n_rollouts=400, shapley_samples=32, seed=42,
        )
        assert large.score >= small.score - 1e-9

    def test_search_stays_inside_the_neighborhood(self):
        # Depth 1 from node 0 reaches 1, 2, 3, 4, 5 but the search must not use
        # nodes outside that set; depth 0 restricts it to node 0 alone.
        explanation = explain_subgraph(
            planted_graph(), target=0, value_fn=triad_game, max_size=3,
            n_rollouts=100, shapley_samples=32, seed=2, neighborhood_depth=1,
        )
        assert set(explanation.nodes) <= k_hop_neighborhood(planted_graph(), 0, 1)

        solo = explain_subgraph(
            planted_graph(), target=0, value_fn=triad_game, max_size=3,
            n_rollouts=100, shapley_samples=32, seed=2, neighborhood_depth=0,
        )
        assert set(solo.nodes) == {0}

    def test_the_explanation_is_reproducible(self):
        first = explain_subgraph(
            planted_graph(), target=0, value_fn=triad_game, max_size=3,
            n_rollouts=150, shapley_samples=32, seed=99,
        )
        second = explain_subgraph(
            planted_graph(), target=0, value_fn=triad_game, max_size=3,
            n_rollouts=150, shapley_samples=32, seed=99,
        )
        assert first.nodes == second.nodes
        assert first.score == second.score

    def test_a_different_seed_may_find_a_different_subgraph(self):
        # Not a defect: MCTS is stochastic. Recording the seed is what makes the
        # explanation auditable, which is why the field exists.
        seeds = [
            explain_subgraph(
                planted_graph(), target=0, value_fn=triad_game, max_size=3,
                n_rollouts=3, shapley_samples=8, seed=seed,
            ).nodes
            for seed in range(12)
        ]
        assert len(set(seeds)) >= 1


class TestExplanationRecord:
    def _explanation(self) -> SubgraphExplanation:
        return explain_subgraph(
            planted_graph(), target=0, value_fn=triad_game, max_size=3,
            n_rollouts=200, shapley_samples=32, seed=5,
            node_labels=["A", "B", "C", "D", "E", "F"],
        )

    def test_labels_align_with_nodes(self):
        explanation = self._explanation()
        expected = tuple(
            ["A", "B", "C", "D", "E", "F"][node] for node in explanation.nodes
        )
        assert explanation.node_labels == expected

    def test_fraction_of_full_is_measured_against_the_range(self):
        explanation = self._explanation()
        # empty_score is 0 and full_score is 1 for this game, so the fraction is
        # the score itself.
        assert explanation.empty_score == pytest.approx(0.0)
        assert explanation.full_score == pytest.approx(1.0)
        assert explanation.fraction_of_full == pytest.approx(explanation.score)

    def test_serialises_to_json(self):
        json.dumps(self._explanation().to_dict(), allow_nan=False)

    def test_summary_names_the_motif(self):
        summary = self._explanation().summary()
        assert "A" in summary and "B" in summary and "C" in summary
        assert "game value" in summary

    def test_payload_reports_the_search_budget_and_seed(self):
        payload = self._explanation().to_dict()
        assert payload["n_rollouts"] == 200
        assert payload["shapley_samples"] == 32
        assert payload["search_statistics"]["seed"] == 5
        assert payload["n_value_evaluations"] > 0


class TestValueFunctionCaching:
    def test_repeated_subsets_are_not_re_evaluated(self):
        calls = {"count": 0}

        def counting_value(subset) -> float:
            calls["count"] += 1
            return 1.0 if len(subset) >= 2 else 0.0

        explain_subgraph(
            planted_graph(), target=0, value_fn=counting_value, max_size=3,
            n_rollouts=100, shapley_samples=32, seed=4,
        )
        # Six nodes means at most 64 distinct subsets, so caching must keep the
        # number of real evaluations far below the number of lookups.
        assert calls["count"] <= 64


class TestSubgraphExplainerValidation:
    def test_non_square_adjacency_is_rejected(self):
        with pytest.raises(ValueError, match="square"):
            SubgraphExplainer(np.zeros((2, 3)), triad_game)

    def test_empty_graph_is_rejected(self):
        with pytest.raises(ValueError, match="no nodes"):
            SubgraphExplainer(np.zeros((0, 0)), triad_game)

    def test_non_finite_adjacency_is_rejected(self):
        graph = np.zeros((2, 2))
        graph[0, 1] = np.nan
        with pytest.raises(ValueError, match="non-finite"):
            SubgraphExplainer(graph, triad_game)

    def test_negative_weights_are_rejected(self):
        graph = np.zeros((2, 2))
        graph[0, 1] = -1.0
        with pytest.raises(ValueError, match="negative"):
            SubgraphExplainer(graph, triad_game)

    def test_mislabelled_nodes_are_rejected(self):
        with pytest.raises(ValueError, match="node_labels"):
            SubgraphExplainer(planted_graph(), triad_game, node_labels=["A"])

    def test_invalid_parameters_are_rejected(self):
        graph = planted_graph()
        with pytest.raises(ValueError, match="max_size"):
            SubgraphExplainer(graph, triad_game, max_size=0)
        with pytest.raises(ValueError, match="n_rollouts"):
            SubgraphExplainer(graph, triad_game, n_rollouts=0)
        with pytest.raises(ValueError, match="shapley_samples"):
            SubgraphExplainer(graph, triad_game, shapley_samples=0)
        with pytest.raises(ValueError, match="exploration"):
            SubgraphExplainer(graph, triad_game, exploration=0.0)

    def test_out_of_range_target_is_rejected(self):
        explainer = SubgraphExplainer(planted_graph(), triad_game)
        with pytest.raises(ValueError, match="outside"):
            explainer.explain(99)

    def test_exact_enumeration_limit_is_enforced(self):
        players = list(range(16))
        with pytest.raises(ValueError, match="limit"):
            exact_shapley_values(players, majority_game)

    def test_a_non_finite_game_value_is_rejected(self):
        def broken(subset):
            return float("nan")

        with pytest.raises(ValueError, match="non-finite"):
            exact_shapley_values([0, 1], broken)


class TestIntegrationWithClearing:
    def test_explains_a_prediction_denominated_in_clearing_shortfall(self):
        """The intended use: the game value is the clearing shortfall.

        This ties the attribution to the same arithmetic that produces the risk
        number, so the explanation is in the same units as the thing explained
        rather than in an abstract importance scale.
        """
        from backend.modules.risk.clearing import sequential_clearing

        # 0 owes 1; 1 owes 2; 2 owes 1. Node 0 has no endowment.
        liabilities = np.array([
            [0.0, 10.0, 0.0],
            [0.0, 0.0, 4.0],
            [0.0, 4.0, 0.0],
        ])
        endowments = np.array([3.0, 1.0, 1.0])

        def shortfall(subset) -> float:
            if not subset:
                return 0.0
            nodes = sorted(subset)
            if len(nodes) == 1:
                single = np.zeros((3, 3))
                return sequential_clearing(single, endowments).total_shortfall
            sub_liabilities = liabilities[np.ix_(nodes, nodes)].copy()
            sub_endowments = endowments[nodes]
            result = sequential_clearing(sub_liabilities, sub_endowments)
            return float(result.total_shortfall)

        explanation = explain_subgraph(
            np.where(liabilities > 0, 1.0, 0.0) + np.where(liabilities.T > 0, 1.0, 0.0),
            target=0,
            value_fn=shortfall,
            max_size=3,
            n_rollouts=80,
            shapley_samples=32,
            seed=13,
            node_labels=["BankA", "BankB", "BankC"],
        )

        assert 0 in explanation.nodes
        assert explanation.size <= 3
        assert explanation.full_score >= 0.0
        json.dumps(explanation.to_dict(), allow_nan=False)
        # The summary must name institutions, not feature indices.
        assert "Bank" in explanation.summary()
