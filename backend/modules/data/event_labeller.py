"""Point-in-time event labelling for early-warning validation.

Why this module exists
----------------------

Every predictive claim the platform could make -- precision, recall, lead
time, false-positive rate in calm periods -- needs a binary event target:
"stress began here". None existed, so ``event_metrics.py`` (which implements
those statistics correctly, including the conservative earliest-alarm lead
time) had nothing to consume, and the census carried it as a ``decide``
item pending exactly this producer.

An event is defined **declaratively**, never learned silently:

* a monitored series' own horizon-cumulative move in a declared direction
  crosses a declared quantile of that same move distribution, and
* the crossing persists for a declared minimum duration, so a single
  spike is not an event and a slow burn is.

Labels are allowed to use future observations *by construction* -- an event
at ``t`` means "stress materialised in ``(t, t + horizon]``". That is what a
label is. What labels must never do is enter the feature side: nothing in
the inference path reads this module, and the docstring of every consumer
must keep saying so. Using a label to score a forecast is validation; using
it to make one is leakage.

Point-in-time discipline on the threshold
-----------------------------------------

The crossing threshold is a quantile of the horizon-move distribution. For
*historical* validation over a certified window the quantile may be computed
on that window (it is a property of the evaluation period, declared up
front). For *rolling/live* labelling the quantile must be computed on data
published before the labelled point; :func:`label_events` therefore takes an
explicit ``threshold_span`` (index slice) and refuses to default it: the
caller states what the threshold saw, and the result carries it back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = ["EventDefinition", "EventLabelling", "label_events"]


@dataclass(frozen=True)
class EventDefinition:
    """A declarative stress-event rule over one monitored series.

    Attributes:
        direction: ``"up"`` when rising values are stress (e.g. a basis or a
            default rate), ``"down"`` when falling values are (e.g. an
            index or a coverage ratio). ``None`` defers to the per-series
            orientation registered in ``backend.modules.data.semantics``;
            a series with neither is skipped by consumers rather than
            labelled with a guessed orientation.
        quantile: Quantile of the horizon-move distribution that defines the
            crossing. Must be in (0.5, 1) -- a median crossing is noise, not
            stress.
        horizon: Number of steps over which the move accumulates.
        min_duration: Minimum number of consecutive crossing steps for the
            episode to count as an event.
        decay: Fraction of the threshold below which the episode is
            considered over (default 0.5: the episode ends when the move
            falls back under half the crossing level).
    """

    direction: Optional[str] = "up"
    quantile: float = 0.95
    horizon: int = 5
    min_duration: int = 2
    decay: float = 0.5

    def __post_init__(self) -> None:
        if self.direction is not None and self.direction not in ("up", "down"):
            raise ValueError(f"direction must be 'up' or 'down', got {self.direction!r}")
        if not 0.5 < self.quantile < 1.0:
            raise ValueError(f"quantile must be in (0.5, 1), got {self.quantile}")
        if self.horizon < 1:
            raise ValueError(f"horizon must be >= 1, got {self.horizon}")
        if self.min_duration < 1:
            raise ValueError(f"min_duration must be >= 1, got {self.min_duration}")
        if not 0.0 < self.decay <= 1.0:
            raise ValueError(f"decay must be in (0, 1], got {self.decay}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "direction": self.direction,
            "quantile": self.quantile,
            "horizon": self.horizon,
            "min_duration": self.min_duration,
            "decay": self.decay,
        }


@dataclass(frozen=True)
class EventLabelling:
    """The labelled series plus everything needed to audit it."""

    events: np.ndarray           # True inside an event episode
    onsets: np.ndarray           # indices where episodes begin
    threshold: float             # the crossing level in move units
    move: np.ndarray             # the horizon-cumulative signed move
    definition: EventDefinition
    threshold_span: Tuple[int, int]
    n_events: int = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "n_events", int(self.onsets.size))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "definition": self.definition.to_dict(),
            "threshold": float(self.threshold),
            "threshold_span": list(self.threshold_span),
            "n_events": self.n_events,
            "onsets": [int(i) for i in self.onsets],
        }


def horizon_move(values: np.ndarray, horizon: int, direction: str) -> np.ndarray:
    """Signed horizon-cumulative move, oriented so stress is positive."""
    series = np.asarray(values, dtype=float)
    move = series[horizon:] - series[:-horizon]
    aligned = np.full(series.shape, np.nan)
    aligned[horizon:] = move
    if direction == "down":
        aligned = -aligned
    return aligned


def label_events(
    values: Sequence[float],
    definition: EventDefinition,
    *,
    threshold_span: Optional[Tuple[int, int]] = None,
) -> EventLabelling:
    """Label stress episodes on one series.

    Args:
        values: The monitored series, time-ordered, gaps as NaN.
        definition: The declarative rule.
        threshold_span: ``(start, stop)`` index span whose moves define the
            crossing quantile. ``None`` means "the whole series" and is only
            honest for historical validation over a declared window; live
            callers must pass a span that ends at or before the labelled
            point. The chosen span is carried on the result either way.

    Returns:
        An :class:`EventLabelling` with the episode mask, onsets, threshold
        and the oriented move series.
    """
    series = np.asarray(values, dtype=float).ravel()
    if series.size < definition.horizon + definition.min_duration:
        raise ValueError(
            f"series of {series.size} points cannot support horizon="
            f"{definition.horizon}, min_duration={definition.min_duration}"
        )

    move = horizon_move(series, definition.horizon, definition.direction)

    if threshold_span is None:
        span = (0, series.size)
    else:
        start, stop = threshold_span
        if not 0 <= start < stop <= series.size:
            raise ValueError(f"threshold_span {threshold_span} outside [0, {series.size})")
        span = (start, stop)

    observed = move[span[0]:span[1]]
    observed = observed[np.isfinite(observed)]
    if observed.size == 0:
        raise ValueError("no finite horizon moves inside threshold_span")
    threshold = float(np.quantile(observed, definition.quantile))

    crossing = np.isfinite(move) & (move >= threshold)
    ended = np.isfinite(move) & (move < threshold * definition.decay)

    events = np.zeros(series.size, dtype=bool)
    onsets = []
    index = 0
    while index < series.size:
        if crossing[index]:
            start = index
            end = index
            probe = index
            while probe < series.size:
                if crossing[probe]:
                    end = probe
                elif ended[probe]:
                    break
                probe += 1
            duration = end - start + 1
            if duration >= definition.min_duration:
                events[start:end + 1] = True
                onsets.append(start)
            index = probe + 1
        else:
            index += 1

    return EventLabelling(
        events=events,
        onsets=np.asarray(onsets, dtype=int),
        threshold=threshold,
        move=move,
        definition=definition,
        threshold_span=span,
    )


def events_to_frame(labelling: EventLabelling, index: Optional[pd.Index] = None) -> pd.DataFrame:
    """Materialise a labelling as a frame for reports and persistence."""
    idx = index if index is not None else pd.RangeIndex(labelling.events.size)
    return pd.DataFrame(
        {
            "event": labelling.events,
            "onset": np.isin(np.arange(labelling.events.size), labelling.onsets),
            "move": labelling.move,
        },
        index=idx,
    )
