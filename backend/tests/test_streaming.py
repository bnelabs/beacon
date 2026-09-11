"""Tests for event-time stream ingestion.

The properties under test are the ones that decide whether a downstream risk model
sees reality or a plausible reconstruction of it:

* a window is never emitted before the watermark passes its end, because until then
  a straggler could still belong to it;
* arrival order does not change the aggregate, because window membership is a
  function of event time;
* a late event is never silently absorbed;
* a gap is counted rather than papered over.
"""

from __future__ import annotations

import pytest

from backend.modules.data.streaming import (
    InMemoryTransport,
    IngestionMetrics,
    LateDataPolicy,
    MarketEvent,
    NS_PER_MILLISECOND,
    NS_PER_SECOND,
    TumblingWindowAggregator,
    WatermarkTracker,
)

WIDTH = 1000  # nanoseconds; small values keep the test arithmetic readable


def event(t: int, value: float, instrument: str = "SOFR", sequence: int = 0) -> MarketEvent:
    return MarketEvent(
        instrument=instrument, event_time_ns=t, value=value, sequence=sequence
    )


class TestWatermark:
    def test_watermark_is_monotone_under_out_of_order_arrival(self):
        tracker = WatermarkTracker(allowed_lateness_ns=100)

        tracker.observe(5_000)
        first = tracker.watermark_ns
        # A straggler must not pull the watermark backwards.
        tracker.observe(1_000)
        assert tracker.watermark_ns == first

        tracker.observe(9_000)
        assert tracker.watermark_ns > first

    def test_watermark_is_none_until_the_first_event(self):
        tracker = WatermarkTracker(allowed_lateness_ns=10)
        assert tracker.watermark_ns is None
        assert tracker.max_event_time_ns is None

    def test_watermark_lags_the_newest_event_by_allowed_lateness(self):
        tracker = WatermarkTracker(allowed_lateness_ns=250)
        tracker.observe(10_000)
        assert tracker.watermark_ns == 10_000 - 250

    def test_event_exactly_on_the_watermark_is_not_late(self):
        tracker = WatermarkTracker(allowed_lateness_ns=100)
        tracker.observe(1_000)  # watermark = 900
        assert tracker.watermark_ns == 900
        assert tracker.is_late(900) is False   # inclusive
        assert tracker.is_late(899) is True

    def test_negative_lateness_is_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            WatermarkTracker(allowed_lateness_ns=-1)


class TestWindowAssignment:
    def test_windows_are_half_open(self):
        aggregator = TumblingWindowAggregator(width_ns=WIDTH)
        assert aggregator.window_bounds(0) == (0, WIDTH)
        assert aggregator.window_bounds(WIDTH - 1) == (0, WIDTH)
        # The right edge belongs to the next window, not this one.
        assert aggregator.window_bounds(WIDTH) == (WIDTH, 2 * WIDTH)

    def test_negative_timestamps_floor_towards_negative_infinity(self):
        aggregator = TumblingWindowAggregator(width_ns=WIDTH)
        assert aggregator.window_start_for(-1) == -WIDTH
        assert aggregator.window_start_for(-WIDTH) == -WIDTH

    def test_window_is_not_emitted_before_the_watermark_passes_it(self):
        aggregator = TumblingWindowAggregator(width_ns=WIDTH, allowed_lateness_ns=0)

        emitted = aggregator.add_all([event(0, 1.0), event(500, 2.0), event(900, 3.0)])
        assert emitted == []

        # This event lands in the next window and pushes the watermark to 1500,
        # which finally closes window [0, 1000).
        emitted = aggregator.add(event(1_500, 4.0))
        assert [w.window_start_ns for w in emitted] == [0]

        window = emitted[0]
        assert window.count == 3
        assert window.first_event_time_ns == 0
        assert window.last_event_time_ns == 900

    def test_emission_is_deferred_by_allowed_lateness(self):
        # The same events, but with a 400ns tolerance: window [0,1000) now closes
        # only once the watermark reaches 1000, i.e. max event time 1400.
        aggregator = TumblingWindowAggregator(width_ns=WIDTH, allowed_lateness_ns=400)
        aggregator.add(event(0, 1.0))
        assert aggregator.add(event(1_000, 2.0)) == []
        assert aggregator.tracker.watermark_ns == 600

        emitted = aggregator.add(event(1_400, 3.0))
        assert [w.window_start_ns for w in emitted] == [0]

    def test_aggregate_statistics_are_correct(self):
        aggregator = TumblingWindowAggregator(width_ns=WIDTH)
        aggregator.add_all([event(0, 1.0), event(100, 3.0), event(200, 5.0)])
        emitted = aggregator.add(event(1_000, 0.0))

        window = emitted[0]
        assert window.count == 3
        assert window.total == pytest.approx(9.0)
        assert window.mean == pytest.approx(3.0)
        assert window.minimum == pytest.approx(1.0)
        assert window.maximum == pytest.approx(5.0)

    def test_multiple_windows_close_incrementally_in_event_time_order(self):
        # Each arrival advances the watermark past at most the windows it has
        # overtaken, so windows are emitted as they close rather than in one
        # batch at the end.
        aggregator = TumblingWindowAggregator(width_ns=WIDTH)
        emitted = []
        emitted += aggregator.add(event(0, 1.0))
        emitted += aggregator.add(event(1_200, 2.0))
        emitted += aggregator.add(event(2_500, 3.0))
        emitted += aggregator.add(event(9_000, 0.0))

        assert [w.window_start_ns for w in emitted] == [0, 1_000, 2_000]
        assert [w.count for w in emitted] == [1, 1, 1]

    def test_instruments_do_not_cross_contaminate(self):
        aggregator = TumblingWindowAggregator(width_ns=WIDTH)
        aggregator.add(event(0, 1.0, instrument="SOFR"))
        aggregator.add(event(10, 100.0, instrument="ESTR"))
        emitted = aggregator.add(event(1_000, 0.0, instrument="SOFR"))

        by_instrument = {w.instrument: w for w in emitted}
        # Both instruments' opening windows close on this arrival, but each
        # aggregate contains only its own instrument's prints.
        assert by_instrument["SOFR"].count == 1
        assert by_instrument["SOFR"].total == pytest.approx(1.0)
        assert by_instrument["ESTR"].count == 1
        assert by_instrument["ESTR"].total == pytest.approx(100.0)

    def test_zero_width_window_is_rejected(self):
        with pytest.raises(ValueError, match="positive"):
            TumblingWindowAggregator(width_ns=0)


