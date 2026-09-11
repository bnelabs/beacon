"""The neural SDE drives a reachable latent-stress dispersion capability.

``backend/modules/engine/neural_sde.py`` implemented and tested a complete
Stochastic Differential Equation for the continuous-time graph memory, and
nothing in production imported it. A capability that is correct in isolation but
is never fed by the engine is a capability the system does not have, and the
documentation that described it as shipped overstated the system.

``backend/modules/engine/latent_dynamics.py`` is the production face: it samples
a caller-declared SDE over per-institution initial latent states through
``NeuralSDEMemory`` and reports the terminal dispersion. What these tests
establish, in order:

* the declared process reproduces its closed-form law and collapses exactly onto
  the deterministic ODE the SDE replaces when the diffusion is zero -- so the
  stochastic path is anchored to something checkable rather than merely running;
* a fixed seed makes the run reproducible, which is a hard requirement for risk
  monitoring;
* the central claim -- wider diffusion, wider terminal dispersion -- holds
  quantitatively, not just directionally;
* every way of supplying an impossible scenario raises instead of producing a
  dispersion from nothing;
* the capability is reachable through ``analyze_multiple_banks`` and through
  ``RealPredictionEngine._predict_multi_bank``, and the report renders both a
  present and an absent section;
* the dispersion is **not** written into ``confidence_lower`` /
  ``confidence_upper`` / ``confidence_intervals``. That is the defect this repo
  already refuses once: MC-dropout intervals described a different network from
  the one that scored the payload, so the calibrated-interval fields stay ``None``
  and the SDE dispersion is labelled as a scenario dispersion instead.
"""

from __future__ import annotations

import json
import math
from dataclasses import FrozenInstanceError

import pandas as pd
import pytest
import torch

from backend.modules.engine.latent_dynamics import (
    CALIBRATION_NOTE,
    DISPERSION_LABEL,
    LatentDynamicsScenario,
    simulate_latent_stress,
)
from backend.modules.engine.neural_sde import ConstantDiffusion
from backend.modules.engine.prediction_engine import RealPredictionEngine
from backend.modules.risk.bank_analyzer import BankRiskAnalyzer


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


EXPOSURES = {("B1", "B2"): 100.0}
ENDOWMENTS = {"B1": 50.0, "B2": 50.0}

DRIFT_RATE = 0.5
HORIZON = 1.0
DT = 0.02


def scenario(**overrides) -> LatentDynamicsScenario:
    """A declared SDE over two institutions, two latent coordinates each."""
    values = {
        "initial_states": {"B1": (0.5, 0.25), "B2": (-0.25, 0.5)},
        "horizon": HORIZON,
        "dt": DT,
        "n_paths": 256,
        "seed": 11,
        "drift_rate": DRIFT_RATE,
        "diffusion_scale": 0.2,
    }
    values.update(overrides)
    return LatentDynamicsScenario(**values)


def ou_terminal_std(sigma: float, rate: float, horizon: float) -> float:
    """Closed-form terminal standard deviation of ``dz = -rate*z dt + sigma dW``.

    ``Var(z_T) = sigma^2 (1 - exp(-2 rate T)) / (2 rate)`` for the
    Ornstein-Uhlenbeck process started from a known state. This is the reference
    the simulated dispersion is checked against, and it is written from the SDE
    rather than read out of the implementation.
    """
    return sigma * math.sqrt((1.0 - math.exp(-2.0 * rate * horizon)) / (2.0 * rate))


class TestDeterminism:
    def test_a_fixed_seed_reproduces_the_run_exactly(self):
        first = simulate_latent_stress(scenario(seed=2024))
        second = simulate_latent_stress(scenario(seed=2024))
        assert first.to_dict() == second.to_dict()

    def test_a_different_seed_changes_the_drawn_paths(self):
        first = simulate_latent_stress(scenario(seed=1))
        second = simulate_latent_stress(scenario(seed=2))
        # The terminal *mean* is a random variable too, and with non-zero
        # diffusion two seeds must not agree on it.
        assert first.terminal_mean != second.terminal_mean

    def test_the_seed_is_reported(self):
        result = simulate_latent_stress(scenario(seed=99))
        assert result.seed == 99
        assert result.to_dict()["seed"] == 99

    def test_the_payload_is_json_serialisable(self):
        payload = simulate_latent_stress(scenario()).to_dict()
        json.dumps(payload, allow_nan=False)


