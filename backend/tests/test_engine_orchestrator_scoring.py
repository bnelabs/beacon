"""Composition tests for the pipeline route's scoring path.

``EngineOrchestrator`` is what ``POST /api/v1/pipeline`` runs between the DATA
and RESULTS stages, and before this round nothing composed it in a test. The
defects these tests pin down (fourth-round quant review, findings F4, F9;

* with no trained checkpoint, the orchestrator scored the payload through a
  randomly initialized LSTM and called the output a risk score -- now it fails
  closed unless an explicit test-only override is set;
* ``_predict`` treated the source-major concatenation as one series (windows
  straddled source seams), fed RAW-scale values to a model trained on
  standardized windows, and passed ``source_id=0`` for every window;
* ``_compute_risk_scores`` thresholded the raw model mean at 30/60/80 as if a
  standardized regression output were a percentage;
* ``_evaluate`` reported a fabricated ``stability_score`` and, in its
  ground-truth branch, paired every prediction with the wrong row.

Synthetic values are appropriate here: these tests verify the machinery's
honesty, never a risk claim.
"""

from __future__ import annotations

import os

os.environ.setdefault("USE_SQLITE", "true")

import numpy as np
import pandas as pd
import pytest

torch = pytest.importorskip("torch")

from backend.exceptions import PredictionBlockedError  # noqa: E402
from backend.modules.engine.model_io import safe_torch_save  # noqa: E402
from backend.modules.engine.multi_scale_trainer import (  # noqa: E402
    MultiScaleTemporalAttentionModel,
)
from backend.modules.engine import orchestrator as orchestrator_module  # noqa: E402
from backend.modules.engine.orchestrator import EngineOrchestrator  # noqa: E402

SEQUENCE_LENGTH = 4
SOURCES = ("SRC_BIG", "SRC_TINY")
SOURCE_STATS = {
    "SRC_BIG": {"mean": 38000.0, "std": 500.0},
    "SRC_TINY": {"mean": 0.02, "std": 0.005},
}


def _payload(rows: int = 12) -> pd.DataFrame:
    """A source-major frame with wildly different scales per source."""
    dates = pd.date_range("2024-01-01", periods=rows, freq="D")
    big = 38000.0 + np.arange(rows, dtype=float)
    tiny = 0.02 + 0.001 * np.arange(rows, dtype=float)
    return pd.concat(
        [
            pd.DataFrame({"Date": dates, "date": dates, "Value": big,
                          "value": big, "source_code": "SRC_BIG"}),
            pd.DataFrame({"Date": dates, "date": dates, "Value": tiny,
                          "value": tiny, "source_code": "SRC_TINY"}),
        ],
        ignore_index=True,
    )


def _write_checkpoint(output_dir, job_id: str, seed: int = 3) -> str:
    torch.manual_seed(seed)
    model = MultiScaleTemporalAttentionModel(
        num_sources=len(SOURCES),
        sequence_length=SEQUENCE_LENGTH,
        d_model=8,
        nhead=2,
        num_layers=1,
        dropout=0.0,
    )
    path = os.path.join(output_dir, job_id, "best_model.pt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    safe_torch_save(
        {
            "model_state_dict": model.state_dict(),
            "config": {
                "model": "temporal_attention",
                "sequence_length": SEQUENCE_LENGTH,
                "d_model": 8, "nhead": 2, "num_layers": 1, "dropout": 0.0,
            },
            "sources": list(SOURCES),
            "source_stats": SOURCE_STATS,
        },
        path,
    )
    return path


class _CapturingModel(torch.nn.Module):
    """Records every (inputs, source_ids) pair the orchestrator feeds it."""

    def __init__(self, inner: torch.nn.Module) -> None:
        super().__init__()
        self.inner = inner
        self.inputs: list = []
        self.source_ids: list = []

    def forward(self, x, source_ids):
        self.inputs.append(x.detach().cpu().numpy().copy())
        self.source_ids.append(source_ids.detach().cpu().numpy().copy())
        return self.inner(x, source_ids)


