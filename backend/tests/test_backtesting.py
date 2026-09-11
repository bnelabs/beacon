"""Unit tests for the walk-forward backtesting framework.

The suite is deliberately torch-free (and pandas-free for the core cases) so it
can run on a minimal scientific-python install.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from backend.modules.engine import backtesting as bt


QUANT_METRIC_KEYS = (
    "sharpe_ratio",
    "sortino_ratio",
    "max_drawdown",
    "calmar_ratio",
    "annualized_volatility",
    "hit_rate",
    "var_95",
    "cvar_95",
)


class LinearStubModel:
    """Tiny least-squares model exposing the duck-typed fit/predict surface."""

    def __init__(self) -> None:
        self.coef_: np.ndarray | None = None
        self.intercept_: float = 0.0
        self.fit_calls: int = 0

    def fit(self, X, y) -> "LinearStubModel":
        features = np.asarray(X, dtype=float)
        design = np.column_stack([features, np.ones(features.shape[0])])
        solution, *_ = np.linalg.lstsq(design, np.asarray(y, dtype=float), rcond=None)
        self.coef_ = solution[:-1]
        self.intercept_ = float(solution[-1])
        self.fit_calls += 1
        return self

    def predict(self, X) -> np.ndarray:
        return np.asarray(X, dtype=float) @ self.coef_ + self.intercept_


# ---------------------------------------------------------------------------
# Fold generation
# ---------------------------------------------------------------------------
class TestWalkForwardFolds:
    def test_fold_count_and_no_leakage_with_gap(self):
        config = bt.WalkForwardConfig(n_splits=3, test_size=10, gap=2, expanding=True)
        folds = bt.generate_walk_forward_folds(100, config)

        assert len(folds) == 3
        for train_idx, test_idx in folds:
            assert isinstance(train_idx, np.ndarray) and isinstance(test_idx, np.ndarray)
            assert np.all(np.diff(train_idx) == 1)
            assert np.all(np.diff(test_idx) == 1)
            assert train_idx.max() < test_idx.min()
            assert train_idx.max() + config.gap < test_idx.min()
            assert test_idx.min() - train_idx.max() - 1 == config.gap

    def test_expanding_window_starts_at_zero_and_grows(self):
        config = bt.WalkForwardConfig(n_splits=3, test_size=10, gap=2, expanding=True)
        folds = bt.generate_walk_forward_folds(100, config)

        assert [len(train) for train, _ in folds] == [68, 78, 88]
        assert all(train[0] == 0 for train, _ in folds)
        assert [int(test[0]) for _, test in folds] == [70, 80, 90]
        assert [int(test[-1]) for _, test in folds] == [79, 89, 99]

    def test_rolling_window_keeps_constant_train_size(self):
        config = bt.WalkForwardConfig(n_splits=3, test_size=10, gap=2, expanding=False)
        folds = bt.generate_walk_forward_folds(100, config)

        assert {len(train) for train, _ in folds} == {68}
        for train_idx, test_idx in folds:
            assert train_idx[-1] == test_idx.min() - config.gap - 1
        assert [int(train[0]) for train, _ in folds] == [0, 10, 20]

    def test_fractional_test_size(self):
        config = bt.WalkForwardConfig(n_splits=2, test_size=0.1, gap=0, expanding=True)
        folds = bt.generate_walk_forward_folds(100, config)

        assert [(int(test[0]), int(test[-1])) for _, test in folds] == [(80, 89), (90, 99)]

    def test_default_config_is_usable(self):
        folds = bt.generate_walk_forward_folds(100, bt.WalkForwardConfig())
        assert len(folds) == 5

    @pytest.mark.parametrize(
        "config, n_samples",
        [
            (bt.WalkForwardConfig(n_splits=0, test_size=10), 100),
            (bt.WalkForwardConfig(n_splits=3, test_size=0), 100),
            (bt.WalkForwardConfig(n_splits=3, test_size=1.5), 100),
            (bt.WalkForwardConfig(n_splits=3, test_size=200), 100),
            (bt.WalkForwardConfig(n_splits=5, test_size=0.2), 50),
            (bt.WalkForwardConfig(n_splits=2, test_size=10, gap=-1), 100),
            (bt.WalkForwardConfig(n_splits=2, test_size=10, min_train_size=90), 100),
        ],
    )
    def test_invalid_configs_raise_value_error(self, config, n_samples):
        with pytest.raises(ValueError):
            bt.generate_walk_forward_folds(n_samples, config)

    def test_invalid_sample_counts_raise_value_error(self):
        config = bt.WalkForwardConfig(n_splits=2, test_size=10)
        with pytest.raises(ValueError):
            bt.generate_walk_forward_folds(100.5, config)
        with pytest.raises(ValueError):
            bt.generate_walk_forward_folds(-5, config)

    def test_empty_series_raises_value_error(self):
        with pytest.raises(ValueError):
            bt.generate_walk_forward_folds(0, bt.WalkForwardConfig(n_splits=1, test_size=5))


# ---------------------------------------------------------------------------
# Hand-computed quantitative metrics
# ---------------------------------------------------------------------------
class TestMetricsHandComputed:
    def test_sharpe_ratio(self):
        returns = np.array([0.02, 0.01, -0.01, 0.03, 0.0])
        # mean = 0.01, sample sd = sqrt(2.5e-4), * sqrt(252) -> 10.0399
        assert bt.sharpe_ratio(returns) == pytest.approx(10.0399, rel=1e-4)
        assert bt.sharpe_ratio(returns, risk_free=0.05) < bt.sharpe_ratio(returns, risk_free=0.0)

    def test_sortino_ratio(self):
        returns = np.array([0.02, 0.01, -0.01, 0.03, 0.0])
        # mean excess = 0.01; downside deviation = sqrt(1e-4 / 5) = sqrt(2e-5)
        # -> 0.01 / sqrt(2e-5) * sqrt(252) = sqrt(1260)
        assert bt.sortino_ratio(returns) == pytest.approx(math.sqrt(1260), rel=1e-9)
        assert bt.sortino_ratio(returns) > bt.sharpe_ratio(returns)

    def test_max_drawdown(self):
        equity = np.array([100.0, 120.0, 90.0, 110.0, 80.0, 130.0])
        assert bt.max_drawdown(equity) == pytest.approx(1.0 / 3.0, rel=1e-12)

    def test_rmse_and_r2(self):
        actual = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        predicted = np.array([1.1, 1.9, 3.2, 3.8, 5.1])

        assert bt.mean_squared_error(actual, predicted) == pytest.approx(0.022, rel=1e-12)
        assert bt.rmse(actual, predicted) == pytest.approx(math.sqrt(0.022), rel=1e-12)
        assert bt.mae(actual, predicted) == pytest.approx(0.14, rel=1e-12)
        assert bt.r2_score_(actual, predicted) == pytest.approx(0.989, rel=1e-12)

    def test_var_and_cvar(self):
        returns = np.array([-0.05, -0.03, -0.01, 0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06])
        var_95 = bt.value_at_risk(returns, level=0.95)
        cvar_95 = bt.conditional_value_at_risk(returns, level=0.95)

        assert var_95 == pytest.approx(0.041, rel=1e-12)
        assert cvar_95 == pytest.approx(0.05, rel=1e-12)
        assert cvar_95 >= var_95

    def test_invalid_var_level_raises(self):
        with pytest.raises(ValueError):
            bt.value_at_risk(np.array([0.1, -0.1]), level=1.0)
        with pytest.raises(ValueError):
            bt.conditional_value_at_risk(np.array([0.1, -0.1]), level=0.0)

    def test_risk_signal_convention(self):
        risk = np.array([0.1, 0.15, 0.12, 0.2])
        np.testing.assert_allclose(bt.risk_signal_to_returns(risk), [-0.05, 0.03, -0.08])

    def test_equity_curve_shape(self):
        returns = np.array([0.0, 0.0, 0.0])
        equity = bt.equity_curve_from_returns(returns)
        assert equity.shape == (4,)
        np.testing.assert_allclose(equity, [1.0, 1.0, 1.0, 1.0])


# ---------------------------------------------------------------------------
# Degenerate input
# ---------------------------------------------------------------------------
class TestDegenerateInputs:
    def test_empty_series(self):
        empty = np.array([])
        assert math.isnan(bt.sharpe_ratio(empty))
        assert math.isnan(bt.sortino_ratio(empty))
        assert bt.max_drawdown(empty) == 0.0
        assert math.isnan(bt.annualized_volatility(empty))
        assert math.isnan(bt.calmar_ratio(empty))
        assert math.isnan(bt.hit_rate(empty, empty))
        assert math.isnan(bt.mean_squared_error(empty, empty))
        assert math.isnan(bt.mae(empty, empty))
        assert math.isnan(bt.rmse(empty, empty))
        assert math.isnan(bt.r2_score_(empty, empty))
        assert math.isnan(bt.value_at_risk(empty))
        assert math.isnan(bt.conditional_value_at_risk(empty))
        assert bt.risk_signal_to_returns(empty).size == 0

    def test_constant_series(self):
        zeros = np.zeros(5)
        assert bt.sharpe_ratio(zeros) == 0.0
        assert bt.sortino_ratio(zeros) == 0.0
        assert bt.annualized_volatility(zeros) == 0.0
        assert bt.max_drawdown(zeros) == 0.0
        assert bt.max_drawdown(bt.equity_curve_from_returns(zeros)) == 0.0
        assert bt.r2_score_(zeros, zeros) == 0.0
        assert bt.mean_squared_error(zeros, zeros) == 0.0
        assert bt.rmse(zeros, zeros) == 0.0
        assert math.isnan(bt.hit_rate(zeros, zeros))

    def test_single_element(self):
        one = np.array([0.5])
        assert math.isnan(bt.sharpe_ratio(one))
        assert math.isnan(bt.sortino_ratio(one))
        assert math.isnan(bt.annualized_volatility(one))
        assert bt.max_drawdown(one) == 0.0
        assert bt.max_drawdown(bt.equity_curve_from_returns(one)) == 0.0
        assert math.isnan(bt.hit_rate(one, one))
        assert bt.mean_squared_error(one, one) == 0.0
        assert bt.rmse(one, one) == 0.0
        # A single point is a zero-variance target, so R^2 reports 0.0.
        assert bt.r2_score_(one, one) == 0.0
        assert bt.risk_signal_to_returns(one).size == 0


# ---------------------------------------------------------------------------
# compute_metrics bundle
# ---------------------------------------------------------------------------
class TestComputeMetrics:
    def test_all_keys_present_with_ground_truth(self):
        actual = np.linspace(0.0, 1.0, 40)
        predicted = actual + 0.01 * np.sin(np.arange(40))
        metrics = bt.compute_metrics(actual=actual, predicted=predicted)

        for key in ("mse", "mae", "rmse", "r2", "directional_accuracy", *QUANT_METRIC_KEYS):
            assert key in metrics
        assert metrics["rmse"] < 0.02

    def test_quant_metrics_without_ground_truth(self):
        predicted = np.linspace(0.0, 1.0, 30)
        metrics = bt.compute_metrics(predicted=predicted)

        assert math.isnan(metrics["mse"])
        for key in QUANT_METRIC_KEYS:
            assert key in metrics

    def test_requires_some_signal(self):
        with pytest.raises(ValueError):
            bt.compute_metrics()
        with pytest.raises(ValueError):
            bt.compute_metrics(actual=np.array([1.0, 2.0]))


# ---------------------------------------------------------------------------
# End-to-end backtester
# ---------------------------------------------------------------------------
class TestWalkForwardBacktester:
    def test_oos_length_and_fresh_models(self):
        n_samples = 120
        X = np.linspace(0.0, 1.0, n_samples).reshape(-1, 1)
        y = 3.0 * X.ravel() + 2.0

        created: list[LinearStubModel] = []

        def factory() -> LinearStubModel:
            model = LinearStubModel()
            created.append(model)
            return model

        config = bt.WalkForwardConfig(n_splits=3, test_size=20, gap=2, expanding=True)
        result = bt.WalkForwardBacktester(factory, config).run(X, y)

        expected_oos = sum(len(test) for _, test in bt.generate_walk_forward_folds(n_samples, config))
        assert expected_oos == 60
        assert result.predictions.shape[0] == expected_oos
        assert result.actuals.shape == result.predictions.shape

        assert len(created) == config.n_splits
        assert len({id(model) for model in created}) == config.n_splits
        assert all(model.fit_calls == 1 for model in created)

        assert result.metrics.r2 > 0.99
        assert math.isfinite(result.metrics.rmse)
        for key in QUANT_METRIC_KEYS:
            assert hasattr(result.metrics, key)
        assert len(result.folds) == config.n_splits

    def test_result_to_dict_is_strictly_json_serialisable(self):
        X = np.linspace(0.0, 1.0, 80).reshape(-1, 1)
        y = np.cos(X.ravel())
        config = bt.WalkForwardConfig(n_splits=2, test_size=20, gap=1)

        result = bt.WalkForwardBacktester(lambda: LinearStubModel(), config).run(X, y)
        payload = result.to_dict()

        encoded = json.dumps(payload, allow_nan=False)
        assert encoded

        decoded = json.loads(encoded)
        assert decoded["n_oos"] == 40
        assert decoded["walk_forward"]["config"]["n_splits"] == 2
        assert len(decoded["walk_forward"]["folds"]) == 2
        for key in QUANT_METRIC_KEYS:
            assert key in decoded["metrics"]

    def test_pandas_inputs_supported(self):
        pd = pytest.importorskip("pandas")
        X = pd.DataFrame({"feature": np.linspace(0.0, 1.0, 60)})
        y = pd.Series(2.0 * X["feature"] + 1.0)
        config = bt.WalkForwardConfig(n_splits=2, test_size=15, gap=1)

        result = bt.WalkForwardBacktester(lambda: LinearStubModel(), config).run(X, y)
        assert result.predictions.shape[0] == 30

    def test_mismatched_lengths_raise(self):
        X = np.zeros((10, 2))
        y = np.zeros(9)
        with pytest.raises(ValueError):
            bt.WalkForwardBacktester(lambda: LinearStubModel()).run(X, y)

    def test_invalid_factory_raises(self):
        with pytest.raises(TypeError):
            bt.WalkForwardBacktester("not-callable")

        class NoFit:
            def predict(self, X):
                return X

        with pytest.raises(TypeError):
            bt.WalkForwardBacktester(NoFit).run(np.zeros((20, 1)), np.zeros(20))

    def test_fold_predictions_have_expected_length(self):
        n_samples = 60
        X = np.arange(n_samples, dtype=float).reshape(-1, 1)
        y = X.ravel()
        config = bt.WalkForwardConfig(n_splits=2, test_size=15, gap=0)
        result = bt.WalkForwardBacktester(lambda: LinearStubModel(), config).run(X, y)

        assert [fold.n_test for fold in result.folds] == [15, 15]
        for fold in result.folds:
            assert fold.to_dict()["n_test"] == 15
