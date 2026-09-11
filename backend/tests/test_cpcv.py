"""Tests for Combinatorial Purged Cross-Validation.

The property that matters is that no training observation's label span overlaps the
test set's label span. That is the leak CPCV exists to remove, and the test suite
proves the invariant holds for purged splits *and* that a naive split violates it --
otherwise the assertion would be vacuous.
"""

from __future__ import annotations

import json
from math import comb

import numpy as np
import pytest

from backend.modules.engine.cpcv import (
    CPCVConfig,
    CPCVSplit,
    combinatorial_purged_splits,
    cpcv_summary,
    group_bounds,
    n_backtest_paths,
    n_splits,
)


def _blocks(indices: np.ndarray) -> list[tuple[int, int]]:
    """Half-open runs of consecutive indices."""
    if indices.size == 0:
        return []
    ordered = np.sort(indices)
    breaks = np.nonzero(np.diff(ordered) > 1)[0]
    starts = np.concatenate(([0], breaks + 1))
    ends = np.concatenate((breaks + 1, [ordered.size]))
    return [(int(ordered[a]), int(ordered[b - 1]) + 1) for a, b in zip(starts, ends)]


def _overlapping_label_spans(
    train_indices: np.ndarray, test_indices: np.ndarray, label_horizon: int
) -> list[tuple[int, int]]:
    """Training indices whose label span overlaps the test label span.

    A label at ``i`` spans ``[i, i + h]``; a test block ``[lo, hi)`` spans
    ``[lo, hi - 1 + h]``. The two spans overlap exactly when

        i <= hi - 1 + h   AND   i + h >= lo

    Both halves matter. Checking only ``i >= lo`` would miss the observations
    *before* a test block whose labels reach forward across the boundary -- which
    is the more common look-ahead and the one purging specifically targets.
    """
    overlaps: list[tuple[int, int]] = []
    for lo, hi in _blocks(test_indices):
        test_lo = lo
        test_hi = hi - 1 + label_horizon
        for index in np.asarray(train_indices, dtype=int):
            i = int(index)
            if i <= test_hi and i + label_horizon >= test_lo:
                overlaps.append((i, lo))
    return overlaps


class TestGroupBounds:
    def test_groups_are_contiguous_and_cover_everything(self):
        bounds = group_bounds(10, 3)
        assert bounds == [(0, 4), (4, 7), (7, 10)]
        assert bounds[0][0] == 0
        assert bounds[-1][1] == 10
        for (_, previous_end), (next_start, _) in zip(bounds, bounds[1:]):
            assert previous_end == next_start

    def test_group_sizes_differ_by_at_most_one(self):
        sizes = [end - start for start, end in group_bounds(103, 7)]
        assert max(sizes) - min(sizes) <= 1
        assert sum(sizes) == 103

    def test_remainder_goes_to_the_earliest_groups(self):
        bounds = group_bounds(10, 3)
        assert [b - a for a, b in bounds] == [4, 3, 3]

    def test_more_groups_than_samples_is_rejected(self):
        with pytest.raises(ValueError, match="non-empty groups"):
            group_bounds(3, 5)

    def test_non_positive_inputs_are_rejected(self):
        with pytest.raises(ValueError, match="n_samples"):
            group_bounds(0, 2)
        with pytest.raises(ValueError, match="n_groups"):
            group_bounds(10, 0)


class TestSplitCounts:
    def test_n_splits_is_the_binomial_coefficient(self):
        assert n_splits(6, 2) == comb(6, 2) == 15
        assert n_splits(10, 3) == comb(10, 3) == 120

    def test_generated_split_count_matches_the_formula(self):
        for groups, test_groups in [(4, 1), (6, 2), (8, 3)]:
            config = CPCVConfig(n_groups=groups, n_test_groups=test_groups)
            splits = list(combinatorial_purged_splits(60, config))
            assert len(splits) == n_splits(groups, test_groups)

    def test_backtest_paths_matches_the_canonical_example(self):
        # Advances in Financial Machine Learning: N=6, k=2 gives 5 paths.
        assert n_backtest_paths(6, 2) == 5
        assert n_backtest_paths(4, 1) == 1
        assert n_backtest_paths(6, 3) == 10

    def test_path_count_is_an_integer_for_valid_inputs(self):
        for groups in range(2, 11):
            for test_groups in range(1, groups):
                assert isinstance(n_backtest_paths(groups, test_groups), int)

    def test_invalid_split_parameters_are_rejected(self):
        with pytest.raises(ValueError):
            n_splits(5, 5)
        with pytest.raises(ValueError):
            n_splits(5, 0)
        with pytest.raises(ValueError):
            n_backtest_paths(5, 5)


