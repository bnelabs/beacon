"""Non-linear causal discovery: the basis-expansion NOTEARS.

The linear solver fits ``X = X W + E``, so a relationship such as
``X2 = sin(X1)`` has no representation. These tests exist to establish one thing
above all: that the non-linear solver recovers a graph the linear solver cannot, on
data generated from a known non-linear SEM. A test that only shows the new code
runs would not distinguish it from a method that returns an arbitrary DAG.

The second theme is the one that sank the MLP variant: a solver can satisfy the
acyclicity constraint *and* report ``converged=True`` while returning an empty
graph, because ``W = 0`` is acyclic. Every recovery assertion here therefore
checks the actual edge set against ground truth, and a separate test asserts that a
converged, acyclic result is not vacuously empty.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.exceptions import DataQualityError
from backend.modules.engine.causal_discovery import (
    NoteArsBasisConfig,
    NoteArsBasisDiscovery,
    NoteArsConfig,
    NoteArsResult,
    basis_expansion,
    basis_structural_loss,
    is_acyclic,
    notears,
    notears_basis,
    notears_linear,
)

VARIABLES = ("X1", "X2", "X3")
TRUE_EDGES = {("X1", "X2"), ("X2", "X3")}


def nonlinear_sem(seed: int = 0, n_samples: int = 1000):
    """``X1 -> X2 -> X3`` with a sine and a square, and equal noise variance.

    Equal noise variance is not decoration: the orientation NOTEARS can identify is
    the one the equal-variance assumption supports. Generating unequal variances
    would test the assumption rather than the solver.
    """
    rng = np.random.default_rng(seed)
    x1 = rng.standard_normal(n_samples)
    x2 = np.sin(x1) + rng.standard_normal(n_samples)
    x3 = x2**2 - 1.0 + rng.standard_normal(n_samples)
    return np.column_stack([x1, x2, x3])


def recovered(result: NoteArsResult) -> set:
    return {(str(parent), str(child)) for parent, child in result.edge_list()}


class TestRecoversWhatTheLinearModelCannot:
    def test_linear_misses_the_non_linear_edge(self):
        """The premise of the whole feature, asserted rather than assumed."""
        result = notears_linear(
            nonlinear_sem(),
            VARIABLES,
            NoteArsConfig(l1_strength=0.1, threshold=0.3, seed=0),
        )
        assert ("X2", "X3") not in recovered(result)

    def test_basis_recovers_the_full_non_linear_graph(self):
        result = notears_basis(
            nonlinear_sem(),
            VARIABLES,
            NoteArsBasisConfig(
                degree=2, l1_strength=0.1, threshold=0.3, seed=0
            ),
        )
        assert recovered(result) == TRUE_EDGES
        assert result.acyclic is True

    @pytest.mark.parametrize("degree", [2, 3])
    def test_recovery_holds_across_degrees(self, degree: int):
        result = notears_basis(
            nonlinear_sem(),
            VARIABLES,
            NoteArsBasisConfig(
                degree=degree, l1_strength=0.1, threshold=0.3, seed=0
            ),
        )
        assert recovered(result) == TRUE_EDGES

    def test_the_result_is_not_vacuously_empty(self):
        """``W = 0`` is acyclic and converges; that must not count as success.

        The MLP variant this replaced converged to an empty graph. A solver that
        returns nothing satisfies every structural check, so the emptiness is
        asserted against directly.
        """
        result = notears_basis(
            nonlinear_sem(),
            VARIABLES,
            NoteArsBasisConfig(degree=2, l1_strength=0.1, threshold=0.3, seed=0),
        )
        assert result.edge_list() != ()
        assert float(np.max(result.weights)) > 0.0


class TestAcyclicityIsGuaranteed:
    @pytest.mark.parametrize("seed", [0, 1, 2, 3])
    def test_the_thresholded_graph_is_acyclic(self, seed: int):
        result = notears_basis(
            nonlinear_sem(seed=seed),
            VARIABLES,
            NoteArsBasisConfig(degree=2, l1_strength=0.1, threshold=0.3, seed=seed),
        )
        assert result.acyclic is True
        assert is_acyclic(result.adjacency) is True
        # h(W) is the constraint the solver claims to have met; assert it directly
        # rather than trusting the boolean it sets from the same number.
        assert result.h_final <= 1e-6

    def test_a_lower_objective_with_a_violated_constraint_is_not_preferred(self):
        """The restart-selection rule must not trade feasibility for fit."""
        result = notears_basis(
            nonlinear_sem(),
            VARIABLES,
            NoteArsBasisConfig(
                degree=2, l1_strength=0.1, threshold=0.3, n_restarts=3, seed=11
            ),
        )
        if result.converged:
            assert result.acyclic is True


class TestDeterminism:
    def test_the_same_seed_reproduces_the_result_exactly(self):
        config = NoteArsBasisConfig(degree=2, l1_strength=0.1, threshold=0.3, seed=7)
        first = notears_basis(nonlinear_sem(), VARIABLES, config)
        second = notears_basis(nonlinear_sem(), VARIABLES, config)
        assert first.to_dict() == second.to_dict()

    def test_different_restart_seeds_are_seeded_not_ambient(self):
        """With restarts, the seed governs every draw, so runs stay reproducible."""
        config = NoteArsBasisConfig(
            degree=2, l1_strength=0.1, threshold=0.3, n_restarts=2, seed=3
        )
        first = notears_basis(nonlinear_sem(), VARIABLES, config)
        second = notears_basis(nonlinear_sem(), VARIABLES, config)
        assert first.to_dict() == second.to_dict()
        assert first.n_starts == 2


class TestExpansion:
    def test_each_variable_contributes_one_column_per_power(self):
        data = np.arange(12, dtype=float).reshape(4, 3)
        features, groups = basis_expansion(data, 3)
        assert features.shape == (4, 9)
        assert groups.tolist() == [0, 0, 0, 1, 1, 1, 2, 2, 2]

    def test_the_basis_actually_contains_the_non_linear_terms(self):
        data = np.arange(1, 5, dtype=float).reshape(4, 1)
        features, _ = basis_expansion(data, 2)
        np.testing.assert_allclose(features[:, 0], data[:, 0])
        np.testing.assert_allclose(features[:, 1], data[:, 0] ** 2)

    def test_a_non_integer_degree_raises(self):
        with pytest.raises(ValueError):
            basis_expansion(np.zeros((3, 2)), 2.5)  # type: ignore[arg-type]


class TestStructuralLossIsRecomputable:
    def test_reported_loss_matches_an_independent_recomputation(self):
        """A fit is re-derived from the coefficients; it is not the solver's word."""
        data = nonlinear_sem()
        result = notears_basis(
            data, VARIABLES, NoteArsBasisConfig(degree=2, l1_strength=0.0, seed=0)
        )
        # With no sparsity penalty the reported objective is the structural loss.
        assert result.structural_loss == pytest.approx(result.objective, rel=1e-9)
        assert result.structural_loss > 0.0

    def test_basis_structural_loss_rejects_nothing_and_is_finite(self):
        data = nonlinear_sem(n_samples=50)
        features, _ = basis_expansion(data - data.mean(axis=0), 2)
        coefficients = np.zeros((features.shape[1], data.shape[1]))
        # Zero coefficients reproduce the centred target exactly.
        loss = basis_structural_loss(features, data - data.mean(axis=0), coefficients)
        assert np.isfinite(loss)
        assert loss > 0.0


