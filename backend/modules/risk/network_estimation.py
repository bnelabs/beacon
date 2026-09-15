"""Bilateral exposure estimation from aggregate totals.

Why this module exists
----------------------

The clearing and fire-sale engines are only as useful as the networks they
run on, and real bilateral interbank matrices are rarely public. What IS
public for many jurisdictions (FDIC call reports, ECB supervisory data) is
each institution's *aggregate* interbank assets and liabilities. This module
turns those marginals into bilateral matrices, and -- because a single
completion hides how much the answer depends on the unknown structure --
propagates the structural uncertainty through the clearing engine.

Three estimators, one contract
------------------------------

``estimate_bilateral_matrix``
    The **maximum-entropy** completion: the matrix with the given row and
    column sums that assumes no other structure -- the least-informative
    completion consistent with the data. Dense by construction; the standard
    baseline in the literature (Mistrulli, Upper; Anand et al.).

``estimate_minimum_density``
    The **minimum-support** corner: a greedy transportation solve that
    reproduces the same marginals with as few bilateral links as possible.
    Real interbank networks are sparse and concentrated, and the
    maximum-entropy estimator is known to *understate* contagion on such
    networks. The two estimators bracket the structural uncertainty: the
    truth is not guaranteed to sit between them, but the pair says how much
    of the answer is the data and how much is the completion assumption.

``posterior_draws``
    A **marginal-preserving structure bootstrap**: Dirichlet-weighted
    resampling of the estimated cells, re-reconciled to the *declared*
    marginals after every draw. The draws span completions consistent with
    the same aggregates, which is the uncertainty the marginals leave open.
    They are not a Bayesian posterior from a generative likelihood of the
    banking system, and the result says so.

``propagate_estimation_uncertainty``
    Runs Eisenberg-Noe clearing on the point estimate and on every draw
    under a declared shock, and reports shortfall and default counts as
    percentile bands. One number from one completion would present an
    assumption as a measurement; the bands keep the distinction visible.

Honesty contract
----------------

* The estimators invent no totals: row and column sums reproduce the declared
  aggregates (up to the reported reconciliation residual), and the declared
  aggregates are the only structural input.
* The zero-diagonal constraint (no bank lends to itself) can break the exact
  marginals; bounded reconciliation restores them and the residual is
  reported, never hidden. For the minimum-support estimator an exactly
  infeasible marginal pair (a bank that owes what only it is owed) leaves a
  reported residual rather than a silently repaired matrix.
* When aggregate assets and liabilities disagree (they often do, across
  reporting populations), the matrix is scaled to the smaller total and the
  discrepancy is reported as ``marginal_mismatch`` -- the operator sees how
  much of the system was unbalanced before any modelling.
* Endowments are *declared* (``build_clearing_inputs``), never estimated: an
  operator-chosen buffer ratio, stated in the result.
* Every result carries ``method`` and ``uncertainty`` strings: an estimated
  matrix is a prior, not a measurement. Downstream clearing results inherit
  that caveat and the module says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Sequence, Tuple

import numpy as np

from backend.modules.risk.clearing import ClearingResult, sequential_clearing

__all__ = [
    "EstimatedNetwork",
    "estimate_bilateral_matrix",
    "estimate_minimum_density",
    "posterior_draws",
    "propagate_estimation_uncertainty",
    "ClearingUncertainty",
    "build_clearing_inputs",
]


@dataclass(frozen=True)
class EstimatedNetwork:
    """The estimated bilateral matrix plus everything needed to audit it."""

    node_ids: Tuple[str, ...]
    liabilities: np.ndarray
    method: str = "maximum_entropy_ras"
    marginal_residual: float = 0.0
    marginal_mismatch: float = 0.0
    iterations: int = 0
    uncertainty: str = (
        "estimated completion of declared aggregate marginals: a prior over "
        "bilateral structure, not a measurement of bilateral exposures; "
        "clearing results inherit this caveat"
    )
    notes: Sequence[str] = field(default_factory=tuple)

    def row_sums(self) -> np.ndarray:
        return self.liabilities.sum(axis=1)

    def col_sums(self) -> np.ndarray:
        return self.liabilities.sum(axis=0)

    def n_links(self) -> int:
        """Number of non-zero bilateral links (the support size)."""
        return int((self.liabilities > 0).sum())


def _validated_totals(
    interbank_assets: Mapping[str, float],
    interbank_liabilities: Mapping[str, float],
    *,
    tolerance: float,
) -> Tuple[Tuple[str, ...], np.ndarray, np.ndarray, float, list]:
    """Shared front door: node order, non-negative totals, scaling, notes.

    Both estimators must treat the declared aggregates identically, so the
    balancing decision (scale to the smaller total, report the mismatch) is
    made once, here.
    """
    nodes = tuple(sorted(set(interbank_assets) | set(interbank_liabilities)))
    if len(nodes) < 2:
        raise ValueError("a bilateral network needs at least two institutions")

    assets = np.array(
        [max(0.0, float(interbank_assets.get(n, 0.0))) for n in nodes]
    )
    liabs = np.array(
        [max(0.0, float(interbank_liabilities.get(n, 0.0))) for n in nodes]
    )

    notes: list = []
    total_assets = float(assets.sum())
    total_liabs = float(liabs.sum())
    mismatch = abs(total_assets - total_liabs)
    scale = min(total_assets, total_liabs)
    if scale <= 0:
        raise ValueError("declared interbank totals are all zero: nothing to estimate")
    if mismatch > tolerance:
        notes.append(
            f"aggregate assets ({total_assets:.6g}) and liabilities "
            f"({total_liabs:.6g}) disagree by {mismatch:.6g}; matrix scaled to "
            "the smaller total"
        )
        assets = assets * (scale / total_assets) if total_assets else assets
        liabs = liabs * (scale / total_liabs) if total_liabs else liabs
    return nodes, assets, liabs, mismatch, notes


def _ras_reconcile(
    matrix: np.ndarray,
    row_target: np.ndarray,
    col_target: np.ndarray,
    *,
    max_iterations: int,
    tolerance: float,
    scale: float,
    prune: bool = True,
) -> Tuple[np.ndarray, float, int]:
    """RAS iteration restoring the marginals broken by the zero diagonal.

    Degenerate supports (entries that must be exactly zero) make plain RAS
    limit-cycle, so an outer loop thresholds numerically-dead entries and
    refits on the reduced support -- the standard fix, and the residual is
    reported either way.
    """
    def _ras(matrix: np.ndarray, iterations: int) -> Tuple[np.ndarray, float, int]:
        used = 0
        residual = np.inf
        for used in range(1, iterations + 1):
            row_sums = matrix.sum(axis=1)
            row_factor = np.where(
                row_sums > 0, row_target / np.where(row_sums > 0, row_sums, 1.0), 0.0
            )
            matrix = matrix * row_factor[:, None]
            col_sums = matrix.sum(axis=0)
            col_factor = np.where(
                col_sums > 0, col_target / np.where(col_sums > 0, col_sums, 1.0), 0.0
            )
            matrix = matrix * col_factor[None, :]
            np.fill_diagonal(matrix, 0.0)
            residual = float(
                max(
                    np.max(np.abs(matrix.sum(axis=1) - row_target)),
                    np.max(np.abs(matrix.sum(axis=0) - col_target)),
                )
            )
            if residual <= tolerance:
                break
        return matrix, residual, used

    small_threshold = 1e-4 * scale
    total_used = 0
    residual = np.inf
    for _outer in range(6):
        matrix, residual, used = _ras(matrix, max_iterations)
        total_used += used
        dead = (matrix > 0) & (matrix < small_threshold)
        if not dead.any() or residual <= tolerance or not prune:
            break
        matrix[dead] = 0.0
    return np.where(matrix > 0, matrix, 0.0), residual, total_used


def estimate_bilateral_matrix(
    interbank_assets: Mapping[str, float],
    interbank_liabilities: Mapping[str, float],
    *,
    max_iterations: int = 5000,
    tolerance: float = 1e-8,
) -> EstimatedNetwork:
    """Estimate a bilateral liability matrix from per-institution totals.

    Args:
        interbank_assets: ``institution -> total interbank claims`` (what it
            is owed). These become the matrix **column** sums: column j is
            what all debtors owe to j.
        interbank_liabilities: ``institution -> total interbank obligations``
            (what it owes): the matrix **row** sums.
        max_iterations: Cap on the RAS reconciliation of the zero-diagonal
            constraint. Reaching it reports the residual, it does not raise.
        tolerance: Convergence threshold on the worst marginal deviation.

    Returns:
        An :class:`EstimatedNetwork` whose ``liabilities[i, j]`` is what ``i``
        owes ``j``, with a zero diagonal and marginals reproducing the
        declared totals up to the reported residual.
    """
    nodes, assets, liabs, mismatch, notes = _validated_totals(
        interbank_assets, interbank_liabilities, tolerance=tolerance
    )

    # Maximum-entropy (independence) prior: X_ij proportional to liab_i * asset_j.
    matrix = np.outer(liabs, assets)
    denom = assets.sum()
    if denom > 0:
        matrix = matrix / denom
    np.fill_diagonal(matrix, 0.0)

    matrix, residual, iterations = _ras_reconcile(
        matrix,
        liabs,
        assets,
        max_iterations=max_iterations,
        tolerance=tolerance,
        scale=float(min(assets.sum(), liabs.sum())),
    )
    return EstimatedNetwork(
        node_ids=nodes,
        liabilities=matrix,
        method="maximum_entropy_ras",
        marginal_residual=residual,
        marginal_mismatch=mismatch,
        iterations=iterations,
        notes=tuple(notes),
    )


def estimate_minimum_density(
    interbank_assets: Mapping[str, float],
    interbank_liabilities: Mapping[str, float],
    *,
    tolerance: float = 1e-8,
) -> EstimatedNetwork:
    """Estimate the sparsest bilateral matrix consistent with the totals.

    Greedy transportation solve: each debtor, largest obligation first, pays
    the creditor with the largest remaining claim (never itself) until either
    side is exhausted. The result uses at most ``2n - 1`` links for generic
    marginals -- the concentrated corner opposite the maximum-entropy
    estimator's dense one.

    Why it exists: real interbank networks are sparse, and clearing on a
    maximum-entropy completion understates contagion precisely because that
    completion spreads every exposure thin. Reporting both completions turns
    "the network structure is unknown" from a hidden assumption into a
    visible interval.

    The zero-diagonal constraint can make the marginals exactly infeasible on
    a sparse support (a debtor whose only remaining creditor is itself). The
    unplaceable mass is reported as ``marginal_residual``; it is never
    silently redistributed onto the diagonal.
    """
    nodes, assets, liabs, mismatch, notes = _validated_totals(
        interbank_assets, interbank_liabilities, tolerance=tolerance
    )
    n = len(nodes)
    matrix = np.zeros((n, n))
    row_rem = liabs.copy()
    col_rem = assets.copy()

    # Rows in descending obligation: settling the largest debtor first keeps
    # the support small (each payment exhausts one side).
    for i in np.argsort(-row_rem):
        while row_rem[i] > tolerance:
            candidates = np.where(col_rem > tolerance)[0]
            candidates = candidates[candidates != i]
            if candidates.size == 0:
                break
            j = int(candidates[np.argmax(col_rem[candidates])])
            amount = min(row_rem[i], col_rem[j])
            matrix[i, j] += amount
            row_rem[i] -= amount
            col_rem[j] -= amount

    residual = float(max(row_rem.max(initial=0.0), col_rem.max(initial=0.0)))
    if residual > tolerance:
        notes.append(
            f"minimum-support completion could not place {residual:.6g} of "
            "declared mass without violating the zero-diagonal constraint; "
            "the residual is reported, not redistributed"
        )
    return EstimatedNetwork(
        node_ids=nodes,
        liabilities=matrix,
        method="minimum_density_greedy",
        marginal_residual=residual,
        marginal_mismatch=mismatch,
        iterations=0,
        uncertainty=(
            "minimum-support completion of declared aggregate marginals: the "
            "concentrated corner of the structural uncertainty the marginals "
            "leave open, not a measurement of bilateral exposures"
        ),
        notes=tuple(notes),
    )


def posterior_draws(
    network: EstimatedNetwork,
    *,
    n_draws: int = 64,
    concentration: float = 1.0,
    rng: Optional[np.random.Generator] = None,
    max_iterations: int = 2000,
    tolerance: float = 1e-8,
) -> Tuple[EstimatedNetwork, ...]:
    """Draw marginal-preserving structural completions around an estimate.

    Mechanism, per draw: every positive cell of ``network`` is multiplied by
    a Dirichlet weight (mean one, dispersion ``concentration``), and the
    perturbed matrix is RAS-reconciled back to the *declared* row and column
    totals. ``concentration`` large collapses the draws onto the point
    estimate; the default (1.0) is the flat Bayesian bootstrap.

    What the draws are, and are not
    -------------------------------

    They span the completions of the declared aggregates that the point
    estimate's support can express -- the structural uncertainty the
    marginals leave open. They are not sampling error of the aggregates
    (those are treated as declared facts) and not a posterior from a
    generative model of the banking system. Propagating clearing over them
    answers "how much does the loss distribution depend on the unknown
    bilateral structure, given these totals?" and nothing stronger.

    Raises:
        ValueError: ``n_draws < 1`` or ``concentration <= 0``.
    """
    if n_draws < 1:
        raise ValueError("n_draws must be at least 1")
    if concentration <= 0:
        raise ValueError("concentration must be positive")

    generator = rng if rng is not None else np.random.default_rng()
    base = network.liabilities
    support = base > 0
    if not support.any():
        raise ValueError("the estimated network has no positive cells to resample")

    row_target = base.sum(axis=1)
    col_target = base.sum(axis=0)
    scale = float(min(row_target.sum(), col_target.sum()))
    alpha = np.full(int(support.sum()), float(concentration))
    k = alpha.size

    draws = []
    for _ in range(int(n_draws)):
        weights = generator.dirichlet(alpha) * k
        draw = base.copy()
        draw[support] *= weights
        np.fill_diagonal(draw, 0.0)
        draw, residual, _used = _ras_reconcile(
            draw,
            row_target,
            col_target,
            max_iterations=max_iterations,
            tolerance=tolerance,
            scale=scale,
            prune=False,
        )
        draws.append(draw)
    return tuple(draws)


@dataclass(frozen=True)
class ClearingUncertainty:
    """Clearing outcomes over the point estimate and the structural draws."""

    node_ids: Tuple[str, ...]
    endowment_ratio: float
    shocks: Mapping[str, float]
    percentiles: Tuple[float, ...]
    n_draws: int
    point: Dict[str, object]
    bands: Dict[str, Dict[str, float]]
    shortfall_draws: np.ndarray
    uncertainty: str
    notes: Sequence[str] = field(default_factory=tuple)


def _declared_endowments(
    network: EstimatedNetwork,
    *,
    endowment_ratio: float,
    shocks: Optional[Mapping[str, float]],
) -> np.ndarray:
    """Endowments are declared, then damaged by the declared shock.

    ``endowment_ratio`` scales each institution's external assets against its
    interbank obligations (the operator's buffer assumption); ``shocks``
    destroys a declared fraction of each named institution's endowment
    before clearing. Nothing here is estimated.
    """
    if not 0 < endowment_ratio <= 1:
        raise ValueError("endowment_ratio must be in (0, 1]")
    obligations = network.liabilities.sum(axis=1)
    endowments = obligations * float(endowment_ratio)
    if shocks:
        known = set(network.node_ids)
        unknown = set(shocks) - known
        if unknown:
            raise ValueError(f"shocks declared for unknown institutions: {sorted(unknown)}")
        for name, fraction in shocks.items():
            fraction = float(fraction)
            if not 0.0 <= fraction <= 1.0:
                raise ValueError(f"shock fraction for {name} must be in [0, 1]")
            index = network.node_ids.index(name)
            endowments[index] *= 1.0 - fraction
    return endowments


def _summarise(result: ClearingResult) -> Dict[str, object]:
    return {
        "total_shortfall": result.total_shortfall,
        "n_defaults": result.n_defaults,
        "defaulted": [
            result.node_ids[i] for i in range(len(result.node_ids)) if result.defaulted[i]
        ],
        "converged": bool(result.converged),
    }


def propagate_estimation_uncertainty(
    network: EstimatedNetwork,
    *,
    endowment_ratio: float = 0.10,
    shocks: Optional[Mapping[str, float]] = None,
    n_draws: int = 64,
    concentration: float = 1.0,
    rng: Optional[np.random.Generator] = None,
    percentiles: Sequence[float] = (5.0, 50.0, 95.0),
) -> ClearingUncertainty:
    """Clear the point estimate and every structural draw; report bands.

    The declared shock (a fraction of each named institution's endowment
    destroyed) is applied identically to the point estimate and to every
    draw, so the spread across draws is *purely* the unknown bilateral
    structure -- the thing the marginals do not pin down.

    Returns a :class:`ClearingUncertainty` whose ``bands`` carry the requested
    percentiles of total shortfall and default count across draws, alongside
    the point-estimate outcome. The uncertainty string travels with the
    result: these are bands over completions of declared aggregates, not
    confidence intervals for a measured network.

    Raises:
        ValueError: invalid ratio/shocks (see :func:`build_clearing_inputs`),
            ``n_draws < 1``, or an empty percentile list.
    """
    if n_draws < 1:
        raise ValueError("n_draws must be at least 1")
    pcts = tuple(float(p) for p in percentiles)
    if not pcts or any(not 0.0 <= p <= 100.0 for p in pcts):
        raise ValueError("percentiles must be non-empty and within [0, 100]")

    endowments = _declared_endowments(
        network, endowment_ratio=endowment_ratio, shocks=shocks
    )
    point = sequential_clearing(
        network.liabilities, endowments, node_ids=network.node_ids
    )

    notes = list(network.notes)
    draws = posterior_draws(
        network,
        n_draws=n_draws,
        concentration=concentration,
        rng=rng,
    )
    shortfalls = np.empty(len(draws))
    defaults = np.empty(len(draws))
    unconverged = 0
    for index, draw in enumerate(draws):
        result = sequential_clearing(draw, endowments, node_ids=network.node_ids)
        shortfalls[index] = result.total_shortfall
        defaults[index] = result.n_defaults
        if not result.converged:
            unconverged += 1
    if unconverged:
        notes.append(
            f"{unconverged} of {len(draws)} draw clearings did not converge; "
            "their outcomes are included as computed and flagged here"
        )

    bands = {
        "total_shortfall": {
            f"p{p:g}": float(np.percentile(shortfalls, p)) for p in pcts
        },
        "n_defaults": {
            f"p{p:g}": float(np.percentile(defaults, p)) for p in pcts
        },
    }
    return ClearingUncertainty(
        node_ids=network.node_ids,
        endowment_ratio=float(endowment_ratio),
        shocks=dict(shocks or {}),
        percentiles=pcts,
        n_draws=len(draws),
        point=_summarise(point),
        bands=bands,
        shortfall_draws=shortfalls,
        uncertainty=(
            "clearing bands over marginal-preserving structural draws of an "
            "estimated network: they measure sensitivity to the unknown "
            "bilateral structure given the declared aggregates, not "
            "statistical confidence in a measured network; "
            + network.uncertainty
        ),
        notes=tuple(notes),
    )


def build_clearing_inputs(
    network: EstimatedNetwork,
    *,
    endowment_ratio: float = 0.10,
) -> Tuple[np.ndarray, np.ndarray]:
    """Turn an estimated network into clearing-engine inputs.

    Endowments are declared, not estimated: each institution's external
    assets are ``endowment_ratio`` times its total interbank obligations --
    an operator-chosen capital/liquidity buffer, stated in the result rather
    than discovered.
    """
    if not 0 < endowment_ratio <= 1:
        raise ValueError("endowment_ratio must be in (0, 1]")
    obligations = network.liabilities.sum(axis=1)
    endowments = obligations * float(endowment_ratio)
    return network.liabilities, endowments