class TestArrivalOrderInvariance:
    def test_aggregates_are_independent_of_arrival_order(self):
        """Window membership is a function of event time, not arrival order.

        A sufficiently large lateness tolerance means no event is dropped, so the
        only thing that differs between the two runs is the order the events
        showed up in -- and the aggregates must still agree.
        """
        timestamps = [0, 250, 1_100, 1_500, 2_050, 3_000, 3_100]
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]

        forward = TumblingWindowAggregator(width_ns=WIDTH, allowed_lateness_ns=10_000)
        for t, v in zip(timestamps, values):
            forward.add(event(t, v))
        forward_windows = sorted(forward.flush(), key=lambda w: w.window_start_ns)

        # Same events, reversed arrival order. Every event still sits inside the
        # lateness horizon, so none is late.
        backward = TumblingWindowAggregator(width_ns=WIDTH, allowed_lateness_ns=10_000)
        for t, v in zip(reversed(timestamps), reversed(values)):
            backward.add(event(t, v))
        backward_windows = sorted(backward.flush(), key=lambda w: w.window_start_ns)

        assert [w.window_start_ns for w in forward_windows] == [
            w.window_start_ns for w in backward_windows
        ]
        assert [w.count for w in forward_windows] == [
            w.count for w in backward_windows
        ]
        assert [w.total for w in forward_windows] == pytest.approx(
            [w.total for w in backward_windows]
        )
        assert [w.mean for w in forward_windows] == pytest.approx(
            [w.mean for w in backward_windows]
        )

    def test_shuffled_order_yields_identical_aggregates(self):
        import numpy as np

        rng = np.random.default_rng(20260214)
        timestamps = sorted(int(x) for x in rng.integers(0, 20_000, size=60))
        values = [float(x) for x in rng.normal(size=60)]

        ordered = TumblingWindowAggregator(width_ns=WIDTH, allowed_lateness_ns=10**9)
        for t, v in zip(timestamps, values):
            ordered.add(event(t, v))
        baseline = sorted(ordered.flush(), key=lambda w: w.window_start_ns)

        order = rng.permutation(len(timestamps))
        shuffled = TumblingWindowAggregator(width_ns=WIDTH, allowed_lateness_ns=10**9)
        for index in order:
            shuffled.add(event(timestamps[index], values[index]))
        candidate = sorted(shuffled.flush(), key=lambda w: w.window_start_ns)

        assert [w.window_start_ns for w in baseline] == [
            w.window_start_ns for w in candidate
        ]
        assert [w.count for w in baseline] == [w.count for w in candidate]
        assert [w.total for w in baseline] == pytest.approx(
            [w.total for w in candidate]
        )


