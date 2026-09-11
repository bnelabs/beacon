"""Tests for persistent homology of the liquidity network.

The invariants here have known values, so they are checked against those rather
than against the implementation: a cycle has ``beta_1 = 1``, a tree has 0, and the
connectivity threshold is the bottleneck of a *minimum* spanning tree -- which is
independently recomputed by brute force in the tests, because it is the quantity an
earlier version silently got wrong by building the maximum spanning tree instead.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from backend.modules.engine.multiplex import MultiplexLayer, RelationKind
from backend.modules.engine.persistent_homology import (
    UnionFind,
    betti_curve,
    betti_numbers,
    connected_components,
    connectivity_threshold,
    largest_component_fraction,
    merge_levels,
    multiplex_signature,
    topological_signature,
)


def graph(n: int, edges, weight: float = 1.0) -> np.ndarray:
    matrix = np.zeros((n, n), dtype=float)
    for a, b in edges:
        matrix[a, b] = matrix[b, a] = weight
    return matrix


def ring(n: int, weight: float = 1.0) -> np.ndarray:
    return graph(n, [(i, (i + 1) % n) for i in range(n)], weight)


class TestUnionFind:
    def test_starts_fully_disjoint(self):
        forest = UnionFind(4)
        assert forest.n_components == 4
        assert len(set(forest.find(i) for i in range(4))) == 4

    def test_union_merges_and_reports_novelty(self):
        forest = UnionFind(3)
        assert forest.union(0, 1) is True
        assert forest.n_components == 2
        # Merging again is a no-op, which is how cycles are detected.
        assert forest.union(0, 1) is False
        assert forest.n_components == 2

    def test_transitivity(self):
        forest = UnionFind(4)
        forest.union(0, 1)
        forest.union(1, 2)
        assert forest.find(0) == forest.find(2)
        assert forest.n_components == 2

    def test_component_sizes(self):
        forest = UnionFind(5)
        forest.union(0, 1)
        forest.union(1, 2)
        sizes = sorted(forest.sizes().values())
        assert sizes == [1, 1, 3]

    def test_long_chain_does_not_recurse(self):
        # Path compression is iterative; a recursive implementation exhausts the
        # stack on a chain this long.
        forest = UnionFind(5_000)
        for node in range(4_999):
            forest.union(node, node + 1)
        assert forest.n_components == 1

    def test_negative_size_is_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            UnionFind(-1)


class TestBettiNumbers:
    @pytest.mark.parametrize(
        "name,matrix,expected",
        [
            ("three isolated nodes", graph(3, []), (3, 0)),
            ("path of three (a tree)", graph(3, [(0, 1), (1, 2)]), (1, 0)),
            ("triangle (one cycle)", graph(3, [(0, 1), (1, 2), (0, 2)]), (1, 1)),
            ("square (one cycle)", graph(4, [(0, 1), (1, 2), (2, 3), (3, 0)]), (1, 1)),
            (
                "two disjoint triangles",
                graph(6, [(0, 1), (1, 2), (0, 2), (3, 4), (4, 5), (3, 5)]),
                (2, 2),
            ),
            (
                "K4 complete",
                graph(4, [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]),
                (1, 3),
            ),
        ],
    )
    def test_known_graphs(self, name, matrix, expected):
        assert betti_numbers(matrix) == expected, name

    def test_absolute_edges_are_not_relations(self):
        """A zero entry is an absent edge, not a weak one.

        An earlier version tested only ``weight >= threshold``, which admitted
        every absent pair once the threshold reached zero, silently completing any
        graph and reporting a single connected component with a large cycle rank.
        """
        sparse = graph(5, [(0, 1)])
        beta_0, beta_1 = betti_numbers(sparse, 0.0)
        assert beta_0 == 4  # 0-1 joined, three isolated
        assert beta_1 == 0

    def test_cycle_rank_matches_the_identity(self):
        # beta_1 = E - V + beta_0 for any graph.
        matrix = graph(5, [(0, 1), (1, 2), (2, 0), (2, 3), (3, 4)])
        n = matrix.shape[0]
        edges = int(np.count_nonzero(np.triu(matrix, k=1) > 0))
        beta_0, beta_1 = betti_numbers(matrix)
        assert beta_1 == edges - n + beta_0

    def test_threshold_excludes_weak_relations(self):
        matrix = np.zeros((3, 3))
        matrix[0, 1] = matrix[1, 0] = 5.0
        matrix[1, 2] = matrix[2, 1] = 1.0

        assert betti_numbers(matrix, 0.0) == (1, 0)
        # At 5 the weak edge is gone, leaving 0-1 and an isolated node 2.
        assert betti_numbers(matrix, 5.0) == (2, 0)

    def test_a_directed_exposure_matrix_is_symmetrised_by_maximum(self):
        """Netting would erase a relation between banks that owe each other.

        Max of the two directions answers "is there a relation at all", which is
        what connectivity means here.
        """
        matrix = np.zeros((2, 2))
        matrix[0, 1] = 5.0  # 0 owes 1; 1 owes 0 nothing
        assert betti_numbers(matrix) == (1, 0)

    def test_validation(self):
        with pytest.raises(ValueError, match="square"):
            betti_numbers(np.zeros((2, 3)))
        with pytest.raises(ValueError, match="no nodes"):
            betti_numbers(np.zeros((0, 0)))
        with pytest.raises(ValueError, match="non-finite"):
            betti_numbers(np.array([[0.0, np.nan], [np.nan, 0.0]]))
        with pytest.raises(ValueError, match="negative"):
            betti_numbers(np.array([[0.0, -1.0], [-1.0, 0.0]]))
        with pytest.raises(ValueError, match="threshold"):
            betti_numbers(graph(2, [(0, 1)]), float("nan"))


class TestComponents:
    def test_components_are_grouped_correctly(self):
        matrix = graph(5, [(0, 1), (2, 3)])
        assert connected_components(matrix) == [[0, 1], [2, 3], [4]]

    def test_largest_component_fraction(self):
        matrix = graph(6, [(0, 1), (1, 2), (0, 2), (3, 4), (4, 5), (3, 5)])
        assert largest_component_fraction(matrix) == pytest.approx(0.5)

    def test_a_connected_network_is_entirely_one_component(self):
        assert largest_component_fraction(ring(8)) == pytest.approx(1.0)


class TestConnectivityThreshold:
    def test_matches_a_hand_computed_filtration(self):
        """The hand-computed case, then every threshold checked by brute force.

        The graph is 0-1 (weight 5), 1-2 (3), 0-2 (1). Keeping edges of weight
        >= t stays connected down to t = 3, through the path 0-1-2; at t = 4 only
        the 5-edge survives and node 2 is isolated. So the largest surviving
        threshold is 3, which here equals both the lightest edge of the maximum
        spanning tree and the heaviest of the minimum one -- a coincidence that the
        tree case below breaks.
        """
        matrix = np.zeros((3, 3))
        matrix[0, 1] = matrix[1, 0] = 5.0
        matrix[1, 2] = matrix[2, 1] = 3.0
        matrix[0, 2] = matrix[2, 0] = 1.0

        assert connectivity_threshold(matrix) == pytest.approx(3.0)

        # Brute force: the LARGEST level at which the kept graph is still
        # connected. Raising the level removes edges, so connectivity holds up to
        # a maximum and fails beyond it -- the minimum would trivially be the
        # lowest edge weight, since keeping everything connects everything.
        weights = sorted({5.0, 3.0, 1.0})
        brute = max(
            level for level in weights if betti_numbers(matrix, level)[0] == 1
        )
        assert brute == pytest.approx(3.0)
        assert connectivity_threshold(matrix) == pytest.approx(brute)

    def test_brute_force_agreement_on_random_graphs(self):
        rng = np.random.default_rng(20260501)
        for _ in range(30):
            n = int(rng.integers(3, 9))
            raw = rng.random((n, n))
            matrix = np.triu(raw, k=1)
            matrix = matrix + matrix.T
            # Guarantee connectivity so the brute-force minimum is well defined.
            for node in range(n - 1):
                matrix[node, node + 1] = matrix[node + 1, node] = 1.0

            expected = max(
                level
                for level in np.unique(matrix[matrix > 0])
                if betti_numbers(matrix, float(level))[0] == 1
            )
            assert connectivity_threshold(matrix) == pytest.approx(float(expected))

    def test_an_edgeless_graph_is_never_connected(self):
        # Reported as inf rather than substituted with a large finite number,
        # which would read as "very fragile but connected".
        assert connectivity_threshold(np.zeros((4, 4))) == float("inf")

    def test_a_single_node_is_trivially_connected(self):
        assert connectivity_threshold(np.zeros((1, 1))) == pytest.approx(0.0)

    def test_a_strongly_connected_ring_needs_only_a_weak_edge(self):
        # All edges equal: the binding relation is exactly that weight.
        assert connectivity_threshold(ring(6, weight=2.5)) == pytest.approx(2.5)


class TestFiltration:
    def test_merge_levels_are_descending(self):
        matrix = graph(4, [(0, 1)], 5.0)
        matrix[1, 2] = matrix[2, 1] = 3.0
        matrix[2, 3] = matrix[3, 2] = 1.0
        levels = merge_levels(matrix)
        assert levels == sorted(levels, reverse=True)
        assert levels == [5.0, 3.0, 1.0]

    def test_a_connected_graph_has_n_minus_one_merges(self):
        assert len(merge_levels(ring(7))) == 6

    def test_a_disconnected_graph_has_fewer(self):
        # Two components of two: only two merges are possible.
        matrix = graph(4, [(0, 1), (2, 3)])
        assert len(merge_levels(matrix)) == 2

    def test_betti_curve_reports_every_level(self):
        curve = betti_curve(ring(6), thresholds=[0.0, 0.5, 1.0])
        assert len(curve) == 3
        assert curve[0]["beta_0"] == 1
        assert curve[0]["beta_1"] == 1
        # The threshold comparison is inclusive, so 1.0 keeps every edge; above
        # that nothing survives and each node is its own component.
        assert betti_curve(ring(6), thresholds=[1.5])[0]["beta_0"] == 6
        for point in curve:
            json.dumps(point, allow_nan=False)

    def test_betti_curve_default_sweep_is_descending_and_finite(self):
        curve = betti_curve(ring(6, weight=100.0))
        thresholds = [point["threshold"] for point in curve]
        assert thresholds == sorted(thresholds, reverse=True)
        assert all(math.isfinite(value) for value in thresholds)

    def test_curve_validation(self):
        with pytest.raises(ValueError, match="thresholds must be finite"):
            betti_curve(ring(4), thresholds=[1.0, float("inf")])


class TestFragmentationProgression:
    def test_redundancy_is_lost_before_the_network_fragments(self):
        """The plan's claim, made testable.

        Removing edges from a ring, the first removal destroys the cycle -- beta_1
        falls from 1 to 0 -- while the network remains a single connected path,
        beta_0 still 1. Fragmentation only begins on the next removal. So the loss
        of *redundancy* is observable strictly before the loss of *connectivity*,
        which is what makes a topological signal earlier than one that watches for
        the network to break.
        """
        base = ring(6)
        no_cycle = base.copy()
        no_cycle[0, 1] = no_cycle[1, 0] = 0.0

        intact = topological_signature(base, reference="zero")
        thinned = topological_signature(no_cycle, reference="zero")

        assert intact.beta_1 == 1 and intact.beta_0 == 1
        assert thinned.beta_1 == 0
        assert thinned.beta_0 == 1, "connectivity must survive the first removal"
        assert thinned.redundancy < intact.redundancy

    def test_fragmentation_rises_as_edges_are_removed(self):
        fragmentations = []
        for removed in range(0, 5):
            matrix = ring(6)
            for index in range(removed):
                matrix[index, (index + 1) % 6] = 0.0
                matrix[(index + 1) % 6, index] = 0.0
            fragmentations.append(topological_signature(matrix, reference="zero").fragmentation)

        assert fragmentations == sorted(fragmentations)
        assert fragmentations[0] == pytest.approx(0.0)
        assert fragmentations[-1] > 0.0

    def test_beta_0_climbs_as_the_ring_breaks(self):
        counts = []
        for removed in range(0, 4):
            matrix = ring(6)
            for index in range(removed):
                matrix[index, (index + 1) % 6] = 0.0
                matrix[(index + 1) % 6, index] = 0.0
            counts.append(betti_numbers(matrix)[0])
        assert counts == sorted(counts)
        assert counts[-1] > counts[0]


class TestSignature:
    def test_connectivity_ratio_is_one_for_a_ring(self):
        # Every edge is equally strong, so holding the network together requires
        # exactly the strongest relation available.
        signature = topological_signature(ring(6, weight=3.0), reference="zero")
        assert signature.connectivity_ratio == pytest.approx(1.0)

    def test_a_strong_relation_does_not_by_itself_raise_the_threshold(self):
        """The threshold is set by the weakest relation the structure needs.

        Here 0-1 carries weight 100, but node 1 also reaches the network through
        1-2 (weight 1), so the heavy edge is redundant and the binding relation is
        a weak one -- the ratio is 0.01. This is what makes the ratio informative:
        it does not rise just because one relation is large.
        """
        matrix = np.zeros((4, 4))
        matrix[0, 1] = matrix[1, 0] = 100.0  # strong but redundant
        matrix[0, 2] = matrix[2, 0] = 1.0
        matrix[1, 2] = matrix[2, 1] = 1.0
        matrix[0, 3] = matrix[3, 0] = 1.0

        signature = topological_signature(matrix, reference="zero")
        assert signature.connectivity_threshold == pytest.approx(1.0)
        assert signature.connectivity_ratio == pytest.approx(0.01)

    def test_a_tree_is_limited_by_its_weakest_edge(self):
        """For a tree the binding relation is the weakest one, not the strongest.

        A star with spokes 100, 1 and 1 stays connected for every threshold up to
        1, because all three edges survive there; above 1 the two weak spokes drop
        out and leaves 2 and 3 isolated. The heavy spoke never sets the threshold --
        it only raises the maximum the ratio is measured against.
        """
        matrix = np.zeros((4, 4))
        matrix[0, 1] = matrix[1, 0] = 100.0
        matrix[0, 2] = matrix[2, 0] = 1.0
        matrix[0, 3] = matrix[3, 0] = 1.0

        signature = topological_signature(matrix, reference="zero")
        assert signature.connectivity_threshold == pytest.approx(1.0)
        assert signature.connectivity_ratio == pytest.approx(0.01)

    def test_infinite_connectivity_is_reported_as_none_in_json(self):
        signature = topological_signature(np.zeros((4, 4)))
        payload = signature.to_dict()
        # A disconnected-everywhere network must not serialise as a large finite
        # ratio, which a reader would take for "fragile but intact".
        assert payload["connectivity_threshold"] is None
        assert payload["connectivity_ratio"] is None
        json.dumps(payload, allow_nan=False)

    def test_signature_serialises(self):
        json.dumps(topological_signature(ring(5)).to_dict(), allow_nan=False)

    def test_summary_reads_sensibly(self):
        text = topological_signature(ring(6), reference="zero").summary()
        assert "connected" in text
        assert "cycle" in text

    def test_reference_levels_are_distinct(self):
        matrix = graph(3, [(0, 1)], 10.0)
        matrix[1, 2] = matrix[2, 1] = 1.0

        at_median = topological_signature(matrix, reference="median")
        at_max = topological_signature(matrix, reference="max")
        at_zero = topological_signature(matrix, reference="zero")

        assert at_max.threshold == pytest.approx(10.0)
        assert at_median.threshold == pytest.approx(5.5)
        assert at_zero.threshold == pytest.approx(0.0)

    def test_explicit_threshold_overrides_the_reference(self):
        signature = topological_signature(ring(4), threshold=0.5, reference="max")
        assert signature.threshold == pytest.approx(0.5)
        assert signature.reference == "explicit"

    def test_validation(self):
        with pytest.raises(ValueError, match="reference"):
            topological_signature(ring(4), reference="nonsense")
        with pytest.raises(ValueError, match="threshold"):
            topological_signature(ring(4), threshold=-1.0)


class TestMultiplexSignature:
    def _layer(self, matrix, name, kind=RelationKind.EXPOSURE):
        return MultiplexLayer(
            name=name,
            kind=kind,
            adjacency=np.asarray(matrix, dtype=float),
            node_ids=tuple(f"N{i}" for i in range(matrix.shape[0])),
            as_of=pd.Timestamp("2024-01-01"),
            directed=False,
        )

    def test_two_weak_layers_pool_into_a_strong_relation_under_sum(self):
        first = np.zeros((2, 2))
        first[0, 1] = first[1, 0] = 0.4
        second = np.zeros((2, 2))
        second[0, 1] = second[1, 0] = 0.4

        pooled = multiplex_signature([self._layer(first, "a"), self._layer(second, "b")],
                                     combine="sum", reference="zero")
        assert pooled.n_edges == 1
        assert pooled.max_edge_weight == pytest.approx(0.8)

    def test_max_pooling_keeps_the_strongest_single_relation(self):
        first = np.zeros((2, 2))
        first[0, 1] = first[1, 0] = 0.4
        second = np.zeros((2, 2))
        second[0, 1] = second[1, 0] = 0.9

        pooled = multiplex_signature([self._layer(first, "a"), self._layer(second, "b")],
                                     combine="max", reference="zero")
        assert pooled.max_edge_weight == pytest.approx(0.9)

    def test_layers_of_different_sizes_are_rejected(self):
        small = np.zeros((2, 2))
        large = np.zeros((3, 3))
        with pytest.raises(ValueError, match="node count"):
            multiplex_signature([self._layer(small, "a"), self._layer(large, "b")])

    def test_empty_and_invalid_combine_are_rejected(self):
        with pytest.raises(ValueError, match="at least one layer"):
            multiplex_signature([])
        with pytest.raises(ValueError, match="combine"):
            multiplex_signature([self._layer(np.zeros((2, 2)), "a")], combine="mean")

    def test_weights_scale_a_named_layer(self):
        matrix = np.zeros((2, 2))
        matrix[0, 1] = matrix[1, 0] = 1.0
        pooled = multiplex_signature(
            [self._layer(matrix, "a")], combine="sum", reference="zero", weights={"a": 3.0}
        )
        assert pooled.max_edge_weight == pytest.approx(3.0)


class TestDeterminism:
    def test_repeated_signatures_are_identical(self):
        matrix = ring(8)
        first = topological_signature(matrix)
        second = topological_signature(matrix)
        assert first.to_dict() == second.to_dict()

    def test_merge_levels_are_stable(self):
        matrix = ring(8)
        assert merge_levels(matrix) == merge_levels(matrix)
