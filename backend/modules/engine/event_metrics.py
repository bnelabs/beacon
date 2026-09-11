"""Event-based evaluation for systemic-risk early-warning signals.

Why this module exists
----------------------

BEACON originally scored its risk models with portfolio statistics -- Sharpe,
Sortino, maximum drawdown and Value-at-Risk -- computed on a sign-flipped risk
score. Those functions were deleted in Phase 1 because every one of them is
defined on a *price or return series*, and a risk score is neither:

1. **A risk score is a latent state, not an asset price.** Sharpe and Sortino
   divide a mean return by a dispersion of returns. The score has no return, no
   notional, and no holding period, so the numerator and denominator have no
   units in common and the ratio is not an estimate of anything. Feeding it a
   sign-flipped score only renamed the input; it did not create an economic
   quantity.
2. **Drawdown is path-dependent in price space.** A drawdown is the decline of
   a wealth process from its running peak. Applying it to ``1 - risk`` measures
   how far a bounded index has fallen from its own running maximum -- a fact
   about the score's serial correlation, not about losses borne by anyone.
3. **VaR needs a loss distribution on a horizon.** "VaR at 99%" of a risk score
   is a quantile of the model's own output, so it is a statement about the
   model, not about the system it is supposed to warn about. It is circular.

The defensible evaluation for an early-warning system is *event-based*: did the
signal fire before the events that matter, how much warning did it give, and how
often did it cry wolf. That is what this module computes. The events are the
systemic ones the system exists to anticipate -- CCP default-fund activation,
an MMF breaking the buck, an interbank freeze -- encoded as a boolean mask over
the same time grid as the risk score.

The three questions
===================

* :func:`roc_auc` / :func:`average_precision` answer *discrimination*: does the
  score rank event periods above quiet ones? This is the ranking quality that
  the plan asks for. Precision-recall is reported alongside ROC because the
  events are rare, and ROC overstates usefulness under severe imbalance.
* :func:`lead_time_stats` answers *timeliness*: how many steps before an event
  did the alarm arrive? The target is 1-2 weeks of warning; a detector that only
  fires simultaneously with the event is accurate but useless as a warning, so
  simultaneous alarms are recorded separately as ``n_zero_lead``.
* :func:`false_alarm_stats` answers *cost*: how many alarms were not followed by
  an event, per alarm and per period. A detector that fires constantly has
  perfect recall and is worthless; this is the quantity an operator pays for.

Deliberate design choices
=========================

* **Undefined statistics are ``nan``, never a stand-in.** A single-class label
  vector has no ROC AUC; an event set with no detected event has no lead-time
  distribution. Returning ``0.0`` or ``0.5`` there would be read downstream as a
  measured value. ``nan`` propagates the "not measured" state, and
  :func:`event_summary` deliberately leaves it as ``nan`` so that strict
  serialisation (``json.dumps(..., allow_nan=False)``) fails loudly rather than
  publishing a fabricated number.
* **Ties use average ranks.** AUROC is the Mann-Whitney U statistic. With tied
  scores the correct contribution of a tied pair is one half, which average
  ranks produce exactly; breaking ties by array position makes the metric depend
  on input order and is the usual bug in hand-rolled AUCs.
* **Average precision is the step-wise sum, not the trapezoid.** For rare
  events the trapezoidal area under the PR curve linearly interpolates between
  operating points that the detector cannot actually realise and is therefore
  optimistic. The step-wise definition (the one ``sklearn`` uses) weights the
  precision at each threshold by the *increase* in recall there.
* **Warning windows are strict.** An alarm at ``t`` only counts for an event at
  ``e`` when ``t < e <= t + horizon``: an alarm simultaneous with the event gave
  the operator no time to act, so it is not a warning. See
  :func:`false_alarm_stats` for why the event-side window is written backwards.

Only ``numpy`` and ``pandas``-style array inputs are used here; ``scikit-learn``
appears only in the test suite, where it cross-checks the maths.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence, Tuple, Union

import numpy as np

__all__ = [
    "roc_auc",
    "average_precision",
    "precision_recall_curve",
    "precision_at_recall",
    "lead_time_stats",
    "false_alarm_stats",
    "event_summary",
]

ArrayLike = Union[Sequence[float], np.ndarray]


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------
def _as_float_vector(values: ArrayLike, name: str) -> np.ndarray:
    """Coerce array-like input to a 1-D float array, or raise ``ValueError``."""
    try:
        array = np.asarray(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} could not be interpreted as numeric: {exc}") from exc
    return array.ravel()


def _validate_binary_inputs(
    labels: ArrayLike, scores: ArrayLike
) -> Tuple[np.ndarray, np.ndarray]:
    """Validate a ``(labels, scores)`` pair and return ``(bool_mask, scores)``.

    Labels are read as a boolean event indicator: any non-zero value is an
    event, which keeps boolean, integer and ``0.0``/``1.0`` encodings working
    without a separate code path.

    Raises:
        ValueError: if the two arrays differ in length, either is empty, or a
            score is ``nan``/``inf``. A non-finite score cannot be ranked, so
            silently dropping it would change the denominator of the metric
            without saying so.
    """
    scores_arr = _as_float_vector(scores, "scores")
    labels_arr = _as_float_vector(labels, "labels")
    if scores_arr.size != labels_arr.size:
        raise ValueError(
            f"labels and scores must have the same length, got "
            f"{labels_arr.size} and {scores_arr.size}"
        )
    if scores_arr.size == 0:
        raise ValueError("labels and scores must not be empty")
    if not np.all(np.isfinite(scores_arr)):
        raise ValueError("scores must be finite; nan/inf cannot be ranked")
    if not np.all(np.isfinite(labels_arr)):
        raise ValueError("labels must be finite")
    return labels_arr != 0.0, scores_arr


def _as_boolean_mask(mask: ArrayLike, name: str) -> np.ndarray:
    """Return ``mask`` as a 1-D boolean array, rejecting non-boolean dtypes.

    Integer ``0``/``1`` masks are rejected deliberately. Which integer counts as
    an event is a convention, and a silent ``astype(bool)`` would accept any
    non-zero code as "event" -- including sentinel codes such as ``-1``.
    """
    array = np.asarray(mask)
    if array.size == 0:
        return np.zeros(0, dtype=bool)
    if array.dtype != np.bool_:
        raise ValueError(
            f"{name} must be a boolean array, got dtype {array.dtype}"
        )
    return array.ravel()


def _validate_window(value: Any, name: str) -> int:
    """Validate a non-negative integer window length."""
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer, got {value!r}")
    window = int(value)
    if window < 0:
        raise ValueError(f"{name} must be non-negative, got {window}")
    return window


# ---------------------------------------------------------------------------
# Ranking metrics
# ---------------------------------------------------------------------------
def _average_ranks(scores: np.ndarray) -> np.ndarray:
    """Mid-ranks of ``scores`` (ties share the mean of the ranks they span).

    ``rankdata(method="average")`` is implemented here in ``numpy`` rather than
    pulled from ``scipy``: the only property required is that a tie of size
    ``k`` contributes ``k * (mean rank)``, which a grouped cumulative sum gives
    exactly and in ``O(n log n)``.
    """
    n = scores.size
    order = np.argsort(scores, kind="stable")
    sorted_scores = scores[order]
    # Group id per sorted position: increments wherever the score changes.
    group = np.concatenate(
        ([0], np.cumsum(sorted_scores[1:] != sorted_scores[:-1]))
    )
    sorted_ranks = np.arange(1, n + 1, dtype=float)
    group_sums = np.bincount(group, weights=sorted_ranks)
    group_sizes = np.bincount(group)
    ranks_sorted = (group_sums / group_sizes)[group]
    ranks = np.empty(n, dtype=float)
    ranks[order] = ranks_sorted
    return ranks


def roc_auc(labels: ArrayLike, scores: ArrayLike) -> float:
    """Area under the ROC curve, as the Mann-Whitney U statistic.

    ``U`` is the number of positive/negative pairs the score ranks correctly,
    counting a tied pair as one half. With ``n_pos`` positives and ``n_neg``
    negatives::

        U   = sum(ranks of positives) - n_pos * (n_pos + 1) / 2
        AUC = U / (n_pos * n_neg)

    using **average** ranks for tied scores. This is exactly the trapezoidal
    area under the ROC curve, but computing it from ranks makes the tie
    treatment explicit; the usual hand-rolled AUC assigns tied pairs 0 or 1
    depending on input order and is not order-invariant.

    A risk score is a latent state, so the only thing this number claims is
    *rank* separation between event periods and quiet periods -- it does not
    claim the score is a return, and it is not annualised or scaled.

    Returns:
        The AUC in ``[0, 1]``, or ``nan`` when ``labels`` contains only one
        class. The statistic is undefined there; returning ``0.5`` (chance) or
        ``0.0`` would be fabricated evidence of discrimination quality.

    Raises:
        ValueError: if lengths differ, either array is empty, or a score is
            non-finite.
    """
    positive, scores_arr = _validate_binary_inputs(labels, scores)
    n_pos = int(positive.sum())
    n_neg = int(positive.size - n_pos)
    if n_pos == 0 or n_neg == 0:
        return float("nan")

    ranks = _average_ranks(scores_arr)
    u_statistic = float(ranks[positive].sum()) - n_pos * (n_pos + 1) / 2.0
    return float(u_statistic / (n_pos * n_neg))


def _precision_recall_curve(
    positive: np.ndarray, scores: np.ndarray
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Step-wise PR curve for already-validated inputs.

    Thresholds are the distinct observed scores in increasing order. For each
    threshold, a sample is predicted positive when ``score >= threshold``, which
    is the convention ``sklearn.metrics.precision_recall_curve`` uses. Tied
    scores move together, so a tie never manufactures an intermediate operating
    point that the detector could not choose.
    """
    # Descending, stable: the reference convention. Rank order within a tie does
    # not affect precision or recall because tied scores share a threshold.
    order = np.argsort(-scores, kind="stable")
    scores_sorted = scores[order]
    truth_sorted = positive[order].astype(float)
    n = scores_sorted.size

    # Last index of each group of equal scores, plus the final sample.
    distinct = np.flatnonzero(np.diff(scores_sorted) != 0.0)
    threshold_indices = np.concatenate((distinct, [n - 1]))

    cumulative = np.cumsum(truth_sorted)
    true_positives = cumulative[threshold_indices]
    false_positives = 1.0 + threshold_indices - true_positives
    predicted_positives = true_positives + false_positives
    precision = np.divide(
        true_positives,
        predicted_positives,
        out=np.zeros_like(true_positives),
        where=predicted_positives != 0,
    )

    total_positives = true_positives[-1]
    if total_positives == 0:
        # No positives: recall is conventionally reported as 1 everywhere.
        # average_precision refuses this input instead of reporting the
        # resulting 0.0 (see the module docstring).
        recall = np.ones_like(true_positives)
    else:
        recall = true_positives / total_positives

    thresholds = scores_sorted[threshold_indices]
    # Reverse to increasing-threshold order and append the anchor point that has
    # no threshold: precision=1 at recall=0.
    return (
        np.concatenate((precision[::-1], [1.0])),
        np.concatenate((recall[::-1], [0.0])),
        thresholds[::-1].copy(),
    )


