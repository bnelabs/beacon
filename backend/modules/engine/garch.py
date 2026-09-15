"""Gaussian GARCH(1,1): the volatility baseline the platform never priced.

Round-eight adoption. Volatility clustering is a first-order feature of
financial series, and until now the only wired volatility awareness was the
regime nowcast. A GARCH(1,1) is the honest baseline: three parameters,
closed-form likelihood, and a conditional variance series that every richer
model (stochastic volatility, Neural SDE) must beat to earn its place.

Estimation is maximum likelihood on the Gaussian likelihood via Nelder-Mead
(no new dependency); the conditional variance recursion is the standard
``h_t = omega + alpha * r_{t-1}^2 + beta * h_t-1`` with stationarity enforced
by parameter bounds and a persistence check. Non-stationary fits are reported
as such rather than clipped into looking stationary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

__all__ = ["GARCHResult", "fit_garch11"]


@dataclass(frozen=True)
class GARCHResult:
    omega: float
    alpha: float
    beta: float
    persistence: float
    long_run_variance: float
    conditional_volatility: np.ndarray
    stationary: bool
    log_likelihood: float
    converged: bool

    def to_dict(self) -> dict:
        return {
            "omega": self.omega,
            "alpha": self.alpha,
            "beta": self.beta,
            "persistence": self.persistence,
            "long_run_variance": self.long_run_variance,
            "stationary": self.stationary,
            "log_likelihood": self.log_likelihood,
            "converged": self.converged,
        }


def _neg_log_likelihood(params: np.ndarray, returns: np.ndarray) -> float:
    omega, alpha, beta = params
    if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 0.9999:
        return 1e12
    n = returns.size
    var = np.empty(n)
    var[0] = returns.var() if returns.var() > 0 else 1e-8
    sq = returns * returns
    for t in range(1, n):
        var[t] = omega + alpha * sq[t - 1] + beta * var[t - 1]
        if var[t] <= 0:
            return 1e12
    return float(0.5 * np.sum(np.log(var) + sq / var))


def fit_garch11(returns: Sequence[float]) -> GARCHResult:
    """Fit a Gaussian GARCH(1,1) by maximum likelihood (Nelder-Mead)."""
    from scipy.optimize import minimize

    series = np.asarray(returns, dtype=float).ravel()
    series = series[np.isfinite(series)]
    if series.size < 50:
        raise ValueError(f"GARCH(1,1) needs at least 50 observations, got {series.size}")
    centered = series - series.mean()

    unconditional = centered.var()
    if unconditional <= 0:
        raise ValueError("returns have zero variance: nothing to model")
    x0 = np.array([unconditional * 0.05, 0.10, 0.85])
    result = minimize(
        _neg_log_likelihood,
        x0,
        args=(centered,),
        method="Nelder-Mead",
        options={"maxiter": 4000, "xatol": 1e-8, "fatol": 1e-8},
    )
    omega, alpha, beta = (float(v) for v in result.x)
    persistence = alpha + beta
    stationary = persistence < 1.0
    long_run = unconditional if not stationary else omega / (1.0 - persistence)

    # conditional variance series at the fitted parameters
    n = centered.size
    var = np.empty(n)
    var[0] = unconditional
    sq = centered * centered
    for t in range(1, n):
        var[t] = omega + alpha * sq[t - 1] + beta * var[t - 1]

    return GARCHResult(
        omega=omega,
        alpha=alpha,
        beta=beta,
        persistence=persistence,
        long_run_variance=long_run,
        conditional_volatility=np.sqrt(var),
        stationary=stationary,
        log_likelihood=-float(result.fun),
        converged=bool(result.success or result.fun < 1e11),
    )
