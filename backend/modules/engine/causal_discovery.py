"""Causal structure discovery: the validation TNCM-VAE says it does not have.

Why this module exists
----------------------

:mod:`backend.modules.engine.tncm_vae` states its own central limitation in its
docstring: the causal structure is **declared, not learned**, and "nothing here
validates that the declared structure is the true one. The counterfactual is
exactly as good as the DAG and coefficients handed in." A declared DAG is a
modelling assumption, and an unexamined assumption is where model risk hides. A
missing parent leaves a confounding path open, so an intervention that severs the
declared parents still moves quantities through the undeclared one: the
counterfactual is quietly wrong and nothing in the counterfactual machinery
objects. This module is the missing check. It learns structure from observational
data by two independent routes and compares both against the declaration.

What is implemented
-------------------

**NOTEARS** (Zheng, Aragam, Ravikumar, Xing, "DAGs with NO TEARS", NeurIPS 2018).
The problem is written as a continuous program over a real weight matrix ``W``::

    minimise   (1 / 2n) * ||X - X * W||_F^2  +  lambda * ||W||_1
    subject to h(W) = tr(exp(W o W)) - d = 0

where ``o`` is the Hadamard (elementwise) product and ``exp`` the matrix
exponential. ``h(W) >= 0`` everywhere and ``h(W) = 0`` exactly when the directed
graph of ``W`` has no cycle (Zheng et al., Theorem 1), so a smooth equality
constraint replaces the combinatorial acyclicity requirement. The constraint
gradient ``dh(W) = exp(W o W)^T o 2W`` is implemented analytically -- the tests
check it against central finite differences, because a wrong gradient still
descends to *something* and only an independent derivative exposes it.

The constrained problem is solved by an augmented Lagrangian around an inner
L-BFGS-B solve, with dual ascent on the constraint and a penalty coefficient that
grows when the constraint fails to shrink:

1. ``rho = initial_rho`` (1.0), ``alpha = 0``, ``h_previous = inf``.
2. Inner solve: L-BFGS-B on
   ``loss + lambda*||W||_1 + alpha*h(W) + 0.5*rho*h(W)^2``, started from the
   current ``W`` (zeros on the first pass).
3. If the new ``h(W) > rho_decrease_ratio * h_previous`` (default 0.25) the inner
   problem was solved too loosely for the current penalty, so ``rho`` is
   multiplied by ``rho_growth`` (10) and step 2 repeats; otherwise the inner solve
   is accepted.
4. Dual ascent: ``alpha <- alpha + rho * h(W)``.
5. Stop when ``h(W) <= h_tolerance`` (1e-8) or ``rho >= rho_max``. Otherwise
   repeat from step 2 with the accepted ``W`` as the warm start.

This is the schedule of the reference implementation; the differences and the
bounds that keep the matrix exponential finite are documented on
:class:`NoteArsConfig`.

**A constraint-based skeleton.** Partial correlations with a Fisher-z test produce
an undirected skeleton (:func:`partial_correlation`,
:class:`PartialCorrelationSkeleton`). This is **not the PC algorithm** and is not
named after it: PC's edge-removal stage is reproduced, but of the orientation
rules only the collider (v-structure) rule is applied -- no Meek rules R1-R4 -- so
the output is a partially directed graph (a CPDAG *fragment*), not a DAG, and it
must not be read as one. It exists so that the NOTEARS result has a second,
independent route to compare against: two methods with different assumptions
agreeing on an edge is evidence; either alone is a hypothesis.

**DAG validity and the integration seam.** :func:`is_acyclic` (topological sort),
:func:`threshold_weights`, and honest conversions both ways between the
adjacency/``W`` representation here and the ``parents: Dict[str, Tuple[str, ...]]``
form of :class:`backend.modules.engine.tncm_vae.StructuralCausalModel`.

**The deliverable.** :func:`compare_dag` reports the edge-level discrepancies
between a learned DAG and a declared one, with the asymmetry stated rather than
smoothed over (see its docstring).

What is NOT implemented, and where this fails
---------------------------------------------

These are not disclaimers; they are the conditions under which the output is
wrong, and they are the reason discovery is a diagnostic rather than an authority.

* **Linearity.** NOTEARS assumes a *linear* structural equation model,
  ``X = X W + Z``. A real relationship that is monotone but nonlinear -- a cap, a
  threshold, a convexity, a ratio -- leaves little or no linear residual
  correlation, so the edge can be missing from the learned graph even though the
  dependence is real and strong. A missing edge is therefore *not* evidence of
  absence of causation.
* **Additive Gaussian noise of equal variance.** The equal-variance assumption is
  what makes the least-squares loss the right likelihood. Financial residuals are
  heteroskedastic (volatility clusters), so the loss is mis-specified and the
  edges it favours are the ones with the largest variance, not the strongest
  structure. This module does not weight, whiten, or model the noise. The
  assumption is also about the data *as fitted*: z-scoring each column rescales
  its residual, so it turns equal noise variances into unequal ones whenever the
  columns have different scales and can invert the orientation the data support.
  That is why :attr:`NoteArsConfig.standardize` defaults to ``False`` and only
  centres; it was observed, not assumed -- on this module's own simulated
  colliders, standardizing recovered the reversed graph.
* **Markov equivalence.** With observational data alone the likelihood cannot
  orient edges within a Markov equivalence class: ``A -> B`` and ``B -> A`` are
  equally consistent with the same distribution and the same variance, and a
  chain has no v-structure to break the tie, so a learned chain is as likely to
  come out reversed as forward. Reversing a *collider* is not in the same class
  and is a genuine error, which is the distinction the recovery tests exercise.
  ``tncm_vae.py`` says the same thing for the same reason. A "recovered"
  direction among two variables with no other structure carries no information.
* **No latent confounders.** This is not FCI and it is not a latent-variable
  method. A common cause that was never measured becomes a spurious edge between
  its observed children, and no output here says so. If confounding is plausible
  the learned graph must be read as a network of *associations*, not causes.
* **The L1 penalty is a tuning knob with no principled selector.** ``l1_strength``
  and ``threshold`` together decide sparsity and there is no cross-validation,
  stability selection, or BIC-based choice implemented here. Different values give
  different graphs. Reporting one graph without reporting the sensitivity to these
  two numbers overstates what was found. Because columns are not scaled by
  default, ``l1_strength`` is in the units of the data: a penalty that is right
  for a series measured in percent is wrong for the same series measured in
  basis points. The tests use many samples and strong coefficients, which is the
  regime where the penalty has a wide working range; a weak, small-sample fit will
  not behave like that.
* **Nonconvexity.** The augmented Lagrangian solves a nonconvex program to a local
  optimum. Independent restarts may disagree; a solution that satisfies ``h(W)=0``
  is acyclic but is not guaranteed to be the global optimum.
* **The constraint-based baseline is weaker than NOTEARS**, not a tie-breaker. The
  Fisher-z test assumes joint Gaussianity and its power falls as the conditioning
  set grows, and orientation is limited to v-structures. When the two routes
  disagree, the module reports the disagreement; it does not adjudicate it.
* **Nothing here establishes faithfulness.** A constraint-based method can delete
  a true edge when two paths cancel exactly, and NOTEARS can keep a spurious one.
  Neither route is ground truth, and neither is a licence to overwrite a declared
  DAG with a possibly-spurious learned one. The correct use of
  :func:`compare_dag` is to *look* at the discrepancy and argue about it.

All numeric paths fail closed: missing, non-finite, or rank-degenerate inputs
raise rather than being imputed, dropped, or defaulted.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace
from itertools import combinations
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from scipy.linalg import expm
from scipy.optimize import minimize

from backend.exceptions import DataQualityError

logger = logging.getLogger(__name__)

__all__ = [
    "NoteArsConfig",
    "NoteArsResult",
    "NoteArsDiscovery",
    "resolve_w_bound",
    "SkeletonResult",
    "PartialCorrelationSkeleton",
    "OrientationConflict",
    "DagComparison",
    "notears_linear",
    "least_squares_loss",
    "least_squares_gradient",
    "note_ars_objective",
    "acyclicity_constraint",
    "acyclicity_gradient",
    "is_acyclic",
    "topological_order",
    "threshold_weights",
    "adjacency_to_parents",
    "parents_to_adjacency",
    "weights_to_parents",
    "partial_correlation",
    "compare_dag",
]

#: Tolerance at which ``h(W)`` is treated as numerically zero. ``h`` is exact in
#: floating point up to the error of the matrix exponential (a few ulp), so 1e-10
#: is below what the constraint can meaningfully distinguish from zero.
H_ZERO_TOLERANCE = 1e-10


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _as_square(matrix: Any, name: str) -> np.ndarray:
    """Return a finite, non-empty square float matrix or raise ``ValueError``."""
    array = np.asarray(matrix, dtype=float)
    if array.ndim != 2 or array.shape[0] != array.shape[1]:
        raise ValueError(
            f"{name} must be a square 2-D array, got shape {tuple(array.shape)}"
        )
    if array.shape[0] == 0:
        raise ValueError(f"{name} is empty")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} contains non-finite (NaN or infinite) values")
    return array


def _without_diagonal(weights: np.ndarray) -> np.ndarray:
    """A copy of ``weights`` with the diagonal zeroed.

    A structural equation model has no self-edge, so the diagonal of ``W`` is not
    a free parameter. It is projected out in both the value and the gradient of
    every objective, which makes the search space the off-diagonal entries.
    """
    out = np.array(weights, dtype=float, copy=True)
    np.fill_diagonal(out, 0.0)
    return out


def _as_variables(variables: Sequence[str]) -> Tuple[str, ...]:
    names = tuple(variables)
    if not names:
        raise ValueError("at least one variable name is required")
    if any(not isinstance(name, str) or not name for name in names):
        raise ValueError(f"variable names must be non-empty strings, got {names!r}")
    if len(set(names)) != len(names):
        raise ValueError(f"variable names must be unique, got {names!r}")
    return names


def _as_data_matrix(X: Any) -> np.ndarray:
    """Return the data as a finite 2-D float matrix or raise ``ValueError``."""
    matrix = np.asarray(X, dtype=float)
    if matrix.ndim != 2:
        raise ValueError(
            f"data must be 2-D (samples, variables), got shape {tuple(matrix.shape)}"
        )
    if matrix.shape[1] == 0:
        raise ValueError("data has no columns")
    if not np.all(np.isfinite(matrix)):
        raise DataQualityError(
            "the data contain non-finite values (NaN or infinite); causal "
            "discovery will not impute, drop, or forward-fill them",
            context={"shape": list(matrix.shape)},
        )
    return matrix


def _validated_data(
    X: Any, variables: Sequence[str], *, name: str = "X"
) -> Tuple[np.ndarray, Tuple[str, ...]]:
    """Common data validation for both discovery routes.

    Raises:
        ValueError: for shape or naming mistakes that are programmer errors.
        DataQualityError: for data that exist but cannot support the method.
    """
    names = _as_variables(variables)
    matrix = _as_data_matrix(X)
    if matrix.shape[1] != len(names):
        raise ValueError(
            f"data has {matrix.shape[1]} columns but {len(names)} variable names "
            f"were given"
        )
    if len(names) < 2:
        raise ValueError(
            "causal discovery needs at least two variables; with one variable "
            "there is no edge to discover"
        )
    n_samples = matrix.shape[0]
    if n_samples == 0:
        raise DataQualityError("the data have no rows", context={"variables": list(names)})
    if n_samples <= len(names):
        raise DataQualityError(
            f"only {n_samples} samples for {len(names)} variables; the structural "
            "regression is under-determined and any graph it produced would be a "
            "property of the sample count, not of the data. This is the bare "
            "feasibility floor, not a statistical power guarantee",
            context={"n_samples": int(n_samples), "n_variables": len(names)},
        )
    return matrix, names


# ---------------------------------------------------------------------------
# Acyclicity: the constraint and its gradient
# ---------------------------------------------------------------------------


def acyclicity_constraint(weights: Any) -> float:
    """``h(W) = tr(exp(W o W)) - d``.

    Non-negative for every real ``W`` and zero exactly on the acyclic matrices
    (Zheng et al., Theorem 1). The matrix exponential is computed by
    scaling-and-squaring in :func:`scipy.linalg.expm`; the value is finite for any
    matrix whose entries are moderate (the module bounds ``W`` during the search
    for exactly that reason) and a non-finite result raises rather than being
    returned as a plausible-looking number.
    """
    matrix = _as_square(weights, "weights")
    value = float(np.trace(expm(matrix * matrix)) - matrix.shape[0])
    if not math.isfinite(value):
        raise ValueError(
            "the acyclicity constraint overflowed; the weight matrix has entries "
            "too large for the matrix exponential to be evaluated in float64"
        )
    return value


def acyclicity_gradient(weights: Any) -> np.ndarray:
    """Analytic gradient ``dh(W) = exp(W o W)^T o 2W``.

    Derivation: with ``M = W o W``, ``d tr(exp M) = tr(exp(M) dM)`` and
    ``dM_ij / dW_ij = 2 W_ij``, so ``dh/dW_ij = (exp(M)^T)_ij * 2 W_ij``. The
    tests check this against central finite differences on
    :func:`acyclicity_constraint`.
    """
    matrix = _as_square(weights, "weights")
    exponential = expm(matrix * matrix)
    gradient = exponential.T * (2.0 * matrix)
    if not np.all(np.isfinite(gradient)):
        raise ValueError(
            "the acyclicity gradient overflowed; the weight matrix has entries "
            "too large for the matrix exponential to be evaluated in float64"
        )
    return np.asarray(gradient, dtype=float)


def topological_order(weights: Any, threshold: float = 0.0) -> Optional[Tuple[int, ...]]:
    """A topological order of the nonzero pattern, or ``None`` if it is cyclic.

    Kahn's algorithm over the edges ``j -> i`` where ``|W[j, i]| > threshold``.
    A non-zero diagonal entry is a self-loop and therefore a cycle, so it returns
    ``None`` -- which is what keeps this consistent with
    :func:`acyclicity_constraint`, since ``h([[w]]) = e^{w^2} - 1 > 0`` for any
    ``w != 0``. Deterministic: ties are broken by index, so the same matrix always
    yields the same order.
    """
    matrix = _as_square(weights, "weights")
    if not math.isfinite(threshold) or threshold < 0.0:
        raise ValueError(f"threshold must be finite and non-negative, got {threshold}")
    d = matrix.shape[0]

    for node in range(d):
        if abs(matrix[node, node]) > threshold:
            return None  # a self-loop is a cycle of length one

    parent_count = [0] * d
    children: List[List[int]] = [[] for _ in range(d)]
    for child in range(d):
        for parent in range(d):
            if abs(matrix[parent, child]) > threshold:
                parent_count[child] += 1
                children[parent].append(child)

    ready = [node for node in range(d) if parent_count[node] == 0]
    order: List[int] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for child in children[node]:
            parent_count[child] -= 1
            if parent_count[child] == 0:
                ready.append(child)

    if len(order) != d:
        return None
    return tuple(order)


def is_acyclic(weights: Any, threshold: float = 0.0) -> bool:
    """Whether the nonzero pattern of ``W`` (above ``threshold``) is acyclic.

    Verified by topological sort rather than by ``h(W) == 0``: the two are
    equivalent for this constraint, and the tests assert that equivalence on random
    matrices, but the sort is exact and does not depend on the conditioning of the
    matrix exponential.
    """
    return topological_order(weights, threshold) is not None


def threshold_weights(weights: Any, threshold: float = 0.3) -> np.ndarray:
    """Turn a raw weight matrix into a 0/1 adjacency by dropping small entries.

    ``adjacency[j, i] = 1`` iff ``|W[j, i]| > threshold`` and ``j != i``. The
    threshold is a real modelling choice, not a formality: it decides which
    borderline edges exist, and no value is preferred by the optimisation. The
    magnitude is discarded (the raw weights remain available on
    :attr:`NoteArsResult.weights`) so that this output is exactly an adjacency and
    can round-trip through the :mod:`tncm_vae` parents representation.
    """
    matrix = _as_square(weights, "weights")
    if not math.isfinite(threshold) or threshold < 0.0:
        raise ValueError(f"threshold must be finite and non-negative, got {threshold}")
    adjacency = (np.abs(matrix) > threshold).astype(float)
    np.fill_diagonal(adjacency, 0.0)
    return adjacency


# ---------------------------------------------------------------------------
# The least-squares loss, exposed so it can be checked against a closed form
# ---------------------------------------------------------------------------


def _check_widths(weights: np.ndarray, matrix: np.ndarray) -> None:
    if matrix.shape[1] != weights.shape[0]:
        raise ValueError(
            f"data has {matrix.shape[1]} columns but the weight matrix is "
            f"{weights.shape[0]}x{weights.shape[1]}"
        )


def least_squares_loss(weights: Any, X: Any) -> float:
    """``(1 / 2n) * ||X - X W||_F^2`` with the diagonal of ``W`` ignored.

    Exposed because it has a hand-computable value (for one variable,
    ``0.5 * mean(x^2) * (1 - w)^2``) which the tests use instead of trusting the
    optimiser's own reporting.
    """
    matrix = _as_square(weights, "weights")
    data = _as_data_matrix(X)
    _check_widths(matrix, data)
    centered = _without_diagonal(matrix)
    residual = data - data @ centered
    return float(0.5 * np.sum(residual * residual) / data.shape[0])


def least_squares_gradient(weights: Any, X: Any) -> np.ndarray:
    """``d/dW`` of :func:`least_squares_loss`: ``-(1/n) X^T (X - X W)``."""
    matrix = _as_square(weights, "weights")
    data = _as_data_matrix(X)
    _check_widths(matrix, data)
    centered = _without_diagonal(matrix)
    residual = data - data @ centered
    gradient = -(data.T @ residual) / data.shape[0]
    np.fill_diagonal(gradient, 0.0)
    return np.asarray(gradient, dtype=float)


def note_ars_objective(weights: Any, X: Any, l1_strength: float = 0.1) -> float:
    """The NOTEARS objective ``loss + lambda * ||W||_1`` (constraint excluded)."""
    if not math.isfinite(l1_strength) or l1_strength < 0.0:
        raise ValueError(
            f"l1_strength must be finite and non-negative, got {l1_strength}"
        )
    matrix = _as_square(weights, "weights")
    centered = _without_diagonal(matrix)
    return float(
        least_squares_loss(centered, X) + l1_strength * np.sum(np.abs(centered))
    )


# ---------------------------------------------------------------------------
# NOTEARS
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NoteArsConfig:
    """Settings for the augmented-Lagrangian NOTEARS solver.

    The defaults follow the reference implementation except for ``w_bound``, which
    is derived because the matrix exponential must stay finite in float64 (see
    below), and ``l1_strength``, which is set to a value that works on the small
    standardized graphs the tests use. All of them change the graph that comes out;
    the sensitivity is real and is not quantified here.

    Attributes:
        l1_strength: ``lambda`` on ``||W||_1``. Larger means sparser. No
            cross-validation or stability selection is implemented, so this is a
            judgement call by the caller.
        threshold: Weight magnitude below which an edge is dropped when forming
            the adjacency. The raw weights are always kept.
        max_outer_iterations: Cap on augmented-Lagrangian (dual ascent) rounds.
        max_inner_iterations: Cap on L-BFGS-B iterations per outer round.
        h_tolerance: ``h(W)`` at or below this counts as acyclic; the loop stops.
        initial_rho: Starting penalty coefficient.
        rho_max: Largest penalty coefficient; the loop stops at this value even if
            ``h`` is still positive, and ``converged`` is then ``False``.
        rho_growth: Factor by which ``rho`` grows when the constraint has not
            shrunk enough.
        rho_decrease_ratio: The constraint is judged to have shrunk enough when
            ``h_new <= ratio * h_previous``.
        w_bound: Box bound on every entry of ``W``. This is a numerical guard: the
            augmented-Lagrangian term is ``rho * h(W)^2`` and
            ``h(W) <= d * exp(d * w_bound^2)``, so a bound that is too loose makes
            the term overflow to ``inf`` and destroys the solve. ``None`` (the
            default) derives the largest bound for which the term provably stays
            finite given ``d`` and ``rho_max``. It is also an implicit prior that
            no structural coefficient exceeds the bound; ``NoteArsResult.hit_bound``
            reports when the bound actually binds.
        standardize: Whether to divide each column by its standard deviation
            after centering. **Defaults to False, and the default matters.** The
            method's identifiability rests on the noise being *equally* variable
            across the structural equations, and the least-squares loss is only
            that likelihood up to a constant when it is. Dividing column ``i`` by
            ``sd_i`` scales its residual by the same factor, so z-scoring turns
            equal noise variances into unequal ones whenever the variables have
            different scales and can invert the orientation the data support. This
            was not a theoretical worry: on the module's own simulated DAGs,
            standardizing reversed the recovered collider. Center is always
            applied (the structural equations have no intercept); scaling is
            opt-in and the caller is asserting equal noise variance on the
            *standardized* scale by asking for it.
        n_restarts: Number of augmented-Lagrangian runs. The first starts from
            ``W = 0``; the rest from seeded random draws. With more than one run,
            ``seed`` is mandatory so the result is reproducible.
        seed: Seed for the restart draws. Required when ``n_restarts > 1``.
    """

    l1_strength: float = 0.1
    threshold: float = 0.3
    max_outer_iterations: int = 100
    max_inner_iterations: int = 200
    h_tolerance: float = 1e-8
    initial_rho: float = 1.0
    rho_max: float = 1e16
    rho_growth: float = 10.0
    rho_decrease_ratio: float = 0.25
    w_bound: Optional[float] = None
    standardize: bool = False
    n_restarts: int = 1
    seed: Optional[int] = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.l1_strength) or self.l1_strength < 0.0:
            raise ValueError(
                f"l1_strength must be finite and non-negative, got {self.l1_strength}"
            )
        if not math.isfinite(self.threshold) or self.threshold < 0.0:
            raise ValueError(
                f"threshold must be finite and non-negative, got {self.threshold}"
            )
        if self.max_outer_iterations < 1:
            raise ValueError(
                f"max_outer_iterations must be positive, got {self.max_outer_iterations}"
            )
        if self.max_inner_iterations < 1:
            raise ValueError(
                f"max_inner_iterations must be positive, got {self.max_inner_iterations}"
            )
        if not math.isfinite(self.h_tolerance) or self.h_tolerance <= 0.0:
            raise ValueError(
                f"h_tolerance must be finite and positive, got {self.h_tolerance}"
            )
        if not math.isfinite(self.initial_rho) or self.initial_rho <= 0.0:
            raise ValueError(
                f"initial_rho must be finite and positive, got {self.initial_rho}"
            )
        if not math.isfinite(self.rho_max) or self.rho_max < self.initial_rho:
            raise ValueError(
                f"rho_max must be finite and at least initial_rho, got {self.rho_max}"
            )
        if not math.isfinite(self.rho_growth) or self.rho_growth <= 1.0:
            raise ValueError(
                f"rho_growth must be finite and greater than 1, got {self.rho_growth}"
            )
        if not 0.0 < self.rho_decrease_ratio < 1.0:
            raise ValueError(
                "rho_decrease_ratio must lie strictly between 0 and 1, got "
                f"{self.rho_decrease_ratio}"
            )
        if self.w_bound is not None and (
            not math.isfinite(self.w_bound) or self.w_bound <= 0.0
        ):
            raise ValueError(
                f"w_bound must be None or finite and positive, got {self.w_bound}"
            )
        if self.n_restarts < 1:
            raise ValueError(f"n_restarts must be positive, got {self.n_restarts}")
        if self.n_restarts > 1 and self.seed is None:
            raise ValueError(
                f"n_restarts={self.n_restarts} makes the fit stochastic; an explicit "
                "seed is required so the result is reproducible"
            )


def resolve_w_bound(
    n_variables: int, w_bound: Optional[float] = None, rho_max: float = 1e16
) -> float:
    """The box bound on ``W``, defaulted so the penalty term cannot overflow.

    ``h(W) = tr(exp(W o W)) - d`` obeys ``h <= d * exp(||W o W||_1)`` and
    ``||W o W||_1 <= d * w_bound^2``, so the augmented-Lagrangian term
    ``rho_max * h^2`` is finite in float64 only while ``w_bound`` is below a
    dimension-dependent threshold. The derived bound keeps ``rho_max * h^2`` under
    ``1e300``. An explicit bound that violates this raises rather than being
    silently clipped, because clipping would quietly change the problem.
    """
    if n_variables < 1:
        raise ValueError(f"n_variables must be positive, got {n_variables}")
    if not math.isfinite(rho_max) or rho_max <= 0.0:
        raise ValueError(f"rho_max must be finite and positive, got {rho_max}")
    # hmax such that hmax^2 * rho_max <= 1e300.
    log_h_max = 0.5 * (math.log(1e300) - math.log(rho_max))
    log_ceiling = log_h_max - math.log(n_variables)
    derived = math.sqrt(max(0.0, log_ceiling) / n_variables)
    derived = float(min(10.0, derived))

    if w_bound is None:
        return derived
    if w_bound <= derived:
        return float(w_bound)
    raise ValueError(
        f"w_bound={w_bound} is too large for {n_variables} variables and "
        f"rho_max={rho_max}: the augmented-Lagrangian term would overflow to inf. "
        f"The largest safe bound here is {derived:.4g}"
    )


@dataclass(frozen=True)
class NoteArsResult:
    """A learned weighted DAG and the evidence for it.

    Convention, which is the integration seam with ``tncm_vae``:
    ``weights[j, i]`` is the coefficient of variable ``j`` in the structural
    equation for variable ``i``, i.e. **column ``i`` holds the parents of ``i``**
    and ``adjacency[j, i] = 1`` means ``j -> i``. This is the transposition that
    ``X = X W`` implies, and it is the opposite of
    ``StructuralCausalModel.coefficients[child][parent]``, which is why the
    conversion helpers exist.

    Attributes:
        variables: Column order of every matrix in this record.
        weights: Raw ``d x d`` weight matrix, diagonal zero.
        adjacency: 0/1 matrix obtained by thresholding ``weights``.
        h_trace: ``h(W)`` after each outer augmented-Lagrangian iteration,
            in order. A trace that stalls above ``h_tolerance`` is the signature of
            a fit that did not converge.
        h_final: ``h(W)`` of the returned matrix.
        objective: ``loss + lambda * ||W||_1`` at the returned matrix.
        structural_loss: The least-squares term alone.
        l1_penalty: The L1 term alone.
        acyclic: Whether the **thresholded adjacency** -- the graph a caller would
            actually use -- is acyclic. This is the field to branch on.
        raw_pattern_acyclic: Whether the raw weight matrix's nonzero pattern is
            acyclic. This is almost always ``False`` even for a converged fit,
            because the optimiser leaves float dust of order 1e-12 in every entry
            and a nonzero pattern is exact: a dust edge closes a cycle. It is
            reported for completeness, not as a failure signal; ``h_final`` and
            ``acyclic`` are the meaningful checks.
        converged: Whether ``h(W) <= h_tolerance`` was reached, or ``rho`` reached
            ``rho_max`` -- the latter is reported as *not* converged because the
            constraint, not the budget, is the stopping criterion.
        threshold, l1_strength, standardised: The settings that produced this.
        hit_bound: Whether any weight sits against ``w_bound``; if so the solution
            is a boundary artefact and should not be trusted.
        n_starts: How many restarts were run; the returned fit is the best of them.
    """

    variables: Tuple[str, ...]
    weights: np.ndarray
    adjacency: np.ndarray
    h_trace: Tuple[float, ...]
    h_final: float
    objective: float
    structural_loss: float
    l1_penalty: float
    acyclic: bool
    raw_pattern_acyclic: bool
    converged: bool
    threshold: float
    l1_strength: float
    standardised: bool
    hit_bound: bool
    n_starts: int

    def parents(self) -> Dict[str, Tuple[str, ...]]:
        """The learned structure as a ``tncm_vae`` parents mapping."""
        return adjacency_to_parents(self.adjacency, self.variables)

    def edge_list(self) -> Tuple[Tuple[str, str], ...]:
        """Learned edges as ``(parent, child)`` pairs in canonical variable order."""
        edges: List[Tuple[str, str]] = []
        for child in range(len(self.variables)):
            for parent in range(len(self.variables)):
                if self.adjacency[parent, child] != 0.0:
                    edges.append((self.variables[parent], self.variables[child]))
        return tuple(edges)

    def summary(self) -> str:
        state = "acyclic" if self.acyclic else "CYCLIC (the constraint was not met)"
        return (
            f"NOTEARS learned {len(self.edge_list())} edges over "
            f"{len(self.variables)} variables: h(W)={self.h_final:.3e} after "
            f"{len(self.h_trace)} outer iterations, graph is {state}, "
            f"objective={self.objective:.6g}"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variables": list(self.variables),
            "weights": [[float(value) for value in row] for row in self.weights],
            "adjacency": [[float(value) for value in row] for row in self.adjacency],
            "edges": [list(edge) for edge in self.edge_list()],
            "h_trace": [float(value) for value in self.h_trace],
            "h_final": float(self.h_final),
            "objective": float(self.objective),
            "structural_loss": float(self.structural_loss),
            "l1_penalty": float(self.l1_penalty),
            "acyclic": bool(self.acyclic),
            "raw_pattern_acyclic": bool(self.raw_pattern_acyclic),
            "converged": bool(self.converged),
            "threshold": float(self.threshold),
            "l1_strength": float(self.l1_strength),
            "standardised": bool(self.standardised),
            "hit_bound": bool(self.hit_bound),
            "n_starts": int(self.n_starts),
            "summary": self.summary(),
        }


class NoteArsDiscovery:
    """The augmented-Lagrangian NOTEARS solver for the linear SEM.

    Args:
        config: Solver settings; defaults to :class:`NoteArsConfig`.

    The class holds no state between calls: :meth:`fit` is pure in ``(X, config)``
    up to the seeded restarts, so the same inputs produce the same graph.
    """

    def __init__(self, config: Optional[NoteArsConfig] = None) -> None:
        self.config = config if config is not None else NoteArsConfig()

    # -- the objective handed to L-BFGS-B ----------------------------------

    def _make_objective(self, gram: np.ndarray, l1_strength: float, alpha: float, rho: float):
        """Return ``f(theta) -> (value, gradient)`` for the inner solve.

        ``gram`` is ``X^T X / n``, so the loss is evaluated without touching the
        ``n``-row data matrix on every call.
        """
        d = gram.shape[0]
        identity = np.eye(d)

        def objective(theta: np.ndarray) -> Tuple[float, np.ndarray]:
            weights = _without_diagonal(theta.reshape(d, d))
            # loss = 0.5 * (tr(G) - 2 tr(G W) + tr(W^T G W)), grad = G (W - I)
            loss = 0.5 * (
                np.trace(gram)
                - 2.0 * np.trace(gram @ weights)
                + np.trace(weights.T @ gram @ weights)
            )
            gradient = gram @ (weights - identity)
            penalty = l1_strength * np.sum(np.abs(weights))
            gradient = gradient + l1_strength * np.sign(weights)

            exponential = expm(weights * weights)
            h_value = float(np.trace(exponential) - d)
            h_gradient = exponential.T * (2.0 * weights)
            value = loss + penalty + alpha * h_value + 0.5 * rho * h_value * h_value
            gradient = gradient + (alpha + rho * h_value) * h_gradient

            np.fill_diagonal(gradient, 0.0)
            value = float(value)
            if not math.isfinite(value) or not np.all(np.isfinite(gradient)):
                raise ValueError(
                    "the augmented-Lagrangian objective became non-finite; this "
                    "should be impossible inside w_bound and rho_max and indicates "
                    "a numerical breakdown rather than a data problem"
                )
            return value, gradient.reshape(-1)

        return objective

    # -- one augmented-Lagrangian run --------------------------------------

    def _run(
        self, data: np.ndarray, initial: np.ndarray, bound: float
    ) -> Tuple[np.ndarray, Tuple[float, ...], bool]:
        config = self.config
        d = data.shape[1]
        gram = data.T @ data / data.shape[0]

        weights = _without_diagonal(initial)
        rho = float(config.initial_rho)
        alpha = 0.0
        h_previous = float("inf")
        h_trace: List[float] = []
        converged = False

        for _ in range(config.max_outer_iterations):
            objective = self._make_objective(gram, config.l1_strength, alpha, rho)
            while True:
                solution = minimize(
                    objective,
                    weights.reshape(-1),
                    method="L-BFGS-B",
                    jac=True,
                    bounds=[(-bound, bound)] * (d * d),
                    options={"maxiter": config.max_inner_iterations},
                )
                candidate = _without_diagonal(solution.x.reshape(d, d))
                h_value = acyclicity_constraint(candidate)
                if h_value > config.rho_decrease_ratio * h_previous:
                    # The inner problem was not solved tightly enough for this
                    # penalty: raise the penalty and re-solve from the last
                    # accepted point, as the reference implementation does.
                    if rho >= config.rho_max:
                        break
                    rho = min(rho * config.rho_growth, config.rho_max)
                    objective = self._make_objective(
                        gram, config.l1_strength, alpha, rho
                    )
                    continue
                break

            weights = candidate
            h_value = acyclicity_constraint(weights)
            alpha += rho * h_value
            h_trace.append(h_value)
            h_previous = h_value

            if h_value <= config.h_tolerance:
                converged = True
                break
            if rho >= config.rho_max:
                # Out of penalty budget with the constraint still violated. The
                # graph is reported as not converged rather than silently accepted.
                break

        return weights, tuple(h_trace), converged

    # -- public API --------------------------------------------------------

    def fit(self, X: Any, variables: Sequence[str]) -> NoteArsResult:
        """Learn a weighted DAG from ``X`` (samples x variables).

        Raises:
            ValueError: for shape, config, or weight-matrix mistakes.
            DataQualityError: for non-finite data, constant columns, or fewer
                samples than variables.
        """
        config = self.config
        matrix, names = _validated_data(X, variables)

        # A constant column has no variance, so nothing can be estimated about its
        # structural equation and no edge into or out of it is meaningful. That is
        # a data defect whether or not the caller asked for standardisation, so it
        # is rejected either way rather than being carried through.
        standard_deviation = matrix.std(axis=0, ddof=0)
        degenerate = [
            names[column]
            for column in range(len(names))
            if standard_deviation[column] == 0.0
        ]
        if degenerate:
            raise DataQualityError(
                "these variables are constant in the sample, so their structural "
                f"equation cannot be estimated: {degenerate}",
                context={"variables": degenerate},
            )

        # The structural equations have no intercept, so centering is part of the
        # estimator. Scaling is not, and by default it is not applied: see
        # NoteArsConfig.standardize for why z-scoring can invert the orientation.
        matrix = matrix - matrix.mean(axis=0)
        if config.standardize:
            matrix = matrix / standard_deviation

        d = matrix.shape[1]
        bound = resolve_w_bound(d, config.w_bound, config.rho_max)
        best: Optional[Tuple[float, float, np.ndarray, Tuple[float, ...], bool]] = None
        rng = np.random.default_rng(config.seed)
        n_starts = int(config.n_restarts)

        for start in range(n_starts):
            initial = np.zeros((d, d))
            if start > 0:
                # Random off-diagonal start, kept small: a large start makes the
                # matrix exponential and the constraint too stiff to move.
                initial = rng.uniform(-0.5, 0.5, size=(d, d))
            weights, h_trace, converged = self._run(matrix, initial, bound)
            h_final = acyclicity_constraint(weights)
            objective = note_ars_objective(weights, matrix, config.l1_strength)
            candidate = (h_final, objective, weights, h_trace, converged)
            if best is None:
                best = candidate
                continue
            # Prefer a converged run; among equals prefer a smaller constraint
            # violation, then a smaller objective. Never mix up the two keys: a
            # lower objective with a violated constraint is not a better DAG.
            best_key = (not best[4], best[0], best[1])
            new_key = (not converged, h_final, objective)
            if new_key < best_key:
                best = candidate

        assert best is not None  # n_restarts >= 1 is enforced by the config
        h_final, objective, weights, h_trace, converged = best

        adjacency = threshold_weights(weights, config.threshold)
        result = NoteArsResult(
            variables=names,
            weights=weights,
            adjacency=adjacency,
            h_trace=h_trace,
            h_final=float(h_final),
            objective=float(objective),
            structural_loss=least_squares_loss(weights, matrix),
            l1_penalty=float(config.l1_strength * np.sum(np.abs(weights))),
            acyclic=is_acyclic(adjacency),
            raw_pattern_acyclic=is_acyclic(weights),
            converged=bool(converged),
            threshold=float(config.threshold),
            l1_strength=float(config.l1_strength),
            standardised=bool(config.standardize),
            hit_bound=bool(np.any(np.abs(weights) >= bound - 1e-9)),
            n_starts=n_starts,
        )
        if not result.acyclic:
            logger.warning(
                "NOTEARS returned a thresholded graph that is still cyclic "
                "(h=%s); it must not be used as a DAG",
                result.h_final,
            )
        return result


def notears_linear(
    X: Any,
    variables: Sequence[str],
    config: Optional[NoteArsConfig] = None,
    **overrides: Any,
) -> NoteArsResult:
    """Convenience wrapper: fit NOTEARS with a (possibly overridden) config."""
    effective = config if config is not None else NoteArsConfig()
    if overrides:
        effective = replace(effective, **overrides)
    return NoteArsDiscovery(effective).fit(X, variables)


# ---------------------------------------------------------------------------
# Conversions to and from the tncm_vae parents representation
# ---------------------------------------------------------------------------


def adjacency_to_parents(
    adjacency: Any,
    variables: Sequence[str],
    *,
    require_acyclic: bool = True,
    name: str = "adjacency",
) -> Dict[str, Tuple[str, ...]]:
    """Convert ``adjacency[j, i] = 1`` (meaning ``j -> i``) to a parents mapping.

    The output has exactly the shape of
    ``StructuralCausalModel.parents``: one key per declared variable -- including
    the empty tuples -- mapping to a ``tuple`` of parent names. The order within
    each tuple follows ``variables``; ``tncm_vae`` does not depend on that order
    (it rebuilds a dict from it), but a canonical order makes the round trip and
    the comparisons here deterministic.

    Args:
        adjacency: Square matrix; any nonzero off-diagonal entry is an edge.
        variables: Names in column/row order.
        require_acyclic: When true (the default, matching
            ``StructuralCausalModel``, which raises on a cycle) a cyclic adjacency
            raises :class:`ValueError`. Set false to convert a cyclic matrix for
            diagnostic purposes only.
        name: Name used in error messages.

    Raises:
        ValueError: on shape mismatch, a self-loop, unknown names, or a cycle when
            ``require_acyclic`` is set.
    """
    matrix = _as_square(adjacency, name)
    names = _as_variables(variables)
    if matrix.shape[0] != len(names):
        raise ValueError(
            f"{name} is {matrix.shape[0]}x{matrix.shape[1]} but {len(names)} variable "
            f"names were given"
        )

    for node in range(len(names)):
        if matrix[node, node] != 0.0:
            raise ValueError(
                f"{name} has a self-loop at {names[node]!r}; a structural model has "
                "no self-edge (use self_lag in tncm_vae for own dynamics)"
            )

    if require_acyclic and not is_acyclic(matrix):
        raise ValueError(
            f"{name} contains a cycle, so it cannot be expressed as the acyclic "
            "parents mapping StructuralCausalModel requires; pass "
            "require_acyclic=False only for diagnostics"
        )

    parents: Dict[str, Tuple[str, ...]] = {}
    for child in range(len(names)):
        parents[names[child]] = tuple(
            names[parent] for parent in range(len(names)) if matrix[parent, child] != 0.0
        )
    return parents


def parents_to_adjacency(
    parents: Mapping[str, Sequence[str]],
    variables: Optional[Sequence[str]] = None,
) -> np.ndarray:
    """Convert a parents mapping to ``adjacency[parent, child] = 1``.

    ``parents`` must have exactly the shape produced by ``tncm_vae``: a mapping in
    which every variable appears as a key, including those with no parents whose
    value is an empty tuple. A missing key raises rather than being read as "no
    parents", because the two are not the same statement and silently defaulting
    would invent structure.

    Args:
        parents: ``{child: (parent, ...)}``.
        variables: Names in the desired matrix order. When omitted, the keys of
            ``parents`` are used in their insertion order.

    Raises:
        ValueError: on unknown names, a missing variable key, a self-parent, a
            non-sequence value, or a cycle (which ``StructuralCausalModel`` would
            reject).
    """
    if not isinstance(parents, Mapping):
        raise ValueError(
            f"parents must be a mapping child -> sequence of parents, got "
            f"{type(parents).__name__}"
        )
    if variables is None:
        names = _as_variables(tuple(parents.keys()))
    else:
        names = _as_variables(variables)
        missing = [name for name in names if name not in parents]
        if missing:
            raise ValueError(
                f"parents is missing entries for {missing}; the mapping must name "
                "every variable, exactly as StructuralCausalModel.parents does, "
                "with an empty tuple for a variable that has no parents"
            )

    unknown = [key for key in parents if key not in names]
    if unknown:
        raise ValueError(f"parents names children that are not declared: {unknown}")

    index = {name: position for position, name in enumerate(names)}
    adjacency = np.zeros((len(names), len(names)), dtype=float)
    for child, parent_list in parents.items():
        if isinstance(parent_list, str):
            raise ValueError(
                f"parents[{child!r}] is the string {parent_list!r}; a bare string is "
                "a sequence of characters, not a list of parents -- did you mean "
                f"({parent_list!r},)?"
            )
        for parent in parent_list:
            if parent not in index:
                raise ValueError(
                    f"variable {child!r} lists parent {parent!r}, which is not a "
                    "declared variable"
                )
            if parent == child:
                raise ValueError(
                    f"variable {child!r} lists itself as a parent; a structural "
                    "model has no self-edge"
                )
            adjacency[index[parent], index[child]] = 1.0

    if not is_acyclic(adjacency):
        raise ValueError(
            "the parents mapping contains a cycle, which StructuralCausalModel "
            "rejects; a parents mapping that cannot be handed to tncm_vae is not a "
            "valid conversion target"
        )
    return adjacency


def weights_to_parents(
    weights: Any,
    variables: Sequence[str],
    threshold: float = 0.3,
) -> Dict[str, Tuple[str, ...]]:
    """Threshold a weight matrix and convert it to the parents mapping."""
    return adjacency_to_parents(threshold_weights(weights, threshold), variables)


# ---------------------------------------------------------------------------
# Constraint-based baseline: partial-correlation skeleton (NOT PC)
# ---------------------------------------------------------------------------


def partial_correlation(
    X: Any,
    i: int,
    j: int,
    conditioning: Sequence[int] = (),
) -> float:
    """Partial correlation of columns ``i`` and ``j`` given ``conditioning``.

    Computed with the standard recursion used by constraint-based methods::

        r(i, j | S) = (r(i, j | S\\k) - r(i, k | S\\k) * r(j, k | S\\k))
                      / sqrt((1 - r(i, k | S\\k)^2) (1 - r(j, k | S\\k)^2))

    with the unconditional correlation as the base case. The tests check it
    against the independent route: the correlation of the residuals of the OLS
    regressions of ``i`` and ``j`` on the conditioning columns.

    Raises:
        ValueError: for out-of-range or repeated indices.
        DataQualityError: for zero-variance columns, or when a denominator vanishes
            (perfect collinearity, which makes the conditional correlation
            undefined rather than zero).
    """
    matrix = _as_data_matrix(X)
    d = matrix.shape[1]
    for label, position in (("i", i), ("j", j)):
        if not isinstance(position, (int, np.integer)) or not 0 <= int(position) < d:
            raise ValueError(f"{label}={position!r} is not a column index in [0, {d})")
    i, j = int(i), int(j)
    if i == j:
        raise ValueError("a partial correlation needs two distinct columns")

    indices = tuple(int(k) for k in conditioning)
    if any(not 0 <= k < d for k in indices):
        raise ValueError(f"conditioning indices out of range: {indices}")
    if len(set(indices)) != len(indices):
        raise ValueError(f"conditioning indices repeat: {indices}")
    if i in indices or j in indices:
        raise ValueError(
            f"conditioning set {indices} contains an endpoint of the correlation "
            f"({i}, {j})"
        )
    if matrix.shape[0] < 3:
        raise DataQualityError(
            f"a correlation needs at least 3 samples, got {matrix.shape[0]}"
        )
    _require_positive_variance(matrix, (i, j, *indices))

    if not indices:
        return float(np.corrcoef(matrix[:, i], matrix[:, j])[0, 1])

    pivot = indices[-1]
    rest = indices[:-1]
    r_ij = partial_correlation(matrix, i, j, rest)
    r_ik = partial_correlation(matrix, i, pivot, rest)
    r_jk = partial_correlation(matrix, j, pivot, rest)
    denominator = math.sqrt(max(0.0, (1.0 - r_ik * r_ik) * (1.0 - r_jk * r_jk)))
    if denominator <= 0.0:
        raise DataQualityError(
            f"the partial correlation of columns {i} and {j} given {indices} is "
            f"undefined: column {pivot} is perfectly predictable from the rest of "
            "the conditioning set, so the recursion divides by zero. This is "
            "collinearity in the data, not an independence result",
            context={"i": i, "j": j, "conditioning": list(indices)},
        )
    value = (r_ij - r_ik * r_jk) / denominator
    if not math.isfinite(value):
        raise DataQualityError(
            f"the partial correlation of columns {i} and {j} given {indices} is "
            f"non-finite ({value})"
        )
    return float(value)


def _require_positive_variance(matrix: np.ndarray, columns: Sequence[int]) -> None:
    for column in columns:
        if float(matrix[:, column].std(ddof=0)) <= 0.0:
            raise DataQualityError(
                f"column {column} is constant in the sample; its correlations are "
                "undefined and causal discovery will not drop or impute it"
            )


def _fisher_z_p_value(r: float, n_samples: int, n_conditioning: int) -> float:
    """Two-sided p-value for conditional independence from the Fisher z statistic.

    ``z = atanh(r) * sqrt(n - |S| - 3)``, which is standard normal under the null
    of conditional independence for jointly Gaussian data. ``|r| = 1`` is the
    limiting case of perfect conditional dependence and returns p = 0.

    Raises:
        DataQualityError: when ``n - |S| - 3 <= 0``, i.e. the sample cannot support
            a test at this conditioning size. The asymptotic approximation is
            meaningless there, and returning 1.0 (the "no evidence" value) would
            look like independence.
    """
    degrees_of_freedom = n_samples - n_conditioning - 3
    if degrees_of_freedom <= 0:
        raise DataQualityError(
            f"cannot test conditional independence with {n_samples} samples and a "
            f"conditioning set of size {n_conditioning}: the Fisher z statistic "
            "requires n - |S| - 3 > 0",
            context={"n_samples": int(n_samples), "conditioning_size": int(n_conditioning)},
        )
    if abs(r) >= 1.0:
        return 0.0
    z = math.atanh(r) * math.sqrt(degrees_of_freedom)
    return float(math.erfc(abs(z) / math.sqrt(2.0)))


@dataclass(frozen=True)
class SkeletonResult:
    """An undirected skeleton plus the partial orientations the collider rule gave.

    Attributes:
        variables: Column order.
        skeleton: Symmetric 0/1 matrix, zero diagonal; ``skeleton[i, j] = 1`` means
            an undirected edge between ``i`` and ``j``.
        directed: 0/1 matrix where ``directed[i, j] = 1`` means ``i -> j`` was
            oriented by the collider rule. ``directed[i, j]`` and
            ``directed[j, i]`` are never both set; edges with neither set remain
            undirected, which is the normal case.
        sepsets: For each removed edge ``(i, j)``, the conditioning set that made the
            two columns independent. Stored under both ``(i, j)`` and ``(j, i)``.
        p_values: The p-value that triggered each removal, keyed like ``sepsets``.
        max_conditioning_size: Largest conditioning set the search considered.
        alpha: Significance level used for the independence test.
        orientation_conflicts: Edges the collider rule would have oriented in both
            directions. Non-empty means the CI tests are inconsistent (violated
            faithfulness or sampling noise); those edges are left undirected.
    """

    variables: Tuple[str, ...]
    skeleton: np.ndarray
    directed: np.ndarray
    sepsets: Dict[Tuple[int, int], Tuple[int, ...]]
    p_values: Dict[Tuple[int, int], float]
    max_conditioning_size: int
    alpha: float
    orientation_conflicts: Tuple[Tuple[str, str], ...]

    def skeleton_edges(self) -> Tuple[Tuple[str, str], ...]:
        """Undirected edges as ``(a, b)`` name pairs with ``index(a) < index(b)``."""
        edges: List[Tuple[str, str]] = []
        for i in range(len(self.variables)):
            for j in range(i + 1, len(self.variables)):
                if self.skeleton[i, j] != 0.0:
                    edges.append((self.variables[i], self.variables[j]))
        return tuple(edges)

    def directed_edges(self) -> Tuple[Tuple[str, str], ...]:
        """Oriented edges as ``(source, target)`` name pairs."""
        edges: List[Tuple[str, str]] = []
        for i in range(len(self.variables)):
            for j in range(len(self.variables)):
                if self.directed[i, j] != 0.0:
                    edges.append((self.variables[i], self.variables[j]))
        return tuple(edges)

    def summary(self) -> str:
        oriented = self.directed_edges()
        undirected = [
            edge
            for edge in self.skeleton_edges()
            if not (
                self.directed[self.variables.index(edge[0]), self.variables.index(edge[1])]
                or self.directed[self.variables.index(edge[1]), self.variables.index(edge[0])]
            )
        ]
        text = (
            f"partial-correlation skeleton with {len(self.skeleton_edges())} edges "
            f"over {len(self.variables)} variables; {len(oriented)} oriented by the "
            f"collider rule, {len(undirected)} left undirected"
        )
        if self.orientation_conflicts:
            text += f"; {len(self.orientation_conflicts)} orientation conflicts"
        return text

    def to_dict(self) -> Dict[str, Any]:
        names = self.variables
        return {
            "variables": list(names),
            "skeleton": [[float(value) for value in row] for row in self.skeleton],
            "directed": [[float(value) for value in row] for row in self.directed],
            "edges": [list(edge) for edge in self.skeleton_edges()],
            "directed_edges": [list(edge) for edge in self.directed_edges()],
            "sepsets": [
                {
                    "i": names[i],
                    "j": names[j],
                    "conditioning": [names[k] for k in conditioning],
                    "p_value": float(self.p_values[(i, j)]),
                }
                for (i, j), conditioning in sorted(self.sepsets.items())
                if i < j
            ],
            "max_conditioning_size": int(self.max_conditioning_size),
            "alpha": float(self.alpha),
            "orientation_conflicts": [list(edge) for edge in self.orientation_conflicts],
            "summary": self.summary(),
        }


class PartialCorrelationSkeleton:
    """Edge removal by partial-correlation tests; **not** the PC algorithm.

    This is labelled plainly because the distinction matters. What is implemented
    is PC's *skeleton* stage: start from the complete undirected graph and delete
    the edge ``i - j`` as soon as some conditioning set makes ``i`` and ``j``
    conditionally independent, remembering the separating set. What is **not**
    implemented is PC's orientation stage beyond its first rule: only the collider
    (v-structure) rule is applied, and only to unshielded triples, where the
    separating set of the outer pair does not contain the middle node. The Meek
    rules R1-R4, which propagate orientations through the remaining edges, are
    absent; therefore edges that PC would orient reproducibly are returned here
    undirected, and :attr:`SkeletonResult.directed` is a partial orientation, not a
    DAG. It must never be handed to a counterfactual engine as if it were one.

    The tests use it as an independent second opinion on which edges exist, which
    is the comparison that is actually supported by what is implemented.

    Args:
        alpha: Significance level of the Fisher-z test. Smaller removes fewer
            edges.
        max_conditioning_size: Largest conditioning set considered. ``None`` means
            ``d - 2``, the standard PC bound; the enumeration is over subsets and
            is exponential in this size, so large ``d`` is impractical.

    Scope and failure modes: the test assumes jointly Gaussian data; a monotone
    nonlinear dependence can be invisible, and with small ``n`` the test has almost
    no power (and raises outright once ``n - |S| - 3 <= 0``).
    """

    def __init__(
        self,
        alpha: float = 0.01,
        max_conditioning_size: Optional[int] = None,
    ) -> None:
        if not math.isfinite(alpha) or not 0.0 < alpha < 1.0:
            raise ValueError(f"alpha must lie strictly between 0 and 1, got {alpha}")
        if max_conditioning_size is not None and max_conditioning_size < 0:
            raise ValueError(
                f"max_conditioning_size must be non-negative, got {max_conditioning_size}"
            )
        self.alpha = float(alpha)
        self.max_conditioning_size = max_conditioning_size

    def fit(self, X: Any, variables: Sequence[str]) -> SkeletonResult:
        """Recover the skeleton and apply the collider orientation rule.

        Raises:
            ValueError: for shape mistakes.
            DataQualityError: for non-finite data, constant columns, too few
                samples, or a conditioning size the sample cannot support.
        """
        matrix, names = _validated_data(X, variables)
        d = len(names)
        n_samples = matrix.shape[0]
        _require_positive_variance(matrix, tuple(range(d)))

        max_size = (
            d - 2 if self.max_conditioning_size is None else int(self.max_conditioning_size)
        )
        max_size = max(0, min(max_size, d - 1))
        if max_size > 0 and n_samples - max_size - 3 <= 0:
            raise DataQualityError(
                f"cannot condition on sets of size {max_size} with {n_samples} "
                "samples: the Fisher z statistic requires n - |S| - 3 > 0",
                context={"n_samples": int(n_samples), "max_conditioning_size": int(max_size)},
            )

        skeleton = np.ones((d, d), dtype=float)
        np.fill_diagonal(skeleton, 0.0)
        sepsets: Dict[Tuple[int, int], Tuple[int, ...]] = {}
        p_values: Dict[Tuple[int, int], float] = {}

        for size in range(0, max_size + 1):
            for i in range(d):
                for j in range(i + 1, d):
                    if skeleton[i, j] == 0.0:
                        continue
                    neighbours = [
                        k for k in range(d) if k != j and skeleton[i, k] != 0.0
                    ]
                    if len(neighbours) < size:
                        continue
                    for conditioning in combinations(neighbours, size):
                        r = partial_correlation(matrix, i, j, conditioning)
                        p_value = _fisher_z_p_value(r, n_samples, size)
                        if p_value >= self.alpha:
                            skeleton[i, j] = skeleton[j, i] = 0.0
                            sepsets[(i, j)] = conditioning
                            sepsets[(j, i)] = conditioning
                            p_values[(i, j)] = p_value
                            p_values[(j, i)] = p_value
                            break

        directed, conflicts = self._orient_colliders(skeleton, sepsets, names)
        return SkeletonResult(
            variables=names,
            skeleton=skeleton,
            directed=directed,
            sepsets=sepsets,
            p_values=p_values,
            max_conditioning_size=int(max_size),
            alpha=float(self.alpha),
            orientation_conflicts=conflicts,
        )

    @staticmethod
    def _orient_colliders(
        skeleton: np.ndarray,
        sepsets: Mapping[Tuple[int, int], Tuple[int, ...]],
        names: Tuple[str, ...],
    ) -> Tuple[np.ndarray, Tuple[Tuple[str, str], ...]]:
        """Orient unshielded triples ``i - k - j`` as ``i -> k <- j`` when ``k`` is
        not in the separating set of ``(i, j)``.

        This is the single orientation rule of the PC algorithm that observational
        data can justify directly: if ``i`` and ``j`` are marginally independent but
        both become dependent once ``k`` is conditioned on, the only unconfounded
        explanation is that ``k`` is a common effect. Note the if: with latent
        confounding the rule is wrong, and this module handles no latent variables.
        """
        d = skeleton.shape[0]
        directed = np.zeros((d, d), dtype=float)
        conflicts: List[Tuple[str, str]] = []

        for middle in range(d):
            neighbours = [k for k in range(d) if skeleton[middle, k] != 0.0]
            for i, j in combinations(neighbours, 2):
                if skeleton[i, j] != 0.0:
                    continue  # shielded triple: not a v-structure
                if middle in sepsets.get((i, j), ()):
                    # The middle is in the separating set, so the triple is a chain
                    # or a fork. The collider rule says nothing here.
                    continue
                for source in (i, j):
                    if directed[middle, source] != 0.0:
                        conflicts.append((names[middle], names[source]))
                        continue
                    directed[source, middle] = 1.0
        return directed, tuple(conflicts)


# ---------------------------------------------------------------------------
# compare_dag: the deliverable the review asked for
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OrientationConflict:
    """A node pair that is an edge in both structures, pointing opposite ways."""

    learned_source: str
    learned_target: str
    declared_source: str
    declared_target: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "learned_source": self.learned_source,
            "learned_target": self.learned_target,
            "declared_source": self.declared_source,
            "declared_target": self.declared_target,
        }


@dataclass(frozen=True)
class DagComparison:
    """Edge-level discrepancies between a learned DAG and a declared one.

    Read the asymmetry, because the two directions of error are not equally
    dangerous and the summary does not pretend they are:

    * ``learned_only`` -- the data support a parent relation the declaration omits.
      The declared DAG is **under-specified**. This is the severe case: an
      undeclared parent is an open confounding path, so ``do(X)`` in
      ``tncm_vae`` leaves a channel through which the counterfactual can move,
      and the engine will report that movement as a causal effect of ``X``.
    * ``declared_only`` -- the declaration asserts a parent the data do not
      support. The declared DAG is **over-specified** (or the data lack the power
      to see the edge). Less immediately dangerous: severing a spurious edge in
      ``do`` is either harmless or makes the counterfactual conservative, though
      the declared coefficients are still being applied to a relationship the data
      do not corroborate.
    * ``orientation_conflicts`` -- both agree the pair is connected and disagree
      about which way. This is simultaneously an over- and an under-specification
      and is reported separately; a conflict edge also appears in
      ``learned_only`` and ``declared_only`` because, read literally, the learned
      direction is absent from the declaration and the declared direction is absent
      from the learned graph.

    Attributes:
        variables: Variable names, in the order used for canonical sorting.
        learned_only: Learned edges absent from the declaration, as
            ``(parent, child)`` in canonical order.
        declared_only: Declared edges absent from the learned graph.
        orientation_conflicts: Node pairs present in both with opposite directions.
        agreed: Edges present in both with the same direction.
        model_risk_warning: True iff any discrepancy exists.
        under_specified: True iff ``learned_only`` is non-empty (the severe case).
        over_specified: True iff ``declared_only`` is non-empty.
    """

    variables: Tuple[str, ...]
    learned_only: Tuple[Tuple[str, str], ...]
    declared_only: Tuple[Tuple[str, str], ...]
    orientation_conflicts: Tuple[OrientationConflict, ...]
    agreed: Tuple[Tuple[str, str], ...]
    model_risk_warning: bool
    under_specified: bool
    over_specified: bool
    summary_text: str

    def summary(self) -> str:
        return self.summary_text

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variables": list(self.variables),
            "learned_only": [list(edge) for edge in self.learned_only],
            "declared_only": [list(edge) for edge in self.declared_only],
            "orientation_conflicts": [
                conflict.to_dict() for conflict in self.orientation_conflicts
            ],
            "agreed": [list(edge) for edge in self.agreed],
            "model_risk_warning": bool(self.model_risk_warning),
            "under_specified": bool(self.under_specified),
            "over_specified": bool(self.over_specified),
            "summary": self.summary_text,
        }


def _coerce_edges(
    structure: Any,
    variables: Optional[Sequence[str]],
    label: str,
) -> Tuple[Dict[str, Tuple[str, ...]], Tuple[str, ...]]:
    """Normalise an adjacency matrix or a parents mapping to a parents mapping."""
    if isinstance(structure, Mapping):
        declared_names: Optional[Tuple[str, ...]] = (
            None if variables is None else _as_variables(variables)
        )
        adjacency = parents_to_adjacency(structure, declared_names)
        names = (
            declared_names
            if declared_names is not None
            else _as_variables(tuple(structure.keys()))
        )
        return adjacency_to_parents(adjacency, names, name=label), names

    matrix = _as_square(structure, label)
    if variables is None:
        raise ValueError(
            f"{label} was given as a matrix, so the variable names are unknown; "
            "pass variables=(...) as well, or pass a parents mapping"
        )
    names = _as_variables(variables)
    if matrix.shape[0] != len(names):
        raise ValueError(
            f"{label} is {matrix.shape[0]}x{matrix.shape[1]} but {len(names)} variable "
            f"names were given"
        )
    return adjacency_to_parents(matrix, names, name=label), names


def compare_dag(
    learned: Any,
    declared: Any,
    *,
    variables: Optional[Sequence[str]] = None,
) -> DagComparison:
    """Compare a learned DAG against a declared one, edge by edge.

    Neither input is authoritative. The learned graph comes from observational
    data and carries every limitation listed in this module's docstring; the
    declared graph is a modelling assumption. The output is a discrepancy report
    to argue with, **not** a verdict that the declaration is wrong and the learned
    graph is right.

    Args:
        learned: Either a 0/1 adjacency matrix (``[parent, child] = 1``) or a
            ``tncm_vae``-style parents mapping. Nonzero entries are treated as
            edges; feed a raw weight matrix only after :func:`threshold_weights`.
        declared: The same, for the declaration.
        variables: Variable order, required for matrix inputs and used to make the
            output order deterministic. Optional when both inputs are mappings.

    Returns:
        A :class:`DagComparison`.

    Raises:
        ValueError: for shape mistakes, unknown or missing variable names, a
            self-loop, or a cycle in either input (a cyclic graph is not a DAG and
            cannot be compared as one).
        DataQualityError: never -- this function operates on structure, not data.
    """
    learned_parents, learned_names = _coerce_edges(learned, variables, "learned")
    declared_parents, declared_names = _coerce_edges(declared, variables, "declared")
    if set(learned_names) != set(declared_names):
        raise ValueError(
            "the learned and declared structures cover different variables: "
            f"{sorted(set(learned_names) ^ set(declared_names))} differ"
        )
    names = learned_names

    learned_edges = {
        (parent, child)
        for child, parent_list in learned_parents.items()
        for parent in parent_list
    }
    declared_edges = {
        (parent, child)
        for child, parent_list in declared_parents.items()
        for parent in parent_list
    }

    order = {name: position for position, name in enumerate(names)}
    key = lambda edge: (order[edge[0]], order[edge[1]])  # noqa: E731 - terse local sorter

    learned_only = tuple(sorted(learned_edges - declared_edges, key=key))
    declared_only = tuple(sorted(declared_edges - learned_edges, key=key))
    agreed = tuple(sorted(learned_edges & declared_edges, key=key))

    conflicts: List[OrientationConflict] = []
    for parent, child in learned_only:
        if (child, parent) in declared_edges:
            conflicts.append(
                OrientationConflict(
                    learned_source=parent,
                    learned_target=child,
                    declared_source=child,
                    declared_target=parent,
                )
            )
    conflicts.sort(key=lambda item: (order[item.learned_source], order[item.learned_target]))

    model_risk_warning = bool(learned_only or declared_only)
    under_specified = bool(learned_only)
    over_specified = bool(declared_only)

    if not model_risk_warning:
        text = (
            f"the learned and declared structures agree on all {len(agreed)} edges "
            f"over {len(names)} variables; no discrepancy was found"
        )
        return DagComparison(
            variables=names,
            learned_only=(),
            declared_only=(),
            orientation_conflicts=(),
            agreed=agreed,
            model_risk_warning=False,
            under_specified=False,
            over_specified=False,
            summary_text=text,
        )

    parts: List[str] = []
    if learned_only:
        parts.append(
            f"{len(learned_only)} learned-only edge(s) {list(learned_only)}: the data "
            "support a parent the declaration omits, so the declared DAG is "
            "UNDER-SPECIFIED and the omitted parent is an open path through which a "
            "counterfactual can move -- the severe direction of model risk"
        )
    if declared_only:
        parts.append(
            f"{len(declared_only)} declared-only edge(s) {list(declared_only)}: the "
            "declaration asserts a parent the data do not support, so the declared "
            "DAG is OVER-SPECIFIED (or the data lack the power to see it)"
        )
    if conflicts:
        rendered = [
            f"{item.declared_source}->{item.declared_target} (declared) vs "
            f"{item.learned_source}->{item.learned_target} (learned)"
            for item in conflicts
        ]
        parts.append(
            f"{len(conflicts)} orientation conflict(s) {rendered}: the same node pair "
            "points opposite ways, which the data alone cannot resolve within a "
            "Markov equivalence class"
        )
    text = (
        f"learned and declared structures agree on {len(agreed)} edge(s) but differ "
        f"on {len(learned_only) + len(declared_only)}: " + "; ".join(parts)
    )

    return DagComparison(
        variables=names,
        learned_only=learned_only,
        declared_only=declared_only,
        orientation_conflicts=tuple(conflicts),
        agreed=agreed,
        model_risk_warning=True,
        under_specified=under_specified,
        over_specified=over_specified,
        summary_text=text,
    )
