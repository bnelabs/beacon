"""Tests for data governance: typed ingestion failures and the quality gate.

Two regressions are covered explicitly:

* The AI4Risk plugin used to synthesise plausible interbank networks when its
  dataset was missing. Fake exposure edges are indistinguishable from real ones
  once they reach the graph, so the plugin must now fail loudly instead.
* A completely empty payload scored exactly 70/100 on the composite quality
  score and was therefore certified as ``fit_for_engine``. The gate must reject
  it regardless of that score.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import pytest

from backend.exceptions import (
    BeaconError,
    DataIngestionError,
    DataQualityError,
    DataSourceUnavailableError,
    DatasetMissingError,
    EmptyDatasetError,
    PredictionBlockedError,
    SchemaValidationError,
)
from backend.modules.data.quality_gate import DataQualityGate, QualityAttestation, QualityPolicy
from backend.plugins.base import DataSourcePlugin, register_plugin


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------

class _FakeDataSource:
    def __init__(self, plugin_type: str, config: Optional[Dict[str, Any]] = None):
        self.plugin_type = plugin_type
        self.config = config or {}


class _FakeItem:
    def __init__(self, code: str, plugin_type: str, endpoint: Optional[str] = None):
        self.id = abs(hash(code)) % 10_000
        self.code = code
        self.category = "economic_indicators"
        self.region = "GLOBAL"
        self.endpoint = endpoint or code
        self.data_source = _FakeDataSource(plugin_type)


class _FakeQuery:
    def __init__(self, item):
        self._item = item

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._item


class _FakeDB:
    """Returns the queued catalogue items in order, mimicking ``db.query().filter().first()``."""

    def __init__(self, items: List[_FakeItem]):
        self._items = list(items)

    def query(self, _model):
        item = self._items.pop(0) if self._items else None
        return _FakeQuery(item)


class _FailingPlugin(DataSourcePlugin):
    def validate_config(self) -> None:
        return None

    def test_connection(self) -> Dict[str, Any]:
        return {"success": False}

    def fetch_asset_data(self, symbols, start_date, end_date):
        raise DataSourceUnavailableError("provider unreachable", context={"provider": "test"})

    def fetch_indicator_data(self, indicator_id, start_date, end_date):
        raise DataSourceUnavailableError(
            "provider unreachable", context={"indicator": indicator_id}
        )

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        return {}

    @classmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        return {"name": "Failing", "description": "always fails", "version": "1.0.0"}


class _EmptyPlugin(_FailingPlugin):
    def fetch_indicator_data(self, indicator_id, start_date, end_date):
        return pd.DataFrame()

    def fetch_asset_data(self, symbols, start_date, end_date):
        return pd.DataFrame()

    @classmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        return {"name": "Empty", "description": "returns nothing", "version": "1.0.0"}


class _GoodPlugin(_FailingPlugin):
    def fetch_indicator_data(self, indicator_id, start_date, end_date):
        return pd.DataFrame(
            {"Date": pd.date_range("2023-01-01", periods=40, freq="D"), "Value": range(40)}
        )

    @classmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        return {"name": "Good", "description": "returns data", "version": "1.0.0"}


register_plugin("test_failing", _FailingPlugin)
register_plugin("test_empty", _EmptyPlugin)
register_plugin("test_good", _GoodPlugin)


def _frame(rows: int = 40, with_date: bool = True) -> pd.DataFrame:
    data: Dict[str, Any] = {"Value": range(rows)}
    if with_date:
        data["Date"] = pd.date_range("2023-01-01", periods=rows, freq="D")
    return pd.DataFrame(data)


# --------------------------------------------------------------------------
# Exception contract
# --------------------------------------------------------------------------

def test_domain_errors_expose_stable_codes():
    assert DataSourceUnavailableError("x").code == "DATA_SOURCE_UNAVAILABLE"
    assert DatasetMissingError("x").code == "DATASET_MISSING"
    assert SchemaValidationError("x").code == "SCHEMA_INVALID"
    assert EmptyDatasetError("x").code == "EMPTY_DATASET"
    assert DataQualityError("x").code == "DATA_QUALITY_FAILED"
    assert PredictionBlockedError("x").code == "PREDICTION_BLOCKED"


def test_errors_are_beacon_errors_and_serialise():
    exc = DatasetMissingError("dataset gone", context={"data_dir": "/tmp/ai4risk"})
    assert isinstance(exc, BeaconError)
    assert isinstance(exc, DataIngestionError)
    payload = exc.to_dict()
    assert payload["code"] == "DATASET_MISSING"
    assert payload["context"]["data_dir"] == "/tmp/ai4risk"
    assert "dataset gone" in str(exc)


# --------------------------------------------------------------------------
# AI4Risk plugin: no synthetic fallback
# --------------------------------------------------------------------------

def test_ai4risk_plugin_has_no_sample_generators():
    from backend.plugins.ai4risk_plugin import AI4RiskInterbankPlugin

    for name in ("_generate_sample_network", "_generate_sample_features", "_generate_sample_ratings"):
        assert not hasattr(AI4RiskInterbankPlugin, name), f"{name} must be removed"


def test_ai4risk_plugin_satisfies_the_base_contract(tmp_path):
    """Regression: the plugin omitted an abstract method and could not be instantiated."""
    from backend.plugins.ai4risk_plugin import AI4RiskInterbankPlugin

    data_dir = tmp_path / "ai4risk"
    data_dir.mkdir()
    plugin = AI4RiskInterbankPlugin({"data_dir": str(data_dir)})

    assert isinstance(plugin, DataSourcePlugin)
    with pytest.raises(SchemaValidationError):
        plugin.fetch_asset_data(["AAPL"], datetime(2023, 1, 1), datetime(2023, 2, 1))


def test_ai4risk_plugin_rejects_missing_dataset(tmp_path):
    from backend.plugins.ai4risk_plugin import AI4RiskInterbankPlugin

    with pytest.raises(DatasetMissingError) as excinfo:
        AI4RiskInterbankPlugin({"data_dir": str(tmp_path / "absent")})

    assert excinfo.value.context["download_url"]
    assert not list((tmp_path / "absent").glob("*")) if (tmp_path / "absent").exists() else True


def test_ai4risk_plugin_reads_real_dataset(tmp_path):
    from backend.plugins.ai4risk_plugin import AI4RiskInterbankPlugin

    data_dir = tmp_path / "ai4risk"
    data_dir.mkdir()
    pd.DataFrame(
        {
            "quarter": pd.date_range("2020-03-31", periods=4, freq="QE"),
            "bank_i": ["A", "B", "A", "C"],
            "bank_j": ["B", "C", "C", "A"],
            "exposure": [1.0, 2.0, 3.0, 4.0],
        }
    ).to_csv(data_dir / "interbank_network.csv", index=False)

    plugin = AI4RiskInterbankPlugin({"data_dir": str(data_dir)})
    df = plugin.fetch_data("network_topology", datetime(2019, 1, 1), datetime(2021, 1, 1))

    assert list(df.columns) == ["Date", "source_bank", "target_bank", "Value"]
    assert len(df) == 4


def test_ai4risk_plugin_reports_schema_error(tmp_path):
    from backend.plugins.ai4risk_plugin import AI4RiskInterbankPlugin

    data_dir = tmp_path / "ai4risk"
    data_dir.mkdir()
    pd.DataFrame({"quarter": pd.date_range("2020-03-31", periods=2, freq="QE"), "junk": [1, 2]}).to_csv(
        data_dir / "interbank_network.csv", index=False
    )

    plugin = AI4RiskInterbankPlugin({"data_dir": str(data_dir)})
    with pytest.raises(SchemaValidationError):
        plugin.fetch_data("network_topology", datetime(2019, 1, 1), datetime(2021, 1, 1))


def test_ai4risk_plugin_rejects_unknown_item(tmp_path):
    from backend.plugins.ai4risk_plugin import AI4RiskInterbankPlugin

    data_dir = tmp_path / "ai4risk"
    data_dir.mkdir()
    plugin = AI4RiskInterbankPlugin({"data_dir": str(data_dir)})

    with pytest.raises(SchemaValidationError):
        plugin.fetch_data("not_a_real_item", datetime(2019, 1, 1), datetime(2021, 1, 1))


# --------------------------------------------------------------------------
# Quality gate
# --------------------------------------------------------------------------

def test_gate_accepts_healthy_payload():
    gate = DataQualityGate(QualityPolicy(min_total_rows=5))
    attestation = gate.enforce({"A": _frame(40)}, job_id="job-1")

    assert attestation.verified is True
    assert attestation.failures == []
    assert "verified" in attestation.summary()


def test_gate_rejects_empty_payload_despite_composite_score():
    """The empty payload is exactly the case the composite score green-lights."""
    gate = DataQualityGate(QualityPolicy())

    # What the legacy scoring produces for an empty payload:
    empty_score = 100 * 0.25 + 100 * 0.25 + 100 * 0.20 + 0.0 * 0.30
    assert empty_score >= 70.0, "precondition: the composite score would have passed"

    with pytest.raises(EmptyDatasetError) as excinfo:
        gate.enforce({"A": pd.DataFrame()}, job_id="job-empty", quality_score=empty_score, completeness=100.0)

    assert excinfo.value.code == "EMPTY_DATASET"


def test_gate_rejects_missing_required_column():
    gate = DataQualityGate(QualityPolicy())
    payload = {"A": _frame(40, with_date=False)}

    with pytest.raises(DataQualityError) as excinfo:
        gate.enforce(payload, job_id="job-nodate")

    assert "required_columns" in str(excinfo.value.context["failures"])


def test_gate_rejects_undersized_dataset():
    gate = DataQualityGate(QualityPolicy(min_rows_per_dataset=10, min_total_rows=10))
    with pytest.raises(DataQualityError):
        gate.enforce({"A": _frame(3)}, job_id="job-small")


def test_gate_emits_alert_on_failure():
    alerts: List[tuple] = []
    gate = DataQualityGate(
        QualityPolicy(min_total_rows=1000),
        alert_sink=lambda source, issue, severity: alerts.append((source, issue, severity)),
    )

    with pytest.raises(DataQualityError):
        gate.enforce({"A": _frame(10)}, job_id="job-alert")

    assert alerts, "a data-quality alert must be raised"
    assert alerts[0][0] == "pipeline:job-alert"
    assert alerts[0][2] in {"high", "critical"}


def test_alert_sink_failure_does_not_mask_gate_error():
    def exploding_sink(source, issue, severity):
        raise RuntimeError("notification backend down")

    gate = DataQualityGate(QualityPolicy(min_total_rows=1000), alert_sink=exploding_sink)
    with pytest.raises(DataQualityError):
        gate.enforce({"A": _frame(10)}, job_id="job-sink")


def test_gate_missing_ratio_and_freshness():
    sparse = _frame(40)
    sparse.loc[0:30, "Value"] = None
    gate = DataQualityGate(QualityPolicy(min_total_rows=5, max_missing_ratio=0.1))
    with pytest.raises(DataQualityError):
        gate.enforce({"A": sparse}, job_id="job-sparse")

    stale = pd.DataFrame(
        {"Date": pd.date_range("2000-01-01", periods=40, freq="D"), "Value": range(40)}
    )
    fresh_gate = DataQualityGate(QualityPolicy(min_total_rows=5, max_staleness_days=30))
    with pytest.raises(DataQualityError):
        fresh_gate.enforce({"A": stale}, job_id="job-stale")


def test_require_attestation_blocks_prediction():
    with pytest.raises(PredictionBlockedError):
        DataQualityGate.require(None)

    strict = DataQualityGate(QualityPolicy(min_total_rows=1000))
    failed = strict.evaluate({"A": _frame(1)}, job_id="job-x")
    with pytest.raises(PredictionBlockedError):
        DataQualityGate.require(failed)

    lenient = DataQualityGate(QualityPolicy(min_total_rows=5))
    verified = lenient.evaluate({"A": _frame(50)}, job_id="job-y")
    assert DataQualityGate.require(verified) is verified


def test_attestation_round_trips_to_dict():
    gate = DataQualityGate(QualityPolicy(min_total_rows=5))
    attestation = gate.enforce({"A": _frame(40)}, job_id="job-rt", quality_score=88.0, completeness=97.5)
    payload = attestation.to_dict()

    assert payload["verified"] is True
    assert payload["quality_score"] == 88.0
    assert payload["dataset_row_counts"] == {"A": 40}
    assert isinstance(payload["checks"], list) and payload["checks"]


def test_policy_serialises_sequences_as_lists():
    policy = QualityPolicy()
    payload = policy.to_dict()
    assert isinstance(payload["required_columns"], list)
    assert isinstance(payload["value_columns"], list)


# --------------------------------------------------------------------------
# Attestation passed between pipeline stages
# --------------------------------------------------------------------------

def test_attestation_survives_a_job_result_round_trip():
    gate = DataQualityGate(QualityPolicy(min_total_rows=5))
    original = gate.enforce({"A": _frame(40)}, job_id="job-1", quality_score=91.0)

    restored = QualityAttestation.from_dict(original.to_dict())
    assert restored.verified is True
    assert restored.job_id == "job-1"
    assert restored.quality_score == 91.0
    assert len(restored.checks) == len(original.checks)


def test_attestation_resolved_from_full_payload():
    gate = DataQualityGate(QualityPolicy(min_total_rows=5))
    attestation = gate.enforce({"A": _frame(40)}, job_id="job-2")

    resolved = DataQualityGate.attestation_from_job_result(
        {"quality_attestation": attestation.to_dict()}, job_id="job-2"
    )
    assert resolved is not None
    assert resolved.verified is True


def test_legacy_job_result_is_reconstructed():
    resolved = DataQualityGate.attestation_from_job_result(
        {"fit_for_engine": True, "quality_score": 88.0, "completeness": 99.0},
        job_id="legacy-1",
    )
    assert resolved is not None
    assert resolved.verified is True
    assert resolved.failures == []
    assert resolved.checks[0].name == "legacy_record"


def test_legacy_job_result_below_threshold_is_rejected():
    resolved = DataQualityGate.attestation_from_job_result(
        {"fit_for_engine": True, "quality_score": 41.0}, job_id="legacy-2"
    )
    assert resolved is not None
    assert resolved.verified is False
    with pytest.raises(PredictionBlockedError):
        DataQualityGate.require(resolved)


def test_legacy_job_result_without_quality_fields_is_unknown():
    assert DataQualityGate.attestation_from_job_result({}, job_id="legacy-3") is None
    assert DataQualityGate.attestation_from_job_result(None, job_id="legacy-4") is None


def test_prediction_is_blocked_when_no_attestation_exists():
    with pytest.raises(PredictionBlockedError) as excinfo:
        DataQualityGate.require(
            DataQualityGate.attestation_from_job_result({"output_path": "/tmp/x.parquet"})
        )
    assert excinfo.value.code == "PREDICTION_BLOCKED"


# --------------------------------------------------------------------------
# Collector: failures are recorded, never silently flattened
# --------------------------------------------------------------------------

def test_collector_raises_when_every_source_fails():
    from backend.modules.data.collector import DataCollector

    db = _FakeDB([_FakeItem("A", "test_failing"), _FakeItem("B", "test_failing")])
    collector = DataCollector(db, "job-all-fail", output_dir="/tmp")

    with pytest.raises(DataIngestionError) as excinfo:
        collector.collect([1, 2], "2023-01-01", "2023-02-01")

    assert len(excinfo.value.context["failures"]) == 2
    assert collector.last_report is not None
    assert set(collector.last_report.failed) == {"A", "B"}
    assert all(f.error_code == "DATA_SOURCE_UNAVAILABLE" for f in collector.last_report.failures)


def test_collector_returns_partial_success_and_records_failure():
    from backend.modules.data.collector import DataCollector

    db = _FakeDB([_FakeItem("GOOD", "test_good"), _FakeItem("BAD", "test_failing")])
    collector = DataCollector(db, "job-partial", output_dir="/tmp")

    collected = collector.collect([1, 2], "2023-01-01", "2023-02-01")

    assert set(collected) == {"GOOD"}
    assert collector.last_report.failed == ["BAD"]
    assert collector.last_report.success_ratio == pytest.approx(0.5)


def test_collector_treats_empty_frame_as_failure():
    from backend.modules.data.collector import DataCollector

    db = _FakeDB([_FakeItem("EMPTY", "test_empty")])
    collector = DataCollector(db, "job-empty-plugin", output_dir="/tmp")

    with pytest.raises(DataIngestionError):
        collector.collect([1], "2023-01-01", "2023-02-01")

    assert collector.last_report.failures[0].error_code == "EMPTY_DATASET"


def test_collector_strict_mode_fails_on_any_error():
    from backend.modules.data.collector import DataCollector

    db = _FakeDB([_FakeItem("GOOD", "test_good"), _FakeItem("BAD", "test_failing")])
    collector = DataCollector(db, "job-strict", output_dir="/tmp")

    with pytest.raises(DataQualityError):
        collector.collect([1, 2], "2023-01-01", "2023-02-01", fail_on_any_error=True)


def test_collector_unregistered_plugin_is_a_typed_failure():
    from backend.modules.data.collector import DataCollector

    db = _FakeDB([_FakeItem("X", "no_such_plugin")])
    collector = DataCollector(db, "job-noplugin", output_dir="/tmp")

    with pytest.raises(DataIngestionError):
        collector.collect([1], "2023-01-01", "2023-02-01")

    assert collector.last_report.failures[0].error_code == "DATA_SOURCE_UNAVAILABLE"


def test_collector_distinguishes_skipped_from_failed():
    """Missing catalogue items are skipped, not failures, and the error says so."""
    from backend.modules.data.collector import DataCollector

    db = _FakeDB([None, None])
    collector = DataCollector(db, "job-skipped", output_dir="/tmp")

    with pytest.raises(DataIngestionError) as excinfo:
        collector.collect([1, 2], "2023-01-01", "2023-02-01")

    assert "skipped or unmatched" in str(excinfo.value)
    assert collector.last_report.failures == []
    assert len(collector.last_report.skipped) == 2


def test_collector_rejects_an_empty_request():
    from backend.modules.data.collector import DataCollector

    collector = DataCollector(_FakeDB([]), "job-nothing", output_dir="/tmp")
    with pytest.raises(DataIngestionError) as excinfo:
        collector.collect([], "2023-01-01", "2023-02-01")
    assert "No catalogue items were requested" in str(excinfo.value)