class TestPartitioning:
    def test_train_and_test_never_overlap(self):
        config = CPCVConfig(n_groups=6, n_test_groups=2, label_horizon=3, embargo_pct=0.05)
        for split in combinatorial_purged_splits(60, config):
            assert np.intersect1d(split.train_indices, split.test_indices).size == 0

    def test_every_observation_is_tested_exactly_the_same_number_of_times(self):
        groups, test_groups, n_samples = 5, 2, 50
        config = CPCVConfig(n_groups=groups, n_test_groups=test_groups)
        counts = np.zeros(n_samples, dtype=int)
        for split in combinatorial_purged_splits(n_samples, config):
            counts[split.test_indices] += 1

        # Each group is held out in C(N-1, k-1) of the splits.
        expected = comb(groups - 1, test_groups - 1)
        assert np.all(counts == expected)
        assert expected == 4

    def test_every_observation_is_covered_by_the_test_sets(self):
        config = CPCVConfig(n_groups=6, n_test_groups=2)
        covered = np.zeros(36, dtype=bool)
        for split in combinatorial_purged_splits(36, config):
            covered[split.test_indices] = True
        assert covered.all()

    def test_test_sets_are_unions_of_whole_groups(self):
        config = CPCVConfig(n_groups=6, n_test_groups=2)
        bounds = group_bounds(60, 6)
        for split in combinatorial_purged_splits(60, config):
            expected = np.sort(
                np.concatenate([np.arange(*bounds[g]) for g in split.test_groups])
            )
            assert np.array_equal(split.test_indices, expected)

    def test_without_purge_or_embargo_training_is_the_complement_of_test(self):
        # label_horizon=0 means labels are point-in-time, so there is nothing to
        # purge; embargo_pct=0 removes nothing further.
        config = CPCVConfig(n_groups=4, n_test_groups=1, label_horizon=0, embargo_pct=0.0)
        n_samples = 40
        for split in combinatorial_purged_splits(n_samples, config):
            expected_train = np.setdiff1d(np.arange(n_samples), split.test_indices)
            assert np.array_equal(split.train_indices, expected_train)
            assert split.n_purged == 0
            assert split.n_embargoed == 0


class TestPurging:
    def test_no_training_label_span_overlaps_the_test_label_span(self):
        """The invariant CPCV exists to guarantee."""
        config = CPCVConfig(n_groups=6, n_test_groups=2, label_horizon=4, embargo_pct=0.0)
        for split in combinatorial_purged_splits(60, config):
            overlaps = _overlapping_label_spans(
                split.train_indices, split.test_indices, config.label_horizon
            )
            assert overlaps == [], (
                f"fold {split.fold} leaks: training indices {overlaps[:5]} share "
                "label span with the test set"
            )

    def test_a_naive_split_violates_the_invariant(self):
        """Proves the invariant above has teeth.

        The same split with purging disabled leaks, so the assertion in the
        previous test is not vacuous.
        """
        n_samples, groups, test_groups, horizon = 60, 6, 2, 4
        config = CPCVConfig(
            n_groups=groups, n_test_groups=test_groups, label_horizon=horizon
        )
        # Pick a split with an interior test block. The first combination holds
        # out groups (0, 1), which sits at the very start of the sample and so has
        # no observations before it to leak from.
        split = next(
            s
            for s in combinatorial_purged_splits(n_samples, config)
            if any(lo - horizon >= 0 for lo, _ in _blocks(s.test_indices))
        )

        naive_train = np.setdiff1d(np.arange(n_samples), split.test_indices)
        overlaps = _overlapping_label_spans(naive_train, split.test_indices, horizon)
        assert overlaps, "expected the naive split to leak, but it did not"

        # Specifically: observations immediately BEFORE a test block whose labels
        # reach forward across the boundary. This is the leak that purging targets,
        # and it is the half a naive check would miss.
        leaked = {index for index, _ in overlaps}
        block_starts = [lo for lo, _ in _blocks(split.test_indices)]
        backward_leaks = {
            index
            for index in leaked
            if any(lo - horizon <= index < lo for lo in block_starts)
        }
        assert backward_leaks, "expected forward-reaching labels before a test block"

        # And the purged split genuinely removed every leaking observation.
        assert split.n_purged > 0
        assert leaked.isdisjoint(set(split.train_indices.tolist()))

    def test_purge_window_is_exactly_the_label_overlap(self):
        # A single interior test block, no embargo: exactly `horizon` observations
        # before the block and `horizon` after it are removed.
        horizon = 3
        config = CPCVConfig(n_groups=5, n_test_groups=1, label_horizon=horizon)
        bounds = group_bounds(50, 5)
        split = next(
            s for s in combinatorial_purged_splits(50, config) if s.test_groups == (2,)
        )
        block_start, block_end = bounds[2]
        assert split.n_purged == 2 * horizon

        # The boundary is exact: `block_start - horizon` overlaps and is purged;
        # one further back does not overlap and survives.
        assert block_start - horizon not in set(split.train_indices.tolist())
        assert block_start - horizon - 1 in set(split.train_indices.tolist())
        # Likewise on the far side.
        assert block_end - 1 + horizon not in set(split.train_indices.tolist())
        assert block_end + horizon in set(split.train_indices.tolist())

    def test_purging_removes_more_as_the_label_horizon_grows(self):
        removed = []
        for horizon in (0, 1, 3, 5):
            config = CPCVConfig(n_groups=6, n_test_groups=2, label_horizon=horizon)
            total = sum(s.n_purged for s in combinatorial_purged_splits(72, config))
            removed.append(total)
        assert removed == sorted(removed)
        assert removed[0] == 0
        assert removed[-1] > removed[0]

    def test_purge_never_removes_test_observations(self):
        config = CPCVConfig(n_groups=6, n_test_groups=2, label_horizon=6, embargo_pct=0.1)
        for split in combinatorial_purged_splits(60, config):
            assert np.intersect1d(split.train_indices, split.test_indices).size == 0
            assert split.n_test == 20


