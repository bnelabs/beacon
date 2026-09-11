"""Tests for event-based evaluation of systemic-risk early-warning signals.

The strongest evidence in this file is the cross-check against
``scikit-learn``: :func:`roc_auc` must equal ``sklearn.metrics.roc_auc_score``
and :func:`average_precision` must equal
``sklearn.metrics.average_precision_score`` across randomly generated datasets
that vary size, class balance and tie structure. Ties are exercised explicitly,
because a hand-rolled AUC that breaks ties by array position agrees with the
reference on all-distinct scores and diverges the moment scores repeat.

The remaining tests pin the properties the plan requires: perfect and inverted
separation, undefined statistics reported as ``nan`` rather than a fabricated
``0.0``/``0.5``, the exact warning windows (an alarm simultaneous with an event
gives no warning), and strict JSON serialisation that fails on ``nan``.

``scikit-learn`` is imported here only, never in the module under test.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
from sklearn import metrics

from backend.modules.engine.event_metrics import (
    average_precision,
    event_summary,
    false_alarm_stats,
    lead_time_stats,
    precision_at_recall,
    precision_recall_curve,
    roc_auc,
)


def _index_mask(size: int, *indices: int) -> np.ndarray:
    """Boolean mask of length ``size`` with the given indices set."""
    mask = np.zeros(size, dtype=bool)
    if indices:
        mask[list(indices)] = True
    return mask


def _ensure_two_classes(
    rng: np.random.Generator, labels: np.ndarray
) -> np.ndarray:
    """Force at least one positive and one negative label in place."""
    labels = labels.copy()
    if labels.all():
        labels[0] = False
    if not labels.any():
        labels[0] = True
    if labels.all():
        labels[-1] = False
    return labels


# ---------------------------------------------------------------------------
# (a) Cross-check against scikit-learn
# ---------------------------------------------------------------------------
def _score_families(rng: np.random.Generator, size: int, mode: int) -> np.ndarray:
    """Score vectors with deliberately different tie structure."""
    if mode == 0:
        # Continuous scores: ties are unlikely, so this isolates rank maths.
        return rng.normal(size=size)
    if mode == 1:
        # Scores rounded to integers: some ties.
        return np.round(rng.normal(size=size), 0)
    # Scores from a tiny integer set: many ties, the failure mode of a naive
    # position-based tie rule.
    return rng.integers(0, 4, size=size).astype(float)


def test_roc_auc_and_average_precision_match_sklearn_over_random_datasets():
    rng = np.random.default_rng(20260101)
    max_auc_deviation = 0.0
    max_ap_deviation = 0.0

    for trial in range(400):
        size = int(rng.integers(4, 250))
        positive_fraction = float(rng.uniform(0.03, 0.97))
        labels = _ensure_two_classes(rng, rng.random(size) < positive_fraction)
        scores = _score_families(rng, size, trial % 3)

        ours_auc = roc_auc(labels, scores)
        reference_auc = metrics.roc_auc_score(labels.astype(int), scores)
        max_auc_deviation = max(max_auc_deviation, abs(ours_auc - reference_auc))

        ours_ap = average_precision(labels, scores)
        reference_ap = metrics.average_precision_score(labels.astype(int), scores)
        max_ap_deviation = max(max_ap_deviation, abs(ours_ap - reference_ap))

    assert max_auc_deviation < 1e-9
    assert max_ap_deviation < 1e-9


def test_sklearn_agreement_holds_with_many_tied_scores():
    rng = np.random.default_rng(4242)
    observed_tie_density = 0.0

    for _ in range(200):
        size = int(rng.integers(10, 150))
        labels = _ensure_two_classes(rng, rng.random(size) < rng.uniform(0.1, 0.9))
        # Only five possible values for the whole sample: dense ties.
        scores = rng.integers(0, 5, size=size).astype(float)
        observed_tie_density = max(
            observed_tie_density, 1.0 - np.unique(scores).size / size
        )

        assert roc_auc(labels, scores) == pytest.approx(
            metrics.roc_auc_score(labels.astype(int), scores), abs=1e-9
        )
        assert average_precision(labels, scores) == pytest.approx(
            metrics.average_precision_score(labels.astype(int), scores), abs=1e-9
        )

    # Guard that the dataset really was tie-heavy; otherwise the test above
    # would be a weaker repeat of the continuous-score case.
    assert observed_tie_density > 0.9


def test_precision_recall_curve_matches_sklearn_convention():
    rng = np.random.default_rng(31337)
    for _ in range(100):
        size = int(rng.integers(4, 120))
        labels = _ensure_two_classes(rng, rng.random(size) < rng.uniform(0.1, 0.9))
        scores = rng.integers(0, 5, size=size).astype(float)

        precision, recall, thresholds = precision_recall_curve(labels, scores)
        ref_precision, ref_recall, ref_thresholds = metrics.precision_recall_curve(
            labels.astype(int), scores
        )

        assert precision.shape == (thresholds.size + 1,)
        assert recall.shape == (thresholds.size + 1,)
        # The final, threshold-less anchor is always precision=1, recall=0.
        assert precision[-1] == pytest.approx(1.0)
        assert recall[-1] == pytest.approx(0.0)

        assert np.allclose(precision, ref_precision, atol=1e-12)
        assert np.allclose(recall, ref_recall, atol=1e-12)
        assert np.allclose(thresholds, ref_thresholds, atol=1e-12)


# ---------------------------------------------------------------------------
# (b) Separation, inversion and chance
# ---------------------------------------------------------------------------
def test_perfect_separation_gives_auc_one_and_ap_one():
    labels = np.array([1, 1, 0, 0])
    scores = np.array([0.9, 0.8, 0.2, 0.1])

    assert roc_auc(labels, scores) == 1.0
    assert average_precision(labels, scores) == 1.0


def test_fully_inverted_gives_auc_zero_and_ap_one_over_n_pos():
    # Every negative is ranked above every positive, and both positives are tied
    # at the lowest score. The precision-recall curve then has a single recall
    # jump (0 -> 1) at the threshold of the tied positives, where the two
    # positives are the last two of the four samples: precision = 2/4 = 0.5.
    # AP weighs that single step by delta recall = 1, so AP = 0.5. With this
    # balanced construction the minimum-AP value, the prevalence n_pos / n,
    # coincides with 1 / n_pos = 1/2, which is what the plan expects.
    labels = np.array([1, 1, 0, 0])
    scores = np.array([0.1, 0.1, 0.9, 0.8])
    n_pos = int(labels.sum())

    assert roc_auc(labels, scores) == 0.0
    assert average_precision(labels, scores) == pytest.approx(1.0 / n_pos)


def test_chance_level_identical_scores_gives_auc_half():
    # With every score tied, each positive-negative pair is a tie and counts as
    # one half: U = 2 * 2 / 2 = 2, AUC = 2 / (2 * 2) = 0.5.
    labels = np.array([1, 1, 0, 0])
    scores = np.ones(4)

    assert roc_auc(labels, scores) == 0.5
    # Average precision at a single threshold is the prevalence, n_pos / n,
    # because every sample is admitted at once (there is only one threshold).
    assert average_precision(labels, scores) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# (c) Single-class input is undefined, not zero
# ---------------------------------------------------------------------------
def test_single_class_labels_return_nan_for_ranking_metrics():
    scores = np.array([0.1, 0.2, 0.3, 0.4])
    all_negative = np.zeros(4, dtype=int)
    all_positive = np.ones(4, dtype=int)

    for labels in (all_negative, all_positive):
        auc = roc_auc(labels, scores)
        ap = average_precision(labels, scores)

        assert math.isnan(auc)
        assert math.isnan(ap)
        # A fabricated chance value would be worse than "undefined".
        assert auc != 0.0
        assert auc != 0.5
        assert ap != 0.0


def test_no_positive_labels_returns_nan_average_precision():
    # sklearn returns 0.0 here; a 0.0 would read downstream as "measured, and
    # the model found nothing". The label set simply has no events to recall.
    labels = np.zeros(5, dtype=int)
    scores = np.linspace(0.0, 1.0, 5)

    assert math.isnan(average_precision(labels, scores))


# ---------------------------------------------------------------------------
# (d) Hand-computed example
# ---------------------------------------------------------------------------
def test_hand_computed_auc_and_average_precision():
    # labels    = [1, 0, 0, 1, 1]
    # scores    = [0.9, 0.8, 0.7, 0.6, 0.5]  (all distinct)
    # ranks (ascending score): 0.5->1, 0.6->2, 0.7->3, 0.8->4, 0.9->5.
    # Positives sit at ranks 5, 2, 1: sum = 8, n_pos = 3, n_neg = 2.
    #   U   = 8 - 3 * 4 / 2 = 8 - 6 = 2
    #   AUC = 2 / (3 * 2) = 1/3
    labels = np.array([1, 0, 0, 1, 1])
    scores = np.array([0.9, 0.8, 0.7, 0.6, 0.5])

    assert roc_auc(labels, scores) == pytest.approx(1.0 / 3.0)

    # PR points in increasing threshold order (threshold -> tp, fp -> p, r):
    #   0.5 -> 3,2 -> 3/5, recall 1
    #   0.6 -> 2,2 -> 1/2, recall 2/3
    #   0.7 -> 1,2 -> 1/3, recall 1/3
    #   0.8 -> 1,1 -> 1/2, recall 1/3
    #   0.9 -> 1,0 -> 1,   recall 1/3
    # The step AP is -sum(diff(recall) * precision[:-1]); the recall deltas are
    # -1/3 at precision 3/5, -1/3 at precision 1/2, and -1/3 at precision 1:
    #   AP = (1/3)(3/5) + (1/3)(1/2) + (1/3)(1)
    #      = 1/5 + 1/6 + 1/3 = 6/30 + 5/30 + 10/30 = 21/30 = 0.7
    # The literal below is additionally pinned to sklearn, so it is not taken on
    # trust.
    assert average_precision(labels, scores) == pytest.approx(0.7)
    assert average_precision(labels, scores) == pytest.approx(
        metrics.average_precision_score(labels, scores)
    )


# ---------------------------------------------------------------------------
# (e) Lead-time distribution on a hand-built case
# ---------------------------------------------------------------------------
def test_lead_time_uses_the_earliest_alarm_in_the_window():
    events = _index_mask(100, 50)
    alarms = _index_mask(100, 40, 45)

    stats = lead_time_stats(events, alarms, max_lead=20)

    assert stats["n_events"] == 1
    assert stats["n_detected"] == 1
    assert stats["n_missed"] == 0
    assert stats["n_zero_lead"] == 0
    assert stats["detection_rate"] == 1.0
    assert stats["lead_times"] == [10]
    # Earliest alarm at 40 wins over the later one at 45, giving lead 50 - 40.
    assert stats["mean_lead"] == 10.0
    assert stats["median_lead"] == 10.0
    assert stats["max_lead_observed"] == 10
    assert stats["p10_lead"] == 10.0
    assert stats["p90_lead"] == 10.0


def test_missed_event_reports_nan_statistics_not_zero():
    events = _index_mask(100, 50)
    alarms = np.zeros(100, dtype=bool)

    stats = lead_time_stats(events, alarms, max_lead=20)

    assert stats["n_events"] == 1
    assert stats["n_detected"] == 0
    assert stats["n_missed"] == 1
    assert stats["detection_rate"] == 0.0
    assert stats["lead_times"] == []
    # No detected event means there is no lead-time distribution to summarise.
    assert math.isnan(stats["mean_lead"])
    assert math.isnan(stats["median_lead"])
    assert math.isnan(stats["p10_lead"])
    assert math.isnan(stats["p90_lead"])
    assert stats["mean_lead"] != 0.0


# ---------------------------------------------------------------------------
# (f) max_lead bounds the admissible warning
# ---------------------------------------------------------------------------
def test_max_lead_excludes_an_alarm_that_is_too_early():
    events = _index_mask(100, 50)
    too_early = _index_mask(100, 40)

    # The alarm is 10 steps before the event; a 5-step window cannot see it.
    narrow = lead_time_stats(events, too_early, max_lead=5)
    assert narrow["n_detected"] == 0
    assert narrow["n_missed"] == 1

    wide = lead_time_stats(events, too_early, max_lead=10)
    assert wide["n_detected"] == 1
    assert wide["mean_lead"] == 10.0

    # With a second, closer alarm the narrow window detects at lead 5: the
    # window excludes the stale alarm but keeps the fresh one.
    two_alarms = _index_mask(100, 40, 45)
    assert lead_time_stats(events, two_alarms, max_lead=5)["mean_lead"] == 5.0


# ---------------------------------------------------------------------------
# (g) A simultaneous alarm is detected but gives no warning
# ---------------------------------------------------------------------------
def test_simultaneous_alarm_is_detected_with_zero_lead():
    events = _index_mask(100, 50)
    alarms = _index_mask(100, 50)

    stats = lead_time_stats(events, alarms, max_lead=5)

    assert stats["n_detected"] == 1
    assert stats["n_missed"] == 0
    assert stats["n_zero_lead"] == 1
    assert stats["lead_times"] == [0]
    assert stats["mean_lead"] == 0.0
    assert stats["max_lead_observed"] == 0


# ---------------------------------------------------------------------------
# (h) False-alarm rate on a hand-built case
# ---------------------------------------------------------------------------
def test_false_alarm_rate_hand_case():
    # Alarm at 10: event at 12 lies in (10, 15], so it is true.
    # Alarm at 100: no event in (100, 105], so it is false.
    # false_alarm_rate = 1 false / 2 alarms = 0.5.
    alarms = _index_mask(200, 10, 100)
    events = _index_mask(200, 12)

    stats = false_alarm_stats(alarms, events, horizon=5)

    assert stats["n_alarms"] == 2
    assert stats["n_true_alarms"] == 1
    assert stats["n_false_alarms"] == 1
    assert stats["false_alarm_rate"] == 0.5
    assert stats["false_alarms_per_period"] == pytest.approx(1 / 200)
    assert stats["n_events"] == 1
    # The event at 12 is warned by the alarm at 10, which lies in [7, 11].
    assert stats["n_events_missed"] == 0


def test_no_alarms_makes_the_false_alarm_rate_undefined():
    alarms = np.zeros(50, dtype=bool)
    events = _index_mask(50, 20)

    stats = false_alarm_stats(alarms, events, horizon=5)

    assert stats["n_alarms"] == 0
    assert math.isnan(stats["false_alarm_rate"])
    assert stats["false_alarms_per_period"] == 0.0
    assert stats["n_events_missed"] == 1


# ---------------------------------------------------------------------------
# (i) The strict forward window
# ---------------------------------------------------------------------------
def test_alarm_immediately_before_event_is_a_true_alarm():
    alarms = _index_mask(100, 10)
    events = _index_mask(100, 11)

    stats = false_alarm_stats(alarms, events, horizon=5)

    assert stats["n_true_alarms"] == 1
    assert stats["n_false_alarms"] == 0


def test_alarm_simultaneous_with_event_is_a_false_alarm_under_strict_window():
    # t < e <= t + horizon is strict at the left: an alarm at the same index as
    # the event gave no warning, so it is a false alarm even though the event is
    # "detected" (with lead 0) by lead_time_stats.
    alarms = _index_mask(100, 10)
    events = _index_mask(100, 10)

    false_alarms = false_alarm_stats(alarms, events, horizon=5)
    assert false_alarms["n_true_alarms"] == 0
    assert false_alarms["n_false_alarms"] == 1
    assert false_alarms["false_alarm_rate"] == 1.0
    # The event has no alarm in [5, 9], so it is unwarned.
    assert false_alarms["n_events_missed"] == 1

    leads = lead_time_stats(events, alarms, max_lead=5)
    assert leads["n_detected"] == 1
    assert leads["n_zero_lead"] == 1


def test_zero_horizon_makes_every_alarm_false_and_every_event_unwarned():
    alarms = _index_mask(50, 10, 20)
    events = _index_mask(50, 10, 20)

    stats = false_alarm_stats(alarms, events, horizon=0)

    assert stats["n_true_alarms"] == 0
    assert stats["n_false_alarms"] == 2
    assert stats["n_events_missed"] == 2


# ---------------------------------------------------------------------------
# (j) Precision at a required recall
# ---------------------------------------------------------------------------
def test_precision_at_recall_reachable_at_perfect_precision():
    labels = np.array([1, 1, 0, 0])
    scores = np.array([0.9, 0.8, 0.2, 0.1])

    # The top two scores are exactly the two positives, so recall 0.5 is
    # reachable with no false positive: precision 1.0.
    assert precision_at_recall(labels, scores, 0.5) == 1.0
    # Recall 1.0 is also reachable here, still at precision 1.0.
    assert precision_at_recall(labels, scores, 1.0) == 1.0


def test_precision_at_recall_at_full_recall_for_an_inverted_score():
    labels = np.array([1, 1, 0, 0])
    scores = np.array([0.1, 0.1, 0.9, 0.8])

    # To reach recall 1.0 every sample must be admitted, so precision collapses
    # to the prevalence 2/4 = 0.5.
    assert precision_at_recall(labels, scores, 1.0) == pytest.approx(0.5)


def test_precision_at_recall_ignores_the_perfect_precision_anchor():
    # The curve carries an artificial anchor (precision=1, recall=0) with no
    # threshold. A target recall of 0 must not pick it up: the best realisable
    # operating point is the threshold at 1.0, with precision 1/2.
    labels = np.array([1, 0])
    scores = np.array([0.0, 1.0])

    assert precision_at_recall(labels, scores, 0.0) == pytest.approx(0.5)


def test_precision_at_recall_is_nan_when_recall_is_unreachable():
    # No positive label: no operating point has recall > 0.
    labels = np.zeros(6, dtype=int)
    scores = np.linspace(0.0, 1.0, 6)

    assert math.isnan(precision_at_recall(labels, scores, 0.5))
    assert math.isnan(precision_at_recall(labels, scores, 1.0))


# ---------------------------------------------------------------------------
# (k) JSON round-trip, and refusal to hide nan
# ---------------------------------------------------------------------------
def test_event_summary_round_trips_through_strict_json_when_defined():
    labels = np.array([1, 0, 1, 0])
    scores = np.array([0.9, 0.1, 0.8, 0.2])

    payload = event_summary(labels, scores, threshold=0.5, max_lead=2, horizon=2)

    assert payload["roc_auc"] == 1.0
    assert payload["average_precision"] == 1.0
    assert payload["threshold"] == 0.5
    assert payload["precision"] == 1.0
    assert payload["recall"] == 1.0
    assert payload["n_observations"] == 4
    assert payload["n_events"] == 2
    assert payload["lead_time"]["lead_times"] == [0, 2]
    assert payload["lead_time"]["mean_lead"] == 1.0
    assert payload["false_alarm"]["n_true_alarms"] == 1
    assert payload["false_alarm"]["n_false_alarms"] == 1
    assert payload["false_alarm"]["false_alarm_rate"] == 0.5

    # No undefined value is present, so strict serialisation must succeed and be
    # reversible.
    encoded = json.dumps(payload, allow_nan=False)
    assert json.loads(encoded) == payload


def test_event_summary_strict_json_raises_when_a_metric_is_nan():
    # No events at all: ROC AUC, average precision, precision, recall and the
    # lead-time statistics are all undefined. Replacing them with 0.0 would let
    # a "not measured" report be published as a real number.
    labels = np.zeros(4, dtype=int)
    scores = np.array([0.1, 0.2, 0.3, 0.4])

    payload = event_summary(labels, scores, threshold=0.5, max_lead=2, horizon=2)

    assert math.isnan(payload["roc_auc"])
    assert math.isnan(payload["average_precision"])
    assert math.isnan(payload["precision"])
    assert math.isnan(payload["recall"])
    assert math.isnan(payload["lead_time"]["mean_lead"])
    with pytest.raises(ValueError):
        json.dumps(payload, allow_nan=False)


# ---------------------------------------------------------------------------
# (l) ValueError paths
# ---------------------------------------------------------------------------
def test_ranking_metrics_reject_mismatched_lengths():
    with pytest.raises(ValueError):
        roc_auc(np.array([1, 0, 1]), np.array([0.1, 0.2]))
    with pytest.raises(ValueError):
        average_precision(np.array([1, 0, 1]), np.array([0.1, 0.2]))
    with pytest.raises(ValueError):
        precision_recall_curve(np.array([1, 0, 1]), np.array([0.1, 0.2]))
    with pytest.raises(ValueError):
        precision_at_recall(np.array([1, 0, 1]), np.array([0.1, 0.2]), 0.5)


def test_ranking_metrics_reject_empty_input():
    empty = np.array([])
    with pytest.raises(ValueError):
        roc_auc(empty, empty)
    with pytest.raises(ValueError):
        average_precision(empty, empty)
    with pytest.raises(ValueError):
        precision_recall_curve(empty, empty)
    with pytest.raises(ValueError):
        precision_at_recall(empty, empty, 0.5)


@pytest.mark.parametrize("bad_score", [np.nan, np.inf, -np.inf])
def test_ranking_metrics_reject_non_finite_scores(bad_score):
    labels = np.array([1, 0, 1, 0])
    scores = np.array([0.9, bad_score, 0.8, 0.2])

    with pytest.raises(ValueError):
        roc_auc(labels, scores)
    with pytest.raises(ValueError):
        average_precision(labels, scores)
    with pytest.raises(ValueError):
        precision_recall_curve(labels, scores)


@pytest.mark.parametrize(
    "target_recall", [-0.001, 1.001, 2.0, float("nan"), float("inf")]
)
def test_precision_at_recall_rejects_out_of_range_targets(target_recall):
    labels = np.array([1, 0, 1, 0])
    scores = np.array([0.9, 0.1, 0.8, 0.2])

    with pytest.raises(ValueError):
        precision_at_recall(labels, scores, target_recall)


def test_lead_time_stats_rejects_mismatched_masks():
    with pytest.raises(ValueError):
        lead_time_stats(
            _index_mask(10, 3), _index_mask(9, 2), max_lead=2
        )


@pytest.mark.parametrize(
    "bad_mask", [np.array([0, 1, 0, 1]), np.array([0.0, 1.0, 0.0, 1.0])]
)
def test_lead_time_stats_rejects_non_boolean_masks(bad_mask):
    # Integer masks are refused: any non-zero code would otherwise be silently
    # promoted to "event", including sentinel codes.
    good_mask = np.array([False, False, True, False])
    with pytest.raises(ValueError):
        lead_time_stats(bad_mask, good_mask, max_lead=2)
    with pytest.raises(ValueError):
        lead_time_stats(good_mask, bad_mask, max_lead=2)
    with pytest.raises(ValueError):
        false_alarm_stats(bad_mask, good_mask, horizon=2)
    with pytest.raises(ValueError):
        false_alarm_stats(good_mask, bad_mask, horizon=2)


@pytest.mark.parametrize("bad_max_lead", [-1, -100])
def test_lead_time_stats_rejects_negative_max_lead(bad_max_lead):
    mask = np.array([False, False, True, False])
    with pytest.raises(ValueError):
        lead_time_stats(mask, mask, max_lead=bad_max_lead)


def test_false_alarm_stats_rejects_mismatched_masks():
    with pytest.raises(ValueError):
        false_alarm_stats(_index_mask(10, 3), _index_mask(9, 2), horizon=1)


@pytest.mark.parametrize("bad_horizon", [-1, -50])
def test_false_alarm_stats_rejects_negative_horizon(bad_horizon):
    mask = np.array([False, False, True, False])
    with pytest.raises(ValueError):
        false_alarm_stats(mask, mask, horizon=bad_horizon)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"threshold": 0.5, "max_lead": -1, "horizon": 2},
        {"threshold": 0.5, "max_lead": 2, "horizon": -1},
        {"threshold": float("nan"), "max_lead": 2, "horizon": 2},
    ],
)
def test_event_summary_rejects_invalid_windows_and_threshold(kwargs):
    labels = np.array([1, 0, 1, 0])
    scores = np.array([0.9, 0.1, 0.8, 0.2])

    with pytest.raises(ValueError):
        event_summary(labels, scores, **kwargs)


def test_event_summary_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        event_summary(
            np.array([1, 0, 1]),
            np.array([0.9, 0.1]),
            threshold=0.5,
            max_lead=2,
            horizon=2,
        )