class TestZeroDiffusionReducesToTheOde:
    """``diffusion_scale = 0`` collapses the SDE onto the drift ODE exactly.

    The drift of the declared process is the temporal graph's ``-rate * z`` form,
    so the deterministic drift-only terminal reported alongside the dispersion is
    the ODE the SDE replaces. With ``g == 0`` the noise is multiplied by exactly
    zero, so this is an identity, not a small-noise approximation.
    """

    def test_every_sampled_path_is_identical(self):
        result = simulate_latent_stress(scenario(diffusion_scale=0.0, n_paths=64))
        for values in result.terminal_std.values():
            assert values == tuple(0.0 for _ in values)
        assert all(value == 0.0 for value in result.terminal_dispersion.values())

    def test_the_terminal_mean_is_the_deterministic_drift_only_path(self):
        result = simulate_latent_stress(scenario(diffusion_scale=0.0, n_paths=8))
        for name in result.institution_ids:
            for simulated, deterministic in zip(
                result.terminal_mean[name], result.drift_only_terminal[name]
            ):
                # Forward Euler against the RK4 reference: the gap is the
                # first-order truncation error at dt = 0.02, about 1e-3 relative.
                assert simulated == pytest.approx(deterministic, rel=5e-3)

    def test_it_matches_the_closed_form_solution(self):
        result = simulate_latent_stress(scenario(diffusion_scale=0.0, n_paths=8))
        initial = dict(scenario().initial_states)
        for name in result.institution_ids:
            for z0, simulated in zip(initial[name], result.terminal_mean[name]):
                assert simulated == pytest.approx(
                    z0 * math.exp(-DRIFT_RATE * HORIZON), rel=5e-3
                )

    def test_the_paths_do_not_depend_on_the_seed(self):
        """``g == 0`` must remove the randomness, not merely shrink it."""
        first = simulate_latent_stress(scenario(diffusion_scale=0.0, seed=1))
        second = simulate_latent_stress(scenario(diffusion_scale=0.0, seed=2))
        assert first.terminal_mean == second.terminal_mean


class TestDiffusionWidensDispersion:
    """The central claim: more diffusion means more terminal dispersion."""

    def test_a_wider_diffusion_widens_the_terminal_dispersion(self):
        narrow = simulate_latent_stress(scenario(diffusion_scale=0.2))
        wide = simulate_latent_stress(scenario(diffusion_scale=0.4))
        for name in narrow.institution_ids:
            assert (
                wide.terminal_dispersion[name] > narrow.terminal_dispersion[name]
            ), name

    def test_the_widening_is_the_declared_ratio(self):
        """Same seed means the same Wiener draws, so the ratio is near-exact."""
        narrow = simulate_latent_stress(scenario(diffusion_scale=0.1))
        wide = simulate_latent_stress(scenario(diffusion_scale=0.3))
        for name in narrow.institution_ids:
            assert narrow.terminal_std[name][0] > 0.0
            ratio = wide.terminal_std[name][0] / narrow.terminal_std[name][0]
            assert ratio == pytest.approx(3.0, rel=0.05)

    def test_the_dispersion_matches_the_closed_form_law(self):
        result = simulate_latent_stress(scenario(diffusion_scale=0.2, n_paths=4096))
        expected = ou_terminal_std(0.2, DRIFT_RATE, HORIZON)
        for name in result.institution_ids:
            for value in result.terminal_std[name]:
                assert value == pytest.approx(expected, rel=0.05)

    def test_the_zero_diffusion_dispersion_is_strictly_smaller(self):
        zero = simulate_latent_stress(scenario(diffusion_scale=0.0))
        positive = simulate_latent_stress(scenario(diffusion_scale=0.2))
        for name in zero.institution_ids:
            assert positive.terminal_dispersion[name] > zero.terminal_dispersion[name]


