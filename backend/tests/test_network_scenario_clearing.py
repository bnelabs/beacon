"""Tests for the scenario-driven Eisenberg-Noe clearing wired into the
simulate endpoint (``_run_network_clearing``).

The helper clears the latest quarter of the AI4Risk edge rows under two
DECLARED assumptions (edge orientation, endowments as a fraction of gross
exposure). These tests lock in the mechanics of the declaration, including
the skip paths: the endpoint must say plainly when the clearing cannot run.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.api.routes.models_v1 import _run_network_clearing  # noqa: E402


def edge_frame() -> pd.DataFrame:
    """Two banks, one quarter: A holds 100 on B, B holds 80 on A.

    Edge convention (declared, not measured): sourceid holds a claim on
    targetid, so (debtor, creditor) = (target_bank, source_bank).
    """
    return pd.DataFrame(
        {
            "Date": ["2026-06-30", "2026-06-30"],
            "source_code": ["AI4RISK_EDGE_1", "AI4RISK_EDGE_2"],
            "series_id": ["AI4RISK::A->B", "AI4RISK::B->A"],
            "Value": [100.0, 80.0],
            "source_bank": ["A", "B"],
            "target_bank": ["B", "A"],
        }
    )


class TestNetworkClearing:
    def test_no_network_params_returns_none(self):
        assert _run_network_clearing(edge_frame(), {"stock_drop_pct": 0.2}) is None
        assert _run_network_clearing(edge_frame(), {}) is None

    def test_no_edge_columns_is_a_declared_skip(self):
        frame = pd.DataFrame({"Date": ["2026-06-30"], "source_code": ["STOCK_SPX"], "Value": [1.0]})
        result = _run_network_clearing(frame, {"failed_bank_id": "A"})
        assert result is not None
        assert "skipped" in result

    def test_failed_bank_defaults_and_the_assumptions_are_declared(self):
        result = _run_network_clearing(edge_frame(), {"failed_bank_id": "B", "endowment_fraction": 1.0})
        assert result is not None
        assert "skipped" not in result
        # B is insolvent (endowment zeroed) and A is solvent: A's claim on B
        # is funded only by B's endowment, but A's own obligation is fully
        # covered by its endowment plus the par claim it never needs to lose.
        assert result["n_defaults"] == 1
        assert result["default_sequence"] == ["B"]
        assumptions = result["declared_assumptions"]
        assert assumptions["failed_bank"] == {"bank": "B", "endowment": 0.0}
        assert assumptions["edge_orientation"]
        assert assumptions["endowments"]
        assert assumptions["as_of"] == "2026-06-30"

    def test_failed_bank_not_in_latest_quarter_is_declared(self):
        result = _run_network_clearing(edge_frame(), {"failed_bank_id": "ZZZ"})
        assert result is not None
        assert "skipped" in result
        assert "ZZZ" in result["skipped"]

    def test_liquidity_freeze_alone_triggers_the_clearing(self):
        result = _run_network_clearing(
            edge_frame(), {"interbank_lending_reduction": 0.5, "endowment_fraction": 1.0}
        )
        assert result is not None
        assert "skipped" not in result
        # Both banks' endowments equal their (reduced) gross exposures, so
        # the network still clears without default.
        assert result["n_defaults"] == 0
        assert result["total_shortfall"] == 0.0

    def test_negative_edge_values_are_declared_exclusions(self):
        frame = pd.concat(
            [
                edge_frame(),
                pd.DataFrame(
                    {
                        "Date": ["2026-06-30"],
                        "source_code": ["AI4RISK_EDGE_3"],
                        "series_id": ["AI4RISK::C->A"],
                        "Value": [-5.0],
                        "source_bank": ["C"],
                        "target_bank": ["A"],
                    }
                ),
            ],
            ignore_index=True,
        )
        result = _run_network_clearing(frame, {"failed_bank_id": "B"})
        assert result is not None
        assert "skipped" not in result
        assumptions = result["declared_assumptions"]
        assert assumptions["dropped_nonpositive_edges"] == 1
        # C never entered the network as a debtor or creditor.
        assert result["n_nodes"] == 2

    def test_multiple_quarters_use_the_latest_one(self):
        frame = pd.concat(
            [
                pd.DataFrame(
                    {
                        "Date": ["2026-03-31", "2026-03-31"],
                        "source_code": ["AI4RISK_EDGE_1", "AI4RISK_EDGE_2"],
                        "series_id": ["AI4RISK::A->B", "AI4RISK::B->A"],
                        "Value": [10.0, 8.0],
                        "source_bank": ["A", "B"],
                        "target_bank": ["B", "A"],
                    }
                ),
                edge_frame(),
            ],
            ignore_index=True,
        )
        result = _run_network_clearing(frame, {"failed_bank_id": "B"})
        assert result is not None
        assert result["declared_assumptions"]["as_of"] == "2026-06-30"