class TestEmbargo:
    def test_embargo_removes_the_window_after_each_test_block(self):
        config = CPCVConfig(n_groups=5, n_test_groups=1, label_horizon=0, embargo_pct=0.1)
        n_samples = 50
        embargo_size = int(0.1 * n_samples)
        bounds = group_bounds(n_samples, 5)
        split = next(
            s for s in combinatorial_purged_splits(n_samples, config) if s.test_groups == (1,)
        )
        _, block_end = bounds[1]
        train = set(split.train_indices.tolist())

        for offset in range(embargo_size):
            assert block_end + offset not in train, "embargoed observation survived"
        # The observation immediately past the embargo survives.
        assert block_end + embargo_size in train
        assert split.n_embargoed == embargo_size

    def test_embargo_removes_more_as_the_fraction_grows(self):
        removed = []
        for pct in (0.0, 0.02, 0.05, 0.1):
            config = CPCVConfig(n_groups=6, n_test_groups=2, embargo_pct=pct)
            removed.append(sum(s.n_embargoed for s in combinatorial_purged_splits(100, config)))
        assert removed == sorted(removed)
        assert removed[0] == 0

    def test_embargo_is_clipped_at_the_end_of_the_sample(self):
        # A test block at the very end has nothing after it to embargo.
        config = CPCVConfig(n_groups=4, n_test_groups=1, embargo_pct=0.25)
        splits = list(combinatorial_purged_splits(40, config))
        last = splits[-1]
        assert last.test_groups == (3,)
        assert last.n_embargoed == 0

    def test_combined_purge_and_embargo_respect_both_windows(self):
        config = CPCVConfig(n_groups=6, n_test_groups=2, label_horizon=2, embargo_pct=0.05)
        n_samples = 60
        embargo_size = int(0.05 * n_samples)
        for split in combinatorial_purged_splits(n_samples, config):
            train = set(split.train_indices.tolist())
            for block_start, block_end in _blocks(split.test_indices):
                for offset in range(1, config.label_horizon + 1):
                    assert block_start - offset not in train
                    assert block_end - 1 + offset not in train
                for offset in range(embargo_size):
                    assert block_end + offset not in train