class TestFailClosed:
    @pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
    def test_a_non_positive_or_non_finite_horizon_raises(self, bad):
        with pytest.raises(ValueError):
            scenario(horizon=bad)

    @pytest.mark.parametrize("bad", [0.0, -0.5, float("nan"), float("inf")])
    def test_a_non_positive_or_non_finite_dt_raises(self, bad):
        with pytest.raises(ValueError):
            scenario(dt=bad)

    @pytest.mark.parametrize("bad", [0, -4])
    def test_a_non_positive_path_count_raises(self, bad):
        with pytest.raises(ValueError, match="n_paths"):
            scenario(n_paths=bad)

    def test_a_non_integer_path_count_raises(self):
        with pytest.raises(ValueError, match="integer"):
            scenario(n_paths=2.5)

    def test_a_non_integer_seed_raises(self):
        with pytest.raises(ValueError, match="seed"):
            scenario(seed=1.5)

    def test_a_horizon_that_is_not_a_whole_number_of_steps_raises(self):
        """The declared dt cannot be honoured otherwise, so it is refused."""
        with pytest.raises(ValueError, match="whole number"):
            scenario(horizon=1.0, dt=0.3)

    def test_a_mismatched_initial_state_width_raises(self):
        """``NeuralSDEMemory`` has one width; two widths cannot both be honoured."""
        with pytest.raises(ValueError, match="width"):
            scenario(initial_states={"B1": (0.1, 0.2), "B2": (0.3,)})

    def test_an_empty_state_raises(self):
        with pytest.raises(ValueError, match="at least one element"):
            scenario(initial_states={"B1": (), "B2": (0.1,)})

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
    def test_a_non_finite_initial_state_raises(self, bad):
        with pytest.raises(ValueError, match="finite"):
            scenario(initial_states={"B1": (0.1, bad), "B2": (0.2, 0.3)})

    def test_no_institutions_raises(self):
        with pytest.raises(ValueError, match="at least one institution"):
            scenario(initial_states={})

    @pytest.mark.parametrize("bad", [0.0, -0.5, float("nan"), float("inf")])
    def test_a_non_positive_or_non_finite_drift_rate_raises(self, bad):
        with pytest.raises(ValueError):
            scenario(drift_rate=bad)

    @pytest.mark.parametrize("bad", [-0.1, float("nan"), float("inf")])
    def test_a_negative_or_non_finite_diffusion_scale_raises(self, bad):
        with pytest.raises(ValueError):
            scenario(diffusion_scale=bad)

    def test_declaring_no_drift_raises(self):
        with pytest.raises(ValueError, match="drift"):
            scenario(drift_rate=None)

    def test_declaring_two_drifts_raises(self):
        with pytest.raises(ValueError, match="drift"):
            scenario(drift_rate=0.5, drift=lambda state, time: -state)

    def test_declaring_two_diffusions_raises(self):
        with pytest.raises(ValueError, match="diffusion"):
            scenario(diffusion_scale=0.2, diffusion=lambda state, time: state * 0.0)

    def test_the_deterministic_integrator_is_refused(self):
        with pytest.raises(ValueError, match="integrator"):
            scenario(integrator="deterministic")

    def test_an_unknown_integrator_is_refused(self):
        with pytest.raises(ValueError, match="integrator"):
            scenario(integrator="trapezoid")

    def test_a_non_scenario_is_refused(self):
        with pytest.raises(TypeError, match="LatentDynamicsScenario"):
            simulate_latent_stress({"initial_states": {}})

    def test_a_frozen_scenario_cannot_be_mutated_after_validation(self):
        """A scenario that changed after validation would be simulated unvalidated."""
        declared = scenario()
        with pytest.raises(FrozenInstanceError):
            declared.horizon = -1.0  # type: ignore[misc]

    def test_a_caller_supplied_diffusion_module_is_honoured(self):
        """A caller with a trained diffusion can replace the declared constant.

        The supplied module is numerically identical to the declared constant
        here, so the two runs must agree bit-for-bit -- the branch is tested
        against a known-equal reference rather than merely asserting it runs.
        """
        supplied = simulate_latent_stress(
            scenario(diffusion_scale=None, diffusion=ConstantDiffusion(0.2))
        )
        declared = simulate_latent_stress(scenario())
        assert supplied.terminal_mean == declared.terminal_mean
        assert "caller_supplied_module" in supplied.diffusion_description

    def test_a_caller_supplied_drift_module_is_honoured(self):
        """A trained field can replace the declared linear drift."""
        supplied = simulate_latent_stress(
            scenario(drift_rate=None, drift=lambda state, time: -DRIFT_RATE * state)
        )
        declared = simulate_latent_stress(scenario())
        assert supplied.terminal_mean == declared.terminal_mean
        assert "caller_supplied_module" in supplied.drift_description
        assert "declared_linear_mean_reversion" not in supplied.drift_description