class TestLateData:
    def _closed_aggregator(self, policy: LateDataPolicy) -> TumblingWindowAggregator:
        # lateness 0 means the watermark keeps up with the newest event, so the
        # window [0, 1000) is closed as soon as t=1000 arrives.
        aggregator = TumblingWindowAggregator(width_ns=WIDTH, policy=policy)
        aggregator.add_all([event(0, 1.0), event(100, 2.0)])
        aggregator.add(event(1_000, 3.0))
        assert aggregator.metrics.windows_emitted == 1
        return aggregator

    def test_side_output_diverts_a_late_event_without_altering_the_window(self):
        aggregator = self._closed_aggregator(LateDataPolicy.SIDE_OUTPUT)
        emitted = aggregator.add(event(50, 999.0))

        assert emitted == []
        assert aggregator.metrics.events_side_output == 1
        assert aggregator.metrics.events_late == 1
        assert len(aggregator.late_events) == 1
        assert aggregator.late_events[0].value == pytest.approx(999.0)
        # The already-published window did not absorb the straggler.
        assert aggregator.metrics.windows_revised == 0

    def test_drop_discards_the_late_event(self):
        aggregator = self._closed_aggregator(LateDataPolicy.DROP)
        emitted = aggregator.add(event(50, 999.0))

        assert emitted == []
        assert aggregator.metrics.events_dropped == 1
        assert aggregator.late_events == []

    def test_revise_reemits_the_window_with_an_incremented_revision(self):
        aggregator = self._closed_aggregator(LateDataPolicy.REVISE)
        emitted = aggregator.add(event(50, 998.0))

        assert len(emitted) == 1
        revised = emitted[0]
        assert revised.window_start_ns == 0
        assert revised.revision == 1
        assert revised.count == 3
        assert revised.total == pytest.approx(1.0 + 2.0 + 998.0)
        assert revised.late_events_absorbed == 1
        assert aggregator.metrics.windows_revised == 1

    def test_late_event_is_never_silently_absorbed(self):
        """Every policy must account for the straggler somewhere."""
        for policy in LateDataPolicy:
            aggregator = self._closed_aggregator(policy)
            aggregator.add(event(50, 999.0))

            accounted = (
                aggregator.metrics.events_side_output
                + aggregator.metrics.events_dropped
                + aggregator.metrics.events_revised_into_closed_windows
            )
            assert accounted == 1, policy
            assert aggregator.metrics.events_late == 1, policy

    def test_straggler_within_the_lateness_horizon_is_on_time(self):
        # A lateness of 700ns means the watermark trails the newest event by
        # 700ns, which is the window the tolerance opens for stragglers.
        aggregator = TumblingWindowAggregator(width_ns=WIDTH, allowed_lateness_ns=700)
        aggregator.add(event(100, 1.0))
        aggregator.add(event(1_500, 2.0))          # watermark = 800
        assert aggregator.tracker.watermark_ns == 800

        # 900 is behind the newest event (1500) but ahead of the watermark (800),
        # so the tolerance absorbs it and it is not late.
        assert aggregator.add(event(900, 3.0)) == []
        assert aggregator.metrics.events_late == 0

        # Advancing further closes [0,1000) containing BOTH the early print and
        # the straggler, so the straggler was neither lost nor misassigned.
        emitted = aggregator.add(event(1_800, 4.0))
        window = next(w for w in emitted if w.window_start_ns == 0)
        assert window.count == 2
        assert window.total == pytest.approx(4.0)


