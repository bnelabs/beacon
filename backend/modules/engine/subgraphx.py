"""SubgraphX: subgraph attribution for graph-based predictions.

Why a subgraph rather than a feature score
------------------------------------------

Phase 1 deleted a hand-rolled attribution routine that computed
``gradient * input * attention``, normalised it, and called the result SHAP. It
was removed rather than repaired because the quantity had no guarantee attached:
no efficiency, symmetry, dummy or additivity property, and no defined objective.
A per-feature scalar is also the wrong object for a network model, where what
matters is *which institutions together* produced the risk, not which column of a
feature matrix was large.

SubgraphX (Yuan et al., 2021) answers the question the domain actually asks: find
the small, connected subgraph whose presence accounts for the prediction. The
example from the plan -- "the specific triad of Bank A, Hedge Fund B and the
EUR/USD swap rate" -- is a subgraph, and this module returns one.

Two pieces, both with verifiable properties
-------------------------------------------

**A game-theoretic score.** The explainer treats nodes as players in a
cooperative game whose value ``v(S)`` is a caller-supplied function of the
induced subgraph -- for BEACON that is naturally the clearing shortfall computed
on the subnetwork, which makes the explanation denominated in the same units as
the risk it explains. Coalitions are scored by their Shapley value, which is the
unique allocation satisfying efficiency, symmetry, dummy-player and additivity.
Those four axioms are tested, so the score is not merely plausible arithmetic: on
a game with a hand-computable answer it returns that answer.

**Monte Carlo tree search.** Finding the highest-scoring connected subgraph is
combinatorial, so the explainer runs MCTS with UCT selection, expanding one node
at a time and scoring rollouts by the coalition's Shapley value. Search is
restricted to the ``k``-hop neighbourhood of the target node, which is both the
receptive field any message-passing model can see and the pruning that makes the
search tractable.

Honest cost and limits
----------------------

Shapley values are exponential in the number of players, so the coalition score
is estimated by permutation sampling rather than computed exactly above a few
players. It is therefore an estimate, and ``n_samples`` controls its variance;
the returned object reports how many samples were used. MCTS gives no optimality
guarantee either -- a larger budget finds an equal or better subgraph, which is
what the tests check, but not necessarily the best.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np

logger = logging.getLogger(__name__)

__all__ = [
    "SubgraphExplanation",
    "SubgraphExplainer",
    "coalition_shapley_value",
    "exact_shapley_values",
    "monte_carlo_shapley_values",
    "k_hop_neighborhood",
    "connected_edges",
]

EXACT_ENUMERATION_LIMIT = 14


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------

def k_hop_neighborhood(adjacency: np.ndarray, target: int, depth: int) -> Set[int]:
    """Nodes within ``depth`` hops of ``target``, including the target.

    This is the receptive field of a message-passing model of that depth, and the
    bound inside which the search is allowed to move. Restricting to it is not an
    approximation of the model -- a deeper subgraph cannot influence the target's
    representation, so searching outside it would spend budget on nodes that
    cannot matter.
    """
    matrix = np.asarray(adjacency, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError(f"adjacency must be square, got {matrix.shape}")
    if not 0 <= target < matrix.shape[0]:
        raise ValueError(f"target {target} is outside a {matrix.shape[0]}-node graph")
    if depth < 0:
        raise ValueError(f"depth must be non-negative, got {depth}")

    reachable = {target}
    frontier = [target]
    for _ in range(depth):
        next_frontier = []
        for node in frontier:
            neighbours = np.nonzero(matrix[node] > 0)[0]
            for neighbour in neighbours:
                index = int(neighbour)
                if index not in reachable:
                    reachable.add(index)
                    next_frontier.append(index)
        frontier = next_frontier
        if not frontier:
            break
    return reachable


def connected_edges(adjacency: np.ndarray, nodes: Iterable[int]) -> Tuple[Tuple[int, int], ...]:
    """Edges of the subgraph induced by ``nodes``, as ordered index pairs."""
    matrix = np.asarray(adjacency, dtype=float)
    selected = sorted(set(int(node) for node in nodes))
    edges: List[Tuple[int, int]] = []
    for position, source in enumerate(selected):
        for target in selected[position + 1:]:
            if matrix[source, target] > 0 or matrix[target, source] > 0:
                edges.append((source, target))
    return tuple(edges)


def _is_connected(adjacency: np.ndarray, nodes: Set[int]) -> bool:
    if not nodes:
        return False
    matrix = np.asarray(adjacency, dtype=float)
    start = next(iter(nodes))
    seen = {start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for neighbour in np.nonzero(matrix[node] > 0)[0]:
            index = int(neighbour)
            if index in nodes and index not in seen:
                seen.add(index)
                queue.append(index)
    return seen == nodes


# ---------------------------------------------------------------------------
# Shapley values
# ---------------------------------------------------------------------------

def _as_players(players: Sequence[Any]) -> List[Any]:
    ordered = list(players)
    if not ordered:
        raise ValueError("players is empty; a game needs at least one")
    if len(set(ordered)) != len(ordered):
        raise ValueError("players contains duplicates")
    return ordered


def _subset_key(subset: Iterable[Any]) -> frozenset:
    return frozenset(subset)


class _CachedValue:
    """Memoised value function.

    MCTS calls the game thousands of times and the same subsets recur, so without
    caching the search is dominated by repeated evaluation of an expensive
    function -- typically run the clearing engine.
    """

    def __init__(self, value_fn: Callable[[frozenset], float]) -> None:
        self._value_fn = value_fn
        self._cache: Dict[frozenset, float] = {}
        self.n_evaluations = 0

    def __call__(self, subset: Iterable[Any]) -> float:
        key = _subset_key(subset)
        if key not in self._cache:
            value = float(self._value_fn(key))
            if not math.isfinite(value):
                raise ValueError(
                    f"value function returned a non-finite value for {sorted(key, key=str)}"
                )
            self._cache[key] = value
            self.n_evaluations += 1
        return self._cache[key]


def exact_shapley_values(
    players: Sequence[Any],
    value_fn: Callable[[frozenset], float],
) -> Dict[Any, float]:
    """Exact Shapley values by enumerating every coalition.

    Exponential in the number of players, so intended for small games and for
    verifying the sampled estimator rather than for production use.
    """
    ordered = _as_players(players)
    n = len(ordered)
    if n > EXACT_ENUMERATION_LIMIT:
        raise ValueError(
            f"exact enumeration over {n} players is refused; the limit is "
            f"{EXACT_ENUMERATION_LIMIT}. Use monte_carlo_shapley_values."
        )

    cached = _CachedValue(value_fn)
    values: Dict[Any, float] = {player: 0.0 for player in ordered}
    others = {player: [other for other in ordered if other != player] for player in ordered}

    for player in ordered:
        total = 0.0
        rest = others[player]
        for mask in range(1 << len(rest)):
            coalition = frozenset(rest[i] for i in range(len(rest)) if mask & (1 << i))
            size = len(coalition)
            # |S|! (n - |S| - 1)! / n!
            weight = math.factorial(size) * math.factorial(n - size - 1) / math.factorial(n)
            total += weight * (cached(coalition | {player}) - cached(coalition))
        values[player] = total
    return values


def monte_carlo_shapley_values(
    players: Sequence[Any],
    value_fn: Callable[[frozenset], float],
    *,
    n_samples: int = 512,
    seed: Optional[int] = None,
) -> Dict[Any, float]:
    """Shapley values estimated from random permutations.

    The permutation estimator: draw an order of the players, credit each player
    with the marginal value of being added at its own position. Averaged over
    permutations this is an unbiased estimate of the Shapley value, and unlike
    exact enumeration its cost does not grow with the coalition space.
    """
    ordered = _as_players(players)
    if n_samples < 1:
        raise ValueError(f"n_samples must be positive, got {n_samples}")

    cached = _CachedValue(value_fn)
    rng = np.random.default_rng(seed)
    totals = {player: 0.0 for player in ordered}

    for _ in range(n_samples):
        permutation = rng.permutation(len(ordered))
        coalition: Set[Any] = set()
        for position in permutation:
            player = ordered[int(position)]
            without = cached(coalition)
            with_player = cached(coalition | {player})
            totals[player] += with_player - without
            coalition.add(player)

    return {player: total / n_samples for player, total in totals.items()}


def coalition_shapley_value(
    coalition: Iterable[Any],
    players: Sequence[Any],
    value_fn: Callable[[frozenset], float],
    *,
    n_samples: int = 256,
    seed: Optional[int] = None,
) -> float:
    """Shapley value of a whole coalition, estimated by permutation sampling.

    The coalition is treated as a single player. For a uniformly random
    permutation of *all* players, ``T`` is the set of players appearing before the
    earliest member of the coalition, and the coalition's contribution is
    ``v(T u S) - v(T)``. For a random permutation the set preceding a fixed
    element is uniformly distributed over the subsets of the other players, so the
    probability of drawing any particular ``T`` is exactly the Shapley coefficient
    ``|T|! (n - |S| - |T|)! / (n - |S| + 1)!``. Averaging over permutations is
    therefore an unbiased estimate of the coalition's Shapley value.

    Permuting only the players outside the coalition and stopping at the first
    change in value is a different and biased estimator -- it stops at the first
    fluctuation instead of averaging over insertion points -- and would overstate
    small coalitions.

    Returns 0.0 for a coalition that is empty or equals the whole player set: with
    nothing to add, the marginal contribution is zero by definition.
    """
    ordered = _as_players(players)
    members = frozenset(coalition)
    if not members:
        return 0.0
    unknown = members - set(ordered)
    if unknown:
        raise ValueError(f"coalition contains players not in the game: {sorted(unknown, key=str)}")

    if len(members) == len(ordered):
        return 0.0
    if n_samples < 1:
        raise ValueError(f"n_samples must be positive, got {n_samples}")

    cached = _CachedValue(value_fn)
    rng = np.random.default_rng(seed)
    total = 0.0
    all_players = ordered
    for _ in range(n_samples):
        # The permutation must span every player, not just those outside the
        # coalition. For a uniformly random permutation the set of players
        # preceding a fixed element is uniform over all subsets of the others,
        # which is exactly the Shapley weighting. Permuting only the outsiders and
        # walking until the value changes is a different, biased estimator: it
        # stops at the first fluctuation rather than averaging over every
        # insertion point, and it inflated a single-player coalition to the full
        # coalition value in testing.
        before: Set[Any] = set()
        for index in rng.permutation(len(all_players)):
            player = all_players[int(index)]
            if player in members:
                break
            before.add(player)
        total += cached(before | members) - cached(before)
    return total / n_samples


# ---------------------------------------------------------------------------
# Explanation record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SubgraphExplanation:
    """The subgraph that accounts for a prediction, with its evidence."""

    target: int
    nodes: Tuple[int, ...]
    node_labels: Tuple[str, ...]
    edges: Tuple[Tuple[int, int], ...]
    score: float
    empty_score: float
    full_score: float
    n_rollouts: int
    n_value_evaluations: int
    shapley_samples: int
    final_samples: int = 0
    search_statistics: Dict[str, Any] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.nodes)

    @property
    def fraction_of_full(self) -> float:
        """Share of the total game value this subgraph accounts for.

        Denominatored against ``v(N) - v(empty)`` rather than ``v(N)`` so that a
        game with a non-zero baseline does not report a misleading ratio.
        """
        denominator = self.full_score - self.empty_score
        if denominator == 0:
            return 0.0
        return float(self.score / denominator)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target": int(self.target),
            "nodes": [int(node) for node in self.nodes],
            "node_labels": list(self.node_labels),
            "edges": [[int(a), int(b)] for a, b in self.edges],
            "size": self.size,
            "score": float(self.score),
            "empty_score": float(self.empty_score),
            "full_score": float(self.full_score),
            "fraction_of_full": self.fraction_of_full,
            "n_rollouts": int(self.n_rollouts),
            "n_value_evaluations": int(self.n_value_evaluations),
            "shapley_samples": int(self.shapley_samples),
            "final_samples": int(self.final_samples),
            "search_statistics": dict(self.search_statistics),
        }

    def summary(self) -> str:
        labels = ", ".join(self.node_labels) if self.node_labels else ", ".join(
            str(node) for node in self.nodes
        )
        return (
            f"Prediction for {self.target} is accounted for by the "
            f"{self.size}-node subgraph {{{labels}}}, carrying "
            f"{self.fraction_of_full:.1%} of the game value "
            f"(score {self.score:.6g} of {self.full_score - self.empty_score:.6g})"
        )


class _SearchNode:
    """One node of the MCTS tree, holding a connected coalition."""

    __slots__ = ("members", "parent", "children", "untried", "visits", "value_sum")

    def __init__(self, members: frozenset, parent: Optional["_SearchNode"]) -> None:
        self.members = members
        self.parent = parent
        self.children: Dict[int, "_SearchNode"] = {}
        self.untried: List[int] = []
        self.visits = 0
        self.value_sum = 0.0

    @property
    def mean_value(self) -> float:
        return self.value_sum / self.visits if self.visits else 0.0


class SubgraphExplainer:
    """MCTS search for the subgraph that best accounts for a prediction.

    Args:
        adjacency: Square matrix; a non-zero entry means the two nodes are linked.
        value_fn: Game value ``v(S) -> float`` for a frozenset of node indices.
            For BEACON this is naturally the clearing shortfall on the induced
            subnetwork, which denominates the explanation in the same units as the
            risk being explained.
        node_labels: Optional display names, aligned to the adjacency index.
        max_size: Largest subgraph the search may return -- the interpretability
            budget, since an explanation covering the whole network explains
            nothing.
        exploration: UCT exploration constant.
        n_rollouts: MCTS budget. Larger finds an equal or better subgraph.
        shapley_samples: Permutation samples used to score each rollout. Kept
            small because it is paid thousands of times.
        final_samples: Permutation samples used to re-score the winning subgraph
            once the search is over. The search retains the best of many noisy
            estimates, so that maximum is biased upward; re-measuring the winner
            at higher fidelity is what makes the reported score trustworthy.
        neighborhood_depth: Hops from the target within which the search moves.
        seed: Seed for the rollout and Shapley sampling, so an explanation is
            reproducible. Attribution that changes between identical runs is not
            auditable.
    """

    def __init__(
        self,
        adjacency: np.ndarray,
        value_fn: Callable[[frozenset], float],
        *,
        node_labels: Optional[Sequence[str]] = None,
        max_size: int = 4,
        exploration: float = math.sqrt(2.0),
        n_rollouts: int = 200,
        shapley_samples: int = 64,
        final_samples: int = 512,
        neighborhood_depth: int = 2,
        seed: Optional[int] = None,
    ) -> None:
        matrix = np.asarray(adjacency, dtype=float)
        if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
            raise ValueError(f"adjacency must be square, got {matrix.shape}")
        if not np.all(np.isfinite(matrix)):
            raise ValueError("adjacency contains non-finite values")
        if np.any(matrix < 0):
            raise ValueError("adjacency contains negative weights")
        if matrix.shape[0] == 0:
            raise ValueError("adjacency has no nodes")
        if max_size < 1:
            raise ValueError(f"max_size must be positive, got {max_size}")
        if n_rollouts < 1:
            raise ValueError(f"n_rollouts must be positive, got {n_rollouts}")
        if shapley_samples < 1:
            raise ValueError(f"shapley_samples must be positive, got {shapley_samples}")
        if final_samples < 1:
            raise ValueError(f"final_samples must be positive, got {final_samples}")
        if exploration <= 0:
            raise ValueError(f"exploration must be positive, got {exploration}")
        if node_labels is not None and len(node_labels) != matrix.shape[0]:
            raise ValueError(
                f"node_labels has {len(node_labels)} entries but the graph has "
                f"{matrix.shape[0]} nodes"
            )

        self.adjacency = matrix
        self.n_nodes = int(matrix.shape[0])
        self.value_fn = value_fn
        self.node_labels = tuple(node_labels) if node_labels is not None else tuple(
            str(index) for index in range(self.n_nodes)
        )
        self.max_size = min(int(max_size), self.n_nodes)
        self.exploration = float(exploration)
        self.n_rollouts = int(n_rollouts)
        self.shapley_samples = int(shapley_samples)
        self.final_samples = int(final_samples)
        self.neighborhood_depth = int(neighborhood_depth)
        self.seed = seed
        self._rng = np.random.default_rng(seed)
        self._cached = _CachedValue(value_fn)

    # -- search ---------------------------------------------------------

    def _neighbours_in(self, node: int, allowed: Set[int]) -> List[int]:
        return [
            int(neighbour)
            for neighbour in np.nonzero(self.adjacency[node] > 0)[0]
            if int(neighbour) in allowed
        ]

    def _untried_for(self, members: frozenset, allowed: Set[int]) -> List[int]:
        """Neighbours outside the coalition, keeping the coalition connected."""
        candidates: Set[int] = set()
        for member in members:
            candidates.update(self._neighbours_in(member, allowed))
        return sorted(candidates - members)

    def _rollout(self, members: frozenset, allowed: Set[int]) -> Tuple[frozenset, float]:
        """Complete a partial coalition and score it, returning both.

        The completed coalition must come back alongside the score. The score
        belongs to the *completed* set, not to the partial one the rollout started
        from, and conflating the two silently records a subgraph whose value was
        never measured -- an earlier version did exactly that and reported a
        two-node subgraph with the triad's score.

        Completion is random rather than greedy: a greedy completion would make
        every rollout from a given state identical, and the search would lose the
        exploration that makes MCTS worthwhile.
        """
        coalition = set(members)
        while len(coalition) < self.max_size:
            candidates = [
                node
                for node in self._untried_for(frozenset(coalition), allowed)
                if _is_connected(self.adjacency, coalition | {node})
            ]
            if not candidates:
                break
            coalition.add(int(self._rng.choice(candidates)))

        score = coalition_shapley_value(
            coalition,
            list(range(self.n_nodes)),
            self._cached,
            n_samples=self.shapley_samples,
            seed=int(self._rng.integers(0, 2**31 - 1)),
        )
        return frozenset(coalition), score

    def explain(self, target: int) -> SubgraphExplanation:
        """Find the subgraph that best accounts for the prediction at ``target``."""
        if not 0 <= target < self.n_nodes:
            raise ValueError(f"target {target} is outside a {self.n_nodes}-node graph")

        allowed = k_hop_neighborhood(self.adjacency, target, self.neighborhood_depth)
        root = _SearchNode(frozenset({target}), None)
        root.untried = self._untried_for(root.members, allowed)

        best_members, best_score = self._rollout(root.members, allowed)

        for _ in range(self.n_rollouts):
            node = root

            # 1. Selection: descend by UCT while fully expanded.
            while not node.untried and node.children:
                node = max(
                    node.children.values(),
                    key=lambda child: child.mean_value
                    + self.exploration
                    * math.sqrt(math.log(max(node.visits, 1)) / max(child.visits, 1)),
                )

            # 2. Expansion: try one untried neighbour.
            if node.untried and len(node.members) < self.max_size:
                action = node.untried.pop(0)
                child_members = node.members | {action}
                child = _SearchNode(child_members, node)
                child.untried = self._untried_for(child_members, allowed)
                node.children[action] = child
                node = child

            # 3. Simulation. The rollout returns the coalition it actually
            #    scored, which is the set that must be recorded if it wins.
            rollout_members, score = self._rollout(node.members, allowed)

            # 4. Backpropagation.
            walker: Optional[_SearchNode] = node
            while walker is not None:
                walker.visits += 1
                walker.value_sum += score
                walker = walker.parent

            if score > best_score:
                best_score = score
                best_members = rollout_members

        empty_key = frozenset()
        full_key = frozenset(range(self.n_nodes))

        # The search kept the best of many noisy estimates, so `best_score` is a
        # maximum and therefore biased upward. Re-measure the winner at higher
        # fidelity so the number that reaches a report is an estimate of the
        # winner's value rather than of how lucky the search got.
        final_score = coalition_shapley_value(
            sorted(best_members),
            list(range(self.n_nodes)),
            self._cached,
            n_samples=self.final_samples,
            seed=int(self._rng.integers(0, 2**31 - 1)),
        )

        return SubgraphExplanation(
            target=int(target),
            nodes=tuple(sorted(best_members)),
            node_labels=tuple(self.node_labels[node] for node in sorted(best_members)),
            edges=connected_edges(self.adjacency, best_members),
            score=float(final_score),
            empty_score=float(self._cached(empty_key)),
            full_score=float(self._cached(full_key)),
            n_rollouts=self.n_rollouts,
            n_value_evaluations=self._cached.n_evaluations,
            shapley_samples=self.shapley_samples,
            final_samples=self.final_samples,
            search_statistics={
                "neighborhood_size": len(allowed),
                "root_visits": root.visits,
                "n_children": len(root.children),
                "max_size": self.max_size,
                "neighborhood_depth": self.neighborhood_depth,
                "exploration": self.exploration,
                "seed": self.seed,
                "search_best_score": float(best_score),
                "final_samples": self.final_samples,
            },
        )


def explain_subgraph(
    adjacency: np.ndarray,
    target: int,
    value_fn: Callable[[frozenset], float],
    **kwargs: Any,
) -> SubgraphExplanation:
    """Convenience wrapper around :class:`SubgraphExplainer`."""
    return SubgraphExplainer(adjacency, value_fn, **kwargs).explain(target)
