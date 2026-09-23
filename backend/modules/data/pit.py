"""Point-in-time (vintage) storage for macro and market series.

Why this module exists
----------------------

BEACON stored each indicator as a single column of values and forward-filled the
gaps. That design hides two distinct look-ahead bugs.

1. **Revisions are invisible when only the latest value is kept.** Official
   series are restated. The GDP figure for Q1 2020 was first published on
   2020-04-30 as ``100.0``, restated on 2020-05-28 to ``95.0``, and restated
   again on 2020-06-25 to ``90.0``. A table that keeps only "the value of Q1
   2020" keeps ``90.0``. A model reading that row is told a number no market
   participant could have known until 2020-06-25, so a backtest that "predicted"
   the recession looks prescient for reasons that have nothing to do with the
   model. The information simply was not there yet.

2. **Forward-fill fabricates the pre-gap level.** ``ffill`` copies the last
   observed value into later periods. When the values being filled are *final*
   values, the newest number is projected backwards and forwards across periods
   that predate its publication. Absence of information is silently replaced by
   a number, and at the join boundary the replacement is always the future
   value -- exactly the leak the join is supposed to prevent.

The fix is to store every **vintage** of every observation. An
:class:`Observation` carries both the period it describes (``valid_time``, e.g.
Q1 2020) and the moment it became known (``observed_at``, the vintage, e.g.
2020-05-28). :class:`PITStore` never exposes a vintage that had not been
published by the caller's ``as_of`` timestamp, and it never fills a missing
period: an as-of query with no published vintage for a period returns no row for
that period. Absence of information is represented as absence, not as a carried
forward number.

:func:`as_of_join` applies the same discipline when attaching features to
events. A feature row qualifies only if it was both **published** by the event
time (``observed_at <= event_time``) and **describes** a period that had already
begun (``valid_time <= event_time``). The second condition matters because
publication is not the only way to see the future: a forecast, a survey
expectation, or a pre-announcement can be published early while describing a
period that has not happened yet. Without it, such a row attaches to the event
and the feature set contains the answer.

Boundary policy
---------------

All comparisons are inclusive: a vintage is known *at* its ``observed_at``
instant, so ``as_of == observed_at`` exposes it. Likewise ``valid_time ==
event_time`` is in the past (the period has begun) and is allowed. This matches
the convention that a release timestamp marks the first instant the value is
available. When several vintages share an ``observed_at`` timestamp, the highest
``revision`` wins, since a restatement carrying the same publication stamp is
the more recently issued number.

Timestamps are normalised to timezone-naive UTC on construction so that a mix of
aware and naive inputs cannot silently fail to compare.

Production status (recorded so the gap is a decision, not a silence)
--------------------------------------------------------------------

``PITStore`` and ``Observation`` are wired: the bilateral-exposure store
(``services/bilateral_exposure_store``) persists exposure vintages through them
and serves ``load_as_of`` queries. :func:`as_of_join` is wired too:
:func:`attach_pit_features_at_onsets` uses it to attach point-in-time features
to the labelled stress events in ``run_backtest``'s event-metrics path (opt-in,
via the job's ``pit_features`` parameter), reading the indicator vintages the
point-in-time store exposes. The reachability census walks modules, not
functions, so this note is where the function-level status lives.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

__all__ = [
    "Observation",
    "PITStore",
    "as_of_join",
    "attach_pit_features_at_onsets",
    "OBSERVATION_COLUMNS",
]

#: Column order guaranteed by every frame this module returns.
OBSERVATION_COLUMNS: Tuple[str, ...] = (
    "entity_id",
    "series_id",
    "valid_time",
    "observed_at",
    "value",
    "revision",
)


def _normalise_timestamp(value: object, field: str) -> pd.Timestamp:
    """Coerce ``value`` to a timezone-naive UTC timestamp, naming ``field`` on failure.

    Naive input is assumed to already be UTC. Aware input is converted so that a
    tz-aware ``as_of`` can be compared against tz-naive stored vintages instead
    of raising a bare ``TypeError`` far from the call site.
    """
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a timestamp, got {value!r}") from exc
    if pd.isna(stamp):
        raise ValueError(f"{field} must not be NaT")
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    return stamp


def _is_datetime_like(series: pd.Series) -> bool:
    """Whether a column can be treated as timestamps.

    Object columns are accepted only when they hold actual datetime objects.
    Numeric columns are *not* datetime-like: ``pd.to_datetime`` would happily
    reinterpret epoch integers as nanoseconds, which would let a caller pass a
    plain counter as a time axis and silently produce a wrong join.
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if series.dtype == object:
        non_null = series.dropna()
        if non_null.empty:
            return True
        return all(
            isinstance(item, (pd.Timestamp, datetime, np.datetime64))
            for item in non_null
        )
    return False


