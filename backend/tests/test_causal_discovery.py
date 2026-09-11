"""Tests for causal structure discovery.

Three independent routes to the same object are exercised here, and the tests are
written so that a method agreeing only with itself cannot pass:

* the analytic acyclicity gradient against central finite differences, and the
  constraint value at matrices whose matrix exponential has a closed form
  (``tr exp([[0 1],[1 0]]) = 2 cosh 1``);
* the least-squares loss against a hand-computed value and its gradient against
  finite differences;
* NOTEARS' recovered graph against the DAG the data were generated from, and its
  skeleton against the partial-correlation skeleton -- a different method with
  different assumptions, so agreement is evidence and disagreement is a finding.

The recovery tests use colliders because a chain has no v-structure to orient it:
its reverse is in the same Markov equivalence class and carries the same
observational likelihood, so "recovered the chain backwards" is not an error the
method can be blamed for. The tests therefore assert exact edges on identifiable
graphs, and only the skeleton where the direction is not identified.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from backend.exceptions import DataQualityError
from backend.modules.engine.causal_discovery import (
    DagComparison,
    NoteArsConfig,
    NoteArsDiscovery,
    NoteArsResult,
    OrientationConflict,
    PartialCorrelationSkeleton,
    SkeletonResult,
    acyclicity_constraint,
    acyclicity_gradient,
    adjacency_to_parents,
    compare_dag,
    is_acyclic,
    least_squares_gradient,
    least_squares_loss,
    note_ars_objective,
    notears_linear,
    parents_to_adjacency,
    partial_correlation,
    resolve_w_bound,
    threshold_weights,
    topological_order,
    weights_to_parents,
)
from backend.modules.engine.tncm_vae import StructuralCausalModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_dag(names, edges, coefficient=2.0):
    """Build ``(parents, coefficients)`` containers from an edge list."""
    parents = {name: () for name in names}
    coefficients = {name: {} for name in names}
    for parent, child in edges:
        parents[child] = parents[child] + (parent,)
        coefficients[child][parent] = coefficient
    return parents, coefficients


def simulate_linear_sem(parents, coefficients, n_samples, seed, noise_scale=1.0):
    """Sample a linear SEM with independent Gaussian noise of equal variance.

    Nodes are filled in topological order, so each column is exactly
    ``sum_j a_ij x_j + noise_i``. The equal noise variance is not decoration: it
    is the assumption NOTEARS' least-squares loss relies on, and violating it in
    the generator would make every recovery assertion unfair.
    """
    names = list(parents)
    index = {name: position for position, name in enumerate(names)}
    rng = np.random.default_rng(seed)
    matrix = np.zeros((n_samples, len(names)))
    done = set()
    while len(done) < len(names):
        progressed = False
        for child in names:
            if child in done:
                continue
            if all(parent in done for parent in parents[child]):
                values = rng.normal(scale=noise_scale, size=n_samples)
                for parent in parents[child]:
                    values = values + coefficients[child][parent] * matrix[:, index[parent]]
                matrix[:, index[child]] = values
                done.add(child)
                progressed = True
        if not progressed:  # pragma: no cover - only reachable with a cyclic input
            raise AssertionError("the generator input contains a cycle")
    return matrix


def finite_difference_gradient(function, matrix, epsilon=1e-6):
    """Central finite differences of a scalar function of a matrix."""
    gradient = np.zeros_like(matrix)
    for row in range(matrix.shape[0]):
        for column in range(matrix.shape[1]):
            step = np.zeros_like(matrix)
            step[row, column] = epsilon
            gradient[row, column] = (
                function(matrix + step) - function(matrix - step)
            ) / (2.0 * epsilon)
    return gradient


def undirected(edges):
    """Edges as a set of frozensets, for skeleton comparisons."""
    return {frozenset(edge) for edge in edges}


# A five-node DAG with two colliders. A, B, C and E all have different noise
# scales because the variables accumulate upstream noise, which is what makes the
# equal-variance assumption bite and the orientation identifiable in the raw scale.
COLLIDER_CHAIN = make_dag(
    ["A", "B", "C", "D", "E"],
    [("A", "C"), ("B", "C"), ("C", "D"), ("D", "E")],
)

DIAMOND = make_dag(
    ["A", "B", "C", "D"],
    [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")],
)

CHAIN = make_dag(
    ["A", "B", "C", "D", "E"],
    [("A", "B"), ("B", "C"), ("C", "D"), ("D", "E")],
)


def true_edges(parents):
    return sorted((parent, child) for child, ps in parents.items() for parent in ps)


# ---------------------------------------------------------------------------
# The acyclicity constraint and its gradient
# ---------------------------------------------------------------------------


class TestAcyclicityConstraint:
    def test_is_zero_for_a_dag(self):
        """A triangular weight matrix is nilpotent, so exp has trace d."""
        weights = np.array(
            [[0.0, 0.5, 0.0], [0.0, 0.0, 0.8], [0.0, 0.0, 0.0]]
        )
        assert acyclicity_constraint(weights) == pytest.approx(0.0, abs=1e-12)

    def test_matches_the_closed_form_for_a_two_cycle(self):
        """tr exp([[0,1],[1,0]]) = 2 cosh(1), so h = 2 cosh(1) - 2 exactly."""
        weights = np.array([[0.0, 1.0], [1.0, 0.0]])
        assert acyclicity_constraint(weights) == pytest.approx(
            2.0 * math.cosh(1.0) - 2.0, rel=1e-12
        )

    def test_is_positive_for_a_cycle(self):
        weights = np.array([[0.0, 1.0], [1.0, 0.0]])
        assert acyclicity_constraint(weights) > 0.0

    def test_is_positive_for_a_self_loop(self):
        """A self-edge is a cycle, so h > 0: exp([[w^2]]) has trace e^{w^2}."""
        weights = np.array([[1.0]])
        assert acyclicity_constraint(weights) == pytest.approx(math.e - 1.0, rel=1e-12)

    def test_is_zero_for_the_zero_matrix(self):
        assert acyclicity_constraint(np.zeros((4, 4))) == pytest.approx(0.0, abs=1e-12)

    def test_is_non_negative_on_random_matrices(self):
        """h >= 0 everywhere; a negative value would mean a broken implementation."""
        rng = np.random.default_rng(11)
        for _ in range(5):
            weights = rng.normal(size=(4, 4))
            assert acyclicity_constraint(weights) >= 0.0

    def test_gradient_matches_finite_differences(self):
        rng = np.random.default_rng(3)
        weights = rng.normal(size=(4, 4))
        analytic = acyclicity_gradient(weights)
        numeric = finite_difference_gradient(acyclicity_constraint, weights)
        assert np.allclose(analytic, numeric, rtol=1e-5, atol=1e-6)

    def test_gradient_of_a_dag_is_not_trivially_zero(self):
        """Guard against a gradient that passes the FD check only by being 0.

        For a strictly triangular ``W`` the constraint is *identically* zero --
        every triangular matrix is nilpotent, so ``tr exp(W o W) = d`` everywhere
        in that region and the true gradient vanishes. That is why the check uses a
        matrix with a cycle, where the derivative is known to be non-zero.
        """
        weights = np.array([[0.0, 0.5], [0.1, 0.0]])
        gradient = acyclicity_gradient(weights)
        assert abs(gradient[0, 1]) > 1e-3
        assert np.allclose(
            gradient,
            finite_difference_gradient(acyclicity_constraint, weights),
            rtol=1e-5,
            atol=1e-7,
        )

    def test_rejects_a_non_square_matrix(self):
        with pytest.raises(ValueError, match="square"):
            acyclicity_constraint(np.zeros((2, 3)))

    def test_rejects_non_finite_entries(self):
        with pytest.raises(ValueError, match="non-finite"):
            acyclicity_constraint(np.array([[0.0, np.nan], [0.0, 0.0]]))


# ---------------------------------------------------------------------------
# The least-squares objective
# ---------------------------------------------------------------------------


class TestLeastSquaresObjective:
    def test_has_a_hand_computed_value(self):
        """A single edge 0 -> 1 with coefficient 0.5 on a 3-row example."""
        data = np.array([[1.0, 0.0], [2.0, 1.0], [3.0, 0.0]])
        weights = np.array([[0.0, 0.5], [0.0, 0.0]])
        residual = data - data @ weights
        expected = 0.5 * float(np.sum(residual * residual)) / data.shape[0]
        assert least_squares_loss(weights, data) == pytest.approx(expected, rel=1e-12)
        # And the same number by hand: (14 + 2.5) / 6 = 2.75.
        assert least_squares_loss(weights, data) == pytest.approx(2.75, rel=1e-12)

    def test_zero_weights_reproduce_the_variance(self):
        data = np.array([[1.0, 0.0], [2.0, 1.0], [3.0, 0.0]])
        expected = 0.5 * float(np.sum(data * data)) / data.shape[0]
        assert least_squares_loss(np.zeros((2, 2)), data) == pytest.approx(expected)

    def test_the_diagonal_is_not_a_free_parameter(self):
        """A self-edge is not part of a structural model, so it is ignored."""
        data = np.array([[1.0, 0.0], [2.0, 1.0], [3.0, 0.0]])
        diagonal_only = np.diag([0.7, -0.3])
        assert least_squares_loss(diagonal_only, data) == pytest.approx(
            least_squares_loss(np.zeros((2, 2)), data)
        )

    def test_gradient_matches_finite_differences(self):
        rng = np.random.default_rng(5)
        data = rng.normal(size=(200, 4))
        weights = rng.normal(size=(4, 4))
        analytic = least_squares_gradient(weights, data)
        numeric = finite_difference_gradient(
            lambda w: least_squares_loss(w, data), weights
        )
        assert np.allclose(analytic, numeric, rtol=1e-5, atol=1e-7)

    def test_objective_adds_the_l1_penalty(self):
        rng = np.random.default_rng(6)
        data = rng.normal(size=(100, 3))
        weights = rng.normal(size=(3, 3))
        np.fill_diagonal(weights, 0.0)
        expected = least_squares_loss(weights, data) + 0.25 * np.sum(np.abs(weights))
        assert note_ars_objective(weights, data, 0.25) == pytest.approx(expected)

    def test_rejects_a_negative_penalty(self):
        with pytest.raises(ValueError, match="l1_strength"):
            note_ars_objective(np.zeros((2, 2)), np.zeros((5, 2)), -0.1)

    def test_rejects_mismatched_data(self):
        with pytest.raises(ValueError, match="columns"):
            least_squares_loss(np.zeros((3, 3)), np.zeros((10, 2)))


# ---------------------------------------------------------------------------
# Acyclicity check and thresholding
# ---------------------------------------------------------------------------


class TestDagValidity:
    def test_topological_order_respects_the_edges(self):
        weights = np.zeros((3, 3))
        weights[0, 1] = 1.0
        weights[1, 2] = 1.0
        order = topological_order(weights)
        assert order is not None
        assert order.index(0) < order.index(1) < order.index(2)

    def test_topological_order_is_none_on_a_cycle(self):
        weights = np.array([[0.0, 1.0], [1.0, 0.0]])
        assert topological_order(weights) is None

    def test_is_acyclic_on_a_dag_and_a_cycle(self):
        assert is_acyclic(np.array([[0.0, 1.0], [0.0, 0.0]]))
        assert not is_acyclic(np.array([[0.0, 1.0], [1.0, 0.0]]))

    def test_is_acyclic_rejects_a_self_loop(self):
        assert not is_acyclic(np.array([[1.0]]))

    def test_is_acyclic_agrees_with_the_constraint(self):
        """The topological argument and the matrix-exponential argument coincide.

        Zheng et al.'s Theorem 1 says h(W) = 0 exactly on acyclic matrices. The
        check is exact via the sort and numerical via the exponential, so this
        tests that the two definitions genuinely mean the same thing here.
        """
        rng = np.random.default_rng(21)
        matrices = []
        for _ in range(10):
            matrices.append(rng.normal(size=(4, 4)))          # almost surely cyclic
            triangular = np.triu(rng.normal(size=(4, 4)), 1)  # acyclic by construction
            matrices.append(triangular)
        for weights in matrices:
            assert is_acyclic(weights) == (acyclicity_constraint(weights) < 1e-8)

    def test_threshold_weights_drops_small_entries(self):
        weights = np.array([[0.0, 0.4, 0.05], [0.0, 0.0, -0.35], [0.0, 0.0, 0.0]])
        adjacency = threshold_weights(weights, 0.3)
        assert adjacency[0, 1] == 1.0
        assert adjacency[1, 2] == 1.0
        assert adjacency[0, 2] == 0.0

    def test_threshold_weights_keeps_the_diagonal_zero(self):
        weights = np.full((3, 3), 0.9)
        adjacency = threshold_weights(weights, 0.3)
        assert np.all(np.diag(adjacency) == 0.0)

    def test_threshold_weights_is_a_pure_adjacency(self):
        rng = np.random.default_rng(9)
        adjacency = threshold_weights(rng.normal(size=(5, 5)), 0.5)
        assert set(np.unique(adjacency)) <= {0.0, 1.0}

    def test_threshold_weights_rejects_bad_settings(self):
        with pytest.raises(ValueError, match="threshold"):
            threshold_weights(np.zeros((2, 2)), -1.0)
        with pytest.raises(ValueError, match="threshold"):
            threshold_weights(np.zeros((2, 2)), float("nan"))

    def test_resolve_w_bound_derives_a_finite_bound(self):
        bound = resolve_w_bound(5)
        assert math.isfinite(bound) and bound > 0.0
        assert bound <= 10.0

    def test_resolve_w_bound_rejects_an_overflowing_bound(self):
        """A bound so large that rho_max * h(W)^2 overflows must raise, not clip."""
        with pytest.raises(ValueError, match="too large"):
            resolve_w_bound(5, w_bound=50.0, rho_max=1e16)

    def test_resolve_w_bound_honours_a_safe_explicit_bound(self):
        assert resolve_w_bound(5, w_bound=1.0) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# NOTEARS recovery
# ---------------------------------------------------------------------------


class TestNoteArsRecovery:
    @pytest.mark.parametrize("seed", [0, 1, 2])
    def test_recovers_a_five_node_dag_with_colliders(self, seed):
        """A, B -> C -> D -> E: the collider at C fixes the orientation class."""
        parents, coefficients = COLLIDER_CHAIN
        data = simulate_linear_sem(parents, coefficients, 4000, seed)
        result = notears_linear(data, list(parents))
        assert sorted(result.edge_list()) == true_edges(parents)

    @pytest.mark.parametrize("seed", [0, 1, 2])
    def test_recovers_a_diamond(self, seed):
        parents, coefficients = DIAMOND
        data = simulate_linear_sem(parents, coefficients, 4000, seed)
        result = notears_linear(data, list(parents))
        assert sorted(result.edge_list()) == true_edges(parents)

    @pytest.mark.parametrize("seed", [0, 1, 2])
    def test_recovers_the_weights_not_only_the_support(self, seed):
        """The recovered coefficient of a simple edge is close to the generating one.

        Weights are in the raw scale because the module does not standardise by
        default, so the generating coefficient is directly comparable. The fit is
        shrunk below 2.0 by the L1 penalty -- a real bias, not noise, and the next
        test shows it shrinking as the penalty falls.
        """
        parents, coefficients = COLLIDER_CHAIN
        data = simulate_linear_sem(parents, coefficients, 4000, seed)
        result = notears_linear(data, list(parents))
        names = list(parents)
        # A -> C is 2.0 in the generator; the fitted column of C holds it.
        fitted = result.weights[names.index("A"), names.index("C")]
        assert fitted == pytest.approx(2.0, abs=0.25)

    def test_a_smaller_l1_penalty_shrinks_the_coefficients_less(self):
        """L1 shrinkage is monotone in the penalty, so the bias is attributable."""
        parents, coefficients = COLLIDER_CHAIN
        data = simulate_linear_sem(parents, coefficients, 4000, 0)
        names = list(parents)
        row, column = names.index("A"), names.index("C")

        heavily = notears_linear(data, names, l1_strength=0.2)
        lightly = notears_linear(data, names, l1_strength=0.02)

        assert abs(lightly.weights[row, column] - 2.0) < abs(
            heavily.weights[row, column] - 2.0
        )

    def test_the_solution_satisfies_the_constraint(self):
        parents, coefficients = COLLIDER_CHAIN
        data = simulate_linear_sem(parents, coefficients, 4000, 0)
        result = notears_linear(data, list(parents))
        assert result.converged is True
        assert result.h_final == pytest.approx(0.0, abs=1e-7)
        assert acyclicity_constraint(result.weights) == pytest.approx(0.0, abs=1e-7)
        assert result.acyclic is True
        assert result.hit_bound is False

    def test_the_constraint_trace_decreases(self):
        """The augmented Lagrangian must shrink h(W), not merely end small."""
        parents, coefficients = COLLIDER_CHAIN
        data = simulate_linear_sem(parents, coefficients, 4000, 0)
        result = notears_linear(data, list(parents))
        assert len(result.h_trace) >= 2
        assert result.h_trace[-1] < result.h_trace[0]

    def test_the_thresholded_graph_is_the_dag_that_counts(self):
        """The DAG is the thresholded graph: float dust is not structural.

        A hand-built case first, so the property does not depend on what the
        optimiser happens to leave behind, then the fitted result.
        """
        weights = np.zeros((3, 3))
        weights[0, 1] = 1.0
        weights[1, 2] = 1.0
        weights[2, 0] = 1e-13  # numerical dust closing a cycle
        assert is_acyclic(weights) is False
        assert is_acyclic(threshold_weights(weights, 0.3)) is True

        parents, coefficients = COLLIDER_CHAIN
        data = simulate_linear_sem(parents, coefficients, 4000, 0)
        result = notears_linear(data, list(parents))
        assert result.acyclic is True
        assert result.acyclic == is_acyclic(result.adjacency)
        assert result.raw_pattern_acyclic == is_acyclic(result.weights)

    def test_the_objective_is_the_loss_plus_the_penalty(self):
        parents, coefficients = COLLIDER_CHAIN
        data = simulate_linear_sem(parents, coefficients, 4000, 0)
        result = notears_linear(data, list(parents))
        assert result.objective == pytest.approx(
            result.structural_loss + result.l1_penalty, rel=1e-9
        )

    def test_a_chain_is_recovered_up_to_its_equivalence_class(self):
        """The skeleton is identified; the direction of a chain is not.

        A chain has no v-structure, so its reverse carries the same observational
        likelihood. Asserting the exact direction here would be asserting something
        the method cannot know.
        """
        parents, coefficients = CHAIN
        data = simulate_linear_sem(parents, coefficients, 4000, 0)
        result = notears_linear(data, list(parents))
        expected = undirected(true_edges(parents))
        assert undirected(result.edge_list()) == expected
        assert is_acyclic(result.adjacency)

    def test_repeated_fits_are_identical(self):
        parents, coefficients = COLLIDER_CHAIN
        data = simulate_linear_sem(parents, coefficients, 4000, 0)
        first = notears_linear(data, list(parents))
        second = notears_linear(data, list(parents))
        assert first.to_dict() == second.to_dict()

    def test_the_default_does_not_standardise(self):
        config = NoteArsConfig()
        assert config.standardize is False

    @pytest.mark.parametrize("seed", [0, 1])
    def test_standardising_inverts_the_recovered_orientation(self, seed):
        """The documented reason the default is standardize=False.

        Z-scoring rescales each column's residual, so the equal-noise-variance
        assumption the loss relies on no longer holds and the collider comes back
        pointing backwards. The test fixes the observed failure so a future change
        to the default cannot quietly reintroduce it.
        """
        parents, coefficients = COLLIDER_CHAIN
        data = simulate_linear_sem(parents, coefficients, 4000, seed)

        raw = notears_linear(data, list(parents), standardize=False)
        standardised = notears_linear(data, list(parents), standardize=True)

        assert sorted(raw.edge_list()) == true_edges(parents)
        assert sorted(standardised.edge_list()) != true_edges(parents)

    def test_tncm_vae_can_consume_the_learned_structure(self):
        """The integration seam: the learned DAG builds a usable StructuralCausalModel."""
        parents, coefficients = COLLIDER_CHAIN
        data = simulate_linear_sem(parents, coefficients, 4000, 0)
        result = notears_linear(data, list(parents))
        names = list(parents)

        model = StructuralCausalModel(
            variables=names,
            coefficients={
                child: {parent: 1.0 for parent in parents_tuple}
                for child, parents_tuple in result.parents().items()
            },
        )
        assert set(model.parents["C"]) == {"A", "B"}
        assert model.descendants("C") == ("D", "E")

    def test_result_serialises_to_json(self):
        parents, coefficients = COLLIDER_CHAIN
        data = simulate_linear_sem(parents, coefficients, 4000, 0)
        result = notears_linear(data, list(parents))
        assert isinstance(result, NoteArsResult)
        payload = result.to_dict()
        json.dumps(payload, allow_nan=False)
        assert payload["summary"].startswith("NOTEARS learned")

    def test_overrides_reach_the_config(self):
        parents, coefficients = COLLIDER_CHAIN
        data = simulate_linear_sem(parents, coefficients, 4000, 0)
        # The generating coefficients are 2.0 in the raw scale, so a threshold
        # above them removes every edge while the fit itself is unchanged.
        result = notears_linear(data, list(parents), threshold=3.0)
        assert result.threshold == pytest.approx(3.0)
        assert result.edge_list() == ()
        # The raw weights are still there: thresholding discards the magnitude
        # from the adjacency, not from the record.
        assert np.max(np.abs(result.weights)) > 1.0


# ---------------------------------------------------------------------------
# Conversions to and from the tncm_vae parents representation
# ---------------------------------------------------------------------------


class TestParentsConversion:
    def test_adjacency_parents_adjacency_round_trip(self):
        parents, _ = COLLIDER_CHAIN
        names = list(parents)
        rng = np.random.default_rng(13)
        upper = np.triu(rng.normal(size=(5, 5)), 1)
        adjacency = threshold_weights(upper, 0.5)

        mapping = adjacency_to_parents(adjacency, names)
        assert np.array_equal(parents_to_adjacency(mapping, names), adjacency)

    def test_the_mapping_matches_the_tncm_vae_structure(self):
        """Every variable is a key, including those with no parents."""
        model = StructuralCausalModel(
            variables=["A", "B", "C", "D"],
            coefficients={"C": {"A": 1.0, "B": 0.5}, "D": {"C": 2.0}},
        )
        adjacency = parents_to_adjacency(model.parents, list(model.variables))
        recovered = adjacency_to_parents(adjacency, list(model.variables))

        assert set(recovered) == set(model.parents)
        for child in model.variables:
            assert set(recovered[child]) == set(model.parents[child])
            assert isinstance(recovered[child], tuple)

    def test_real_model_structure_survives_a_round_trip(self):
        model = StructuralCausalModel(
            variables=["A", "B", "C", "D"],
            coefficients={"B": {"A": 1.0}, "C": {"A": 0.5, "B": 0.5}, "D": {"C": 1.0}},
        )
        adjacency = parents_to_adjacency(model.parents, list(model.variables))
        back = parents_to_adjacency(adjacency_to_parents(adjacency, list(model.variables)))
        assert np.array_equal(back, adjacency)
        # The row/column convention: column i holds the parents of variable i.
        assert adjacency[0, 2] == 1.0  # A -> C
        assert adjacency[1, 2] == 1.0  # B -> C
        assert adjacency[2, 3] == 1.0  # C -> D
        assert adjacency[2, 0] == 0.0

    def test_parents_can_be_derived_from_weights(self):
        weights = np.array([[0.0, 0.9], [0.1, 0.0]])
        assert weights_to_parents(weights, ["A", "B"], 0.5) == {
            "A": (),
            "B": ("A",),
        }

    def test_self_loops_are_rejected(self):
        adjacency = np.eye(2)
        with pytest.raises(ValueError, match="self-loop"):
            adjacency_to_parents(adjacency, ["A", "B"])

    def test_a_cycle_is_rejected_unless_explicitly_allowed(self):
        adjacency = np.array([[0.0, 1.0], [1.0, 0.0]])
        with pytest.raises(ValueError, match="cycle"):
            adjacency_to_parents(adjacency, ["A", "B"])
        mapping = adjacency_to_parents(adjacency, ["A", "B"], require_acyclic=False)
        assert mapping == {"A": ("B",), "B": ("A",)}

    def test_a_cyclic_parents_mapping_is_rejected(self):
        with pytest.raises(ValueError, match="cycle"):
            parents_to_adjacency({"A": ("B",), "B": ("A",)})

    def test_a_missing_variable_key_is_rejected(self):
        """A missing key is not the same statement as an empty tuple."""
        with pytest.raises(ValueError, match="missing entries"):
            parents_to_adjacency({"A": (), "B": ("A",)}, ["A", "B", "C"])

    def test_unknown_names_are_rejected(self):
        with pytest.raises(ValueError, match="not a declared variable"):
            parents_to_adjacency({"A": (), "B": ("Z",)})
        with pytest.raises(ValueError, match="not declared"):
            parents_to_adjacency({"A": (), "B": ("A",), "C": ()}, ["A", "B"])

    def test_a_bare_string_is_not_a_parent_list(self):
        with pytest.raises(ValueError, match="bare string"):
            parents_to_adjacency({"A": (), "B": "A"})

    def test_a_self_parent_is_rejected(self):
        with pytest.raises(ValueError, match="itself"):
            parents_to_adjacency({"A": ("A",)})

    def test_a_non_mapping_is_rejected(self):
        with pytest.raises(ValueError, match="mapping"):
            parents_to_adjacency(np.zeros((2, 2)), ["A", "B"])

    def test_shape_mismatch_is_rejected(self):
        with pytest.raises(ValueError, match="variable names"):
            adjacency_to_parents(np.zeros((3, 3)), ["A", "B"])


# ---------------------------------------------------------------------------
# compare_dag
# ---------------------------------------------------------------------------


class TestCompareDag:
    def test_an_entirely_correct_dag_raises_no_warning(self):
        declared = {"A": (), "B": ("A",), "C": ("B",)}
        learned = {"A": (), "B": ("A",), "C": ("B",)}
        comparison = compare_dag(learned, declared)

        assert isinstance(comparison, DagComparison)
        assert comparison.model_risk_warning is False
        assert comparison.learned_only == ()
        assert comparison.declared_only == ()
        assert comparison.orientation_conflicts == ()
        assert comparison.under_specified is False
        assert comparison.over_specified is False
        assert set(comparison.agreed) == {("A", "B"), ("B", "C")}
        assert "agree" in comparison.summary()

    def test_a_missing_declared_edge_is_reported_as_under_specification(self):
        """The severe direction: the declaration omits a parent the data support."""
        declared = {"A": (), "B": ("A",), "C": ("B",)}
        learned = {"A": (), "B": ("A",), "C": ("A", "B")}
        comparison = compare_dag(learned, declared)

        assert comparison.model_risk_warning is True
        assert comparison.learned_only == (("A", "C"),)
        assert comparison.declared_only == ()
        assert comparison.under_specified is True
        assert comparison.over_specified is False
        assert "UNDER-SPECIFIED" in comparison.summary()

    def test_an_extra_declared_edge_is_reported_as_over_specification(self):
        declared = {"A": (), "B": ("A",), "C": ("A", "B")}
        learned = {"A": (), "B": ("A",), "C": ("B",)}
        comparison = compare_dag(learned, declared)

        assert comparison.model_risk_warning is True
        assert comparison.declared_only == (("A", "C"),)
        assert comparison.learned_only == ()
        assert comparison.over_specified is True
        assert comparison.under_specified is False
        assert "OVER-SPECIFIED" in comparison.summary()

    def test_a_reversed_edge_is_an_orientation_conflict(self):
        declared = {"A": ("B",), "B": ()}
        learned = {"A": (), "B": ("A",)}
        comparison = compare_dag(learned, declared)

        assert len(comparison.orientation_conflicts) == 1
        conflict = comparison.orientation_conflicts[0]
        assert isinstance(conflict, OrientationConflict)
        assert (conflict.learned_source, conflict.learned_target) == ("A", "B")
        assert (conflict.declared_source, conflict.declared_target) == ("B", "A")
        assert comparison.model_risk_warning is True
        # The reversed direction is literally absent from each structure, so it is
        # also reported in both one-sided lists. The docstring says so.
        assert ("A", "B") in comparison.learned_only
        assert ("B", "A") in comparison.declared_only
        assert "orientation conflict" in comparison.summary()

    def test_a_reversed_edge_is_not_counted_as_a_missing_one(self):
        """The conflict is visible on its own, not only as a pair of set differences."""
        declared = {"A": (), "B": ("C",), "C": ()}
        learned = {"A": (), "B": (), "C": ("B",)}
        comparison = compare_dag(learned, declared)
        assert len(comparison.orientation_conflicts) == 1
        assert comparison.under_specified is True
        assert comparison.over_specified is True

    def test_matrices_and_mappings_give_the_same_answer(self):
        declared = {"A": (), "B": ("A",), "C": ("B",)}
        learned = {"A": (), "B": ("A",), "C": ("A",)}
        names = ["A", "B", "C"]
        from_mapping = compare_dag(learned, declared)
        from_matrices = compare_dag(
            parents_to_adjacency(learned, names),
            parents_to_adjacency(declared, names),
            variables=names,
        )
        assert from_matrices.to_dict() == from_mapping.to_dict()

    def test_a_matrix_without_variables_is_rejected(self):
        with pytest.raises(ValueError, match="variable names"):
            compare_dag(np.zeros((2, 2)), np.zeros((2, 2)))

    def test_different_variable_sets_are_rejected(self):
        with pytest.raises(ValueError, match="different variables"):
            compare_dag({"A": (), "B": ()}, {"A": (), "C": ()})

    def test_a_cyclic_input_is_rejected(self):
        with pytest.raises(ValueError, match="cycle"):
            compare_dag(
                {"A": ("B",), "B": ("A",)},
                {"A": (), "B": ("A",)},
            )

    def test_comparison_serialises_to_json(self):
        comparison = compare_dag(
            {"A": (), "B": ("A",)},
            {"A": ("B",), "B": ()},
        )
        payload = comparison.to_dict()
        json.dumps(payload, allow_nan=False)
        assert payload["model_risk_warning"] is True
        assert payload["orientation_conflicts"][0]["learned_source"] == "A"


# ---------------------------------------------------------------------------
# The constraint-based baseline
# ---------------------------------------------------------------------------


class TestConstraintBasedSkeleton:
    def test_recovers_the_skeleton_of_a_chain(self):
        parents, coefficients = make_dag(["A", "B", "C"], [("A", "B"), ("B", "C")])
        data = simulate_linear_sem(parents, coefficients, 3000, 0)
        result = PartialCorrelationSkeleton().fit(data, list(parents))

        assert isinstance(result, SkeletonResult)
        assert undirected(result.skeleton_edges()) == undirected([("A", "B"), ("B", "C")])

    def test_the_chain_edge_is_removed_by_conditioning_on_the_middle(self):
        """A and C are marginally dependent; conditioning on B separates them.

        This is the property that distinguishes a conditional-independence test
        from a correlation threshold, and the separating set is recorded so the
        claim is checkable rather than asserted.
        """
        parents, coefficients = make_dag(["A", "B", "C"], [("A", "B"), ("B", "C")])
        data = simulate_linear_sem(parents, coefficients, 3000, 0)
        skeleton = PartialCorrelationSkeleton()
        result = skeleton.fit(data, list(parents))

        assert result.skeleton[0, 2] == 0.0
        assert result.sepsets[(0, 2)] == (1,)
        assert result.p_values[(0, 2)] >= skeleton.alpha

    def test_a_chain_is_not_oriented(self):
        """A-C is separated by B, so the collider rule must not fire."""
        parents, coefficients = make_dag(["A", "B", "C"], [("A", "B"), ("B", "C")])
        data = simulate_linear_sem(parents, coefficients, 3000, 0)
        result = PartialCorrelationSkeleton().fit(data, list(parents))
        assert result.directed_edges() == ()

    def test_orients_an_unshielded_collider(self):
        parents, coefficients = make_dag(["A", "B", "C"], [("A", "C"), ("B", "C")])
        data = simulate_linear_sem(parents, coefficients, 3000, 1)
        result = PartialCorrelationSkeleton().fit(data, list(parents))

        assert undirected(result.skeleton_edges()) == undirected([("A", "C"), ("B", "C")])
        assert set(result.directed_edges()) == {("A", "C"), ("B", "C")}
        assert result.sepsets[(0, 1)] == ()
        assert result.orientation_conflicts == ()

    def test_the_skeleton_is_symmetric_with_no_self_edges(self):
        parents, coefficients = COLLIDER_CHAIN
        data = simulate_linear_sem(parents, coefficients, 3000, 0)
        result = PartialCorrelationSkeleton().fit(data, list(parents))
        assert np.array_equal(result.skeleton, result.skeleton.T)
        assert np.all(np.diag(result.skeleton) == 0.0)

    def test_partial_correlation_matches_the_residual_route(self):
        """An independent computation: correlation of OLS residuals."""
        rng = np.random.default_rng(7)
        common = rng.normal(size=(2000, 1))
        left = 0.7 * common[:, 0] + rng.normal(size=2000)
        right = 0.5 * common[:, 0] + rng.normal(size=2000)
        data = np.column_stack([left, common[:, 0], right])

        def residuals(column, cond):
            design = np.column_stack([np.ones(len(cond)), cond])
            beta, *_ = np.linalg.lstsq(design, column, rcond=None)
            return column - design @ beta

        expected = float(
            np.corrcoef(
                residuals(data[:, 0], data[:, [1]]),
                residuals(data[:, 2], data[:, [1]]),
            )[0, 1]
        )
        assert partial_correlation(data, 0, 2, (1,)) == pytest.approx(expected, rel=1e-9)

    def test_partial_correlation_matches_the_recursion_closed_form(self):
        rng = np.random.default_rng(4)
        data = rng.normal(size=(1500, 3))
        correlations = np.corrcoef(data, rowvar=False)
        expected = (
            correlations[0, 1] - correlations[0, 2] * correlations[1, 2]
        ) / math.sqrt(
            (1.0 - correlations[0, 2] ** 2) * (1.0 - correlations[1, 2] ** 2)
        )
        assert partial_correlation(data, 0, 1, (2,)) == pytest.approx(expected, rel=1e-9)

    def test_the_baseline_and_notears_agree_on_the_skeleton(self):
        """Two methods with different assumptions must agree on which edges exist."""
        parents, coefficients = COLLIDER_CHAIN
        data = simulate_linear_sem(parents, coefficients, 4000, 0)

        learned = notears_linear(data, list(parents))
        skeleton = PartialCorrelationSkeleton().fit(data, list(parents))

        assert undirected(learned.edge_list()) == undirected(skeleton.skeleton_edges())
        assert undirected(skeleton.skeleton_edges()) == undirected(
            [("A", "C"), ("B", "C"), ("C", "D"), ("D", "E")]
        )

    def test_result_serialises_to_json(self):
        parents, coefficients = COLLIDER_CHAIN
        data = simulate_linear_sem(parents, coefficients, 3000, 0)
        result = PartialCorrelationSkeleton().fit(data, list(parents))
        payload = result.to_dict()
        json.dumps(payload, allow_nan=False)
        assert payload["summary"].startswith("partial-correlation skeleton")

    def test_validation(self):
        with pytest.raises(ValueError, match="alpha"):
            PartialCorrelationSkeleton(alpha=0.0)
        with pytest.raises(ValueError, match="alpha"):
            PartialCorrelationSkeleton(alpha=1.5)
        with pytest.raises(ValueError, match="max_conditioning_size"):
            PartialCorrelationSkeleton(max_conditioning_size=-1)

    def test_partial_correlation_validation(self):
        data = np.random.default_rng(0).normal(size=(50, 4))
        with pytest.raises(ValueError, match="column index"):
            partial_correlation(data, 0, 9)
        with pytest.raises(ValueError, match="distinct"):
            partial_correlation(data, 1, 1)
        with pytest.raises(ValueError, match="contains an endpoint"):
            partial_correlation(data, 0, 1, (1,))
        with pytest.raises(ValueError, match="out of range"):
            partial_correlation(data, 0, 1, (7,))
        with pytest.raises(ValueError, match="repeat"):
            partial_correlation(data, 0, 1, (2, 2))


# ---------------------------------------------------------------------------
# Fail-closed behaviour
# ---------------------------------------------------------------------------


class TestFailClosed:
    def test_non_finite_data_is_rejected(self):
        data = simulate_linear_sem(*COLLIDER_CHAIN, 100, 0)
        poisoned = data.copy()
        poisoned[3, 2] = np.nan
        with pytest.raises(DataQualityError, match="non-finite"):
            notears_linear(poisoned, ["A", "B", "C", "D", "E"])
        with pytest.raises(DataQualityError, match="non-finite"):
            PartialCorrelationSkeleton().fit(poisoned, ["A", "B", "C", "D", "E"])

    def test_infinite_data_is_rejected(self):
        data = simulate_linear_sem(*COLLIDER_CHAIN, 100, 0)
        data[0, 0] = np.inf
        with pytest.raises(DataQualityError, match="non-finite"):
            notears_linear(data, ["A", "B", "C", "D", "E"])

    def test_too_few_samples_relative_to_variables_is_rejected(self):
        data = np.random.default_rng(0).normal(size=(3, 5))
        with pytest.raises(DataQualityError, match="samples for"):
            notears_linear(data, ["A", "B", "C", "D", "E"])
        with pytest.raises(DataQualityError, match="samples for"):
            PartialCorrelationSkeleton().fit(data, ["A", "B", "C", "D", "E"])

    def test_a_single_variable_is_rejected(self):
        with pytest.raises(ValueError, match="at least two variables"):
            notears_linear(np.zeros((10, 1)), ["A"])

    def test_non_square_weight_matrices_are_rejected(self):
        rectangle = np.zeros((2, 3))
        with pytest.raises(ValueError, match="square"):
            acyclicity_constraint(rectangle)
        with pytest.raises(ValueError, match="square"):
            acyclicity_gradient(rectangle)
        with pytest.raises(ValueError, match="square"):
            is_acyclic(rectangle)
        with pytest.raises(ValueError, match="square"):
            topological_order(rectangle)
        with pytest.raises(ValueError, match="square"):
            threshold_weights(rectangle)

    def test_one_dimensional_data_is_rejected(self):
        with pytest.raises(ValueError, match="2-D"):
            notears_linear(np.zeros(10), ["A", "B"])

    def test_mismatched_column_count_is_rejected(self):
        with pytest.raises(ValueError, match="columns"):
            notears_linear(np.zeros((10, 3)), ["A", "B"])

    def test_duplicate_variable_names_are_rejected(self):
        with pytest.raises(ValueError, match="unique"):
            notears_linear(np.zeros((10, 2)), ["A", "A"])

    def test_a_constant_column_is_rejected(self):
        """A constant column has no structural equation to estimate."""
        data = simulate_linear_sem(*COLLIDER_CHAIN, 100, 0)
        data[:, 1] = 7.0
        names = ["A", "B", "C", "D", "E"]
        with pytest.raises(DataQualityError, match="constant"):
            notears_linear(data, names)
        with pytest.raises(DataQualityError, match="constant"):
            notears_linear(data, names, standardize=True)
        with pytest.raises(DataQualityError, match="constant"):
            PartialCorrelationSkeleton().fit(data, names)

    def test_a_degenerate_partial_correlation_is_rejected(self):
        """Perfect collinearity makes the conditional correlation undefined."""
        rng = np.random.default_rng(2)
        column = rng.normal(size=200)
        data = np.column_stack([column, rng.normal(size=200), 2.0 * column])
        with pytest.raises(DataQualityError, match="undefined"):
            partial_correlation(data, 0, 1, (2,))

    def test_a_conditioning_set_too_large_for_the_sample_is_rejected(self):
        data = np.random.default_rng(0).normal(size=(6, 5))
        with pytest.raises(DataQualityError, match="n - \\|S\\| - 3"):
            PartialCorrelationSkeleton().fit(data, ["A", "B", "C", "D", "E"])

    def test_stochastic_restarts_without_a_seed_are_rejected(self):
        with pytest.raises(ValueError, match="seed"):
            NoteArsConfig(n_restarts=2)

    def test_invalid_solver_settings_are_rejected(self):
        with pytest.raises(ValueError, match="l1_strength"):
            NoteArsConfig(l1_strength=-0.1)
        with pytest.raises(ValueError, match="threshold"):
            NoteArsConfig(threshold=-0.1)
        with pytest.raises(ValueError, match="rho_growth"):
            NoteArsConfig(rho_growth=1.0)
        with pytest.raises(ValueError, match="rho_decrease_ratio"):
            NoteArsConfig(rho_decrease_ratio=1.0)
        with pytest.raises(ValueError, match="h_tolerance"):
            NoteArsConfig(h_tolerance=0.0)
        with pytest.raises(ValueError, match="n_restarts"):
            NoteArsConfig(n_restarts=0)
        with pytest.raises(ValueError, match="w_bound"):
            NoteArsConfig(w_bound=-1.0)

    def test_an_unsafe_explicit_bound_is_rejected_at_fit_time(self):
        data = simulate_linear_sem(*COLLIDER_CHAIN, 200, 0)
        with pytest.raises(ValueError, match="too large"):
            notears_linear(data, ["A", "B", "C", "D", "E"], w_bound=50.0)

    def test_a_non_converged_fit_is_reported_as_such(self):
        """Exhausting the penalty budget must not be disguised as success."""
        data = simulate_linear_sem(*COLLIDER_CHAIN, 4000, 0)
        result = notears_linear(
            data,
            ["A", "B", "C", "D", "E"],
            max_outer_iterations=1,
            h_tolerance=1e-30,
        )
        assert result.converged is False
        assert result.h_final > 1e-30

    def test_restarts_are_reproducible_with_a_seed(self):
        data = simulate_linear_sem(*COLLIDER_CHAIN, 1000, 0)
        config = NoteArsConfig(n_restarts=3, seed=42)
        first = NoteArsDiscovery(config).fit(data, ["A", "B", "C", "D", "E"])
        second = NoteArsDiscovery(config).fit(data, ["A", "B", "C", "D", "E"])
        assert first.to_dict() == second.to_dict()
        assert first.n_starts == 3
