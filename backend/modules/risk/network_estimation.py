"""Bilateral exposure estimation from aggregate totals (maximum entropy).

Why this module exists
----------------------

The clearing and fire-sale engines are only as useful as the networks they
run on, and real bilateral interbank matrices are rarely public. What IS
public for many jurisdictions (FDIC call reports, ECB supervisory data) is
each institution's *aggregate* interbank assets and liabilities. The
standard, literature-standard way to turn those marginals into a bilateral
matrix is the **maximum-entropy estimator**: the matrix with the given row
and column sums that assumes no other structure -- i.e. the least-informative
completion consistent with the data.

Honesty contract
----------------

* The estimator invents no totals: row and column sums reproduce the declared
  aggregates (up to the zero-diagonal reconciliation), and the declared
  aggregates are the only input.
* The zero-diagonal constraint (no bank lends to itself) breaks the exact
  marginals; a bounded RAS iteration restores them and the residual is
  reported, never hidden.
* When aggregate assets and liabilities disagree (they often do, across
  reporting populations), the matrix is scaled to the smaller total and the
  discrepancy is reported as ``marginal_mismatch`` -- the operator sees how
  much of the system was unbalanced before any modelling.
* Every result carries ``method`` and ``uncertainty`` strings: a
  maximum-entropy matrix is a prior, not a measurement. Downstream clearing
  results inherit that caveat and the module says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Sequence, Tuple

import numpy as np

__all__ = ["EstimatedNetwork", "estimate_bilateral_matrix"]


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
        "maximum-entropy completion of declared aggregate marginals: a "
        "least-informative prior, not a measurement of bilateral exposures; "
        "clearing results inherit this caveat"
    )
    notes: Sequence[str] = field(default_factory=tuple)

    def row_sums(self) -> np.ndarray:
        return self.liabilities.sum(axis=1)

    def col_sums(self) -> np.ndarray:
        return self.liabilities.sum(axis=0)


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
    nodes = sorted(set(interbank_assets) | set(interbank_liabilities))
    if len(nodes) < 2:
        raise ValueError("a bilateral network needs at least two institutions")

    assets = np.array([max(0.0, float(interbank_assets.get(n, 0.0))) for n in nodes])
    liabs = np.array([max(0.0, float(interbank_liabilities.get(n, 0.0))) for n in nodes])

    notes = []
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

    # Maximum-entropy (independence) prior: X_ij proportional to liab_i * asset_j.
    matrix = np.outer(liabs, assets)
    denom = assets.sum()
    if denom > 0:
        matrix = matrix / denom
    np.fill_diagonal(matrix, 0.0)

    # RAS iteration restores the marginals broken by the zero diagonal.
    # Degenerate supports (entries that must be exactly zero) make plain RAS
    # limit-cycle, so an outer loop thresholds numerically-dead entries and
    # refits on the reduced support -- the standard fix, and the residual is
    # reported either way.
    row_target = liabs
    col_target = assets

    def _ras(matrix: np.ndarray, iterations: int) -> tuple[np.ndarray, float, int]:
        used = 0
        residual = np.inf
        for used in range(1, iterations + 1):
            row_sums = matrix.sum(axis=1)
            row_factor = np.where(row_sums > 0, row_target / np.where(row_sums > 0, row_sums, 1.0), 0.0)
            matrix = matrix * row_factor[:, None]
            col_sums = matrix.sum(axis=0)
            col_factor = np.where(col_sums > 0, col_target / np.where(col_sums > 0, col_sums, 1.0), 0.0)
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
        if not dead.any() or residual <= tolerance:
            break
        matrix[dead] = 0.0
    iterations = total_used

    matrix = np.where(matrix > 0, matrix, 0.0)
    return EstimatedNetwork(
        node_ids=tuple(nodes),
        liabilities=matrix,
        marginal_residual=residual,
        marginal_mismatch=mismatch,
        iterations=iterations,
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
