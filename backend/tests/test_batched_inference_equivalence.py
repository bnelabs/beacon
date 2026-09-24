"""Batched-vs-serial inference equivalence for the single-entity path.

``RealPredictionEngine._predict_single`` now scores through
``_predict_single_batched`` (one forward pass over every source's final
window, one over every held-out calibration window) and falls back to
``_predict_single_serial`` on any failure. This test pins the contract the
fallback relies on: for the same payload, the two paths produce the same
prediction rows — same sources in the same order, the same confidence
methods, the same regime labels, the same uncertainty decomposition — with
numeric fields agreeing within float32 batch-vs-single-row reduction noise.

Tolerances: the model runs in float32; a batched GEMM and a single-row GEMM
reduce in a different order, so exact bit equality is not the right bar —
``rtol=1e-5`` is orders of magnitude tighter than any meaningful drift while
leaving float32 rounding (~1e-7 relative) comfortably inside.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

torch = pytest.importorskip("torch")

from backend.modules.data.quality_gate import (  # noqa: E402
    DataQualityGate,
    QualityPolicy,
)
from backend.modules.engine.model_io import safe_torch_save  # noqa: E402
from backend.modules.engine.multi_scale_trainer import (  # noqa: E402
    MultiScaleTemporalAttentionModel,
)
from backend.modules.engine.prediction_engine import (  # noqa: E402
    RealPredictionEngine,
)

NUM_SOURCES = 6
LENGTH = 500
SEQUENCE_LENGTH = 20

NUMERIC_COLUMNS = [
    "prediction",
    "risk_score",
    "confidence_lower",
    "confidence_upper",
    "aleatoric_var",
    "epistemic_var",
    "epistemic_share",
]
EXACT_COLUMNS = [
    "source",
    "confidence_method",
    "regime",
    "regime_method",
    "uncertainty_status",
    "uncertainty_reasons",
]


def _engine(tmp_path) -> RealPredictionEngine:
    """A minimal real checkpoint for NUM_SOURCES sources (the layout
    test_risk_series.py / test_regime_batch_equivalence.py established)."""
    torch.manual_seed(11)
    model = MultiScaleTemporalAttentionModel(
        num_sources=NUM_SOURCES,
        sequence_length=SEQUENCE_LENGTH,
        d_model=16,
        nhead=4,
        num_layers=1,
        dropout=0.0,
    )
    checkpoint = tmp_path / "best_model.pt"
    safe_torch_save(
        {
            "model_state_dict": model.state_dict(),
            "config": {
                "sequence_length": SEQUENCE_LENGTH,
                "d_model": 16,
                "nhead": 4,
                "num_layers": 1,
                "dropout": 0.0,
            },
            "sources": [f"S{i}" for i in range(NUM_SOURCES)],
        },
        checkpoint,
    )
    return RealPredictionEngine(
        model_path=str(checkpoint),
        device=torch.device("cpu"),
        config={},
    )


def _payload() -> pd.DataFrame:
    """Six deterministic mixed-regime daily series, one per known source."""
    rng = np.random.default_rng(42)
    frames = []
    for i in range(NUM_SOURCES):
        values = rng.normal(0.0, 1.0, LENGTH)
        # A level shift halfway through keeps the regime fit off a constant
        # (which would trip the degenerate-seed fallback and change the
        # per-source stream the serial and batched legs share).
        values[LENGTH // 2 :] += 0.5
        values += 0.01 * np.arange(LENGTH) * (1 if i % 2 else -1)
        dates = pd.bdate_range("2020-01-01", periods=LENGTH)
        frames.append(
            pd.DataFrame(
                {
                    "Date": dates,
                    "source_code": f"S{i}",
                    "Close": values,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def _attestation(df: pd.DataFrame):
    gate = DataQualityGate(QualityPolicy(min_total_rows=5))
    components = {
        sc: df[df["source_code"] == sc] for sc in df["source_code"].unique()
    }
    return gate.enforce(components, job_id="equivalence-1")


def _compare(batched: pd.DataFrame, serial: pd.DataFrame) -> None:
    a = batched.sort_values("source").reset_index(drop=True)
    b = serial.sort_values("source").reset_index(drop=True)
    assert list(a.columns) == list(b.columns)
    assert len(a) == len(b) == NUM_SOURCES
    assert list(a["source"]) == list(b["source"])
    for col in EXACT_COLUMNS:
        assert (a[col].fillna("__NA__") == b[col].fillna("__NA__")).all(), col
    for col in NUMERIC_COLUMNS:
        if col not in a.columns:
            continue
        av = a[col].to_numpy(dtype=float)
        bv = b[col].to_numpy(dtype=float)
        np.testing.assert_allclose(
            av, bv, rtol=1e-5, atol=1e-6, equal_nan=True, err_msg=col
        )


def test_batched_and_serial_paths_agree(tmp_path):
    engine = _engine(tmp_path)
    df = _payload()
    attestation = _attestation(df)

    assert engine._batch_inference is True
    r_batched = engine.predict(df, attestation=attestation)

    engine._batch_inference = False
    r_serial = engine.predict(df, attestation=attestation)

    _compare(r_batched.predictions_df, r_serial.predictions_df)

    # The summaries are one shared computation on both legs (pass 3); they
    # must agree exactly, not approximately.
    assert r_batched.uncertainty_summary == r_serial.uncertainty_summary
    assert r_batched.feature_importances == r_serial.feature_importances
    assert r_batched.executive_summary == r_serial.executive_summary
    for key in r_batched.metrics:
        bv = r_batched.metrics[key]
        sv = r_serial.metrics[key]
        if isinstance(bv, float):
            np.testing.assert_allclose(bv, sv, rtol=1e-5, atol=1e-6)
        else:
            assert bv == sv, key
    # Per-source interval bounds: same sources, bounds within float noise.
    assert set(r_batched.confidence_intervals) == set(r_serial.confidence_intervals)
    for src, (bl, bu) in r_batched.confidence_intervals.items():
        sl, su = r_serial.confidence_intervals[src]
        if bl is None:
            assert sl is None
            continue
        np.testing.assert_allclose(bl, sl, rtol=1e-5, atol=1e-6)
        np.testing.assert_allclose(bu, su, rtol=1e-5, atol=1e-6)


def test_batched_path_is_the_default(tmp_path):
    """The default predict() scores through the batched pass: with the
    serial path broken, a working batched pass must still answer — proving
    the batched leg, not the serial one, produced the result."""
    engine = _engine(tmp_path)
    df = _payload()
    attestation = _attestation(df)

    serial = engine._predict_single_serial

    def broken_serial(_input):
        raise AssertionError("serial path should not have run")

    engine._predict_single_serial = broken_serial
    try:
        result = engine.predict(df, attestation=attestation)
    finally:
        engine._predict_single_serial = serial
    assert len(result.predictions_df) == NUM_SOURCES


def test_dispatcher_falls_back_to_serial(caplog, tmp_path):
    """Any failure in the batched pass degrades to the serial path — slow,
    never different: the result equals the serial result and the fallback is
    logged, not swallowed."""
    engine = _engine(tmp_path)
    df = _payload()
    attestation = _attestation(df)

    engine._batch_inference = False
    r_serial = engine.predict(df, attestation=attestation)

    engine._batch_inference = True
    def broken(_input):
        raise RuntimeError("simulated batched failure")

    engine._predict_single_batched = broken
    import logging

    with caplog.at_level(logging.WARNING):
        r_fallback = engine.predict(df, attestation=attestation)

    assert any("Batched source inference unavailable" in m for m in caplog.messages)
    _compare(r_fallback.predictions_df, r_serial.predictions_df)
    assert r_fallback.uncertainty_summary == r_serial.uncertainty_summary
