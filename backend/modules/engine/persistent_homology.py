"""Persistent homology of the liquidity network.

What TDA is doing here, and what it is not
------------------------------------------

The claim this module is built to support is that the *shape* of the interbank
network degrades before its node-level statistics do. That is a claim about
structure, not about levels: a network can have unchanged average exposure and
unchanged volatility while the paths between its members quietly collapse, so that
a shock which would previously have been absorbed across many routes now has only
one route to travel. Persistent homology is the tool for measuring that, because it
counts connectivity and redundancy rather than magnitudes.

Two invariants carry the interpretation:

* **beta-0**, the number of connected components. Above one, the network has
  fragmented into groups that cannot pass stress to each other at all.
* **beta-1**, the number of independent cycles, or *cycle rank*. Each independent
  cycle is a redundant route: a shock reaching a node inside a cycle has more than
  one way onward. When beta-1 falls while beta-0 holds, the network has not
  broken apart but has lost its redundancy -- it is thinner without being
  disconnected, which is precisely the condition that is invisible in the summary
  statistics.

Both are computed exactly on the graph's 1-skeleton. ``beta_1 = E - V + beta_0``
for any graph, and this module uses that identity rather than a simplex-wise
reduction, because a graph has no higher simplices to reduce over.

The honest limit: **this is not full persistent homology.** A complete
implementation builds a simplicial complex, computes boundary operators and
reduces them to obtain persistence pairs in every dimension, which is what makes
higher-dimensional holes (voids enclosed by triangles) visible. What is here is
the 1-dimensional case -- connectivity and cycles -- plus the H0 filtration
recorded as merge levels. That is enough for fragmentation and redundancy, and
those are the two things the plan asks for, but a reader who knows the term
"persistent homology" will expect higher simplices and should be told they are
absent rather than left to discover it.

The filtration
--------------

A network is not a graph but a *weighted* graph, and the interesting question is
what happens as the relation strength changes. So the graph is filtered by weight:
``G(t)`` keeps edges of weight at least ``t``. As ``t`` falls from the strongest
edge to zero, edges appear, components merge, and cycles close. Recording the
weights at which components merge gives the single-linkage dendrogram, whose
largest value is the **connectivity threshold** -- the strongest relation the
network needs in order to hold together at all. A network that only connects
through its single strongest edge is fragile no matter how many edges it has.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

__all__ = [
    "TopologicalSignature",
    "UnionFind",
    "betti_numbers",
    "connected_components",
    "largest_component_fraction",
    "cycle_rank",
    "merge_levels",
    "connectivity_threshold",
    "betti_curve",
    "topological_signature",
    "multiplex_signature",
]

DEFAULT_TOLERANCE = 1e-12


class UnionFind:
    """Disjoint-set forest with path compression and union by size.

    Path compression is iterative rather than recursive: a long chain of merges
    would otherwise exhaust the recursion limit on a large network, which is the
    kind of failure that only appears at scale.
    """

    def __init__(self, n: int) -> None:
        if n < 0:
            raise ValueError(f"n must be non-negative, got {n}")
        self._parent = list(range(n))
        self._size = [1] * n
        self.n_components = n

    def find(self, node: int) -> int:
        root = node
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[node] != root:
            self._parent[node], node = root, self._parent[node]
        return root

    def union(self, left: int, right: int) -> bool:
        """Merge two sets. Returns True if they were separate."""
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left == root_right:
            return False
        if self._size[root_left] < self._size[root_right]:
            root_left, root_right = root_right, root_left
        self._parent[root_right] = root_left
        self._size[root_left] += self._size[root_right]
        self.n_components -= 1
        return True

    def component_of(self, node: int) -> int:
        return self.find(node)

    def sizes(self) -> Dict[int, int]:
        sizes: Dict[int, int] = {}
        for node in range(len(self._parent)):
            root = self.find(node)
            sizes[root] = sizes.get(root, 0) + 1
        return sizes


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------

def _as_adjacency(adjacency: Any) -> np.ndarray:
    """Accept a matrix or a multiplex layer, and symmetrise a directed one.

    Betti numbers of the 1-skeleton are defined on an undirected graph. A
    directed exposure matrix is symmetrised by taking the maximum of the two
    directions, which answers "is there a relation between these two at all"
    without letting the direction cancel it out -- a netting convention would
    report no relation between two banks that owe each other heavily.
    """
    from backend.modules.engine.multiplex import MultiplexLayer

    if isinstance(adjacency, MultiplexLayer):
        matrix = np.asarray(adjacency.adjacency, dtype=float)
    else:
        matrix = np.asarray(adjacency, dtype=float)

    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError(f"adjacency must be square, got shape {matrix.shape}")
    if matrix.shape[0] == 0:
        raise ValueError("adjacency has no nodes")
    if not np.all(np.isfinite(matrix)):
        raise ValueError("adjacency contains non-finite values")
    if np.any(matrix < 0):
        raise ValueError("adjacency contains negative weights")

    symmetric = np.maximum(matrix, matrix.T)
    np.fill_diagonal(symmetric, 0.0)
    return symmetric


def _edges(adjacency: np.ndarray, threshold: float) -> List[Tuple[int, int, float]]:
    """Present edges at or above ``threshold``, as ``(u, v, weight)`` with ``u < v``.

    Presence and strength are separate conditions and must be tested separately. A
    zero entry means the relation *does not exist*; it is not a relation of
    strength zero. Testing only ``weight >= threshold`` would admit every absent
    pair once the threshold reached zero, silently completing the graph and
    reporting a fully connected network with a large cycle rank for any input.
    """
    upper = np.triu(adjacency, k=1)
    rows, columns = np.nonzero((upper > 0) & (upper >= threshold))
    return [
        (int(row), int(column), float(adjacency[row, column]))
        for row, column in zip(rows, columns)
    ]


# ---------------------------------------------------------------------------
# Betti numbers
# ---------------------------------------------------------------------------

def connected_components(adjacency: Any, threshold: float = 0.0) -> List[List[int]]:
    """Components of the graph after keeping edges of weight at least ``threshold``."""
    matrix = _as_adjacency(adjacency)
    if not math.isfinite(threshold):
        raise ValueError(f"threshold must be finite, got {threshold}")

    n = matrix.shape[0]
    forest = UnionFind(n)
    for u, v, _weight in _edges(matrix, threshold):
        forest.union(u, v)

    groups: Dict[int, List[int]] = {}
    for node in range(n):
        groups.setdefault(forest.find(node), []).append(node)
    return [sorted(group) for group in sorted(groups.values(), key=lambda g: g[0])]


def betti_numbers(adjacency: Any, threshold: float = 0.0) -> Tuple[int, int]:
    """``(beta_0, beta_1)`` of the graph at ``threshold``.

    ``beta_1`` uses the identity ``E - V + beta_0`` for the 1-skeleton rather than
    a boundary-matrix reduction. They agree on graphs -- there are no 2-simplices
    to contribute -- and the identity is exact, so no approximation is involved.
    """
    matrix = _as_adjacency(adjacency)
    if not math.isfinite(threshold):
        # A NaN threshold compares false against everything, so it would silently
        # drop every edge and report a fully disconnected network rather than
        # failing.
        raise ValueError(f"threshold must be finite, got {threshold}")
    n = matrix.shape[0]
    edges = _edges(matrix, threshold)

    forest = UnionFind(n)
    for u, v, _weight in edges:
        forest.union(u, v)

    beta_0 = forest.n_components
    beta_1 = len(edges) - n + beta_0
    return int(beta_0), int(max(beta_1, 0))


def cycle_rank(adjacency: Any, threshold: float = 0.0) -> int:
    """Number of independent cycles: the network's route redundancy."""
    return betti_numbers(adjacency, threshold)[1]