class TestCouplingThroughAnalysis:
    def test_a_supplied_scenario_produces_the_dispersion(self, analyzer, bank_data):
        analysis = analyzer.analyze_multiple_banks(
            bank_data,
            latent_dynamics_scenario=scenario(),
        )
        assert analysis.latent_dynamics is not None
        assert set(analysis.latent_dynamics.terminal_dispersion) == {"B1", "B2"}
        assert analysis.latent_dynamics.label == DISPERSION_LABEL
        assert analysis.latent_dynamics.calibrated is False

    def test_the_result_serialises_with_its_label(self, analyzer, bank_data):
        analysis = analyzer.analyze_multiple_banks(
            bank_data, latent_dynamics_scenario=scenario()
        )
        payload = analysis.to_dict()["latent_dynamics"]
        assert payload["label"] == DISPERSION_LABEL
        assert payload["calibrated"] is False
        assert payload["not_a_prediction_interval"] is True
        assert payload["calibration_note"] == CALIBRATION_NOTE

    def test_the_scenario_needs_no_balance_sheet(self, analyzer, bank_data):
        """The SDE propagates latent uncertainty; it does not need a network."""
        analysis = analyzer.analyze_multiple_banks(
            bank_data, None, latent_dynamics_scenario=scenario()
        )
        assert analysis.clearing is None
        assert analysis.latent_dynamics is not None

    def test_absent_scenario_leaves_the_field_none(self, analyzer, bank_data):
        analysis = analyzer.analyze_multiple_banks(bank_data)
        assert analysis.latent_dynamics is None
        assert analysis.to_dict()["latent_dynamics"] is None

    def test_an_unknown_institution_raises(self, analyzer, bank_data):
        with pytest.raises(KeyError, match="outside the analysis"):
            analyzer.analyze_multiple_banks(
                bank_data,
                latent_dynamics_scenario=scenario(
                    initial_states={"B1": (0.1, 0.2), "GHOST": (0.3, 0.4)}
                ),
            )

    def test_a_partial_scenario_raises_rather_than_omitting_an_institution(
        self, analyzer, bank_data
    ):
        with pytest.raises(ValueError, match="must cover every analysed institution"):
            analyzer.analyze_multiple_banks(
                bank_data,
                latent_dynamics_scenario=scenario(initial_states={"B1": (0.1, 0.2)}),
            )

    def test_a_wrongly_typed_scenario_raises(self, analyzer, bank_data):
        with pytest.raises(TypeError, match="LatentDynamicsScenario"):
            analyzer.analyze_multiple_banks(
                bank_data, latent_dynamics_scenario={"B1": [0.1, 0.2]}
            )


