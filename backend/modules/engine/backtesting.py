"""Walk-forward backtesting and evaluation metrics for liquidity-risk models.

BEACON predicts a per-timestep *liquidity-risk level*, a bounded state rather
than a financial return. The two are not interchangeable, so return-based
portfolio statistics (Sharpe, Sortino, drawdown, Calmar, volatility, VaR/CVaR)
are not defined on a risk score and are deliberately not computed here. The
module reports only the supervised metrics that are meaningful for a state
series: MSE/MAE/RMSE/R^2 and the directional hit rate.

Fold-boundary handling
======================
:class:`WalkForwardBacktester` evaluates the model on disjoint out-of-sample
test blocks. Naively concatenating those blocks and scoring the result creates
one synthetic change at every fold boundary -- a transition that never occurred
in the underlying series -- which biases the directional score.

The backtester therefore records the interior fold seams and asks the
directional score to pool within the same segments instead of across them:
:func:`hit_rate` takes a ``boundaries`` argument and measures agreement inside
each segment, weighting the pool by the number of comparisons. The result records
``boundaries`` and ``n_boundary_transitions_removed`` so the correction is
auditable.

Degenerate-input policy
=======================
Every metric tolerates empty, constant, and single-element input and never
raises ``ZeroDivisionError``. The deliberate return values are:

* Empty input -> ``float('nan')`` for the error metrics and R^2, because there
  is nothing to score; :func:`hit_rate` is also ``nan``.
* Constant series -> ``nan`` for :func:`hit_rate`, because a series with no
  non-zero changes carries no directional signal to score; R^2 against a
  constant target is ``0.0``.
* Single element -> ``0.0`` for ``mse``/``mae``/``rmse``/R^2 (there is no
  misprediction to measure) and ``nan`` for :func:`hit_rate` (there is no
  change to compare).
* A segment whose changes are all zero is skipped rather than counted as a run
  of mismatches.

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


def _validate_periods(periods_per_year: float) -> float:
    periods = float(periods_per_year)
    if not math.isfinite(periods) or periods <= 0.0:
        raise ValueError(f"periods_per_year must be a positive number, got {periods_per_year!r}")
    return periods


# ---------------------------------------------------------------------------
# Boundary / segment helpers
# ---------------------------------------------------------------------------
def _normalise_boundaries(boundaries: Optional[Sequence[int]], size: int) -> List[int]:
    """Validate interior segment starts; return them sorted and de-duplicated.

    ``boundaries`` lists the index at which each segment *after the first*
    begins, so ``[10, 20]`` describes the segments ``[0:10]``, ``[10:20]`` and
    ``[20:]``.
    """
    if boundaries is None:
        return []
    interior: List[int] = []
    for raw in boundaries:
        if isinstance(raw, bool) or not isinstance(raw, (int, np.integer)):
            raise ValueError(f"boundaries must contain integers, got {raw!r}")
        value = int(raw)
        if value <= 0:
            raise ValueError(f"boundaries must be positive interior offsets, got {value!r}")
        if value >= size:
            raise ValueError(f"boundary {value} is at or beyond the series length {size}")
        interior.append(value)
    return sorted(set(interior))


def segment_slices(boundaries: Optional[Sequence[int]], size: int) -> List[slice]:
    """Split ``range(size)`` into the contiguous segments named by ``boundaries``."""
    interior = _normalise_boundaries(boundaries, size)
    edges = [0, *interior, size]
    return [slice(edges[index], edges[index + 1]) for index in range(len(edges) - 1)]


def count_segment_transitions(boundaries: Optional[Sequence[int]], size: int) -> int:
    """Number of across-segment transitions that ``boundaries`` suppresses."""
    return max(len(segment_slices(boundaries, size)) - 1, 0)


def boundaries_from_group_sizes(sizes: Sequence[int]) -> np.ndarray:
    """Interior offsets for a concatenation of blocks of the given sizes.

    The inverse of :func:`segment_slices`: given the length of every block that
    was concatenated, return the offsets at which each block after the first
    begins. Blocks of size zero contribute no rows and therefore no boundary.
    Fewer than two non-empty blocks means nothing was concatenated.
    """
    non_empty: List[int] = []
    for raw in sizes:
        if isinstance(raw, bool) or not isinstance(raw, (int, np.integer)):
            raise ValueError(f"group sizes must be integers, got {raw!r}")
        value = int(raw)
        if value < 0:
            raise ValueError(f"group sizes must be non-negative, got {value!r}")
        if value:
            non_empty.append(value)
    if len(non_empty) <= 1:
        return np.array([], dtype=int)
    return np.cumsum(non_empty)[:-1].astype(int)


# ---------------------------------------------------------------------------
# Evaluation metrics
# ---------------------------------------------------------------------------
def hit_rate(
    actual: ArrayLike,
    predicted: ArrayLike,
    boundaries: Optional[Sequence[int]] = None,
) -> float:
    """Fraction of periods where actual and predicted *changes* share a sign.

    A segment whose changes are all zero carries no directional signal and is
    left out of the pooled score; ``nan`` is returned when no segment carries
    signal.

    ``boundaries`` names interior segment starts (see
    :func:`_normalise_boundaries`): agreement is measured inside each segment and
    pooled with the number of comparisons as the weight, so a seam between two
    separately generated blocks is never scored. A boundary at or beyond the
    common prefix of the two series starts no non-empty segment and is ignored.
    """
    actual_series = _as_1d(actual)
    predicted_series = _as_1d(predicted)
    n = min(actual_series.size, predicted_series.size)
    if n < 2:
        return float("nan")

    interior: List[int] = []
    for raw in boundaries if boundaries is not None else ():
        if isinstance(raw, bool) or not isinstance(raw, (int, np.integer)):
            raise ValueError(f"boundaries must contain integers, got {raw!r}")
        value = int(raw)
        if 0 < value < n:
            interior.append(value)

    matches = 0
    comparisons = 0
    for segment in segment_slices(interior, n):
        actual_segment = actual_series[segment]
        predicted_segment = predicted_series[segment]
        if actual_segment.size < 2 or predicted_segment.size < 2:
            continue
        actual_direction = np.sign(np.diff(actual_segment))
        predicted_direction = np.sign(np.diff(predicted_segment))
        if not np.any(actual_direction) or not np.any(predicted_direction):
            continue
        matches += int(np.sum(actual_direction == predicted_direction))
        comparisons += int(actual_direction.size)

    if comparisons == 0:
        return float("nan")
    return float(matches / comparisons)


def directional_accuracy(
    actual: ArrayLike, predicted: ArrayLike, boundaries: Optional[Sequence[int]] = None
) -> float:
    """Alias of :func:`hit_rate` kept for the existing ML-metric vocabulary."""
    return hit_rate(actual, predicted, boundaries)


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


# ---------------------------------------------------------------------------
# Baseline models
# ---------------------------------------------------------------------------
# A custom attention/GNN model is only justified if it beats something simple.
# These baselines need nothing beyond numpy, so they run through the same
# walk-forward folds and under the same seam-free metric rules as the primary
# model, and the lift reported by :class:`BaselineComparison` is an apples-to-
# apples comparison rather than a claim.
class PersistenceBaseline:
    """Random-walk baseline: repeat the last value seen during training."""

    def __init__(self) -> None:
        self.last_value: float = 0.0
        self.fit_calls: int = 0

    def fit(self, X: ArrayLike, y: ArrayLike) -> "PersistenceBaseline":
        target = _as_1d(y)
        self.last_value = float(target[-1]) if target.size else 0.0
        self.fit_calls += 1
        return self

    def predict(self, X: ArrayLike) -> np.ndarray:
        rows = _as_2d(X).shape[0]
        return np.full(rows, self.last_value, dtype=float)


class LinearBaseline:
    """Least-squares baseline with an intercept, solved in closed form by numpy."""

    def __init__(self) -> None:
        self.coef_: Optional[np.ndarray] = None
        self.intercept_: float = 0.0

    def fit(self, X: ArrayLike, y: ArrayLike) -> "LinearBaseline":
        features = _as_2d(X)
        target = _as_1d(y)
        if features.shape[0] != target.size:
            raise ValueError(
                f"X and y have mismatched lengths: X has {features.shape[0]} rows, "
                f"y has {target.size}"
            )
        design = np.column_stack([features, np.ones(features.shape[0])])
        solution, *_ = np.linalg.lstsq(design, target, rcond=None)
        self.coef_ = np.asarray(solution[:-1], dtype=float)
        self.intercept_ = float(solution[-1])
        return self

    def predict(self, X: ArrayLike) -> np.ndarray:
        if self.coef_ is None:
            raise RuntimeError("LinearBaseline.predict called before fit")
        return _as_2d(X) @ self.coef_ + self.intercept_


class AR1Baseline:
    """AR(1) baseline -- the ARIMA(1, 0, 0) case -- fitted by OLS on lagged levels.

    Forecasts are produced recursively from the final training observation, which
    is the standard one-step-then-multi-step AR(1) path. ``X`` is accepted for
    duck-type compatibility with the harness and is otherwise unused.

    The fitted slope is clamped to ``[-1, 1]``. That is the stationary form of
    AR(1); without the clamp an explosive coefficient would produce a benchmark
    so bad that any model looks good against it, which is the opposite of what a
    baseline is for.
    """

    def __init__(self, min_points: int = 3) -> None:
        self.min_points = max(int(min_points), 2)
        self.slope: float = 0.0
        self.intercept: float = 0.0
        self.last_value: float = 0.0
        self.n_observations: int = 0

    def fit(self, X: ArrayLike, y: ArrayLike) -> "AR1Baseline":
        target = _as_1d(y)
        self.n_observations = int(target.size)
        if target.size == 0:
            self.slope, self.intercept, self.last_value = 0.0, 0.0, 0.0
            return self

        self.last_value = float(target[-1])
        if target.size < self.min_points:
            self.slope, self.intercept = 0.0, self.last_value
            return self

        lagged = target[:-1]
        current = target[1:]
        lag_mean = float(np.mean(lagged))
        current_mean = float(np.mean(current))
        variance = float(np.sum((lagged - lag_mean) ** 2))
        if not math.isfinite(variance) or variance == 0.0:
            self.slope = 0.0
        else:
            covariance = float(np.sum((lagged - lag_mean) * (current - current_mean)))
            self.slope = covariance / variance
        if not math.isfinite(self.slope):
            self.slope = 0.0
        self.slope = float(min(max(self.slope, -1.0), 1.0))
        self.intercept = current_mean - self.slope * lag_mean
        return self

    def predict(self, X: ArrayLike) -> np.ndarray:
        rows = _as_2d(X).shape[0]
        forecasts = np.empty(rows, dtype=float)
        previous = self.last_value
        for index in range(rows):
            previous = self.slope * previous + self.intercept
            forecasts[index] = previous
        return forecasts


_BASELINE_ALIASES: Dict[str, type] = {
    "persistence": PersistenceBaseline,
    "random_walk": PersistenceBaseline,
    "last_value": PersistenceBaseline,
    "ar1": AR1Baseline,
    "arima": AR1Baseline,
    "linear": LinearBaseline,
    "ols": LinearBaseline,
}

#: Canonical baseline names accepted by :func:`baseline_factory`.
BASELINE_NAMES: Tuple[str, ...] = ("persistence", "ar1", "linear")

#: Metrics where a smaller value is the better outcome.
LOWER_IS_BETTER: Tuple[str, ...] = (
    "mse",
    "mae",
    "rmse",
)


def baseline_factory(kind: str = "persistence") -> Callable[[], Any]:
    """Return a zero-argument factory for a named baseline model."""
    key = str(kind).strip().lower()
    try:
        model_class = _BASELINE_ALIASES[key]
    except KeyError:
        raise ValueError(
            f"Unknown baseline {kind!r}; available: {list(BASELINE_NAMES)} "
            f"(aliases: {sorted(_BASELINE_ALIASES)})"
        ) from None
    return model_class


# ---------------------------------------------------------------------------
# Aggregate metric bundle
# ---------------------------------------------------------------------------
def compute_metrics(
    actual: Optional[ArrayLike] = None,
    predicted: Optional[ArrayLike] = None,
    boundaries: Optional[Sequence[int]] = None,
) -> Dict[str, float]:
    """Compute the supervised metric bundle for a predicted risk series.

    ``predicted`` is required. ``actual`` is optional; without it every metric is
    ``nan`` because there is no target to score against.

    ``boundaries`` names interior segment starts in ``actual``/``predicted``
    (see :func:`_normalise_boundaries`). The directional score is then pooled
    within each segment rather than across the seams, which is what a caller that
    concatenates out-of-sample blocks wants. A boundary at or beyond the common
    prefix of the two series starts no non-empty segment and is ignored.
    """
    if predicted is None:
        raise ValueError("'predicted' must be provided")

    if actual is None:
        return {
            "mse": float("nan"),
            "mae": float("nan"),
            "rmse": float("nan"),
            "r2": float("nan"),
            "directional_accuracy": float("nan"),
            "hit_rate": float("nan"),
        }

    actual_series = _as_1d(actual)
    if actual_series.size == 0:
        return {
            "mse": float("nan"),
            "mae": float("nan"),
            "rmse": float("nan"),
            "r2": float("nan"),
            "directional_accuracy": float("nan"),
            "hit_rate": float("nan"),
        }

    return {
        "mse": mean_squared_error(actual_series, predicted),
        "mae": mae(actual_series, predicted),
        "rmse": rmse(actual_series, predicted),
        "r2": r2_score_(actual_series, predicted),
        "directional_accuracy": directional_accuracy(actual_series, predicted, boundaries),
        "hit_rate": hit_rate(actual_series, predicted, boundaries),
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


def walk_forward_folds_per_segment(
    boundaries: Optional[Sequence[int]],
    size: int,
    config: Optional[WalkForwardConfig] = None,
) -> Tuple[List[Tuple[int, slice, List[IndexPair]]], Dict[int, str]]:
    """Generate walk-forward folds *inside* each segment of a concatenated series.

    When a series is a concatenation of blocks -- separate data sources, say --
    folding across the whole thing would train on one block and test on another.
    Folds are therefore generated per segment and their indices shifted back into
    the concatenated frame.

    Returns ``(entries, failures)``. Each entry is
    ``(segment_index, segment_slice, folds)`` with **global** fold indices;
    ``failures`` maps a segment index to the reason no folds could be built for
    it (typically too few samples for the requested configuration).
    """
    entries: List[Tuple[int, slice, List[IndexPair]]] = []
    failures: Dict[int, str] = {}
    for segment_index, segment in enumerate(segment_slices(boundaries, size)):
        local_size = segment.stop - segment.start
        try:
            folds = generate_walk_forward_folds(local_size, config)
        except (TypeError, ValueError) as exc:
            failures[segment_index] = str(exc)
            continue
        entries.append(
            (
                segment_index,
                segment,
                [
                    (train_idx + segment.start, test_idx + segment.start)
                    for train_idx, test_idx in folds
                ],
            )
        )
    return entries, failures


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
    """Supervised metrics computed over one out-of-sample series."""

    mse: float = float("nan")
    mae: float = float("nan")
    rmse: float = float("nan")
    r2: float = float("nan")
    directional_accuracy: float = float("nan")
    hit_rate: float = float("nan")

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "BacktestMetrics":
        return cls(**{key: float(values[key]) for key in _METRIC_KEYS if key in values})

    def to_dict(self) -> Dict[str, Any]:
        return {key: _json_safe(getattr(self, key)) for key in _METRIC_KEYS}


@dataclass
class BacktestResult:
    """Full walk-forward backtest output.

    ``predictions``/``actuals`` are the concatenated out-of-sample series and
    ``boundaries`` records the interior fold seams in concatenated index space so
    the directional score can be pooled within each fold.

    There is no ``returns`` or ``equity_curve`` field. A risk score is a latent
    state, not a price: producing a "return" series required sign-flipping
    consecutive scores and differencing them, and those differences then had to
    be aggregated across fold seams where no economic transition occurs. The
    fields existed only to feed the Sharpe/Sortino/drawdown/VaR statistics that
    have themselves been removed.
    """

    config: WalkForwardConfig
    folds: List[FoldResult]
    predictions: np.ndarray
    actuals: np.ndarray
    metrics: BacktestMetrics
    boundaries: np.ndarray = field(default_factory=lambda: np.array([], dtype=int))

    @property
    def n_oos(self) -> int:
        return int(np.asarray(self.predictions).size)

    @property
    def n_boundary_transitions_removed(self) -> int:
        """Across-fold transitions that the seam-aware directional score suppressed."""
        boundary_count = int(np.asarray(self.boundaries).size)
        return boundary_count

    def to_dict(self) -> Dict[str, Any]:
        fold_dicts = [fold.to_dict() for fold in self.folds]
        config_dict = self.config.to_dict()
        return {
            "config": config_dict,
            "n_oos": self.n_oos,
            "metrics": self.metrics.to_dict(),
            "folds": fold_dicts,
            "walk_forward": {"config": config_dict, "folds": fold_dicts},
            "aggregation": {
                "strategy": "directional_score_pooled_within_segment",
                "boundaries": [int(value) for value in np.asarray(self.boundaries).ravel()],
                "n_boundary_transitions_removed": self.n_boundary_transitions_removed,
            },
            "predictions": [_json_safe(value) for value in np.asarray(self.predictions).ravel()],
            "actuals": [_json_safe(value) for value in np.asarray(self.actuals).ravel()],
        }


@dataclass
class BaselineComparison:
    """A primary model's walk-forward result next to named baselines, with lift.

    ``lift()[baseline][metric]`` is ``primary - baseline`` for metrics where a
    larger value is better and ``baseline - primary`` for the metrics in
    :data:`LOWER_IS_BETTER`. A positive number therefore always means "the
    primary model is better"; ``None`` means the metric was undefined (``nan``)
    on one side.
    """

    primary: BacktestResult
    baselines: Dict[str, BacktestResult]

    def lift(self) -> Dict[str, Dict[str, Optional[float]]]:
        primary_metrics = self.primary.metrics.to_dict()
        lift: Dict[str, Dict[str, Optional[float]]] = {}
        for name, result in self.baselines.items():
            baseline_metrics = result.metrics.to_dict()
            per_metric: Dict[str, Optional[float]] = {}
            for key, primary_value in primary_metrics.items():
                baseline_value = baseline_metrics.get(key)
                if primary_value is None or baseline_value is None:
                    per_metric[key] = None
                elif key in LOWER_IS_BETTER:
                    per_metric[key] = _json_safe(baseline_value - primary_value)
                else:
                    per_metric[key] = _json_safe(primary_value - baseline_value)
            lift[name] = per_metric
        return lift

    def to_dict(self) -> Dict[str, Any]:
        return {
            "primary": self.primary.to_dict(),
            "baselines": {name: result.to_dict() for name, result in self.baselines.items()},
            "lift": self.lift(),
            "lift_convention": "positive means the primary model is better",
            "lower_is_better": list(LOWER_IS_BETTER),
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
                    ),
                )
            )

        oos_predictions = (
            np.concatenate(predictions) if predictions else np.array([], dtype=float)
        )
        oos_actuals = np.concatenate(actuals) if actuals else np.array([], dtype=float)

        # Fold seams are not observations: the directional score is pooled
        # segment-by-segment so it never sees a transition that did not happen in
        # the underlying series.
        boundaries = boundaries_from_group_sizes([chunk.size for chunk in predictions])
        metrics = compute_metrics(
            actual=oos_actuals,
            predicted=oos_predictions,
            boundaries=boundaries,
        )

        return BacktestResult(
            config=self.config,
            folds=fold_results,
            predictions=oos_predictions,
            actuals=oos_actuals,
            metrics=BacktestMetrics.from_dict(metrics),
            boundaries=np.asarray(boundaries, dtype=int),
        )

    def compare(
        self,
        X: ArrayLike,
        y: ArrayLike,
        baselines: Sequence[str] = ("persistence", "ar1"),
    ) -> BaselineComparison:
        """Run the primary model and each named baseline through the same folds.

        The baselines see the identical fold boundaries and the identical
        seam-free metric rules, so the returned lift is a like-for-like
        comparison. Without it, model complexity is unjustified.
        """
        primary = self.run(X, y)
        named_results: Dict[str, BacktestResult] = {}
        for name in baselines:
            runner = WalkForwardBacktester(
                model_factory=baseline_factory(name),
                config=self.config,
                periods_per_year=self.periods_per_year,
                risk_free=self.risk_free,
            )
            named_results[str(name)] = runner.run(X, y)
        return BaselineComparison(primary=primary, baselines=named_results)
