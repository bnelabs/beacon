"""Tests for feeding the systemic modules from the multi-bank analysis.

The modules themselves are tested in their own files. What is tested here is the
*wiring*: that every optional input is either used or explicitly refused, that a
missing input stays missing rather than becoming a zero, and that an input which
cannot be honoured raises instead of producing a table that silently omits part of
the system.

The first test is a regression guard and exists for a specific reason. During
development the fire-sale call was accidentally placed inside the topology
branch, so a supplied scenario was validated and then silently ignored unless
topology happened to be requested as well. The whole suite stayed green. Nothing
here asserts "it did not raise" — it asserts that a supplied input produces a
result, which is the property that was actually broken.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
import torch

from backend.modules.engine.persistence_vectors import SUMMARY_FEATURES
from backend.modules.engine.prediction_engine import RealPredictionEngine
from backend.modules.engine.portfolio_overlap import PortfolioOverlapDataError
from backend.modules.risk.bank_analyzer import BankRiskAnalyzer
from backend.modules.risk.fire_sale import FireSaleScenario
from backend.modules.risk.regulatory import (
    InstitutionState,
    LeveragePosition,
    LiquidityPosition,
    StableFundingPosition,
    translate_systemic_stress,
)


class StubModel(torch.nn.Module):
    """A model that returns a constant score, so the wiring is what is tested."""

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


EXPOSURES = {("B1", "B2"): 100.0}
ENDOWMENTS = {"B1": 50.0, "B2": 50.0}


def institution_state(bank_id: str, *, tier1: float = 20.0) -> InstitutionState:
    """A minimal but complete Basel III position for one institution."""
    return InstitutionState(
        institution_id=bank_id,
        liquidity=LiquidityPosition(
            level1_assets=100.0,
            level2a_assets=0.0,
            level2b_assets=0.0,
            outflows_by_category={"stable_retail_deposits": 50.0},
            inflows_by_category={"retail_loans": 10.0},
        ),
        funding=StableFundingPosition(
            asf_by_category={"tier1_capital": 40.0, "stable_retail_deposits": 60.0},
            rsf_by_category={"hqla_level1": 100.0, "loans_retail_over_1y": 20.0},
        ),
        leverage=LeveragePosition(
            tier1_capital=tier1,
            on_balance_sheet_assets=400.0,
            derivative_exposure=0.0,
            off_balance_sheet_items={"commitments_over_1y": 20.0},
        ),
        price_sensitive_assets=80.0,
    )


def fire_sale_scenario() -> FireSaleScenario:
    return FireSaleScenario(
        institution_ids=["B1", "B2"],
        asset_ids=["X"],
        holdings=np.array([[10.0], [0.0]]),
        prices=np.array([10.0]),
        capital=np.array([1000.0, 0.0]),
        endowments=np.array([0.0, 0.0]),
        liabilities=np.array([[0.0, 150.0], [0.0, 0.0]]),
        margins=np.array([1.0, 1.0]),
        price_impacts=np.array([0.5]),
        price_shock=np.array([0.0]),
    )


class TestFireSaleIsActuallySolved:
    """Regression: the call was once reachable only via the topology branch."""

    def test_a_supplied_scenario_produces_a_result(self, analyzer, bank_data):
        analysis = analyzer.analyze_multiple_banks(
            bank_data,
            EXPOSURES,
            None,
            ENDOWMENTS,
            fire_sale_scenario=fire_sale_scenario(),
        )
        assert analysis.fire_sale is not None
        assert analysis.fire_sale.converged or analysis.fire_sale.diverged
        assert analysis.to_dict()["fire_sale"] is not None

    def test_the_scenario_is_ignored_only_when_it_is_absent(self, analyzer, bank_data):
        analysis = analyzer.analyze_multiple_banks(bank_data, EXPOSURES, None, ENDOWMENTS)
        assert analysis.fire_sale is None

    def test_a_scenario_for_other_institutions_raises(self, analyzer, bank_data):
        scenario = fire_sale_scenario()
        scenario = FireSaleScenario(
            institution_ids=["B1", "ZZ"],
            asset_ids=scenario.asset_ids,
            holdings=scenario.holdings,
            prices=scenario.prices,
            capital=scenario.capital,
            endowments=scenario.endowments,
            liabilities=scenario.liabilities,
            margins=scenario.margins,
            price_impacts=scenario.price_impacts,
            price_shock=scenario.price_shock,
        )
        with pytest.raises(ValueError, match="different institution set"):
            analyzer.analyze_multiple_banks(
                bank_data, EXPOSURES, None, ENDOWMENTS, fire_sale_scenario=scenario
            )


class TestRegulatoryStates:
    def test_states_are_translated_and_attached(self, analyzer, bank_data):
        states = [institution_state("B1"), institution_state("B2", tier1=30.0)]
        analysis = analyzer.analyze_multiple_banks(
            bank_data,
            EXPOSURES,
            None,
            ENDOWMENTS,
            regulatory_states=states,
        )
        assert analysis.regulatory_stress is not None
        assert {row.institution_id for row in analysis.regulatory_stress.rows} == {
            "B1",
            "B2",
        }
        # Independently: the same call, made directly, must give the same rows.
        direct = translate_systemic_stress(states, clearing=analysis.clearing)
        assert analysis.regulatory_stress.to_dict() == direct.to_dict()

    def test_a_price_decline_reaches_the_translation(self, analyzer, bank_data):
        states = [institution_state("B1"), institution_state("B2")]
        analysis = analyzer.analyze_multiple_banks(
            bank_data,
            EXPOSURES,
            None,
            ENDOWMENTS,
            regulatory_states=states,
            price_decline=0.5,
        )
        assert analysis.regulatory_stress is not None
        assert analysis.regulatory_stress.stress_applied is True

    def test_partial_coverage_raises(self, analyzer, bank_data):
        with pytest.raises(ValueError, match="must cover every analysed institution"):
            analyzer.analyze_multiple_banks(
                bank_data,
                EXPOSURES,
                None,
                ENDOWMENTS,
                regulatory_states=[institution_state("B1")],
            )

    def test_an_unknown_institution_raises(self, analyzer, bank_data):
        with pytest.raises(KeyError, match="outside the analysis"):
            analyzer.analyze_multiple_banks(
                bank_data,
                EXPOSURES,
                None,
                ENDOWMENTS,
                regulatory_states=[institution_state("B1"), institution_state("ZZ")],
            )

    def test_a_repeated_institution_raises(self, analyzer, bank_data):
        with pytest.raises(ValueError, match="repeats institution"):
            analyzer.analyze_multiple_banks(
                bank_data,
                EXPOSURES,
                None,
                ENDOWMENTS,
                regulatory_states=[institution_state("B1"), institution_state("B1")],
            )

    def test_absent_states_leave_the_field_none(self, analyzer, bank_data):
        analysis = analyzer.analyze_multiple_banks(bank_data, EXPOSURES, None, ENDOWMENTS)
        assert analysis.regulatory_stress is None
        assert analysis.to_dict()["regulatory_stress"] is None


class TestHoldings:
    def holdings(self, index=("B1", "B2")) -> pd.DataFrame:
        rows = len(index)
        return pd.DataFrame(
            {
                "BOND": [10.0] + [0.0] * (rows - 1),
                "EQUITY": [0.0] * (rows - 1) + [8.0],
                "CDS": [2.0] * rows,
            },
            index=list(index),
        )

    def test_crowding_is_attached(self, analyzer, bank_data):
        analysis = analyzer.analyze_multiple_banks(
            bank_data, EXPOSURES, None, ENDOWMENTS, holdings=self.holdings()
        )
        assert analysis.crowding is not None
        assert list(analysis.crowding.institution_ids) == ["B1", "B2"]
        assert list(analysis.crowding.instrument_ids) == ["BOND", "EQUITY", "CDS"]
        assert analysis.crowding.system_crowding.normalized > 0.0
        assert analysis.to_dict()["crowding"] is not None

    def test_a_subset_of_the_institutions_is_allowed(self, analyzer, bank_data):
        analysis = analyzer.analyze_multiple_banks(
            bank_data,
            EXPOSURES,
            None,
            ENDOWMENTS,
            holdings=self.holdings(index=("B1",)),
        )
        assert analysis.crowding is not None
        assert list(analysis.crowding.institution_ids) == ["B1"]

    def test_an_unknown_institution_raises(self, analyzer, bank_data):
        with pytest.raises(KeyError, match="outside the analysis"):
            analyzer.analyze_multiple_banks(
                bank_data,
                EXPOSURES,
                None,
                ENDOWMENTS,
                holdings=self.holdings(index=("B1", "ZZ")),
            )

    def test_missing_holdings_fail_closed_rather_than_becoming_zero(self, analyzer, bank_data):
        frame = self.holdings()
        frame.loc["B2", "BOND"] = np.nan
        with pytest.raises(PortfolioOverlapDataError):
            analyzer.analyze_multiple_banks(
                bank_data, EXPOSURES, None, ENDOWMENTS, holdings=frame
            )

    def test_a_non_frame_raises(self, analyzer, bank_data):
        with pytest.raises(TypeError, match="must be a DataFrame"):
            analyzer.analyze_multiple_banks(
                bank_data, EXPOSURES, None, ENDOWMENTS, holdings=[[1.0, 2.0]]
            )

    def test_absent_holdings_leave_the_field_none(self, analyzer, bank_data):
        analysis = analyzer.analyze_multiple_banks(bank_data, EXPOSURES, None, ENDOWMENTS)
        assert analysis.crowding is None
        assert analysis.to_dict()["crowding"] is None


class TestTopology:
    @staticmethod
    def parameters():
        from backend.modules.engine.persistence_vectors import (
            PersistenceVectorParameters,
        )

        return PersistenceVectorParameters(
            grid=np.linspace(0.0, 100.0, 9),
            n_landscapes=2,
            image_resolution=4,
            birth_range=(0.0, 100.0),
            death_range=(0.0, 100.0),
            sigma=5.0,
        )

    def test_features_are_attached_when_the_network_exists(self, analyzer, bank_data):
        analysis = analyzer.analyze_multiple_banks(
            bank_data,
            EXPOSURES,
            None,
            ENDOWMENTS,
            topology_parameters=self.parameters(),
        )
        assert analysis.topology is not None
        assert set(analysis.topology.summary) == set(SUMMARY_FEATURES)
        assert analysis.topology.to_dict()["width"] == len(analysis.topology.vector)

    def test_requesting_topology_without_a_network_raises(self, analyzer, bank_data):
        with pytest.raises(ValueError, match="network is unavailable"):
            analyzer.analyze_multiple_banks(
                bank_data,
                None,
                None,
                None,
                topology_parameters=self.parameters(),
            )

    def test_absent_parameters_leave_the_field_none(self, analyzer, bank_data):
        analysis = analyzer.analyze_multiple_banks(bank_data, EXPOSURES, None, ENDOWMENTS)
        assert analysis.topology is None
        assert analysis.to_dict()["topology"] is None


class TestSerialisationAndReport:
    def test_every_module_serialises_together(self, analyzer, bank_data):
        analysis = analyzer.analyze_multiple_banks(
            bank_data,
            EXPOSURES,
            None,
            ENDOWMENTS,
            regulatory_states=[institution_state("B1"), institution_state("B2")],
            price_decline=0.2,
            holdings=TestHoldings().holdings(),
            topology_parameters=TestTopology.parameters(),
        )
        json.dumps(analysis.to_dict(), allow_nan=False)

    def test_the_report_names_what_is_missing(self, analyzer, bank_data):
        analysis = analyzer.analyze_multiple_banks(bank_data, EXPOSURES, None, ENDOWMENTS)
        engine = object.__new__(RealPredictionEngine)
        report = RealPredictionEngine._generate_multi_bank_explanation_report(
            engine, analysis
        )
        assert "Basel III stress translation: UNAVAILABLE" in report
        assert "Crowded-trade overlap: UNAVAILABLE" in report
        assert "Network topology: UNAVAILABLE" in report

    def test_the_report_renders_what_is_present(self, analyzer, bank_data):
        analysis = analyzer.analyze_multiple_banks(
            bank_data,
            EXPOSURES,
            None,
            ENDOWMENTS,
            regulatory_states=[institution_state("B1"), institution_state("B2")],
            holdings=TestHoldings().holdings(),
            topology_parameters=TestTopology.parameters(),
        )
        engine = object.__new__(RealPredictionEngine)
        report = RealPredictionEngine._generate_multi_bank_explanation_report(
            engine, analysis
        )
        assert "Basel III stress translation: UNAVAILABLE" not in report
        assert "LCR:" in report
        assert "Crowded-trade overlap across 2 institution(s)" in report
        assert "Network topology:" in report and "redundancy" in report
