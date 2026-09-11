"""Multiplex sequential clearing -- the Eisenberg-Noe fixed point.

Why this module exists
----------------------

It replaces ``NetworkExplainer``, which computed contagion as::

    shock     = min(exposure / 1e9, 0.5)
    new_risk  = current_risk + shock
    if new_risk >= 0.8: bank fails

That is not a model of default. Three things were wrong with it:

1. **Risk scores were added to risk scores.** A bank's distress was assumed to
   increase linearly with the *gross* exposure of its failed counterparties,
   regardless of the failed bank's capital. A counterparty with no equity left
   and one with equity covering its book transmitted identically.

2. **The ``/ 1e9`` divisor is a scale constant, not economics.** It converts
   dollars into "risk units" so the number lands in ``[0, 1]``. The failure
   threshold ``0.8`` was then calibrated against that arbitrary scale, so the
   threshold has no meaning independent of the unit of account.

3. **No conservation law.** Payments were never tracked. A bank could "fail"
   having paid nothing, while its creditors absorbed no loss -- so losses were
   never accounted for and could not propagate correctly. There was no balance
   sheet, so there was nothing to conserve.

The Eisenberg-Noe (2001) clearing vector is the standard alternative. It is a
fixed point of a monotone map, so it exists, is unique as the greatest fixed
point, and is computable by iteration. It conserves payments by construction and
derives default from the balance sheet rather than from a rescaled score.

The formulation
---------------

Let bank ``i`` have exogenous assets ``e_i`` (its endowment: liquid assets it
holds before any interbank settlement) and nominal liabilities ``L[i, j]`` owed
to ``j``. Write

    l_i = sum_j L[i, j]            total nominal liabilities of i
    Pi[j, i] = L[j, i] / l_j       i's claim on j as a share of j's liabilities

A clearing vector ``p`` is any fixed point of

    Phi(p)_i = min( l_i , e_i + sum_j Pi[j, i] * p_j )                        (1)

The min is limited liability: a bank can never pay more than its resources, and
never more than it owes. ``Phi`` is monotone and bounded above by ``l``, so
iterating from ``p^0 = l`` decreases monotonically to the greatest fixed point
``p*`` (Tarski). The greatest fixed point is the economically correct one: it is
the clearing that pays creditors as much as the balance sheet permits.

Multiplex extension
-------------------

Liabilities are partitioned into layers, each with a seniority rank -- secured
funding and CCP variation margin rank above unsecured wholesale funding, which
ranks above equity-like claims. Receipts are pooled across all layers (a bank
cannot spend a repayment it has not received), then allocated to layers in
seniority order::

    resources_i = e_i + sum_m sum_j Pi_m[j, i] * p_m[j]
    p_m[i]      = min( l_m[i], max(0, resources_i - sum_{s < m} p_s[i]) )

This preserves absolute priority *across layers* while keeping limited liability
at the level of the bank's total balance sheet. The same monotone-decrease
argument applies, so the multipartite fixed point exists and iteration converges
to the greatest one.

Default classification
----------------------

Two economically distinct failures are separated, because the policy response
differs:

* **Insolvency** -- the bank fails even if every counterparty pays in full.
  Its endowment plus the full value of its claims is below its liabilities:
  ``e_i + sum_j (L[j,i] / l_j) * l_j - l_i < 0``. Since ``l_j`` cancels, this is
  ``e_i + sum_j L[j, i] - l_i < 0``: assets below liabilities on a mark-to-book
  basis. Failure here is fundamental, not contagion.
* **Illiquidity** -- the bank is solvent if all counterparties pay, but fails on
  realised receipts because they did not. Failure here is transmitted.

The distinction matters: a solvent-but-illiquid bank should be recapitalised by
discount-window lending, whereas an insolvent one cannot be saved by liquidity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "NetworkLayer",
    "ClearingResult",
    "DefaultEvent",
    "ContagionEdge",
    "MultiplexClearingEngine",
    "clear_multiplex",
    "sequential_clearing",
    "DEFAULT_TOLERANCE",
]

DEFAULT_TOLERANCE = 1e-10
DEFAULT_MAX_ITERATIONS = 10_000

CAUSE_INSOLVENCY = "insolvency"
CAUSE_ILLIQUIDITY = "illiquidity"


@dataclass(frozen=True)
class NetworkLayer:
    """One relation in the multiplex.

    Attributes:
        name: Layer identifier, e.g. ``"secured"`` or ``"unsecured"``.
        liabilities: ``(n, n)`` matrix where ``liabilities[i, j]`` is what ``i``
            owes ``j`` *in this layer*.
        seniority: Lower values are paid first. Ties are paid pro rata (both
            are capped by the same remaining resources).
    """

    name: str
    liabilities: np.ndarray
    seniority: int = 0

    def __post_init__(self) -> None:
        matrix = np.asarray(self.liabilities, dtype=float)
        if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
            raise ValueError(
                f"Layer {self.name!r} liabilities must be a square matrix, "
                f"got shape {matrix.shape}"
            )
        if not np.all(np.isfinite(matrix)):
            raise ValueError(f"Layer {self.name!r} contains non-finite liabilities")
        if np.any(matrix < 0):
            raise ValueError(f"Layer {self.name!r} contains negative liabilities")
        object.__setattr__(self, "liabilities", matrix)

    @property
    def n_nodes(self) -> int:
        return int(self.liabilities.shape[0])

    def nominal_liabilities(self) -> np.ndarray:
        """``l_i``: total owed by each node within this layer."""
        return self.liabilities.sum(axis=1)


@dataclass(frozen=True)
class DefaultEvent:
    """A node entering default at a specific round of the cascade."""

    round: int
    node: int
    node_id: str
    cause: str
    shortfall: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "round": self.round,
            "node": self.node,
            "node_id": self.node_id,
            "cause": self.cause,
            "shortfall": self.shortfall,
        }


@dataclass(frozen=True)
class ContagionEdge:
    """A realised transmission of loss from a defaulter to a creditor."""

    round: int
    source: int
    source_id: str
    target: int
    target_id: str
    layer: str
    nominal: float
    loss: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "round": self.round,
            "source": self.source,
            "source_id": self.source_id,
            "target": self.target,
            "target_id": self.target_id,
            "layer": self.layer,
            "nominal": self.nominal,
            "loss": self.loss,
        }


@dataclass
class ClearingResult:
    """Outcome of a multiplex clearing computation."""

    payments: np.ndarray
    """``(n,)`` total paid by each node across all layers."""

    layer_payments: Dict[str, np.ndarray]
    """Per-layer ``(n,)`` payment vectors."""

    nominal_liabilities: np.ndarray
    """``(n,)`` total owed by each node."""

    resources: np.ndarray
    """``(n,)`` endowment plus realised interbank receipts."""

    equity: np.ndarray
    """``(n,)`` resources minus liabilities. Negative means insolvent."""

    endowments: np.ndarray

    defaulted: np.ndarray
    """``(n,)`` boolean mask of nodes that failed to pay in full."""

    causes: Dict[int, str]
    """node index -> ``insolvency`` or ``illiquidity``."""

    default_rounds: List[List[int]]
    """Nodes that defaulted at each round, in cascade order."""

    contagion_edges: List[ContagionEdge]

    losses_by_creditor: np.ndarray
    """``(n,)`` total shortfall borne by each node as a creditor."""

    node_ids: List[str]

    iterations: int
    converged: bool
    tolerance: float

    @property
    def n_defaults(self) -> int:
        return int(self.defaulted.sum())

    @property
    def total_shortfall(self) -> float:
        return float((self.nominal_liabilities - self.payments).sum())

    def default_sequence(self) -> List[str]:
        """Node ids in cascade order, flattened across rounds."""
        return [self.node_ids[i] for rnd in self.default_rounds for i in rnd]

    def to_dict(self) -> Dict[str, object]:
        return {
            "n_nodes": int(self.payments.shape[0]),
            "n_defaults": self.n_defaults,
            "total_shortfall": self.total_shortfall,
            "converged": self.converged,
            "iterations": self.iterations,
            "default_sequence": self.default_sequence(),
            "default_rounds": [
                [self.node_ids[i] for i in rnd] for rnd in self.default_rounds
            ],
            "causes": {
                self.node_ids[i]: cause for i, cause in sorted(self.causes.items())
            },
            "contagion_edges": [edge.to_dict() for edge in self.contagion_edges],
            "payments": {
                self.node_ids[i]: float(self.payments[i])
                for i in range(len(self.node_ids))
            },
            "equity": {
                self.node_ids[i]: float(self.equity[i])
                for i in range(len(self.node_ids))
            },
        }


def _as_square(matrix: np.ndarray, name: str) -> np.ndarray:
    arr = np.asarray(matrix, dtype=float)
    if arr.ndim != 2 or arr.shape[0] != arr.shape[1]:
        raise ValueError(f"{name} must be square, got shape {arr.shape}")
    return arr


def _validate_endowments(endowments: np.ndarray, n: int) -> np.ndarray:
    arr = np.asarray(endowments, dtype=float).reshape(-1)
    if arr.shape[0] != n:
        raise ValueError(
            f"endowments has length {arr.shape[0]} but the network has {n} nodes"
        )
    if not np.all(np.isfinite(arr)):
        raise ValueError("endowments contains non-finite values")
    if np.any(arr < 0):
        raise ValueError("endowments must be non-negative")
    return arr


def _recovery_ratios(payments: np.ndarray, nominal: np.ndarray) -> np.ndarray:
    """``p_j / l_j`` per node, with ``0`` where nothing is owed.

    A node owing nothing is not in default; it simply has no claim to scale.
    """
    ratios = np.zeros_like(nominal, dtype=float)
    np.divide(payments, nominal, out=ratios, where=nominal > 0)
    return np.clip(ratios, 0.0, 1.0)


def _allocate_by_seniority(
    resources: np.ndarray,
    layer_nominals: Sequence[Tuple[str, np.ndarray, int]],
) -> Dict[str, np.ndarray]:
    """Split each node's resources across layers in seniority order.

    ``layer_nominals`` is ``(name, nominal, seniority)`` already sorted by
    increasing seniority rank (most senior first).

    Layers sharing a rank are *pari passu* and share the resources available at
    that rank in proportion to their claims. Paying them in declaration order
    instead would let the order of the input list decide which equally-senior
    creditor is made whole -- an arbitrary input detail determining a payment.
    """
    payments: Dict[str, np.ndarray] = {}
    remaining = np.maximum(resources, 0.0)

    index = 0
    total = len(layer_nominals)
    while index < total:
        rank = layer_nominals[index][2]
        group = []
        while index < total and layer_nominals[index][2] == rank:
            group.append(layer_nominals[index])
            index += 1

        group_nominal = np.sum([nominal for _, nominal, _ in group], axis=0)
        # Resources available to this rank, never more than the claims on it.
        distributable = np.minimum(group_nominal, remaining)
        scales = np.divide(
            distributable,
            group_nominal,
            out=np.zeros_like(distributable, dtype=float),
            where=group_nominal > 0,
        )

        for name, nominal, _ in group:
            pay = np.minimum(nominal, nominal * scales)
            payments[name] = pay

        remaining = remaining - distributable

    return payments


class MultiplexClearingEngine:
    """Computes the greatest fixed point of the multiplex clearing map.

    Args:
        layers: Network layers. If empty, the network has no interbank
            liabilities and every node simply pays what its endowment allows.
        node_ids: Optional labels. Defaults to ``node_0``, ``node_1``, ...
        tolerance: Convergence tolerance on the sup-norm change in payments.
        max_iterations: Hard cap on iterations before declaring non-convergence.
    """

    def __init__(
        self,
        layers: Sequence[NetworkLayer],
        node_ids: Optional[Sequence[str]] = None,
        tolerance: float = DEFAULT_TOLERANCE,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
    ) -> None:
        self.layers: List[NetworkLayer] = list(layers)
        self.tolerance = float(tolerance)
        self.max_iterations = int(max_iterations)

        if self.layers:
            sizes = {layer.n_nodes for layer in self.layers}
            if len(sizes) != 1:
                raise ValueError(
                    f"all layers must share a node count, got {sorted(sizes)}"
                )
            self.n_nodes = sizes.pop()
        else:
            self.n_nodes = len(node_ids) if node_ids is not None else 0

        if self.n_nodes == 0:
            raise ValueError("a clearing network needs at least one node")

        if node_ids is None:
            node_ids = [f"node_{i}" for i in range(self.n_nodes)]
        if len(node_ids) != self.n_nodes:
            raise ValueError(
                f"node_ids has length {len(node_ids)} but the network has "
                f"{self.n_nodes} nodes"
            )
        self.node_ids = [str(x) for x in node_ids]

        # Most senior first; stable so equal ranks keep declaration order.
        self._ordered_layers = sorted(
            self.layers, key=lambda layer: layer.seniority
        )

    def _nominal_by_layer(self) -> List[Tuple[str, np.ndarray, int]]:
        return [
            (layer.name, layer.nominal_liabilities(), layer.seniority)
            for layer in self._ordered_layers
        ]

    def _aggregate_nominal(self) -> np.ndarray:
        total = np.zeros(self.n_nodes, dtype=float)
        for layer in self.layers:
            total += layer.nominal_liabilities()
        return total

    def _apply_map(
        self,
        payments: Dict[str, np.ndarray],
        endowments: np.ndarray,
        layer_nominals: Sequence[Tuple[str, np.ndarray, int]],
    ) -> Tuple[Dict[str, np.ndarray], np.ndarray]:
        """One application of the clearing map ``Phi`` (equation 1, multiplex).

        Receipts are pooled across layers, then allocated by seniority.
        """
        receipts = np.zeros(self.n_nodes, dtype=float)
        for layer in self._ordered_layers:
            nominal = layer.nominal_liabilities()
            ratios = _recovery_ratios(payments[layer.name], nominal)
            # Creditor i receives L[j, i] * (p_j / l_j), summed over debtors j.
            receipts += layer.liabilities.T @ ratios

        resources = endowments + receipts
        new_payments = _allocate_by_seniority(resources, layer_nominals)
        return new_payments, resources

    def clear(
        self,
        endowments: Sequence[float],
        *,
        record_edges: bool = True,
    ) -> ClearingResult:
        """Run the sequential clearing algorithm.

        Iterating ``Phi`` from full payment is the fictitious-default algorithm:
        each round reveals the nodes that cannot meet their obligations given the
        payments realised so far. The rounds are therefore the propagation order.
        """
        endowments_arr = _validate_endowments(np.asarray(endowments), self.n_nodes)
        layer_nominals = self._nominal_by_layer()
        nominal_total = self._aggregate_nominal()

        # p^0 = l : everyone is assumed to pay in full, then revised downward.
        payments: Dict[str, np.ndarray] = {
            name: nominal.copy() for name, nominal, _ in layer_nominals
        }

        # Solvency is judged on the balance sheet with all claims honoured --
        # the endowment plus the *full* face value of every claim.
        claims_at_par = np.zeros(self.n_nodes, dtype=float)
        for layer in self.layers:
            claims_at_par += layer.liabilities.T @ np.ones(self.n_nodes)
        solvent_at_par = (endowments_arr + claims_at_par) >= (nominal_total - self.tolerance)

        defaulted = np.zeros(self.n_nodes, dtype=bool)
        default_rounds: List[List[int]] = []
        causes: Dict[int, str] = {}
        round_of: Dict[int, int] = {}
        edges: List[ContagionEdge] = []

        iterations = 0
        converged = False
        previous_payments = payments

        for iteration in range(1, self.max_iterations + 1):
            iterations = iteration
            payments, resources = self._apply_map(
                previous_payments, endowments_arr, layer_nominals
            )

            current_paid = self._total_paid(payments, layer_nominals)
            previous_paid = self._total_paid(previous_payments, layer_nominals)
            delta = float(np.max(np.abs(current_paid - previous_paid)))

            # A node defaults in the first round where it cannot meet its
            # nominal obligations given the payments realised so far. Recording
            # that first round is what yields the cascade order.
            shortfall = nominal_total - current_paid
            newly_defaulted = [
                i
                for i in range(self.n_nodes)
                if shortfall[i] > self.tolerance and not defaulted[i]
            ]

            if newly_defaulted:
                for i in newly_defaulted:
                    defaulted[i] = True
                    causes[i] = (
                        CAUSE_INSOLVENCY if not solvent_at_par[i] else CAUSE_ILLIQUIDITY
                    )
                    round_of[i] = len(default_rounds) + 1

                if record_edges:
                    edges.extend(
                        self._contagion_edges_for_round(
                            newly_defaulted,
                            previous_payments,
                            payments,
                            round_of,
                        )
                    )
                default_rounds.append(newly_defaulted)

            previous_payments = payments

            # Iterate to the fixed point rather than stopping at the last new
            # default. An already-defaulted node's payment keeps falling as its
            # own debtors fall, so halting at the last *new* default would
            # return a vector that is not yet the clearing vector.
            if delta <= self.tolerance:
                converged = True
                break

        total_paid = self._total_paid(payments, layer_nominals)
        receipts = resources - endowments_arr
        equity = resources - nominal_total

        return ClearingResult(
            payments=total_paid,
            layer_payments={name: vec.copy() for name, vec in payments.items()},
            nominal_liabilities=nominal_total,
            resources=resources,
            equity=equity,
            endowments=endowments_arr,
            defaulted=defaulted,
            causes=causes,
            default_rounds=default_rounds,
            contagion_edges=edges,
            losses_by_creditor=self._losses_by_creditor(layer_nominals, payments),
            node_ids=list(self.node_ids),
            iterations=iterations,
            converged=converged,
            tolerance=self.tolerance,
        )

    def _total_paid(
        self,
        payments: Dict[str, np.ndarray],
        layer_nominals: Sequence[Tuple[str, np.ndarray, int]],
    ) -> np.ndarray:
        total = np.zeros(self.n_nodes, dtype=float)
        for name, _, _ in layer_nominals:
            total = total + payments[name]
        return total

    def _losses_by_creditor(
        self,
        layer_nominals: Sequence[Tuple[str, np.ndarray, int]],
        payments: Dict[str, np.ndarray],
    ) -> np.ndarray:
        """How much each node loses on its claims, summed across layers."""
        losses = np.zeros(self.n_nodes, dtype=float)
        for layer in self.layers:
            nominal = layer.nominal_liabilities()
            ratios = _recovery_ratios(payments[layer.name], nominal)
            shortfall_ratio = 1.0 - ratios
            # Loss to creditor i is L[j, i] * (1 - p_j / l_j), summed over j.
            losses += layer.liabilities.T @ shortfall_ratio
        return losses

    def _contagion_edges_for_round(
        self,
        newly_defaulted: Sequence[int],
        previous_payments: Dict[str, np.ndarray],
        current_payments: Dict[str, np.ndarray],
        round_of: Dict[int, int],
    ) -> List[ContagionEdge]:
        """Edges along which this round's defaults destroyed creditor value."""
        edges: List[ContagionEdge] = []
        for layer in self.layers:
            nominal = layer.nominal_liabilities()
            before = _recovery_ratios(previous_payments[layer.name], nominal)
            after = _recovery_ratios(current_payments[layer.name], nominal)
            deterioration = np.maximum(before - after, 0.0)
            for source in newly_defaulted:
                if nominal[source] <= 0:
                    continue
                creditors = np.nonzero(layer.liabilities[source] > 0)[0]
                for target in creditors:
                    loss = float(
                        layer.liabilities[source, target] * deterioration[source]
                    )
                    if loss <= self.tolerance:
                        continue
                    edges.append(
                        ContagionEdge(
                            round=round_of[source],
                            source=int(source),
                            source_id=self.node_ids[source],
                            target=int(target),
                            target_id=self.node_ids[target],
                            layer=layer.name,
                            nominal=float(layer.liabilities[source, target]),
                            loss=loss,
                        )
                    )
        return edges


def clear_multiplex(
    layers: Sequence[NetworkLayer],
    endowments: Sequence[float],
    *,
    node_ids: Optional[Sequence[str]] = None,
    tolerance: float = DEFAULT_TOLERANCE,
) -> ClearingResult:
    """Convenience wrapper: clear a multiplex network in one call."""
    engine = MultiplexClearingEngine(
        layers, node_ids=node_ids, tolerance=tolerance
    )
    return engine.clear(endowments)


def sequential_clearing(
    liabilities: np.ndarray,
    endowments: Sequence[float],
    *,
    node_ids: Optional[Sequence[str]] = None,
    tolerance: float = DEFAULT_TOLERANCE,
) -> ClearingResult:
    """Single-layer Eisenberg-Noe clearing.

    Provided because the single-layer case is the reference implementation the
    multiplex result must reduce to; tests assert exactly that.
    """
    matrix = _as_square(np.asarray(liabilities), "liabilities")
    layer = NetworkLayer(name="interbank", liabilities=matrix, seniority=0)
    return clear_multiplex(
        [layer], endowments, node_ids=node_ids, tolerance=tolerance
    )
