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
