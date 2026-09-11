"""Split conformal prediction: distribution-free intervals with a coverage guarantee.

Why Gaussian intervals are wrong here
-------------------------------------

The deleted implementation reported "confidence bounds" from MC-dropout: it called
``model.train()`` on a model that had been loaded for inference, drew 30 samples,
and took the 5th and 95th percentiles. So the interval described a *different*
network from the one that produced the prediction -- dropout was active during the
interval but not during scoring -- and it carried no coverage guarantee even for
the network it did describe. Reporting a 90% interval that contains the truth 70%
of the time is worse than reporting nothing, because it invites a false confidence.

Conformal prediction replaces that with a guarantee that holds under one assumption
(exchangeability) and makes no distributional assumption at all:

    P(Y in C_hat(X)) >= 1 - alpha

for finite samples, for *any* model, however badly misspecified. The price is that
the guarantee is *marginal*: it holds on average over the population, not
conditionally on every X. That is a real limitation and is stated here rather than
glossed.

The construction (split conformal)
----------------------------------

Hold out a calibration set the model has not seen. Define a nonconformity score that
measures how badly the model did on each calibration point -- for regression,
``|y - y_hat|``. For a new input, the interval is the prediction widened by the
appropriate empirical quantile of those scores::

    q = the ceil((n + 1)(1 - alpha))-th smallest calibration score
    C_hat(x) = [y_hat - q, y_hat + q]

The ``(n + 1)`` is what makes the guarantee finite-sample rather than asymptotic.
When ``ceil((n + 1)(1 - alpha)) > n`` the calibration set is too small to support
the requested level at all, and the honest answer is an infinite interval -- not a
narrower one. That case is returned explicitly.

Why this matters for fat tails
------------------------------

Financial residuals are fat-tailed and heteroskedastic. A Gaussian interval is
built from a standard deviation that the tail observations inflate, so it is too
wide in calm periods and too narrow in stressed ones -- exactly backwards. Conformal
makes no shape assumption, so the calibrated width follows the empirical
distribution instead of a fitted one.

Normalized scores recover *some* adaptivity: dividing the residual by a scale
estimate gives intervals that widen when the model itself expects more noise.
Adaptive Conformal Inference goes further and tunes the level online, which is what
keeps coverage when the data stop being exchangeable.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np

logger = logging.getLogger(__name__)

__all__ = [
    "conformal_quantile",
    "ConformalInterval",
    "SplitConformalCalibrator",
    "NormalizedConformalCalibrator",
    "AdaptiveConformalInference",
]


def conformal_quantile(scores: Sequence[float], alpha: float) -> float:
    """The finite-sample conformal quantile of the calibration scores.

    Returns the ``ceil((n + 1)(1 - alpha))``-th smallest score. The ``(n + 1)``
    correction is what delivers the finite-sample guarantee; using the plain
    empirical quantile at ``1 - alpha`` gives a systematically optimistic interval.

    Args:
        scores: Nonconformity scores from the calibration set.
        alpha: Miscoverage level in ``(0, 1)``. A 90% interval has ``alpha=0.1``.

    Returns:
        The quantile, or ``inf`` when ``n`` is too small to support the level. An
        infinite width is the honest answer: with too few calibration points, no
        finite interval can carry the requested guarantee, and returning a finite
        one would overstate what is known.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")

    array = np.asarray(scores, dtype=float).reshape(-1)
    if array.size == 0:
        raise ValueError("calibration scores are empty")
    if not np.all(np.isfinite(array)):
        raise ValueError("calibration scores contain non-finite values")

    n = int(array.size)
    rank = math.ceil((n + 1) * (1.0 - alpha))
    if rank > n:
        return float("inf")
    return float(np.sort(array)[rank - 1])


@dataclass(frozen=True)
class ConformalInterval:
    """A prediction interval, with the provenance needed to interpret it."""

    lower: float
    upper: float
    alpha: float
    margin: float
    method: str
    n_calibration: int

    @property
    def width(self) -> float:
        return float(self.upper - self.lower)

    @property
    def is_finite(self) -> bool:
        return math.isfinite(self.lower) and math.isfinite(self.upper)

    def contains(self, value: float) -> bool:
        return bool(self.lower <= value <= self.upper)

    def to_dict(self) -> Dict[str, object]:
        return {
            "lower": float(self.lower),
            "upper": float(self.upper),
            "width": self.width,
            "alpha": float(self.alpha),
            "coverage_target": float(1.0 - self.alpha),
            "margin": float(self.margin),
            "method": self.method,
            "n_calibration": int(self.n_calibration),
            "is_finite": self.is_finite,
        }


