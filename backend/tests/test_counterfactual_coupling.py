"""The counterfactual capability is reachable from the engine, not just importable.

``backend/modules/engine/tncm_vae.py`` implements abduction, intervention and
propagation with a thorough test suite, and nothing in production imported it: the
only module that touched it was ``causal_validation.py``, which is itself
unreachable. The engine could therefore not answer a counterfactual question at
all, while the documentation described counterfactual analysis as a capability.

These tests cover the *wiring* and the honesty properties that the wiring must
preserve. The causal machinery itself is tested in ``test_tncm_vae.py``; what is
established here is that a caller can drive it through the engine, that every
malformed scenario fails closed, and that the output cannot be mistaken for a
forecast.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch

from backend.modules.engine.causal_discovery import (
    NoteArsBasisConfig,
    NoteArsConfig,
    NoteArsResult,
    notears_basis,
    notears_linear,
)
from backend.modules.engine.counterfactual import (
    CONDITIONALITY_NOTE,
    CounterfactualOutcome,
    CounterfactualScenario,
    CounterfactualScenarioError,
    run_counterfactual,
    structural_model_from_weights,
)
from backend.modules.engine.prediction_engine import RealPredictionEngine
from backend.modules.engine.tncm_vae import (
    Intervention,
    StructuralCausalModel,
    TrajectoryConstraints,
)
from backend.modules.risk.bank_analyzer import BankRiskAnalyzer


class StubModel(torch.nn.Module):
    def forward(self, inputs: torch.Tensor, source_ids: torch.Tensor) -> torch.Tensor:
        return torch.full((inputs.shape[0], 1), 0.4)


@pytest.fixture
def analyzer() -> BankRiskAnalyzer:
    return BankRiskAnalyzer(
        StubModel(),
        torch.device("cpu"),
        sequence_length=4,
        source_stats={},
        source_to_id={},
    )


def declared_model() -> StructuralCausalModel:
    """``F1 -> F2`` plus own lags, so an intervention persists through them."""
    return StructuralCausalModel(
        ["F1", "F2"],
        coefficients={"F2": {"F1": 0.7}},
        self_lag={"F1": 0.5, "F2": 0.4},
    )


def scenario(**overrides) -> CounterfactualScenario:
    values = {
        "model": declared_model(),
        "observations": np.zeros((4, 2)),
        "interventions": (Intervention("F1", 1.5),),
    }
    values.update(overrides)
    return CounterfactualScenario(**values)


def fabricated_result(
    adjacency: np.ndarray,
    weights: np.ndarray,
    *,
    variables=("X1", "X2"),
    acyclic: bool = True,
    solver: str = "linear",
) -> NoteArsResult:
    """A ``NoteArsResult`` built directly, so failure paths can be driven exactly."""
    return NoteArsResult(
        variables=tuple(variables),
        weights=np.asarray(weights, dtype=float),
        adjacency=np.asarray(adjacency, dtype=float),
        h_trace=(),
        h_final=0.0,
        objective=0.0,
        structural_loss=0.0,
        l1_penalty=0.0,
        acyclic=acyclic,
        raw_pattern_acyclic=False,
        converged=True,
        threshold=0.3,
        l1_strength=0.1,
        standardised=False,
        hit_bound=False,
        n_starts=1,
        solver=solver,
    )


class TestScenarioFailsClosed:
    def test_a_run_of_a_declared_scenario_produces_a_counterfactual(self):
        outcome = run_counterfactual(scenario())
        assert isinstance(outcome, CounterfactualOutcome)
        assert "F1" in outcome.moved

    def test_a_bare_model_is_not_a_scenario(self):
        """Passing the model alone must not silently run with no intervention."""
        with pytest.raises(CounterfactualScenarioError, match="CounterfactualScenario"):
            run_counterfactual(declared_model())  # type: ignore[arg-type]

    def test_no_intervention_raises(self):
        with pytest.raises(CounterfactualScenarioError, match="at least one"):
            scenario(interventions=())

    def test_an_unknown_intervention_variable_raises(self):
        with pytest.raises(CounterfactualScenarioError, match="unknown variable"):
            scenario(interventions=(Intervention("F9", 1.0),))

    def test_observations_must_match_the_declared_variable_count(self):
        with pytest.raises(CounterfactualScenarioError, match="column"):
            scenario(observations=np.zeros((4, 3)))

    def test_a_one_dimensional_trajectory_raises(self):
        with pytest.raises(CounterfactualScenarioError, match="n_steps"):
            scenario(observations=np.zeros(4))

    def test_an_empty_trajectory_raises(self):
        with pytest.raises(CounterfactualScenarioError, match="at least one timestep"):
            scenario(observations=np.zeros((0, 2)))

    def test_non_finite_observations_raise(self):
        bad = np.zeros((4, 2))
        bad[1, 0] = np.nan
        with pytest.raises(CounterfactualScenarioError, match="non-finite"):
            scenario(observations=bad)

    def test_a_non_model_raises(self):
        with pytest.raises(CounterfactualScenarioError, match="StructuralCausalModel"):
            scenario(model={"F1": {}})  # type: ignore[arg-type]

    def test_a_wrong_constraints_type_raises(self):
        with pytest.raises(CounterfactualScenarioError, match="TrajectoryConstraints"):
            scenario(constraints={"F1": 0.0})  # type: ignore[arg-type]

    def test_a_non_intervention_entry_raises(self):
        with pytest.raises(CounterfactualScenarioError, match="Intervention"):
            scenario(interventions=("F1",))  # type: ignore[arg-type]


class TestConstraintsAreReportedNotClipped:
    def test_a_violation_is_surfaced_on_the_outcome(self):
        constrained = scenario(
            interventions=(Intervention("F1", 100.0),),
            constraints=TrajectoryConstraints(upper={"F1": 1.0}),
        )
        outcome = run_counterfactual(constrained)
        assert outcome.result.constraints_ok is False
        assert outcome.result.constraint_violations

    def test_a_satisfied_constraint_reports_ok(self):
        outcome = run_counterfactual(
            scenario(constraints=TrajectoryConstraints(lower={"F1": -1e9}))
        )
        assert outcome.result.constraints_ok is True


class TestOutputCannotBeMistakenForAForecast:
    def test_the_serialised_outcome_is_explicitly_not_a_forecast(self):
        payload = run_counterfactual(scenario()).to_dict()
        assert payload["is_forecast"] is False
        assert payload["conditionality_note"] == CONDITIONALITY_NOTE
        assert "not a prediction of the world" in payload["conditionality_note"]

    def test_the_outcome_records_what_it_was_conditioned_on(self):
        payload = run_counterfactual(scenario()).to_dict()
        assert "declared structural model" in payload["reference"]

    def test_plain_json_survives(self):
        import json

        assert json.dumps(run_counterfactual(scenario()).to_dict(), allow_nan=False)


class TestStructuralModelFromWeights:
    def test_a_linear_fit_converts_into_a_structural_model(self):
        result = fabricated_result(
            adjacency=np.array([[0.0, 1.0], [0.0, 0.0]]),  # adjacency[parent, child]
            weights=np.array([[0.0, 0.8], [0.0, 0.0]]),  # weights[parent, child]
        )
        model = structural_model_from_weights(result)
        assert model.parents["X2"] == ("X1",)
        assert model.coefficients["X2"]["X1"] == pytest.approx(0.8)

    def test_a_basis_fit_is_rejected_rather_than_read_as_coefficients(self):
        """Basis weights are block norms; reading them as coefficients invents them."""
        result = fabricated_result(
            adjacency=np.array([[0.0, 1.0], [0.0, 0.0]]),
            weights=np.array([[0.0, 0.8], [0.0, 0.0]]),
            solver="basis",
        )
        with pytest.raises(CounterfactualScenarioError, match="group norms"):
            structural_model_from_weights(result)

    def test_a_cyclic_fit_is_rejected(self):
        result = fabricated_result(
            adjacency=np.array([[0.0, 1.0], [1.0, 0.0]]),
            weights=np.array([[0.0, 0.9], [0.9, 0.0]]),
            acyclic=False,
        )
        with pytest.raises(CounterfactualScenarioError, match="not acyclic"):
            structural_model_from_weights(result)

    def test_a_non_result_is_rejected(self):
        with pytest.raises(CounterfactualScenarioError, match="NoteArsResult"):
            structural_model_from_weights(object())  # type: ignore[arg-type]

    def test_a_real_linear_fit_converts(self):
        rng = np.random.default_rng(3)
        n = 600
        x1 = rng.standard_normal(n)
        x2 = 0.9 * x1 + rng.standard_normal(n)
        result = notears_linear(
            np.column_stack([x1, x2]),
            ["X1", "X2"],
            NoteArsConfig(l1_strength=0.1, threshold=0.3, seed=0),
        )
        model = structural_model_from_weights(result, self_lag={"X1": 0.3})
        assert set(model.variables) == {"X1", "X2"}

    def test_a_real_basis_fit_is_rejected(self):
        rng = np.random.default_rng(4)
        n = 600
        x1 = rng.standard_normal(n)
        x2 = np.sin(x1) + rng.standard_normal(n)
        result = notears_basis(
            np.column_stack([x1, x2]),
            ["X1", "X2"],
            NoteArsBasisConfig(degree=2, l1_strength=0.1, threshold=0.3, seed=0),
        )
        assert result.solver == "basis"
        with pytest.raises(CounterfactualScenarioError):
            structural_model_from_weights(result)


class TestReachableFromTheEngine:
    def _input_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "bank_id": ["B1"] * 6 + ["B2"] * 6,
                "Value": [1.0, 2, 3, 4, 5, 6, 2.0, 3, 4, 5, 6, 7],
            }
        )

    def _engine(self, analyzer: BankRiskAnalyzer) -> RealPredictionEngine:
        engine = object.__new__(RealPredictionEngine)
        engine.bank_analyzer = analyzer
        engine.config = {"job_id": "counterfactual-reachability"}
        engine.model_path = "unused"
        return engine

    def test_the_analysis_carries_the_counterfactual(self, analyzer):
        analysis = analyzer.analyze_multiple_banks(
            {"B1": pd.DataFrame({"Value": [1.0, 2, 3, 4, 5, 6]}),
             "B2": pd.DataFrame({"Value": [2.0, 3, 4, 5, 6, 7]})},
            None,
            counterfactual_scenario=scenario(),
        )
        assert analysis.counterfactual is not None
        assert "counterfactual" in analysis.to_dict()
        assert analysis.to_dict()["counterfactual"]["is_forecast"] is False

    def test_the_engine_forwards_the_scenario(self, analyzer):
        result = RealPredictionEngine._predict_multi_bank(
            self._engine(analyzer),
            self._input_frame(),
            None,
            None,
            None,
            None,
            scenario(),
        )
        assert result.multi_bank_analysis.counterfactual is not None

    def test_the_report_renders_the_counterfactual(self, analyzer):
        result = RealPredictionEngine._predict_multi_bank(
            self._engine(analyzer), self._input_frame(), None, None, None, None, scenario()
        )
        report = result.explanation_report
        assert "Counterfactual (conditional on the caller-declared structural model" in report
        assert "NOT a forecast" in report
        assert "what follows from this intervention" in report

    def test_the_report_renders_the_intervention(self, analyzer):
        result = RealPredictionEngine._predict_multi_bank(
            self._engine(analyzer), self._input_frame(), None, None, None, None, scenario()
        )
        assert "do(F1 := 1.5)" in result.explanation_report

    def test_the_report_reports_unavailable_when_none_was_supplied(self, analyzer):
        result = RealPredictionEngine._predict_multi_bank(
            self._engine(analyzer), self._input_frame(), None, None, None, None, None
        )
        assert "Counterfactual: UNAVAILABLE" in result.explanation_report

    def test_a_wrong_scenario_type_raises_rather_than_being_ignored(self, analyzer):
        with pytest.raises(TypeError, match="CounterfactualScenario"):
            analyzer.analyze_multiple_banks(
                {"B1": pd.DataFrame({"Value": [1.0, 2, 3, 4, 5, 6]})},
                None,
                counterfactual_scenario=declared_model(),  # type: ignore[arg-type]
            )

    def test_the_counterfactual_is_independent_of_the_institution_set(self, analyzer):
        """Model variables are factors, not institutions, so coverage is not required."""
        analysis = analyzer.analyze_multiple_banks(
            {"B1": pd.DataFrame({"Value": [1.0, 2, 3, 4, 5, 6]})},
            None,
            counterfactual_scenario=scenario(),
        )
        assert analysis.counterfactual is not None