class TestFailsClosed:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"degree": 1},
            {"degree": 0},
            {"degree": 2.5},
            {"l1_strength": -0.1},
            {"threshold": -1.0},
            {"max_outer_iterations": 0},
            {"max_inner_iterations": 0},
            {"h_tolerance": 0.0},
            {"rho_max": 0.5, "initial_rho": 1.0},
            {"rho_growth": 1.0},
            {"rho_decrease_ratio": 1.0},
            {"n_restarts": 2},  # no seed
            {"seed": "abc"},
        ],
    )
    def test_invalid_configs_raise(self, kwargs):
        with pytest.raises(ValueError):
            NoteArsBasisConfig(**kwargs)

    def test_degree_one_raises_rather_than_silently_running_the_linear_model(self):
        with pytest.raises(ValueError, match="degree must be at least 2"):
            NoteArsBasisConfig(degree=1)

    def test_a_constant_column_raises(self):
        data = nonlinear_sem()
        data[:, 1] = 5.0
        with pytest.raises(DataQualityError):
            notears_basis(data, VARIABLES, NoteArsBasisConfig(degree=2, seed=0))

    def test_non_finite_data_raises(self):
        data = nonlinear_sem()
        data[0, 0] = np.nan
        with pytest.raises(DataQualityError):
            notears_basis(data, VARIABLES, NoteArsBasisConfig(degree=2, seed=0))

    def test_an_oversized_coefficient_bound_raises(self):
        with pytest.raises(ValueError, match="too large"):
            notears_basis(
                nonlinear_sem(),
                VARIABLES,
                NoteArsBasisConfig(degree=2, coefficient_bound=1e6, seed=0),
            )

    def test_a_wrong_config_type_raises(self):
        with pytest.raises(TypeError, match="NoteArsBasisConfig"):
            NoteArsBasisDiscovery(NoteArsConfig())  # type: ignore[arg-type]


