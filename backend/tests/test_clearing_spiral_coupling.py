"""The clearing engine drives the liquidity spiral -- the coupling, not the parts.

The Eisenberg-Noe clearing engine (``backend/modules/risk/clearing.py``) and the
Brunnermeier-Pedersen spiral (``backend/modules/risk/liquidity_spiral.py``) were
both implemented and separately tested, and the spiral's own docstring claimed it
"composes with the clearing engine". Nothing actually joined them: clearing
produced a shortfall and the spiral expected a price shock, with no translation
in between. A module that is correct in isolation but never fed by the engine is
a capability the system does not have.

This file tests the join: that a real clearing shortfall becomes a shock, that the
spiral is solved from it, and that every way of *not* having the required input
raises instead of silently producing a spiral from nothing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch

from backend.modules.engine.prediction_engine import RealPredictionEngine
from backend.modules.risk.bank_analyzer import BankRiskAnalyzer
from backend.modules.risk.liquidity_spiral import SpiralParameters, shock_from_shortfall


class StubModel(torch.nn.Module):
    """A constant score, so the *wiring* is what these tests exercise."""

    def __init__(self, score: float = 0.4) -> None:
        super().__init__()
        self.score = float(score)

    def forward(self, inputs: torch.Tensor, source_ids: torch.Tensor) -> torch.Tensor:
        return torch.full((inputs.shape[0], 1), self.score)


@pytest.fixture
def analyzer() -> BankRiskAnalyzer:
    return BankRiskAnalyzer(
        StubModel(),
        torch.device("cpu"),
        sequence_length=4,
        source_stats={},
        source_to_id={},
    )


@pytest.fixture
def bank_data() -> dict:
    return {
        "B1": pd.DataFrame({"Value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}),
        "B2": pd.DataFrame({"Value": [2.0, 3.0, 4.0, 5.0, 6.0, 7.0]}),
    }


# B1 owes B2 100 and holds 50 of external assets, so B1 -- and only B1 -- fails to
# pay, with a shortfall of exactly 50.
EXPOSURES = {("B1", "B2"): 100.0}
ENDOWMENTS = {"B1": 50.0, "B2": 50.0}
B1_SHORTFALL = 50.0

PRICE = 10.0
PRICE_IMPACT = 0.01


def spiral_parameters(**overrides) -> SpiralParameters:
    """A financeable holder: margin * price * position == capital exactly."""
    values = {
        "price": PRICE,
        "position": 1.0,
        "capital": 5.0,
        "margin": 0.5,
        "price_impact": PRICE_IMPACT,
    }
    values.update(overrides)
    return SpiralParameters(**values)


class TestShockTranslation:
    def test_zero_shortfall_forces_no_sale(self):
        assert shock_from_shortfall(0.0, price=PRICE, price_impact=PRICE_IMPACT) == 0.0

    def test_a_shortfall_produces_an_adverse_move(self):
        shock = shock_from_shortfall(B1_SHORTFALL, price=PRICE, price_impact=PRICE_IMPACT)
        # 50 / 10 = 5 units sold, at 0.01 per unit -> 0.05 adverse.
        assert shock == pytest.approx(-0.05)
        assert shock < 0.0

    def test_the_move_is_linear_in_the_shortfall(self):
        one = shock_from_shortfall(B1_SHORTFALL, price=PRICE, price_impact=PRICE_IMPACT)
        two = shock_from_shortfall(2 * B1_SHORTFALL, price=PRICE, price_impact=PRICE_IMPACT)
        assert two == pytest.approx(2 * one)

    def test_no_price_impact_means_no_shock(self):
        assert (
            shock_from_shortfall(B1_SHORTFALL, price=PRICE, price_impact=0.0) == 0.0
        )

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"price": 0.0, "price_impact": 0.1},
            {"price": -1.0, "price_impact": 0.1},
            {"price": float("nan"), "price_impact": 0.1},
            {"price": PRICE, "price_impact": -0.1},
            {"price": PRICE, "price_impact": float("inf")},
        ],
    )
    def test_nonsensical_inputs_raise(self, kwargs):
        with pytest.raises(ValueError):
            shock_from_shortfall(B1_SHORTFALL, **kwargs)

    def test_a_negative_shortfall_raises_rather_than_flipping_the_sign(self):
        """A surplus forces no sale; it must not become an adverse shock."""
        with pytest.raises(ValueError, match="non-negative"):
            shock_from_shortfall(-1.0, price=PRICE, price_impact=PRICE_IMPACT)

    def test_a_non_finite_shortfall_raises(self):
        with pytest.raises(ValueError):
            shock_from_shortfall(float("nan"), price=PRICE, price_impact=PRICE_IMPACT)


class TestCouplingThroughAnalysis:
    def test_the_clearing_shortfall_becomes_the_spiral_shock(self, analyzer, bank_data):
        analysis = analyzer.analyze_multiple_banks(
            bank_data,
            EXPOSURES,
            bank_endowments=ENDOWMENTS,
            spiral_parameters={"B1": spiral_parameters()},
        )

        assert analysis.clearing is not None
        assert analysis.clearing.total_shortfall == pytest.approx(B1_SHORTFALL)

        assert set(analysis.liquidity_spiral) == {"B1"}
        result = analysis.liquidity_spiral["B1"]
        # The shock is exactly the translated clearing shortfall -- not a constant.
        assert result.shock == pytest.approx(
            shock_from_shortfall(B1_SHORTFALL, price=PRICE, price_impact=PRICE_IMPACT)
        )
        assert result.total_price_change <= result.shock  # adverse move only grows
        assert result.amplification >= 1.0

    def test_a_non_defaulting_institution_with_parameters_has_no_spiral(
        self, analyzer, bank_data
    ):
        """B2 does not fail to pay, so its shortfall is zero and nothing is forced."""
        analysis = analyzer.analyze_multiple_banks(
            bank_data,
            EXPOSURES,
            bank_endowments=ENDOWMENTS,
            spiral_parameters={"B1": spiral_parameters(), "B2": spiral_parameters()},
        )

        assert analysis.liquidity_spiral["B2"].shock == 0.0
        assert analysis.liquidity_spiral["B2"].amplification == pytest.approx(1.0)

    def test_the_result_serialises_the_spiral(self, analyzer, bank_data):
        analysis = analyzer.analyze_multiple_banks(
            bank_data,
            EXPOSURES,
            bank_endowments=ENDOWMENTS,
            spiral_parameters={"B1": spiral_parameters()},
        )
        payload = analysis.to_dict()

        assert "liquidity_spiral" in payload
        assert set(payload["liquidity_spiral"]) == {"B1"}
        assert "amplification" in payload["liquidity_spiral"]["B1"]

    def test_the_shortfall_the_spiral_receives_tracks_the_endowment(self, analyzer, bank_data):
        """Halving the endowment deepens the default and must deepen the shock."""
        shallow = analyzer.analyze_multiple_banks(
            bank_data,
            EXPOSURES,
            bank_endowments={"B1": 50.0, "B2": 50.0},
            spiral_parameters={"B1": spiral_parameters()},
        ).liquidity_spiral["B1"]

        deep = analyzer.analyze_multiple_banks(
            bank_data,
            EXPOSURES,
            bank_endowments={"B1": 25.0, "B2": 50.0},
            spiral_parameters={"B1": spiral_parameters()},
        ).liquidity_spiral["B1"]

        assert deep.shock < shallow.shock


class TestFailClosed:
    def test_spiral_without_a_clearing_equilibrium_raises(self, analyzer, bank_data):
        """The shock is the shortfall; with no clearing there is no shock."""
        with pytest.raises(ValueError, match="no clearing equilibrium"):
            analyzer.analyze_multiple_banks(
                bank_data,
                EXPOSURES,
                bank_endowments=None,
                spiral_parameters={"B1": spiral_parameters()},
            )

    def test_spiral_without_topology_at_all_raises(self, analyzer, bank_data):
        with pytest.raises(ValueError, match="no clearing equilibrium"):
            analyzer.analyze_multiple_banks(
                bank_data,
                None,
                spiral_parameters={"B1": spiral_parameters()},
            )

    def test_a_partial_spiral_table_raises_rather_than_omitting_an_institution(
        self, analyzer, bank_data
    ):
        """Omitting a defaulter would read as though it had no spiral."""
        with pytest.raises(ValueError, match="must cover every institution"):
            analyzer.analyze_multiple_banks(
                bank_data,
                EXPOSURES,
                bank_endowments=ENDOWMENTS,
                spiral_parameters={"B2": spiral_parameters()},
            )

    def test_an_unknown_institution_raises(self, analyzer, bank_data):
        with pytest.raises(KeyError, match="outside the analysis"):
            analyzer.analyze_multiple_banks(
                bank_data,
                EXPOSURES,
                bank_endowments=ENDOWMENTS,
                spiral_parameters={
                    "B1": spiral_parameters(),
                    "GHOST": spiral_parameters(),
                },
            )

    def test_a_wrongly_typed_parameter_raises(self, analyzer, bank_data):
        with pytest.raises(TypeError, match="SpiralParameters"):
            analyzer.analyze_multiple_banks(
                bank_data,
                EXPOSURES,
                bank_endowments=ENDOWMENTS,
                spiral_parameters={"B1": {"price": 10.0}},
            )


class TestReachabilityFromTheEngine:
    """The coupling must be reachable from the engine, not only from the analyzer."""

    def _input_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "bank_id": ["B1"] * 6 + ["B2"] * 6,
                "Value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
            }
        )

    def test_predict_forwards_spiral_parameters(self, analyzer):
        engine = object.__new__(RealPredictionEngine)
        engine.bank_analyzer = analyzer
        engine.config = {"job_id": "spiral-reachability"}
        engine.model_path = "unused"

        result = RealPredictionEngine._predict_multi_bank(
            engine,
            self._input_frame(),
            EXPOSURES,
            ENDOWMENTS,
            {"B1": spiral_parameters()},
        )

        assert result.multi_bank_analysis is not None
        assert set(result.multi_bank_analysis.liquidity_spiral) == {"B1"}

    def test_the_report_renders_the_spiral(self, analyzer):
        engine = object.__new__(RealPredictionEngine)
        engine.bank_analyzer = analyzer
        engine.config = {"job_id": "spiral-report"}
        engine.model_path = "unused"

        result = RealPredictionEngine._predict_multi_bank(
            engine,
            self._input_frame(),
            EXPOSURES,
            ENDOWMENTS,
            {"B1": spiral_parameters()},
        )
        report = result.explanation_report

        assert "Liquidity spiral (Brunnermeier-Pedersen)" in report
        assert "UNAVAILABLE" not in report.split("Liquidity spiral")[1].split("\n\n")[0]

    def test_the_report_says_unavailable_when_no_spiral_was_requested(self, analyzer):
        engine = object.__new__(RealPredictionEngine)
        engine.bank_analyzer = analyzer
        engine.config = {"job_id": "spiral-absent"}
        engine.model_path = "unused"

        result = RealPredictionEngine._predict_multi_bank(
            engine, self._input_frame(), EXPOSURES, ENDOWMENTS, None
        )

        assert "Liquidity spiral: UNAVAILABLE" in result.explanation_report
