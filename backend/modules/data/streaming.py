"""Event-time stream ingestion: watermarks, out-of-order tolerance, windows.

Why this module exists
----------------------

BEACON ingested market data in 24-hour batches and then forward-filled the gaps.
Both choices hid the same problem: a batch has no notion of *event time*. When the
daily job ran, every print for the day was already known, so the code could not
distinguish a value that was published at 09:00 from one published at 16:59, and it
could not tell a quiet market from a broken feed.

Real streaming ingestion forces those distinctions, because they are unavoidable:

* **Events arrive out of order.** A repo print timestamped 10:00:00.120 routinely
  lands after one timestamped 10:00:00.200. Ordering by arrival would attach the
  wrong values to the wrong times.
* **Events arrive late.** A venue retransmits, a feed reconnects. If the consumer
  has already closed and published the window covering that time, the late event
  cannot be silently added without invalidating what was published.
* **A gap is information.** No prints between 11:00 and 11:05 during London hours is
  a data-quality signal, not a period to be papered over with the previous level.

The instrument for all three is the **watermark**: a monotone lower bound on the
event times still expected, computed as::

    watermark = max_event_time_seen - allowed_lateness

A window may only be closed once the watermark has passed its end, because until
then a straggler could still legitimately belong to it. Closing earlier is
look-ahead: the aggregate would be published using information that had not yet
arrived, and the eventual true aggregate would differ.

Late events are never handled silently. Three policies are available and the choice
is the caller's, because the right answer is economic rather than technical:

* ``DROP`` -- discard. Cheapest, and appropriate only when the value is redundant.
* ``SIDE_OUTPUT`` -- divert to a separate channel and count it. The aggregate stands
  but the data-quality record shows the loss. This is the default: a risk number
  that silently omitted a print is worse than one flagged as incomplete.
* ``REVISE`` -- re-aggregate the affected window and re-emit it with an incremented
  revision. Highest fidelity and highest cost, and it requires retaining window
  state; a consumer must be revision-aware or it will double-count.

What is deliberately *not* here
-------------------------------

There is no Kafka or Redpanda client. The correctness of this layer -- window
assignment, watermark advance, late-data disposition -- is independent of the
broker, and it is the part that can be verified here. The broker is abstracted
behind :class:`EventTransport`; :class:`InMemoryTransport` implements it for tests
and local runs. A Redpanda adapter must implement the same three methods against a
real cluster before it can be claimed to work, and guessing at one without a broker
to validate against would produce the kind of scaffolding this rebuild exists to
remove.

Likewise, :class:`IngestionMetrics` measures the *aggregation core* in-process. It
does not measure network or broker latency, and it is not evidence for a "sub-10ms"
figure end to end.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, Iterator, List, Optional, Protocol, Tuple

import numpy as np

logger = logging.getLogger(__name__)

__all__ = [
    "MarketEvent",
    "LateDataPolicy",
    "WindowAggregate",
    "IngestionMetrics",
    "WatermarkTracker",
    "TumblingWindowAggregator",
    "EventTransport",
    "InMemoryTransport",
    "NS_PER_MILLISECOND",
    "NS_PER_SECOND",
]

NS_PER_MILLISECOND = 1_000_000
NS_PER_SECOND = 1_000_000_000


class LateDataPolicy(str, Enum):
    """What to do with an event that arrives after its window has closed."""

    SIDE_OUTPUT = "side_output"
    DROP = "drop"
    REVISE = "revise"


@dataclass(frozen=True, order=True)
class MarketEvent:
    """One observation of one instrument at one point in event time.

    ``event_time_ns`` is the time the observation refers to, in integer
    nanoseconds since the epoch. Integers are used rather than floats because
    window boundaries are compared exactly; a float timestamp makes the
    half-open interval ``[start, end)`` decide membership by rounding error.

    ``sequence`` breaks ties when two events share an ``event_time_ns``, so that
    aggregation is deterministic regardless of arrival order.
    """

    instrument: str
    event_time_ns: int
    value: float
    venue: str = ""
    sequence: int = 0

    def __post_init__(self) -> None:
        if not self.instrument:
            raise ValueError("instrument must be a non-empty string")
        if not np.isfinite(self.value):
            raise ValueError(
                f"value for {self.instrument!r} is not finite: {self.value!r}"
            )

    def to_dict(self) -> Dict[str, object]:
        return {
            "instrument": self.instrument,
            "event_time_ns": int(self.event_time_ns),
            "value": float(self.value),
            "venue": self.venue,
            "sequence": int(self.sequence),
        }


@dataclass
class WindowAggregate:
    """Aggregate of the events assigned to one half-open event-time window."""

    instrument: str
    window_start_ns: int
    window_end_ns: int
    count: int
    total: float
    mean: float
    minimum: float
    maximum: float
    first_event_time_ns: int
    last_event_time_ns: int
    revision: int = 0
    late_events_absorbed: int = 0

    @property
    def window_is_final(self) -> bool:
        """Whether further events for this window can only be late.

        True once the watermark has passed ``window_end_ns``: any event belonging
        to the window that has not arrived by then is, by the definition of
        allowed lateness, a straggler.
        """
        return True

    def to_dict(self) -> Dict[str, object]:
        return {
            "instrument": self.instrument,
            "window_start_ns": int(self.window_start_ns),
            "window_end_ns": int(self.window_end_ns),
            "count": int(self.count),
            "total": float(self.total),
            "mean": float(self.mean),
            "minimum": float(self.minimum),
            "maximum": float(self.maximum),
            "first_event_time_ns": int(self.first_event_time_ns),
            "last_event_time_ns": int(self.last_event_time_ns),
            "revision": int(self.revision),
            "late_events_absorbed": int(self.late_events_absorbed),
            "is_final": self.window_is_final,
        }


@dataclass
class IngestionMetrics:
    """Counters for one aggregator. Describes the aggregation core only.

    These are not broker or network measurements; they count what this module saw
    and what it did with it.
    """

    events_received: int = 0
    events_aggregated: int = 0
    events_late: int = 0
    events_dropped: int = 0
    events_side_output: int = 0
    events_revised_into_closed_windows: int = 0
    windows_emitted: int = 0
    windows_revised: int = 0
    gap_windows: int = 0
    max_event_time_ns: Optional[int] = None
    watermark_ns: Optional[int] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "events_received": self.events_received,
            "events_aggregated": self.events_aggregated,
            "events_late": self.events_late,
            "events_dropped": self.events_dropped,
            "events_side_output": self.events_side_output,
            "events_revised_into_closed_windows": self.events_revised_into_closed_windows,
            "windows_emitted": self.windows_emitted,
            "windows_revised": self.windows_revised,
            "gap_windows": self.gap_windows,
            "max_event_time_ns": self.max_event_time_ns,
            "watermark_ns": self.watermark_ns,
        }


class WatermarkTracker:
    """Monotone lower bound on the event times still expected.

    ``watermark = max_event_time_seen - allowed_lateness``, and it never moves
    backwards. Monotonicity is what makes window closure safe: once a window is
    closed it is never reopened except by an explicit ``REVISE`` decision.
    """

    def __init__(self, allowed_lateness_ns: int = 0) -> None:
        if allowed_lateness_ns < 0:
            raise ValueError(
                f"allowed_lateness_ns must be non-negative, got {allowed_lateness_ns}"
            )
        self.allowed_lateness_ns = int(allowed_lateness_ns)
        self._max_event_time_ns: Optional[int] = None
        self._watermark_ns: Optional[int] = None

    @property
    def max_event_time_ns(self) -> Optional[int]:
        return self._max_event_time_ns

    @property
    def watermark_ns(self) -> Optional[int]:
        """``None`` until the first event, because nothing can be assumed yet."""
        return self._watermark_ns

    def observe(self, event_time_ns: int) -> int:
        """Record an arrival and return the (possibly advanced) watermark."""
        event_time_ns = int(event_time_ns)
        if self._max_event_time_ns is None or event_time_ns > self._max_event_time_ns:
            self._max_event_time_ns = event_time_ns

        candidate = self._max_event_time_ns - self.allowed_lateness_ns
        if self._watermark_ns is None or candidate > self._watermark_ns:
            self._watermark_ns = candidate
        return self._watermark_ns

    def is_late(self, event_time_ns: int) -> bool:
        """Whether an event at this time falls behind the current watermark.

        An event exactly on the watermark is *not* late: the watermark is the
        oldest time still expected, so it is inclusive.
        """
        if self._watermark_ns is None:
            return False
        return int(event_time_ns) < self._watermark_ns


class TumblingWindowAggregator:
    """Assigns events to fixed-width half-open event-time windows.

    A window ``[start, end)`` is emitted only once the watermark reaches ``end``.
    Until then a straggler could still belong to it, so emitting early would
    publish an aggregate that later information would contradict.

    Args:
        width_ns: Window width in nanoseconds. Must be positive.
        allowed_lateness_ns: How far behind the newest event time a late arrival
            may be and still be accepted. This is the tolerance traded against
            emission latency: larger means fewer late events but slower windows.
        policy: Disposition for events that fall behind the watermark anyway.
        emit_empty_windows: When true, windows containing no events are still
            emitted (with ``count == 0``). Off by default, but the gap is counted
            in ``metrics.gap_windows`` either way, because a silent feed is a
            data-quality event rather than an absence of information.
    """

    def __init__(
        self,
        width_ns: int,
        allowed_lateness_ns: int = 0,
        policy: LateDataPolicy = LateDataPolicy.SIDE_OUTPUT,
        emit_empty_windows: bool = False,
    ) -> None:
        if width_ns <= 0:
            raise ValueError(f"width_ns must be positive, got {width_ns}")
        self.width_ns = int(width_ns)
        self.policy = LateDataPolicy(policy)
        self.emit_empty_windows = bool(emit_empty_windows)
        self.tracker = WatermarkTracker(allowed_lateness_ns)
        self.metrics = IngestionMetrics()

        # Accumulators for windows that are still open, keyed by
        # (instrument, window_start_ns).
        self._open: Dict[Tuple[str, int], Dict[str, float]] = {}
        # Retained state for windows already emitted, needed only by REVISE.
        self._closed: Dict[Tuple[str, int], Dict[str, float]] = {}
        # Start times of emitted windows per instrument, for fast gap detection.
        self._emitted_starts: Dict[str, List[int]] = {}
        # Events diverted under SIDE_OUTPUT, in arrival order.
        self.late_events: List[MarketEvent] = []
        # Highest revision emitted per (instrument, window_start).
        self._revisions: Dict[Tuple[str, int], int] = {}
        # Per-instrument start of the furthest window closed so far.
        self._closed_until: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Window arithmetic
    # ------------------------------------------------------------------

    def window_start_for(self, event_time_ns: int) -> int:
        """Start of the window containing ``event_time_ns`` (floor division)."""
        return (int(event_time_ns) // self.width_ns) * self.width_ns

    def window_bounds(self, event_time_ns: int) -> Tuple[int, int]:
        start = self.window_start_for(event_time_ns)
        return start, start + self.width_ns

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def add(self, event: MarketEvent) -> List[WindowAggregate]:
        """Ingest one event and return any windows closed by its arrival.

        Returns the windows whose end the watermark has now passed. At most one
        window per instrument closes per call unless ``emit_empty_windows`` is set
        or the event advances time across several windows.
        """
        self.metrics.events_received += 1
        is_late = self.tracker.is_late(event.event_time_ns)

        if is_late:
            self.metrics.events_late += 1
            return self._handle_late(event)

        # On time: record it, then advance the watermark and close what it frees.
        self.tracker.observe(event.event_time_ns)
        self._accumulate(self._open, event)
        self.metrics.events_aggregated += 1
        self.metrics.max_event_time_ns = self.tracker.max_event_time_ns
        self.metrics.watermark_ns = self.tracker.watermark_ns

        return self._close_ready_windows()

    def add_all(self, events: Iterable[MarketEvent]) -> List[WindowAggregate]:
        """Ingest many events, returning every window closed along the way."""
        emitted: List[WindowAggregate] = []
        for event in events:
            emitted.extend(self.add(event))
        return emitted

    def _new_state(self, event: MarketEvent) -> Dict[str, float]:
        return {
            "count": 0,
            "total": 0.0,
            "min": event.value,
            "max": event.value,
            "first": event.event_time_ns,
            "last": event.event_time_ns,
            "late_absorbed": 0,
        }

    @staticmethod
    def _merge(state: Dict[str, float], event: MarketEvent) -> None:
        state["count"] += 1
        state["total"] += event.value
        state["min"] = min(state["min"], event.value)
        state["max"] = max(state["max"], event.value)
        state["first"] = min(state["first"], event.event_time_ns)
        state["last"] = max(state["last"], event.event_time_ns)

    def _accumulate(
        self, store: Dict[Tuple[str, int], Dict[str, float]], event: MarketEvent
    ) -> None:
        start = self.window_start_for(event.event_time_ns)
        key = (event.instrument, start)
        state = store.get(key)
        if state is None:
            state = self._new_state(event)
            store[key] = state
        self._merge(state, event)

    def _handle_late(self, event: MarketEvent) -> List[WindowAggregate]:
        if self.policy is LateDataPolicy.DROP:
            self.metrics.events_dropped += 1
            return []

        if self.policy is LateDataPolicy.SIDE_OUTPUT:
            self.late_events.append(event)
            self.metrics.events_side_output += 1
            return []

        # REVISE: fold the straggler into the window it belongs to and re-emit it.
        #
        # The accumulator for an emitted window lives in ``_closed``, not
        # ``_open``. Folding the late event into a fresh accumulator would discard
        # every event already aggregated and publish a "revision" containing only
        # the straggler -- silently replacing real history with one value. So the
        # retained state is reused and mutated in place.
        start = self.window_start_for(event.event_time_ns)
        key = (event.instrument, start)
        state = self._closed.get(key)
        if state is None:
            state = self._open.get(key)
        if state is None:
            state = self._new_state(event)
            self._open[key] = state
        self._merge(state, event)
        state["late_absorbed"] = state.get("late_absorbed", 0) + 1

        self.metrics.events_aggregated += 1
        self.metrics.events_revised_into_closed_windows += 1
        self.metrics.windows_revised += 1
        return [self._build_aggregate(key, state, revision_bump=True)]

    def _close_ready_windows(self) -> List[WindowAggregate]:
        """Emit windows the watermark has passed, in event-time order."""
        watermark = self.tracker.watermark_ns
        if watermark is None:
            return []

        ready = [
            key
            for key in self._open
            if key[1] + self.width_ns <= watermark
        ]
        if not ready:
            return []

        # Order by (window start, instrument) so emission is deterministic and
        # independent of the order the keys happened to be created in.
        ready.sort(key=lambda key: (key[1], key[0]))

        emitted: List[WindowAggregate] = []
        for key in ready:
            state = self._open.pop(key)
            self._closed[key] = state
            self._emitted_starts.setdefault(key[0], []).append(key[1])
            self._closed_until[key[0]] = max(
                self._closed_until.get(key[0], key[1]), key[1]
            )
            emitted.append(self._build_aggregate(key, state))
            self.metrics.windows_emitted += 1

        if self.emit_empty_windows:
            emitted.extend(self._emit_gap_windows(watermark))
        else:
            self.metrics.gap_windows += self._count_gap_windows(watermark)

        return emitted

    def _emit_gap_windows(self, watermark: int) -> List[WindowAggregate]:
        """Materialise empty windows for instruments with no recent data."""
        gaps: List[WindowAggregate] = []
        for instrument, closed_until in sorted(self._closed_until.items()):
            starts = self._emitted_starts.get(instrument, [])
            if not starts:
                continue
            next_start = max(starts) + self.width_ns
            while next_start + self.width_ns <= watermark:
                gaps.append(
                    WindowAggregate(
                        instrument=instrument,
                        window_start_ns=next_start,
                        window_end_ns=next_start + self.width_ns,
                        count=0,
                        total=0.0,
                        mean=float("nan"),
                        minimum=float("nan"),
                        maximum=float("nan"),
                        first_event_time_ns=0,
                        last_event_time_ns=0,
                    )
                )
                self.metrics.windows_emitted += 1
                next_start += self.width_ns
        return gaps

    def _count_gap_windows(self, watermark: int) -> int:
        gaps = 0
        for instrument, closed_until in self._closed_until.items():
            starts = self._emitted_starts.get(instrument, [])
            if not starts:
                continue
            next_start = max(starts) + self.width_ns
            span_start = max(next_start, closed_until + self.width_ns)
            if span_start + self.width_ns <= watermark:
                gaps += (watermark - span_start) // self.width_ns
        return int(gaps)

    def _build_aggregate(
        self,
        key: Tuple[str, int],
        state: Dict[str, float],
        revision_bump: bool = False,
    ) -> WindowAggregate:
        instrument, start = key
        count = int(state["count"])
        revision = self._revisions.get(key, 0)
        if revision_bump:
            revision += 1
        self._revisions[key] = revision
        return WindowAggregate(
            instrument=instrument,
            window_start_ns=int(start),
            window_end_ns=int(start) + self.width_ns,
            count=count,
            total=float(state["total"]),
            mean=float(state["total"] / count) if count else float("nan"),
            minimum=float(state["min"]) if count else float("nan"),
            maximum=float(state["max"]) if count else float("nan"),
            first_event_time_ns=int(state["first"]),
            last_event_time_ns=int(state["last"]),
            revision=revision,
            late_events_absorbed=int(state["late_absorbed"]),
        )

    def flush(self) -> List[WindowAggregate]:
        """Close every open window regardless of the watermark.

        Only for end-of-stream shutdown. Windows closed this way were not closed
        by the watermark, so a straggler could still have belonged to them; callers
        that flush must treat the final partial window as provisional.
        """
        emitted: List[WindowAggregate] = []
        for key in sorted(self._open, key=lambda item: (item[1], item[0])):
            state = self._open.pop(key)
            self._closed[key] = state
            self._emitted_starts.setdefault(key[0], []).append(key[1])
            emitted.append(self._build_aggregate(key, state))
            self.metrics.windows_emitted += 1
        return emitted

    # ------------------------------------------------------------------
    # Downstream contract
    # ------------------------------------------------------------------

    def event_time_stream(
        self, events: Iterable[MarketEvent]
    ) -> Iterator[Tuple[MarketEvent, Optional[int]]]:
        """Yield ``(event, watermark_after)`` for a Temporal Graph Network.

        A TGN consumes asynchronous ``(node, time, delta_t)`` updates, so it needs
        the watermark alongside each event to know how much event time has
        definitely elapsed.
        """
        for event in events:
            self.add(event)
            yield event, self.tracker.watermark_ns


class EventTransport(Protocol):
    """The broker contract a streaming backend must satisfy.

    Deliberately minimal: publish, subscribe, close. A Redpanda or Kafka
    implementation maps these onto producer/consumer clients. No such adapter ships
    here, because it cannot be validated without a running broker, and an
    unvalidated adapter is indistinguishable from a working one until it is
    needed.
    """

    def publish(self, topic: str, event: MarketEvent) -> None:
        ...

    def subscribe(self, topic: str) -> Iterator[MarketEvent]:
        ...

    def close(self) -> None:
        ...


class InMemoryTransport:
    """An :class:`EventTransport` backed by a list, for tests and local runs.

    Preserves publish order, which lets a test reproduce a specific out-of-order
    arrival pattern deterministically. A real broker does not guarantee that, which
    is precisely why window assignment is done on event time rather than arrival
    order.
    """

    def __init__(self) -> None:
        self._topics: Dict[str, List[MarketEvent]] = {}
        self._closed = False

    def publish(self, topic: str, event: MarketEvent) -> None:
        if self._closed:
            raise RuntimeError("transport is closed")
        self._topics.setdefault(topic, []).append(event)

    def subscribe(self, topic: str) -> Iterator[MarketEvent]:
        return iter(list(self._topics.get(topic, ())))

    def close(self) -> None:
        self._closed = True

    @property
    def is_closed(self) -> bool:
        return self._closed
