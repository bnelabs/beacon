"""Walk-forward backtesting and quantitative metrics for liquidity-risk models.

Signal-to-return convention
===========================
BEACON models predict a *liquidity-risk level*, not a financial return. For
liquidity risk a RISE in predicted risk is a NEGATIVE return::

    return_t = -(risk_t - risk_{t-1})

Every return-based metric in this module (Sharpe, Sortino, drawdown, Calmar,
VaR/CVaR) consumes that sign-flipped series. The public helper
:func:`risk_signal_to_returns` implements the convention so callers do not have
to restate it.

When :class:`WalkForwardBacktester` concatenates out-of-sample predictions
across folds, ``np.diff`` is applied to the concatenated signal, so each fold
boundary contributes exactly one transition that did not exist in the
underlying series. Per-fold metrics are computed *inside* each fold (and are
therefore free of that artefact); the aggregate metrics should be read with the
boundary transition in mind.

Degenerate-input policy
=======================
Every metric tolerates empty, constant, and single-element input and never
raises ``ZeroDivisionError``. The deliberate return values are:

* Empty input -> ``float('nan')`` for ratios, error metrics, and tail-risk
  metrics (the statistic is undefined); :func:`max_drawdown` returns ``0.0``
  because an empty curve has no drawdown by definition.
* Constant / zero-variance input -> ``0.0`` for Sharpe, Sortino, and
  annualized volatility (there is no dispersion to reward or penalise), and for
  R^2 against a constant target.
* Zero downside deviation -> Sortino ``0.0`` rather than ``inf`` so results
  stay JSON-serialisable.
* Constant series -> ``nan`` for :func:`hit_rate`, because a series with no
  non-zero changes carries no directional signal to score.
* Single element -> ``nan`` for dispersion-based metrics (sample variance needs
  at least two observations).

Metrics align their inputs on the common prefix, so slightly mismatched series
degrade instead of raising. :meth:`WalkForwardBacktester.run` is stricter and
rejects genuinely mismatched ``X``/``y``.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np

try:  # pandas is a runtime convenience, not a hard requirement of the framework
    import pandas as pd

    _HAS_PANDAS = True
except ImportError:  # pragma: no cover - exercised only in minimal environments
    pd = None  # type: ignore[assignment]
    _HAS_PANDAS = False

logger = logging.getLogger(__name__)

ArrayLike = Union[Sequence[float], np.ndarray, Any]
IndexPair = Tuple[np.ndarray, np.ndarray]

_METRIC_KEYS: Tuple[str, ...] = (
    "mse",
    "mae",
    "rmse",
    "r2",
    "directional_accuracy",
    "hit_rate",
    "sharpe_ratio",
    "sortino_ratio",
    "max_drawdown",
    "calmar_ratio",
    "annualized_volatility",
    "var_95",
    "cvar_95",
)


# ---------------------------------------------------------------------------
# Input coercion helpers
# ---------------------------------------------------------------------------
def _as_1d(values: ArrayLike) -> np.ndarray:
    """Coerce array-like input (including pandas objects) to a 1-D float array."""
    if values is None:
        return np.array([], dtype=float)
    if _HAS_PANDAS and isinstance(values, (pd.Series, pd.DataFrame)):
        values = values.to_numpy()
    try:
        array = np.asarray(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Could not interpret input as a numeric array: {exc}") from exc
    return array.ravel()


def _as_2d(values: ArrayLike) -> np.ndarray:
    """Coerce array-like input (including pandas objects) to a 2-D float array."""
    if values is None:
        return np.empty((0, 1), dtype=float)
    if _HAS_PANDAS and isinstance(values, (pd.DataFrame, pd.Series)):
        values = values.to_numpy()
    try:
        array = np.asarray(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Could not interpret input as a numeric array: {exc}") from exc
    if array.ndim == 1:
        array = array.reshape(-1, 1)
    if array.ndim != 2:
        raise ValueError(f"Expected a 1-D or 2-D feature array, got shape {array.shape}")
    return array


def _json_safe(value: Any) -> Any:
    """Return a strictly JSON-serialisable number (non-finite -> None)."""
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _validate_level(level: float) -> float:
    level = float(level)
    if not 0.0 < level < 1.0:
        raise ValueError(f"level must be strictly between 0 and 1, got {level!r}")
    return level


def _validate_periods(periods_per_year: float) -> float:
    periods = float(periods_per_year)
    if not math.isfinite(periods) or periods <= 0.0:
        raise ValueError(f"periods_per_year must be a positive number, got {periods_per_year!r}")
    return periods


# ---------------------------------------------------------------------------
# Signal / return transformations
# ---------------------------------------------------------------------------
def risk_signal_to_returns(risk_signal: ArrayLike) -> np.ndarray:
    """Convert a predicted risk level into returns via ``-(risk_t - risk_{t-1})``.

    A rise in liquidity risk is treated as a negative return. Fewer than two
    observations produce an empty return series.
    """
    risk = _as_1d(risk_signal)
    if risk.size < 2:
        return np.array([], dtype=float)
    return -np.diff(risk)


def equity_curve_from_returns(returns: ArrayLike, initial: float = 1.0) -> np.ndarray:
    """Compound a return series into a normalised equity curve.

    The returned array has ``len(returns) + 1`` points and starts at
    ``initial``.
    """
    series = _as_1d(returns)
    start = float(initial)
    if series.size == 0:
        return np.array([start], dtype=float)
    compounded = start * np.cumprod(1.0 + series)
    return np.concatenate(([start], compounded))


# ---------------------------------------------------------------------------
# Quantitative metrics
# ---------------------------------------------------------------------------
def sharpe_ratio(returns: ArrayLike, risk_free: float = 0.0, periods_per_year: int = 252) -> float:
    """Annualised Sharpe ratio of a per-period return series.

    ``risk_free`` is an *annual* rate and is de-annualised before subtracting.
    """
    series = _as_1d(returns)
    if series.size < 2:
        return float("nan")
    periods = _validate_periods(periods_per_year)
    excess = series - float(risk_free) / periods
    std = float(np.std(excess, ddof=1))
    if not math.isfinite(std) or std == 0.0:
        return 0.0
    return float(np.mean(excess) / std * math.sqrt(periods))


def sortino_ratio(returns: ArrayLike, risk_free: float = 0.0, periods_per_year: int = 252) -> float:
    """Annualised Sortino ratio (downside-deviation adjusted)."""
    series = _as_1d(returns)
    if series.size < 2:
        return float("nan")
    periods = _validate_periods(periods_per_year)
    excess = series - float(risk_free) / periods
    downside = np.minimum(excess, 0.0)
    downside_deviation = float(np.sqrt(np.mean(downside**2)))
    if not math.isfinite(downside_deviation) or downside_deviation == 0.0:
        return 0.0
    return float(np.mean(excess) / downside_deviation * math.sqrt(periods))


def max_drawdown(equity_curve: ArrayLike) -> float:
    """Maximum peak-to-trough drawdown as a positive magnitude (e.g. 0.25 = 25%)."""
    equity = _as_1d(equity_curve)
    if equity.size < 2:
        return 0.0
    peak = np.maximum.accumulate(equity)
    with np.errstate(divide="ignore", invalid="ignore"):
        drawdown = np.where(peak > 0.0, (peak - equity) / peak, 0.0)
    return float(np.max(drawdown))


def annualized_volatility(returns: ArrayLike, periods_per_year: int = 252) -> float:
    """Annualised sample standard deviation of a per-period return series."""
    series = _as_1d(returns)
    if series.size < 2:
        return float("nan")
    periods = _validate_periods(periods_per_year)
    std = float(np.std(series, ddof=1))
    if not math.isfinite(std) or std == 0.0:
        return 0.0
    return float(std * math.sqrt(periods))


def calmar_ratio(
    returns: ArrayLike,
    equity_curve: Optional[ArrayLike] = None,
    risk_free: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """Annualised arithmetic return divided by maximum drawdown magnitude.

    Returns ``0.0`` when there is no drawdown (rather than ``inf``).
    """
    series = _as_1d(returns)
    if series.size == 0:
        return float("nan")
    periods = _validate_periods(periods_per_year)
    curve = equity_curve if equity_curve is not None else equity_curve_from_returns(series)
    drawdown = max_drawdown(curve)
    if not math.isfinite(drawdown) or drawdown == 0.0:
        return 0.0
    annualized_return = (float(np.mean(series)) - float(risk_free) / periods) * periods
    return float(annualized_return / drawdown)


def hit_rate(actual: ArrayLike, predicted: ArrayLike) -> float:
    """Fraction of periods where actual and predicted *changes* share a sign.

    A constant (all-zero-change) series carries no directional signal, so
    ``nan`` is returned instead of a meaningless perfect score.
    """
    actual_series = _as_1d(actual)
    predicted_series = _as_1d(predicted)
    n = min(actual_series.size, predicted_series.size)
    if n < 2:
        return float("nan")
    actual_direction = np.sign(np.diff(actual_series[:n]))
    predicted_direction = np.sign(np.diff(predicted_series[:n]))
    if not np.any(actual_direction) or not np.any(predicted_direction):
        return float("nan")
    return float(np.mean(actual_direction == predicted_direction))


def directional_accuracy(actual: ArrayLike, predicted: ArrayLike) -> float:
    """Alias of :func:`hit_rate` kept for the existing ML-metric vocabulary."""
    return hit_rate(actual, predicted)


def mean_squared_error(actual: ArrayLike, predicted: ArrayLike) -> float:
    """Mean squared error over the common prefix of the two series."""
    actual_series = _as_1d(actual)
    predicted_series = _as_1d(predicted)
    n = min(actual_series.size, predicted_series.size)
    if n == 0:
        return float("nan")
    return float(np.mean((actual_series[:n] - predicted_series[:n]) ** 2))


def mae(actual: ArrayLike, predicted: ArrayLike) -> float:
    """Mean absolute error over the common prefix of the two series."""
    actual_series = _as_1d(actual)
    predicted_series = _as_1d(predicted)
    n = min(actual_series.size, predicted_series.size)
    if n == 0:
        return float("nan")
    return float(np.mean(np.abs(actual_series[:n] - predicted_series[:n])))


def rmse(actual: ArrayLike, predicted: ArrayLike) -> float:
    """Root mean squared error over the common prefix of the two series."""
    error = mean_squared_error(actual, predicted)
    if math.isnan(error):
        return float("nan")
    return float(math.sqrt(error))


def r2_score_(actual: ArrayLike, predicted: ArrayLike) -> float:
    """Coefficient of determination (numpy implementation; no sklearn).

    A constant target has undefined explained variance, so ``0.0`` is returned.
    """
    actual_series = _as_1d(actual)
    predicted_series = _as_1d(predicted)
    n = min(actual_series.size, predicted_series.size)
    if n == 0:
        return float("nan")
    residual = float(np.sum((actual_series[:n] - predicted_series[:n]) ** 2))
    total = float(np.sum((actual_series[:n] - np.mean(actual_series[:n])) ** 2))
    if total == 0.0:
        return 0.0
    return float(1.0 - residual / total)


def value_at_risk(returns: ArrayLike, level: float = 0.95) -> float:
    """Historical Value-at-Risk at ``level``, reported as a loss magnitude.

    ``-quantile(returns, 1 - level)``; may be negative when the tail is
    profitable.
    """
    series = _as_1d(returns)
    if series.size == 0:
        return float("nan")
    level = _validate_level(level)
    return float(-np.quantile(series, 1.0 - level))


def conditional_value_at_risk(returns: ArrayLike, level: float = 0.95) -> float:
    """Historical CVaR (expected shortfall) at ``level``, as a loss magnitude."""
    series = _as_1d(returns)
    if series.size == 0:
        return float("nan")
    level = _validate_level(level)
    threshold = np.quantile(series, 1.0 - level)
    tail = series[series <= threshold]
    if tail.size == 0:
        return float(-threshold)
    return float(-np.mean(tail))


# ---------------------------------------------------------------------------
# Aggregate metric bundle
# ---------------------------------------------------------------------------
def compute_metrics(
    actual: Optional[ArrayLike] = None,
    predicted: Optional[ArrayLike] = None,
    returns: Optional[ArrayLike] = None,
    risk_free: float = 0.0,
    periods_per_year: int = 252,
    var_level: float = 0.95,
) -> Dict[str, float]:
    """Compute the full ML + quantitative metric bundle.

    Either ``predicted`` (a risk signal, from which returns are derived via the
    module convention) or an explicit ``returns`` series is required. ``actual``
    is optional; without it the supervised ML metrics are ``nan`` but the
    return-based metrics are still reported.
    """
    if predicted is None and returns is None:
        raise ValueError("Either 'predicted' or 'returns' must be provided")
    if actual is not None and predicted is None:
        raise ValueError("'predicted' is required when 'actual' is provided")

    if returns is None:
        returns = risk_signal_to_returns(predicted)
    return_series = _as_1d(returns)
    equity = equity_curve_from_returns(return_series)

    if actual is not None:
        actual_series = _as_1d(actual)
        if actual_series.size == 0:
            ml_metrics = {
                "mse": float("nan"),
                "mae": float("nan"),
                "rmse": float("nan"),
                "r2": float("nan"),
                "directional_accuracy": float("nan"),
                "hit_rate": float("nan"),
            }
        else:
            ml_metrics = {
                "mse": mean_squared_error(actual_series, predicted),
                "mae": mae(actual_series, predicted),
                "rmse": rmse(actual_series, predicted),
                "r2": r2_score_(actual_series, predicted),
                "directional_accuracy": directional_accuracy(actual_series, predicted),
                "hit_rate": hit_rate(actual_series, predicted),
            }
    else:
        ml_metrics = {
            "mse": float("nan"),
            "mae": float("nan"),
            "rmse": float("nan"),
            "r2": float("nan"),
            "directional_accuracy": float("nan"),
            "hit_rate": float("nan"),
        }

    return {
        **ml_metrics,
        "sharpe_ratio": sharpe_ratio(return_series, risk_free=risk_free, periods_per_year=periods_per_year),
        "sortino_ratio": sortino_ratio(return_series, risk_free=risk_free, periods_per_year=periods_per_year),
        "max_drawdown": max_drawdown(equity),
        "calmar_ratio": calmar_ratio(
            return_series, equity_curve=equity, risk_free=risk_free, periods_per_year=periods_per_year
        ),
        "annualized_volatility": annualized_volatility(return_series, periods_per_year=periods_per_year),
        "var_95": value_at_risk(return_series, level=var_level),
        "cvar_95": conditional_value_at_risk(return_series, level=var_level),
    }


# ---------------------------------------------------------------------------
# Configuration and folds
# ---------------------------------------------------------------------------
@dataclass
class WalkForwardConfig:
    """Configuration for walk-forward fold generation.

    ``test_size`` may be an absolute number of samples (``int``) or a fraction
    of the full series (``float`` in ``(0, 1)``) applied to *each* test fold.
    ``gap`` is the embargo: the number of samples dropped immediately before
    the test block so that ``max(train) + gap < min(test)``.
    """

    n_splits: int = 5
    test_size: Union[int, float] = 0.1
    expanding: bool = True
    gap: int = 0
    min_train_size: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_splits": int(self.n_splits),
            "test_size": self.test_size if isinstance(self.test_size, int) else float(self.test_size),
            "expanding": bool(self.expanding),
            "gap": int(self.gap),
            "min_train_size": int(self.min_train_size),
        }


def _validate_n_samples(n_samples: Any) -> int:
    if isinstance(n_samples, bool) or not isinstance(n_samples, (int, np.integer)):
        raise ValueError(f"n_samples must be an integer, got {n_samples!r}")
    if n_samples < 0:
        raise ValueError(f"n_samples must be non-negative, got {n_samples!r}")
    return int(n_samples)


def _resolve_test_size(test_size: Any, n_samples: int) -> int:
    if isinstance(test_size, bool):
        raise ValueError("test_size must be an int or a float fraction, got a bool")
    if isinstance(test_size, (int, np.integer)):
        if test_size < 1:
            raise ValueError(f"integer test_size must be >= 1, got {test_size!r}")
        return int(test_size)
    if isinstance(test_size, (float, np.floating)):
        if not 0.0 < float(test_size) < 1.0:
            raise ValueError(f"float test_size must be in (0, 1), got {test_size!r}")
        resolved = int(math.floor(n_samples * float(test_size)))
        if resolved < 1:
            raise ValueError(
                f"test_size fraction {test_size!r} yields 0 test samples for n_samples={n_samples}; "
                "use a larger fraction or an absolute integer test_size"
            )
        return resolved
    raise ValueError(f"test_size must be an int or a float fraction, got {type(test_size).__name__}")


def generate_walk_forward_folds(
    n_samples: int,
    config: Optional[WalkForwardConfig] = None,
) -> List[IndexPair]:
    """Build leakage-free walk-forward ``(train_idx, test_idx)`` folds.

    Test blocks are laid out consecutively at the end of the series. For every
    fold ``train_end = test_start - gap``, so the test block is always strictly
    after the training block plus the embargo. Expanding windows start at index
    0; rolling windows keep the first fold's training length fixed.
    """
    if config is None:
        config = WalkForwardConfig()
    if not isinstance(config, WalkForwardConfig):
        raise TypeError(f"config must be a WalkForwardConfig, got {type(config).__name__}")

    n = _validate_n_samples(n_samples)

    n_splits = config.n_splits
    if isinstance(n_splits, bool) or not isinstance(n_splits, (int, np.integer)) or n_splits < 1:
        raise ValueError(f"n_splits must be an integer >= 1, got {n_splits!r}")

    gap = config.gap
    if isinstance(gap, bool) or not isinstance(gap, (int, np.integer)) or gap < 0:
        raise ValueError(f"gap must be an integer >= 0, got {gap!r}")

    min_train_size = config.min_train_size
    if isinstance(min_train_size, bool) or not isinstance(min_train_size, (int, np.integer)) or min_train_size < 1:
        raise ValueError(f"min_train_size must be an integer >= 1, got {min_train_size!r}")

    test_len = _resolve_test_size(config.test_size, n)
    total_test = int(n_splits) * test_len
    if total_test > n:
        raise ValueError(
            f"n_splits ({n_splits}) * test_size ({test_len}) = {total_test} exceeds n_samples ({n})"
        )

    first_test_start = n - total_test
    initial_train_size = first_test_start - int(gap)
    if initial_train_size < int(min_train_size):
        raise ValueError(
            f"Not enough training samples for the requested folds: the first fold would have "
            f"{initial_train_size} train samples, below min_train_size={min_train_size} "
            f"(n_samples={n}, n_splits={n_splits}, test_size={test_len}, gap={gap}). "
            "Reduce n_splits/test_size/gap or provide more samples."
        )

    folds: List[IndexPair] = []
    for fold_index in range(int(n_splits)):
        test_start = first_test_start + fold_index * test_len
        test_end = test_start + test_len
        train_end = test_start - int(gap)
        train_start = 0 if config.expanding else train_end - initial_train_size
        if train_start < 0:
            raise ValueError(
                f"Rolling window underflow at fold {fold_index}: train_start={train_start}. "
                "This indicates an invalid configuration."
            )
        folds.append(
            (
                np.arange(train_start, train_end, dtype=int),
                np.arange(test_start, test_end, dtype=int),
            )
        )
    return folds


# ---------------------------------------------------------------------------
# Result objects
# ---------------------------------------------------------------------------
@dataclass
class FoldResult:
    """Metrics and index bookkeeping for a single walk-forward fold."""

    fold: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    metrics: Dict[str, float] = field(default_factory=dict)

    @property
    def n_train(self) -> int:
        return self.train_end - self.train_start

    @property
    def n_test(self) -> int:
        return self.test_end - self.test_start

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fold": int(self.fold),
            "train_start": int(self.train_start),
            "train_end": int(self.train_end),
            "test_start": int(self.test_start),
            "test_end": int(self.test_end),
            "n_train": self.n_train,
            "n_test": self.n_test,
            "metrics": {key: _json_safe(value) for key, value in self.metrics.items()},
        }


@dataclass
class BacktestMetrics:
    """Quantitative and ML metrics computed over one out-of-sample series."""

    mse: float = float("nan")
    mae: float = float("nan")
    rmse: float = float("nan")
    r2: float = float("nan")
    directional_accuracy: float = float("nan")
    hit_rate: float = float("nan")
    sharpe_ratio: float = float("nan")
    sortino_ratio: float = float("nan")
    max_drawdown: float = 0.0
    calmar_ratio: float = float("nan")
    annualized_volatility: float = float("nan")
    var_95: float = float("nan")
    cvar_95: float = float("nan")

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "BacktestMetrics":
        return cls(**{key: float(values[key]) for key in _METRIC_KEYS if key in values})

    def to_dict(self) -> Dict[str, Any]:
        return {key: _json_safe(getattr(self, key)) for key in _METRIC_KEYS}


@dataclass
class BacktestResult:
    """Full walk-forward backtest output.

    ``predictions``/``actuals`` are the concatenated out-of-sample series,
    ``returns`` is the sign-flipped risk-change series derived from
    ``predictions``, and ``equity_curve`` is its compounded curve.
    """

    config: WalkForwardConfig
    folds: List[FoldResult]
    predictions: np.ndarray
    actuals: np.ndarray
    returns: np.ndarray
    equity_curve: np.ndarray
    metrics: BacktestMetrics

    @property
    def n_oos(self) -> int:
        return int(np.asarray(self.predictions).size)

    def to_dict(self) -> Dict[str, Any]:
        fold_dicts = [fold.to_dict() for fold in self.folds]
        config_dict = self.config.to_dict()
        return {
            "config": config_dict,
            "n_oos": self.n_oos,
            "metrics": self.metrics.to_dict(),
            "folds": fold_dicts,
            "walk_forward": {"config": config_dict, "folds": fold_dicts},
            "predictions": [_json_safe(value) for value in np.asarray(self.predictions).ravel()],
            "actuals": [_json_safe(value) for value in np.asarray(self.actuals).ravel()],
            "returns": [_json_safe(value) for value in np.asarray(self.returns).ravel()],
            "equity_curve": [_json_safe(value) for value in np.asarray(self.equity_curve).ravel()],
        }


# ---------------------------------------------------------------------------
# Backtester
# ---------------------------------------------------------------------------
class WalkForwardBacktester:
    """Run a duck-typed model through leakage-free walk-forward folds.

    ``model_factory`` is a zero-argument callable returning a *fresh* object
    exposing ``.fit(X, y)`` and ``.predict(X)``. A new model is constructed for
    every fold, so no state can leak from one fold into the next.
    """

    def __init__(
        self,
        model_factory: Callable[[], Any],
        config: Optional[WalkForwardConfig] = None,
        periods_per_year: int = 252,
        risk_free: float = 0.0,
    ) -> None:
        if not callable(model_factory):
            raise TypeError("model_factory must be a zero-argument callable")
        if config is not None and not isinstance(config, WalkForwardConfig):
            raise TypeError(f"config must be a WalkForwardConfig, got {type(config).__name__}")
        self.model_factory = model_factory
        self.config = config if config is not None else WalkForwardConfig()
        self.periods_per_year = int(_validate_periods(periods_per_year))
        self.risk_free = float(risk_free)

    def run(self, X: ArrayLike, y: ArrayLike) -> BacktestResult:
        features = _as_2d(X)
        target = _as_1d(y)
        if features.shape[0] != target.size:
            raise ValueError(
                f"X and y have mismatched lengths: X has {features.shape[0]} rows, y has {target.size}"
            )

        folds = generate_walk_forward_folds(target.size, self.config)

        predictions: List[np.ndarray] = []
        actuals: List[np.ndarray] = []
        fold_results: List[FoldResult] = []

        for fold_index, (train_idx, test_idx) in enumerate(folds):
            model = self.model_factory()
            if not hasattr(model, "fit") or not hasattr(model, "predict"):
                raise TypeError(
                    "model_factory must return an object exposing .fit(X, y) and .predict(X); "
                    f"got {type(model).__name__}"
                )
            model.fit(features[train_idx], target[train_idx])
            fold_predictions = np.asarray(model.predict(features[test_idx]), dtype=float).ravel()
            if fold_predictions.size != test_idx.size:
                raise ValueError(
                    f"Fold {fold_index}: model returned {fold_predictions.size} predictions "
                    f"for {test_idx.size} test samples"
                )

            predictions.append(fold_predictions)
            actuals.append(target[test_idx])
            fold_results.append(
                FoldResult(
                    fold=fold_index,
                    train_start=int(train_idx[0]),
                    train_end=int(train_idx[-1]) + 1,
                    test_start=int(test_idx[0]),
                    test_end=int(test_idx[-1]) + 1,
                    metrics=compute_metrics(
                        actual=target[test_idx],
                        predicted=fold_predictions,
                        risk_free=self.risk_free,
                        periods_per_year=self.periods_per_year,
                    ),
                )
            )

        oos_predictions = (
            np.concatenate(predictions) if predictions else np.array([], dtype=float)
        )
        oos_actuals = np.concatenate(actuals) if actuals else np.array([], dtype=float)
        returns = risk_signal_to_returns(oos_predictions)
        equity_curve = equity_curve_from_returns(returns)
        metrics = compute_metrics(
            actual=oos_actuals,
            predicted=oos_predictions,
            risk_free=self.risk_free,
            periods_per_year=self.periods_per_year,
        )

        return BacktestResult(
            config=self.config,
            folds=fold_results,
            predictions=oos_predictions,
            actuals=oos_actuals,
            returns=returns,
            equity_curve=equity_curve,
            metrics=BacktestMetrics.from_dict(metrics),
        )
