"""The uncertainty decomposition is wired, and it refuses rather than guesses.

`modules/engine/uncertainty.py` shipped complete and tested but unreachable --
the disposition census carried it as ``wire`` with the note that an epistemic
spike should refuse the prediction. These tests pin the wiring:

* a single frozen checkpoint reports the split *not measurable* (an epistemic
  term from one model is identically zero by construction, and a reliability
  flag built on that zero would understate ignorance);
* with independently seeded members, a source whose final window makes the
  members disagree more than any calibration window did is REFUSED: score,
  prediction and interval withheld, reason recorded -- absence, not a number;
* a source the members agree on is assessed reliable and keeps its score;
* ``train_ensemble`` writes member checkpoints beside the canonical
  ``best_model.pt`` and the members are genuinely different models;
* the engine discovers members from disk at load time;
* the explainability card attaches the decomposition the job recorded.

The stub members here are deliberate: the decomposition contract is about
member *disagreement*, which stubs control exactly. Real trained members are
exercised by the train_ensemble test and the module's own suite.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

torch = pytest.importorskip("torch")

from backend.modules.engine.model_io import safe_torch_load, safe_torch_save  # noqa: E402
from backend.modules.engine.prediction_engine import RealPredictionEngine  # noqa: E402
from backend.modules.engine.trainer import ModelTrainer, train_ensemble  # noqa: E402

SEQUENCE_LENGTH = 5


class _Const(torch.nn.Module):
    """A member that always predicts a constant, whatever the window."""

    def __init__(self, value: float = 0.0):
        super().__init__()
        self.value = float(value)

    def forward(self, inputs, source_ids):  # noqa: ANN001 - harness duck type
        return torch.full((inputs.shape[0],), self.value)


class _LastValue(torch.nn.Module):
    """A member that predicts the window's last value: agreement on flat
    windows, maximal disagreement on a spike."""

    def forward(self, inputs, source_ids):  # noqa: ANN001 - harness duck type
        return inputs[:, -1]


def _engine(**overrides) -> RealPredictionEngine:
    """An engine shell carrying exactly the attributes the decomposition
    path reads, assembled without a checkpoint (the pattern the orchestrator
    scoring tests use)."""
    engine = RealPredictionEngine.__new__(RealPredictionEngine)
    engine.model_path = "stub://ensemble-wiring-test"
    engine.device = torch.device("cpu")
    engine.sequence_length = SEQUENCE_LENGTH
    engine.config = {}
    engine.source_stats = {}
    engine.sources = []
    engine.source_to_id = {}
    engine.model = _Const(0.0)
    engine.ensemble_members = []
    for name, value in overrides.items():
        setattr(engine, name, value)
    return engine


class TestSingleCheckpointIsHonest:
    def test_not_measurable_rather_than_a_fabricated_zero(self):
        engine = _engine()
        record = engine._uncertainty_for_source(
            np.zeros(SEQUENCE_LENGTH), np.zeros(60), {}, 0
        )
        assert record["status"] == "not_measurable_single_model"
        assert record["n_members"] == 1
        assert "ensemble_size" in record["reason"]
        # No variance fields are invented on the single-model path: the only
        # keys are the status, the member count and the reason.
        assert set(record) == {"status", "n_members", "reason"}

    def test_insufficient_history_is_reported_as_absence(self):
        engine = _engine(ensemble_members=[_LastValue()])
        record = engine._uncertainty_for_source(
            np.zeros(SEQUENCE_LENGTH), np.zeros(10), {}, 0
        )
        assert record["status"] == "insufficient_history_for_decomposition"
        assert record["n_members"] == 2


class TestEnsembleDecomposition:
    def _spiked(self):
        """Flat history, spike in the final window: calibration windows all
        flat (members agree), final window spiky (members diverge)."""
        values = np.zeros(60)
        values[-1] = 50.0
        sequence = np.zeros(SEQUENCE_LENGTH)
        sequence[-1] = 50.0
        return sequence, values

    def test_epistemic_spike_refuses_the_source(self):
        engine = _engine(model=_Const(0.0), ensemble_members=[_LastValue()])
        sequence, values = self._spiked()
        record = engine._uncertainty_for_source(sequence, values, {}, 0)

        assert record["status"] == "refused"
        assert record["reliable"] is False
        assert record["epistemic_spiked"] is True
        assert any("extrapolating" in reason for reason in record["reasons"])
        assert record["n_members"] == 2
        assert record["epistemic"] > record["epistemic_reference_threshold"]
        assert record["method"]  # the decomposition names its own method

    def test_agreeing_members_assess_reliable(self):
        engine = _engine(model=_Const(0.0), ensemble_members=[_Const(0.0)])
        values = np.tile([0.0, 1.0], 30)
        record = engine._uncertainty_for_source(values[-SEQUENCE_LENGTH:], values, {}, 0)

        assert record["status"] == "assessed"
        assert record["reliable"] is True
        assert record["epistemic"] == pytest.approx(0.0, abs=1e-12)
        # The world is noisy, so the aleatoric term carries the variance.
        assert record["aleatoric"] > 0.0

    def test_refusal_flows_through_predict_single(self):
        """The refused source's row carries absence end-to-end: NaN score,
        null interval, the refusal as the confidence method, and the summary
        counting it -- while the agreeing source keeps its number."""
        engine = _engine(
            model=_Const(0.0),
            ensemble_members=[_LastValue()],
            source_to_id={"SPIKY": 0, "FLAT": 1},
        )
        # Regime is tested elsewhere; stub it so this test stays on uncertainty.
        engine._regime_labels_batch = lambda items: {
            code: (None, "test_stub") for code, _values, _stats in items
        }

        dates = pd.date_range("2026-01-01", periods=65, freq="D")
        spiky = np.zeros(65)
        spiky[-1] = 50.0
        flat = np.tile([0.0, 1.0], 33)[:65]
        payload = pd.DataFrame({
            "source_code": ["SPIKY"] * 65 + ["FLAT"] * 65,
            "Date": list(dates) * 2,
            "Close": list(spiky) + list(flat),
        })

        result = engine._predict_single(payload)
        rows = result.predictions_df.set_index("source")

        refused = rows.loc["SPIKY"]
        assert refused["uncertainty_status"] == "refused"
        assert np.isnan(refused["risk_score"])
        assert np.isnan(refused["prediction"])
        assert refused["confidence_lower"] is None or pd.isna(refused["confidence_lower"])
        assert refused["confidence_method"] == "refused_uncertainty_assessment"
        assert "extrapolating" in str(refused["uncertainty_reasons"])

        assessed = rows.loc["FLAT"]
        assert assessed["uncertainty_status"] == "assessed"
        assert np.isfinite(assessed["risk_score"])

        summary = result.uncertainty_summary
        assert summary["mode"] == "deep_ensemble"
        assert summary["n_members"] == 2
        assert summary["refused_sources"] == ["SPIKY"]
        assert summary["statuses"] == {"refused": 1, "assessed": 1}

        assert "UNCERTAINTY DECOMPOSITION" in result.executive_summary
        assert "SPIKY" in result.executive_summary
        # The refused score is absent from the averages, not zero.
        assert float(result.predictions_df["risk_score"].mean()) == pytest.approx(
            float(assessed["risk_score"])
        )

    def test_single_model_summary_says_not_measurable(self):
        engine = _engine(source_to_id={"FLAT": 0})
        engine._regime_labels_batch = lambda items: {
            code: (None, "test_stub") for code, _values, _stats in items
        }
        dates = pd.date_range("2026-01-01", periods=65, freq="D")
        payload = pd.DataFrame({
            "source_code": ["FLAT"] * 65,
            "Date": dates,
            "Close": np.tile([0.0, 1.0], 33)[:65],
        })
        result = engine._predict_single(payload)
        assert result.uncertainty_summary["mode"] == "single_model"
        assert "not measurable" in result.executive_summary
        assert (
            result.predictions_df.loc[0, "uncertainty_status"]
            == "not_measurable_single_model"
        )


def _small_tan_checkpoint(path, seed: int) -> None:
    from backend.modules.engine.multi_scale_trainer import (
        MultiScaleTemporalAttentionModel,
    )

    torch.manual_seed(seed)
    model = MultiScaleTemporalAttentionModel(
        num_sources=1,
        sequence_length=SEQUENCE_LENGTH,
        d_model=8,
        nhead=2,
        num_layers=1,
        dropout=0.0,
    )
    safe_torch_save(
        {
            "model_state_dict": model.state_dict(),
            "config": {
                "sequence_length": SEQUENCE_LENGTH,
                "d_model": 8,
                "nhead": 2,
                "num_layers": 1,
                "dropout": 0.0,
            },
            "sources": [],
            "model_type": "temporal_attention",
        },
        path,
    )


class TestEnsembleTrainingAndDiscovery:
    def test_train_ensemble_writes_independent_members(self, tmp_path):
        rng = np.random.default_rng(3)
        n = 90
        df = pd.DataFrame({
            "Date": pd.date_range("2024-01-01", periods=n, freq="D"),
            "Value": rng.normal(0.0, 1.0, n).cumsum(),
            "Feature1": rng.normal(0.0, 1.0, n),
        })
        train_df, val_df, test_df = df.iloc[:60], df.iloc[60:75], df.iloc[75:]
        config = {
            "epochs": 1,
            "sequence_length": SEQUENCE_LENGTH,
            "batch_size": 8,
            "d_model": 8,
            "nhead": 2,
            "num_layers": 1,
            "dropout": 0.0,
            "ensemble_size": 2,
            "seed": 7,
        }

        metrics, member_paths = train_ensemble(
            train_df, val_df, test_df, str(tmp_path),
            model_type="temporal_attention", device=torch.device("cpu"), config=config,
        )

        assert metrics.model_path.endswith("best_model.pt")
        assert (tmp_path / "best_model.pt").exists()
        assert (tmp_path / "ensemble_member_1.pt").exists()
        assert len(member_paths) == 2

        primary = safe_torch_load(str(tmp_path / "best_model.pt"))
        member = safe_torch_load(str(tmp_path / "ensemble_member_1.pt"))
        key = next(iter(primary["model_state_dict"]))
        # Independent seeds must produce genuinely different members: an
        # epistemic term computed from identical weights is a fabricated zero.
        assert not torch.equal(
            primary["model_state_dict"][key], member["model_state_dict"][key]
        )

    def test_engine_discovers_members_beside_the_checkpoint(self, tmp_path):
        _small_tan_checkpoint(tmp_path / "best_model.pt", seed=1)
        _small_tan_checkpoint(tmp_path / "ensemble_member_1.pt", seed=2)

        engine = RealPredictionEngine(
            str(tmp_path / "best_model.pt"), torch.device("cpu"), {}
        )
        assert len(engine.ensemble_members) == 1

    def test_single_checkpoint_engine_has_no_members(self, tmp_path):
        _small_tan_checkpoint(tmp_path / "best_model.pt", seed=1)
        engine = RealPredictionEngine(
            str(tmp_path / "best_model.pt"), torch.device("cpu"), {}
        )
        assert engine.ensemble_members == []


class TestTransparencyCard:
    def test_card_attaches_the_decomposition_the_job_recorded(self):
        from backend.api.routes.explainability import _uncertainty_block

        decomposition = {
            "mode": "deep_ensemble",
            "n_members": 3,
            "statuses": {"assessed": 4, "refused": 1},
            "refused_sources": ["SRC_X"],
        }
        block = _uncertainty_block({
            "confidence_methods": {"split_conformal_alpha_0.1": 4,
                                    "refused_uncertainty_assessment": 1},
            "uncertainty_decomposition": decomposition,
        })
        assert block["status"] == "split_conformal_per_source"
        assert block["decomposition"] == decomposition

    def test_card_without_decomposition_is_unchanged(self):
        from backend.api.routes.explainability import _uncertainty_block

        block = _uncertainty_block({"confidence_methods": {"split_conformal_alpha_0.1": 2}})
        assert "decomposition" not in block
        assert _uncertainty_block({})["status"] == "not_recorded"


class TestPredictionReportAbsence:
    """The v2 predictions API must not fabricate a score for a refused row.

    `_extract_nodes` used to end its fallback chain in "any numeric column,
    scanned backwards" and to coerce a missing score to 0.0 -- on a refused
    row (NaN score, uncertainty columns present) that would have served
    epistemic variance as a risk score, or NaN to a JSON encoder configured
    to reject it. Absence travels as null, with the reason beside it.
    """

    def test_refused_row_yields_null_risk_and_carries_its_reason(self):
        import numpy as np
        import pandas as pd
        from backend.api.routes.predictions_v2 import _extract_nodes

        df = pd.DataFrame([
            {
                "source": "ASSESSED",
                "risk_score": 0.42,
                "prediction": 0.87,
                "confidence_lower": 0.7,
                "confidence_upper": 0.95,
                "confidence_method": "split_conformal_alpha_0.1",
                "uncertainty_status": "assessed",
                "aleatoric_var": 0.3,
                "epistemic_var": 0.04,
                "epistemic_share": 0.12,
            },
            {
                "source": "REFUSED",
                "risk_score": float("nan"),
                "prediction": float("nan"),
                "confidence_lower": None,
                "confidence_upper": None,
                "confidence_method": "refused_uncertainty_assessment",
                "uncertainty_status": "refused",
                "uncertainty_reasons": "the model is extrapolating",
                "aleatoric_var": 0.3,
                "epistemic_var": 4.2,
                "epistemic_share": 0.93,
            },
        ])
        nodes = {node.source: node for node in _extract_nodes(df)}

        assessed = nodes["ASSESSED"]
        assert assessed.risk == 0.42
        assert assessed.additional["uncertainty_status"] == "assessed"
        assert assessed.additional["epistemic_share"] == 0.12

        refused = nodes["REFUSED"]
        assert refused.risk is None  # not 0.0, not NaN, not epistemic_var
        assert refused.confidence_lower is None
        assert refused.additional["uncertainty_status"] == "refused"
        assert refused.additional["uncertainty_reasons"] == "the model is extrapolating"
        assert refused.additional["confidence_method"] == "refused_uncertainty_assessment"

    def test_nodes_serialise_without_nan(self):
        """Starlette's JSON encoder rejects NaN; a refused row must not 500."""
        import json
        import numpy as np
        import pandas as pd
        from backend.api.routes.predictions_v2 import _extract_nodes

        df = pd.DataFrame([{
            "source": "REFUSED",
            "risk_score": float("nan"),
            "prediction": float("nan"),
            "uncertainty_status": "refused",
        }])
        payload = [node.model_dump() for node in _extract_nodes(df)]
        json.dumps(payload, allow_nan=False)  # raises on any NaN/Infinity
