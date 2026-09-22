"""Unit tests for the unified plugin HTTP resilience layer.

These run without a network, without pandas/torch, and without pytest being
mandatory: ``http_client`` is loaded straight from its file path so the test
never triggers ``backend.plugins.__init__`` (which imports pandas-heavy
plugins). Run either with ``pytest`` or directly::

    python backend/tests/test_plugin_http_client.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional

import requests

# --- load http_client.py by path (self-contained: stdlib + requests only) ----
_HERE = os.path.dirname(os.path.abspath(__file__))
_HTTP_PATH = os.path.normpath(os.path.join(_HERE, "..", "plugins", "http_client.py"))
_spec = importlib.util.spec_from_file_location("beacon_http_client", _HTTP_PATH)
http_client = importlib.util.module_from_spec(_spec)
sys.modules["beacon_http_client"] = http_client
_spec.loader.exec_module(http_client)  # type: ignore[union-attr]

ResilientSession = http_client.ResilientSession
retry_call = http_client.retry_call
_TTLCache = http_client._TTLCache
_RateLimiter = http_client._RateLimiter


# --- test doubles -----------------------------------------------------------
def _make_response(status_code: int = 200, payload: Any = None, text: Optional[str] = None) -> requests.Response:
    r = requests.Response()
    r.status_code = status_code
    r.url = "https://example.test/data"
    body = text if text is not None else json.dumps(payload if payload is not None else {"ok": True})
    r._content = body.encode("utf-8")
    r.headers["Content-Type"] = "application/json"
    return r


class FakeSession:
    """Mimics the slice of requests.Session that ResilientSession uses."""

    def __init__(self, responder: Callable[[str, str, Dict[str, Any]], requests.Response]):
        self.headers: Dict[str, str] = {}
        self.mounted: Dict[str, Any] = {}
        self.calls: List[Dict[str, Any]] = []
        self._responder = responder
        self.closed = False

    def mount(self, prefix: str, adapter: Any) -> None:
        self.mounted[prefix] = adapter

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self._responder(method, url, kwargs)

    def close(self) -> None:
        self.closed = True


class _SleepCounter:
    """Context manager that replaces http_client.time.sleep with a counter."""

    def __init__(self) -> None:
        self.calls: List[float] = []
        self._orig: Optional[Callable[[float], None]] = None

    def __enter__(self) -> "_SleepCounter":
        self._orig = http_client.time.sleep
        http_client.time.sleep = lambda s: self.calls.append(s)  # type: ignore[assignment]
        return self

    def __exit__(self, *exc: Any) -> None:
        http_client.time.sleep = self._orig  # type: ignore[assignment]


# --- _TTLCache --------------------------------------------------------------
def test_cache_fresh_then_stale() -> None:
    cache = _TTLCache(max_entries=8, ttl=0.05)
    cache.set("k", "v")
    assert cache.get_fresh("k") == "v"
    assert cache.get_any("k") == "v"
    time.sleep(0.06)
    assert cache.get_fresh("k") is None, "expired entry must not be fresh"
    assert cache.get_any("k") == "v", "expired entry must survive for fallback"


def test_cache_bounded_eviction() -> None:
    cache = _TTLCache(max_entries=3, ttl=60)
    for i in range(6):
        cache.set(i, i)
    assert len(cache) == 3, "cache must evict beyond max_entries"
    assert cache.get_fresh(0) is None, "oldest entries evicted first (LRU)"
    assert cache.get_fresh(5) == 5


def test_cache_disabled_when_ttl_zero() -> None:
    cache = _TTLCache(max_entries=8, ttl=0)
    cache.set("k", "v")
    assert cache.get_fresh("k") is None
    assert len(cache) == 0, "ttl<=0 means nothing is stored"


# --- _RateLimiter -----------------------------------------------------------
def test_rate_limiter_enforces_min_interval() -> None:
    limiter = _RateLimiter(min_interval=1.0)
    with _SleepCounter() as sleeps:
        limiter.wait("host")  # first: no prior timestamp -> no sleep
        limiter.wait("host")  # second: elapsed ~0 -> must sleep ~min_interval
    assert len(sleeps.calls) == 1, "second wait to the same host must throttle"
    assert 0 < sleeps.calls[0] <= 1.0


def test_rate_limiter_disabled_when_zero() -> None:
    limiter = _RateLimiter(min_interval=0)
    with _SleepCounter() as sleeps:
        limiter.wait("host")
        limiter.wait("host")
    assert sleeps.calls == []


# --- retry_call -------------------------------------------------------------
def test_retry_call_succeeds_after_transient_failures() -> None:
    attempts = {"n": 0}

    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionError("boom")
        return "ok"

    with _SleepCounter() as sleeps:
        result = retry_call(flaky, retries=4, backoff_factor=0.5)
    assert result == "ok"
    assert attempts["n"] == 3
    # exponential backoff: 0.5, 1.0 (capped growth), two sleeps before success
    assert sleeps.calls == [0.5, 1.0]


def test_retry_call_raises_after_exhaustion() -> None:
    def always_fail() -> None:
        raise ValueError("nope")

    raised = False
    with _SleepCounter():
        try:
            retry_call(always_fail, retries=2, backoff_factor=0.1)
        except ValueError:
            raised = True
    assert raised, "must re-raise once retries are exhausted"


def test_retry_call_respects_max_backoff_cap() -> None:
    attempts = {"n": 0}

    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] <= 4:
            raise RuntimeError("x")
        return "done"

    with _SleepCounter() as sleeps:
        retry_call(flaky, retries=5, backoff_factor=1.0, max_backoff=3.0)
    # 1, 2, 3, 3(capped) for the four failed attempts
    assert sleeps.calls == [1.0, 2.0, 3.0, 3.0]


# --- ResilientSession -------------------------------------------------------
def test_session_configures_urllib3_retry() -> None:
    sess = ResilientSession(retries=5, backoff_factor=1.5, status_forcelist=(429, 503))
    adapter = sess._session.get_adapter("https://example.test")
    retry = adapter.max_retries
    assert retry.total == 5
    assert retry.backoff_factor == 1.5
    assert set(retry.status_forcelist) == {429, 503}
    assert retry.respect_retry_after_header is True


def test_session_caches_fresh_get() -> None:
    responder = lambda m, u, k: _make_response(200, {"v": 1})  # noqa: E731
    fake = FakeSession(responder)
    sess = ResilientSession(session=fake, cache_ttl=60)

    a = sess.get("https://example.test/data", params={"q": "x"})
    b = sess.get("https://example.test/data", params={"q": "x"})
    assert a is b, "fresh cache hit returns the identical response object"
    assert len(fake.calls) == 1, "second identical GET must not hit transport"
    assert a.json() == {"v": 1}


def test_session_distinct_params_not_confused() -> None:
    fake = FakeSession(lambda m, u, k: _make_response(200, {"p": k.get("params")}))
    sess = ResilientSession(session=fake, cache_ttl=60)
    sess.get("https://example.test/data", params={"q": "x"})
    sess.get("https://example.test/data", params={"q": "y"})
    assert len(fake.calls) == 2, "different params are different cache keys"


def test_session_stale_fallback_on_transport_error() -> None:
    state = {"fail": False}

    def responder(m, u, k):
        if state["fail"]:
            raise requests.exceptions.ConnectionError("upstream down")
        return _make_response(200, {"v": "good"})

    fake = FakeSession(responder)
    sess = ResilientSession(session=fake, cache_ttl=0.01)
    first = sess.get("https://example.test/data")
    assert first.json() == {"v": "good"}

    time.sleep(0.02)  # let it go stale
    state["fail"] = True
    fallback = sess.get("https://example.test/data")
    assert fallback.json() == {"v": "good"}, "stale cache must ride out the outage"
    assert fallback is first


def test_session_raises_when_no_cache_and_error() -> None:
    def responder(m, u, k):
        raise requests.exceptions.ConnectionError("down")

    fake = FakeSession(responder)
    sess = ResilientSession(session=fake, cache_ttl=0)  # caching disabled
    raised = False
    try:
        sess.get("https://example.test/data")
    except requests.exceptions.ConnectionError:
        raised = True
    assert raised, "with no cache, a hard failure must propagate"


def test_session_stale_fallback_on_persistent_5xx() -> None:
    state = {"fail": False}

    def responder(m, u, k):
        if state["fail"]:
            return _make_response(503, {"error": "unavailable"})
        return _make_response(200, {"v": "good"})

    fake = FakeSession(responder)
    sess = ResilientSession(session=fake, cache_ttl=0.01)
    sess.get("https://example.test/data")
    time.sleep(0.02)
    state["fail"] = True
    out = sess.get("https://example.test/data")
    assert out.status_code == 200, "stale 200 preferred over a fresh 503"
    assert out.json() == {"v": "good"}


def test_stale_fallback_is_counted_and_tagged() -> None:
    """A degraded fetch must be witnessable (pipeline-review finding F9).

    The counter is what the collector reads (plugins hand back DataFrames,
    never responses); the header is what any other consumer can see. A
    fresh fetch carries neither.
    """
    state = {"fail": False}

    def responder(m, u, k):
        if state["fail"]:
            raise requests.exceptions.ConnectionError("upstream down")
        return _make_response(200, {"v": "good"})

    fake = FakeSession(responder)
    sess = ResilientSession(session=fake, cache_ttl=0.01)
    first = sess.get("https://example.test/data")
    assert sess.stale_fallback_hits == 0
    assert "X-Beacon-Stale-Fallback" not in first.headers

    time.sleep(0.02)  # let it go stale
    state["fail"] = True
    fallback = sess.get("https://example.test/data")
    assert fallback.json() == {"v": "good"}
    assert sess.stale_fallback_hits == 1
    assert fallback.headers["X-Beacon-Stale-Fallback"] == "1"

    # a second degraded fetch keeps counting
    sess.get("https://example.test/data")
    assert sess.stale_fallback_hits == 2


def test_stale_fallback_on_5xx_is_counted_too() -> None:
    state = {"fail": False}

    def responder(m, u, k):
        if state["fail"]:
            return _make_response(503, {"error": "unavailable"})
        return _make_response(200, {"v": "good"})

    fake = FakeSession(responder)
    sess = ResilientSession(session=fake, cache_ttl=0.01)
    sess.get("https://example.test/data")
    time.sleep(0.02)
    state["fail"] = True
    out = sess.get("https://example.test/data")
    assert out.status_code == 200
    assert sess.stale_fallback_hits == 1
    assert out.headers["X-Beacon-Stale-Fallback"] == "1"


def test_session_does_not_cache_errors() -> None:
    fake = FakeSession(lambda m, u, k: _make_response(404, {"e": 1}))
    sess = ResilientSession(session=fake, cache_ttl=60)
    sess.get("https://example.test/missing")
    sess.get("https://example.test/missing")
    assert len(fake.calls) == 2, "4xx must not be cached"


def test_session_rate_limits_per_host() -> None:
    fake = FakeSession(lambda m, u, k: _make_response(200, {}))
    sess = ResilientSession(session=fake, cache_ttl=0, min_interval=2.0)
    with _SleepCounter() as sleeps:
        sess.get("https://a.test/x")
        sess.get("https://a.test/y")
        sess.get("https://b.test/z")  # different host -> independent limiter
    assert len(sleeps.calls) == 1, "only the 2nd call to host a.test should throttle"


def test_get_json_and_text_helpers() -> None:
    fake = FakeSession(lambda m, u, k: _make_response(200, {"hello": "world"}))
    sess = ResilientSession(session=fake, cache_ttl=0)
    assert sess.get_json("https://example.test/data") == {"hello": "world"}
    fake2 = FakeSession(lambda m, u, k: _make_response(200, text="plain"))
    sess2 = ResilientSession(session=fake2, cache_ttl=0)
    assert sess2.get_text("https://example.test/data") == "plain"


# --- runner -----------------------------------------------------------------
def _run_all() -> int:
    tests = [(n, o) for n, o in sorted(globals().items()) if n.startswith("test_") and callable(o)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed, {passed + failed} total")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
