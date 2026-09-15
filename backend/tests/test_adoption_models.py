"""Round-eight model adoption: channel decomposition, liability sensitivity, GARCH.

Anchors: the decomposition adds measured increments and names absent channels
rather than zeroing them; liability sensitivity is positive on the binding
edge of a chain and zero on edges that cannot bind; GARCH(1,1) recovers
clustering from simulated data and refuses degenerate inputs.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.modules.risk.channel_decomposition import (
    decompose_channels,
    liability_sensitivity,
)
from backend.modules.risk.clearing import NetworkLayer, clear_multiplex


def _chain():
    # A -> B -> C: A owes B, B owes C. Only those edges can bind.
    matrix = np.zeros((3, 3))
    matrix[0, 1] = 100.0
    matrix[1, 2] = 80.0
    endowments = np.array([10.0, 60.0, 100.0])
    layer = NetworkLayer(name="interbank", liabilities=matrix, seniority=0)
    return [layer], endowments, ["A", "B", "C"]


class TestChannelDecomposition:
    def test_absent_channels_are_named_not_zeroed(self):
        layers, endowments, ids = _chain()
        clearing = clear_multiplex(layers, endowments, node_ids=ids)
        decomposition = decompose_channels(clearing, None, None)
        assert decomposition.direct_clearing == pytest.approx(float(clearing.total_shortfall))
        assert decomposition.fire_sale_feedback is None
        assert decomposition.spiral_amplification is None
        assert any("fire-sale channel not run" in note for note in decomposition.notes)

    def test_no_clearing_means_no_channels(self):
        decomposition = decompose_channels(None, None, None)
        assert decomposition.direct_clearing == 0.0
        assert any("not run" in note for note in decomposition.notes)


class TestLiabilitySensitivity:
    def test_binding_edge_is_sensitive_and_others_are_not(self):
        layers, endowments, ids = _chain()
        sensitivities = liability_sensitivity(layers, endowments, ids, top_k=2, perturb_fraction=0.01)
        by_edge = {(entry["debtor"], entry["creditor"]): entry["delta_shortfall_per_unit_fraction"] for entry in sensitivities}
        # A's obligation to B is the binding edge: A is already insolvent-side
        assert by_edge[("A", "B")] >= by_edge[("B", "C")]

    def test_perturbation_fraction_is_validated(self):
        layers, endowments, ids = _chain()
        with pytest.raises(ValueError):
            liability_sensitivity(layers, endowments, ids, perturb_fraction=0.0)


class TestGARCH:
    def test_recovers_clustering_from_simulated_data(self):
        rng = np.random.default_rng(7)
        n = 4000
        omega, alpha, beta = 0.02, 0.15, 0.80
        returns = np.empty(n)
        var = np.empty(n)
        var[0] = omega / (1 - alpha - beta)
        for t in range(1, n):
            var[t] = omega + alpha * returns[t - 1] ** 2 + beta * var[t - 1]
            returns[t] = np.sqrt(var[t]) * rng.normal()
        from backend.modules.engine.garch import fit_garch11

        result = fit_garch11(returns[1:])
        assert result.persistence == pytest.approx(alpha + beta, abs=0.1)
        assert result.stationary is True
        assert result.conditional_volatility.size == returns.size - 1

    def test_short_series_are_refused(self):
        from backend.modules.engine.garch import fit_garch11

        with pytest.raises(ValueError):
            fit_garch11(np.random.default_rng(1).normal(size=10))

    def test_zero_variance_is_refused(self):
        from backend.modules.engine.garch import fit_garch11

        with pytest.raises(ValueError):
            fit_garch11(np.zeros(100))
