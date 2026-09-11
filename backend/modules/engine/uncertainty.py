"""Aleatoric and epistemic uncertainty, decomposed with deep ensembles.

Why the distinction matters operationally
----------------------------------------

Before this module the engine reported a single interval width, which conflates
two failures that call for opposite responses:

* **Aleatoric** uncertainty is irreducible noise in the world. The funding market
  was genuinely volatile on that day. Nothing about the model is wrong, more data
  would not help, and the honest response is to widen the interval and say so.
* **Epistemic** uncertainty is model ignorance. The model is being asked about a
  region of input space it has not learned -- a regime it never saw, a topology
  that did not exist during training. More data *would* help, and the correct
  response is to refuse the prediction rather than attach a number to it.

A single width cannot tell these apart. A wide interval caused by genuine market
turbulence is a usable warning; the same width caused by the model being lost is
not. The plan's requirement -- "if epistemic uncertainty spikes, the system
automatically flags the prediction as unreliable" -- is exactly this distinction,
and it is only computable once the two are separated.

The decomposition
-----------------

For an ensemble of ``M`` members, each supplying a predictive mean ``mu_m`` and a
variance ``sigma_m^2``, the law of total variance gives::

    Var(Y) = E[ Var(Y | member) ] + Var( E[Y | member] )
           = aleatoric            + epistemic

so::

    aleatoric = (1/M) * sum_m sigma_m^2          average within-member noise
    epistemic = variance of {mu_m}               disagreement between members

This is exact for the mixture the ensemble defines, and it is what the tests
check: a synthetic ensemble with a known noise level and a known spread of member
means must recover both.

Degrees of freedom, stated because it changes the answer
-------------------------------------------------------

The ensemble members are ``M`` draws from a posterior over models, so the spread
of their means estimates the posterior variance. With ``ddof=0`` the epistemic
term is the *population* variance of the finite ensemble -- the exact mixture
identity above -- but it underestimates the posterior variance by a factor
``(M-1)/M``, which is 20% at the ``M=5`` an ensemble typically uses. With
``ddof=1`` it is unbiased for the posterior variance, at the cost of no longer
satisfying the mixture identity exactly.

The default is ``ddof=1``: an unbiased estimate of model ignorance is what the
reliability flag depends on, and a systematic 20% understatement of ignorance is
the wrong direction to be wrong in. ``ddof=0`` is available and tested, and the
choice is recorded in the returned object rather than left implicit.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

logger = logging.getLogger(__name__)

__all__ = [
    "UncertaintyDecomposition",
    "UncertaintyAssessment",
    "decompose_variance",
    "DeepEnsemble",
    "EpistemicReference",
    "assess_uncertainty",
]

METHOD_ENSEMBLE = "deep_ensemble_law_of_total_variance"
METHOD_RESIDUAL = "ensemble_with_calibrated_residual_variance"


@dataclass(frozen=True)
class UncertaintyDecomposition:
    """A prediction with its uncertainty split into its two sources."""

    mean: float
    aleatoric: float
    epistemic: float
    n_members: int
    method: str
    ddof: int

    @property
    def total(self) -> float:
        """Total predictive variance. The two sources add."""
        return float(self.aleatoric + self.epistemic)

    @property
    def aleatoric_std(self) -> float:
        return float(math.sqrt(max(self.aleatoric, 0.0)))

    @property
    def epistemic_std(self) -> float:
        return float(math.sqrt(max(self.epistemic, 0.0)))

    @property
    def total_std(self) -> float:
        return float(math.sqrt(max(self.total, 0.0)))

    @property
    def aleatoric_share(self) -> float:
        """Fraction of total variance that is irreducible noise."""
        total = self.total
        return float(self.aleatoric / total) if total > 0 else 0.0

    @property
    def epistemic_share(self) -> float:
        """Fraction of total variance that is model ignorance.

        A high share is the dangerous case: the model is not merely facing a
        noisy world, it is being asked something it does not know, and the
        uncertainty will not shrink with a longer observation window.
        """
        total = self.total
        return float(self.epistemic / total) if total > 0 else 0.0

    @property
    def is_degenerate(self) -> bool:
        """Whether total variance is zero, so no interval is warranted at all."""
        return self.total <= 0.0

    def to_dict(self) -> Dict[str, object]:
        return {
            "mean": float(self.mean),
            "aleatoric": float(self.aleatoric),
            "epistemic": float(self.epistemic),
            "total": self.total,
            "aleatoric_std": self.aleatoric_std,
            "epistemic_std": self.epistemic_std,
            "total_std": self.total_std,
            "aleatoric_share": self.aleatoric_share,
            "epistemic_share": self.epistemic_share,
            "n_members": int(self.n_members),
            "method": self.method,
            "ddof": int(self.ddof),
        }


def decompose_variance(
    member_means: Sequence[float],
    member_variances: Optional[Sequence[float]] = None,
    *,
    ddof: int = 1,
) -> tuple[float, float]:
    """Split predictive variance into ``(aleatoric, epistemic)``.

    Args:
        member_means: One predictive mean per ensemble member.
        member_variances: One predictive variance per member. When omitted the
            aleatoric term is 0.0, which is the honest answer: with no
            within-member noise estimate there is nothing to attribute to the
            world, and assuming a value would fabricate a decomposition.
        ddof: Delta degrees of freedom for the epistemic term. ``1`` (default)
            gives an unbiased estimate of the posterior variance; ``0`` gives the
            exact variance of the finite ensemble as a mixture.

    Returns:
        ``(aleatoric, epistemic)`` as variances.

    Raises:
        ValueError: On empty input, length mismatch, negative variances, or
            non-finite values.
    """
    means = np.asarray(member_means, dtype=float).reshape(-1)
    if means.size == 0:
        raise ValueError("member_means is empty; there is nothing to decompose")
    if not np.all(np.isfinite(means)):
        raise ValueError("member_means contains non-finite values")
    if ddof not in (0, 1):
        raise ValueError(f"ddof must be 0 or 1, got {ddof}")
    if ddof >= means.size:
        raise ValueError(
            f"ddof={ddof} is degenerate for {means.size} member(s); "
            "an unbiased spread needs at least two members"
        )

    if member_variances is None:
        aleatoric = 0.0
    else:
        variances = np.asarray(member_variances, dtype=float).reshape(-1)
        if variances.size != means.size:
            raise ValueError(
                f"member_variances has {variances.size} entries but member_means "
                f"has {means.size}"
            )
        if not np.all(np.isfinite(variances)):
            raise ValueError("member_variances contains non-finite values")
        if np.any(variances < 0):
            raise ValueError("member_variances contains a negative variance")
        aleatoric = float(np.mean(variances))

    epistemic = float(np.var(means, ddof=ddof))
    return aleatoric, epistemic


class DeepEnsemble:
    """An ensemble of independently trained models, decomposed per prediction.

    Members are supplied as objects with a ``predict(X) -> array`` method, which
    is the interface the existing baseline harness already uses. They must be
    independently trained: members sharing initialisation or training data order
    disagree less than the truth warrants, and the epistemic term would then
    understate ignorance. That assumption is the caller's to keep and is recorded
    in the returned method string rather than silently assumed.

    Args:
        members: Fitted predictors. At least one; two or more for an epistemic
            term that is not identically zero by construction.
        member_variance_fn: Optional callable ``(member, X) -> array`` giving a
            per-point predictive variance for that member. When absent, call
            :meth:`calibrate_residual_variance` to supply the aleatoric term from
            held-out residuals instead.
        ddof: Degrees of freedom for the epistemic term. See the module docstring.
    """

    def __init__(
        self,
        members: Sequence[Any],
        member_variance_fn: Optional[Callable[[Any, Any], np.ndarray]] = None,
        *,
        ddof: int = 1,
    ) -> None:
        if not members:
            raise ValueError("a deep ensemble needs at least one member")
        if ddof not in (0, 1):
            raise ValueError(f"ddof must be 0 or 1, got {ddof}")
        if ddof == 1 and len(members) < 2:
            raise ValueError(
                "an unbiased epistemic spread (ddof=1) needs at least two members"
            )
        for index, member in enumerate(members):
            if not hasattr(member, "predict"):
                raise TypeError(
                    f"member {index} has no predict() method, so it cannot be an "
                    "ensemble member"
                )

        self.members = list(members)
        self.member_variance_fn = member_variance_fn
        self.ddof = int(ddof)
        self._residual_variance: Optional[float] = None
        self.n_calibration_points = 0

    @property
    def n_members(self) -> int:
        return len(self.members)

    def _member_means(self, X: Any) -> np.ndarray:
        predictions = [
            np.asarray(member.predict(X), dtype=float).reshape(-1)
            for member in self.members
        ]
        sizes = {row.size for row in predictions}
        if len(sizes) != 1:
            raise ValueError(
                f"ensemble members returned inconsistent numbers of predictions: "
                f"{sorted(sizes)}"
            )
        return np.vstack(predictions)

    def calibrate_residual_variance(self, X: Any, y: Sequence[float]) -> float:
        """Estimate the aleatoric variance from ensemble residuals on held-out data.

        Used when members do not emit their own variance. The residual is measured
        against the *ensemble mean*, so it captures the noise the ensemble as a
        whole fails to explain -- which is the aleatoric part -- while the spread
        of member means captures the epistemic part. The data must be held out
        from member training; residuals on training data are optimistic and would
        understate the noise term.
        """
        truth = np.asarray(y, dtype=float).reshape(-1)
        mean = self.predict_mean(X)
        if truth.size != mean.size:
            raise ValueError(
                f"y has {truth.size} entries but the ensemble produced {mean.size}"
            )
        if truth.size == 0:
            raise ValueError("calibration data is empty")
        if not np.all(np.isfinite(truth)):
            raise ValueError("calibration targets contain non-finite values")

        residual = truth - mean
        variance = float(np.mean(residual ** 2))
        self._residual_variance = variance
        self.n_calibration_points = int(truth.size)
        return variance

    def predict_mean(self, X: Any) -> np.ndarray:
        """Ensemble mean prediction, per input row."""
        return self._member_means(X).mean(axis=0)

    def decompose(self, X: Any) -> List[UncertaintyDecomposition]:
        """Per-input decomposition into aleatoric and epistemic variance."""
        stacked = self._member_means(X)
        n_points = int(stacked.shape[1])

        if self.member_variance_fn is not None:
            member_variances = np.vstack(
                [
                    np.asarray(self.member_variance_fn(member, X), dtype=float).reshape(-1)
                    for member in self.members
                ]
            )
            variance_source = METHOD_ENSEMBLE
        elif self._residual_variance is not None:
            member_variances = np.full_like(stacked, self._residual_variance)
            variance_source = METHOD_RESIDUAL
        else:
            member_variances = None
            variance_source = METHOD_ENSEMBLE

        results: List[UncertaintyDecomposition] = []
        for index in range(n_points):
            means = stacked[:, index]
            variances = None if member_variances is None else member_variances[:, index]
            aleatoric, epistemic = decompose_variance(
                means, variances, ddof=self.ddof
            )
            results.append(
                UncertaintyDecomposition(
                    mean=float(np.mean(means)),
                    aleatoric=aleatoric,
                    epistemic=epistemic,
                    n_members=self.n_members,
                    method=variance_source,
                    ddof=self.ddof,
                )
            )
        return results

    def decompose_one(self, x: Any) -> UncertaintyDecomposition:
        """Decomposition for a single input row."""
        results = self.decompose(x)
        if len(results) != 1:
            raise ValueError(
                f"decompose_one received data producing {len(results)} predictions; "
                "supply exactly one row"
            )
        return results[0]


class EpistemicReference:
    """Calibrated ceiling on epistemic uncertainty.

    Built from the epistemic values the ensemble produced on validation data the
    members did not train on. "Spiked" then means "more model ignorance than this
    ensemble ever showed on data it was validated against", rather than an
    absolute number somebody picked -- the same derived-threshold discipline used
    for interval width and topology drift.
    """

    def __init__(self, epistemic_values: Sequence[float], level: float = 0.99) -> None:
        array = np.asarray(epistemic_values, dtype=float).reshape(-1)
        if array.size == 0:
            raise ValueError("epistemic reference needs at least one observed value")
        if not np.all(np.isfinite(array)):
            raise ValueError("epistemic reference contains non-finite values")
        if np.any(array < 0):
            raise ValueError("epistemic reference contains a negative variance")
        if not 0.0 < level < 1.0:
            raise ValueError(f"level must be in (0, 1), got {level}")

        self.values = array
        self.level = float(level)
        self.minimum_reference_size = 2

    @property
    def threshold(self) -> float:
        return float(np.quantile(self.values, self.level, method="higher"))

    @property
    def is_calibratable(self) -> bool:
        """Whether the reference is large enough for the quantile to mean anything.

        A single observation makes every quantile equal that observation, so any
        new value above it -- or below it -- is compared against one draw. The
        test still runs, but the caller should know the threshold is a single
        sample rather than a distribution.
        """
        return self.values.size >= self.minimum_reference_size

    def assess(self, epistemic: float) -> Dict[str, object]:
        if not np.isfinite(epistemic) or epistemic < 0:
            raise ValueError(
                f"epistemic variance must be finite and non-negative, got {epistemic}"
            )
        threshold = self.threshold
        spiked = bool(epistemic > threshold)
        return {
            "epistemic": float(epistemic),
            "threshold": threshold,
            "level": self.level,
            "n_reference": int(self.values.size),
            "calibratable": self.is_calibratable,
            "spiked": spiked,
            "ratio": (
                float(epistemic / threshold)
                if threshold > 0
                else (float("inf") if epistemic > 0 else 0.0)
            ),
        }


@dataclass
class UncertaintyAssessment:
    """Reliability verdict attached to a prediction."""

    reliable: bool
    decomposition: UncertaintyDecomposition
    epistemic_check: Dict[str, object] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    max_epistemic_share: Optional[float] = None

    @property
    def epistemic_spiked(self) -> bool:
        return bool(self.epistemic_check.get("spiked", False))

    def to_dict(self) -> Dict[str, object]:
        return {
            "reliable": bool(self.reliable),
            "decomposition": self.decomposition.to_dict(),
            "epistemic_check": dict(self.epistemic_check),
            "epistemic_spiked": self.epistemic_spiked,
            "reasons": list(self.reasons),
            "max_epistemic_share": self.max_epistemic_share,
        }

    def summary(self) -> str:
        if self.reliable:
            return (
                f"Prediction is reliable (epistemic share "
                f"{self.decomposition.epistemic_share:.1%}, "
                f"total std {self.decomposition.total_std:.6g})"
            )
        return "Prediction flagged unreliable: " + "; ".join(self.reasons)


def assess_uncertainty(
    decomposition: UncertaintyDecomposition,
    epistemic_reference: Optional[EpistemicReference] = None,
    *,
    require_epistemic_reference: bool = False,
    max_epistemic_share: Optional[float] = None,
) -> UncertaintyAssessment:
    """Decide whether a prediction should be trusted, given its uncertainty.

    Three conditions flag a prediction as unreliable, and they are deliberately
    different questions:

    * **Epistemic spike.** The ensemble disagrees more than it ever did on
      validation data, so the model is extrapolating. This is the plan's stated
      trigger.
    * **Model ignorance dominates.** Configured via ``max_epistemic_share``. A
      wide interval is acceptable when the world is noisy and much less so when
      the width is mostly the model not knowing.
    * **Unmeasurable.** With ``require_epistemic_reference``, failing to supply a
      reference is itself a failure rather than a silent pass. A gate that
      cannot measure what it is supposed to measure should not certify.

    Args:
        decomposition: The prediction and its variance split.
        epistemic_reference: Calibrated ceiling, or ``None`` to skip that test.
        require_epistemic_reference: Promote a missing reference to a failure.
        max_epistemic_share: Optional ceiling on the epistemic share of variance,
            in ``[0, 1]``.

    Returns:
        :class:`UncertaintyAssessment` with ``reliable`` and the reasons.
    """
    reasons: List[str] = []
    epistemic_check: Dict[str, object] = {}

    if max_epistemic_share is not None and not 0.0 <= max_epistemic_share <= 1.0:
        raise ValueError(
            f"max_epistemic_share must be in [0, 1], got {max_epistemic_share}"
        )

    if not np.isfinite(decomposition.total) or not np.isfinite(decomposition.epistemic):
        reasons.append(
            "uncertainty could not be measured: the decomposition contains a "
            "non-finite variance"
        )
    elif decomposition.is_degenerate:
        # Zero variance from a real ensemble is not a confident prediction, it is
        # a sign the members are not independent.
        reasons.append(
            "total predictive variance is exactly zero, which an independently "
            "trained ensemble should not produce; the members are probably not "
            "independent or the calibration is broken"
        )

    if epistemic_reference is None:
        if require_epistemic_reference:
            reasons.append(
                "no calibrated epistemic reference was supplied, so model ignorance "
                "could not be tested"
            )
    else:
        epistemic_check = epistemic_reference.assess(decomposition.epistemic)
        if epistemic_check["spiked"]:
            reasons.append(
                f"epistemic uncertainty {decomposition.epistemic:.6g} exceeds the "
                f"calibrated ceiling {epistemic_check['threshold']:.6g} "
                f"(level {epistemic_check['level']}); the model is extrapolating"
            )
        if not epistemic_reference.is_calibratable:
            logger.warning(
                "Epistemic reference has %d value(s); the threshold is a single "
                "sample rather than a distribution",
                epistemic_reference.values.size,
            )

    if max_epistemic_share is not None:
        share = decomposition.epistemic_share
        if share > max_epistemic_share:
            reasons.append(
                f"epistemic share {share:.1%} exceeds the permitted "
                f"{max_epistemic_share:.1%}; the uncertainty is mostly model "
                "ignorance rather than market noise"
            )

    return UncertaintyAssessment(
        reliable=not reasons,
        decomposition=decomposition,
        epistemic_check=epistemic_check,
        reasons=reasons,
        max_epistemic_share=max_epistemic_share,
    )