class SplitConformalCalibrator:
    """Absolute-residual split conformal for a regression-style model.

    The model must already be trained; calibration uses data it has not seen, and
    that separation is what makes the guarantee hold. Reusing training data would
    make the residuals optimistic and the intervals too narrow.
    """

    def __init__(self, alpha: float = 0.1) -> None:
        if not 0.0 < alpha < 1.0:
            raise ValueError(f"alpha must be in (0, 1), got {alpha}")
        self.alpha = float(alpha)
        self.scores: Optional[np.ndarray] = None

    def fit(self, y_true: Sequence[float], y_pred: Sequence[float]) -> "SplitConformalCalibrator":
        """Calibrate on held-out residuals ``|y_true - y_pred|``."""
        truth = np.asarray(y_true, dtype=float).reshape(-1)
        pred = np.asarray(y_pred, dtype=float).reshape(-1)
        if truth.size != pred.size:
            raise ValueError(
                f"y_true has {truth.size} entries but y_pred has {pred.size}"
            )
        if truth.size == 0:
            raise ValueError("calibration data is empty")
        if not (np.all(np.isfinite(truth)) and np.all(np.isfinite(pred))):
            raise ValueError("calibration data contains non-finite values")

        self.scores = np.abs(truth - pred)
        return self

    def _require_fitted(self) -> np.ndarray:
        if self.scores is None:
            raise RuntimeError("calibrator has not been fitted; call fit() first")
        return self.scores

    @property
    def n_calibration(self) -> int:
        return 0 if self.scores is None else int(self.scores.size)

    @property
    def margin(self) -> float:
        return conformal_quantile(self._require_fitted(), self.alpha)

    def interval(self, prediction: float, alpha: Optional[float] = None) -> ConformalInterval:
        """Interval for a single prediction at the calibrated level."""
        level = self.alpha if alpha is None else float(alpha)
        margin = conformal_quantile(self._require_fitted(), level)
        return ConformalInterval(
            lower=float(prediction) - margin,
            upper=float(prediction) + margin,
            alpha=level,
            margin=margin,
            method="split_conformal_absolute",
            n_calibration=self.n_calibration,
        )

    def intervals(
        self, predictions: Sequence[float], alpha: Optional[float] = None
    ) -> List[ConformalInterval]:
        return [self.interval(value, alpha) for value in predictions]

    def empirical_coverage(
        self, y_true: Sequence[float], y_pred: Sequence[float], alpha: Optional[float] = None
    ) -> float:
        """Fraction of held-out points the interval covers.

        For a fresh exchangeable sample this should be at least ``1 - alpha``, up
        to sampling noise. Calling it on the calibration data itself will report
        inflated coverage and is a misuse, so the caller supplies separate data.
        """
        level = self.alpha if alpha is None else float(alpha)
        margin = conformal_quantile(self._require_fitted(), level)
        truth = np.asarray(y_true, dtype=float).reshape(-1)
        pred = np.asarray(y_pred, dtype=float).reshape(-1)
        if truth.size != pred.size or truth.size == 0:
            raise ValueError("y_true and y_pred must be non-empty and equal length")
        return float(np.mean(np.abs(truth - pred) <= margin))


class NormalizedConformalCalibrator:
    """Locally adaptive conformal, using a per-point scale estimate.

    Nonconformity is ``|y - y_hat| / sigma(x)``. Interval width then scales with
    ``sigma(x)``, so the interval widens where the model expects more noise instead
    of being a single global width. ``sigma`` must be strictly positive and must be
    computable without seeing the label -- it is a scale estimate, not a residual.
    """

    def __init__(self, alpha: float = 0.1, epsilon: float = 1e-9) -> None:
        if not 0.0 < alpha < 1.0:
            raise ValueError(f"alpha must be in (0, 1), got {alpha}")
        if epsilon <= 0:
            raise ValueError(f"epsilon must be positive, got {epsilon}")
        self.alpha = float(alpha)
        self.epsilon = float(epsilon)
        self.scores: Optional[np.ndarray] = None

    def fit(
        self,
        y_true: Sequence[float],
        y_pred: Sequence[float],
        sigma: Sequence[float],
    ) -> "NormalizedConformalCalibrator":
        truth = np.asarray(y_true, dtype=float).reshape(-1)
        pred = np.asarray(y_pred, dtype=float).reshape(-1)
        scale = np.asarray(sigma, dtype=float).reshape(-1)
        if not (truth.size == pred.size == scale.size):
            raise ValueError(
                "y_true, y_pred and sigma must have equal length, got "
                f"{truth.size}, {pred.size}, {scale.size}"
            )
        if truth.size == 0:
            raise ValueError("calibration data is empty")
        if np.any(scale <= 0) or not np.all(np.isfinite(scale)):
            raise ValueError("sigma must be finite and strictly positive")

        self.scores = np.abs(truth - pred) / np.maximum(scale, self.epsilon)
        return self

    def _require_fitted(self) -> np.ndarray:
        if self.scores is None:
            raise RuntimeError("calibrator has not been fitted; call fit() first")
        return self.scores

    @property
    def n_calibration(self) -> int:
        return 0 if self.scores is None else int(self.scores.size)

    def interval(
        self, prediction: float, sigma: float, alpha: Optional[float] = None
    ) -> ConformalInterval:
        if not math.isfinite(sigma) or sigma <= 0:
            raise ValueError(f"sigma must be finite and strictly positive, got {sigma}")
        level = self.alpha if alpha is None else float(alpha)
        quantile = conformal_quantile(self._require_fitted(), level)
        margin = quantile * float(sigma)
        return ConformalInterval(
            lower=float(prediction) - margin,
            upper=float(prediction) + margin,
            alpha=level,
            margin=margin,
            method="split_conformal_normalized",
            n_calibration=self.n_calibration,
        )

    def empirical_coverage(
        self,
        y_true: Sequence[float],
        y_pred: Sequence[float],
        sigma: Sequence[float],
        alpha: Optional[float] = None,
    ) -> float:
        level = self.alpha if alpha is None else float(alpha)
        quantile = conformal_quantile(self._require_fitted(), level)
        truth = np.asarray(y_true, dtype=float).reshape(-1)
        pred = np.asarray(y_pred, dtype=float).reshape(-1)
        scale = np.asarray(sigma, dtype=float).reshape(-1)
        if not (truth.size == pred.size == scale.size) or truth.size == 0:
            raise ValueError("y_true, y_pred and sigma must be non-empty and equal length")
        return float(np.mean(np.abs(truth - pred) / np.maximum(scale, self.epsilon) <= quantile))


