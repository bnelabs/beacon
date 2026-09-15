"""Maximum-entropy bilateral estimation must reproduce what was declared.

The estimator's only inputs are aggregate interbank assets and liabilities;
its contract is that the bilateral matrix reproduces those marginals (up to
the zero-diagonal residual), stays non-negative, keeps a zero diagonal, and
reports -- rather than hides -- marginal mismatch and reconciliation error.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.modules.risk.network_estimation import (
    build_clearing_inputs,
    estimate_bilateral_matrix,
    estimate_minimum_density,
    posterior_draws,
    propagate_estimation_uncertainty,
)

ASSETS = {"A": 60.0, "B": 30.0, "C": 10.0}
LIABS = {"A": 40.0, "B": 35.0, "C": 25.0}


class TestEstimation:
    def test_marginals_reproduce_declared_totals(self):
        network = estimate_bilateral_matrix(ASSETS, LIABS)
        scale = min(sum(ASSETS.values()), sum(LIABS.values()))
        # row sums = liabilities scaled to the balanced total
        assert np.allclose(network.row_sums(), np.array([40.0, 35.0, 25.0]) * (scale / 100.0), atol=1e-6)
        assert network.marginal_residual <= 1e-8

    def test_zero_diagonal_and_non_negative(self):
        network = estimate_bilateral_matrix(ASSETS, LIABS)
        assert np.allclose(np.diag(network.liabilities), 0.0)
        assert np.all(network.liabilities >= 0.0)

    def test_marginal_mismatch_is_reported_not_hidden(self):
        network = estimate_bilateral_matrix(ASSETS, LIABS)
        assert network.marginal_mismatch == pytest.approx(abs(100.0 - 100.0), abs=1e-9)
        mismatched = estimate_bilateral_matrix({"A": 60.0, "B": 30.0}, {"A": 40.0, "B": 35.0, "C": 25.0})
        assert mismatched.marginal_mismatch > 0
        assert any("disagree" in note for note in mismatched.notes)

    def test_uncertainty_is_carried(self):
        network = estimate_bilateral_matrix(ASSETS, LIABS)
        assert "prior" in network.uncertainty
        assert network.method == "maximum_entropy_ras"

    def test_single_institution_is_refused(self):
        with pytest.raises(ValueError):
            estimate_bilateral_matrix({"A": 10.0}, {"A": 10.0})

    def test_all_zero_totals_are_refused(self):
        with pytest.raises(ValueError):
            estimate_bilateral_matrix({"A": 0.0, "B": 0.0}, {"A": 0.0, "B": 0.0})


class TestClearingInputs:
    def test_endowments_are_declared_not_estimated(self):
        network = estimate_bilateral_matrix(ASSETS, LIABS)
        liabilities, endowments = build_clearing_inputs(network, endowment_ratio=0.2)
        assert np.allclose(endowments, network.liabilities.sum(axis=1) * 0.2)

    def test_endowment_ratio_is_validated(self):
        network = estimate_bilateral_matrix(ASSETS, LIABS)
        with pytest.raises(ValueError):
            build_clearing_inputs(network, endowment_ratio=0.0)


class TestMinimumDensity:
    """The concentrated corner must honour the same declaration contract."""

    def test_marginals_reproduce_declared_totals(self):
        network = estimate_minimum_density(ASSETS, LIABS)
        assert network.marginal_residual <= 1e-8
        scale = min(sum(ASSETS.values()), sum(LIABS.values())) / sum(LIABS.values())
        assert np.allclose(network.row_sums(), np.array([40.0, 35.0, 25.0]) * scale, atol=1e-6)
        assert np.allclose(network.col_sums(), np.array([60.0, 30.0, 10.0]) * scale, atol=1e-6)

    def test_support_is_no_larger_than_maximum_entropy(self):
        sparse = estimate_minimum_density(ASSETS, LIABS)
        dense = estimate_bilateral_matrix(ASSETS, LIABS)
        assert sparse.n_links() <= dense.n_links()
        # greedy transportation keeps the support at most 2n-1 for generic marginals
        assert sparse.n_links() <= 2 * len(ASSETS) - 1

    def test_zero_diagonal_and_non_negative(self):
        network = estimate_minimum_density(ASSETS, LIABS)
        assert np.allclose(np.diag(network.liabilities), 0.0)
        assert np.all(network.liabilities >= 0.0)

    def test_infeasible_diagonal_leaves_reported_residual(self):
        # A owes 10 and only A is owed anything: the zero-diagonal constraint
        # makes the marginals unplaceable, and the residual must be reported
        # rather than smuggled onto the diagonal.
        network = estimate_minimum_density({"A": 10.0, "B": 0.0}, {"A": 10.0, "B": 0.0})
        assert network.marginal_residual == pytest.approx(10.0)
        assert any("zero-diagonal" in note for note in network.notes)
        assert np.allclose(np.diag(network.liabilities), 0.0)

    def test_method_and_uncertainty_are_declared(self):
        network = estimate_minimum_density(ASSETS, LIABS)
        assert network.method == "minimum_density_greedy"
        assert "minimum-support" in network.uncertainty

    def test_mismatch_is_reported_not_hidden(self):
        network = estimate_minimum_density({"A": 60.0, "B": 30.0}, {"A": 40.0, "B": 35.0, "C": 25.0})
        assert network.marginal_mismatch > 0


class TestPosteriorDraws:
    """The structure bootstrap may move mass, never the declared totals."""

    def test_draws_preserve_marginals(self):
        network = estimate_bilateral_matrix(ASSETS, LIABS)
        draws = posterior_draws(network, n_draws=8, rng=np.random.default_rng(7))
        assert len(draws) == 8
        for draw in draws:
            assert np.allclose(draw.sum(axis=1), network.row_sums(), atol=1e-6)
            assert np.allclose(draw.sum(axis=0), network.col_sums(), atol=1e-6)
            assert np.allclose(np.diag(draw), 0.0)
            assert np.all(draw >= 0.0)

    def test_draws_differ_from_each_other_and_the_point_estimate(self):
        # On the 3-bank fixture the marginals nearly determine the structure
        # (6 free cells, 5 independent constraints), so genuine diversity
        # needs a system with real degrees of freedom in the transport polytope.
        rng = np.random.default_rng(11)
        nodes = [f"B{i}" for i in range(6)]
        assets = {n: float(rng.uniform(10.0, 100.0)) for n in nodes}
        liabs = {n: float(rng.uniform(10.0, 100.0)) for n in nodes}
        network = estimate_bilateral_matrix(assets, liabs)
        draws = posterior_draws(network, n_draws=4, rng=np.random.default_rng(11))
        assert not np.allclose(draws[0], draws[1])
        assert not np.allclose(draws[0], network.liabilities)

    def test_seed_reproduces_draws(self):
        network = estimate_bilateral_matrix(ASSETS, LIABS)
        first = posterior_draws(network, n_draws=3, rng=np.random.default_rng(42))
        second = posterior_draws(network, n_draws=3, rng=np.random.default_rng(42))
        for a, b in zip(first, second):
            assert np.allclose(a, b)

    def test_high_concentration_collapses_onto_point_estimate(self):
        network = estimate_bilateral_matrix(ASSETS, LIABS)
        draws = posterior_draws(
            network, n_draws=3, concentration=1e6, rng=np.random.default_rng(5)
        )
        for draw in draws:
            assert np.allclose(draw, network.liabilities, rtol=1e-3, atol=1e-6)

    def test_invalid_parameters_are_refused(self):
        network = estimate_bilateral_matrix(ASSETS, LIABS)
        with pytest.raises(ValueError):
            posterior_draws(network, n_draws=0)
        with pytest.raises(ValueError):
            posterior_draws(network, concentration=0.0)


class TestPropagation:
    """Clearing bands must be placebo-clean and structurally sensitive."""

    def test_placebo_full_endowments_no_shock_yields_no_shortfall(self):
        # With endowments equal to obligations and no shock, every institution
        # can pay in full on every draw: the machinery must not manufacture
        # contagion that the declarations do not contain.
        network = estimate_bilateral_matrix(ASSETS, LIABS)
        result = propagate_estimation_uncertainty(
            network,
            endowment_ratio=1.0,
            n_draws=8,
            rng=np.random.default_rng(3),
        )
        assert result.point["total_shortfall"] == pytest.approx(0.0, abs=1e-6)
        assert result.point["n_defaults"] == 0
        assert float(np.max(result.shortfall_draws)) == pytest.approx(0.0, abs=1e-6)

    def test_declared_shock_produces_shortfall_and_names_the_defaulted(self):
        # C is a net debtor (owes 25, is owed 10): destroying its endowment
        # leaves receipts of 10 against obligations of 25, so the shortfall is
        # exactly the declared gap and C is the institution named. A is a net
        # creditor and cannot be defaulted by an endowment shock alone -- the
        # engine must not invent that contagion.
        network = estimate_bilateral_matrix(ASSETS, LIABS)
        result = propagate_estimation_uncertainty(
            network,
            endowment_ratio=1.0,
            shocks={"C": 1.0},
            n_draws=8,
            rng=np.random.default_rng(3),
        )
        assert result.point["total_shortfall"] == pytest.approx(15.0, abs=1e-6)
        assert result.point["defaulted"] == ["C"]
        # every draw preserves the marginals, so the declared gap is invariant
        assert np.allclose(result.shortfall_draws, 15.0, atol=1e-6)

    def test_bands_are_ordered_percentiles(self):
        network = estimate_bilateral_matrix(ASSETS, LIABS)
        result = propagate_estimation_uncertainty(
            network,
            endowment_ratio=0.1,
            shocks={"B": 0.5},
            n_draws=24,
            rng=np.random.default_rng(13),
        )
        shortfall = result.bands["total_shortfall"]
        assert shortfall["p5"] <= shortfall["p50"] <= shortfall["p95"]
        defaults = result.bands["n_defaults"]
        assert defaults["p5"] <= defaults["p50"] <= defaults["p95"]
        assert result.n_draws == 24

    def test_marginal_randomization_moves_the_loss_distribution(self):
        # Placebo for structural sensitivity: keeping every declared total in
        # the system but re-pairing which institution holds which total must
        # change the propagated losses -- the bands respond to who owes whom,
        # not only to how much is owed in aggregate.
        network = estimate_bilateral_matrix(ASSETS, LIABS)
        permuted_assets = {
            node: ASSETS[network.node_ids[(i + 1) % len(network.node_ids)]]
            for i, node in enumerate(network.node_ids)
        }
        baseline = propagate_estimation_uncertainty(
            network, endowment_ratio=0.1, shocks={"A": 0.9}, n_draws=16,
            rng=np.random.default_rng(19),
        )
        permuted_network = estimate_bilateral_matrix(permuted_assets, LIABS)
        permuted = propagate_estimation_uncertainty(
            permuted_network, endowment_ratio=0.1, shocks={"A": 0.9}, n_draws=16,
            rng=np.random.default_rng(19),
        )
        assert not np.allclose(
            baseline.shortfall_draws, permuted.shortfall_draws, atol=1e-9
        )

    def test_unknown_shock_target_is_refused(self):
        network = estimate_bilateral_matrix(ASSETS, LIABS)
        with pytest.raises(ValueError, match="unknown institutions"):
            propagate_estimation_uncertainty(network, shocks={"GHOST": 0.5}, n_draws=2)

    def test_uncertainty_caveat_travels_with_the_bands(self):
        network = estimate_bilateral_matrix(ASSETS, LIABS)
        result = propagate_estimation_uncertainty(network, n_draws=2, rng=np.random.default_rng(1))
        assert "not" in result.uncertainty and "measured network" in result.uncertainty