class TestGapsAndMetrics:
    def test_gap_windows_are_counted_not_papered_over(self):
        aggregator = TumblingWindowAggregator(width_ns=WIDTH)
        aggregator.add(event(0, 1.0))
        # Jump far ahead: several windows receive nothing at all.
        emitted = aggregator.add(event(10_000, 1.0))

        # Only the window that actually received a print was emitted; no
        # aggregate was invented for the silent stretch.
        assert [w.window_start_ns for w in emitted] == [0]
        assert all(w.count > 0 for w in emitted)
        assert aggregator.metrics.gap_windows >= 8
        assert aggregator.metrics.windows_emitted == 1

    def test_empty_windows_can_be_materialised_on_request(self):
        aggregator = TumblingWindowAggregator(width_ns=WIDTH, emit_empty_windows=True)
        aggregator.add(event(0, 1.0))
        emitted = aggregator.add(event(3_000, 1.0))

        empty = [w for w in emitted if w.count == 0]
        assert len(empty) == 2
        assert [w.window_start_ns for w in empty] == [1_000, 2_000]
        # An empty window's mean is undefined, and is reported as NaN rather than
        # as zero, which would read as a real observation of zero.
        assert all(w.mean != w.mean for w in empty)

    def test_metrics_account_for_every_event(self):
        aggregator = TumblingWindowAggregator(width_ns=WIDTH)
        aggregator.add_all([event(0, 1.0), event(100, 1.0)])
        aggregator.add(event(1_000, 1.0))
        aggregator.add(event(10, 1.0))  # late

        metrics = aggregator.metrics
        assert metrics.events_received == 4
        assert metrics.events_late == 1
        assert metrics.events_aggregated == 3
        assert metrics.windows_emitted == 1
        assert (
            metrics.events_aggregated
            + metrics.events_dropped
            + metrics.events_side_output
        ) == metrics.events_received

    def test_metrics_serialise_to_json(self):
        import json

        aggregator = TumblingWindowAggregator(width_ns=WIDTH)
        aggregator.add_all([event(0, 1.0), event(2_000, 2.0)])
        payload = aggregator.metrics.to_dict()
        json.dumps(payload, allow_nan=False)

        assert set(payload) >= {"events_received", "events_late", "windows_emitted"}


class TestFlushAndStreaming:
    def test_flush_closes_open_windows(self):
        aggregator = TumblingWindowAggregator(width_ns=WIDTH)
        aggregator.add_all([event(0, 1.0), event(100, 2.0)])
        assert aggregator.metrics.windows_emitted == 0

        flushed = aggregator.flush()
        assert len(flushed) == 1
        assert flushed[0].count == 2
        assert aggregator.flush() == []

    def test_event_time_stream_yields_a_monotone_watermark(self):
        aggregator = TumblingWindowAggregator(width_ns=WIDTH, allowed_lateness_ns=50)
        arrivals = [event(300, 1.0), event(100, 2.0), event(900, 3.0)]

        watermarks = [wm for _, wm in aggregator.event_time_stream(arrivals)]
        assert watermarks == sorted(watermarks)
        assert all(wm is not None for wm in watermarks)


class TestTransport:
    def test_in_memory_transport_round_trip(self):
        transport = InMemoryTransport()
        transport.publish("sofr", event(1, 1.0))
        transport.publish("sofr", event(2, 2.0))

        received = list(transport.subscribe("sofr"))
        assert [e.event_time_ns for e in received] == [1, 2]
        assert list(transport.subscribe("unused")) == []

    def test_publishing_after_close_is_rejected(self):
        transport = InMemoryTransport()
        transport.close()
        assert transport.is_closed
        with pytest.raises(RuntimeError, match="closed"):
            transport.publish("sofr", event(1, 1.0))


class TestEventValidation:
    def test_empty_instrument_is_rejected(self):
        with pytest.raises(ValueError, match="instrument"):
            MarketEvent(instrument="", event_time_ns=0, value=1.0)

    def test_non_finite_value_is_rejected(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValueError, match="finite"):
                MarketEvent(instrument="SOFR", event_time_ns=0, value=bad)

    def test_event_serialises_to_json(self):
        import json

        json.dumps(event(123, 4.5).to_dict(), allow_nan=False)


class TestUnitConstants:
    def test_nanosecond_constants_are_consistent(self):
        assert NS_PER_MILLISECOND == 1_000_000
        assert NS_PER_SECOND == 1_000 * NS_PER_MILLISECOND

    def test_a_ten_millisecond_window_accepts_sub_millisecond_prints(self):
        """The aggregation core handles the timescales the plan calls for.

        This exercises the arithmetic at realistic resolution; it is not a claim
        about end-to-end broker latency.
        """
        aggregator = TumblingWindowAggregator(width_ns=10 * NS_PER_MILLISECOND)
        base = 1_700_000_000 * NS_PER_SECOND
        values = [1.0, 1.5, 2.0, 2.5, 3.0]
        for index, value in enumerate(values):
            aggregator.add(event(base + index * 100_000, value))  # 0.1ms apart

        emitted = aggregator.add(event(base + 10 * NS_PER_MILLISECOND, 0.0))
        window = emitted[0]
        assert window.count == 5
        assert window.mean == pytest.approx(2.0)


def test_ingestion_metrics_defaults_are_zero():
    metrics = IngestionMetrics()
    assert metrics.events_received == 0
    assert metrics.watermark_ns is None
    assert metrics.max_event_time_ns is None
