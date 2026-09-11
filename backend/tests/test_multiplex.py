"""Tests for rolling multiplex network construction.

The load-bearing property here is the type guard. The deleted static-graph code
built one untyped adjacency by thresholding correlation, and that matrix was then
consumed as though it held obligations. These tests pin the separation: a
co-movement or similarity layer must be impossible to hand to the clearing engine,
and only an ``EXPOSURE`` layer may be cleared.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from backend.modules.engine.multiplex import (
    MultiplexLayer,
    MultiplexSnapshot,
    RelationKind,
    RollingMultiplex,
    build_ccp_exposure_layer,
    build_co_movement_layer,
    build_interbank_exposure_layer,
    build_similarity_layer,
    require_exposure,
)
from backend.modules.risk.clearing import clear_multiplex

NODES = ("A", "B", "C")


def _layer(kind: RelationKind, matrix, nodes=NODES, name="l", directed=False, as_of="2024-01-01"):
    return MultiplexLayer(
        name=name,
        kind=kind,
        adjacency=np.asarray(matrix, dtype=float),
        node_ids=nodes,
        as_of=pd.Timestamp(as_of),
        directed=directed,
    )


class TestExposureGuard:
    """The guard that prevents the old correlation-as-exposure bug."""

    def test_co_movement_layer_cannot_be_cleared(self):
        layer = _layer(RelationKind.CO_MOVEMENT, [[0.0, 0.9, 0.0], [0.9, 0.0, 0.0], [0.0, 0.0, 0.0]])
        with pytest.raises(TypeError, match="not\\s+an obligation"):
            require_exposure(layer)

    def test_similarity_layer_cannot_be_cleared(self):
        layer = _layer(RelationKind.SIMILARITY, [[0.0, 0.5, 0.0], [0.5, 0.0, 0.0], [0.0, 0.0, 0.0]])
        with pytest.raises(TypeError, match="not\\s+an obligation"):
            require_exposure(layer)

    def test_error_message_explains_why(self):
        layer = _layer(RelationKind.CO_MOVEMENT, np.zeros((3, 3)))
        with pytest.raises(TypeError) as excinfo:
            require_exposure(layer)
        message = str(excinfo.value)
        assert "co_movement" in message
        # The message must name the missing concept, not just refuse.
        assert "owes" in message or "obligation" in message

    def test_exposure_layer_converts_to_a_clearing_layer(self):
        matrix = [[0.0, 10.0, 0.0], [0.0, 0.0, 5.0], [0.0, 0.0, 0.0]]
        layer = _layer(RelationKind.EXPOSURE, matrix, directed=True)
        clearing_layer = require_exposure(layer)

        assert clearing_layer.name == "l"
        assert np.allclose(clearing_layer.liabilities, matrix)

    def test_seniority_is_carried_into_the_clearing_layer(self):
        layer = MultiplexLayer(
            name="secured",
            kind=RelationKind.EXPOSURE,
            adjacency=np.zeros((3, 3)),
            node_ids=NODES,
            as_of=pd.Timestamp("2024-01-01"),
            directed=True,
            metadata={"seniority": 2},
        )
        assert require_exposure(layer).seniority == 2

    def test_exposure_layer_clears_end_to_end(self):
        matrix = [[0.0, 10.0, 0.0], [0.0, 0.0, 0.0], [10.0, 0.0, 0.0]]
        layer = _layer(RelationKind.EXPOSURE, matrix, directed=True)
        result = clear_multiplex([require_exposure(layer)], [0.0, 0.0, 0.0], node_ids=list(NODES))

        # C (index 2) is fundamentally insolvent; A (index 0) fails only because
        # C did not pay it.
        assert result.causes[2] == "insolvency"
        assert result.causes[0] == "illiquidity"


class TestLayerValidation:
    def test_non_square_adjacency_is_rejected(self):
        with pytest.raises(ValueError, match="square"):
            _layer(RelationKind.EXPOSURE, [[0.0, 1.0, 0.0], [0.0, 0.0, 0.0]], directed=True)

    def test_node_count_mismatch_is_rejected(self):
        with pytest.raises(ValueError, match="node ids"):
            _layer(RelationKind.EXPOSURE, np.zeros((3, 3)), nodes=("A", "B"), directed=True)

    def test_negative_weights_are_rejected(self):
        with pytest.raises(ValueError, match="negative"):
            _layer(RelationKind.EXPOSURE, [[0.0, -1.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]], directed=True)

    def test_non_finite_weights_are_rejected(self):
        with pytest.raises(ValueError, match="non-finite"):
            _layer(RelationKind.EXPOSURE, [[0.0, np.nan, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]], directed=True)

    def test_self_relation_is_rejected(self):
        with pytest.raises(ValueError, match="itself"):
            _layer(RelationKind.EXPOSURE, np.eye(3), directed=True)

    def test_asymmetric_undirected_layer_is_rejected(self):
        with pytest.raises(ValueError, match="not symmetric"):
            _layer(
                RelationKind.CO_MOVEMENT,
                [[0.0, 0.9, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
                directed=False,
            )

    def test_directed_layer_may_be_asymmetric(self):
        layer = _layer(RelationKind.EXPOSURE, [[0.0, 1.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]], directed=True)
        assert layer.directed is True


class TestDensity:
    def test_directed_density_counts_ordered_pairs(self):
        layer = _layer(
            RelationKind.EXPOSURE,
            [[0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
            directed=True,
        )
        # 2 of 3*2 = 6 ordered pairs.
        assert layer.density() == pytest.approx(2 / 6)

    def test_undirected_density_counts_unordered_pairs(self):
        layer = _layer(
            RelationKind.CO_MOVEMENT,
            [[0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
        )
        # 1 of 3*2/2 = 3 unordered pairs.
        assert layer.density() == pytest.approx(1 / 3)

    def test_single_node_has_zero_density(self):
        layer = _layer(RelationKind.EXPOSURE, [[0.0]], nodes=("A",), directed=True)
        assert layer.density() == 0.0


class TestSimilarityLayer:
    def test_cosine_similarity_is_correct_on_a_known_case(self):
        features = pd.DataFrame(
            {"x": [1.0, 0.0, 3.0], "y": [0.0, 1.0, 0.0]},
            index=["A", "B", "C"],
        )
        layer = build_similarity_layer(
            features, NODES, as_of=pd.Timestamp("2024-01-01"), k_neighbors=5
        )

        m = layer.adjacency
        # A=[1,0] and C=[3,0] point the same way: similarity 1.
        assert m[0, 2] == pytest.approx(1.0)
        # A and B are orthogonal: similarity 0, i.e. no edge.
        assert m[0, 1] == pytest.approx(0.0)
        assert m[1, 2] == pytest.approx(0.0)

    def test_similarity_layer_is_symmetric_with_zero_diagonal(self):
        rng = np.random.default_rng(11)
        features = pd.DataFrame(
            rng.normal(size=(5, 4)), index=list("ABCDE")
        )
        layer = build_similarity_layer(
            features, tuple("ABCDE"), as_of=pd.Timestamp("2024-01-01"), k_neighbors=3
        )
        assert np.allclose(layer.adjacency, layer.adjacency.T)
        assert np.allclose(np.diag(layer.adjacency), 0.0)

    def test_knn_sparsification_limits_edges_per_node(self):
        rng = np.random.default_rng(12)
        features = pd.DataFrame(rng.normal(size=(8, 3)), index=[f"N{i}" for i in range(8)])
        layer = build_similarity_layer(
            features, tuple(features.index), as_of=pd.Timestamp("2024-01-01"), k_neighbors=2
        )
        # At most k neighbours per node, and symmetrisation cannot exceed 2k.
        per_node = (layer.adjacency > 0).sum(axis=1)
        assert per_node.max() <= 4
        assert layer.metadata["k_neighbors"] == 2

    def test_min_similarity_threshold_drops_weak_relations(self):
        features = pd.DataFrame({"x": [1.0, 0.0], "y": [0.0, 1.0]}, index=["A", "B"])
        layer = build_similarity_layer(
            features, ("A", "B"), as_of=pd.Timestamp("2024-01-01"),
            k_neighbors=5, min_similarity=0.5,
        )
        assert layer.adjacency.sum() == pytest.approx(0.0)

    def test_is_labelled_similarity_not_exposure(self):
        features = pd.DataFrame({"x": [1.0, 2.0]}, index=["A", "B"])
        layer = build_similarity_layer(
            features, ("A", "B"), as_of=pd.Timestamp("2024-01-01")
        )
        assert layer.kind is RelationKind.SIMILARITY
        assert layer.is_clearing_eligible is False

    def test_cross_section_declared_known_after_as_of_is_rejected(self):
        # The feature frame is a cross-section indexed by institution, so it
        # carries no per-row timestamp. Its vintage is declared explicitly, and a
        # vintage later than as_of is look-ahead.
        features = pd.DataFrame({"x": [1.0, 2.0]}, index=["A", "B"])
        with pytest.raises(ValueError, match="must not read the future"):
            build_similarity_layer(
                features,
                ("A", "B"),
                as_of=pd.Timestamp("2024-03-01"),
                known_at=pd.Timestamp("2024-06-01"),
            )

    def test_cross_section_known_before_as_of_records_its_vintage(self):
        features = pd.DataFrame({"x": [1.0, 2.0]}, index=["A", "B"])
        layer = build_similarity_layer(
            features,
            ("A", "B"),
            as_of=pd.Timestamp("2024-03-01"),
            known_at=pd.Timestamp("2024-01-15"),
        )
        assert layer.metadata["known_at"] == pd.Timestamp("2024-01-15").isoformat()

    def test_institutions_absent_from_features_are_isolated(self):
        features = pd.DataFrame({"x": [1.0, 2.0]}, index=["A", "B"])
        layer = build_similarity_layer(
            features, ("A", "B", "C"), as_of=pd.Timestamp("2024-01-01"), k_neighbors=5
        )
        # C has no features, so it has no relations to anything.
        assert layer.adjacency[2].sum() == pytest.approx(0.0)
        assert layer.adjacency[:, 2].sum() == pytest.approx(0.0)

    def test_missing_feature_values_are_imputed_at_the_column_median(self):
        features = pd.DataFrame(
            {"x": [1.0, np.nan, 3.0], "y": [1.0, 1.0, 1.0]},
            index=["A", "B", "C"],
        )
        layer = build_similarity_layer(
            features, NODES, as_of=pd.Timestamp("2024-01-01"), k_neighbors=5
        )
        assert np.all(np.isfinite(layer.adjacency))


class TestCoMovementLayer:
    def test_shared_trend_alone_does_not_create_a_relation(self):
        """The methodological point: co-movement is measured on changes.

        Two spreads with the same linear trend but independent shocks have a
        level correlation near 1. On levels they would look connected, but the
        shared trend is not a funding relation between the institutions.
        """
        rng = np.random.default_rng(20250101)
        index = pd.date_range("2024-01-01", periods=120, freq="D")
        trend = np.linspace(0, 10, 120)
        levels = pd.DataFrame(
            {"A": trend + rng.normal(0, 0.1, 120), "B": trend + rng.normal(0, 0.1, 120)},
            index=index,
        )

        # Sanity: on levels the two series are almost perfectly correlated.
        assert levels["A"].corr(levels["B"]) > 0.99

        layer = build_co_movement_layer(
            levels, ("A", "B"), as_of=index[-1], window=120, min_abs_correlation=0.3
        )
        # On changes they are independent, so no edge is created.
        assert layer.adjacency[0, 1] == pytest.approx(0.0)
        assert layer.metadata["basis"] == "changes"

    def test_correlated_changes_do_create_a_relation(self):
        rng = np.random.default_rng(20250102)
        index = pd.date_range("2024-01-01", periods=120, freq="D")
        shock = rng.normal(0, 1.0, 120)
        walk = np.cumsum(shock)
        levels = pd.DataFrame(
            {"A": walk, "B": walk + rng.normal(0, 0.05, 120)},
            index=index,
        )
        layer = build_co_movement_layer(
            levels, ("A", "B"), as_of=index[-1], window=120, min_abs_correlation=0.3
        )
        assert layer.adjacency[0, 1] > 0.3

    def test_weak_relations_are_thresholded_out(self):
        rng = np.random.default_rng(20250103)
        index = pd.date_range("2024-01-01", periods=120, freq="D")
        levels = pd.DataFrame(
            {"A": rng.normal(size=120), "B": rng.normal(size=120)}, index=index
        )
        layer = build_co_movement_layer(
            levels, ("A", "B"), as_of=index[-1], window=120, min_abs_correlation=0.95
        )
        assert layer.adjacency.sum() == pytest.approx(0.0)

    def test_layer_is_symmetric_labelled_and_not_clearing_eligible(self):
        rng = np.random.default_rng(20250104)
        index = pd.date_range("2024-01-01", periods=60, freq="D")
        walk = np.cumsum(rng.normal(size=60))
        levels = pd.DataFrame(
            {"A": walk, "B": walk * 1.01, "C": rng.normal(size=60)}, index=index
        )
        layer = build_co_movement_layer(
            levels, NODES, as_of=index[-1], window=60, min_abs_correlation=0.3
        )
        assert layer.kind is RelationKind.CO_MOVEMENT
        assert layer.is_clearing_eligible is False
        assert np.allclose(layer.adjacency, layer.adjacency.T)
        assert np.allclose(np.diag(layer.adjacency), 0.0)

    def test_only_data_up_to_as_of_is_used(self):
        index = pd.date_range("2024-01-01", periods=40, freq="D")
        first = pd.DataFrame({"A": np.arange(40.0), "B": np.arange(40.0)}, index=index)
        # Adding violent future observations must not change the as_of=day-20 layer.
        late = first.copy()
        late.iloc[25:] = -1000.0

        cutoff = index[20]
        base = build_co_movement_layer(first, ("A", "B"), as_of=cutoff, window=20)
        perturbed = build_co_movement_layer(late, ("A", "B"), as_of=cutoff, window=20)
        assert np.allclose(base.adjacency, perturbed.adjacency)

    def test_future_dated_levels_are_withheld_not_used(self):
        # A point-in-time panel normally extends past the query date, so rows
        # after as_of are withheld rather than treated as an error.
        index = pd.date_range("2024-01-01", periods=30, freq="D")
        rng = np.random.default_rng(20250105)
        walk = np.cumsum(rng.normal(size=30))
        levels = pd.DataFrame({"A": walk, "B": walk}, index=index)

        full = build_co_movement_layer(levels, ("A", "B"), as_of=index[19], window=20)
        truncated = build_co_movement_layer(
            levels.loc[: index[19]], ("A", "B"), as_of=index[19], window=20
        )

        assert np.allclose(full.adjacency, truncated.adjacency)
        assert full.metadata["rows_withheld_as_future"] == 10

    def test_panel_lying_entirely_in_the_future_is_rejected(self):
        # Not a panel extending past the query but the wrong frame entirely;
        # returning an empty network would hide the mistake.
        index = pd.date_range("2024-06-01", periods=5, freq="D")
        levels = pd.DataFrame({"A": np.arange(5.0), "B": np.arange(5.0)}, index=index)
        with pytest.raises(ValueError, match="must not read the future"):
            build_co_movement_layer(
                levels, ("A", "B"), as_of=pd.Timestamp("2024-01-01"), window=5
            )

    def test_series_without_variation_contributes_nothing(self):
        index = pd.date_range("2024-01-01", periods=30, freq="D")
        levels = pd.DataFrame(
            {"A": np.arange(30.0), "B": np.full(30, 5.0)}, index=index
        )
        layer = build_co_movement_layer(levels, ("A", "B"), as_of=index[-1], window=30)
        assert layer.adjacency.sum() == pytest.approx(0.0)
        assert layer.metadata["n_usable"] <= 1


class TestInterbankExposureLayer:
    def test_exposures_are_directed_debtor_to_creditor(self):
        exposures = pd.DataFrame(
            {"debtor": ["A"], "creditor": ["B"], "amount": [10.0]}
        )
        layer = build_interbank_exposure_layer(exposures, NODES, as_of=pd.Timestamp("2024-01-01"))
        assert layer.adjacency[0, 1] == pytest.approx(10.0)
        assert layer.adjacency[1, 0] == pytest.approx(0.0)
        assert layer.directed is True

    def test_multiple_exposures_between_the_same_pair_accumulate(self):
        exposures = pd.DataFrame(
            {"debtor": ["A", "A"], "creditor": ["B", "B"], "amount": [10.0, 5.0]}
        )
        layer = build_interbank_exposure_layer(exposures, NODES, as_of=pd.Timestamp("2024-01-01"))
        assert layer.adjacency[0, 1] == pytest.approx(15.0)

    def test_unknown_institution_is_rejected(self):
        exposures = pd.DataFrame({"debtor": ["Z"], "creditor": ["B"], "amount": [1.0]})
        with pytest.raises(KeyError, match="outside the node universe"):
            build_interbank_exposure_layer(exposures, NODES, as_of=pd.Timestamp("2024-01-01"))

    def test_negative_amount_is_rejected(self):
        exposures = pd.DataFrame({"debtor": ["A"], "creditor": ["B"], "amount": [-1.0]})
        with pytest.raises(ValueError, match="invalid amount"):
            build_interbank_exposure_layer(exposures, NODES, as_of=pd.Timestamp("2024-01-01"))

    def test_missing_column_is_reported(self):
        exposures = pd.DataFrame({"debtor": ["A"], "creditor": ["B"]})
        with pytest.raises(ValueError, match="missing required column"):
            build_interbank_exposure_layer(exposures, NODES, as_of=pd.Timestamp("2024-01-01"))

    def test_panel_lying_entirely_in_the_future_is_rejected(self):
        exposures = pd.DataFrame(
            {
                "debtor": ["A"],
                "creditor": ["B"],
                "amount": [1.0],
                "as_of": [pd.Timestamp("2024-06-01")],
            }
        )
        with pytest.raises(ValueError, match="must not read the future"):
            build_interbank_exposure_layer(exposures, NODES, as_of=pd.Timestamp("2024-01-01"))

    def test_rows_dated_after_as_of_are_excluded_when_as_of_is_valid(self):
        exposures = pd.DataFrame(
            {
                "debtor": ["A", "A"],
                "creditor": ["B", "B"],
                "amount": [7.0, 100.0],
                "as_of": [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-06-01")],
            }
        )
        layer = build_interbank_exposure_layer(exposures, NODES, as_of=pd.Timestamp("2024-03-01"))
        assert layer.adjacency[0, 1] == pytest.approx(7.0)

    def test_layer_is_clearing_eligible(self):
        exposures = pd.DataFrame({"debtor": ["A"], "creditor": ["B"], "amount": [1.0]})
        layer = build_interbank_exposure_layer(exposures, NODES, as_of=pd.Timestamp("2024-01-01"))
        assert layer.is_clearing_eligible
        require_exposure(layer)  # must not raise


class TestCCPExposureLayer:
    def test_member_obligations_point_at_the_ccp(self):
        members = pd.DataFrame({"member": ["A", "B"], "exposure": [50.0, 30.0]})
        layer = build_ccp_exposure_layer(
            members, NODES, as_of=pd.Timestamp("2024-01-01"), ccp_id="C"
        )
        ccp_index = NODES.index("C")
        assert layer.adjacency[0, ccp_index] == pytest.approx(50.0)
        assert layer.adjacency[1, ccp_index] == pytest.approx(30.0)
        assert layer.adjacency[ccp_index].sum() == pytest.approx(0.0)

    def test_ccp_must_be_in_the_universe(self):
        members = pd.DataFrame({"member": ["A"], "exposure": [1.0]})
        with pytest.raises(KeyError, match="not in the node universe"):
            build_ccp_exposure_layer(
                members, ("A", "B"), as_of=pd.Timestamp("2024-01-01"), ccp_id="Z"
            )

    def test_unknown_member_is_rejected(self):
        members = pd.DataFrame({"member": ["Z"], "exposure": [1.0]})
        with pytest.raises(KeyError, match="not in the node universe"):
            build_ccp_exposure_layer(
                members, NODES, as_of=pd.Timestamp("2024-01-01"), ccp_id="C"
            )

    def test_loss_mutualisation_is_recorded_as_not_modelled(self):
        members = pd.DataFrame({"member": ["A"], "exposure": [1.0]})
        layer = build_ccp_exposure_layer(
            members, NODES, as_of=pd.Timestamp("2024-01-01"), ccp_id="C"
        )
        # The gap is declared rather than left for a reader to assume away.
        assert layer.metadata["loss_mutualisation_modelled"] is False
        assert layer.is_clearing_eligible

    def test_ccp_layer_clears_in_seniority(self):
        members = pd.DataFrame({"member": ["A", "B"], "exposure": [10.0, 10.0]})
        ccp = build_ccp_exposure_layer(
            members, NODES, as_of=pd.Timestamp("2024-01-01"), ccp_id="C"
        )
        result = clear_multiplex(
            [require_exposure(ccp)], [10.0, 0.0, 0.0], node_ids=list(NODES)
        )
        # A holds exactly enough to cover its own margin; B holds nothing.
        assert result.layer_payments["ccp_C"][0] == pytest.approx(10.0)
        assert result.layer_payments["ccp_C"][1] == pytest.approx(0.0)


class TestSnapshot:
    def _snapshot(self, as_of="2024-06-01"):
        return MultiplexSnapshot(
            as_of=pd.Timestamp(as_of), node_ids=NODES
        )

    def test_add_layer_rejects_a_foreign_node_universe(self):
        snapshot = self._snapshot()
        foreign = _layer(RelationKind.EXPOSURE, np.zeros((2, 2)), nodes=("X", "Y"), directed=True)
        with pytest.raises(ValueError, match="different node universe"):
            snapshot.add_layer(foreign)

    def test_add_layer_rejects_a_layer_dated_after_the_snapshot(self):
        snapshot = self._snapshot("2024-06-01")
        future = _layer(
            RelationKind.EXPOSURE, np.zeros((3, 3)), directed=True, as_of="2024-09-01"
        )
        with pytest.raises(ValueError, match="after the snapshot"):
            snapshot.add_layer(future)

    def test_clearing_layers_excludes_non_exposure_layers(self):
        snapshot = self._snapshot()
        snapshot.add_layer(
            _layer(RelationKind.EXPOSURE, [[0.0, 1.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]], name="ib", directed=True)
        )
        snapshot.add_layer(_layer(RelationKind.CO_MOVEMENT, np.zeros((3, 3)), name="flow"))
        snapshot.add_layer(_layer(RelationKind.SIMILARITY, np.zeros((3, 3)), name="sim"))

        clearing = snapshot.clearing_layers
        assert [layer.name for layer in clearing] == ["ib"]
        assert set(snapshot.without_clearing_layers()) == {"flow", "sim"}

    def test_a_snapshot_of_only_non_exposure_layers_clears_nothing(self):
        snapshot = self._snapshot()
        snapshot.add_layer(_layer(RelationKind.CO_MOVEMENT, np.zeros((3, 3)), name="flow"))
        assert snapshot.clearing_layers == []

    def test_snapshot_serialises_without_nan(self):
        snapshot = self._snapshot()
        snapshot.add_layer(
            _layer(RelationKind.EXPOSURE, [[0.0, 5.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]], name="ib", directed=True)
        )
        payload = snapshot.to_dict()
        json.dumps(payload, allow_nan=False)
        assert payload["clearing_eligible"] == ["ib"]


class TestRollingMultiplex:
    def _snapshot(self, as_of, with_exposure=True):
        snapshot = MultiplexSnapshot(as_of=pd.Timestamp(as_of), node_ids=NODES)
        matrix = np.zeros((3, 3))
        if with_exposure:
            matrix[0, 1] = 10.0
        snapshot.add_layer(
            _layer(RelationKind.EXPOSURE, matrix, name="ib", directed=True, as_of=as_of)
        )
        return snapshot

    def test_snapshots_must_advance_in_time(self):
        rolling = RollingMultiplex(NODES)
        rolling.add(self._snapshot("2024-01-01"))
        with pytest.raises(ValueError, match="does not advance time"):
            rolling.add(self._snapshot("2024-01-01"))

    def test_snapshots_cannot_move_backwards(self):
        rolling = RollingMultiplex(NODES)
        rolling.add(self._snapshot("2024-06-01"))
        with pytest.raises(ValueError, match="does not advance time"):
            rolling.add(self._snapshot("2024-01-01"))

    def test_foreign_universe_is_rejected(self):
        rolling = RollingMultiplex(NODES)
        foreign = MultiplexSnapshot(as_of=pd.Timestamp("2024-01-01"), node_ids=("X", "Y"))
        with pytest.raises(ValueError, match="different node universe"):
            rolling.add(foreign)

    def test_at_returns_the_snapshot_known_at_that_time(self):
        rolling = RollingMultiplex(NODES)
        rolling.add(self._snapshot("2024-01-01"))
        rolling.add(self._snapshot("2024-06-01"))
        rolling.add(self._snapshot("2024-12-01"))

        assert rolling.at("2024-03-01").as_of == pd.Timestamp("2024-01-01")
        assert rolling.at("2024-06-01").as_of == pd.Timestamp("2024-06-01")
        assert rolling.at("2025-06-01").as_of == pd.Timestamp("2024-12-01")
        # Before the first snapshot there is nothing a model could have seen.
        assert rolling.at("2023-01-01") is None

    def test_at_never_returns_a_future_snapshot(self):
        rolling = RollingMultiplex(NODES)
        for month in range(1, 7):
            rolling.add(self._snapshot(f"2024-{month:02d}-01"))

        for probe in pd.date_range("2024-01-01", "2024-06-15", freq="D"):
            snapshot = rolling.at(probe)
            if snapshot is not None:
                assert snapshot.as_of <= probe

    def test_layer_history_is_in_time_order(self):
        rolling = RollingMultiplex(NODES)
        rolling.add(self._snapshot("2024-01-01"))
        rolling.add(self._snapshot("2024-06-01"))

        history = rolling.layer_history("ib")
        assert [stamp for stamp, _ in history] == [
            pd.Timestamp("2024-01-01"),
            pd.Timestamp("2024-06-01"),
        ]
        assert rolling.layer_history("absent") == []

    def test_rolling_multiplex_serialises(self):
        rolling = RollingMultiplex(NODES)
        rolling.add(self._snapshot("2024-01-01"))
        json.dumps(rolling.to_dict(), allow_nan=False)

    def test_replaying_a_backtest_sees_the_network_as_it_was(self):
        """The point of the rolling container.

        A network that strengthened over time must look weak when the backtest
        asks about an early date, otherwise the backtest is reading the end state.
        """
        rolling = RollingMultiplex(NODES)
        early = self._snapshot("2024-01-01")
        late = MultiplexSnapshot(as_of=pd.Timestamp("2024-06-01"), node_ids=NODES)
        late.add_layer(
            _layer(
                RelationKind.EXPOSURE,
                [[0.0, 10.0, 0.0], [0.0, 0.0, 10.0], [10.0, 0.0, 0.0]],
                name="ib",
                directed=True,
                as_of="2024-06-01",
            )
        )
        rolling.add(early)
        rolling.add(late)

        assert rolling.at("2024-02-01").layers["ib"].adjacency.sum() == pytest.approx(10.0)
        assert rolling.at("2024-07-01").layers["ib"].adjacency.sum() == pytest.approx(30.0)