def largest_component_fraction(adjacency: Any, threshold: float = 0.0) -> float:
    """Share of nodes in the biggest component, in ``(0, 1]``."""
    components = connected_components(adjacency, threshold)
    total = sum(len(group) for group in components)
    if total == 0:
        return 0.0
    return float(max(len(group) for group in components) / total)


# ---------------------------------------------------------------------------
# Filtration
# ---------------------------------------------------------------------------

def merge_levels(adjacency: Any) -> List[float]:
    """Weights at which components merge, in descending order.

    Blocks are added strongest-first, so a component that merges at a high weight
    is held together by a strong relation and one that merges only at a low weight
    is barely attached. The result is the single-linkage dendrogram of the
    network: for a connected graph of ``n`` nodes there are exactly ``n - 1``
    merges, and the smallest of them is the weakest link the structure depends on.
    """
    matrix = _as_adjacency(adjacency)
    n = matrix.shape[0]
    edges = sorted(_edges(matrix, 0.0), key=lambda item: -item[2])

    forest = UnionFind(n)
    levels: List[float] = []
    for u, v, weight in edges:
        if forest.union(u, v):
            levels.append(weight)
        if len(levels) == n - 1:
            # A spanning structure now exists; further edges only close cycles and
            # cannot merge anything.
            break
    return levels


