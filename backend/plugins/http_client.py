"""Unified resilient HTTP layer for data-source plugins.

Every ingestion plugin used to hand-roll its own ``requests.get(...)`` with
inconsistent handling: some slept a fixed interval, some caught ``Timeout``,
none retried a 5xx or a 429, and none cached. The result is that a single
transient upstream blip -- a rate-limit response, a 502 from a statistics
portal, a dropped connection -- failed an entire collection job.

This module centralises that concern. It depends only on :mod:`requests`,
:mod:`urllib3` and the standard library -- never on pandas/torch -- so it stays
cheap to import and trivial to unit-test in isolation.

It provides three things:

* :class:`ResilientSession` -- a drop-in wrapper around ``requests.Session``
  that adds, in one place:

  - **Exponential backoff retries** via ``urllib3.util.retry.Retry`` on
    connection errors, read timeouts and a configurable status force-list
    (429/5xx by default), honouring the server's ``Retry-After`` header when
    present.
  - **A bounded TTL response cache** (fresh hits avoid redundant calls within a
    job) that *also* keeps stale entries for **graceful degradation**: when a
    request ultimately fails after all retries, the last known-good response is
    returned instead of raising, so a downstream API outage degrades a pipeline
    to "slightly old data" rather than "job failed".
  - **Per-host minimum-interval rate limiting** so a plugin that declares a
    ``rate_limit`` cannot exceed a source's published cadence.

* :func:`retry_call` -- the same exponential-backoff policy for plugins that
  wrap a third-party SDK (``yfinance``, ``sec_api``) instead of raw HTTP, where
  the retry has to live around the opaque library call.

* :func:`get_session` -- a small per-host shared-session cache so plugins that
  talk to the same origin reuse one connection pool and one cache.

Design notes
------------
The stale-fallback is deliberately opt-in via ``cache_ttl > 0`` and only ever
returns a response that was previously a success (``status_code < 400``), so it
can never resurrect an error page. It is a *fallback*, not a lie: callers still
see a normal ``requests.Response``, the event is logged at WARNING, the response
carries ``X-Beacon-Stale-Fallback: 1``, and the session's public
``stale_fallback_hits`` counter lets the collector mark the item degraded --
so a cache-served "success" never clears a source's failure backoff unseen.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, Hashable, Optional, Tuple
from urllib.parse import urlencode, urlsplit

import requests
from requests.adapters import HTTPAdapter

try:  # urllib3 >= 1.26 (and 2.x) expose Retry here
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover - very old urllib3 vendored in requests
    from requests.packages.urllib3.util.retry import Retry  # type: ignore

logger = logging.getLogger(__name__)

__all__ = [
    "ResilientSession",
    "retry_call",
    "get_session",
    "DEFAULT_TIMEOUT",
    "DEFAULT_RETRIES",
    "DEFAULT_BACKOFF_FACTOR",
    "DEFAULT_STATUS_FORCELIST",
]

#: Defaults tuned for public statistical / market APIs that publish rate limits.
DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRIES = 4
#: urllib3 sleeps ``backoff_factor * (2 ** (attempt - 1))`` between retries, so
#: 0.8 yields ~0.8s, 1.6s, 3.2s, 6.4s -- enough to ride out a short outage
#: without stalling a collection job for minutes.
DEFAULT_BACKOFF_FACTOR = 0.8
DEFAULT_STATUS_FORCELIST = (429, 500, 502, 503, 504)
DEFAULT_ALLOWED_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
DEFAULT_CACHE_TTL = 300.0
DEFAULT_CACHE_MAX_ENTRIES = 256


class _TTLCache:
    """Bounded, thread-safe TTL cache that retains stale entries for fallback.

    Entries carry an expiry timestamp. :meth:`get_fresh` returns a value only
    while it is unexpired; :meth:`get_any` returns the most recent value even if
    expired (used for graceful degradation). Expired entries are still evicted
    when the cache exceeds ``max_entries`` so memory stays bounded.
    """

    def __init__(self, max_entries: int = DEFAULT_CACHE_MAX_ENTRIES, ttl: float = DEFAULT_CACHE_TTL):
        self._max = max(0, int(max_entries))
        self._ttl = float(ttl)
        self._data: "OrderedDict[Hashable, Tuple[float, Any]]" = OrderedDict()
        self._lock = threading.Lock()

    @property
    def ttl(self) -> float:
        return self._ttl

    def get_fresh(self, key: Hashable) -> Optional[Any]:
        if self._ttl <= 0:
            return None
        now = time.monotonic()
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at <= now:
                return None
            self._data.move_to_end(key)
            return value

    def get_any(self, key: Hashable) -> Optional[Any]:
        """Return the cached value even if stale (for outage fallback)."""
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            self._data.move_to_end(key)
            return item[1]

    def set(self, key: Hashable, value: Any) -> None:
        if self._max <= 0 or self._ttl <= 0:
            # ttl<=0 means "caching disabled": store nothing, so neither the
            # fresh path nor the stale fallback can ever return an entry.
            return
        with self._lock:
            self._data[key] = (time.monotonic() + self._ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:  # pragma: no cover - convenience for tests
        with self._lock:
            return len(self._data)


class _RateLimiter:
    """Per-key minimum-interval throttle (a token bucket of depth one).

    ``min_interval <= 0`` disables it entirely, so the fast path costs nothing.
    """

    def __init__(self, min_interval: float = 0.0):
        self._min_interval = float(min_interval)
        self._last: Dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, key: str) -> None:
        if self._min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            last = self._last.get(key)
            if last is not None:
                delay = self._min_interval - (now - last)
                if delay > 0:
                    time.sleep(delay)
                    now = time.monotonic()
            self._last[key] = now


def _host_of(url: str) -> str:
    return urlsplit(url).netloc or url


class ResilientSession:
    """A ``requests.Session`` with unified backoff, caching and rate limiting.

    Parameters
    ----------
    timeout:
        Default per-request timeout in seconds (overridable per call).
    retries / backoff_factor / status_forcelist:
        Passed to :class:`urllib3.util.retry.Retry` for HTTP-level exponential
        backoff. ``Retry-After`` is always respected.
    cache_ttl:
        Seconds a successful response stays *fresh*. ``0`` disables caching (and
        therefore the stale fallback). Fresh hits short-circuit the network.
    cache_max_entries:
        Hard bound on cache size (LRU eviction) so a long-lived worker cannot
        grow without limit.
    min_interval:
        Minimum seconds between requests to the same host (rate limiting).
    user_agent:
        Sent on every request; several public APIs (BIS, SEC) require one.
    """

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
        status_forcelist: Tuple[int, ...] = DEFAULT_STATUS_FORCELIST,
        cache_ttl: float = DEFAULT_CACHE_TTL,
        cache_max_entries: int = DEFAULT_CACHE_MAX_ENTRIES,
        min_interval: float = 0.0,
        user_agent: str = "BEACON/2.0 (+https://github.com/bnelabs/beacon)",
        session: Optional[requests.Session] = None,
    ):
        self.timeout = float(timeout)
        self._cache = _TTLCache(max_entries=cache_max_entries, ttl=cache_ttl)
        self._limiter = _RateLimiter(min_interval)
        self._session = session or requests.Session()
        #: How many times this session served a STALE cached response because
        #: the live request ultimately failed. A stale-served fetch delivered
        #: data but is not evidence the provider is reachable, so the counter
        #: is public: the collector reads it to mark the item degraded, and
        #: source telemetry keeps the failure streak (and its backoff) alive
        #: across a degraded "success" (pipeline-review finding F9).
        self.stale_fallback_hits = 0

        retry = self._build_retry(retries, backoff_factor, status_forcelist)
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self._session.headers.update({"User-Agent": user_agent})

    @staticmethod
    def _build_retry(retries: int, backoff_factor: float, status_forcelist: Tuple[int, ...]) -> Retry:
        """Build a urllib3 Retry, tolerating the v1/v2 kwarg rename."""
        common: Dict[str, Any] = dict(
            total=int(retries),
            connect=int(retries),
            read=int(retries),
            backoff_factor=float(backoff_factor),
            status_forcelist=tuple(status_forcelist),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        try:
            return Retry(allowed_methods=DEFAULT_ALLOWED_METHODS, **common)
        except TypeError:  # pragma: no cover - urllib3 < 1.26
            return Retry(method_whitelist=DEFAULT_ALLOWED_METHODS, **common)  # type: ignore[call-arg]

    # -- caching helpers ---------------------------------------------------
    @staticmethod
    def _cache_key(method: str, url: str, params: Optional[Dict[str, Any]]) -> str:
        normalised = urlencode(sorted((params or {}).items()), doseq=True)
        raw = f"{method.upper()}|{url}|{normalised}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _cacheable(self, method: str, use_cache: Optional[bool]) -> bool:
        if use_cache is not None:
            return bool(use_cache) and self._cache.ttl > 0
        return method in ("GET", "HEAD") and self._cache.ttl > 0

    # -- public API --------------------------------------------------------
    def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        use_cache: Optional[bool] = None,
        **kwargs: Any,
    ) -> requests.Response:
        """Perform a request with backoff, rate limiting, caching and fallback.

        On a hard failure after all retries, if a stale cached response exists
        it is returned (logged at WARNING) instead of raising -- this is the
        "keep the pipeline alive during an upstream outage" behaviour.
        """
        method = method.upper()
        cacheable = self._cacheable(method, use_cache)
        key = self._cache_key(method, url, params) if cacheable else None

        if cacheable:
            fresh = self._cache.get_fresh(key)  # type: ignore[arg-type]
            if fresh is not None:
                logger.debug("resilient-http cache HIT (fresh) %s %s", method, url)
                return fresh

        self._limiter.wait(_host_of(url))

        try:
            response = self._session.request(
                method,
                url,
                params=params,
                headers=headers,
                timeout=timeout if timeout is not None else self.timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            if cacheable:
                stale = self._cache.get_any(key)  # type: ignore[arg-type]
                if stale is not None:
                    return self._serve_stale(method, url, stale, f"failed ({exc})")
            raise

        # A persistent server error (retries exhausted) can still surface as a
        # 5xx because raise_on_status=False; fall back to stale if we have it.
        if response.status_code >= 400 and cacheable:
            stale = self._cache.get_any(key)  # type: ignore[arg-type]
            if stale is not None and stale is not response:
                return self._serve_stale(
                    method, url, stale, f"returned HTTP {response.status_code}"
                )

        if cacheable and response.status_code < 400:
            self._cache.set(key, response)  # type: ignore[arg-type]
        return response

    def _serve_stale(
        self, method: str, url: str, stale: requests.Response, reason: str
    ) -> requests.Response:
        """Count, tag, log and return a stale cached response.

        The tag travels on the response itself (``X-Beacon-Stale-Fallback``)
        so any consumer can tell a degraded fetch from a fresh one; the
        counter is what the collector reads (it never sees the response --
        plugins hand back DataFrames).
        """
        self.stale_fallback_hits += 1
        try:
            stale.headers["X-Beacon-Stale-Fallback"] = "1"
        except Exception:  # noqa: BLE001 - tagging must never void the fallback
            pass
        logger.warning(
            "resilient-http %s %s %s; serving STALE cached response",
            method, url, reason,
        )
        return stale

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return self.get(url, **kwargs).json()

    def get_text(self, url: str, **kwargs: Any) -> str:
        return self.get(url, **kwargs).text

    def clear_cache(self) -> None:
        self._cache.clear()

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "ResilientSession":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def retry_call(
    fn: Callable[[], Any],
    *,
    retries: int = DEFAULT_RETRIES,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    exceptions: Tuple[type, ...] = (Exception,),
    max_backoff: float = 30.0,
    on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
) -> Any:
    """Run ``fn()`` with exponential backoff, for SDK calls without raw HTTP.

    Plugins that wrap ``yfinance`` / ``sec_api`` cannot use the urllib3 retry
    adapter because the SDK hides the transport. This applies the same policy
    around the opaque call: retry on the given ``exceptions`` with
    ``backoff_factor * 2**(attempt-1)`` sleeps (capped at ``max_backoff``),
    re-raising the last exception once ``retries`` is exhausted.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except exceptions as exc:  # noqa: PERF203 - retry loop is the point
            attempt += 1
            if attempt > retries:
                raise
            delay = min(backoff_factor * (2 ** (attempt - 1)), max_backoff)
            logger.warning(
                "retry_call attempt %d/%d failed (%s: %s); sleeping %.2fs",
                attempt, retries, type(exc).__name__, exc, delay,
            )
            if on_retry is not None:
                on_retry(attempt, exc, delay)
            time.sleep(delay)


# --- per-host shared sessions ---------------------------------------------
_shared_sessions: Dict[str, ResilientSession] = {}
_shared_lock = threading.Lock()


def get_session(host_key: str, **kwargs: Any) -> ResilientSession:
    """Return a process-wide :class:`ResilientSession` keyed by ``host_key``.

    Lets several plugins hitting the same origin share one connection pool and
    one cache. Keyword arguments are only applied when the session is first
    created for that key.
    """
    with _shared_lock:
        session = _shared_sessions.get(host_key)
        if session is None:
            session = ResilientSession(**kwargs)
            _shared_sessions[host_key] = session
        return session
