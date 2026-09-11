"""End-to-end composition across the rebuilt phases.

Each module has its own suite; this one exists to catch the failures those cannot
-- interface mismatches where two modules are individually correct and mutually
incompatible. It drives one synthetic stress episode through the whole stack in the
order the system actually runs it:

    streaming -> PIT -> fractional differencing -> multiplex
        -> foundation encoders -> temporal graph -> regime (HMM + TDA)
        -> MoE routing -> clearing -> liquidity spiral
        -> network gate + conformal + uncertainty

Nothing here is mocked. Every step calls the real module, so a signature change is a
test failure rather than a runtime surprise.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.modules.data.fractional import frac_diff
from backend.modules.data.network_gate import (
    IntervalWidthReference,
    NetworkQualityGate,
    TopologyReference,
)
from backend.modules.data.pit import Observation, PITStore
from backend.modules.data.streaming import (
    MarketEvent,
    TumblingWindowAggregator,
)
from backend.modules.engine.conformal import SplitConformalCalibrator
from backend.modules.engine.foundation_encoders import HashedFallbackEncoder, compose_input
from backend.modules.engine.hidden_markov import GaussianHMM
from backend.modules.engine.mixture_of_experts import (
    REGIME_ORDER,
    MixtureOfExperts,
    RegimeSignal,
)
from backend.modules.engine.multiplex import (
    RelationKind,
    build_interbank_exposure_layer,
    require_exposure,
)
from backend.modules.engine.persistent_homology import topological_signature
from backend.modules.engine.temporal_graph import TemporalGraphNetwork
from backend.modules.engine.uncertainty import (
    DeepEnsemble,
    assess_uncertainty,
)
from backend.modules.risk.clearing import clear_multiplex
from backend.modules.risk.liquidity_spiral import LiquiditySpiralModel, SpiralParameters

NS_PER_SECOND = 1_000_000_000


class _ConstMember:
    """Stand-in ensemble member returning a constant prediction."""

    def __init__(self, value: float, variance: float) -> None:
        self.value = float(value)
        self.variance = float(variance)

    def predict(self, X):
        size = len(X) if hasattr(X, "__len__") else 1
        return np.full(size, self.value, dtype=float)


def test_the_whole_stack_composes_on_one_stress_episode():
    rng = np.random.default_rng(20260901)
    institutions = ["BANK_A", "BANK_B", "BANK_C", "FUND_D"]
    n_steps = 400

    # --- 1. event-time ingestion -------------------------------------------------
    aggregator = TumblingWindowAggregator(
        width_ns=100 * NS_PER_SECOND, allowed_lateness_ns=20 * NS_PER_SECOND
    )
    for index, name in enumerate(institutions):
        for step in range(60):
            aggregator.add(
                MarketEvent(
                    instrument=name,
                    event_time_ns=(step * 5) * NS_PER_SECOND,
                    value=float(100 + index * 10 + rng.normal(scale=0.4)),
                )
            )
    assert aggregator.metrics.events_received == 240
    assert aggregator.tracker.watermark_ns is not None
    # Ingestion must not have silently dropped anything under the default policy.
    assert aggregator.metrics.events_dropped == 0

    # --- 2. point-in-time store --------------------------------------------------
    store = PITStore()
    store.append(
        [
            Observation(
                entity_id="US",
                series_id="GDP",
                valid_time=pd.Timestamp("2020-01-01"),
                observed_at=pd.Timestamp("2020-04-30"),
                value=100.0,
                revision=0,
            ),
            Observation(
                entity_id="US",
                series_id="GDP",
                valid_time=pd.Timestamp("2020-01-01"),
                observed_at=pd.Timestamp("2020-06-25"),
                value=90.0,
                revision=2,
            ),
        ]
    )
    early = store.query("US", "GDP", as_of=pd.Timestamp("2020-05-15"))
    late = store.query("US", "GDP", as_of=pd.Timestamp("2020-06-30"))
    # The restated value must not be visible before it was published.
    assert float(early["value"].iloc[0]) == 100.0
    assert float(late["value"].iloc[0]) == 90.0

    # --- 3. fractional differencing ---------------------------------------------
    levels = np.cumsum(rng.normal(scale=0.5, size=(len(institutions), n_steps)), axis=1) + 100.0
    fractional = np.vstack([frac_diff(row, 0.4) for row in levels])
    assert fractional.shape == levels.shape
    assert np.all(np.isfinite(fractional))

    # --- 4. multiplex construction ----------------------------------------------
    exposures = pd.DataFrame(
        {
            "debtor": ["BANK_A", "BANK_B", "BANK_C"],
            "creditor": ["BANK_B", "BANK_C", "BANK_A"],
            "amount": [40.0, 25.0, 30.0],
        }
    )
    layer = build_interbank_exposure_layer(
        exposures, institutions, as_of=pd.Timestamp("2024-01-01")
    )
    assert layer.is_clearing_eligible and layer.kind is RelationKind.EXPOSURE
    signature = topological_signature(layer, reference="zero")
    assert signature.beta_1 >= 1  # a ring has at least one independent cycle

    # --- 5. foundation encoders --------------------------------------------------
    encoder = HashedFallbackEncoder(embed_dim=32, seed=3)
    encoder_input = compose_input(levels)
    node_features = encoder.encode(encoder_input)
    assert node_features.shape == (len(institutions), 32)
    assert encoder.provenance.is_pretrained is False  # the stand-in says so

    # --- 6. temporal graph -------------------------------------------------------
    tgn = TemporalGraphNetwork(
        n_nodes=len(institutions), node_feature_dim=32, memory_dim=16, message_dim=16, seed=4
    )
    for step in range(40):
        for index in range(len(institutions)):
            tgn.process_event(
                source=index,
                target=(index + 1) % len(institutions),
                time=float(step),
                features=node_features[index][:32],
            )
        for index in range(len(institutions)):
            tgn.flush(index)
    embedding = tgn.embed(0, 40.0)
    assert embedding.shape == (16,)
    assert bool(np.isfinite(embedding.detach().numpy()).all())

    # --- 7. regime detection: statistical and topological ------------------------
    stress = np.concatenate([rng.normal(-4, 1, 200), rng.normal(4, 1, 200)]).reshape(-1, 1)
    hmm = GaussianHMM(n_states=2, n_features=1, seed=5)
    hmm.fit(stress, max_iterations=40)
    labels = hmm.label_series(stress, labels=("calm", "crisis"))
    assert set(np.unique(labels)) <= {"calm", "crisis"}
    statistical_regime = str(labels[-1])
    assert statistical_regime in REGIME_ORDER

    # --- 8. MoE routing on the regime signal -------------------------------------
    mixture = MixtureOfExperts(
        input_dim=16, output_dim=4, n_experts=4, hidden_dim=16, top_k=1, seed=6
    )
    routed = mixture.forward(embedding.detach().unsqueeze(0), RegimeSignal(statistical_regime))
    assert routed.output.shape == (1, 4)
    assert float(routed.gate_weights.sum().detach()) == pytest.approx(1.0, abs=1e-6)

    # --- 9. clearing on the real exposure layer ----------------------------------
    endowments = [float(levels[i, -1]) for i in range(len(institutions))]
    clearing = clear_multiplex([require_exposure(layer)], endowments, node_ids=institutions)
    assert clearing.converged
    assert clearing.payments.shape[0] == len(institutions)
    assert np.all(clearing.payments <= clearing.nominal_liabilities + 1e-6)

    # --- 10. liquidity spiral ----------------------------------------------------
    spiral = LiquiditySpiralModel(
        SpiralParameters(price=100.0, position=100.0, capital=1500.0, margin=0.15, price_impact=0.01)
    ).cascade(-1.0)
    assert spiral.amplification >= 1.0
    assert np.isfinite(spiral.total_price_change)

    # --- 11. conformal and uncertainty -------------------------------------------
    residuals = rng.normal(scale=2.0, size=2000)
    conformal = SplitConformalCalibrator(alpha=0.1).fit(residuals, np.zeros(2000))
    interval = conformal.interval(0.0)
    assert interval.is_finite and interval.width > 0

    ensemble = DeepEnsemble(
        [_ConstMember(1.0, 0.25), _ConstMember(1.2, 0.25)],
        member_variance_fn=lambda member, X: np.full(len(X), member.variance),
    )
    decomposition = ensemble.decompose_one(np.zeros((1, 1)))
    verdict = assess_uncertainty(decomposition)
    assert isinstance(verdict.reliable, bool)

    # --- 12. network gate --------------------------------------------------------
    # Two complementary topology tests meet the gate here.
    #
    # TopologyReference compares summary DISTRIBUTIONS against training snapshots
    # and so detects drift; it takes network_gate.GraphSignature (edge weights, node
    # strengths, degrees, spectrum). FragmentationReference consumes the TDA output
    # -- the share of nodes outside the largest component -- and so detects the
    # network SPLITTING, which is a different failure: a network can drift barely at
    # all while breaking into pieces that cannot pass stress between them.
    #
    # An earlier version of this file claimed these were two classes both named
    # GraphSignature. That was wrong: persistent_homology exports TopologicalSignature,
    # not GraphSignature, and there is no name collision. The real gap the test
    # exposed was that the gate had no fragmentation input at all, which is now closed.
    from backend.modules.data.network_gate import FragmentationReference
    from backend.modules.data.network_gate import GraphSignature as GateSignature

    reference = TopologyReference([GateSignature.from_layer(layer)], alpha=0.05)
    fragmentation_reference = FragmentationReference([signature.fragmentation], level=0.99)
    gate = NetworkQualityGate(
        topology_reference=reference,
        fragmentation_reference=fragmentation_reference,
        known_regimes=("calm", "elevated", "stressed", "crisis"),
        width_reference=IntervalWidthReference([interval.width * 2.0], level=0.9),
        # One reference snapshot is far too few to reject novelty, so the gate must
        # be told to treat "cannot measure" as a warning rather than silently
        # certifying a topology it cannot compare.
        require_topology=False,
    )
    # Rebuild the reference on the same layer shape the gate will see.
    attestation = gate.evaluate(
        job_id="integration",
        live_layers=[layer],
        regime_label=statistical_regime,
        interval_width=interval.width,
        fragmentation=signature.fragmentation,
    )
    assert attestation.verified is True
    assert attestation.attestation_id.startswith("sha256:")
    assert "topology_reference_undersized" in {check.name for check in attestation.checks}
    # The TDA signal reached the gate and was evaluated.
    assert "fragmentation_ok" in {check.name for check in attestation.checks}
    assert attestation.fragmentation["fragmentation"] == pytest.approx(signature.fragmentation)