class TestDeterminismAndSerialisation:
    def test_splits_are_deterministic(self):
        config = CPCVConfig(n_groups=5, n_test_groups=2, label_horizon=2, embargo_pct=0.05)
        first = [
            (s.fold, s.test_groups, s.train_indices.tolist(), s.test_indices.tolist())
            for s in combinatorial_purged_splits(50, config)
        ]
        second = [
            (s.fold, s.test_groups, s.train_indices.tolist(), s.test_indices.tolist())
            for s in combinatorial_purged_splits(50, config)
        ]
        assert first == second

    def test_split_serialises_to_json(self):
        config = CPCVConfig(n_groups=5, n_test_groups=2, label_horizon=2)
        split = next(combinatorial_purged_splits(50, config))
        json.dumps(split.to_dict(), allow_nan=False)

    def test_summary_serialises_to_json(self):
        summary = cpcv_summary(60, CPCVConfig(n_groups=6, n_test_groups=2, label_horizon=3))
        json.dumps(summary, allow_nan=False)
        assert summary["n_splits"] == 15
        assert summary["n_backtest_paths"] == 5
        assert summary["n_splits_expected"] == 15
        assert len(summary["group_sizes"]) == 6

    def test_summary_accounts_for_every_split(self):
        config = CPCVConfig(n_groups=5, n_test_groups=2, label_horizon=2)
        summary = cpcv_summary(50, config)
        assert summary["n_splits"] + summary["n_degenerate_splits"] == summary["n_splits_expected"]

    def test_summary_agrees_with_materialised_splits(self):
        config = CPCVConfig(n_groups=6, n_test_groups=2, label_horizon=3, embargo_pct=0.05)
        summary = cpcv_summary(60, config)
        splits = list(combinatorial_purged_splits(60, config))

        assert summary["total_purged"] == sum(s.n_purged for s in splits)
        assert summary["total_embargoed"] == sum(s.n_embargoed for s in splits)
        assert summary["mean_train_size"] == pytest.approx(
            float(np.mean([s.n_train for s in splits]))
        )


class TestDegenerateSplits:
    def test_an_excessive_label_horizon_can_leave_no_training_data(self):
        # A horizon long enough to purge the whole sample makes every split
        # unusable. Those splits are still yielded so the caller can see the
        # configuration is wrong rather than silently receiving nothing.
        config = CPCVConfig(n_groups=4, n_test_groups=2, label_horizon=100)
        splits = list(combinatorial_purged_splits(20, config))
        assert splits
        assert all(not split.is_usable for split in splits)
        assert cpcv_summary(20, config)["n_degenerate_splits"] == len(splits)

    def test_is_usable_is_true_for_a_sane_configuration(self):
        config = CPCVConfig(n_groups=5, n_test_groups=2, label_horizon=1, embargo_pct=0.02)
        assert all(split.is_usable for split in combinatorial_purged_splits(50, config))


class TestConfigValidation:
    def test_n_groups_below_two_is_rejected(self):
        with pytest.raises(ValueError, match="n_groups"):
            CPCVConfig(n_groups=1, n_test_groups=1)

    def test_zero_test_groups_is_rejected(self):
        with pytest.raises(ValueError, match="n_test_groups"):
            CPCVConfig(n_groups=4, n_test_groups=0)

    def test_test_groups_not_fewer_than_groups_is_rejected(self):
        with pytest.raises(ValueError, match="fewer than"):
            CPCVConfig(n_groups=4, n_test_groups=4)

    def test_negative_label_horizon_is_rejected(self):
        with pytest.raises(ValueError, match="label_horizon"):
            CPCVConfig(n_groups=4, n_test_groups=2, label_horizon=-1)

    def test_out_of_range_embargo_is_rejected(self):
        with pytest.raises(ValueError, match="embargo_pct"):
            CPCVConfig(n_groups=4, n_test_groups=2, embargo_pct=-0.1)
        with pytest.raises(ValueError, match="embargo_pct"):
            CPCVConfig(n_groups=4, n_test_groups=2, embargo_pct=1.0)

    def test_config_serialises(self):
        json.dumps(CPCVConfig(n_groups=6, n_test_groups=2, label_horizon=5).to_dict(), allow_nan=False)


class TestEquivalentToAGreedyBaseline:
    def test_single_test_group_configuration_matches_a_manual_purge(self):
        """Recompute the purge by hand for one split and compare exactly."""
        n_samples, horizon, groups = 50, 4, 5
        config = CPCVConfig(n_groups=groups, n_test_groups=1, label_horizon=horizon)
        bounds = group_bounds(n_samples, groups)
        block_start, block_end = bounds[2]

        split = next(
            s for s in combinatorial_purged_splits(n_samples, config) if s.test_groups == (2,)
        )

        expected_train = np.array(
            [
                i
                for i in range(n_samples)
                if not (block_start <= i < block_end)
                and not (block_start - horizon <= i <= block_end - 1 + horizon)
            ]
        )
        assert np.array_equal(split.train_indices, expected_train)
        assert split.n_purged == 2 * horizon
