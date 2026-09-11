"""Tests for the network quality attestation gate.

The gate exists to refuse predictions when the network is no longer the one the
model was trained on. These tests cover three things: that the distance is
computed correctly, that the threshold is derived from the training distribution
rather than chosen, and that the gate fails closed when it cannot measure what it
is supposed to measure.

One test deliberately records a limitation: the summary-distribution distance is
blind to rewirings that preserve those distributions. That is a real gap in the
method and is pinned here rather than left for someone to discover in production.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from backend.exceptions import PredictionBlockedError
from backend.modules.data.network_gate import (
    FragmentationReference,
    GraphSignature,
    IntervalWidthReference,
    NetworkAttestation,
    NetworkQualityGate,
    RegimeAssessment,
    TopologyReference,
    wasserstein_1d,
)
from backend.modules.engine.multiplex import MultiplexLayer, RelationKind


def make_layer(adjacency, name="interbank", node_ids=None) -> MultiplexLayer:
    matrix = np.asarray(adjacency, dtype=float)
    n = matrix.shape[0]
    if node_ids is None:
        node_ids = tuple(f"N{i}" for i in range(n))
    return MultiplexLayer(
        name=name,
        kind=RelationKind.EXPOSURE,
        adjacency=matrix,
        node_ids=node_ids,
        as_of=pd.Timestamp("2024-01-01"),
        directed=True,
    )


def ring(n: int, weight: float = 1.0, name: str = "interbank") -> MultiplexLayer:
    matrix = np.zeros((n, n))
    for i in range(n):
        matrix[i, (i + 1) % n] = weight
    return make_layer(matrix, name=name)


class TestWasserstein:
    def test_point_masses(self):
        assert wasserstein_1d([0.0], [1.0]) == pytest.approx(1.0)
        assert wasserstein_1d([0.0], [5.0]) == pytest.approx(5.0)

    def test_identical_samples_are_zero_distance(self):
        sample = [1.0, 2.0, 3.0, 4.0]
        assert wasserstein_1d(sample, sample) == pytest.approx(0.0)

    def test_pure_translation_moves_by_the_shift(self):
        base = [0.0, 1.0, 2.0, 3.0]
        shifted = [value + 2.5 for value in base]
        assert wasserstein_1d(base, shifted) == pytest.approx(2.5)

    def test_unequal_sample_sizes_are_handled(self):
        # F_a over [0,1,2] is [1/2, 1, 1]; F_b is [1/3, 2/3, 1].
        # Areas: |1/2-1/3|*1 + |1-2/3|*1 = 1/6 + 1/3 = 1/2.
        assert wasserstein_1d([0.0, 1.0], [0.0, 1.0, 2.0]) == pytest.approx(0.5)

    def test_is_symmetric(self):
        left = [0.1, 0.5, 9.0]
        right = [0.2, 0.4, 1.0, 1.1]
        assert wasserstein_1d(left, right) == pytest.approx(wasserstein_1d(right, left))

    def test_point_mass_against_a_sample_equals_mean_absolute_deviation(self):
        sample = np.array([1.0, 2.0, 3.0, 4.0])
        centre = float(sample.mean())
        expected = float(np.mean(np.abs(sample - centre)))
        assert wasserstein_1d([centre], sample) == pytest.approx(expected)

    def test_is_non_negative_and_obeys_triangle_inequality(self):
        a = [0.0, 1.0, 5.0]
        b = [1.0, 2.0, 6.0]
        c = [3.0, 3.0, 3.0]
        assert wasserstein_1d(a, b) >= 0
        assert wasserstein_1d(a, c) <= wasserstein_1d(a, b) + wasserstein_1d(b, c) + 1e-12

    def test_validation(self):
        with pytest.raises(ValueError, match="empty"):
            wasserstein_1d([], [1.0])
        with pytest.raises(ValueError, match="empty"):
            wasserstein_1d([1.0], [])
        with pytest.raises(ValueError, match="non-finite"):
            wasserstein_1d([1.0, float("nan")], [1.0])
        with pytest.raises(ValueError, match="non-finite"):
            wasserstein_1d([1.0], [float("inf")])


class TestGraphSignature:
    def test_components_are_the_expected_views(self):
        matrix = [[0.0, 2.0, 0.0], [0.0, 0.0, 3.0], [1.0, 0.0, 0.0]]
        signature = GraphSignature.from_layer(make_layer(matrix))

        assert sorted(signature.edge_weights) == [1.0, 2.0, 3.0]
        assert signature.node_strengths.tolist() == [2.0, 3.0, 1.0]
        assert signature.degrees.tolist() == [1.0, 1.0, 1.0]
        assert signature.n_nodes == 3

    def test_spectrum_is_real_even_for_a_directed_layer(self):
        matrix = [[0.0, 5.0, 0.0], [0.0, 0.0, 7.0], [0.0, 0.0, 0.0]]
        signature = GraphSignature.from_layer(make_layer(matrix))
        assert np.isrealobj(signature.spectrum)
        assert np.all(np.isfinite(signature.spectrum))

    def test_empty_layer_has_no_edge_weights_but_keeps_other_components(self):
        signature = GraphSignature.from_layer(make_layer(np.zeros((4, 4))))
        assert signature.edge_weights.size == 0
        assert signature.node_strengths.size == 4
        assert signature.degrees.size == 4
        assert signature.spectrum.size == 4

    def test_non_square_adjacency_is_rejected(self):
        matrix = np.zeros((3, 3))
        layer = MultiplexLayer(
            name="bad",
            kind=RelationKind.EXPOSURE,
            adjacency=matrix,
            node_ids=("A", "B", "C"),
            as_of=pd.Timestamp("2024-01-01"),
            directed=True,
        )
        # The MultiplexLayer itself rejects malformed matrices, so bypass it to
        # exercise the signature's own guard.
        object.__setattr__(layer, "adjacency", np.zeros((2, 3)))
        with pytest.raises(ValueError, match="square"):
            GraphSignature.from_layer(layer)

    def test_serialises(self):
        signature = GraphSignature.from_layer(ring(4))
        json.dumps(signature.to_dict(), allow_nan=False)


class TestTopologyReference:
    # 32 snapshots: enough that the novelty test can actually reject. With only a
    # handful the smallest attainable p-value (1/(C(n,2)+1)) exceeds the corrected
    # threshold and the gate can never fire -- see the undersized-reference test.
    _WEIGHTS = [1.0 + 0.02 * i for i in range(40)]

    def _reference(self):
        return TopologyReference(
            [GraphSignature.from_layer(ring(6, weight=w)) for w in self._WEIGHTS],
            alpha=0.01,
        )

    def test_a_training_like_topology_is_not_novel(self):
        reference = self._reference()
        assessment = reference.assess(GraphSignature.from_layer(ring(6, weight=1.25)))

        assert assessment.is_novel is False
        assert 0.0 < assessment.aggregate_p_value <= 1.0

    def test_a_collapsed_network_is_novel(self):
        reference = self._reference()
        collapsed = make_layer(np.zeros((6, 6)))
        assessment = reference.assess(GraphSignature.from_layer(collapsed))

        assert assessment.is_novel is True

    def test_a_different_size_network_is_novel(self):
        reference = self._reference()
        assessment = reference.assess(GraphSignature.from_layer(ring(30, weight=1.0)))
        assert assessment.is_novel is True

    def test_p_values_are_in_the_unit_interval(self):
        reference = self._reference()
        for weight in (0.5, 1.0, 1.5, 3.0, 10.0):
            assessment = reference.assess(GraphSignature.from_layer(ring(6, weight=weight)))
            for p_value in assessment.p_values.values():
                assert 0.0 < p_value <= 1.0

    def test_minimum_p_value_is_bounded_away_from_zero(self):
        # Add-one smoothing means a single reference sample cannot produce exactly
        # zero, which would otherwise make any test with one null sample vacuous.
        reference = TopologyReference([GraphSignature.from_layer(ring(4))], alpha=0.05)
        assessment = reference.assess(GraphSignature.from_layer(ring(4, weight=99.0)))
        assert all(p > 0 for p in assessment.p_values.values())

    def test_skipped_components_are_recorded_not_fabricated(self):
        reference = TopologyReference(
            [GraphSignature.from_layer(make_layer(np.zeros((4, 4))))], alpha=0.05
        )
        assessment = reference.assess(GraphSignature.from_layer(ring(4)))
        # edge_weights is empty on the reference side, so it cannot be compared.
        assert "edge_weights" in assessment.skipped
        assert "edge_weights" not in assessment.distances

    def test_an_entirely_incomparable_network_cannot_be_certified(self):
        # Every component skipped: the gate must not report "fine" when it
        # measured nothing.
        reference = TopologyReference(
            [GraphSignature.from_layer(make_layer(np.zeros((0, 0)), node_ids=()))], alpha=0.05
        )
        assessment = reference.assess(
            GraphSignature.from_layer(make_layer(np.zeros((0, 0)), node_ids=()))
        )
        assert assessment.is_novel is True
        assert math.isnan(assessment.aggregate_p_value)

    def test_a_small_reference_cannot_reject_and_says_so(self):
        """A recorded limitation with teeth: an always-passing gate is worthless.

        The empirical p-value is (1 + #{null >= d}) / (1 + n_null) with
        n_null = C(n, 2), so the smallest attainable p-value is 1/(C(n,2)+1). With
        five snapshots that is 1/11 = 0.091, far above the Bonferroni-corrected
        threshold of 0.0025. No input, however exotic, can be flagged -- which is
        precisely why ``is_calibratable`` exists instead of leaving callers to
        assume a passing verdict means something.
        """
        from backend.modules.data.network_gate import minimum_reference_size

        tiny = TopologyReference(
            [GraphSignature.from_layer(ring(6, weight=w)) for w in (1.0, 1.1, 1.2, 1.3, 1.4)],
            alpha=0.01,
        )
        assert tiny.is_calibratable is False
        assert minimum_reference_size(0.01, 5) == 33

        # Even a maximally different network cannot be flagged.
        assessment = tiny.assess(GraphSignature.from_layer(make_layer(np.zeros((6, 6)))))
        assert assessment.is_novel is False, (
            "an undersized reference cannot reject, so this must not be flagged"
        )
        assert assessment.calibratable is False

        # A sufficiently large reference can.
        big = TopologyReference(
            [GraphSignature.from_layer(ring(6, weight=w)) for w in (1.0 + 0.02 * i for i in range(40))],
            alpha=0.01,
        )
        assert big.is_calibratable is True
        assert big.assess(GraphSignature.from_layer(make_layer(np.zeros((6, 6))))).is_novel is True

    def test_the_gate_reports_an_undersized_reference(self):
        tiny = TopologyReference(
            [GraphSignature.from_layer(ring(6, weight=w)) for w in (1.0, 1.1, 1.2)],
            alpha=0.01,
        )
        permissive = NetworkQualityGate(
            topology_reference=tiny, known_regimes=("calm",)
        ).evaluate(job_id="job-tiny", live_layers=[ring(6)], regime_label="calm")
        names = {check.name for check in permissive.checks}
        assert "topology_reference_undersized" in names
        assert permissive.verified is True  # warning, not blocking, by default

        strict = NetworkQualityGate(
            topology_reference=tiny, known_regimes=("calm",), require_topology=True
        ).evaluate(job_id="job-tiny-2", live_layers=[ring(6)], regime_label="calm")
        assert strict.verified is False
        assert "topology_reference_undersized" in {
            check.name for check in strict.failures
        }

    def test_minimum_reference_size_validation(self):
        from backend.modules.data.network_gate import minimum_reference_size

        with pytest.raises(ValueError, match="alpha"):
            minimum_reference_size(0.0, 5)
        with pytest.raises(ValueError, match="n_components"):
            minimum_reference_size(0.01, 0)
        # Fewer components means fewer tests, so a smaller reference suffices.
        assert minimum_reference_size(0.05, 4) < minimum_reference_size(0.01, 5)
        assert minimum_reference_size(0.01, 1) < minimum_reference_size(0.01, 5)

    def test_threshold_is_derived_from_the_training_distribution(self):
        reference = self._reference()
        assessment = reference.assess(GraphSignature.from_layer(ring(6, weight=1.2)))
        # Bonferroni over the number of components tested.
        assert assessment.threshold == pytest.approx(reference.alpha / len(assessment.p_values))

    def test_validation(self):
        with pytest.raises(ValueError, match="at least one signature"):
            TopologyReference([])
        with pytest.raises(ValueError, match="alpha"):
            TopologyReference([GraphSignature.from_layer(ring(4))], alpha=0.0)


class TestIntervalWidthReference:
    def test_threshold_is_the_empirical_quantile(self):
        widths = list(range(1, 101))
        reference = IntervalWidthReference(widths, level=0.9)
        # method="higher" rounds up, so the 0.9 quantile of 1..100 is the 91st
        # value, not the 90th. Rounding up is the intended direction: the ceiling
        # should be conservative rather than permissive.
        assert reference.threshold == pytest.approx(91.0)

    def test_exceeded_detection(self):
        reference = IntervalWidthReference(list(range(1, 101)), level=0.9)
        assert reference.assess(50.0)["exceeded"] is False
        assert reference.assess(95.0)["exceeded"] is True
        assert reference.assess(95.0)["ratio"] > 1.0

    def test_validation(self):
        with pytest.raises(ValueError, match="at least one"):
            IntervalWidthReference([])
        with pytest.raises(ValueError, match="non-finite"):
            IntervalWidthReference([1.0, float("nan")])
        with pytest.raises(ValueError, match="level"):
            IntervalWidthReference([1.0], level=1.0)

        reference = IntervalWidthReference([1.0, 2.0])
        with pytest.raises(ValueError, match="width"):
            reference.assess(-1.0)
        with pytest.raises(ValueError, match="width"):
            reference.assess(float("nan"))


class TestRegimeAssessment:
    def test_records_known_regimes(self):
        assessment = RegimeAssessment(
            label="crisis", known=False, is_transition=True, known_regimes=("calm", "stressed")
        )
        payload = assessment.to_dict()
        assert payload["known"] is False
        assert payload["known_regimes"] == ["calm", "stressed"]
        json.dumps(payload, allow_nan=False)


class TestNetworkQualityGate:
    _WEIGHTS = [1.0 + 0.02 * i for i in range(40)]

    def _gate(self, **kwargs):
        reference = TopologyReference(
            [GraphSignature.from_layer(ring(6, weight=w)) for w in self._WEIGHTS],
            alpha=0.01,
        )
        return NetworkQualityGate(
            topology_reference=reference,
            known_regimes=("calm", "elevated", "stressed"),
            width_reference=IntervalWidthReference(list(range(1, 101)), level=0.9),
            **kwargs,
        )

    def test_a_healthy_situation_verifies(self):
        attestation = self._gate().evaluate(
            job_id="job-1",
            live_layers=[ring(6, weight=1.25)],
            regime_label="calm",
            interval_width=10.0,
        )
        assert attestation.verified is True
        assert attestation.failures == []
        assert attestation.summary().startswith("Network conditions verified")

    def test_novel_topology_blocks(self):
        attestation = self._gate().evaluate(
            job_id="job-2",
            live_layers=[make_layer(np.zeros((6, 6)))],
            regime_label="calm",
            interval_width=10.0,
        )
        assert attestation.verified is False
        names = {check.name for check in attestation.failures}
        assert "topology_out_of_distribution" in names

    def test_unseen_regime_blocks(self):
        attestation = self._gate().evaluate(
            job_id="job-3",
            live_layers=[ring(6, weight=1.2)],
            regime_label="hyperinflation",
            interval_width=10.0,
        )
        assert attestation.verified is False
        assert "regime_unseen" in {check.name for check in attestation.failures}

    def test_overwide_interval_blocks(self):
        attestation = self._gate().evaluate(
            job_id="job-4",
            live_layers=[ring(6, weight=1.2)],
            regime_label="calm",
            interval_width=1_000.0,
        )
        assert attestation.verified is False
        assert "interval_width_exceeded" in {check.name for check in attestation.failures}

    def test_an_unknown_layer_name_is_treated_as_novel(self):
        attestation = self._gate().evaluate(
            job_id="job-5",
            live_layers=[ring(6, weight=1.2, name="brand_new_layer")],
            regime_label="calm",
            interval_width=10.0,
        )
        assert attestation.verified is False
        assert attestation.topology["is_novel"] is True

    def test_missing_reference_warns_by_default_but_blocks_when_required(self):
        permissive = NetworkQualityGate(known_regimes=("calm",)).evaluate(
            job_id="job-6", live_layers=[ring(4)], regime_label="calm"
        )
        assert permissive.verified is True
        assert "topology_reference_missing" in {check.name for check in permissive.checks}

        strict = NetworkQualityGate(
            known_regimes=("calm",), require_topology=True
        ).evaluate(job_id="job-7", live_layers=[ring(4)], regime_label="calm")
        assert strict.verified is False
        assert "topology_reference_missing" in {check.name for check in strict.failures}

    def test_missing_interval_width_warns_by_default_but_blocks_when_required(self):
        reference = IntervalWidthReference([1.0, 2.0, 3.0])
        permissive = NetworkQualityGate(
            width_reference=reference, known_regimes=("calm",)
        ).evaluate(job_id="job-8", live_layers=[], regime_label="calm")
        assert permissive.verified is True

        strict = NetworkQualityGate(
            width_reference=reference, known_regimes=("calm",), require_interval_width=True
        ).evaluate(job_id="job-9", live_layers=[], regime_label="calm")
        assert strict.verified is False
        assert "interval_width_missing" in {check.name for check in strict.failures}

    def test_regime_unreported_is_a_warning_not_a_pass_hidden_in_silence(self):
        attestation = NetworkQualityGate().evaluate(job_id="job-10", live_layers=[])
        names = {check.name for check in attestation.checks}
        assert "regime_unreported" in names
        check = next(c for c in attestation.checks if c.name == "regime_unreported")
        assert check.severity == "warning"
        assert "does not cover regime" in check.detail

    def test_verdict_is_negative_if_any_single_check_fails(self):
        # Three healthy conditions and one broken one must still block.
        attestation = self._gate().evaluate(
            job_id="job-11",
            live_layers=[ring(6, weight=1.2)],
            regime_label="unseen",
            interval_width=10.0,
        )
        assert attestation.verified is False
        assert len(attestation.failures) == 1

    def test_require_raises_when_attestation_is_missing(self):
        with pytest.raises(PredictionBlockedError, match="no network-condition attestation"):
            NetworkQualityGate.require(None)

    def test_require_raises_when_verdict_is_negative(self):
        attestation = NetworkQualityGate(known_regimes=("calm",)).evaluate(
            job_id="job-12", live_layers=[], regime_label="unseen"
        )
        assert attestation.verified is False
        with pytest.raises(PredictionBlockedError, match="failed verification"):
            NetworkQualityGate.require(attestation)

    def test_require_returns_the_attestation_when_positive(self):
        attestation = self._gate().evaluate(
            job_id="job-13",
            live_layers=[ring(6, weight=1.2)],
            regime_label="calm",
            interval_width=10.0,
        )
        assert NetworkQualityGate.require(attestation) is attestation


class TestAttestationRecord:
    def _attestation(self, width=10.0, regime="calm"):
        reference = TopologyReference(
            [GraphSignature.from_layer(ring(6, weight=w)) for w in (1.0 + 0.02 * i for i in range(40))],
            alpha=0.01,
        )
        return NetworkQualityGate(
            topology_reference=reference,
            known_regimes=("calm", "stressed"),
            width_reference=IntervalWidthReference(list(range(1, 101)), level=0.9),
        ).evaluate(
            job_id="job-14",
            live_layers=[ring(6, weight=1.2)],
            regime_label=regime,
            interval_width=width,
            checked_at="2024-01-01T00:00:00Z",
        )

    def test_attestation_id_is_content_addressed(self):
        first = self._attestation()
        second = self._attestation()
        assert first.attestation_id == second.attestation_id
        assert first.attestation_id.startswith("sha256:")

    def test_attestation_id_changes_with_the_verdict(self):
        healthy = self._attestation(width=10.0)
        broken = self._attestation(width=1_000.0)
        assert healthy.verified is True
        assert broken.verified is False
        assert healthy.attestation_id != broken.attestation_id

    def test_round_trips_through_dict(self):
        original = self._attestation()
        rebuilt = NetworkAttestation.from_dict(original.to_dict())
        assert rebuilt.verified == original.verified
        assert rebuilt.job_id == original.job_id
        assert rebuilt.attestation_id == original.attestation_id
        assert len(rebuilt.checks) == len(original.checks)

    def test_serialises_to_json(self):
        json.dumps(self._attestation().to_dict(), allow_nan=False)

    def test_summary_names_the_failures(self):
        broken = self._attestation(width=1_000.0)
        summary = broken.summary()
        assert "rejected" in summary
        assert "interval_width_exceeded" in summary

    def test_payload_carries_the_measurements_not_just_the_verdict(self):
        payload = self._attestation().to_dict()
        assert payload["topology"]["aggregate_p_value"] is not None
        assert payload["regime"]["label"] == "calm"
        assert payload["interval_width"]["width"] == pytest.approx(10.0)


class TestKnownLimitation:
    def test_summary_distributions_are_blind_to_relabelling(self):
        """A recorded gap in the method, not a passing grade.

        The distance compares 1-D summary distributions. Permuting node labels
        leaves every one of them unchanged, so a re-wiring that preserves the
        degree sequence, strength distribution, edge weights and spectrum is
        invisible to this gate. Catching that requires optimal transport between
        the graphs themselves (or a spectral embedding that is not permutation
        invariant), which is not implemented here.

        This test exists so the limitation is pinned in code rather than relying
        on someone reading the module docstring.
        """
        size = 6
        original = np.zeros((size, size))
        for i in range(size):
            original[i, (i + 1) % size] = 1.0

        permutation = np.array([3, 0, 5, 1, 4, 2])
        rewired = original[np.ix_(permutation, permutation)]

        assert not np.allclose(original, rewired), "the rewire must actually change edges"

        first = GraphSignature.from_layer(make_layer(original))
        second = GraphSignature.from_layer(make_layer(rewired))

        # `size` is included: relabelling preserves the node count too, so it
        # offers no protection against this particular blindness.
        for component in (
            "edge_weights",
            "node_strengths",
            "degrees",
            "spectrum",
            "size",
        ):
            left = np.sort(first.components()[component])
            right = np.sort(second.components()[component])
            assert np.allclose(left, right), (
                f"{component} changed under relabelling, so the blindness claim is wrong"
            )

        assert wasserstein_1d(first.node_strengths, second.node_strengths) == pytest.approx(0.0)

    def test_but_a_real_structural_change_is_detected(self):
        """The complement of the blindness test: change that must be caught, is."""
        reference = TopologyReference(
            [GraphSignature.from_layer(ring(6, weight=w)) for w in (1.0 + 0.02 * i for i in range(40))],
            alpha=0.01,
        )
        hub = np.zeros((6, 6))
        for i in range(1, 6):
            hub[0, i] = 1.0  # a star instead of a ring

        assessment = reference.assess(GraphSignature.from_layer(make_layer(hub)))
        assert assessment.is_novel is True


class TestDeterminism:
    def test_repeated_assessment_is_identical(self):
        reference = TopologyReference(
            [GraphSignature.from_layer(ring(6, weight=w)) for w in (1.0 + 0.02 * i for i in range(40))],
            alpha=0.01,
        )
        signature = GraphSignature.from_layer(ring(6, weight=1.1))
        first = reference.assess(signature)
        second = reference.assess(signature)
        assert first.distances == second.distances
        assert first.p_values == second.p_values
        assert first.is_novel == second.is_novel


class TestFragmentationGate:
    """The TDA signal reaching the gate, which the integration test showed was missing.

    The topology test compares summary *distributions* against training snapshots --
    it detects drift. It says nothing about whether the network has split into
    components that cannot pass stress to each other, which is a different failure:
    a network can drift barely at all while breaking in two. These tests cover the
    fragmentation path that closes that gap.
    """

    def _reference(self):
        return FragmentationReference([0.0, 0.0, 0.1, 0.1, 0.2], level=0.9)

    def test_threshold_is_the_empirical_quantile(self):
        assert self._reference().threshold == pytest.approx(0.2)

    def test_an_intact_network_passes(self):
        gate = NetworkQualityGate(fragmentation_reference=self._reference())
        attestation = gate.evaluate(job_id="f1", fragmentation=0.05)
        assert "fragmentation_ok" in {c.name for c in attestation.checks}

    def test_a_split_network_blocks(self):
        gate = NetworkQualityGate(fragmentation_reference=self._reference())
        attestation = gate.evaluate(job_id="f2", fragmentation=0.75)
        assert attestation.verified is False
        assert "fragmentation_exceeded" in {c.name for c in attestation.failures}

    def test_the_reason_names_the_split(self):
        gate = NetworkQualityGate(fragmentation_reference=self._reference())
        detail = next(
            c.detail for c in gate.evaluate(job_id="f3", fragmentation=0.9).checks
            if c.name == "fragmentation_exceeded"
        )
        assert "split" in detail

    def test_missing_reference_warns_by_default_and_blocks_when_required(self):
        permissive = NetworkQualityGate().evaluate(job_id="f4", fragmentation=0.1)
        assert permissive.verified is True
        assert "fragmentation_reference_missing" in {c.name for c in permissive.checks}

        strict = NetworkQualityGate(require_fragmentation=True).evaluate(
            job_id="f5", fragmentation=0.1
        )
        assert strict.verified is False
        assert "fragmentation_reference_missing" in {c.name for c in strict.failures}

    def test_missing_value_warns_by_default_and_blocks_when_required(self):
        gate = NetworkQualityGate(fragmentation_reference=self._reference())
        assert gate.evaluate(job_id="f6").verified is True
        strict = NetworkQualityGate(
            fragmentation_reference=self._reference(), require_fragmentation=True
        )
        assert strict.evaluate(job_id="f7").verified is False

    def test_payload_carries_the_measurement(self):
        gate = NetworkQualityGate(fragmentation_reference=self._reference())
        payload = gate.evaluate(job_id="f8", fragmentation=0.15).to_dict()
        assert payload["fragmentation"]["fragmentation"] == pytest.approx(0.15)
        json.dumps(payload, allow_nan=False)

    def test_round_trips_through_dict(self):
        gate = NetworkQualityGate(fragmentation_reference=self._reference())
        original = gate.evaluate(job_id="f9", fragmentation=0.15, checked_at="2024-01-01T00:00:00Z")
        rebuilt = NetworkAttestation.from_dict(original.to_dict())
        assert rebuilt.fragmentation == original.fragmentation
        assert rebuilt.attestation_id == original.attestation_id

    def test_reference_validation(self):
        with pytest.raises(ValueError, match="at least one value"):
            FragmentationReference([])
        with pytest.raises(ValueError, match="non-finite"):
            FragmentationReference([0.1, float("nan")])
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            FragmentationReference([1.5])
        with pytest.raises(ValueError, match="level"):
            FragmentationReference([0.1], level=1.0)

        reference = FragmentationReference([0.1])
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            reference.assess(1.5)
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            reference.assess(float("nan"))


class TestFragmentationFromPersistentHomology:
    def test_a_real_betti_0_share_drives_the_gate(self):
        """The composition that was missing: TDA output into the gate.

        ``topological_signature(...).fragmentation`` is the share of nodes outside
        the largest component, which is exactly what the gate's ceiling wants.
        """
        from backend.modules.engine.persistent_homology import topological_signature

        # `ring` here returns a MultiplexLayer, so the TDA takes its adjacency.
        intact = ring(6).adjacency.copy()
        broken = intact.copy()
        broken[0, 1] = broken[1, 0] = 0.0
        broken[3, 4] = broken[4, 3] = 0.0

        intact_signature = topological_signature(intact, reference="zero")
        broken_signature = topological_signature(broken, reference="zero")
        assert broken_signature.fragmentation > intact_signature.fragmentation

        gate = NetworkQualityGate(
            fragmentation_reference=FragmentationReference(
                [intact_signature.fragmentation], level=0.99
            )
        )
        assert gate.evaluate(job_id="t1", fragmentation=intact_signature.fragmentation).verified is True
        split = gate.evaluate(job_id="t2", fragmentation=broken_signature.fragmentation)
        assert split.verified is False
        assert "fragmentation_exceeded" in {c.name for c in split.failures}
