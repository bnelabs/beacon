"""Calibrated intervals and live regime labels on the prediction path.

The fifth round wired two census items into ``RealPredictionEngine.predict``:
split-conformal intervals from held-out rolling residuals of each source, and
a Student-t HMM regime nowcast. These tests pin the contract: intervals exist
when the payload can support calibration and bracket the point score; they are
absent -- with a reason, never zero-width -- when it cannot; the regime is a
named state or absent, never guessed.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

torch = pytest.importorskip("torch")

from backend.modules.data.quality_gate import QualityAttestation  # noqa: E402
from backend.modules.engine.model_io import safe_torch_save  # noqa: E402
from backend.modules.engine.multi_scale_trainer import (  # noqa: E402
    MultiScaleTemporalAttentionModel,
)
from backend.modules.engine.prediction_engine import RealPredictionEngine  # noqa: E402

SEQUENCE_LENGTH = 4
SOURCES = ("SRC_A", "SRC_B")


def _attestation() -> QualityAttestation:
    return QualityAttestation(job_id="job-unc", verified=True, checked_at="2024-01-01T00:00:00+00:00")


def _checkpoint(path: Path, rows: int) -> Path:
    torch.manual_seed(11)
    model = MultiScaleTemporalAttentionModel(
        num_sources=len(SOURCES),
        sequence_length=SEQUENCE_LENGTH,
        d_model=8,
        nhead=2,
        num_layers=1,
        dropout=0.0,
    )
    safe_torch_save(
        {
            "model_state_dict": model.state_dict(),
            "config": {"sequence_length": SEQUENCE_LENGTH, "d_model": 8, "nhead": 2,
                       "num_layers": 1, "dropout": 0.0},
            "sources": list(SOURCES),
            "source_stats": {s: {"mean": 50.0 + 5 * i, "std": 2.0} for i, s in enumerate(SOURCES)},
        },
        path,
    )
    return path


def _frame(rows: int, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    records = []
    for index, source in enumerate(SOURCES):
        dates = pd.date_range("2023-01-01", periods=rows, freq="D")
        base = 50.0 + 5 * index
        # regime-ish series: calm half, volatile half, so the HMM has structure
        values = base + rng.normal(0, 0.4, rows).cumsum() * 0.2
        values[rows // 2:] += rng.normal(0, 2.5, rows - rows // 2)
        records.append(pd.DataFrame({"source_code": source, "Date": dates, "Value": values}))
    return pd.concat(records, ignore_index=True)


@pytest.fixture()
def engine(tmp_path: Path) -> RealPredictionEngine:
    return RealPredictionEngine(
        model_path=str(_checkpoint(tmp_path / "best_model.pt", 200)),
        device=torch.device("cpu"),
        config={},
        quality_attestation=_attestation(),
    )


class TestConformalIntervals:
    def test_intervals_exist_and_bracket_the_point_score(self, engine):
        result = engine.predict(_frame(200), attestation=_attestation())
        for _, row in result.predictions_df.iterrows():
            assert row["confidence_method"].startswith("split_conformal")
            # intervals are denormalized: they bracket the predicted VALUE
            assert row["confidence_lower"] <= row["prediction"] <= row["confidence_upper"]
            assert row["confidence_upper"] > row["confidence_lower"]
            lower, upper = result.confidence_intervals[row["source"]]
            assert lower == pytest.approx(row["confidence_lower"])
            assert upper == pytest.approx(row["confidence_upper"])

    def test_short_payload_reports_absence_not_a_fake_interval(self, engine):
        result = engine.predict(_frame(20), attestation=_attestation())
        for _, row in result.predictions_df.iterrows():
            assert row["confidence_lower"] is None
            assert row["confidence_upper"] is None
            assert row["confidence_method"] == "insufficient_history_for_calibration"


class TestRegimeLabel:
    def test_regime_is_a_named_state_on_long_payloads(self, engine):
        result = engine.predict(_frame(200), attestation=_attestation())
        for _, row in result.predictions_df.iterrows():
            assert row["regime"] in ("calm", "stress")
            assert row["regime_method"] == "student_t_hmm_higher_variance_state"

    def test_regime_is_absent_on_short_payloads(self, engine):
        result = engine.predict(_frame(20), attestation=_attestation())
        for _, row in result.predictions_df.iterrows():
            assert row["regime"] is None
            assert row["regime_method"] == "insufficient_history_for_regime"