def _datetime_column(series: pd.Series, field: str) -> pd.Series:
    """Validate and normalise one column to timezone-naive UTC ``datetime64``."""
    if not _is_datetime_like(series):
        raise ValueError(
            f"{field} must be datetime-like, got dtype {series.dtype}"
        )
    converted = pd.to_datetime(series)
    if isinstance(converted.dtype, pd.DatetimeTZDtype):
        converted = converted.dt.tz_convert("UTC").dt.tz_localize(None)
    return converted


@dataclass(frozen=True)
class Observation:
    """One vintage of one series value.

    Attributes:
        entity_id: Whose value this is, e.g. ``"US"`` or ``"BANK_A"``.
        series_id: Which series, e.g. ``"GDP"`` or ``"SOFR"``.
        valid_time: The period the value *describes* (e.g. Q1 2020).
        observed_at: When the value *became known* -- the vintage. A restatement
            gets a later ``observed_at`` than the print it replaces.
        value: The number published in this vintage.
        revision: ``0`` for the first print, ``1`` for the first restatement,
            and so on. Revisions are non-negative and monotone within a vintage
            chain.

    Raises:
        ValueError: If ``value`` is not finite, if ``observed_at`` precedes
            ``valid_time`` (a value cannot be known before the period it
            describes begins), or if ``revision`` is negative. Each message
            names the offending field.
    """

    entity_id: str
    series_id: str
    valid_time: pd.Timestamp
    observed_at: pd.Timestamp
    value: float
    revision: int = 0

    def __post_init__(self) -> None:
        try:
            numeric = float(self.value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"value must be numeric, got {self.value!r}") from exc
        if not np.isfinite(numeric):
            raise ValueError(f"value must be finite, got {self.value!r}")

        valid_time = _normalise_timestamp(self.valid_time, "valid_time")
        observed_at = _normalise_timestamp(self.observed_at, "observed_at")
        if observed_at < valid_time:
            raise ValueError(
                "observed_at must not precede valid_time: a value cannot be "
                f"known before the period it describes (observed_at="
                f"{observed_at!r}, valid_time={valid_time!r})"
            )

        if not isinstance(self.revision, (int, np.integer)) or isinstance(
            self.revision, bool
        ):
            raise ValueError(f"revision must be an integer, got {self.revision!r}")
        revision = int(self.revision)
        if revision < 0:
            raise ValueError(f"revision must be non-negative, got {revision!r}")

        object.__setattr__(self, "entity_id", str(self.entity_id))
        object.__setattr__(self, "series_id", str(self.series_id))
        object.__setattr__(self, "valid_time", valid_time)
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "value", numeric)
        object.__setattr__(self, "revision", revision)

    @property
    def key(self) -> Tuple[str, str, pd.Timestamp, pd.Timestamp, int]:
        """Identity used for duplicate detection."""
        return (
            self.entity_id,
            self.series_id,
            self.valid_time,
            self.observed_at,
            self.revision,
        )

    def to_dict(self) -> Dict[str, object]:
        """Plain-dict view, in :data:`OBSERVATION_COLUMNS` order."""
        return {
            "entity_id": self.entity_id,
            "series_id": self.series_id,
            "valid_time": self.valid_time,
            "observed_at": self.observed_at,
            "value": self.value,
            "revision": self.revision,
        }


def _empty_frame() -> pd.DataFrame:
    """An empty frame carrying the module's column contract and dtypes."""
    frame = pd.DataFrame.from_records([], columns=list(OBSERVATION_COLUMNS))
    frame["valid_time"] = pd.to_datetime(frame["valid_time"])
    frame["observed_at"] = pd.to_datetime(frame["observed_at"])
    frame["value"] = frame["value"].astype("float64")
    frame["revision"] = frame["revision"].astype("int64")
    return frame


