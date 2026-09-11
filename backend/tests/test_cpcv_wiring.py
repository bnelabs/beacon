"""CPCV is reachable from the production trainer path, not just importable.

``backend/modules/engine/cpcv.py`` contained a complete, well-tested CPCV
implementation that **nothing in production imported** -- the only importer was
``test_cpcv.py``. The engine validated with walk-forward folds
(``backtesting.generate_walk_forward_folds``) while the documentation described
CPCV as the validation scheme in use. A tested module that nothing calls is
indistinguishable from a capability the system does not have, except that it makes
the documentation overstate the system.

These tests cover the wiring rather than the combinatorics (``test_cpcv.py``
already covers those): that the trainer selects CPCV from configuration, and that
the backtest result is a *distribution* rather than a concatenated series.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from torch import nn  # noqa: E402

from backend.modules.engine.backtesting import (  # noqa: E402
    CPCVBacktester,
    cpcv_split_boundaries,
    generate_cpcv_folds,
)
from backend.modules.engine.cpcv import CPCVConfig, combinatorial_purged_splits  # noqa: E402
from backend.modules.engine.trainer import ModelTrainer, _FrozenSequenceModelAdapter  # noqa: E402


class _FakeSequenceDataset:
    """Duck-typed stand-in for ``TimeSeriesDataset``."""

    def __init__(self, windows, targets, mean=0.0, std=1.0):
        self.sequences = windows
        self.targets = targets
        self.target_mean = mean
        self.target_std = std

    def denormalize(self, values):
        return values * self.target_std + self.target_mean


def _constant_model(n_features: int, value: float = 1.0) -> nn.Module:
    model = nn.Sequential(nn.Flatten(), nn.Linear(n_features, 1))
    with torch.no_grad():
        model[1].weight.fill_(0.0)
        model[1].bias.fill_(value)
    return model


def _smooth_dataset(n_windows: int = 60, sequence_length: int = 4, n_features: int = 2):
    windows = np.zeros((n_windows, sequence_length, n_features), dtype=np.float32)
    targets = np.sin(np.arange(n_windows) / 5.0)
    return _FakeSequenceDataset(windows, targets, mean=10.0, std=5.0)


def _adapter(value: float = 0.5) -> _FrozenSequenceModelAdapter:
    """The production harness adapter over a constant model (8 = 4 x 2 input)."""
    return _FrozenSequenceModelAdapter(
        model=_constant_model(n_features=8, value=value),
        device=torch.device("cpu"),
        sequence_length=4,
        n_features=2,
        target_mean=0.0,
        target_std=1.0,
    )


def _trainer(config=None) -> ModelTrainer:
    trainer = ModelTrainer(
        model_type="temporal_attention",
        device=torch.device("cpu"),
        config=config or {},
    )
    trainer.model = _constant_model(n_features=8, value=0.2)
    return trainer


class TestGenerator:
    def test_returns_every_split_including_adjacent_test_groups(self):
        config = CPCVConfig(n_groups=6, n_test_groups=2)
        splits = generate_cpcv_folds(60, config)

        assert len(splits) == 15
        assert all(split.is_usable for split in splits)

    def test_raises_rather_than_returning_an_empty_validation(self):
        """An empty fold list would read downstream as 'validated'."""
        # label_horizon longer than the sample purges everything out of training.
        with pytest.raises(ValueError, match="no usable split"):
            generate_cpcv_folds(4, CPCVConfig(n_groups=4, n_test_groups=3, label_horizon=100))

    def test_purge_removes_training_observations_near_the_test_block(self):
        unpurged = generate_cpcv_folds(60, CPCVConfig(n_groups=6, n_test_groups=1))
        purged = generate_cpcv_folds(
            60, CPCVConfig(n_groups=6, n_test_groups=1, label_horizon=3)
        )

        assert all(split.n_purged == 0 for split in unpurged)
        assert sum(split.n_purged for split in purged) > 0
        # Same splits, strictly less training data once labels are purged.
        assert sum(s.n_train for s in purged) < sum(s.n_train for s in unpurged)


class TestNoConcatenation:
    def test_cpcv_test_sets_overlap_so_concatenation_would_double_count(self):
        """This is the reason the result is a distribution, not an OOS series."""
        splits = generate_cpcv_folds(60, CPCVConfig(n_groups=6, n_test_groups=2))

        occurrences = np.zeros(60, dtype=int)
        for split in splits:
            occurrences[split.test_indices] += 1

        # Every observation is held out more than once; a concatenated series
        # would therefore be longer than the sample and score some points twice.
        assert occurrences.min() >= 1
        assert sum(split.n_test for split in splits) > 60
        assert occurrences.max() > 1

    def test_result_exposes_a_distribution_and_no_concatenated_series(self):
        X = np.zeros((60, 8), dtype=np.float32)
        y = np.sin(np.arange(60) / 5.0)
        adapter = _adapter()

        result = CPCVBacktester(
            lambda: adapter, CPCVConfig(n_groups=6, n_test_groups=2)
        ).run(X, y)
        payload = result.to_dict()

        assert payload["scheme"] == "cpcv"
        # A distribution across splits...
        assert set(payload["metric_dispersion"]) == {
            "mse",
            "mae",
            "rmse",
            "r2",
            "directional_accuracy",
            "hit_rate",
        }
        assert payload["n_backtest_paths"] == 5
        assert payload["n_usable_splits"] == 15
        # ...not a pooled out-of-sample series.
        assert "predictions" not in payload
        assert "actuals" not in payload
        assert "boundaries" not in payload

    def test_result_is_json_serialisable_without_nan(self):
        X = np.zeros((60, 8), dtype=np.float32)
        y = np.sin(np.arange(60) / 5.0)
        result = CPCVBacktester(
            lambda: _adapter(),
            CPCVConfig(n_groups=6, n_test_groups=2),
        ).run(X, y)

        assert json.dumps(result.to_dict(), allow_nan=False)


class TestHonestFoldSizes:
    def test_reported_training_size_is_counted_not_spanned(self):
        """``FoldResult`` derives ``n_train = end - start``, which is wrong here.

        A CPCV training set is the complement of the test groups minus purged and
        embargoed rows, so it has holes and its span overstates its size. The
        dedicated fold record must count.
        """
        X = np.zeros((60, 8), dtype=np.float32)
        y = np.sin(np.arange(60) / 5.0)
        config = CPCVConfig(n_groups=6, n_test_groups=1)
        result = CPCVBacktester(lambda: _adapter(), config).run(X, y)

        splits = {split.fold: split for split in combinatorial_purged_splits(60, config)}
        for fold in result.fold_results:
            split = splits[fold.fold]
            assert fold.n_train == int(split.train_indices.size)
            assert fold.n_test == int(split.test_indices.size)

        # With a single held-out interior group the training indices are genuinely
        # discontiguous, so the count is strictly below the span for some fold.
        assert any(
            fold.n_train < (int(np.ptp(splits[fold.fold].train_indices)) + 1)
            for fold in result.fold_results
        )

    def test_unusable_splits_are_reported_not_silently_dropped(self):
        """A long label horizon purges the training set out of some combinations."""
        config = CPCVConfig(n_groups=4, n_test_groups=2, label_horizon=6)
        X = np.zeros((20, 8), dtype=np.float32)
        y = np.sin(np.arange(20) / 5.0)
        result = CPCVBacktester(lambda: _adapter(), config).run(X, y)

        # The accounting identity: every generated split is either evaluated or
        # reported as unusable -- none vanishes.
        assert result.n_usable_splits + len(result.unusable_splits) == 6
        assert len(result.unusable_splits) > 0
        assert result.n_usable_splits > 0
        # An unusable split carries its own record rather than being an anonymous
        # gap in the fold numbering.
        assert all("fold" in record for record in result.unusable_splits)

    def test_directional_score_pools_within_contiguous_test_blocks(self):
        splits = list(
            combinatorial_purged_splits(60, CPCVConfig(n_groups=6, n_test_groups=2))
        )
        for split in splits:
            boundaries = cpcv_split_boundaries(split)
            assert all(0 < int(b) < split.n_test for b in boundaries)

        # Two adjacent held-out groups form one contiguous block: no interior seam,
        # so the directional score must pool across all 20 observations.
        adjacent = next(s for s in splits if s.test_groups == (0, 1))
        assert cpcv_split_boundaries(adjacent).size == 0

        # Two separated groups leave exactly one seam, at the group boundary.
        separated = next(s for s in splits if s.test_groups == (0, 2))
        assert cpcv_split_boundaries(separated).tolist() == [10]


class TestTrainerSelection:
    def test_defaults_to_walk_forward_and_preserves_legacy_keys(self):
        payload = _trainer()._baseline_comparison(_smooth_dataset())

        assert payload is not None
        assert payload["validation_scheme"] == "walk_forward"
        assert payload["cpcv"] is None
        # The pre-existing contract still holds for callers that asked for nothing.
        assert set(payload["baseline_metrics"]) == {"persistence", "ar1"}
        assert set(payload["lift"]) == {"persistence", "ar1"}
        assert "rmse" in payload["lower_is_better"]

    def test_cpcv_is_selectable_from_configuration(self):
        payload = _trainer({"validation_scheme": "cpcv"})._baseline_comparison(
            _smooth_dataset()
        )

        assert payload is not None
        assert payload["validation_scheme"] == "cpcv"
        assert payload["cpcv"] is not None
        # A CPCV-only run must not present CPCV numbers under a walk-forward key.
        assert payload["walk_forward"] is None
        assert "primary_metrics" not in payload

    def test_both_schemes_can_be_reported_together(self):
        payload = _trainer({"validation_scheme": "both"})._baseline_comparison(
            _smooth_dataset()
        )

        assert payload is not None
        assert payload["walk_forward"] is not None
        assert payload["cpcv"] is not None
        # Walk-forward fields stay at the top level for existing consumers.
        assert set(payload["baseline_metrics"]) == {"persistence", "ar1"}

    def test_cpcv_parameters_are_honoured_from_config(self):
        payload = _trainer(
            {
                "validation_scheme": "cpcv",
                "cpcv_n_groups": 5,
                "cpcv_n_test_groups": 1,
                "cpcv_label_horizon": 2,
            }
        )._baseline_comparison(_smooth_dataset())

        assert payload["cpcv"]["config"]["n_groups"] == 5
        assert payload["cpcv"]["config"]["n_test_groups"] == 1
        assert payload["cpcv"]["config"]["label_horizon"] == 2
        assert sum(fold["n_purged"] for fold in payload["cpcv"]["folds"]) > 0

    def test_an_unknown_scheme_raises_instead_of_being_ignored(self):
        """A typo must not silently downgrade the validation to walk-forward."""
        with pytest.raises(ValueError, match="validation_scheme"):
            _trainer({"validation_scheme": "CPVC"})._baseline_comparison(
                _smooth_dataset()
            )

    def test_cpcv_only_on_a_short_series_reports_no_comparison(self):
        """Too few windows for any scheme must not fabricate a verdict."""
        assert (
            _trainer({"validation_scheme": "cpcv"})._baseline_comparison(
                _smooth_dataset(n_windows=10)
            )
            is None
        )
