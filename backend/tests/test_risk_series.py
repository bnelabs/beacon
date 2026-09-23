"""Tests for rolling per-timestep risk inference.

``predict()`` returns one score per data source -- the value for its most recent
timestep -- which cannot be scored against per-row targets. These tests pin down
the rolling series that replaces it: alignment with the row each prediction was
made for, the seam boundaries that stop metrics from differencing across sources,
and the consistency invariant that the final step of the series equals the point
prediction. Skipped when torch is absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

torch = pytest.importorskip("torch")

from backend.exceptions import PredictionBlockedError, SchemaValidationError  # noqa: E402
from backend.modules.data.quality_gate import QualityAttestation  # noqa: E402
from backend.modules.engine.backtesting import (  # noqa: E402
    directional_accuracy,
    segment_slices,
)
from backend.modules.engine.model_io import safe_torch_save  # noqa: E402
from backend.modules.engine.multi_scale_trainer import (  # noqa: E402
    MultiScaleTemporalAttentionModel,
)
from backend.modules.engine.prediction_engine import RealPredictionEngine  # noqa: E402

SEQUENCE_LENGTH = 4
ROWS_PER_SOURCE = 10
SOURCES = ("SRC_A", "SRC_B")
WINDOWS_PER_SOURCE = ROWS_PER_SOURCE - SEQUENCE_LENGTH + 1


def _attestation(job_id: str = "job-series") -> QualityAttestation:
    return QualityAttestation(
        job_id=job_id, verified=True, checked_at="2024-01-01T00:00:00+00:00"
    )


def _checkpoint(
    path: Path,
    *,
    sources=SOURCES,
    with_stats: bool = True,
    seed: int = 7,
) -> Path:
    """Write a real checkpoint in the layout ``RealPredictionEngine`` expects."""
    torch.manual_seed(seed)
    model = MultiScaleTemporalAttentionModel(
        num_sources=max(len(sources), 1),
        sequence_length=SEQUENCE_LENGTH,
        d_model=8,
        nhead=2,
        num_layers=1,
        dropout=0.0,
    )
    payload = {
        "model_state_dict": model.state_dict(),
        "config": {
            "sequence_length": SEQUENCE_LENGTH,
            "d_model": 8,
            "nhead": 2,
            "num_layers": 1,
            "dropout": 0.0,
        },
        "sources": list(sources),
    }
    if with_stats:
        payload["source_stats"] = {
            source: {"mean": 50.0 + 10 * index, "std": 2.0 + index}
            for index, source in enumerate(sources)
        }
    safe_torch_save(payload, path)
    return path


def _frame(rows: int = ROWS_PER_SOURCE, sources=SOURCES) -> pd.DataFrame:
    records = []
    for index, source in enumerate(sources):
        dates = pd.date_range("2024-01-01", periods=rows, freq="D")
        for step in range(rows):
            records.append({
                "source_code": source,
                "Date": dates[step],
                "Value": float(50 + 10 * index + step),
            })
    return pd.DataFrame(records)


@pytest.fixture()
def engine(tmp_path: Path) -> RealPredictionEngine:
    return RealPredictionEngine(
        model_path=str(_checkpoint(tmp_path / "best_model.pt")),
        device=torch.device("cpu"),
        config={},
        quality_attestation=_attestation(),
    )


class TestRiskSeries:
    def test_series_is_aligned_time_ordered_and_seam_bounded(self, engine):
        payload = _frame()
        result = engine.predict_risk_series(payload, attestation=_attestation())

        assert result.n_sources == 2
        assert result.n_steps == 2 * WINDOWS_PER_SOURCE
        assert result.boundaries == [WINDOWS_PER_SOURCE]
        assert result.sources == list(SOURCES)
        assert result.n_dropped_for_history == 2 * (SEQUENCE_LENGTH - 1)
        assert result.stats_provenance == {source: "checkpoint" for source in SOURCES}

        for index, source in enumerate(SOURCES):
            block = result.frame.iloc[
                index * WINDOWS_PER_SOURCE:(index + 1) * WINDOWS_PER_SOURCE
            ]
            assert set(block["source"]) == {source}
            assert block["Date"].is_monotonic_increasing

            # Every prediction is paired with the row whose window it used, so the
            # caller can align it with that row's target.
            source_positions = np.flatnonzero(
                (payload["source_code"] == source).to_numpy()
            )
            expected = source_positions[SEQUENCE_LENGTH - 1:]
            assert block["row_offset"].tolist() == expected.tolist()

    def test_last_step_matches_the_point_prediction(self, engine):
        """The rolling series must agree with `predict()` on the shared final row."""
        payload = _frame()
        series = engine.predict_risk_series(payload, attestation=_attestation())
        point = engine.predict(payload, attestation=_attestation())

        point_scores = dict(
            zip(point.predictions_df["source"], point.predictions_df["risk_score"])
        )
        for source in SOURCES:
            last = series.frame.loc[
                series.frame["source"] == source, "risk_score"
            ].iloc[-1]
            assert last == pytest.approx(point_scores[source], rel=1e-4, abs=1e-6)

    def test_directional_score_never_spans_a_source_seam(self, engine):
        result = engine.predict_risk_series(_frame(), attestation=_attestation())

        # The series reports the first row of the second source as its only seam,
        # so the concatenated series splits into exactly one segment per source.
        assert result.boundaries == [WINDOWS_PER_SOURCE]
        assert (result.boundaries[0] % WINDOWS_PER_SOURCE) == 0
        assert segment_slices(result.boundaries, 2 * WINDOWS_PER_SOURCE) == [
            slice(0, WINDOWS_PER_SOURCE),
            slice(WINDOWS_PER_SOURCE, 2 * WINDOWS_PER_SOURCE),
        ]

        # Two sources with identical internal movement but a level jump at the
        # seam: the boundary-aware score ignores the manufactured change, while the
        # naive whole-series score is dragged down by it.
        actual = np.tile(np.arange(WINDOWS_PER_SOURCE, dtype=float), 2)
        predicted = actual + np.concatenate([
            np.zeros(WINDOWS_PER_SOURCE),
            np.full(WINDOWS_PER_SOURCE, 100.0),
        ])

        assert directional_accuracy(actual, predicted) == pytest.approx(
            (2 * WINDOWS_PER_SOURCE - 2) / (2 * WINDOWS_PER_SOURCE - 1)
        )
        assert directional_accuracy(
            actual, predicted, boundaries=result.boundaries
        ) == pytest.approx(1.0)

    def test_max_steps_keeps_the_most_recent_timesteps(self, engine):
        result = engine.predict_risk_series(
            _frame(), attestation=_attestation(), max_steps=6
        )

        assert result.max_steps == 6
        assert result.truncated == {source: ROWS_PER_SOURCE - 6 for source in SOURCES}
        assert result.n_steps == 2 * (6 - SEQUENCE_LENGTH + 1)
        assert result.boundaries == [3]
        for _, block in result.frame.groupby("source"):
            # Six rows are retained, but the first three are window warm-up, so the
            # first *scored* row is the one whose window is finally full.
            assert block["Date"].min() == pd.Timestamp("2024-01-08")
            assert block["Date"].max() == pd.Timestamp("2024-01-10")
        # Warm-up is a function of the window, not of the cap; rows dropped by the
        # cap are reported separately in `truncated`.
        assert result.n_dropped_for_history == 2 * (SEQUENCE_LENGTH - 1)

    def test_scores_do_not_depend_on_the_batch_size(self, engine):
        one_pass = engine.predict_risk_series(
            _frame(), attestation=_attestation(), batch_size=64
        )
        many_passes = engine.predict_risk_series(
            _frame(), attestation=_attestation(), batch_size=2
        )
        np.testing.assert_allclose(
            one_pass.frame["risk_score"].to_numpy(),
            many_passes.frame["risk_score"].to_numpy(),
            rtol=1e-6,
            atol=1e-7,
        )

    def test_short_source_is_skipped_and_counted(self, engine):
        short = pd.DataFrame({
            "source_code": "SRC_SHORT",
            "Date": pd.date_range("2024-01-01", periods=3),
            "Value": [1.0, 2.0, 3.0],
        })
        payload = pd.concat([_frame(), short], ignore_index=True)

        result = engine.predict_risk_series(payload, attestation=_attestation())

        assert "SRC_SHORT" not in result.sources
        assert result.sources == list(SOURCES)
        assert result.n_dropped_for_history == 2 * (SEQUENCE_LENGTH - 1) + 3
        assert result.boundaries == [WINDOWS_PER_SOURCE]

    def test_payload_window_stats_are_flagged(self, tmp_path):
        """Normalising on the evaluated window is recorded, because it is optimistic."""
        path = _checkpoint(tmp_path / "no_stats.pt", with_stats=False)
        engine = RealPredictionEngine(
            model_path=str(path),
            device=torch.device("cpu"),
            config={},
            quality_attestation=_attestation(),
        )

        result = engine.predict_risk_series(_frame(), attestation=_attestation())

        assert set(result.stats_provenance.values()) == {"payload_window"}

    def test_rolling_inference_is_blocked_without_an_attestation(self, tmp_path):
        blocked = RealPredictionEngine(
            model_path=str(_checkpoint(tmp_path / "blocked.pt")),
            device=torch.device("cpu"),
            config={},
        )
        with pytest.raises(PredictionBlockedError):
            blocked.predict_risk_series(_frame())

    def test_summary_is_json_serialisable(self, engine):
        result = engine.predict_risk_series(
            _frame(), attestation=_attestation(), max_steps=6
        )
        decoded = json.loads(json.dumps(result.to_dict(), allow_nan=False))
        assert decoded["n_steps"] == 6
        assert decoded["boundaries"] == [3]
        assert decoded["ordering"] == "series_major_then_time"
        # A feed-grain payload has no per-entity identity, so each series IS its
        # feed: the new series fields mirror the source fields.
        assert decoded["n_series"] == 2
        assert decoded["series_ids"] == list(SOURCES)
        assert decoded["stats_provenance"] == {source: "checkpoint" for source in SOURCES}


class TestRiskSeriesValidation:
    def test_payload_without_a_source_column_is_rejected(self, engine):
        payload = pd.DataFrame({
            "Date": pd.date_range("2024-01-01", periods=10),
            "Value": range(10),
        })
        with pytest.raises(SchemaValidationError):
            engine.predict_risk_series(payload, attestation=_attestation())

    def test_payload_without_a_value_column_is_rejected(self, engine):
        payload = _frame().drop(columns=["Value"])
        with pytest.raises(SchemaValidationError):
            engine.predict_risk_series(payload, attestation=_attestation())

    def test_max_steps_below_the_window_is_rejected(self, engine):
        with pytest.raises(SchemaValidationError):
            engine.predict_risk_series(
                _frame(), attestation=_attestation(), max_steps=SEQUENCE_LENGTH
            )

    def test_payload_with_no_usable_history_is_rejected(self, engine):
        payload = _frame(rows=SEQUENCE_LENGTH)
        with pytest.raises(SchemaValidationError):
            engine.predict_risk_series(payload, attestation=_attestation())


class TestPredictedRowAlignment:
    """The score for the window ending at row t predicts row t+1, and says so.

    Training pairs the window ``normalized[i:i+L]`` with the target
    ``normalized[i+L]`` -- the row AFTER the window end. Ground truth must
    therefore join on that next row, never on the window-end row itself; the
    frame carries both positions so the convention is explicit and the source
    seam can never be crossed by an alignment.
    """

    def test_predicted_row_offset_is_the_window_end_plus_one_within_source(self, engine):
        payload = _frame()
        result = engine.predict_risk_series(payload, attestation=_attestation())
        frame = result.frame

        for index, source in enumerate(SOURCES):
            block = frame.iloc[
                index * WINDOWS_PER_SOURCE:(index + 1) * WINDOWS_PER_SOURCE
            ]
            source_positions = np.flatnonzero(
                (payload["source_code"] == source).to_numpy()
            )
            ends = source_positions[SEQUENCE_LENGTH - 1:]
            expected_predicted = ends + 1
            # The final window of the source has no next row inside the
            # source's span: it must be -1, never the first row of the next
            # source.
            expected_predicted[-1] = -1
            assert block["row_offset"].tolist() == ends.tolist()
            assert block["predicted_row_offset"].tolist() == expected_predicted.tolist()

    def test_alignment_helper_pairs_scores_with_the_next_row_target(self, engine):
        from backend.modules.engine.backtesting import align_series_targets

        payload = _frame()
        result = engine.predict_risk_series(payload, attestation=_attestation())
        frame = result.frame

        # A target column whose value at row r is 1000 + r, so the correct
        # pairing is checkable by arithmetic alone.
        targets = np.full(payload.shape[0], np.nan)
        targets[:] = 1000.0 + np.arange(payload.shape[0])

        mask, actuals, preds = align_series_targets(
            frame["predicted_row_offset"].to_numpy(),
            targets,
            frame["risk_score"].to_numpy(),
        )

        # Every source's final window is unalignable; everything else pairs
        # with target[end + 1].
        assert int(mask.sum()) == frame.shape[0] - len(SOURCES)
        expected_actuals = []
        for index in range(len(SOURCES)):
            ends = np.arange(SEQUENCE_LENGTH - 1, ROWS_PER_SOURCE)
            base = index * ROWS_PER_SOURCE
            expected_actuals.extend(
                1000.0 + base + ends[ends + 1 < ROWS_PER_SOURCE] + 1
            )
        assert actuals.tolist() == pytest.approx(expected_actuals)
        assert preds.tolist() == pytest.approx(
            frame.loc[mask, "risk_score"].to_numpy().tolist()
        )

    def test_alignment_helper_rejects_length_mismatch(self):
        from backend.modules.engine.backtesting import align_series_targets

        with pytest.raises(ValueError):
            align_series_targets([1, 2], [0.0, 1.0, 2.0], [5.0])

    def test_alignment_helper_excludes_nan_targets(self):
        from backend.modules.engine.backtesting import align_series_targets

        # Offset 1 -> targets[1] = NaN (excluded); offset 2 -> targets[2] = 30
        # (included); offset -1 -> outside the source's span (excluded).
        mask, actuals, preds = align_series_targets(
            [1, 2, -1], [10.0, np.nan, 30.0, 40.0], [1.0, 2.0, 3.0]
        )
        assert mask.tolist() == [False, True, False]
        assert actuals.tolist() == pytest.approx([30.0])
        assert preds.tolist() == pytest.approx([2.0])