class PITStore:
    """Append-only store of observation vintages with as-of retrieval.

    The store keeps every vintage it is given. Retrieval never interpolates,
    forward-fills, or back-fills: a query returns one row per
    ``(series_id, valid_time)`` -- the most recent vintage published by ``as_of``
    -- and nothing at all for periods whose first vintage postdates ``as_of``.

    Duplicate identity is ``(entity_id, series_id, valid_time, observed_at,
    revision)``. Re-appending an identical observation is a no-op, so ingestion
    is safe to retry. Re-appending the *same identity* with a different value is
    rejected: a published vintage is immutable, and a correction must be a new
    vintage (a higher ``revision``, or a later ``observed_at``).
    """

    def __init__(self) -> None:
        self._records: Dict[
            Tuple[str, str, pd.Timestamp, pd.Timestamp, int], Observation
        ] = {}

    def append(self, observations: Iterable[Observation]) -> int:
        """Store ``observations``, returning how many were newly added.

        Idempotent for identical re-appends. Raises ``ValueError`` when the same
        identity is re-appended with a different value, because silently
        overwriting a stored vintage would let the store return a number that
        never existed as of the rewritten timestamp.
        """
        added = 0
        for observation in observations:
            if not isinstance(observation, Observation):
                raise TypeError(
                    "append expects Observation instances, got "
                    f"{type(observation).__name__}"
                )
            key = observation.key
            existing = self._records.get(key)
            if existing is None:
                self._records[key] = observation
                added += 1
            elif existing.value != observation.value:
                raise ValueError(
                    "conflicting value for an already-stored vintage "
                    f"(entity_id={observation.entity_id!r}, "
                    f"series_id={observation.series_id!r}, "
                    f"valid_time={observation.valid_time!r}, "
                    f"observed_at={observation.observed_at!r}, "
                    f"revision={observation.revision}); publish a higher "
                    "revision instead of rewriting the vintage"
                )
        return added

    def __len__(self) -> int:
        return len(self._records)

    def to_frame(self) -> pd.DataFrame:
        """The full raw store: every vintage, sorted, one row per observation."""
        if not self._records:
            return _empty_frame()
        frame = pd.DataFrame.from_records(
            [observation.to_dict() for observation in self._records.values()],
            columns=list(OBSERVATION_COLUMNS),
        )
        frame["valid_time"] = pd.to_datetime(frame["valid_time"])
        frame["observed_at"] = pd.to_datetime(frame["observed_at"])
        frame["value"] = frame["value"].astype("float64")
        frame["revision"] = frame["revision"].astype("int64")
        frame = frame.sort_values(
            ["entity_id", "series_id", "valid_time", "observed_at", "revision"],
            kind="mergesort",
        )
        return frame.reset_index(drop=True)

    def query(
        self,
        entity_id: str,
        series_id: Optional[str] = None,
        *,
        as_of: object,
        valid_from: Optional[object] = None,
        valid_to: Optional[object] = None,
    ) -> pd.DataFrame:
        """Vintages known at ``as_of``, one row per ``(series, valid_time)``.

        Args:
            entity_id: The entity to query.
            series_id: Restrict to one series; ``None`` returns every series.
            as_of: Only vintages with ``observed_at <= as_of`` are eligible. The
                comparison is inclusive -- a value is known at its release
                instant.
            valid_from: Inclusive lower bound on ``valid_time``.
            valid_to: Inclusive upper bound on ``valid_time``.

        Returns:
            A frame with :data:`OBSERVATION_COLUMNS`, sorted by ``valid_time``
            (then ``series_id``). For each ``(series_id, valid_time)`` only the
            greatest eligible ``observed_at`` is returned; ties on
            ``observed_at`` are broken by the greatest ``revision``. Periods
            with no eligible vintage are simply absent -- never filled with a
            neighbouring value.
        """
        as_of_stamp = _normalise_timestamp(as_of, "as_of")
        frame = self.to_frame()

        mask = (frame["entity_id"] == entity_id) & (
            frame["observed_at"] <= as_of_stamp
        )
        if series_id is not None:
            mask &= frame["series_id"] == series_id
        if valid_from is not None:
            mask &= frame["valid_time"] >= _normalise_timestamp(
                valid_from, "valid_from"
            )
        if valid_to is not None:
            mask &= frame["valid_time"] <= _normalise_timestamp(valid_to, "valid_to")

        eligible = frame.loc[mask]
        if eligible.empty:
            return _empty_frame()

        eligible = eligible.sort_values(
            ["series_id", "valid_time", "observed_at", "revision"],
            kind="mergesort",
        )
        deduped = eligible.drop_duplicates(
            subset=["series_id", "valid_time"], keep="last"
        )
        deduped = deduped.sort_values(
            ["valid_time", "series_id"], kind="mergesort"
        )
        return deduped.loc[:, list(OBSERVATION_COLUMNS)].reset_index(drop=True)

    def vintages(
        self, entity_id: str, series_id: str
    ) -> List[pd.Timestamp]:
        """Sorted distinct publication timestamps for one entity/series pair."""
        frame = self.to_frame()
        mask = (frame["entity_id"] == entity_id) & (frame["series_id"] == series_id)
        observed = frame.loc[mask, "observed_at"]
        return sorted(pd.Timestamp(value) for value in observed.unique())

    def latest_as_of(
        self, entity_id: str, series_id: str
    ) -> Optional[pd.Timestamp]:
        """The most recent publication timestamp for one entity/series, or ``None``."""
        stamps = self.vintages(entity_id, series_id)
        return stamps[-1] if stamps else None


