"""Tests for full-topology persistence vectorisation.

The point of ``persistence_vectors`` is that long-lived topological features
carry the signal and short-lived ones are noise. Handler-computed examples
(small enough that every landscape tent, every image entry and every diagram
pair is derivable on paper) pin the definitions down; the stability tests then
assert the property the definition exists for. A vectoriser that merely
produced a fixed-width array of plausible numbers would pass neither.

Hand computations used throughout
---------------------------------

Triangle with edge weights 3, 2, 1 (see ``TRIANGLE``): threshold ``t`` keeps
edges of weight ``>= t``. In the ascending coordinate ``s = W_max - t`` with
``W_max = 3`` the merge levels 3 and 2 give H0 pairs ``(0, 0)`` and ``(0, 1)``,
and the weakest edge of the fundamental cycle (weight 1) gives the H1 pair
``(2, 3)``. Two disjoint edges of weight 5 and 3 give H0 pairs ``(0, 0)`` and
``(0, 2)`` and no H1.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from backend.modules.engine.persistence_vectors import (
    SUMMARY_FEATURES,
    SUMMARY_WIDTH,
    GraphDiagrams,
    PersistenceDiagram,
    PersistenceVectorParameters,
    diagram_from_graph,
    persistence_image,
    persistence_landscape,
    persistence_vector,
    topological_feature_vector,
)
from backend.modules.engine.persistent_homology import (
    betti_numbers,
    merge_levels,
)

TRIANGLE = np.array(
    [
        [0.0, 3.0, 2.0],
        [3.0, 0.0, 1.0],
        [2.0, 1.0, 0.0],
    ]
)

# Two disjoint pairs: component {0, 1} at weight 5, component {2, 3} at weight 3.
TWO_COMPONENT = np.array(
    [
        [0.0, 5.0, 0.0, 0.0],
        [5.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 3.0],
        [0.0, 0.0, 3.0, 0.0],
    ]
)

# A 4-cycle whose edges appear at weight 2, closed into two graph cycles by a
# weight-1 chord. H1 has two features of lifetime 0 and 1 in the s coordinate.
SQUARE_WITH_CHORD = np.array(
    [
        [0.0, 2.0, 1.0, 2.0],
        [2.0, 0.0, 2.0, 0.0],
        [1.0, 2.0, 0.0, 2.0],
        [2.0, 0.0, 2.0, 0.0],
    ]
)


def vector_parameters(**overrides) -> PersistenceVectorParameters:
    defaults = dict(
        grid=np.linspace(0.0, 3.0, 13),
        n_landscapes=3,
        image_resolution=8,
        birth_range=(0.0, 3.0),
        death_range=(0.0, 3.0),
        sigma=0.25,
        persistence_power=1.0,
        reference="median",
    )
    defaults.update(overrides)
    return PersistenceVectorParameters(**defaults)


class TestFiltrationMatchesExistingModule:
    """The diagram must be a reparameterisation, not a second definition."""

    def test_h0_deaths_are_the_existing_merge_levels(self):
        diagrams = diagram_from_graph(TRIANGLE)
        # death in s maps back to the weight by W_max - death.
        recovered = TRIANGLE.max() - diagrams.h0.death
        assert sorted(recovered.tolist(), reverse=True) == pytest.approx(
            merge_levels(TRIANGLE)
        )

    def test_h1_count_is_the_existing_cycle_rank(self):
        diagrams = diagram_from_graph(TRIANGLE)
        beta_0, beta_1 = betti_numbers(TRIANGLE, 0.0)
        assert diagrams.h1.n_features == beta_1
        assert diagrams.n_essential_h0 == beta_0

    def test_h1_birth_is_the_bottleneck_edge_weight(self):
        diagrams = diagram_from_graph(TRIANGLE)
        # The cycle is closed by the weight-1 edge, the weakest of the three.
        assert diagrams.h1.birth.tolist() == pytest.approx([3.0 - 1.0])
        assert diagrams.h1.death.tolist() == pytest.approx([3.0])
        assert diagrams.h1.persistence.tolist() == pytest.approx([1.0])

    def test_two_component_graph_has_no_h1(self):
        diagrams = diagram_from_graph(TWO_COMPONENT)
        assert diagrams.h1.n_features == 0
        assert diagrams.n_essential_h0 == 2
        assert diagrams.max_edge_weight == pytest.approx(5.0)


class TestHandComputedDiagram:
    def test_triangle_h0_pairs_are_exact(self):
        diagrams = diagram_from_graph(TRIANGLE)
        assert diagrams.h0.birth.tolist() == pytest.approx([0.0, 0.0])
        assert diagrams.h0.death.tolist() == pytest.approx([0.0, 1.0])

    def test_triangle_h1_pair_is_exact(self):
        diagrams = diagram_from_graph(TRIANGLE)
        assert diagrams.h0.dimension == 0
        assert diagrams.h1.dimension == 1
        np.testing.assert_allclose(diagrams.h1.birth, [2.0])
        np.testing.assert_allclose(diagrams.h1.death, [3.0])

    def test_two_component_h0_pairs_are_exact(self):
        diagrams = diagram_from_graph(TWO_COMPONENT)
        assert diagrams.h0.birth.tolist() == pytest.approx([0.0, 0.0])
        assert diagrams.h0.death.tolist() == pytest.approx([0.0, 2.0])

    def test_no_edges_gives_empty_diagrams(self):
        diagrams = diagram_from_graph(np.zeros((3, 3)))
        assert isinstance(diagrams, GraphDiagrams)
        assert diagrams.h0.n_features == 0
        assert diagrams.h1.n_features == 0
        assert diagrams.n_essential_h0 == 3


class TestHandComputedLandscape:
    def test_triangle_h1_landscape_values(self):
        diagrams = diagram_from_graph(TRIANGLE)
        grid = np.array([0.0, 1.0, 2.0, 2.25, 2.5, 3.0])
        landscape = persistence_landscape(diagrams.h1, grid, 1)
        # Tent for (2, 3): max(0, min(t - 2, 3 - t)) peaks at 2.5 with height 0.5.
        np.testing.assert_allclose(
            landscape, [[0.0, 0.0, 0.0, 0.25, 0.5, 0.0]], atol=1e-12
        )

    def test_triangle_h0_landscape_values(self):
        diagrams = diagram_from_graph(TRIANGLE)
        grid = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
        landscape = persistence_landscape(diagrams.h0, grid, 3)
        # (0, 0) contributes nothing; (0, 1) is the tent max(0, min(t, 1 - t)).
        np.testing.assert_allclose(landscape[0], [0.0, 0.25, 0.5, 0.25, 0.0])
        np.testing.assert_allclose(landscape[1], np.zeros(5))
        np.testing.assert_allclose(landscape[2], np.zeros(5))

    def test_landscapes_are_ordered_and_non_negative(self):
        diagram = PersistenceDiagram.from_pairs(
            1, [(0.2, 0.5), (1.0, 1.8), (1.5, 3.0)]
        )
        grid = np.linspace(0.0, 3.0, 50)
        landscape = persistence_landscape(diagram, grid, 4)
        assert landscape.shape == (4, 50)
        assert np.all(landscape >= 0.0)
        for k in range(3):
            assert np.all(landscape[k] >= landscape[k + 1] - 1e-15)

    def test_landscape_is_a_pointwise_function_not_a_grid_artefact(self):
        """Refining the grid must not change values at shared points."""
        diagram = PersistenceDiagram.from_pairs(1, [(2.0, 3.0)])
        coarse = persistence_landscape(diagram, [2.0, 2.5, 3.0], 1)
        fine = persistence_landscape(
            diagram, [2.0, 2.25, 2.5, 2.75, 3.0], 1
        )
        np.testing.assert_array_equal(coarse[0], fine[0][::2])
        # The midpoints are exactly half the peak, as the closed form demands.
        assert fine[0][1] == pytest.approx(0.25)
        assert fine[0][3] == pytest.approx(0.25)

    def test_rows_beyond_the_number_of_pairs_are_zero(self):
        diagram = PersistenceDiagram.from_pairs(0, [(0.0, 1.0)])
        landscape = persistence_landscape(diagram, [0.5], 5)
        assert landscape.shape == (5, 1)
        assert landscape[0, 0] == pytest.approx(0.5)
        assert np.all(landscape[1:] == 0.0)


class TestHandComputedImage:
    def test_point_mass_lands_in_the_expected_bin(self):
        # 3 bins over (0, 3) have centres 0.5, 1.5, 2.5; the pair sits on the
        # centre (1.5, 2.5), so the peak is at birth bin 1, death bin 2.
        diagram = PersistenceDiagram.from_pairs(1, [(1.5, 2.5)])
        image = persistence_image(
            diagram,
            resolution=3,
            birth_range=(0.0, 3.0),
            death_range=(0.0, 3.0),
            sigma=0.5,
        )
        assert image.shape == (9,)
        assert int(np.argmax(image)) == 1 * 3 + 2
        assert image[1 * 3 + 2] == pytest.approx(1.0)
        # One bin away on the birth axis: exp(-1 / (2 * 0.25)) = exp(-2).
        assert image[0 * 3 + 2] == pytest.approx(math.exp(-2.0))
        assert image[1 * 3 + 1] == pytest.approx(math.exp(-2.0))
        # Birth one bin low (1.0 away) and death two bins low (2.0 away):
        # exp(-(1 + 4) / (2 * 0.25)) = exp(-10).
        assert image[0 * 3 + 0] == pytest.approx(math.exp(-10.0))

    def test_image_is_non_negative_and_has_the_documented_width(self):
        diagram = PersistenceDiagram.from_pairs(1, [(0.5, 2.0), (1.0, 1.2)])
        image = persistence_image(
            diagram,
            resolution=6,
            birth_range=(0.0, 3.0),
            death_range=(0.0, 3.0),
            sigma=0.3,
        )
        assert image.shape == (36,)
        assert np.all(image >= 0.0)

    def test_persistence_power_scales_by_the_lifetime(self):
        # (0.5, 2.5) has lifetime 2.0 and sits on a bin centre of the 3x3 grid,
        # so the peak is lifetime ** power: 2.0 linear, 4.0 squared.
        diagram = PersistenceDiagram.from_pairs(1, [(0.5, 2.5)])
        kwargs = dict(
            resolution=3,
            birth_range=(0.0, 3.0),
            death_range=(0.0, 3.0),
            sigma=0.5,
        )
        linear = persistence_image(diagram, persistence_power=1.0, **kwargs)
        squared = persistence_image(diagram, persistence_power=2.0, **kwargs)
        assert linear[2] == pytest.approx(2.0)
        assert squared[2] == pytest.approx(4.0)
        np.testing.assert_allclose(squared, 2.0 * linear)

    def test_empty_diagram_gives_a_well_defined_zero_vector(self):
        """Chosen behaviour: empty is a valid state, not an error.

        A tree legitimately has no H1 features, so raising would make ordinary
        inputs unusable. The result is still fixed width so the downstream
        model never sees a ragged vector.
        """
        empty = PersistenceDiagram.from_pairs(1, [])
        image = persistence_image(
            empty,
            resolution=4,
            birth_range=(0.0, 1.0),
            death_range=(0.0, 1.0),
            sigma=0.1,
        )
        assert image.shape == (16,)
        np.testing.assert_array_equal(image, np.zeros(16))

    def test_empty_diagram_landscape_is_all_zero(self):
        empty = PersistenceDiagram.from_pairs(0, [])
        landscape = persistence_landscape(empty, [0.0, 0.5, 1.0], 3)
        assert landscape.shape == (3, 3)
        np.testing.assert_array_equal(landscape, np.zeros((3, 3)))


class TestLongLivedFeaturesDominate:
    """The property the module exists for, asserted directly."""

    def topological_vector(self, diagram: PersistenceDiagram) -> np.ndarray:
        empty = PersistenceDiagram.from_pairs(0, [])
        parameters = vector_parameters(
            grid=np.linspace(0.0, 2.0, 17),
            n_landscapes=3,
            image_resolution=16,
            birth_range=(0.0, 2.0),
            death_range=(0.0, 2.0),
            sigma=0.15,
        )
        return topological_feature_vector(empty, diagram, parameters)

    def test_a_short_lived_feature_barely_moves_the_vector(self):
        base = PersistenceDiagram.from_pairs(1, [(1.0, 2.0)])
        # Lifetime 0.01: essentially on the diagonal.
        short = PersistenceDiagram.from_pairs(1, [(1.0, 2.0), (0.99, 1.0)])
        # Lifetime 0.9: a genuinely long-lived cycle.
        long = PersistenceDiagram.from_pairs(1, [(1.0, 2.0), (0.1, 1.0)])

        baseline = self.topological_vector(base)
        short_delta = float(np.linalg.norm(self.topological_vector(short) - baseline))
        long_delta = float(np.linalg.norm(self.topological_vector(long) - baseline))

        assert long_delta > 0.0
        assert short_delta < long_delta
        assert short_delta < 0.05 * float(np.linalg.norm(baseline))

    def test_the_change_grows_with_the_lifetime(self):
        base = PersistenceDiagram.from_pairs(1, [(1.0, 2.0)])
        baseline = self.topological_vector(base)
        deltas = []
        for lifetime in (0.05, 0.25, 0.5, 0.9):
            perturbed = PersistenceDiagram.from_pairs(
                1, [(1.0, 2.0), (1.0 - lifetime, 1.0)]
            )
            deltas.append(
                float(np.linalg.norm(self.topological_vector(perturbed) - baseline))
            )
        assert deltas == sorted(deltas)
        assert deltas[-1] > 5.0 * deltas[0]

    def test_a_small_edge_perturbation_moves_the_graph_vector_a_little(self):
        parameters = vector_parameters(
            grid=np.linspace(0.0, 2.0, 17),
            image_resolution=12,
            birth_range=(0.0, 2.5),
            death_range=(0.0, 2.5),
            sigma=0.2,
        )
        baseline = persistence_vector(SQUARE_WITH_CHORD, parameters)
        small = persistence_vector(SQUARE_WITH_CHORD * (1.0 + 1e-3), parameters)
        large = persistence_vector(SQUARE_WITH_CHORD * (1.0 + 0.25), parameters)

        small_delta = float(np.linalg.norm(small - baseline))
        large_delta = float(np.linalg.norm(large - baseline))
        assert small_delta < large_delta
        assert small_delta < 0.05 * float(np.linalg.norm(baseline))


class TestFixedWidthVector:
    def test_width_and_layout_are_stable(self):
        parameters = vector_parameters()
        assert len(SUMMARY_FEATURES) == SUMMARY_WIDTH
        layout = parameters.layout()
        assert layout["summary"] == slice(
            parameters.topological_width, parameters.width
        )
        assert layout["h0_landscape"] == slice(0, parameters.landscape_width)
        last = 0
        for name in (
            "h0_landscape",
            "h1_landscape",
            "h0_image",
            "h1_image",
            "summary",
        ):
            assert layout[name].start == last
            last = layout[name].stop
        assert last == parameters.width

    def test_vector_has_the_declared_width_for_every_input(self):
        parameters = vector_parameters()
        for graph in (TRIANGLE, TWO_COMPONENT, np.zeros((3, 3)), np.zeros((1, 1))):
            vector = persistence_vector(graph, parameters)
            assert vector.shape == (parameters.width,)
            assert np.all(np.isfinite(vector))

    def test_summary_block_is_hand_computable_for_the_triangle(self):
        parameters = vector_parameters()
        vector = persistence_vector(TRIANGLE, parameters)
        summary = vector[parameters.layout()["summary"]]
        # Median edge weight is 2.0: two edges survive (weights 3 and 2), the
        # graph is connected, and its cycle rank at that level is 0.
        np.testing.assert_allclose(
            summary,
            [3.0, 2.0, 1.0, 0.0, 1.0, 0.0, 0.0, 3.0, 3.0, 2.0, 1.0],
        )

    def test_h1_block_carries_the_cycle_lifetime(self):
        parameters = vector_parameters()
        vector = persistence_vector(TRIANGLE, parameters)
        landscape = vector[parameters.layout()["h1_landscape"]].reshape(
            parameters.n_landscapes, parameters.n_grid
        )
        # Only one H1 feature of lifetime 1, so row 0 is a unit tent and rows
        # 1 and 2 vanish.
        assert landscape[0].max() == pytest.approx(0.5)
        np.testing.assert_array_equal(landscape[1], np.zeros(parameters.n_grid))
        np.testing.assert_array_equal(landscape[2], np.zeros(parameters.n_grid))


class TestDeterminism:
    def test_identical_inputs_give_bit_identical_vectors(self):
        parameters = vector_parameters()
        first = persistence_vector(TRIANGLE, parameters)
        second = persistence_vector(TRIANGLE, parameters)
        np.testing.assert_array_equal(first, second)
        assert first.tobytes() == second.tobytes()

    def test_a_copy_of_the_matrix_gives_the_same_vector(self):
        parameters = vector_parameters()
        copy = np.array(TRIANGLE, dtype=float, copy=True)
        np.testing.assert_array_equal(
            persistence_vector(TRIANGLE, parameters),
            persistence_vector(copy, parameters),
        )

    def test_diagrams_are_deterministic_under_ties(self):
        """Equal edge weights must not make the pair list depend on iteration."""
        tied = np.array(
            [
                [0.0, 1.0, 1.0, 1.0],
                [1.0, 0.0, 1.0, 1.0],
                [1.0, 1.0, 0.0, 1.0],
                [1.0, 1.0, 1.0, 0.0],
            ]
        )
        first = diagram_from_graph(tied)
        second = diagram_from_graph(tied)
        np.testing.assert_array_equal(first.h1.birth, second.h1.birth)
        np.testing.assert_array_equal(first.h0.death, second.h0.death)


class TestFailClosed:
    def test_non_finite_birth_is_rejected(self):
        with pytest.raises(ValueError, match="finite"):
            PersistenceDiagram.from_pairs(0, [(float("nan"), 1.0)])

    def test_non_finite_death_is_rejected(self):
        with pytest.raises(ValueError, match="finite"):
            PersistenceDiagram.from_pairs(0, [(0.0, float("inf"))])

    def test_death_strictly_before_birth_is_rejected(self):
        with pytest.raises(ValueError, match="strictly before birth"):
            PersistenceDiagram.from_pairs(0, [(0.5, 0.2)])

    def test_unknown_dimension_is_rejected(self):
        with pytest.raises(ValueError, match="only H0 and H1"):
            PersistenceDiagram.from_pairs(2, [(0.0, 1.0)])

    def test_mismatched_lengths_are_rejected(self):
        with pytest.raises(ValueError, match="same length"):
            PersistenceDiagram(0, np.array([0.0, 1.0]), np.array([0.0]))

    def test_malformed_pair_is_rejected(self):
        with pytest.raises(ValueError, match="two entries"):
            PersistenceDiagram.from_pairs(0, [(0.0, 1.0, 2.0)])

    def test_empty_grid_is_rejected(self):
        diagram = PersistenceDiagram.from_pairs(0, [(0.0, 1.0)])
        with pytest.raises(ValueError, match="grid"):
            persistence_landscape(diagram, [], 1)

    def test_non_finite_grid_is_rejected(self):
        diagram = PersistenceDiagram.from_pairs(0, [(0.0, 1.0)])
        with pytest.raises(ValueError, match="grid"):
            persistence_landscape(diagram, [0.0, float("nan")], 1)

    def test_zero_landscape_count_is_rejected(self):
        diagram = PersistenceDiagram.from_pairs(0, [(0.0, 1.0)])
        with pytest.raises(ValueError, match="n_landscapes"):
            persistence_landscape(diagram, [0.0, 1.0], 0)

    def test_negative_sigma_is_rejected(self):
        diagram = PersistenceDiagram.from_pairs(0, [(0.0, 1.0)])
        with pytest.raises(ValueError, match="sigma"):
            persistence_image(
                diagram,
                resolution=4,
                birth_range=(0.0, 1.0),
                death_range=(0.0, 1.0),
                sigma=-1.0,
            )

    def test_zero_sigma_is_rejected(self):
        diagram = PersistenceDiagram.from_pairs(0, [(0.0, 1.0)])
        with pytest.raises(ValueError, match="sigma"):
            persistence_image(
                diagram,
                resolution=4,
                birth_range=(0.0, 1.0),
                death_range=(0.0, 1.0),
                sigma=0.0,
            )

    def test_zero_resolution_is_rejected(self):
        diagram = PersistenceDiagram.from_pairs(0, [(0.0, 1.0)])
        with pytest.raises(ValueError, match="resolution"):
            persistence_image(
                diagram,
                resolution=0,
                birth_range=(0.0, 1.0),
                death_range=(0.0, 1.0),
                sigma=0.1,
            )

    def test_non_integer_resolution_is_rejected(self):
        diagram = PersistenceDiagram.from_pairs(0, [(0.0, 1.0)])
        with pytest.raises(ValueError, match="resolution"):
            persistence_image(
                diagram,
                resolution=2.5,
                birth_range=(0.0, 1.0),
                death_range=(0.0, 1.0),
                sigma=0.1,
            )

    def test_non_positive_persistence_power_is_rejected(self):
        diagram = PersistenceDiagram.from_pairs(0, [(0.0, 1.0)])
        with pytest.raises(ValueError, match="persistence_power"):
            persistence_image(
                diagram,
                resolution=4,
                birth_range=(0.0, 1.0),
                death_range=(0.0, 1.0),
                sigma=0.1,
                persistence_power=0.0,
            )

    def test_degenerate_birth_range_is_rejected(self):
        diagram = PersistenceDiagram.from_pairs(0, [(0.0, 1.0)])
        with pytest.raises(ValueError, match="birth_range"):
            persistence_image(
                diagram,
                resolution=4,
                birth_range=(1.0, 1.0),
                death_range=(0.0, 1.0),
                sigma=0.1,
            )

    def test_inverted_death_range_is_rejected(self):
        diagram = PersistenceDiagram.from_pairs(0, [(0.0, 1.0)])
        with pytest.raises(ValueError, match="death_range"):
            persistence_image(
                diagram,
                resolution=4,
                birth_range=(0.0, 1.0),
                death_range=(1.0, 0.0),
                sigma=0.1,
            )

    def test_non_finite_range_is_rejected(self):
        diagram = PersistenceDiagram.from_pairs(0, [(0.0, 1.0)])
        with pytest.raises(ValueError, match="death_range"):
            persistence_image(
                diagram,
                resolution=4,
                birth_range=(0.0, 1.0),
                death_range=(0.0, float("nan")),
                sigma=0.1,
            )

    def test_parameters_validate_their_fields(self):
        with pytest.raises(ValueError, match="grid"):
            vector_parameters(grid=[])
        with pytest.raises(ValueError, match="n_landscapes"):
            vector_parameters(n_landscapes=0)
        with pytest.raises(ValueError, match="image_resolution"):
            vector_parameters(image_resolution=0)
        with pytest.raises(ValueError, match="sigma"):
            vector_parameters(sigma=-0.5)
        with pytest.raises(ValueError, match="reference"):
            vector_parameters(reference="average")

    def test_dimension_order_is_enforced(self):
        parameters = vector_parameters()
        h1 = PersistenceDiagram.from_pairs(1, [(0.0, 1.0)])
        h0 = PersistenceDiagram.from_pairs(0, [(0.0, 1.0)])
        with pytest.raises(ValueError, match="H0 diagram first"):
            topological_feature_vector(h1, h0, parameters)