class TestReachabilityFromTheEngine:
    """The capability must be reachable from the engine, not only the analyzer."""

    def _input_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "bank_id": ["B1"] * 6 + ["B2"] * 6,
                "Value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
            }
        )

    def _engine(self, analyzer: BankRiskAnalyzer) -> RealPredictionEngine:
        engine = object.__new__(RealPredictionEngine)
        engine.bank_analyzer = analyzer
        engine.config = {"job_id": "latent-reachability"}
        engine.model_path = "unused"
        return engine

    def test_predict_forwards_the_scenario(self, analyzer):
        engine = self._engine(analyzer)
        result = RealPredictionEngine._predict_multi_bank(
            engine, self._input_frame(), None, None, None, scenario()
        )
        assert result.multi_bank_analysis is not None
        assert result.multi_bank_analysis.latent_dynamics is not None
        assert set(
            result.multi_bank_analysis.latent_dynamics.terminal_dispersion
        ) == {"B1", "B2"}

    def test_the_report_renders_the_section(self, analyzer):
        engine = self._engine(analyzer)
        result = RealPredictionEngine._predict_multi_bank(
            engine, self._input_frame(), None, None, None, scenario()
        )
        report = result.explanation_report
        assert "Latent stress dispersion (simulated scenario" in report
        assert "NOT a calibrated prediction interval" in report
        assert "Latent stress dispersion: UNAVAILABLE" not in report
        assert "B1: terminal dispersion" in report

    def test_the_report_says_unavailable_when_no_scenario_was_requested(self, analyzer):
        engine = self._engine(analyzer)
        result = RealPredictionEngine._predict_multi_bank(
            engine, self._input_frame(), None, None, None, None
        )
        report = result.explanation_report
        assert "Latent stress dispersion: UNAVAILABLE -" in report
        assert "NOT a calibrated prediction interval" not in report


class TestTheDispersionIsNotACalibratedInterval:
    """The SDE must not be smuggled into the fields that mean coverage."""

    def _input_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "bank_id": ["B1"] * 6 + ["B2"] * 6,
                "Value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
            }
        )

    def _engine(self, analyzer: BankRiskAnalyzer) -> RealPredictionEngine:
        engine = object.__new__(RealPredictionEngine)
        engine.bank_analyzer = analyzer
        engine.config = {"job_id": "latent-interval"}
        engine.model_path = "unused"
        return engine

    def test_the_engine_confidence_intervals_stay_unset(self, analyzer):
        result = RealPredictionEngine._predict_multi_bank(
            self._engine(analyzer),
            self._input_frame(),
            None,
            None,
            None,
            scenario(diffusion_scale=0.4),
        )
        # The dispersion is non-zero, so the None values below are a deliberate
        # refusal and not the trivial consequence of a degenerate run.
        assert result.multi_bank_analysis.latent_dynamics.max_dispersion > 0.0
        assert result.confidence_intervals == {"B1": (None, None), "B2": (None, None)}

    def test_the_per_bank_confidence_bounds_stay_unset(self, analyzer):
        result = RealPredictionEngine._predict_multi_bank(
            self._engine(analyzer),
            self._input_frame(),
            None,
            None,
            None,
            scenario(diffusion_scale=0.4),
        )
        for profile in result.multi_bank_analysis.bank_profiles.values():
            assert profile.confidence_lower is None
            assert profile.confidence_upper is None
            assert "pending-conformal-calibration" in profile.confidence_method

    def test_the_result_carries_no_confidence_field(self, analyzer):
        analysis = analyzer.analyze_multiple_banks(
            {"B1": pd.DataFrame({"Value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]})},
            latent_dynamics_scenario=scenario(initial_states={"B1": (0.1, 0.2)}),
        )
        payload = analysis.latent_dynamics.to_dict()
        assert "confidence_lower" not in payload
        assert "confidence_upper" not in payload
        assert "confidence_intervals" not in payload
        assert payload["calibrated"] is False
        assert "NOT a calibrated prediction interval" in payload["calibration_note"]
