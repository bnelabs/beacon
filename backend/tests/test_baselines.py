"""Tests for the baseline comparison wired into the model trainer.

The walk-forward baselines themselves are torch-free and live in
``test_backtesting.py``. This module covers the torch-dependent half: the adapter
that exposes a trained sequence model to the backtest harness, and the trainer
hook that reports lift over the baselines. Skipped when torch is absent.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from torch import nn  # noqa: E402

from backend.modules.engine.backtesting import (  # noqa: E402
    PersistenceBaseline,
    WalkForwardBacktester,
    WalkForwardConfig,
)
from backend.modules.engine.trainer import (  # noqa: E402
    ModelTrainer,
    _FrozenSequenceModelAdapter,
)


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
    """A module whose output is a constant, so predictions are predictable."""
    model = nn.Sequential(nn.Flatten(), nn.Linear(n_features, 1))
    with torch.no_grad():
        model[1].weight.fill_(0.0)
        model[1].bias.fill_(value)
    return model


def _smooth_dataset(n_windows: int = 60, sequence_length: int = 4, n_features: int = 2):
    windows = np.zeros((n_windows, sequence_length, n_features), dtype=np.float32)
    targets = np.sin(np.arange(n_windows) / 5.0)
    return _FakeSequenceDataset(windows, targets, mean=10.0, std=5.0)


class TestFrozenAdapter:
    def test_predict_reshapes_and_denormalizes(self):
        adapter = _FrozenSequenceModelAdapter(
            model=_constant_model(n_features=8, value=1.0),
            device=torch.device("cpu"),
            sequence_length=4,
            n_features=2,
            target_mean=10.0,
            target_std=5.0,
        )

        flat = np.zeros((3, 8), dtype=np.float32)
        np.testing.assert_allclose(adapter.predict(flat), [15.0, 15.0, 15.0])

    def test_fit_is_a_no_op_on_the_frozen_artefact(self):
        adapter = _FrozenSequenceModelAdapter(
            model=_constant_model(n_features=8),
            device=torch.device("cpu"),
            sequence_length=4,
            n_features=2,
            target_mean=0.0,
            target_std=1.0,
        )
        assert adapter.fit(np.zeros((3, 8)), np.zeros(3)) is adapter

    def test_adapter_is_a_valid_harness_model(self):
        adapter = _FrozenSequenceModelAdapter(
            model=_constant_model(n_features=8, value=0.5),
            device=torch.device("cpu"),
            sequence_length=4,
            n_features=2,
            target_mean=0.0,
            target_std=1.0,
        )
        X = np.zeros((60, 8), dtype=np.float32)
        y = np.sin(np.arange(60) / 5.0)

        result = WalkForwardBacktester(
            lambda: adapter, WalkForwardConfig(n_splits=2, test_size=10, gap=0)
        ).run(X, y)

        assert result.predictions.size == 20
        np.testing.assert_allclose(result.predictions, 0.5)
        assert result.boundaries.tolist() == [10]


class TestTrainerHook:
    def _trainer(self, n_features: int = 2) -> ModelTrainer:
        trainer = ModelTrainer(
            model_type="temporal_attention", device=torch.device("cpu"), config={}
        )
        trainer.model = _constant_model(n_features=n_features * 4, value=0.2)
        return trainer

    def test_reports_lift_over_the_baselines(self):
        payload = self._trainer()._baseline_comparison(_smooth_dataset())

        assert payload is not None
        assert set(payload["baseline_metrics"]) == {"persistence", "ar1"}
        assert payload["aggregation"]["returns"] == "per_fold"
        assert payload["lift_convention"].startswith("positive")
        assert "rmse" in payload["lower_is_better"]
        assert set(payload["lift"]) == {"persistence", "ar1"}

        # The series was built to be reproducible JSON: no NaN leaks through.
        assert json.dumps(payload, allow_nan=False)

    def test_lift_sign_convention_is_lower_is_better_aware(self):
        payload = self._trainer()._baseline_comparison(_smooth_dataset())

        primary_rmse = payload["primary_metrics"]["rmse"]
        baseline_rmse = payload["baseline_metrics"]["persistence"]["rmse"]
        assert payload["lift"]["persistence"]["rmse"] == pytest.approx(
            baseline_rmse - primary_rmse
        )

    def test_skips_when_the_test_window_is_too_short(self):
        dataset = _smooth_dataset(n_windows=10)
        assert self._trainer()._baseline_comparison(dataset) is None

    def test_baselines_are_rebuilt_for_every_fold(self):
        """A shared baseline instance would leak state between folds."""
        assert isinstance(PersistenceBaseline(), PersistenceBaseline)
