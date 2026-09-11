"""Tests for the BEACON observability stack (workstream F).

These tests are deliberately dependency-light: they must pass with **no live
Redis broker, no Celery workers and no ``prometheus_client`` installed**.  Where
behaviour differs between "prometheus_client installed" and "not installed" the
assertions are guarded on ``backend.monitoring.metrics.PROMETHEUS_AVAILABLE``, so
the same file exercises both the real-metric path and the no-op fallback path.

Run with::

    cd /home/komedi/Denemeler/beacon && \\
        PYTHONPATH=. python -m pytest backend/tests/test_observability.py -v -o addopts=""
"""

from __future__ import annotations

import inspect
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend.monitoring import celery_health, drift, metrics
from backend.monitoring.drift import (
    DEFAULT_THRESHOLDS,
    FeatureDriftMonitor,
    detect_drift,
    jensen_shannon_divergence,
    kolmogorov_cdf,
    kolmogorov_sf,
    kolmogorov_smirnov_statistic,
    population_stability_index,
    psi_severity,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample(name: str, labels: dict | None = None) -> float | None:
    """Read a sample value from the BEACON registry, or ``None`` when disabled.

    Counter names are looked up both verbatim and with an extra ``_total``
    suffix: older ``prometheus_client`` releases append ``_total`` to a counter
    whose name already ends in ``_total``, so accepting both keeps these
    assertions valid across client versions.
    """

    if not metrics.PROMETHEUS_AVAILABLE or metrics.REGISTRY is None:
        return None

    candidates = [name]
    if name.endswith("_total"):
        candidates.append(f"{name}_total")

    for candidate in candidates:
        try:
            value = metrics.REGISTRY.get_sample_value(candidate, labels or {})
        except Exception:  # pragma: no cover - defensive
            value = None
        if value is not None:
            return value
    return None


def _touch_every_metric() -> None:
    """Emit at least one sample for every exported metric."""

    metrics.record_http_request("GET", "/health", 200, 0.012)
    metrics.record_http_request("POST", "/api/v1/pipeline/run", 500, 0.5)
    with metrics.pipeline_job_timer("training", "training"):
        pass
    try:
        with metrics.pipeline_job_timer("inference", "prediction"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    metrics.record_ingestion_attempt("fred", success=True, records=10)
    metrics.record_ingestion_attempt("fred", success=False, error_code="HTTP 500")
    metrics.record_celery_task("backend.tasks.job_tasks.run_training", "started", 1.25)
    metrics.celery_queue_depth.labels(queue="celery").set(3)
    metrics.celery_workers_online.labels(pool="all").set(2)
    metrics.celery_worker_tasks.labels(state="active").set(1)
    metrics.record_inference("gnn-liquidity", duration_seconds=0.42, success=True)
    metrics.record_inference("gnn-liquidity", success=False, error_code="CUDA_OOM")
    metrics.record_prediction("EUROPE", "high", count=2)
    metrics.feature_drift_psi.labels(feature="lcr").set(0.31)


class FakeRedis:
    """Minimal stand-in for ``redis.Redis`` (only the calls queue_depth uses)."""

    def __init__(self, lengths=None, bindings=None, fail=False, priority_keys=None):
        self.lengths = dict(lengths or {})
        self.bindings = list(bindings or [])
        self.priority_keys = list(priority_keys or [])
        self.fail = fail
        self.calls: list[tuple] = []

    def llen(self, key):
        self.calls.append(("llen", key))
        if self.fail:
            raise ConnectionError("redis is down")
        return self.lengths.get(key, 0)

    def smembers(self, key):
        self.calls.append(("smembers", key))
        if self.fail:
            raise ConnectionError("redis is down")
        return self.bindings

    def scan_iter(self, match=None, count=None):
        self.calls.append(("scan_iter", match))
        if self.fail:
            raise ConnectionError("redis is down")
        return iter(self.priority_keys)


class FakeInspect:
    """Minimal stand-in for the object returned by ``celery_app.control.inspect()``."""

    def __init__(self, ping=None, active=None, reserved=None, scheduled=None,
                 active_queues=None, registered=None):
        self._ping = ping
        self._active = active
        self._reserved = reserved
        self._scheduled = scheduled
        self._active_queues = active_queues
        self._registered = registered

    def ping(self):
        return self._ping

    def active(self):
        return self._active

    def reserved(self):
        return self._reserved

    def scheduled(self):
        return self._scheduled

    def active_queues(self):
        return self._active_queues

    def registered(self):
        return self._registered


class FakeControl:
    def __init__(self, inspector=None, raise_on_inspect=False):
        self._inspector = inspector
        self._raise = raise_on_inspect
        self.timeouts: list = []

    def inspect(self, timeout=None):
        self.timeouts.append(timeout)
        if self._raise:
            raise ConnectionError("broker unreachable")
        return self._inspector


class FakeCeleryApp:
    def __init__(self, inspector=None, raise_on_inspect=False):
        self.control = FakeControl(inspector, raise_on_inspect)


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Keep the queue/worker caches and scrape hooks from leaking between tests."""

    celery_health._WORKER_HEALTH_CACHE["value"] = None
    celery_health._WORKER_HEALTH_CACHE["at"] = 0.0
    celery_health._KNOWN_POOLS.clear()
    celery_health._KNOWN_QUEUES_GAUGED.clear()
    celery_health._TASK_START_TIMES.clear()
    metrics.clear_scrape_hooks()
    yield
    metrics.clear_scrape_hooks()
    celery_health._SCRAPE_HOOK_INSTALLED = False


# ===========================================================================
# PSI
# ===========================================================================


def test_psi_is_zero_for_identical_distributions():
    rng = np.random.default_rng(1234)
    sample = rng.normal(0.0, 1.0, 5000)
    assert population_stability_index(sample, sample) == pytest.approx(0.0, abs=1e-12)
    # Same distribution, independently drawn -> tiny PSI, nowhere near the
    # moderate drift band.
    other = rng.normal(0.0, 1.0, 5000)
    assert population_stability_index(sample, other) < DEFAULT_THRESHOLDS["psi_none"]


def test_psi_is_large_for_shifted_distribution():
    rng = np.random.default_rng(99)
    reference = rng.normal(0.0, 1.0, 4000)
    shifted = rng.normal(3.0, 1.0, 4000)
    value = population_stability_index(reference, shifted)
    assert value > DEFAULT_THRESHOLDS["psi_major"]
    assert value == pytest.approx(population_stability_index(reference, shifted))

    # PSI grows with the size of the shift.
    smaller = population_stability_index(reference, rng.normal(0.5, 1.0, 4000))
    larger = population_stability_index(reference, rng.normal(2.0, 1.0, 4000))
    assert smaller < larger < value


def test_psi_handles_zero_width_bins_and_zero_proportions():
    # Constant reference -> quantile bins collapse to zero width.  Both of these
    # would previously produce inf/nan; they must stay finite.
    constant = np.zeros(200)
    assert population_stability_index(constant, constant) == pytest.approx(0.0)

    shifted_constant = population_stability_index(constant, np.ones(200))
    assert np.isfinite(shifted_constant)
    assert shifted_constant > DEFAULT_THRESHOLDS["psi_major"]

    # A discrete feature with a dominant value exercises empty bins.
    discrete = np.concatenate([np.zeros(990), np.ones(10)])
    assert np.isfinite(population_stability_index(discrete, discrete))
    assert np.isfinite(population_stability_index(discrete, np.ones(1000)))


def test_psi_rejects_empty_and_invalid_input():
    with pytest.raises(ValueError):
        population_stability_index([], [1.0, 2.0])
    with pytest.raises(ValueError):
        population_stability_index([1.0, 2.0], [])
    with pytest.raises(ValueError):
        population_stability_index([1.0, 2.0], [1.0, 2.0], buckets=1)
    # All-NaN input collapses to empty.
    with pytest.raises(ValueError):
        population_stability_index([float("nan")] * 10, [1.0, 2.0])


# ===========================================================================
# Kolmogorov-Smirnov
# ===========================================================================


def test_ks_statistic_is_bounded_and_monotonic_under_translation():
    rng = np.random.default_rng(7)
    base = rng.normal(0.0, 1.0, 3000)

    shifts = [0.0, 0.25, 0.5, 1.0, 2.0, 4.0]
    results = [kolmogorov_smirnov_statistic(base, base + shift) for shift in shifts]

    for statistic, p_value in results:
        assert 0.0 <= statistic <= 1.0
        assert 0.0 <= p_value <= 1.0
        assert np.isfinite(statistic) and np.isfinite(p_value)

    statistics = [statistic for statistic, _ in results]
    # Translating the same sample by a growing delta monotonically widens the
    # maximal ECDF gap, so D must be non-decreasing.
    for previous, current in zip(statistics, statistics[1:]):
        assert current >= previous, statistics
    assert statistics[0] == pytest.approx(0.0, abs=1e-12)
    assert statistics[-1] > 0.5


def test_ks_pvalue_sanity():
    rng = np.random.default_rng(2024)
    base = rng.normal(0.0, 1.0, 1500)

    d_same, p_same = kolmogorov_smirnov_statistic(base, base)
    assert d_same == pytest.approx(0.0, abs=1e-12)
    assert p_same == pytest.approx(1.0)

    _, p_close = kolmogorov_smirnov_statistic(base, rng.normal(0.02, 1.0, 1500))
    assert p_close > 0.05  # a negligible shift must not look significant

    _, p_far = kolmogorov_smirnov_statistic(base, base + 5.0)
    assert p_far < 0.001  # a huge shift must be overwhelmingly significant

    with pytest.raises(ValueError):
        kolmogorov_smirnov_statistic([], [1.0])


def test_kolmogorov_distribution_cdf_series():
    assert kolmogorov_cdf(0.0) == 0.0
    assert kolmogorov_cdf(-1.0) == 0.0
    assert kolmogorov_cdf(float("inf")) == 0.0  # non-finite -> guarded
    assert kolmogorov_cdf(6.0) > 0.999
    assert kolmogorov_sf(0.0) == 1.0
    assert kolmogorov_sf(6.0) < 0.001

    # Known asymptotic value: P(K <= 1) = 0.73.
    assert kolmogorov_cdf(1.0) == pytest.approx(0.73, abs=1e-4)

    # Monotone and bounded across both series regimes.
    grid = [0.05, 0.2, 0.4, 0.6, 0.8, 1.0, 1.18, 1.5, 2.0, 3.0, 5.0]
    values = [kolmogorov_cdf(x) for x in grid]
    assert all(0.0 <= value <= 1.0 for value in values)
    assert all(b > a for a, b in zip(values, values[1:])), values

    # The two series are selected around x=1.18; the switch must be continuous.
    # (Compare infinitesimally either side of the switch: the CDF itself has a
    # slope of ~0.58/unit there, so a wider gap would legitimately differ.)
    assert kolmogorov_cdf(1.18 - 1e-9) == pytest.approx(
        kolmogorov_cdf(1.18 + 1e-9), abs=1e-7
    )
    assert kolmogorov_sf(1.18) == pytest.approx(1.0 - kolmogorov_cdf(1.18), abs=1e-12)


# ===========================================================================
# Jensen-Shannon divergence
# ===========================================================================


def test_jensen_shannon_divergence_behaviour():
    rng = np.random.default_rng(31)
    a = rng.normal(0.0, 1.0, 3000)
    b = rng.normal(0.0, 1.0, 3000)
    far = rng.normal(6.0, 1.0, 3000)

    assert jensen_shannon_divergence(a, a) == pytest.approx(0.0, abs=1e-12)
    assert 0.0 <= jensen_shannon_divergence(a, b) < 0.1
    distant = jensen_shannon_divergence(a, far)
    assert distant > 0.5
    assert distant <= 1.0 + 1e-12  # bounded in bits

    # Symmetric.
    assert jensen_shannon_divergence(a, far) == pytest.approx(
        jensen_shannon_divergence(far, a), abs=1e-12
    )
    # nats are smaller than bits for the same pair.
    assert jensen_shannon_divergence(a, far, base=None) < distant


# ===========================================================================
# Severity mapping / drift reports
# ===========================================================================


@pytest.mark.parametrize(
    ("psi", "expected"),
    [
        (0.0, "none"),
        (0.05, "none"),
        (0.099999, "none"),
        (0.1, "moderate"),
        (0.18, "moderate"),
        (0.25, "moderate"),  # the band boundary belongs to moderate
        (0.2500001, "major"),
        (0.5, "major"),
        (12.0, "major"),
    ],
)
def test_psi_severity_threshold_mapping(psi, expected):
    assert psi_severity(psi) == expected


def test_psi_severity_custom_thresholds_and_bad_input():
    stricter = {"psi_none": 0.01, "psi_major": 0.05}
    assert psi_severity(0.02, stricter) == "moderate"
    assert psi_severity(0.06, stricter) == "major"
    assert psi_severity(0.005, stricter) == "none"
    # Non-numeric input must not explode.
    assert psi_severity("not-a-number") == "none"  # type: ignore[arg-type]


def test_detect_drift_report_is_json_serialisable_and_classified():
    rng = np.random.default_rng(5)
    reference = {"lcr": rng.normal(1.0, 0.2, 2000), "nsfr": rng.normal(1.1, 0.1, 2000)}
    stable = detect_drift(reference, reference)
    assert stable["overall"]["verdict"] == "stable"
    assert stable["overall"]["severity"] == "none"
    assert stable["overall"]["drifted_features"] == []
    assert stable["overall"]["n_features"] == 2
    json.dumps(stable)  # must not raise

    drifted = detect_drift(
        reference,
        {"lcr": rng.normal(3.0, 0.2, 2000), "nsfr": rng.normal(1.1, 0.1, 2000)},
    )
    json.dumps(drifted)
    assert drifted["overall"]["verdict"] == "drift"
    assert drifted["overall"]["severity"] == "major"
    assert drifted["overall"]["drifted_features"] == ["lcr"]
    assert drifted["features"]["lcr"]["psi"] > 0.25
    assert drifted["features"]["nsfr"]["psi"] < 0.1
    assert drifted["overall"]["max_psi_feature"] == "lcr"
    assert drifted["features"]["lcr"]["verdict"] == "drift"
    assert drifted["features"]["lcr"]["ks_pvalue"] < 0.05


def test_detect_drift_reports_missing_and_extra_features():
    rng = np.random.default_rng(11)
    reference = {"a": rng.normal(0, 1, 200), "b": rng.normal(0, 1, 200)}
    current = {"a": rng.normal(0, 1, 200), "c": rng.normal(0, 1, 200)}
    report = detect_drift(reference, current)
    assert report["overall"]["missing_in_current"] == ["b"]
    assert report["overall"]["extra_in_current"] == ["c"]
    assert report["overall"]["n_features"] == 1
    json.dumps(report)


def test_detect_drift_updates_prometheus_gauge():
    rng = np.random.default_rng(77)
    reference = {"lcr": rng.normal(0, 1, 1000)}
    detect_drift(reference, {"lcr": rng.normal(4, 1, 1000)})
    value = _sample("beacon_feature_drift_psi", {"feature": "lcr"})
    if metrics.PROMETHEUS_AVAILABLE:
        assert value is not None and value > 0.25


# ===========================================================================
# FeatureDriftMonitor
# ===========================================================================


def test_feature_drift_monitor_json_round_trip():
    rng = np.random.default_rng(4242)
    reference = {
        "lcr": rng.normal(1.0, 0.2, 1500),
        "nsfr": rng.normal(1.1, 0.15, 1500),
        "hqla": rng.lognormal(0.0, 0.5, 1500),
    }
    monitor = FeatureDriftMonitor(buckets=12, name="beacon-test").fit(reference)
    assert monitor.is_fitted
    assert monitor.feature_names == ["hqla", "lcr", "nsfr"]
    assert monitor.reference_size == 4500

    payload = monitor.to_json()
    parsed = json.loads(payload)
    assert parsed["kind"] == "beacon.feature_drift_monitor"
    assert parsed["buckets"] == 12
    assert parsed["name"] == "beacon-test"

    restored = FeatureDriftMonitor.from_json(payload)
    assert restored.feature_names == monitor.feature_names
    assert restored.buckets == monitor.buckets
    assert restored.name == monitor.name
    for feature in monitor.feature_names:
        assert restored.psi(feature, reference[feature]) == pytest.approx(
            monitor.psi(feature, reference[feature]), abs=1e-12
        )

    # A re-serialised monitor is byte-identical for the distribution summary.
    assert json.loads(restored.to_json())["features"] == parsed["features"]

    # Unchanged live data scores as no drift; a shifted feature is flagged.
    stable_report = restored.score(reference)
    assert stable_report["overall"]["verdict"] == "stable"
    json.dumps(stable_report)

    drifted = restored.score({"lcr": rng.normal(5.0, 0.2, 1500)})
    assert drifted["overall"]["verdict"] == "drift"
    assert drifted["overall"]["severity"] == "major"
    assert drifted["features"]["lcr"]["psi"] > 0.25
    assert drifted["features"]["lcr"]["ks_pvalue"] < 0.05
    json.dumps(drifted)


def test_feature_drift_monitor_save_and_load(tmp_path):
    rng = np.random.default_rng(8)
    monitor = FeatureDriftMonitor(buckets=10).fit({"x": rng.normal(0, 1, 400)})
    path = tmp_path / "reference.json"
    written = monitor.save(path)
    assert Path(written).exists()

    loaded = FeatureDriftMonitor.load(path)
    assert loaded.feature_names == ["x"]
    assert loaded.psi("x", rng.normal(0, 1, 400)) < 0.25


def test_feature_drift_monitor_guards_and_degenerate_reference():
    monitor = FeatureDriftMonitor()
    assert not monitor.is_fitted
    with pytest.raises(RuntimeError):
        monitor.score({"x": [1.0, 2.0]})
    with pytest.raises(KeyError):
        monitor.psi("missing", [1.0, 2.0])
    with pytest.raises(ValueError):
        FeatureDriftMonitor(buckets=1)
    with pytest.raises(ValueError):
        FeatureDriftMonitor(max_reference_samples=1)
    with pytest.raises(ValueError):
        FeatureDriftMonitor.from_json('{"schema_version": 999}')

    # Constant reference: bins collapse but scoring must stay finite and detect
    # a genuine level shift.
    constant = FeatureDriftMonitor(buckets=10).fit({"c": np.zeros(100)})
    assert constant.psi("c", np.zeros(100)) == pytest.approx(0.0)
    shifted = constant.psi("c", np.ones(100))
    assert np.isfinite(shifted) and shifted > 0.25


def test_feature_drift_monitor_updates_gauge():
    rng = np.random.default_rng(6)
    monitor = FeatureDriftMonitor().fit({"lcr": rng.normal(0, 1, 500)})
    monitor.score({"lcr": rng.normal(5, 1, 500)})
    value = _sample("beacon_feature_drift_psi", {"feature": "lcr"})
    if metrics.PROMETHEUS_AVAILABLE:
        assert value is not None and value > 0.25


# ===========================================================================
# Celery queue depth (fake Redis)
# ===========================================================================


def test_queue_depth_with_fake_redis_client():
    fake = FakeRedis(lengths={"celery": 7, "training": 3})
    depths = celery_health.queue_depth(
        redis_client=fake, queues=["celery", "training"]
    )
    assert depths == {"celery": 7, "training": 3}
    assert ("llen", "celery") in fake.calls

    value = _sample("beacon_celery_queue_depth", {"queue": "celery"})
    if metrics.PROMETHEUS_AVAILABLE:
        assert value == 7


def test_queue_depth_discovers_queues_from_kombu_bindings_and_priority_steps():
    fake = FakeRedis(
        lengths={"celery": 2, "high_priority": 5, "celery\x06\x163": 1},
        bindings=[
            b"celery\x06\x16celery\x06\x16celery",
            b"high_priority\x06\x16celery\x06\x16high_priority",
        ],
        priority_keys=[b"celery\x06\x163"],
    )
    depths = celery_health.queue_depth(redis_client=fake)
    assert depths["celery"] == 2
    assert depths["high_priority"] == 5
    assert depths["celery\x06\x163"] == 1


def test_queue_depth_uses_monkeypatched_client_factory(monkeypatch):
    fake = FakeRedis(lengths={"celery": 11})
    monkeypatch.setattr(
        celery_health, "_make_redis_client", lambda url, redis_client=None: fake
    )
    monkeypatch.setattr(celery_health, "_configured_queues", lambda: ["celery"])
    assert celery_health.queue_depth() == {"celery": 11}


def test_queue_depth_never_raises_when_redis_is_unavailable(monkeypatch):
    # 1. redis package missing / no client can be created.
    monkeypatch.setattr(celery_health, "REDIS_AVAILABLE", False)
    monkeypatch.setattr(celery_health, "_REDIS_CLIENTS", {})
    assert celery_health.queue_depth(broker_url="redis://127.0.0.1:1/0") == {}

    # 2. A client that raises on every call.
    assert celery_health.queue_depth(redis_client=FakeRedis(fail=True)) == {}

    # 3. A malformed client object (no usable methods at all).
    assert celery_health.queue_depth(redis_client=object()) == {}


def test_queue_depth_removes_stale_gauges(monkeypatch):
    monkeypatch.setattr(celery_health, "_configured_queues", lambda: ["celery"])
    celery_health.queue_depth(redis_client=FakeRedis(lengths={"celery": 4}))
    value = _sample("beacon_celery_queue_depth", {"queue": "celery"})
    if metrics.PROMETHEUS_AVAILABLE:
        assert value == 4


@pytest.mark.skipif(
    not celery_health.REDIS_AVAILABLE,
    reason="redis package not installed; the fallback path is covered separately",
)
def test_queue_depth_returns_empty_for_real_but_dead_broker():
    """Real ``redis`` client, real connection attempt, no server listening.

    Port 1 is not a Redis server, so this exercises the genuine
    connection-refused/timeout path rather than a fake client.
    """

    depths = celery_health.queue_depth(
        broker_url="redis://127.0.0.1:1/0", queues=["celery"]
    )
    assert depths == {}


# ===========================================================================
# Celery worker health
# ===========================================================================


def test_worker_health_degrades_when_inspect_returns_none(monkeypatch):
    monkeypatch.setattr(
        celery_health, "_load_celery_app", lambda: FakeCeleryApp(inspector=None)
    )
    report = celery_health.worker_health(refresh=True, include_queues=False)
    assert report["status"] == "no_workers"
    assert report["live_workers"] == 0
    assert report["active_tasks"] == 0
    assert report["reserved_tasks"] == 0
    assert report["scheduled_tasks"] == 0
    assert report["workers"] == {}
    assert isinstance(report["detail"], str) and report["detail"]
    json.dumps(report)  # JSON-serialisable


def test_worker_health_degrades_when_no_worker_answers(monkeypatch):
    monkeypatch.setattr(
        celery_health,
        "_load_celery_app",
        lambda: FakeCeleryApp(
            FakeInspect(
                ping=None,
                active=None,
                reserved=None,
                scheduled=None,
                active_queues=None,
                registered=None,
            )
        ),
    )
    report = celery_health.worker_health(refresh=True, include_queues=False)
    assert report["status"] == "no_workers"
    assert report["live_workers"] == 0
    json.dumps(report)


def test_worker_health_degrades_when_inspect_raises(monkeypatch):
    monkeypatch.setattr(
        celery_health,
        "_load_celery_app",
        lambda: FakeCeleryApp(raise_on_inspect=True),
    )
    report = celery_health.worker_health(refresh=True, include_queues=False)
    assert report["status"] == "unavailable"
    assert report["live_workers"] == 0
    assert "inspect" in report["detail"]


def test_worker_health_when_celery_is_not_installed(monkeypatch):
    # Force the "no celery" path even if celery happens to be installed.
    monkeypatch.setattr(celery_health, "_load_celery_app", lambda: None)
    monkeypatch.setattr(celery_health, "CELERY_AVAILABLE", False)
    report = celery_health.worker_health(refresh=True, include_queues=False)
    assert report["status"] == "unavailable"
    assert report["celery_available"] is False
    assert report["live_workers"] == 0
    json.dumps(report)


def test_worker_health_reports_counts_and_alive_training_pool(monkeypatch):
    inspector = FakeInspect(
        ping={"celery@training-1": {"ok": "pong"}, "celery@api-1": {"ok": "pong"}},
        active={"celery@training-1": [{}, {}], "celery@api-1": []},
        reserved={"celery@training-1": [{}], "celery@api-1": []},
        scheduled={"celery@training-1": [], "celery@api-1": [{}]},
        active_queues={
            "celery@training-1": [{"name": "training"}],
            "celery@api-1": [{"name": "celery"}],
        },
        registered={
            "celery@training-1": ["backend.tasks.job_tasks.run_training"],
            "celery@api-1": ["dispatch_job"],
        },
    )
    monkeypatch.setattr(
        celery_health, "_load_celery_app", lambda: FakeCeleryApp(inspector)
    )
    monkeypatch.setenv("BEACON_EXPECTED_TRAINING_WORKERS", "1")

    # Pools are configuration-driven; a dedicated training pool is declared here.
    pools = {"default": ("celery",), "training": ("training", "train", "gpu")}
    report = celery_health.worker_health(
        expected=pools, refresh=True, include_queues=False
    )
    assert report["status"] == "healthy"
    assert report["live_workers"] == 2
    assert report["active_tasks"] == 2
    assert report["reserved_tasks"] == 1
    assert report["scheduled_tasks"] == 1
    assert report["training_workers_live"] == 1
    assert report["training_pool"]["status"] == "healthy"
    assert report["workers"]["celery@training-1"]["pool"] == "training"
    assert report["workers"]["celery@api-1"]["pool"] == "default"
    assert report["workers"]["celery@training-1"]["active"] == 2
    assert report["pools"]["default"]["live_workers"] == 1
    assert report["pools"]["training"]["live_workers"] == 1
    json.dumps(report)

    value = _sample("beacon_celery_workers_online", {"pool": "all"})
    if metrics.PROMETHEUS_AVAILABLE:
        assert value == 2
        assert _sample("beacon_celery_workers_online", {"pool": "training"}) == 1
        assert _sample("beacon_celery_workers_online", {"pool": "default"}) == 1


def test_dead_training_pool_is_visible(monkeypatch):
    """A crashed PyTorch training pool must show up while other workers live on."""

    inspector = FakeInspect(
        ping={"celery@api-1": {"ok": "pong"}},
        active={"celery@api-1": []},
        reserved={"celery@api-1": []},
        scheduled={"celery@api-1": []},
        active_queues={"celery@api-1": [{"name": "celery"}]},
        registered={"celery@api-1": ["dispatch_job"]},
    )
    monkeypatch.setattr(
        celery_health, "_load_celery_app", lambda: FakeCeleryApp(inspector)
    )
    monkeypatch.setenv("BEACON_EXPECTED_TRAINING_WORKERS", "2")

    report = celery_health.worker_health(refresh=True, include_queues=False)
    assert report["live_workers"] == 1
    assert report["training_workers_live"] == 0
    assert report["training_pool"]["status"] == "dead"
    assert report["training_pool"]["expected_workers"] == 2
    assert report["status"] == "degraded"
    assert "training" in report["detail"]

    training_gauge = _sample("beacon_celery_workers_online", {"pool": "training"})
    expected_gauge = _sample("beacon_celery_workers_online", {"pool": "training_expected"})
    if metrics.PROMETHEUS_AVAILABLE:
        assert training_gauge == 0
        assert expected_gauge == 2


def test_worker_health_survives_garbage_inspect_payload(monkeypatch):
    class GarbageInspect:
        def ping(self):
            return "not-a-dict"

        def active(self):
            return 42

        def reserved(self):
            raise RuntimeError("nope")

        def scheduled(self):
            return {"celery@x": None}

        def active_queues(self):
            return {"celery@x": [{}]}

        def registered(self):
            return None

    monkeypatch.setattr(
        celery_health, "_load_celery_app", lambda: FakeCeleryApp(GarbageInspect())
    )
    report = celery_health.worker_health(refresh=True, include_queues=False)
    assert isinstance(report, dict)
    json.dumps(report)


def test_worker_health_is_cached_and_refreshable(monkeypatch):
    calls = {"n": 0}

    def _app():
        calls["n"] += 1
        return FakeCeleryApp(inspector=None)

    monkeypatch.setattr(celery_health, "_load_celery_app", _app)
    celery_health.worker_health(refresh=True, include_queues=False)
    first = calls["n"]
    celery_health.worker_health(use_cache=True, include_queues=False)
    assert calls["n"] == first  # served from cache
    celery_health.worker_health(refresh=True, include_queues=False)
    assert calls["n"] == first + 1


# ===========================================================================
# Celery signals
# ===========================================================================


def test_register_celery_signals_is_safe():
    assert celery_health.register_celery_signals(None) is False
    assert isinstance(celery_health.register_celery_signals(object()), bool)


def test_signal_handlers_update_counters_and_durations():
    task = SimpleNamespace(name="backend.tasks.job_tasks.run_training")
    kwargs = {"job_type": "training"}

    before_started = _sample(
        "beacon_celery_tasks_total",
        {"task_name": task.name, "status": "started"},
    ) or 0.0
    before_completed = _sample(
        "beacon_celery_tasks_total",
        {"task_name": task.name, "status": "completed"},
    ) or 0.0
    before_failed = _sample(
        "beacon_celery_tasks_total",
        {"task_name": task.name, "status": "failed"},
    ) or 0.0
    before_pipeline_completed = _sample(
        "beacon_pipeline_jobs_completed_total",
        {"stage": "training", "job_type": "training"},
    ) or 0.0

    celery_health._on_task_prerun(task=task, task_id="task-1", args=(), kwargs=kwargs)
    assert "task-1" in celery_health._TASK_START_TIMES
    celery_health._on_task_postrun(task=task, task_id="task-1", args=(), kwargs=kwargs)
    assert "task-1" not in celery_health._TASK_START_TIMES

    celery_health._on_task_prerun(task=task, task_id="task-2", args=(), kwargs=kwargs)
    celery_health._on_task_failure(
        task=task, task_id="task-2", args=(), kwargs=kwargs, exception=ValueError("x")
    )
    assert "task-2" not in celery_health._TASK_START_TIMES

    # A postrun without a matching prerun must not fabricate a duration.
    celery_health._on_task_postrun(task=task, task_id="orphan", args=(), kwargs=kwargs)

    if metrics.PROMETHEUS_AVAILABLE:
        assert _sample(
            "beacon_celery_tasks_total",
            {"task_name": task.name, "status": "started"},
        ) == before_started + 2
        assert _sample(
            "beacon_celery_tasks_total",
            {"task_name": task.name, "status": "completed"},
        ) == before_completed + 2
        assert _sample(
            "beacon_celery_tasks_total",
            {"task_name": task.name, "status": "failed"},
        ) == before_failed + 1
        assert _sample(
            "beacon_pipeline_jobs_completed_total",
            {"stage": "training", "job_type": "training"},
        ) == before_pipeline_completed + 2
        assert _sample(
            "beacon_celery_task_duration_seconds_count", {"task_name": task.name}
        ) == 2  # task-1 + task-2; the orphan postrun has no start time


def test_signal_handlers_derive_job_type_from_task_name():
    task = SimpleNamespace(name="backend.tasks.job_tasks.run_prediction")
    celery_health._on_task_prerun(task=task, task_id="p1", args=(1, {}), kwargs={})
    celery_health._on_task_postrun(task=task, task_id="p1", args=(1, {}), kwargs={})
    if metrics.PROMETHEUS_AVAILABLE:
        assert _sample(
            "beacon_pipeline_jobs_started_total",
            {"stage": "inference", "job_type": "prediction"},
        )
        assert _sample(
            "beacon_pipeline_jobs_completed_total",
            {"stage": "inference", "job_type": "prediction"},
        )


def test_signal_handlers_tolerate_missing_task_and_labels():
    # Must not raise for anonymous/unknown tasks.
    celery_health._on_task_prerun(task=None, task_id=None, args=None, kwargs=None)
    celery_health._on_task_postrun(task=None, task_id="unknown", args=None, kwargs=None)
    celery_health._on_task_failure(task=None, task_id=None, exception=None)


def test_install_scrape_hooks_respects_env(monkeypatch):
    monkeypatch.setenv("BEACON_CELERY_METRICS_AT_SCRAPE", "0")
    celery_health._SCRAPE_HOOK_INSTALLED = False
    assert celery_health.install_scrape_hooks() is False

    monkeypatch.setenv("BEACON_CELERY_METRICS_AT_SCRAPE", "1")
    assert celery_health.install_scrape_hooks() is True
    assert celery_health.install_scrape_hooks() is True  # idempotent

    # The installed hook must be safe to run even with no broker/workers.
    celery_health.refresh_celery_gauges()


# ===========================================================================
# Metrics module: names, helpers, HTTP wiring, fallback
# ===========================================================================


def test_metrics_module_contract_and_helpers():
    assert hasattr(metrics, "METRIC_NAMES") and len(metrics.METRIC_NAMES) >= 15
    for name in metrics.METRIC_NAMES:
        assert name.startswith("beacon_")

    _touch_every_metric()

    # HTTP helper
    assert metrics.record_http_request("GET", "/health", 200, 0.01) is None

    # Pipeline context manager records a failure when the body raises.
    with pytest.raises(RuntimeError):
        with metrics.pipeline_job_timer("backtest", "backtest"):
            raise RuntimeError("boom")

    # Unknown labels are tolerated (no exception).
    metrics.record_ingestion_failure(plugin_type="", error_code="")
    metrics.record_prediction("", "", count=0)


def test_record_ingestion_failure_public_signature():
    """Locks the interface requested by the data-ingestion workstream."""

    parameters = list(inspect.signature(metrics.record_ingestion_failure).parameters)
    assert parameters == ["plugin_type", "error_code"]

    metrics.record_ingestion_failure(plugin_type="fred", error_code="HTTP 500")
    metrics.record_ingestion_failure("fred", "HTTP 500")
    if metrics.PROMETHEUS_AVAILABLE:
        assert _sample(
            "beacon_data_ingestion_failures_total",
            {"plugin": "fred", "error_code": "HTTP 500"},
        ) >= 2


def test_scrape_hooks_run_and_never_break_exposition():
    calls: list[str] = []
    metrics.register_scrape_hook(lambda: calls.append("good"))
    metrics.register_scrape_hook(lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    payload = metrics.render_metrics()
    assert calls == ["good"]
    assert isinstance(payload, bytes)
    metrics.clear_scrape_hooks()


def test_metrics_endpoint_returns_a_200_response():
    response = metrics.metrics_endpoint()
    assert response.status_code == 200
    assert isinstance(response.body, bytes)
    assert response.body


def test_setup_metrics_is_safe_without_fastapi():
    # `setup_metrics(None)` must be a no-op and must not raise.
    assert metrics.setup_metrics(None) is None

    class RecordingApp:
        def __init__(self):
            self.routes: list = []
            self.middleware: list = []
            self.get_calls: list[dict] = []

        def add_middleware(self, middleware_class, **kwargs):
            self.middleware.append(middleware_class)

        def get(self, path, **kwargs):
            self.get_calls.append({"path": path, **kwargs})

            def _decorator(func):
                self.routes.append(SimpleNamespace(path=path, endpoint=func))
                return func

            return _decorator

    app = RecordingApp()
    metrics.setup_metrics(app)
    assert app.get_calls and app.get_calls[0]["path"] == "/metrics"
    assert app.get_calls[0].get("include_in_schema") is False

    # Calling it twice must not register the route twice.
    metrics.setup_metrics(app)
    assert len([c for c in app.get_calls if c["path"] == "/metrics"]) == 1


def test_normalise_path_collapses_ids():
    assert metrics._normalise_path("/api/v1/jobs/12345") == "/api/v1/jobs/:id"
    assert (
        metrics._normalise_path("/api/v1/assets/550e8400-e29b-41d4-a716-446655440000")
        == "/api/v1/assets/:id"
    )
    assert metrics._normalise_path("/api/v1/catalogue") == "/api/v1/catalogue"


def test_metric_names_are_exposed():
    """In the current environment, assert the correct branch of the contract."""

    _touch_every_metric()
    payload = metrics.render_metrics()

    if metrics.PROMETHEUS_AVAILABLE:
        for name in metrics.METRIC_NAMES:
            assert name.encode() in payload, f"{name} missing from exposition"
        assert b"# TYPE" in payload
    else:
        assert payload == metrics.DISABLED_NOTICE
        assert b"prometheus_client is not installed" in payload
        # No-op shims accept the full API surface without raising.
        metrics.http_requests_total.labels(method="GET", route="/", status="200").inc()
        metrics.celery_queue_depth.labels(queue="celery").set(9)
        metrics.pipeline_job_duration_seconds.labels(
            stage="training", job_type="training"
        ).observe(1.0)
        metrics.feature_drift_psi.labels(feature="x").remove()


def test_metrics_module_noops_without_prometheus_client_in_subprocess():
    """Simulate a missing ``prometheus_client`` in a clean interpreter.

    Setting ``sys.modules['prometheus_client'] = None`` makes ``import`` raise
    ``ImportError``, which exercises the fallback path even in an environment
    where the package *is* installed.  Running in a subprocess keeps the real
    module state (and the real registry) untouched.
    """

    script = textwrap.dedent(
        f"""
        import sys

        # Simulate the dependency being absent.
        sys.modules["prometheus_client"] = None
        for _name in list(sys.modules):
            if _name.startswith("prometheus_client."):
                sys.modules[_name] = None

        sys.path.insert(0, {str(REPO_ROOT)!r})

        from backend.monitoring import metrics

        assert metrics.PROMETHEUS_AVAILABLE is False, "fallback did not engage"
        assert metrics.MULTIPROCESS_ENABLED is False

        # Every recording helper must be a silent no-op.
        metrics.http_requests_total.labels(method="GET", route="/", status="200").inc()
        metrics.record_http_request("GET", "/health", 200, 0.01)
        with metrics.pipeline_job_timer("training", "training"):
            pass
        metrics.record_ingestion_failure(plugin_type="fred", error_code="HTTP 500")
        metrics.record_ingestion_attempt("fred", success=False, error_code="X")
        metrics.record_celery_task("t", "failed", 2.0)
        metrics.celery_queue_depth.labels(queue="celery").set(5)
        metrics.record_inference("m", 0.1, success=False, error_code="E")
        metrics.record_prediction("EUROPE", "high", count=3)

        payload = metrics.render_metrics()
        assert isinstance(payload, bytes)
        assert b"prometheus_client is not installed" in payload

        response = metrics.metrics_endpoint()
        assert response.status_code == 200
        assert b"disabled" in response.body

        # The drift module must work and its gauge must be a no-op shim.
        from backend.monitoring import drift
        assert drift.population_stability_index([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 0.0
        d, p = drift.kolmogorov_smirnov_statistic([1, 2, 3, 4], [1, 2, 3, 4])
        assert d == 0.0 and p == 1.0
        drift.feature_drift_psi_gauge.labels(feature="x").set(0.3)
        report = drift.detect_drift({{"f": [1.0, 2.0, 3.0]}}, {{"f": [1.0, 2.0, 9.0]}})
        assert "overall" in report

        # Celery health must degrade, not explode, without redis/celery.
        from backend.monitoring import celery_health
        assert celery_health.queue_depth() == {{}}
        status = celery_health.worker_health(refresh=True)["status"]
        assert status in {{"no_workers", "unavailable", "degraded"}}, status
        assert celery_health.register_celery_signals(None) is False

        print("FALLBACK_OK")
        """
    )

    process = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
        env={"PYTHONPATH": str(REPO_ROOT), "PATH": "/usr/bin:/bin"},
    )
    assert process.returncode == 0, f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}"
    assert "FALLBACK_OK" in process.stdout