@pytest.fixture()
def orchestrator(tmp_path):
    job_id = "job-scoring"
    orch = EngineOrchestrator(job_id, str(tmp_path), config={"batch_size": 5})
    _write_checkpoint(str(tmp_path), job_id)
    orch._get_model()  # loads checkpoint state: sources, stats, sequence_length
    return orch


class TestFailClosedWithoutCheckpoint:
    def test_missing_checkpoint_blocks_prediction(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BEACON_ALLOW_UNTRAINED_FALLBACK", raising=False)
        orch = EngineOrchestrator("job-no-model", str(tmp_path), config={})
        with pytest.raises(PredictionBlockedError, match="randomly initialized"):
            orch._get_model()

    def test_explicit_override_permits_the_untrained_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BEACON_ALLOW_UNTRAINED_FALLBACK", "1")
        orch = EngineOrchestrator("job-no-model", str(tmp_path), config={})
        model = orch._get_model()
        assert isinstance(model, orchestrator_module.SimpleRiskPredictor)
        assert orch.model_name == "SimpleRiskPredictor"

    def test_override_defaults_to_closed(self, monkeypatch):
        monkeypatch.delenv("BEACON_ALLOW_UNTRAINED_FALLBACK", raising=False)
        assert orchestrator_module._untrained_fallback_allowed() is False


class TestPredictNormalizesPerSource:
    def test_windows_are_standardized_with_checkpoint_stats(self, orchestrator):
        model = _CapturingModel(orchestrator._get_model())
        predictions = orchestrator._predict(model, {"timeseries": _payload()})

        captured = np.concatenate(model.inputs, axis=0)
        # Raw values are ~38000 and ~0.02; standardized windows are O(1).
        assert np.all(np.abs(captured) < 10.0)

        # Hand-check the first window of SRC_BIG against its checkpoint stats.
        rows = 12
        big = 38000.0 + np.arange(rows, dtype=float)
        expected_first = (big[:SEQUENCE_LENGTH] - 38000.0) / 500.0
        assert captured[0] == pytest.approx(expected_first, rel=1e-5, abs=1e-7)

    def test_every_window_carries_its_own_source_id(self, orchestrator):
        model = _CapturingModel(orchestrator._get_model())
        predictions = orchestrator._predict(model, {"timeseries": _payload()})
        ids = np.concatenate(model.source_ids, axis=0).ravel()
        windows_per_source = 12 - SEQUENCE_LENGTH + 1
        expected = np.concatenate([
            np.full(windows_per_source, orchestrator.source_to_id["SRC_BIG"]),
            np.full(windows_per_source, orchestrator.source_to_id["SRC_TINY"]),
        ])
        assert ids.tolist() == expected.tolist()
        assert set(ids.tolist()) == {0, 1}

    def test_no_window_straddles_a_source_seam(self, orchestrator):
        predictions = orchestrator._predict(
            orchestrator._get_model(), {"timeseries": _payload()}
        )
        rows = 12
        expected_total = 2 * (rows - SEQUENCE_LENGTH + 1)
        assert predictions["scores"].size == expected_total
        sources = np.asarray(predictions["sources"])
        # Source-major blocks, each exactly one source's window count.
        assert (sources[: expected_total // 2] == "SRC_BIG").all()
        assert (sources[expected_total // 2:] == "SRC_TINY").all()
        assert predictions["stats_provenance"] == {
            source: "checkpoint" for source in SOURCES
        }

    def test_sources_without_checkpoint_stats_are_flagged_as_optimistic(
        self, orchestrator, caplog
    ):
        frame = _payload()
        extra_dates = pd.date_range("2024-01-01", periods=12, freq="D")
        extra = pd.DataFrame({
            "Date": extra_dates, "date": extra_dates,
            "Value": np.arange(12, dtype=float) + 5.0,
            "value": np.arange(12, dtype=float) + 5.0,
            "source_code": "SRC_UNSEEN",
        })
        predictions = orchestrator._predict(
            orchestrator._get_model(),
            {"timeseries": pd.concat([frame, extra], ignore_index=True)},
        )
        assert predictions["stats_provenance"]["SRC_UNSEEN"] == "payload"
        assert predictions["scores"].size == 3 * (12 - SEQUENCE_LENGTH + 1)

    def test_insufficient_history_yields_no_scores(self, orchestrator):
        tiny = _payload(rows=SEQUENCE_LENGTH)  # no source can fill a window+1
        predictions = orchestrator._predict(
            orchestrator._get_model(), {"timeseries": tiny}
        )
        assert predictions["insufficient_history"] is True
        assert np.asarray(predictions["scores"]).size == 0


class TestRiskScoreSemantics:
    def test_risk_level_is_uncalibrated_not_a_invented_band(self, orchestrator):
        predictions = {"scores": np.array([0.1, -0.2, 0.3])}
        data = {"metadata": {"quality_score": 90.0}}
        result = orchestrator._compute_risk_scores(predictions, data)
        assert result.risk_level == "uncalibrated"
        assert result.overall_score == pytest.approx(np.mean([0.1, -0.2, 0.3]))
        assert result.score_semantics["calibrated"] is False
        assert "standardized" in result.score_semantics["units"]
        # Operational risk stays a real measurement from the DATA stage.
        assert result.operational_risk["data_quality_score"] == 90.0
        assert result.operational_risk["process_risk"] == pytest.approx(10.0)

    def test_scores_are_never_thresholded_as_percentages(self, orchestrator):
        # A standardized mean far above the old 80 "critical" cut-off must not
        # produce a level: the units do not support one.
        predictions = {"scores": np.array([120.0, 130.0])}
        data = {"metadata": {"quality_score": 50.0}}
        result = orchestrator._compute_risk_scores(predictions, data)
        assert result.risk_level == "uncalibrated"

    def test_missing_quality_score_blocks(self, orchestrator):
        with pytest.raises(PredictionBlockedError, match="quality score"):
            orchestrator._compute_risk_scores(
                {"scores": np.array([0.1])}, {"metadata": {}}
            )

    def test_empty_scores_block(self, orchestrator):
        with pytest.raises(PredictionBlockedError, match="no scores"):
            orchestrator._compute_risk_scores(
                {"scores": np.array([])}, {"metadata": {"quality_score": 90.0}}
            )


class TestEvaluateIsHonest:
    def test_no_fabricated_stability_metric(self, orchestrator):
        metrics = orchestrator._evaluate(
            {"scores": np.array([0.1, 0.2]), "sources": np.array(["A", "A"]),
             "score_end_positions": np.array([4, 5])},
            {"timeseries": pd.DataFrame({"Value": [1.0] * 10})},
        )
        assert "stability_score" not in metrics
        assert metrics["note"].startswith("No ground truth")

    def test_ground_truth_alignment_is_shifted_one_row_within_source(self, orchestrator):
        rows = 10
        dates = pd.date_range("2024-01-01", periods=rows, freq="D")
        # target at row r is 100 + r; a perfectly aligned predictor of the row
        # AFTER its window end scores exactly that target.
        df = pd.DataFrame({
            "Date": dates, "date": dates, "source_code": "SRC_A",
            "Value": np.zeros(rows), "value": np.zeros(rows),
            "target": 100.0 + np.arange(rows, dtype=float),
        })
        ends = np.arange(SEQUENCE_LENGTH - 1, rows)
        perfect_scores = 100.0 + ends + 1  # prediction for row end+1
        predictions = {
            "scores": perfect_scores,
            "sources": np.array(["SRC_A"] * ends.size, dtype=object),
            "score_end_positions": ends,
        }
        metrics = orchestrator._evaluate(predictions, {"timeseries": df})
        assert metrics["mse"] == pytest.approx(0.0, abs=1e-9)
        # The last window's predicted row is beyond the source's span.
        assert metrics["n_aligned"] == ends.size - 1

        # The OLD alignment (score vs target at the window-END row) would give
        # a nonzero error on this predictor -- assert the shift matters.
        off_by_one = 100.0 + ends
        misaligned = orchestrator._evaluate(
            {**predictions, "scores": off_by_one}, {"timeseries": df}
        )
        assert misaligned["mse"] > 0.0