class AdaptiveConformalInference:
    """Online conformal that tunes its level to hold coverage under drift.

    Split conformal assumes exchangeability. Financial data violate it: a
    calibration set drawn from a calm period gives intervals that under-cover in a
    stressed one. Gibbs and Candes (2021) fix this by treating the miscoverage
    level as a control variable and updating it from realised errors::

        alpha_{t+1} = alpha_t + gamma * (alpha - err_t)

    where ``err_t`` is 1 when the point was *not* covered. If the interval is
    missing too often, ``alpha_t`` rises, the interval widens, and coverage is
    pushed back towards target. The learning rate ``gamma`` trades responsiveness
    against variance in the level.

    This does not restore a finite-sample guarantee -- nothing can, without
    exchangeability -- but it makes the realised coverage track the target
    asymptotically under drift, which is the property the tests check.
    """

    def __init__(
        self,
        alpha: float = 0.1,
        gamma: float = 0.01,
        buffer_size: int = 500,
        min_alpha: float = 1e-3,
        max_alpha: float = 0.999,
    ) -> None:
        if not 0.0 < alpha < 1.0:
            raise ValueError(f"alpha must be in (0, 1), got {alpha}")
        if gamma <= 0:
            raise ValueError(f"gamma must be positive, got {gamma}")
        if buffer_size < 1:
            raise ValueError(f"buffer_size must be positive, got {buffer_size}")
        if not 0.0 < min_alpha < max_alpha < 1.0:
            raise ValueError(
                f"need 0 < min_alpha < max_alpha < 1, got {min_alpha}, {max_alpha}"
            )

        self.target_alpha = float(alpha)
        self.alpha = float(alpha)
        self.gamma = float(gamma)
        self.buffer_size = int(buffer_size)
        self.min_alpha = float(min_alpha)
        self.max_alpha = float(max_alpha)

        self._scores: List[float] = []
        self.n_updates = 0
        self.n_covered = 0

    def update(self, score: float, covered: bool) -> float:
        """Record one realised nonconformity and advance the level.

        Args:
            score: The realised nonconformity, e.g. ``|y - y_hat| / sigma``.
            covered: Whether the interval emitted for this point contained the
                observation. The caller knows this; it cannot be inferred from the
                score alone because the level may have changed since.

        Returns:
            The updated miscoverage level.
        """
        if not math.isfinite(score) or score < 0:
            raise ValueError(f"score must be finite and non-negative, got {score}")

        self._scores.append(float(score))
        if len(self._scores) > self.buffer_size:
            self._scores.pop(0)

        self.n_updates += 1
        if covered:
            self.n_covered += 1

        error = 0.0 if covered else 1.0
        updated = self.alpha + self.gamma * (self.target_alpha - error)
        self.alpha = float(min(max(updated, self.min_alpha), self.max_alpha))
        return self.alpha

    @property
    def realised_coverage(self) -> float:
        """Fraction of updates that were covered. ``nan`` before any update."""
        if self.n_updates == 0:
            return float("nan")
        return float(self.n_covered / self.n_updates)

    @property
    def n_scores(self) -> int:
        return len(self._scores)

    def margin(self, alpha: Optional[float] = None) -> float:
        """Current margin at the live level (or an override)."""
        if not self._scores:
            raise RuntimeError("no scores recorded yet; call update() first")
        level = self.alpha if alpha is None else float(alpha)
        return conformal_quantile(self._scores, level)

    def interval(self, prediction: float, sigma: float = 1.0) -> ConformalInterval:
        margin = self.margin() * float(sigma)
        return ConformalInterval(
            lower=float(prediction) - margin,
            upper=float(prediction) + margin,
            alpha=self.alpha,
            margin=margin,
            method="adaptive_conformal_inference",
            n_calibration=self.n_scores,
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "target_alpha": self.target_alpha,
            "current_alpha": self.alpha,
            "gamma": self.gamma,
            "n_updates": self.n_updates,
            "realised_coverage": self.realised_coverage,
            "target_coverage": 1.0 - self.target_alpha,
            "n_scores": self.n_scores,
        }