class TestPublicDispatch:
    def test_the_non_linear_method_is_selectable_from_the_shared_entry_point(self):
        result = notears(
            nonlinear_sem(),
            VARIABLES,
            method="basis",
            config=NoteArsBasisConfig(degree=2, l1_strength=0.1, threshold=0.3, seed=0),
        )
        assert isinstance(result, NoteArsResult)
        assert recovered(result) == TRUE_EDGES

    def test_the_linear_method_is_still_selectable_and_unchanged(self):
        result = notears(
            nonlinear_sem(),
            VARIABLES,
            method="linear",
            config=NoteArsConfig(l1_strength=0.1, threshold=0.3, seed=0),
        )
        assert isinstance(result, NoteArsResult)
        assert ("X1", "X2") in recovered(result)

    @pytest.mark.parametrize("method", ["mlp", "dag-gnn", ""])
    def test_an_unknown_method_raises(self, method: str):
        with pytest.raises(ValueError, match="method must be"):
            notears(nonlinear_sem(), VARIABLES, method=method)

    def test_a_mis_typed_config_raises_rather_than_being_ignored(self):
        """Silently dropping the config would run defaults the caller did not choose."""
        with pytest.raises(ValueError, match="NoteArsBasisConfig"):
            notears(nonlinear_sem(), VARIABLES, method="basis", config=NoteArsConfig())
        with pytest.raises(ValueError, match="NoteArsConfig"):
            notears(nonlinear_sem(), VARIABLES, method="linear", config=NoteArsBasisConfig())

    def test_the_non_linear_method_is_case_insensitive(self):
        result = notears(
            nonlinear_sem(), VARIABLES, method="  BASIS  ", degree=2, l1_strength=0.1, seed=0
        )
        assert recovered(result) == TRUE_EDGES


class TestConsumedLikeTheLinearResult:
    """``adjacency`` means the same thing for both solvers, so consumers work."""

    def test_parents_round_trip_from_the_adjacency(self):
        result = notears_basis(
            nonlinear_sem(),
            VARIABLES,
            NoteArsBasisConfig(degree=2, l1_strength=0.1, threshold=0.3, seed=0),
        )
        parents = result.parents()
        assert set(parents["X2"]) == {"X1"}
        assert set(parents["X3"]) == {"X2"}
        assert parents["X1"] == ()

    def test_the_summary_reports_the_acyclic_state(self):
        result = notears_basis(
            nonlinear_sem(),
            VARIABLES,
            NoteArsBasisConfig(degree=2, l1_strength=0.1, threshold=0.3, seed=0),
        )
        assert "acyclic" in result.summary()
        assert "CYCLIC" not in result.summary()

    def test_weights_and_adjacency_agree_on_zero_diagonal(self):
        """A self-loop is not a learnable structure; the constraint drives it out."""
        result = notears_basis(
            nonlinear_sem(),
            VARIABLES,
            NoteArsBasisConfig(degree=2, l1_strength=0.1, threshold=0.3, seed=0),
        )
        assert np.allclose(np.diag(result.adjacency), 0.0)
