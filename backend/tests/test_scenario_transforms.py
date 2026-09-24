"""Tests for scenario transforms: value-column coverage, unit/sign fixes,
type inference, and edge-frame handling in ``RealPredictionEngine.apply_scenario``.

The transforms run before inference and touch no model, so the engine is
constructed via ``object.__new__`` with only the attributes the transform
path reads.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

torch = pytest.importorskip("torch")

from backend.modules.engine.prediction_engine import RealPredictionEngine  # noqa: E402


def make_engine() -> RealPredictionEngine:
    engine = object.__new__(RealPredictionEngine)
    engine.config = {}
    engine.device = torch.device("cpu")
    return engine


def panel_frame() -> pd.DataFrame:
    """A joined panel: an OHLC equity series (Close), an indicator series
    (Value), an interest-rate series (Value), and two AI4Risk edge rows."""
    return pd.DataFrame(
        {
            "Date": pd.to_datetime(
                [
                    "2026-01-02", "2026-01-03",
                    "2026-01-02", "2026-01-03",
                    "2026-01-02", "2026-01-03",
                    "2026-01-02", "2026-01-03",
                ]
            ),
            "source_code": [
                "STOCK_SPX", "STOCK_SPX",
                "STOCK_VIX", "STOCK_VIX",
                "FRED_SOFR", "FRED_SOFR",
                "AI4RISK_EDGE_1", "AI4RISK_EDGE_2",
            ],
            "series_id": [
                "EQ_SPX::^GSPC", "EQ_SPX::^GSPC",
                "VOL_VIX::^VIX", "VOL_VIX::^VIX",
                "IR_US_FF", "IR_US_FF",
                "AI4RISK::0->1", "AI4RISK::1->0",
            ],
            "Close": [5000.0, 5100.0, None, None, None, None, None, None],
            "close": [5000.0, 5100.0, None, None, None, None, None, None],
            "Value": [None, None, 20.0, 21.0, 4.25, 4.25, 100.0, 80.0],
            "value": [None, None, 20.0, 21.0, 4.25, 4.25, 100.0, 80.0],
            "source_bank": [None, None, None, None, None, None, "A", "B"],
            "target_bank": [None, None, None, None, None, None, "B", "A"],
        }
    )


class TestInference:
    def test_rate_cut_without_type_infers_policy_intervention(self):
        engine = make_engine()
        frame = panel_frame()
        out = engine.apply_scenario(frame, {"rate_cut_bps": 50})
        fed = out[out["source_code"] == "FRED_SOFR"]["Value"].unique()
        # 4.25% minus 50bp = 4.25 - 0.50; the old /10000 moved it by 0.005.
        assert np.allclose(fed, 3.75)

    def test_explicit_type_wins_over_inference(self):
        engine = make_engine()
        frame = panel_frame()
        # rate_cut_bps present, but the caller names market_crash.
        out = engine.apply_scenario(frame, {"type": "market_crash", "rate_cut_bps": 50})
        fed = out[out["source_code"] == "FRED_SOFR"]["Value"].unique()
        assert np.allclose(fed, 4.25)  # untouched by market_crash
        spx = out[out["source_code"] == "STOCK_SPX"]["Close"].unique()
        assert np.allclose(spx, np.array([5000.0, 5100.0]) * (1 - 0.20))

    def test_no_params_is_custom_noop(self):
        engine = make_engine()
        frame = panel_frame()
        out = engine.apply_scenario(frame, {})
        assert out.equals(frame)


class TestValueColumnCoverage:
    def test_market_crash_touches_ohlc_close_and_value_series(self):
        engine = make_engine()
        out = engine.apply_scenario(panel_frame(), {"type": "market_crash"})
        spx = out[out["source_code"] == "STOCK_SPX"]["Close"].unique()
        vix = out[out["source_code"] == "STOCK_VIX"]["Value"].unique()
        assert np.allclose(spx, np.array([5000.0, 5100.0]) * 0.80)
        assert np.allclose(vix, np.array([20.0, 21.0]) * 2.0)
        # Lowercase mirror moves with the capitalised column.
        spx_low = out[out["source_code"] == "STOCK_SPX"]["close"].unique()
        assert np.allclose(spx_low, np.array([5000.0, 5100.0]) * 0.80)

    def test_unmatched_sources_are_untouched(self):
        engine = make_engine()
        out = engine.apply_scenario(panel_frame(), {"type": "market_crash"})
        fed = out[out["source_code"] == "FRED_SOFR"]["Value"].unique()
        assert np.allclose(fed, 4.25)


class TestEdgeFrames:
    def test_liquidity_freeze_scales_only_edge_rows(self):
        engine = make_engine()
        out = engine.apply_scenario(
            panel_frame(), {"type": "liquidity_freeze", "interbank_lending_reduction": 0.5}
        )
        edges = out[out["source_bank"].notna()]["Value"].unique()
        scalars = out[out["source_bank"].isna() & (out["source_code"] != "STOCK_SPX")]["Value"].unique()
        assert np.allclose(edges, [50.0, 40.0])
        assert np.allclose(sorted(scalars), [4.25, 20.0, 21.0])

    def test_bank_failure_haircuts_claims_on_it_and_zeroes_its_claims(self):
        engine = make_engine()
        out = engine.apply_scenario(
            panel_frame(),
            {"type": "bank_failure", "failed_bank_id": "B", "exposure_haircut": 0.5},
        )
        by_src = out.set_index("source_code")["Value"].to_dict()
        # A holds a claim on B (edge A->B): haircut. B holds a claim on A
        # (edge B->A): the failed bank's own claim goes to zero.
        assert by_src["AI4RISK_EDGE_1"] == 50.0
        assert by_src["AI4RISK_EDGE_2"] == 0.0

    def test_regional_shock_without_region_column_is_declared_not_silent(self):
        engine = make_engine()
        frame = panel_frame()
        out = engine.apply_scenario(
            frame, {"type": "regional_shock", "regional_shocks": [{"region": "europe", "magnitude": -0.1}]}
        )
        # No region column -> nothing applied; the data is unchanged.
        assert out.equals(frame)


class TestCombined:
    def test_combined_applies_every_applicable_subtype(self):
        engine = make_engine()
        out = engine.apply_scenario(
            panel_frame(),
            {"rate_cut_bps": 50, "stock_drop_pct": 0.20, "interbank_lending_reduction": 0.5},
        )
        fed = out[out["source_code"] == "FRED_SOFR"]["Value"].unique()
        spx = out[out["source_code"] == "STOCK_SPX"]["Close"].unique()
        edges = out[out["source_bank"].notna()]["Value"].unique()
        assert np.allclose(fed, 3.75)
        assert np.allclose(spx, np.array([5000.0, 5100.0]) * 0.80)
        assert np.allclose(sorted(edges), [40.0, 50.0])
