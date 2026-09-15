"""Round-seven honesty: measured channels only (R2, R4).

Anchors:
- the analyzer no longer manufactures an "accuracy" from hand-rolled weights
  (its cleaning term rewarded fixes the cleaner deliberately stopped making);
  accuracy is None and the gate renormalises over present components;
- validator anomalies propagate as a measured integrity count;
- the report pipeline carries no legacy channel aliases: funding liquidity is
  an explicit not-measured status, the model-score report says what it is,
  and institutional profiles carry no invented vulnerabilities or strengths.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from backend.modules.data.analyzer import DataAnalyzer
from backend.modules.engine.orchestrator import EngineResult, RiskScores
from backend.modules.results.generator import ResultsGenerator


class _ValidationReport:
    critical_errors = 0
    anomalies_count = 3


class _CleaningReport:
    fixed_issues = 0


def _frame() -> pd.DataFrame:
    return pd.DataFrame({
        "Date": pd.date_range("2024-01-01", periods=30, freq="D"),
        "source_code": "SRC_A",
        "Value": np.linspace(100, 110, 30),
    })


class TestAnalyzerHonesty:
    def test_accuracy_is_unmeasured_not_invented(self):
        report = DataAnalyzer("job").analyze(_frame(), _ValidationReport(), _CleaningReport())
        assert report.accuracy_score is None

    def test_validator_anomalies_propagate_as_integrity(self):
        report = DataAnalyzer("job").analyze(_frame(), _ValidationReport(), _CleaningReport())
        assert report.integrity_anomalies == 3

    def test_statistics_are_still_measured(self):
        report = DataAnalyzer("job").analyze(_frame(), _ValidationReport(), _CleaningReport())
        assert report.statistics["rows"] == 30

    def test_empty_frame_does_not_invent_a_score(self):
        report = DataAnalyzer("job").analyze(pd.DataFrame(), _ValidationReport(), _CleaningReport())
        assert report.accuracy_score is None


def _engine_result(tmp_path) -> EngineResult:
    scores = RiskScores(
        model_score={"overall": 0.42, "current": 0.44, "n_windows": 10},
        overall_score=0.42,
        risk_level="uncalibrated",
        systemic_risk={},
        operational_risk={"process_risk": 12.0, "data_quality_score": 88.0},
        score_semantics={"units": "standardized one-step-ahead indicator prediction"},
    )
    return EngineResult(
        job_id="job-1",
        model_name="temporal_attention",
        model_version="v1",
        risk_scores=scores,
        predictions_path=None,
        explanations_path=None,
        performance_metrics={},
        compute_stats={},
        processed_at=datetime.now(timezone.utc),
        duration_seconds=1.0,
    )


class TestReportChannels:
    def test_funding_channel_is_explicitly_not_measured(self, tmp_path):
        result = ResultsGenerator("job-1", str(tmp_path)).generate(_engine_result(tmp_path))
        funding = result.funding_liquidity_report
        assert funding["status"] == "not_measured"
        assert funding["overall_score"] is None

    def test_model_score_report_carries_the_model_score(self, tmp_path):
        result = ResultsGenerator("job-1", str(tmp_path)).generate(_engine_result(tmp_path))
        assert result.model_score_report["overall_score"] == pytest.approx(0.42)

    def test_executive_factors_mark_absence_instead_of_nan(self, tmp_path):
        result = ResultsGenerator("job-1", str(tmp_path)).generate(_engine_result(tmp_path))
        funding_factor = next(
            f for f in result.executive_summary.top_risk_factors if f["factor"] == "Funding Pressure"
        )
        assert funding_factor["status"] == "not_measured"
        assert funding_factor["score"] is None

    def test_profiles_carry_no_invented_narrative(self, tmp_path):
        result = ResultsGenerator("job-1", str(tmp_path)).generate(_engine_result(tmp_path))
        profile = result.institutional_profiles[0]
        assert profile.risk_score == pytest.approx(0.42)
        assert profile.risk_level == "uncalibrated"
        assert profile.vulnerabilities == []
        assert profile.strengths == []
        assert "standardized" in profile.score_units
