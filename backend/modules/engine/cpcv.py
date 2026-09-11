"""Combinatorial Purged Cross-Validation (CPCV).

Why standard cross-validation cannot be used here
-------------------------------------------------

Financial labels are not exchangeable. A label attached to observation ``t`` is
typically computed from a *span* of future prices, ``[t, t + h]`` for a horizon
``h`` -- a "did liquidity seize up over the next two weeks" label depends on data
that runs two weeks past ``t``. Consecutive observations therefore share label
information, and an ordinary k-fold split leaks: a training observation at
``t - 1`` carries information about the test observation at ``t`` because their
label spans overlap. The model scores well and the score is an artefact.

Walk-forward splitting removes the obvious form of that leak, but it has two
other problems: it produces a single path, so there is no distribution of
outcomes to reason about, and because it always trains on the past and tests on
the future it cannot be shuffled or repeated to gauge variance.

CPCV (López de Prado, *Advances in Financial Machine Learning*, ch. 7 and 12)
addresses all three:

* **Combinatorial.** ``N`` groups, choose ``k`` as the test set: ``C(N, k)``
  splits instead of one. That yields a *distribution* of out-of-sample results
  rather than a single number, which is the only way to say whether a model is
  robust or lucky.
* **Purged.** Any training observation whose label span overlaps the test set's
  label span is removed. The overlap is the leak.
* **Embargoed.** A further block immediately *after* the test set is removed from
  training. Purging removes label overlap; embargo removes the serial correlation
  that extends past the label span (features measured at ``t`` and ``t + 1`` are
  correlated even when their labels do not overlap).

Two quantities matter and are easy to confuse:

* ``n_splits = C(N, k)`` -- how many train/test evaluations exist.
* ``n_paths = (k / N) * C(N, k)`` -- how many *complete* backtest paths can be
  assembled from them, where a path tests every group exactly once. For the
  canonical ``N = 6, k = 2`` this is ``C(6,2) = 15`` splits and ``5`` paths.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import combinations
from math import comb
from typing import Dict, Iterator, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

__all__ = [
    "CPCVConfig",
    "CPCVSplit",
    "group_bounds",
    "n_splits",
    "n_backtest_paths",
    "combinatorial_purged_splits",
    "cpcv_summary",
]


@dataclass(frozen=True)
class CPCVConfig:
    """Cross-validation parameters.

    Attributes:
        n_groups: Number of contiguous groups the sample is split into. Each
            group is a block of consecutive observations, because the sample is
            ordered in time and a group must be a time interval for purging to
            mean anything.
        n_test_groups: Groups held out per split. Must be at least 1 and fewer
            than ``n_groups``, so that training data always remains.
        label_horizon: Number of observations each label spans forward from its
            own timestamp. ``0`` means labels are point-in-time and there is
            nothing to purge; a multi-day label horizon must be stated in the
            units of the sample.
        embargo_pct: Fraction of the total sample removed from training
            immediately after each test block, to defeat serial correlation that
            outlives the label span. In ``[0, 1)``.
    """

    n_groups: int = 6
    n_test_groups: int = 2
    label_horizon: int = 0
    embargo_pct: float = 0.0

    def __post_init__(self) -> None:
        if self.n_groups < 2:
            raise ValueError(f"n_groups must be at least 2, got {self.n_groups}")
        if self.n_test_groups < 1:
            raise ValueError(
                f"n_test_groups must be at least 1, got {self.n_test_groups}"
            )
        if self.n_test_groups >= self.n_groups:
            raise ValueError(
                f"n_test_groups ({self.n_test_groups}) must be fewer than "
                f"n_groups ({self.n_groups}); otherwise no training data remains"
            )
        if self.label_horizon < 0:
            raise ValueError(
                f"label_horizon must be non-negative, got {self.label_horizon}"
            )
        if not 0.0 <= self.embargo_pct < 1.0:
            raise ValueError(
                f"embargo_pct must be in [0, 1), got {self.embargo_pct}"
            )

    def to_dict(self) -> Dict[str, object]:
        return {
            "n_groups": self.n_groups,
            "n_test_groups": self.n_test_groups,
            "label_horizon": self.label_horizon,
            "embargo_pct": self.embargo_pct,
        }


@dataclass
class CPCVSplit:
    """One train/test evaluation.

    ``train_indices`` already excludes the purged and embargoed observations, so a
    caller can use it directly without re-deriving the exclusions.
    """

    fold: int
    test_groups: Tuple[int, ...]
    train_indices: np.ndarray
    test_indices: np.ndarray
    n_purged: int
    n_embargoed: int
    n_samples: int

    @property
    def n_train(self) -> int:
        return int(np.asarray(self.train_indices).size)

    @property
    def n_test(self) -> int:
        return int(np.asarray(self.test_indices).size)

    @property
    def is_usable(self) -> bool:
        """Whether the split has both training and test data."""
        return self.n_train > 0 and self.n_test > 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "fold": int(self.fold),
            "test_groups": [int(g) for g in self.test_groups],
            "n_train": self.n_train,
            "n_test": self.n_test,
            "n_purged": int(self.n_purged),
            "n_embargoed": int(self.n_embargoed),
            "n_samples": int(self.n_samples),
            "is_usable": self.is_usable,
        }


def group_bounds(n_samples: int, n_groups: int) -> List[Tuple[int, int]]:
    """Half-open ``[start, end)`` bounds for ``n_groups`` near-equal blocks.

    Remainder observations are distributed one each to the earliest groups, so
    group sizes differ by at most one. Contiguity is the point: a group must be a
    time interval, otherwise purging its boundary is meaningless.
    """
    if n_samples <= 0:
        raise ValueError(f"n_samples must be positive, got {n_samples}")
    if n_groups < 1:
        raise ValueError(f"n_groups must be positive, got {n_groups}")
    if n_groups > n_samples:
        raise ValueError(
            f"cannot split {n_samples} observations into {n_groups} non-empty groups"
        )

    base, remainder = divmod(n_samples, n_groups)
    bounds: List[Tuple[int, int]] = []
    start = 0
    for index in range(n_groups):
        size = base + (1 if index < remainder else 0)
        bounds.append((start, start + size))
        start += size
    return bounds


def n_splits(n_groups: int, n_test_groups: int) -> int:
    """Number of train/test evaluations: ``C(n_groups, n_test_groups)``."""
    if not 0 < n_test_groups < n_groups:
        raise ValueError(
            f"need 0 < n_test_groups ({n_test_groups}) < n_groups ({n_groups})"
        )
    return comb(n_groups, n_test_groups)


def n_backtest_paths(n_groups: int, n_test_groups: int) -> int:
    """Number of complete backtest paths assemblable from the splits.

    ``(k / N) * C(N, k)``. Each path covers every group exactly once as test
    data; the total number of test-group slots is ``k * C(N, k)`` and each path
    consumes ``N``, hence the ratio. Non-integer results are impossible for valid
    inputs.
    """
    if not 0 < n_test_groups < n_groups:
        raise ValueError(
            f"need 0 < n_test_groups ({n_test_groups}) < n_groups ({n_groups})"
        )
    return n_test_groups * comb(n_groups, n_test_groups) // n_groups


def _contiguous_blocks(indices: np.ndarray) -> List[Tuple[int, int]]:
    """Maximal runs of consecutive integers, as half-open ``[start, end)``."""
    if indices.size == 0:
        return []
    ordered = np.sort(np.asarray(indices, dtype=int))
    breaks = np.nonzero(np.diff(ordered) > 1)[0]
    starts = np.concatenate(([0], breaks + 1))
    ends = np.concatenate((breaks + 1, [ordered.size]))
    return [(int(ordered[a]), int(ordered[b - 1]) + 1) for a, b in zip(starts, ends)]


def combinatorial_purged_splits(
    n_samples: int,
    config: Optional[CPCVConfig] = None,
) -> Iterator[CPCVSplit]:
    """Yield every purged, embargoed combinatorial train/test split.

    For each combination of ``config.n_test_groups`` groups, the test set is the
    union of those groups and the training set is everything else, minus:

    * every observation whose label span ``[i, i + label_horizon]`` overlaps the
      test set's label span -- the **purge**; and
    * every observation within the embargo window immediately after each test
      block -- the **embargo**.

    Splits are yielded in a deterministic order (lexicographic by group
    combination), so a backtest is reproducible.

    Args:
        n_samples: Total number of time-ordered observations.
        config: Parameters. Defaults to :class:`CPCVConfig` values.

    Yields:
        :class:`CPCVSplit`, including degenerate splits (see ``is_usable``) rather
        than silently skipping them; the caller decides whether to filter.
    """
    config = config or CPCVConfig()
    bounds = group_bounds(n_samples, config.n_groups)
    embargo_size = int(np.floor(config.embargo_pct * n_samples))

    all_indices = np.arange(n_samples, dtype=int)
    group_indices = [np.arange(start, end, dtype=int) for start, end in bounds]

    for fold, combo in enumerate(combinations(range(config.n_groups), config.n_test_groups)):
        test_indices = np.sort(np.concatenate([group_indices[g] for g in combo]))

        excluded = np.zeros(n_samples, dtype=bool)
        excluded[test_indices] = True

        n_purged = 0
        n_embargoed = 0

        for block_start, block_end in _contiguous_blocks(test_indices):
            # Purge: a training label [i, i + h] overlaps the test label span
            # [block_start, block_end - 1 + h] exactly when
            #     i >= block_start - h   and   i <= block_end - 1 + h.
            purge_lo = max(0, block_start - config.label_horizon)
            purge_hi = min(n_samples - 1, block_end - 1 + config.label_horizon)

            # Embargo: a further block after the test set, for serial correlation
            # that outlives the label span.
            embargo_hi = min(n_samples - 1, block_end - 1 + embargo_size)

            window_hi = max(purge_hi, embargo_hi)
            window = np.arange(purge_lo, window_hi + 1, dtype=int)
            new = window[~excluded[window]]
            if new.size:
                excluded[new] = True
                n_purged += int(np.sum(new <= purge_hi))
                n_embargoed += int(np.sum(new > purge_hi))

        train_indices = all_indices[~excluded]

        yield CPCVSplit(
            fold=fold,
            test_groups=tuple(int(g) for g in combo),
            train_indices=train_indices,
            test_indices=test_indices,
            n_purged=n_purged,
            n_embargoed=n_embargoed,
            n_samples=n_samples,
        )


def cpcv_summary(n_samples: int, config: Optional[CPCVConfig] = None) -> Dict[str, object]:
    """Describe a CPCV configuration without materialising every split's indices.

    Materialising the splits to count usable ones is O(C(N,k) * n_samples), which
    is wasteful when only the shape is wanted; this walks the splits but discards
    the index arrays.
    """
    config = config or CPCVConfig()
    usable = 0
    degenerate = 0
    total_purged = 0
    total_embargoed = 0
    train_sizes: List[int] = []

    for split in combinatorial_purged_splits(n_samples, config):
        total_purged += split.n_purged
        total_embargoed += split.n_embargoed
        train_sizes.append(split.n_train)
        if split.is_usable:
            usable += 1
        else:
            degenerate += 1

    bounds = group_bounds(n_samples, config.n_groups)
    intended = n_splits(config.n_groups, config.n_test_groups)

    return {
        "config": config.to_dict(),
        "n_samples": int(n_samples),
        "group_bounds": [[int(a), int(b)] for a, b in bounds],
        "group_sizes": [int(b - a) for a, b in bounds],
        "n_splits": usable,
        "n_degenerate_splits": degenerate,
        "n_splits_expected": intended,
        "n_backtest_paths": n_backtest_paths(config.n_groups, config.n_test_groups),
        "embargo_size": int(np.floor(config.embargo_pct * n_samples)),
        "total_purged": int(total_purged),
        "total_embargoed": int(total_embargoed),
        "mean_train_size": float(np.mean(train_sizes)) if train_sizes else 0.0,
        "min_train_size": int(np.min(train_sizes)) if train_sizes else 0,
    }
