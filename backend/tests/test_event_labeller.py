"""Tests for the point-in-time event labeller.

Anchored to behaviour, not implementation: a declared crossing must produce
exactly the episodes a hand-read series shows, single spikes must not count,
the threshold must be the declared quantile of the declared span, and the
labelling must refuse to guess when the series cannot support the rule.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.modules.data.event_labeller import (
    EventDefinition,
    events_to_frame,
    horizon_move,
    label_events,
)


def _calm_with_episode(n: int = 120, onset: int = 60, length: int = 8) -> np.ndarray:
    rng = np.random.default_rng(5)
    series = 100 + rng.normal(0, 0.5, n).cumsum() * 0.1
    # a stress episode: a sustained upward excursion well above calm moves
    series[onset:onset + length] += np.linspace(4, 6, length)
    series[onset + length:] += 6
    return series


class TestDefinitionValidation:
    def test_quantile_must_be_a_tail(self):
        with pytest.raises(ValueError):
            EventDefinition(quantile=0.5)

    def test_direction_must_be_named(self):
        with pytest.raises(ValueError):
            EventDefinition(direction="sideways")

    def test_horizon_and_duration_must_be_positive(self):
        with pytest.raises(ValueError):
            EventDefinition(horizon=0)
        with pytest.raises(ValueError):
            EventDefinition(min_duration=0)


class TestLabelling:
    def test_a_sustained_excursion_is_one_event(self):
        series = _calm_with_episode()
        labelling = label_events(series, EventDefinition(direction="up", quantile=0.95, horizon=5, min_duration=2))
        assert labelling.n_events == 1
        onset = int(labelling.onsets[0])
        assert 55 <= onset <= 66  # the crossing is detected as the move accumulates
        assert labelling.events[onset:onset + 3].all()

    def test_a_single_spike_is_not_an_event(self):
        rng = np.random.default_rng(9)
        series = 100 + rng.normal(0, 0.3, 120)
        series[70] += 50  # one-step spike: the horizon move crosses once only
        labelling = label_events(series, EventDefinition(direction="up", quantile=0.99, horizon=5, min_duration=3))
        assert labelling.n_events == 0
        assert not labelling.events.any()

    def test_down_direction_labels_falls(self):
        series = -_calm_with_episode()
        labelling = label_events(series, EventDefinition(direction="down", quantile=0.95, horizon=5, min_duration=2))
        assert labelling.n_events == 1

    def test_threshold_is_the_declared_quantile_of_the_declared_span(self):
        series = _calm_with_episode()
        definition = EventDefinition(direction="up", quantile=0.9, horizon=5)
        labelling = label_events(series, definition, threshold_span=(0, 50))
        move = horizon_move(series, 5, "up")
        expected = float(np.quantile(move[0:50][np.isfinite(move[0:50])], 0.9))
        assert labelling.threshold == pytest.approx(expected)
        assert labelling.threshold_span == (0, 50)

    def test_threshold_span_is_refused_outside_the_series(self):
        with pytest.raises(ValueError):
            label_events(np.arange(40, dtype=float), EventDefinition(), threshold_span=(0, 999))

    def test_too_short_a_series_is_refused(self):
        with pytest.raises(ValueError):
            label_events(np.arange(4, dtype=float), EventDefinition(horizon=5, min_duration=2))

    def test_frame_materialisation(self):
        series = _calm_with_episode()
        labelling = label_events(series, EventDefinition())
        frame = events_to_frame(labelling)
        assert frame["event"].sum() == labelling.events.sum()
        assert frame["onset"].sum() == labelling.n_events

    def test_labelling_is_auditable(self):
        series = _calm_with_episode()
        payload = label_events(series, EventDefinition()).to_dict()
        assert payload["definition"]["quantile"] == 0.95
        assert "threshold" in payload and "onsets" in payload
