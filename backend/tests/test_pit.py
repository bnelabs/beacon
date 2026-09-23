"""Tests for point-in-time vintage storage and the as-of join.

The suite is built around one failure mode: a model must never be shown a value
that had not been published yet. ``test_a_value_is_invisible_before_its_vintage``
pins the exact revision timeline for one GDP series, and
``test_forward_filling_final_values_leaks`` shows that the naive alternative --
taking today's final value and carrying it backwards -- disagrees with the
point-in-time answer. Between them, a regression to the old behaviour cannot pass
quietly.

Everything is deterministic. The generated store used by the invariant test is
seeded with a fixed integer where randomness is involved.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from backend.modules.data.pit import (
    OBSERVATION_COLUMNS,
    Observation,
    PITStore,
    as_of_join,
    attach_pit_features_at_onsets,
)

# The central fixture: one series, one period, three vintages. The number moves
# 100.0 -> 95.0 -> 90.0 as the statistical agency restates it.
GDP_VALID_TIME = pd.Timestamp("2020-01-01")
GDP_VINTAGE_TIMES = (
    pd.Timestamp("2020-04-30"),
    pd.Timestamp("2020-05-28"),
    pd.Timestamp("2020-06-25"),
)
GDP_VALUES = (100.0, 95.0, 90.0)


def _gdp_store() -> PITStore:
    """A store holding the three vintages of Q1-2020 GDP."""
    store = PITStore()
    store.append(
        [
            Observation(
                "US", "GDP", GDP_VALID_TIME, observed, value, revision
            )
            for revision, (observed, value) in enumerate(
                zip(GDP_VINTAGE_TIMES, GDP_VALUES)
            )
        ]
    )
    return store


def _single_value(store: PITStore, as_of, entity: str = "US", series: str = "GDP"):
    """The one value returned by a single-key query, or ``None`` if empty."""
    frame = store.query(entity, series, as_of=as_of)
    assert len(frame) <= 1, "a single (series, valid_time) query returned >1 row"
    if frame.empty:
        return None
    return float(frame["value"].iloc[0])


def _events(rows, index=None) -> pd.DataFrame:
    return pd.DataFrame(rows, index=index)


class TestCentralLeakage:
    def test_a_value_is_invisible_before_its_vintage(self):
        store = _gdp_store()

        # First print, and its own release instant.
        assert _single_value(store, "2020-04-30") == 100.0
        # Revision 1 exists in the future only.
        assert _single_value(store, "2020-05-15") == 100.0
        # Boundary: the release instant is inclusive.
        assert _single_value(store, "2020-05-28") == 95.0
        assert _single_value(store, "2020-06-25") == 90.0
        # One day before anything was published.
        before = store.query("US", "GDP", as_of="2020-04-29")
        assert before.empty
        assert list(before.columns) == list(OBSERVATION_COLUMNS)

        # The point of the module: the final value never appears in any query
        # that predates its publication, no matter how the day is chosen.
        probe = pd.date_range("2020-04-29", "2020-06-24", freq="D")
        for as_of in probe:
            frame = store.query("US", "GDP", as_of=as_of)
            assert 90.0 not in set(frame["value"].tolist()), (
                f"final value 90.0 leaked at as_of={as_of}"
            )
            assert set(frame["value"].tolist()) <= {100.0, 95.0}

    def test_missing_period_is_absent_not_forward_filled(self):
        # Q2's first vintage is published in July. An as-of query in May must not
        # invent a Q2 row by carrying Q1's value forward.
        store = _gdp_store()
        store.append(
            [
                Observation(
                    "US",
                    "GDP",
                    pd.Timestamp("2020-04-01"),
                    pd.Timestamp("2020-07-30"),
                    50.0,
                    0,
                )
            ]
        )
        frame = store.query("US", "GDP", as_of="2020-05-15")

        assert list(frame["valid_time"]) == [GDP_VALID_TIME]
        assert 50.0 not in set(frame["value"].tolist())

    def test_naive_forward_fill_leaks(self):
        store = _gdp_store()
        final = store.query("US", "GDP", as_of="2020-12-31")
        assert float(final["value"].iloc[0]) == 90.0

        # The naive pipeline keeps only final values, lays them on the calendar
        # and forward-fills, so every earlier date "knows" 90.0 even though it
        # was published on 2020-06-25.
        calendar = pd.date_range("2020-01-01", "2020-12-31", freq="D")
        naive = final.set_index("valid_time")["value"].reindex(calendar).ffill()

        probe = pd.Timestamp("2020-05-15")
        assert naive.loc[probe] == 90.0
        assert _single_value(store, probe) == 100.0
        assert naive.loc[probe] != _single_value(store, probe)


def _generated_store(seed: int = 20240101) -> PITStore:
    """Deterministic multi-entity, multi-series store with 3 vintages per period."""
    rng = np.random.default_rng(seed)
    store = PITStore()
    valid_times = pd.date_range("2020-01-01", "2021-12-01", freq="MS")
    for entity in ("A", "B"):
        for series in ("S1", "S2", "S3"):
            for valid_time in valid_times:
                for revision, lag_days in enumerate((30, 60, 90)):
                    store.append(
                        [
                            Observation(
                                entity,
                                series,
                                valid_time,
                                valid_time + pd.Timedelta(lag_days, unit="D"),
                                float(rng.normal()),
                                revision,
                            )
                        ]
                    )
    return store


class TestInvariants:
    def test_every_returned_row_is_known_by_as_of(self):
        store = _generated_store()
        as_of_grid = pd.date_range("2019-11-01", "2022-06-01", freq="7D")

        seen = 0
        for entity in ("A", "B"):
            for series in ("S1", "S2", "S3", None):
                for as_of in as_of_grid:
                    frame = store.query(entity, series, as_of=as_of)
                    assert frame["observed_at"].le(as_of).all(), (
                        f"future vintage returned for {entity}/{series} "
                        f"at as_of={as_of}"
                    )
                    # One row per (series, valid_time) and sorted by valid_time.
                    assert not frame.duplicated(
                        subset=["series_id", "valid_time"]
                    ).any()
                    assert frame["valid_time"].is_monotonic_increasing
                    seen += len(frame)
        assert seen > 0

    def test_valid_from_and_valid_to_bounds_are_enforced(self):
        store = _generated_store()
        lower = pd.Timestamp("2020-06-01")
        upper = pd.Timestamp("2021-03-01")
        frame = store.query(
            "A", "S1", as_of="2022-01-01", valid_from=lower, valid_to=upper
        )

        assert not frame.empty
        assert (frame["valid_time"] >= lower).all()
        assert (frame["valid_time"] <= upper).all()


class TestNoCrossContamination:
    def _store(self) -> PITStore:
        store = PITStore()
        store.append(
            [
                Observation(
                    "A", "S1", pd.Timestamp("2020-01-01"),
                    pd.Timestamp("2020-02-01"), 1.0, 0,
                ),
                Observation(
                    "A", "S2", pd.Timestamp("2020-01-01"),
                    pd.Timestamp("2020-02-01"), 2.0, 0,
                ),
                Observation(
                    "B", "S1", pd.Timestamp("2020-01-01"),
                    pd.Timestamp("2020-02-01"), 3.0, 0,
                ),
            ]
        )
        return store

    def test_single_key_query_returns_only_that_key(self):
        frame = self._store().query("A", "S1", as_of="2020-03-01")
        assert len(frame) == 1
        assert frame["entity_id"].tolist() == ["A"]
        assert frame["series_id"].tolist() == ["S1"]
        assert frame["value"].tolist() == [1.0]

    def test_entity_wide_query_spans_its_own_series_only(self):
        frame = self._store().query("A", as_of="2020-03-01")
        assert set(frame["entity_id"]) == {"A"}
        assert set(frame["series_id"]) == {"S1", "S2"}

    def test_other_entity_is_not_visible(self):
        store = self._store()
        assert store.query("B", "S2", as_of="2020-03-01").empty
        assert store.query("C", as_of="2020-03-01").empty
        assert store.query("B", "S1", as_of="2020-03-01")["value"].tolist() == [3.0]


class TestAppendSemantics:
    def test_identical_reappend_is_idempotent(self):
        store = PITStore()
        observation = Observation(
            "US", "GDP", GDP_VALID_TIME, GDP_VINTAGE_TIMES[0], 100.0, 0
        )

        assert store.append([observation]) == 1
        assert store.append([observation]) == 0
        assert store.append([observation]) == 0
        assert len(store) == 1

    def test_conflicting_value_on_same_vintage_is_rejected(self):
        store = _gdp_store()
        rewritten = Observation(
            "US", "GDP", GDP_VALID_TIME, GDP_VINTAGE_TIMES[0], 101.0, 0
        )

        with pytest.raises(ValueError, match="conflicting value"):
            store.append([rewritten])
        # The stored vintage is untouched.
        assert _single_value(store, "2020-04-30") == 100.0

    def test_higher_revision_is_the_way_to_publish_a_new_value(self):
        store = PITStore()
        store.append(
            [
                Observation(
                    "US", "GDP", GDP_VALID_TIME, GDP_VINTAGE_TIMES[0], 100.0, 0
                )
            ]
        )
        same_stamp_restatement = Observation(
            "US", "GDP", GDP_VALID_TIME, GDP_VINTAGE_TIMES[0], 101.0, 1
        )

        assert store.append([same_stamp_restatement]) == 1
        frame = store.query("US", "GDP", as_of="2020-04-30")
        # Same publication instant: the later revision is the newer number.
        assert frame["value"].tolist() == [101.0]
        assert frame["revision"].tolist() == [1]

    def test_reappending_a_different_revision_value_is_still_visible(self):
        store = _gdp_store()
        assert store.append(
            [
                Observation(
                    "US", "GDP", GDP_VALID_TIME, pd.Timestamp("2020-05-28"), 95.5, 3
                )
            ]
        ) == 1
        assert _single_value(store, "2020-05-28") == 95.5


class TestMetadata:
    def test_vintages_and_latest_as_of(self):
        store = _gdp_store()

        assert store.vintages("US", "GDP") == list(GDP_VINTAGE_TIMES)
        assert store.latest_as_of("US", "GDP") == GDP_VINTAGE_TIMES[-1]
        assert store.vintages("US", "MISSING") == []
        assert store.latest_as_of("US", "MISSING") is None

    def test_to_frame_contains_every_vintage_sorted(self):
        store = _gdp_store()
        store.append(
            [
                Observation(
                    "A", "S1", pd.Timestamp("2019-01-01"),
                    pd.Timestamp("2019-02-01"), 7.0, 0,
                )
            ]
        )
        frame = store.to_frame()

        assert len(frame) == 4
        assert list(frame.columns) == list(OBSERVATION_COLUMNS)
        assert set(frame["revision"]) == {0, 1, 2}
        key = frame[["entity_id", "series_id", "valid_time", "observed_at", "revision"]]
        assert key.apply(tuple, axis=1).is_monotonic_increasing

    def test_far_future_as_of_returns_the_latest_vintage(self):
        frame = _gdp_store().query("US", "GDP", as_of="2099-01-01")
        assert len(frame) == 1
        assert frame["value"].tolist() == [90.0]
        assert frame["revision"].tolist() == [2]

    def test_empty_store_query_has_the_column_contract(self):
        frame = PITStore().query("US", "GDP", as_of="2020-01-01")
        assert frame.empty
        assert list(frame.columns) == list(OBSERVATION_COLUMNS)

    def test_query_result_is_a_copy_of_the_store(self):
        store = _gdp_store()
        frame = store.query("US", "GDP", as_of="2099-01-01")
        frame.loc[0, "value"] = -1.0

        assert _single_value(store, "2099-01-01") == 90.0


class TestObservationValidation:
    def _make(self, **overrides):
        fields = {
            "entity_id": "US",
            "series_id": "GDP",
            "valid_time": GDP_VALID_TIME,
            "observed_at": GDP_VINTAGE_TIMES[0],
            "value": 100.0,
            "revision": 0,
        }
        fields.update(overrides)
        return Observation(**fields)

    def test_non_finite_value_is_rejected(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValueError, match="value"):
                self._make(value=bad)

    def test_non_numeric_value_is_rejected(self):
        with pytest.raises(ValueError, match="value"):
            self._make(value="not-a-number")

    def test_observed_at_before_valid_time_is_rejected(self):
        with pytest.raises(ValueError, match="observed_at"):
            self._make(
                valid_time=pd.Timestamp("2020-06-01"),
                observed_at=pd.Timestamp("2020-05-01"),
            )

    def test_observed_at_equal_to_valid_time_is_allowed(self):
        observation = self._make(
            valid_time=pd.Timestamp("2020-05-01"),
            observed_at=pd.Timestamp("2020-05-01"),
        )
        assert observation.valid_time == observation.observed_at

    def test_negative_revision_is_rejected(self):
        with pytest.raises(ValueError, match="revision"):
            self._make(revision=-1)

    def test_to_dict_round_trips_all_fields(self):
        observation = self._make()
        payload = observation.to_dict()
        assert list(payload) == list(OBSERVATION_COLUMNS)
        assert payload["entity_id"] == "US"
        assert payload["series_id"] == "GDP"
        assert payload["valid_time"] == GDP_VALID_TIME
        assert payload["observed_at"] == GDP_VINTAGE_TIMES[0]
        assert payload["value"] == 100.0
        assert payload["revision"] == 0


def _join_events() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "entity_id": ["A", "A", "B", "C"],
            "event_time": pd.to_datetime(
                ["2020-05-15", "2020-06-30", "2020-05-15", "2020-05-15"]
            ),
        },
        index=[10, 3, 7, 42],
    )


def _join_features() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "entity_id": ["A", "A", "B"],
            "observed_at": pd.to_datetime(
                ["2020-04-01", "2020-06-10", "2020-02-01"]
            ),
            "valid_time": pd.to_datetime(
                ["2020-04-01", "2020-06-01", "2020-04-01"]
            ),
            "value": [1.0, 2.0, 3.0],
            "label": ["early", "later", "b"],
        }
    )


class TestAsOfJoin:
    def test_latest_row_known_at_the_event_time_attaches(self):
        joined = as_of_join(
            _join_events(),
            _join_features(),
            on="entity_id",
            event_time_col="event_time",
        )

        assert joined["value"].tolist()[:3] == [1.0, 2.0, 3.0]
        assert joined["label"].tolist()[:3] == ["early", "later", "b"]

    def test_no_match_yields_nan_never_a_carried_value(self):
        joined = as_of_join(
            _join_events(),
            _join_features(),
            on="entity_id",
            event_time_col="event_time",
        )

        # Event C has no features, and must not inherit A's or B's value.
        assert np.isnan(joined.loc[42, "value"])
        assert joined.loc[42, "label"] is np.nan or pd.isna(joined.loc[42, "label"])

    def test_feature_describing_a_future_period_does_not_attach(self):
        events = pd.DataFrame(
            {
                "entity_id": ["A", "A"],
                "event_time": pd.to_datetime(["2020-05-15", "2020-05-15"]),
            }
        )
        # Both rows are published before the event, but one describes a period
        # that has not begun. Publication alone would leak a forecast.
        features = pd.DataFrame(
            {
                "entity_id": ["A", "A"],
                "observed_at": pd.to_datetime(["2020-04-01", "2020-04-01"]),
                "valid_time": pd.to_datetime(["2020-04-01", "2020-06-01"]),
                "value": [1.0, 999.0],
            }
        )
        joined = as_of_join(
            events, features, on="entity_id", event_time_col="event_time"
        )

        assert joined["value"].tolist() == [1.0, 1.0]
        assert 999.0 not in joined["value"].tolist()

    def test_all_future_feature_times_yield_nan(self):
        events = pd.DataFrame(
            {"entity_id": ["A"], "event_time": pd.to_datetime(["2020-03-01"])}
        )
        features = pd.DataFrame(
            {
                "entity_id": ["A"],
                "observed_at": pd.to_datetime(["2020-04-01"]),
                "valid_time": pd.to_datetime(["2020-04-01"]),
                "value": [5.0],
            }
        )
        joined = as_of_join(
            events, features, on="entity_id", event_time_col="event_time"
        )

        assert np.isnan(joined.loc[0, "value"])

    def test_ties_on_observed_at_break_on_greatest_valid_time(self):
        events = pd.DataFrame(
            {"entity_id": ["A"], "event_time": pd.to_datetime(["2020-05-15"])}
        )
        features = pd.DataFrame(
            {
                "entity_id": ["A", "A"],
                "observed_at": pd.to_datetime(["2020-04-01", "2020-04-01"]),
                "valid_time": pd.to_datetime(["2020-03-01", "2020-04-01"]),
                "value": [1.0, 2.0],
            }
        )
        joined = as_of_join(
            events, features, on="entity_id", event_time_col="event_time"
        )

        assert joined["value"].tolist() == [2.0]

    def test_row_order_and_index_are_preserved(self):
        events = _join_events()
        joined = as_of_join(
            events,
            _join_features(),
            on="entity_id",
            event_time_col="event_time",
        )

        assert joined.index.equals(events.index)
        assert joined["event_time"].tolist() == events["event_time"].tolist()
        assert joined["entity_id"].tolist() == events["entity_id"].tolist()

    def test_inputs_are_not_mutated(self):
        events = _join_events()
        features = _join_features()
        events_before = events.copy(deep=True)
        features_before = features.copy(deep=True)

        as_of_join(
            events,
            features,
            on="entity_id",
            event_time_col="event_time",
        )

        pd.testing.assert_frame_equal(events, events_before)
        pd.testing.assert_frame_equal(features, features_before)

    def test_explicit_feature_cols_selects_only_those(self):
        joined = as_of_join(
            _join_events(),
            _join_features(),
            on="entity_id",
            event_time_col="event_time",
            feature_cols=["value"],
        )

        assert "value" in joined.columns
        assert "label" not in joined.columns
        assert "observed_at" not in joined.columns

    def test_default_feature_cols_exclude_key_and_timestamps(self):
        joined = as_of_join(
            _join_events(),
            _join_features(),
            on="entity_id",
            event_time_col="event_time",
        )

        assert "value" in joined.columns
        assert "label" in joined.columns
        assert "valid_time" not in joined.columns

    def test_missing_join_column_is_named(self):
        events = _join_events().drop(columns=["entity_id"])
        with pytest.raises(ValueError, match="entity_id"):
            as_of_join(
                events,
                _join_features(),
                on="entity_id",
                event_time_col="event_time",
            )

    def test_missing_event_time_column_is_named(self):
        with pytest.raises(ValueError, match="event_time_col"):
            as_of_join(
                _join_events(),
                _join_features(),
                on="entity_id",
                event_time_col="nope",
            )

    def test_missing_feature_timestamp_column_is_named(self):
        features = _join_features().drop(columns=["observed_at"])
        with pytest.raises(ValueError, match="observed_at"):
            as_of_join(
                _join_events(),
                features,
                on="entity_id",
                event_time_col="event_time",
            )

    def test_missing_explicit_feature_column_is_named(self):
        with pytest.raises(ValueError, match="nope"):
            as_of_join(
                _join_events(),
                _join_features(),
                on="entity_id",
                event_time_col="event_time",
                feature_cols=["nope"],
            )

    def test_non_datetime_event_time_is_rejected(self):
        events = pd.DataFrame({"entity_id": ["A", "B"], "event_time": [1, 2]})
        features = _join_features()
        with pytest.raises(ValueError, match="event_time"):
            as_of_join(
                events, features, on="entity_id", event_time_col="event_time"
            )

    def test_non_datetime_observed_at_is_rejected(self):
        events = pd.DataFrame(
            {"entity_id": ["A"], "event_time": pd.to_datetime(["2020-05-15"])}
        )
        features = _join_features().assign(observed_at=[1, 2, 3])
        with pytest.raises(ValueError, match="observed_at"):
            as_of_join(
                events, features, on="entity_id", event_time_col="event_time"
            )

    def test_empty_events_returns_empty_frame_with_columns(self):
        events = _join_events().iloc[0:0]
        joined = as_of_join(
            events,
            _join_features(),
            on="entity_id",
            event_time_col="event_time",
        )

        assert joined.empty
        assert list(joined.columns) == list(events.columns) + ["value", "label"]

    def test_composite_key_join(self):
        events = pd.DataFrame(
            {
                "entity_id": ["A", "A"],
                "book": ["x", "y"],
                "event_time": pd.to_datetime(["2020-05-15", "2020-05-15"]),
            }
        )
        features = pd.DataFrame(
            {
                "entity_id": ["A", "A"],
                "book": ["x", "y"],
                "observed_at": pd.to_datetime(["2020-04-01", "2020-04-01"]),
                "valid_time": pd.to_datetime(["2020-04-01", "2020-04-01"]),
                "value": [1.0, 2.0],
            }
        )
        joined = as_of_join(
            events,
            features,
            on=["entity_id", "book"],
            event_time_col="event_time",
        )

        assert joined["value"].tolist() == [1.0, 2.0]


class TestObjectDatetimeColumns:
    def test_object_datetime_columns_are_accepted(self):
        events = pd.DataFrame(
            {
                "entity_id": ["A"],
                "event_time": [pd.Timestamp("2020-05-15")],
            },
            dtype=object,
        )
        features = pd.DataFrame(
            {
                "entity_id": ["A"],
                "observed_at": [pd.Timestamp("2020-04-01")],
                "valid_time": [pd.Timestamp("2020-04-01")],
                "value": [1.0],
            },
            dtype=object,
        )
        joined = as_of_join(
            events, features, on="entity_id", event_time_col="event_time"
        )

        assert joined["value"].tolist() == [1.0]

    def test_tz_aware_event_time_is_normalised(self):
        events = pd.DataFrame(
            {
                "entity_id": ["A"],
                "event_time": pd.to_datetime(["2020-05-15T00:00:00Z"]),
            }
        )
        features = _join_features()
        joined = as_of_join(
            events, features, on="entity_id", event_time_col="event_time"
        )

        assert joined["value"].tolist() == [1.0]


# ---------------------------------------------------------------------------
# attach_pit_features_at_onsets: PIT features at stress-event onsets
# ---------------------------------------------------------------------------
def _vintage(valid_time, published_at, value):
    """A duck-typed vintage row as the store returns them."""
    return SimpleNamespace(
        time=pd.Timestamp(valid_time),
        published_at=pd.Timestamp(published_at),
        value=float(value),
    )


class TestAttachPitFeaturesAtOnsets:
    def test_freshest_published_wins_and_restatements_block_until_published(self):
        # Vintages of indicator F on source S (aware UTC).
        vintages = [
            _vintage("2020-01-01", "2020-01-01", 100.0),  # A: Jan period, first print
            _vintage("2020-01-01", "2020-03-01", 105.0),  # B: Jan period, restated in March
            _vintage("2020-02-01", "2020-02-01", 200.0),  # C: Feb period
            _vintage("2020-04-01", "2020-03-01", 999.0),  # D: Apr period, pre-announced in March
        ]
        onsets = [0, 1, 2, 3]
        onset_dates = [
            pd.Timestamp("2020-01-15"),  # only A known -> 100 (B's restatement not yet out)
            pd.Timestamp("2020-03-15"),  # A, B, C known; B freshest -> 105 (D's period not begun)
            pd.Timestamp("2020-01-01"),  # A published same day -> 100
            pd.Timestamp("2019-12-31"),  # nothing known yet -> None
        ]
        report = attach_pit_features_at_onsets(onsets, onset_dates, {"F": vintages}, "S")
        values = [entry["value"] for entry in report["F"]["onsets"]]
        assert values == [100.0, 105.0, 100.0, None]

    def test_indicator_with_no_vintages_on_the_source_is_skipped(self):
        report = attach_pit_features_at_onsets(
            [0], [pd.Timestamp("2020-01-15")], {"F": []}, "S"
        )
        assert report["F"] == {"skipped": "no vintages for this indicator on this source"}

    def test_no_events_skips_every_indicator(self):
        report = attach_pit_features_at_onsets(
            [], [], {"F": [_vintage("2020-01-01", "2020-01-01", 1.0)]}, "S"
        )
        assert report["F"] == {"skipped": "no stress events in the window"}

    def test_onset_dates_must_be_parallel_to_onsets(self):
        with pytest.raises(ValueError):
            attach_pit_features_at_onsets(
                [0, 1],
                [pd.Timestamp("2020-01-15")],
                {"F": [_vintage("2020-01-01", "2020-01-01", 1.0)]},
                "S",
            )

    def test_event_times_are_reported_as_utc_iso_and_value_is_numeric(self):
        report = attach_pit_features_at_onsets(
            [0],
            [pd.Timestamp("2020-01-15 12:30:00+00:00")],
            {"F": [_vintage("2020-01-01", "2020-01-01", 42.0)]},
            "S",
        )
        entry = report["F"]["onsets"][0]
        assert entry["event_time"] == "2020-01-15T12:30:00+00:00"
        assert entry["value"] == 42.0