def connectivity_threshold(adjacency: Any) -> float:
    """Strongest uniform bar ``t`` under which keeping edges of weight ``>= t`` connects.

    Raising ``t`` deletes weak relations, so connectivity survives up to some
    largest threshold and fails beyond it. That largest surviving threshold is the
    answer.

    It is the LIGHTEST edge on a *maximum* spanning tree, not the heaviest edge on
    a minimum one. The two are different quantities and it is easy to reach for the
    wrong one: for a tree the answer is simply its weakest edge, since keeping only
    edges above that disconnects the tree, while the heaviest edge is irrelevant
    because everything weaker is still present. Equivalently, edges are added
    strongest-first until the nodes are connected and the weight of the edge that
    finally joined them is reported -- a Kruskal pass in descending order.

    Adding strongest-first would compute the bottleneck of the *maximum* spanning
    tree, which is a different number and answers a different question -- how
    strong the surviving relations are, rather than how weak the binding relation
    can be. An earlier version made exactly that substitution.

    Returns ``inf`` when the graph is disconnected at every threshold, including
    when it has no edges at all, because no finite bar connects it.
    """
    matrix = _as_adjacency(adjacency)
    n = matrix.shape[0]
    if n == 1:
        return 0.0

    forest = UnionFind(n)
    # Descending: strongest relations first, so the edge that finally connects the
    # graph is the weakest one the structure can rely on. An ascending pass would
    # compute the minimum spanning tree's heaviest edge, which is a different
    # number (see the docstring).
    edges = sorted(_edges(matrix, 0.0), key=lambda item: -item[2])
    needed = n - 1
    joined = 0
    for u, v, weight in edges:
        if forest.union(u, v):
            joined += 1
            if joined == needed:
                return float(weight)
    return float("inf")


def betti_curve(
    adjacency: Any, thresholds: Optional[Sequence[float]] = None
) -> List[Dict[str, float]]:
    """``(beta_0, beta_1)`` at each threshold, for plotting or tracking."""
    matrix = _as_adjacency(adjacency)
    if thresholds is None:
        # A geometric sweep from the strongest edge down to zero, since edge
        # weights in a financial network span orders of magnitude.
        positive = matrix[matrix > 0]
        if positive.size == 0:
            thresholds = [0.0]
        else:
            hi = float(positive.max())
            thresholds = [hi * (10.0 ** -exponent) for exponent in np.linspace(0, 6, 25)]

    curve: List[Dict[str, float]] = []
    for level in thresholds:
        if not math.isfinite(level):
            raise ValueError(f"thresholds must be finite, got {level}")
        beta_0, beta_1 = betti_numbers(matrix, level)
        curve.append(
            {
                "threshold": float(level),
                "beta_0": beta_0,
                "beta_1": beta_1,
                "largest_component_fraction": largest_component_fraction(matrix, level),
            }
        )
    return curve


# ---------------------------------------------------------------------------
# Signature
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TopologicalSignature:
    """A summary of the network's shape at a chosen reference threshold."""

    n_nodes: int
    n_edges: int
    threshold: float
    beta_0: int
    beta_1: int
    largest_component_fraction: float
    connectivity_threshold: float
    max_edge_weight: float
    reference: str

    @property
    def fragmentation(self) -> float:
        """Share of nodes outside the largest component.

        Zero when the network is whole, rising towards one as it breaks apart.
        """
        return float(1.0 - self.largest_component_fraction)

    @property
    def connectivity_ratio(self) -> float:
        """How strong the spanning relation must be, relative to the strongest.

        ``1.0`` means the network only holds together through its single strongest
        edge, so removing that one relation fragments it. Small values mean many
        relations are individually strong enough to span the graph. ``inf`` when
        the network is disconnected at every threshold.
        """
        if not math.isfinite(self.connectivity_threshold):
            return float("inf")
        if self.max_edge_weight <= 0:
            return 0.0
        return float(self.connectivity_threshold / self.max_edge_weight)

    @property
    def redundancy(self) -> float:
        """Independent cycles per node: spare routes through the network."""
        if self.n_nodes <= 1:
            return 0.0
        return float(self.beta_1 / self.n_nodes)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_nodes": int(self.n_nodes),
            "n_edges": int(self.n_edges),
            "threshold": float(self.threshold),
            "reference": self.reference,
            "beta_0": int(self.beta_0),
            "beta_1": int(self.beta_1),
            "largest_component_fraction": float(self.largest_component_fraction),
            "fragmentation": self.fragmentation,
            "connectivity_threshold": (
                None
                if not math.isfinite(self.connectivity_threshold)
                else float(self.connectivity_threshold)
            ),
            "connectivity_ratio": (
                None if not math.isfinite(self.connectivity_ratio) else self.connectivity_ratio
            ),
            "redundancy": self.redundancy,
            "max_edge_weight": float(self.max_edge_weight),
        }

    def summary(self) -> str:
        if self.beta_0 == 1:
            connectivity = "the network is connected"
        else:
            connectivity = f"the network is split into {self.beta_0} components"
        return (
            f"{connectivity} with {self.beta_1} independent cycle(s) at "
            f"threshold {self.threshold:.6g}; {self.fragmentation:.1%} of nodes lie "
            f"outside the largest component"
        )