def as_of_join(
    events: pd.DataFrame,
    features: pd.DataFrame,
    *,
    on: Union[str, Sequence[str]],
    event_time_col: str,
    observed_at_col: str = "observed_at",
    valid_time_col: str = "valid_time",
    feature_cols: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Attach to each event the feature row that was the freshest one known then.

    This is the leak-free alternative to a plain ``merge`` (which sees every
    vintage, including future ones) and to ``ffill`` (which invents values for
    periods that have none). A feature row qualifies for an event only when both
    hold:

    * ``feature.observed_at <= event[event_time_col]`` -- it had been published;
    * ``feature.valid_time <= event[event_time_col]`` -- the period it describes
      had already begun. This second condition blocks forecasts, survey
      expectations, and pre-announcements, which are published early but refer to
      a period still in the future.

    Among qualifying rows the greatest ``observed_at`` wins, with ties broken by
    the greatest ``valid_time``. Events with no qualifying row receive ``NaN``
    for the appended columns; nothing is forward-filled or back-filled.

    Args:
        events: Event rows. Never mutated.
        features: Candidate feature rows. Never mutated.
        on: Entity key column, present in both frames. A sequence of names is
            accepted for a composite key.
        event_time_col: Timestamp column in ``events``.
        observed_at_col: Publication-timestamp column in ``features``.
        valid_time_col: Described-period column in ``features``.
        feature_cols: Columns to append. Defaults to every ``features`` column
            other than the key and the two timestamp columns, minus any name
            already present in ``events`` (overwriting event data by default
            would be a silent data loss).

    Returns:
        A new frame: ``events`` order and index preserved, with the chosen
        feature columns appended.

    Raises:
        ValueError: If a referenced column is missing, or if ``event_time_col``,
            ``observed_at_col``, or ``valid_time_col`` is not datetime-like.
    """
    if not isinstance(events, pd.DataFrame) or not isinstance(features, pd.DataFrame):
        raise TypeError("events and features must be pandas DataFrames")

    on_keys: List[str] = [on] if isinstance(on, str) else list(on)
    if not on_keys:
        raise ValueError("on must name at least one entity key column")

    for column in on_keys:
        if column not in events.columns:
            raise ValueError(f"events is missing join column {column!r}")
        if column not in features.columns:
            raise ValueError(f"features is missing join column {column!r}")

    if event_time_col not in events.columns:
        raise ValueError(
            f"events is missing event_time_col {event_time_col!r}"
        )
    if observed_at_col not in features.columns:
        raise ValueError(
            f"features is missing observed_at_col {observed_at_col!r}"
        )
    if valid_time_col not in features.columns:
        raise ValueError(
            f"features is missing valid_time_col {valid_time_col!r}"
        )

    if feature_cols is None:
        feature_cols = [
            column
            for column in features.columns
            if column not in on_keys
            and column not in (observed_at_col, valid_time_col)
            and column not in events.columns
        ]
    else:
        feature_cols = list(feature_cols)
        for column in feature_cols:
            if column not in features.columns:
                raise ValueError(f"features is missing feature column {column!r}")

    event_times = _datetime_column(events[event_time_col], event_time_col)
    feature_observed = _datetime_column(features[observed_at_col], observed_at_col)
    feature_valid = _datetime_column(features[valid_time_col], valid_time_col)

    working = events.copy()
    working["__pit_row__"] = np.arange(len(working), dtype=np.int64)
    working["__pit_event_time__"] = event_times.to_numpy()

    candidate: Dict[str, object] = {key: features[key] for key in on_keys}
    candidate["__pit_observed__"] = feature_observed.to_numpy()
    candidate["__pit_valid__"] = feature_valid.to_numpy()
    for column in feature_cols:
        candidate["__pit_feature__" + column] = features[column].to_numpy()
    feature_frame = pd.DataFrame(candidate)

    merged = working.merge(feature_frame, on=on_keys, how="inner")
    merged = merged.loc[
        (merged["__pit_observed__"] <= merged["__pit_event_time__"])
        & (merged["__pit_valid__"] <= merged["__pit_event_time__"])
    ]

    chosen = merged
    if not chosen.empty:
        chosen = chosen.sort_values(
            ["__pit_row__", "__pit_observed__", "__pit_valid__"],
            kind="mergesort",
        )
        chosen = chosen.drop_duplicates(subset="__pit_row__", keep="last")

    result = events.copy()
    row_ids = np.arange(len(events), dtype=np.int64)
    if chosen.empty:
        for column in feature_cols:
            result[column] = np.nan
    else:
        chosen_rows = chosen["__pit_row__"].to_numpy()
        for column in feature_cols:
            values = pd.Series(
                chosen["__pit_feature__" + column].to_numpy(), index=chosen_rows
            )
            result[column] = values.reindex(row_ids).to_numpy()

    return result


def _iso_utc(stamp: object) -> str:
    """ISO-8601 string for a timestamp, naive input treated as UTC."""
    ts = pd.Timestamp(stamp)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("UTC").isoformat()


def attach_pit_features_at_onsets(
    onsets: Sequence,
    onset_dates: Sequence,
    vintages_by_indicator: Dict[str, Sequence],
    source: str,
) -> Dict[str, Any]:
    """Attach point-in-time feature values to each stress-event onset.

    ``onsets`` and ``onset_dates`` are parallel: ``onset_dates[i]`` is the
    timestamp of ``onsets[i]``. ``vintages_by_indicator`` maps each declared
    feature indicator to the sequence of its vintage rows (each row exposes
    ``.time`` (the period it describes), ``.published_at`` (when it became
    known) and ``.value``), all on ``source``.

    For each indicator the freshest vintage *published at or before the
    onset* whose *period had already begun* is attached, via :func:`as_of_join`
    -- the same leak-free rule the exposure store uses. That is what makes this
    an as-of read rather than a plain merge: a restatement published after the
    onset is invisible, and a value whose period had not begun (a forecast, a
    pre-announcement) is blocked.

    Returns one entry per declared indicator: ``{"onsets": [{"event_time",
    "value"}, ...]}`` parallel to ``onsets``, or ``{"skipped": reason}`` when the
    indicator has no vintage on the source, or there are no events. A ``value``
    is ``None`` when no qualifying vintage exists for that onset -- it is never
    forward-filled.
    """
    onsets = list(onsets)
    if not onsets:
        return {
            indicator: {"skipped": "no stress events in the window"}
            for indicator in vintages_by_indicator
        }
    if len(onset_dates) != len(onsets):
        raise ValueError("onset_dates must be parallel to onsets")

    events = pd.DataFrame(
        {
            "entity": [source] * len(onsets),
            "event_time": list(onset_dates),
        }
    )

    report: Dict[str, Any] = {}
    for indicator, vintages in vintages_by_indicator.items():
        vintages = list(vintages)
        if not vintages:
            report[indicator] = {
                "skipped": "no vintages for this indicator on this source"
            }
            continue
        features = pd.DataFrame(
            {
                "entity": [source] * len(vintages),
                "valid_time": [vintage.time for vintage in vintages],
                "observed_at": [vintage.published_at for vintage in vintages],
                "value": [vintage.value for vintage in vintages],
            }
        )
        joined = as_of_join(
            events,
            features,
            on="entity",
            event_time_col="event_time",
            observed_at_col="observed_at",
            valid_time_col="valid_time",
            feature_cols=["value"],
        )
        values = joined["value"].to_numpy()
        report[indicator] = {
            "onsets": [
                {
                    "event_time": _iso_utc(onset_dates[i]),
                    "value": None if not np.isfinite(values[i]) else float(values[i]),
                }
                for i in range(len(onsets))
            ]
        }
    return report