def precision_recall_curve(
    labels: ArrayLike, scores: ArrayLike
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Precision/recall at each distinct score threshold.

    Returns ``(precision, recall, thresholds)`` in increasing threshold order,
    matching ``sklearn.metrics.precision_recall_curve``: ``precision`` and
    ``recall`` have length ``len(thresholds) + 1``, and the final pair
    ``(precision=1, recall=0)`` is an anchor with no corresponding threshold.

    Raises:
        ValueError: if lengths differ, either array is empty, or a score is
            non-finite.
    """
    positive, scores_arr = _validate_binary_inputs(labels, scores)
    return _precision_recall_curve(positive, scores_arr)


def average_precision(labels: ArrayLike, scores: ArrayLike) -> float:
    """Average precision: the step-wise integral of the precision-recall curve.

    With ``P_n`` and ``R_n`` the precision and recall at the ``n``-th
    operating point::

        AP = sum_n (R_n - R_{n-1}) * P_n

    Each operating point is weighted by the recall it *adds*, so the value is an
    achievable quantity rather than an interpolated one. The trapezoidal area
    under the PR curve would instead credit the detector for a precision
    achieved on a recall stretch it never actually covered; for rare systemic
    events -- where the interesting region is the few points near high recall --
    that optimism is exactly the wrong bias. ``sklearn`` uses the same
    step-wise definition, and the test suite pins the two implementations to
    each other to ``1e-9``.

    Returns:
        The step-wise AP, or ``nan`` when ``labels`` contains only one class.
        With no positive label there is nothing to recall; with no negative
        label every threshold has precision one, so the curve carries no
        information and ``1.0`` would read as measured discrimination. (For the
        all-negative case ``sklearn`` returns ``0.0``; that value is refused
        here for the same reason.)

    Raises:
        ValueError: if lengths differ, either array is empty, or a score is
            non-finite.
    """
    positive, scores_arr = _validate_binary_inputs(labels, scores)
    n_pos = int(positive.sum())
    if n_pos == 0 or n_pos == positive.size:
        return float("nan")
    precision, recall, _ = _precision_recall_curve(positive, scores_arr)
    # The step integral. Clipped at zero because floating-point cancellation can
    # produce ``-0.0`` when every delta is zero.
    return float(max(0.0, -np.sum(np.diff(recall) * precision[:-1])))


def precision_at_recall(
    labels: ArrayLike, scores: ArrayLike, target_recall: float
) -> float:
    """Highest precision achievable at recall of at least ``target_recall``.

    This is the operator's question: *if I must catch this share of crises, how
    many of my alarms may be false?* Only realisable operating points count, so
    the anchor point (precision 1 at recall 0) is excluded -- reporting it would
    answer "perfect precision" for a detector that has caught nothing.

    Args:
        labels: Event indicator over time steps.
        scores: Risk score over the same time steps.
        target_recall: Required recall, in ``[0, 1]``.

    Returns:
        The maximum precision over operating points whose recall is at least
        ``target_recall``, or ``nan`` when that recall is unreachable (in
        particular when there is no positive label at all).

    Raises:
        ValueError: if ``target_recall`` is outside ``[0, 1]`` or non-finite, or
            the inputs are invalid.
    """
    target = float(target_recall)
    if not math.isfinite(target) or target < 0.0 or target > 1.0:
        raise ValueError(f"target_recall must be in [0, 1], got {target_recall!r}")

    positive, scores_arr = _validate_binary_inputs(labels, scores)
    if not positive.any():
        return float("nan")

    precision, recall, _ = _precision_recall_curve(positive, scores_arr)
    # Drop the final anchor (recall=0, precision=1); it is not an operating
    # point the detector can select.
    precision, recall = precision[:-1], recall[:-1]
    reachable = recall >= target
    if not np.any(reachable):
        return float("nan")
    return float(np.max(precision[reachable]))


# ---------------------------------------------------------------------------
# Event-time diagnostics
# ---------------------------------------------------------------------------
def lead_time_stats(
    event_mask: ArrayLike, alarm_mask: ArrayLike, max_lead: int
) -> Dict[str, Any]:
    """Distribution of warning time between an alarm and the event it precedes.

    For every event at index ``e``, the alarm that counts is the **earliest**
    alarm ``a`` with ``e - max_lead <= a <= e``; the lead time is ``e - a``.
    Reporting the earliest alarm is the conservative choice for a warning
    system: it measures the warning the operator actually received, not the
    warning available in hindsight from a later, easier-to-hit alarm.

    An alarm at ``a == e`` gives lead ``0``: the event is detected, but no
    warning was given. Those are counted separately as ``n_zero_lead`` because a
    detector that only fires *on* the event has zero operational value even
    though its detection rate is one.

    Args:
        event_mask: Boolean event indicator over time steps.
        alarm_mask: Boolean alarm indicator over the same time steps.
        max_lead: Largest admissible lead, in steps. An alarm further back than
            ``max_lead`` does not count, because a "warning" that arrives long
            before the event is stale rather than timely.

    Returns:
        A dict with ``n_events``, ``n_detected``, ``n_missed``, ``n_zero_lead``,
        ``detection_rate``, ``mean_lead``, ``median_lead``, ``p10_lead``,
        ``p90_lead``, ``max_lead_observed`` and the raw ``lead_times`` list.
        Lead-time statistics are over detected events only and are ``nan`` when
        nothing was detected -- not ``0.0``, which would look like a
        simultaneous detection. ``detection_rate`` is ``nan`` when there are no
        events at all. Percentiles use linear interpolation between order
        statistics.

    Raises:
        ValueError: if the masks differ in length, are not boolean, or
            ``max_lead`` is negative.
    """
    events = _as_boolean_mask(event_mask, "event_mask")
    alarms = _as_boolean_mask(alarm_mask, "alarm_mask")
    if events.shape[0] != alarms.shape[0]:
        raise ValueError(
            f"event_mask and alarm_mask must have the same length, got "
            f"{events.shape[0]} and {alarms.shape[0]}"
        )
    window = _validate_window(max_lead, "max_lead")

    event_indices = np.flatnonzero(events)
    alarm_indices = np.flatnonzero(alarms)

    lead_times: List[int] = []
    n_zero_lead = 0
    for event in event_indices:
        earliest = int(event) - window
        if earliest < 0:
            earliest = 0
        # alarm_indices is sorted, so the first hit is the earliest alarm.
        in_window = alarm_indices[
            (alarm_indices >= earliest) & (alarm_indices <= event)
        ]
        if in_window.size == 0:
            continue
        lead = int(event) - int(in_window[0])
        lead_times.append(lead)
        if lead == 0:
            n_zero_lead += 1

    n_events = int(event_indices.size)
    n_detected = len(lead_times)
    detection_rate = (
        float(n_detected / n_events) if n_events > 0 else float("nan")
    )

    if lead_times:
        leads = np.asarray(lead_times, dtype=float)
        mean_lead = float(np.mean(leads))
        median_lead = float(np.median(leads))
        p10_lead = float(np.percentile(leads, 10))
        p90_lead = float(np.percentile(leads, 90))
        # Only meaningful when something was detected; documented above.
        max_lead_observed = int(max(lead_times))
    else:
        mean_lead = float("nan")
        median_lead = float("nan")
        p10_lead = float("nan")
        p90_lead = float("nan")
        max_lead_observed = 0

    return {
        "n_events": n_events,
        "n_detected": n_detected,
        "n_missed": int(n_events - n_detected),
        "n_zero_lead": int(n_zero_lead),
        "detection_rate": detection_rate,
        "mean_lead": mean_lead,
        "median_lead": median_lead,
        "p10_lead": p10_lead,
        "p90_lead": p90_lead,
        "max_lead_observed": max_lead_observed,
        "lead_times": lead_times,
    }


def false_alarm_stats(
    alarm_mask: ArrayLike, event_mask: ArrayLike, horizon: int
) -> Dict[str, Any]:
    """Count alarms that were not followed by an event, and events not warned.

    An alarm at ``t`` is a **true alarm** when an event occurs at some ``e`` with
    ``t < e <= t + horizon``. The bound is strict at the left on purpose: an
    alarm simultaneous with an event (``t == e``) gave the operator no time to
    act, so it is a false alarm in the only sense that matters -- it did not
    warn. It is still "detection" in :func:`lead_time_stats` (lead 0); the two
    functions measure different things and are intentionally not made to agree.

    An event at ``e`` is counted as **unwarned** when no alarm lies in
    ``[e - horizon, e - 1]``. This is the same relation read backwards: the
    alarm window is forward-looking because an alarm is a forecast, while the
    event window is backward-looking because a warning must precede its event.
    The two use different denominators -- ``false_alarm_rate`` is per alarm,
    while ``n_events_missed`` is per event -- so neither is the complement of
    the other, and both are reported.

    Args:
        alarm_mask: Boolean alarm indicator over time steps.
        event_mask: Boolean event indicator over the same time steps.
        horizon: Forward window in steps within which an event makes an alarm
            true. ``horizon=0`` therefore makes every alarm false and every
            event unwarned.

    Returns:
        A dict with ``n_alarms``, ``n_true_alarms``, ``n_false_alarms``,
        ``false_alarm_rate`` (``nan`` when there are no alarms),
        ``false_alarms_per_period``, ``n_events`` and ``n_events_missed``.

    Raises:
        ValueError: if the masks differ in length or ``horizon`` is negative.
    """
    alarms = _as_boolean_mask(alarm_mask, "alarm_mask")
    events = _as_boolean_mask(event_mask, "event_mask")
    if alarms.shape[0] != events.shape[0]:
        raise ValueError(
            f"alarm_mask and event_mask must have the same length, got "
            f"{alarms.shape[0]} and {events.shape[0]}"
        )
    forward = _validate_window(horizon, "horizon")

    alarm_indices = np.flatnonzero(alarms)
    event_indices = np.flatnonzero(events)

    n_true_alarms = 0
    for alarm in alarm_indices:
        following = np.searchsorted(event_indices, alarm, side="right")
        if (
            following < event_indices.size
            and event_indices[following] <= alarm + forward
        ):
            n_true_alarms += 1

    n_alarms = int(alarm_indices.size)
    n_false_alarms = n_alarms - n_true_alarms
    n_periods = int(alarms.shape[0])

    n_events_missed = 0
    for event in event_indices:
        first = np.searchsorted(alarm_indices, event - forward, side="left")
        last = np.searchsorted(alarm_indices, event - 1, side="right")
        if last <= first:
            n_events_missed += 1

    return {
        "n_alarms": n_alarms,
        "n_true_alarms": int(n_true_alarms),
        "n_false_alarms": int(n_false_alarms),
        "false_alarm_rate": (
            float(n_false_alarms / n_alarms) if n_alarms > 0 else float("nan")
        ),
        "false_alarms_per_period": (
            float(n_false_alarms / n_periods) if n_periods > 0 else float("nan")
        ),
        "n_events": int(event_indices.size),
        "n_events_missed": int(n_events_missed),
    }


# ---------------------------------------------------------------------------
# Combined report
# ---------------------------------------------------------------------------
def _to_native(value: Any) -> Any:
    """Recursively convert numpy scalars/arrays to native Python objects.

    ``json.dumps`` rejects ``np.int64`` (not an ``int`` subclass) while happily
    accepting ``np.float64`` only by accident of subclassing. Converting
    explicitly makes the payload portable. Crucially, ``nan`` is kept as
    ``float('nan')`` rather than mapped to ``None`` or ``0.0``: a downstream
    ``json.dumps(payload, allow_nan=False)`` must fail on an undefined metric so
    that "not measured" can never be published as a number.
    """
    if isinstance(value, dict):
        return {str(key): _to_native(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_native(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_to_native(item) for item in value.tolist()]
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.generic):
        return value.item()
    return value


def event_summary(
    labels: ArrayLike,
    scores: ArrayLike,
    threshold: float,
    max_lead: int,
    horizon: int,
) -> Dict[str, Any]:
    """One JSON-serialisable report combining discrimination, lead and alarms.

    The score is thresholded into an alarm mask with ``score >= threshold`` and
    evaluated against the event mask three ways: ranking quality (ROC AUC,
    average precision), timeliness (:func:`lead_time_stats`) and alarm cost
    (:func:`false_alarm_stats`). ``max_lead`` bounds how far back a warning may
    be and still count; ``horizon`` bounds how far forward an alarm may look for
    the event that justifies it.

    Undefined metrics are returned as ``nan`` and are **not** replaced. A caller
    that must serialise the payload should decide policy explicitly, e.g.::

        json.dumps(event_summary(...), allow_nan=False)   # raises on nan
        json.dumps(event_summary(...), default=...)       # or handle elsewhere

    Returns:
        A dict with ``roc_auc``, ``average_precision``, ``threshold``,
        ``precision`` and ``recall`` at that threshold, ``n_observations``,
        ``n_events``, and the nested ``lead_time`` and ``false_alarm`` payloads.
        Every value is a native Python type.

    Raises:
        ValueError: if the inputs fail the ranking-metric validation, if
            ``threshold`` is non-finite, or if ``max_lead``/``horizon`` is
            negative.
    """
    positive, scores_arr = _validate_binary_inputs(labels, scores)
    alarm_level = float(threshold)
    if not math.isfinite(alarm_level):
        raise ValueError(f"threshold must be finite, got {threshold!r}")
    # Validate the windows here as well so the failure is attributed to this
    # call rather than surfacing later from the nested helpers.
    window = _validate_window(max_lead, "max_lead")
    forward = _validate_window(horizon, "horizon")

    event_mask = positive.copy()
    alarm_mask = scores_arr >= alarm_level

    true_positives = int(np.sum(alarm_mask & event_mask))
    false_positives = int(np.sum(alarm_mask & ~event_mask))
    false_negatives = int(np.sum(~alarm_mask & event_mask))

    precision = (
        float(true_positives / (true_positives + false_positives))
        if (true_positives + false_positives) > 0
        else float("nan")
    )
    recall = (
        float(true_positives / (true_positives + false_negatives))
        if (true_positives + false_negatives) > 0
        else float("nan")
    )

    payload = {
        "roc_auc": roc_auc(positive, scores_arr),
        "average_precision": average_precision(positive, scores_arr),
        "threshold": alarm_level,
        "precision": precision,
        "recall": recall,
        "n_observations": int(scores_arr.size),
        "n_events": int(event_mask.sum()),
        "lead_time": lead_time_stats(event_mask, alarm_mask, window),
        "false_alarm": false_alarm_stats(alarm_mask, event_mask, forward),
    }
    return _to_native(payload)