def _reference_threshold(
    matrix: np.ndarray, reference: str, explicit: Optional[float]
) -> float:
    if explicit is not None:
        if not math.isfinite(explicit) or explicit < 0:
            raise ValueError(f"threshold must be finite and non-negative, got {explicit}")
        return float(explicit)

    positive = matrix[matrix > 0]
    if positive.size == 0:
        return 0.0

    if reference == "max":
        return float(positive.max())
    if reference == "median":
        return float(np.median(positive))
    if reference == "zero":
        return 0.0
    raise ValueError(
        f"reference must be one of 'max', 'median', 'zero', got {reference!r}"
    )


def topological_signature(
    adjacency: Any,
    *,
    threshold: Optional[float] = None,
    reference: str = "median",
) -> TopologicalSignature:
    """Summarise a network's shape.

    Args:
        adjacency: A square weight matrix, or a multiplex layer.
        threshold: Explicit filtration level. When omitted, ``reference`` chooses.
        reference: ``'median'`` (default, the level of a typical relation),
            ``'max'`` (only the strongest relations survive) or ``'zero'`` (the
            whole network).

    Returns:
        A :class:`TopologicalSignature`. ``connectivity_threshold`` is ``inf`` when
        no threshold connects the network, which is reported rather than
        substituted with a large finite number.
    """
    matrix = _as_adjacency(adjacency)
    level = _reference_threshold(matrix, reference, threshold)

    beta_0, beta_1 = betti_numbers(matrix, level)
    positive = matrix[matrix > 0]

    return TopologicalSignature(
        n_nodes=int(matrix.shape[0]),
        n_edges=len(_edges(matrix, level)),
        threshold=level,
        beta_0=beta_0,
        beta_1=beta_1,
        largest_component_fraction=largest_component_fraction(matrix, level),
        connectivity_threshold=connectivity_threshold(matrix),
        max_edge_weight=float(positive.max()) if positive.size else 0.0,
        reference=reference if threshold is None else "explicit",
    )


def multiplex_signature(
    layers: Sequence[Any],
    *,
    threshold: Optional[float] = None,
    reference: str = "median",
    combine: str = "sum",
    weights: Optional[Mapping[str, float]] = None,
) -> TopologicalSignature:
    """Shape of a multiplex, pooling its layers into one weighted graph.

    Pooling is a modelling choice and is stated rather than hidden: ``'sum'``
    treats two weak relations across layers as comparable to one strong one, while
    ``'max'`` insists a relation be strong within a single layer. Neither is
    correct in general, so the caller picks and the choice is recorded.

    Merging is only meaningful because layers carry a ``RelationKind``: a
    co-movement layer pooled with an exposure layer would produce a graph whose
    edges are half obligation and half correlation, which no downstream clearing
    could interpret. Callers wanting that must do it deliberately.
    """
    from backend.modules.engine.multiplex import MultiplexLayer

    layer_list = list(layers)
    if not layer_list:
        raise ValueError("multiplex_signature needs at least one layer")
    if combine not in ("sum", "max"):
        raise ValueError(f"combine must be 'sum' or 'max', got {combine!r}")

    first = _as_adjacency(layer_list[0])
    n = first.shape[0]
    pooled = np.zeros((n, n), dtype=float)

    for layer in layer_list:
        matrix = _as_adjacency(layer)
        if matrix.shape[0] != n:
            raise ValueError(
                "all layers must share a node count; got "
                f"{sorted({_as_adjacency(item).shape[0] for item in layer_list})}"
            )
        if weights is not None and isinstance(layer, MultiplexLayer):
            matrix = matrix * float(weights.get(layer.name, 1.0))
        pooled = pooled + matrix if combine == "sum" else np.maximum(pooled, matrix)

    np.fill_diagonal(pooled, 0.0)
    return topological_signature(pooled, threshold=threshold, reference=reference)
