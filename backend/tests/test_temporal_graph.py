"""Tests for the Temporal Graph Network with Neural ODEs.

The ODE is the part with checkable answers, so it is checked against analytic
solutions and against its own convergence order -- a misimplemented integrator
does not accidentally produce fourth-order convergence. The memory is then checked
end to end by zeroing the learned part of the vector field, which reduces it to a
pure linear decay whose closed form is known, so the wiring between the solver and
the per-node state is verified rather than assumed.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
import torch

from backend.modules.engine.temporal_graph import (
    NeuralODEField,
    TemporalGraphMemory,
    TemporalGraphNetwork,
    TimeEncoder,
    exponential_decay,
    rk4_integrate,
)


def linear_field(state, time):
    return -state


def quadratic_field(state, time):
    return state ** 2


class TestRK4AgainstAnalyticSolutions:
    def test_linear_decay_matches_the_exponential(self):
        """``dz/dt = -z`` from 0 to T is ``exp(-T)``.

        The tolerance is set from the observed truncation error rather than
        guessed: at 256 steps the worst relative error over these horizons is
        6.2e-9, so 1e-7 leaves an order of magnitude of margin while still being
        far too tight for a misimplemented scheme to satisfy. The convergence-order
        test below is what establishes that the scheme is genuinely fourth order;
        this one establishes that it is solving the right equation.
        """
        z0 = torch.tensor([1.0], dtype=torch.float64)
        for horizon in (0.5, 1.0, 2.0, 5.0):
            result = rk4_integrate(linear_field, z0, 0.0, horizon, 256)
            assert result.item() == pytest.approx(math.exp(-horizon), rel=1e-7), horizon

    def test_nonlinear_field_matches_its_closed_form(self):
        """``dz/dt = z^2`` with ``z(0)=1`` is ``1 / (1 - t)``.

        Checking a nonlinear field matters because agreement on a linear one could
        be an artefact of linearity.
        """
        z0 = torch.tensor([1.0], dtype=torch.float64)
        for horizon in (0.1, 0.3, 0.5):
            result = rk4_integrate(quadratic_field, z0, 0.0, horizon, 256)
            assert result.item() == pytest.approx(1.0 / (1.0 - horizon), rel=1e-8), horizon

    def test_convergence_order_is_four(self):
        """Halving the step must cut the error roughly sixteenfold.

        This is the check that distinguishes a fourth-order scheme from a
        first-order one that happens to be accurate at small steps.
        """
        z0 = torch.tensor([1.0], dtype=torch.float64)
        exact = math.exp(-2.0)

        errors = []
        for steps in (4, 8, 16, 32):
            result = rk4_integrate(linear_field, z0, 0.0, 2.0, steps)
            errors.append(abs(result.item() - exact))

        for previous, current in zip(errors, errors[1:]):
            order = math.log2(previous / current)
            assert 3.8 < order < 4.5, f"observed order {order}"

    def test_a_round_trip_returns_to_the_start(self):
        z0 = torch.tensor([1.0], dtype=torch.float64)
        forward = rk4_integrate(linear_field, z0, 0.0, 3.0, 64)
        back = rk4_integrate(linear_field, forward, 3.0, 0.0, 64)
        assert back.item() == pytest.approx(1.0, rel=1e-6)

    def test_zero_horizon_returns_the_input(self):
        z0 = torch.tensor([2.0], dtype=torch.float64)
        assert rk4_integrate(linear_field, z0, 1.0, 1.0, 8).item() == pytest.approx(2.0)

    def test_matches_the_closed_form_decay_helper(self):
        z0 = torch.tensor([1.5, -0.5], dtype=torch.float64)
        rate, interval = 0.7, 1.3
        numeric = rk4_integrate(
            lambda z, t: -rate * z, z0, 0.0, interval, 128
        )
        closed = exponential_decay(z0, interval, rate)
        assert torch.allclose(numeric, closed, rtol=1e-10)

    def test_invalid_step_count_is_rejected(self):
        z0 = torch.tensor([1.0], dtype=torch.float64)
        with pytest.raises(ValueError, match="steps"):
            rk4_integrate(linear_field, z0, 0.0, 1.0, 0)

    def test_negative_interval_is_rejected_by_the_decay_helper(self):
        with pytest.raises(ValueError, match="non-negative"):
            exponential_decay(torch.tensor([1.0]), -1.0, 0.5)


class TestTimeEncoder:
    def test_output_dimension_is_twice_the_frequency_count(self):
        encoder = TimeEncoder(dim=5)
        assert encoder.output_dim == 10
        assert encoder(torch.tensor([1.0])).shape == (1, 10)

    def test_zero_interval_encodes_to_ones_and_zeros(self):
        encoder = TimeEncoder(dim=4)
        encoded = encoder(torch.tensor([0.0])).reshape(-1)
        cosines = encoded[:4]
        sines = encoded[4:]
        assert torch.allclose(cosines, torch.ones(4))
        assert torch.allclose(sines, torch.zeros(4))

    def test_different_intervals_encode_differently(self):
        encoder = TimeEncoder(dim=6)
        first = encoder(torch.tensor([0.1])).reshape(-1)
        second = encoder(torch.tensor([10.0])).reshape(-1)
        assert not torch.allclose(first, second)

    def test_encoding_is_bounded(self):
        # Fourier features lie in [-1, 1]; an unbounded encoding would let a long
        # interval dominate every other input to the model.
        encoder = TimeEncoder(dim=6)
        encoded = encoder(torch.linspace(0.0, 1e6, 50))
        assert float(encoded.abs().max()) <= 1.0 + 1e-6

    def test_geometric_frequencies_span_several_decades(self):
        encoder = TimeEncoder(dim=6, base=1.0, growth=10.0)
        frequencies = encoder.frequencies.numpy()
        assert frequencies[0] == pytest.approx(1.0)
        assert frequencies[-1] == pytest.approx(1e5)
        assert np.all(np.diff(frequencies) > 0)

    def test_negative_interval_is_rejected(self):
        encoder = TimeEncoder(dim=4)
        with pytest.raises(ValueError, match="non-negative"):
            encoder(torch.tensor([-1.0]))

    def test_validation(self):
        with pytest.raises(ValueError, match="dim"):
            TimeEncoder(dim=0)
        with pytest.raises(ValueError, match="base"):
            TimeEncoder(base=0.0)
        with pytest.raises(ValueError, match="growth"):
            TimeEncoder(growth=1.0)


def decay_only_memory(n_nodes: int, memory_dim: int, rate: float) -> TemporalGraphMemory:
    """A memory whose vector field is exactly ``-rate * z``.

    Zeroing the learned network leaves the analytic decay term alone, which turns
    the memory into a system with a known closed-form solution. That makes the
    wiring between solver and per-node state checkable end to end rather than only
    in the abstract.
    """
    field = NeuralODEField(memory_dim, rate=rate)
    with torch.no_grad():
        for parameter in field.net.parameters():
            parameter.zero_()
    return TemporalGraphMemory(n_nodes, memory_dim=memory_dim, field=field, integration_steps=64)


class TestMemoryEvolution:
    def test_memory_evolves_continuously_without_any_event(self):
        """The property the batch model could not have.

        A node observed once must not be frozen until its next observation; its
        state is defined and moving at every instant in between.
        """
        memory = decay_only_memory(1, 4, rate=0.5)
        memory.write(0, torch.ones(4), time=0.0)

        at_zero = memory.read(0, 0.0).memory
        at_one = memory.read(0, 1.0).memory
        at_two = memory.read(0, 2.0).memory

        assert not torch.allclose(at_zero, at_one)
        assert not torch.allclose(at_one, at_two)

    def test_the_evolution_matches_the_analytic_decay(self):
        rate = 0.4
        memory = decay_only_memory(1, 3, rate=rate)
        memory.write(0, torch.tensor([1.0, 2.0, 3.0]), time=0.0)

        for interval in (0.25, 1.0, 3.0):
            evolved = memory.read(0, interval).memory
            expected = exponential_decay(torch.tensor([1.0, 2.0, 3.0]), interval, rate)
            assert torch.allclose(evolved, expected, rtol=1e-6), interval

    def test_evolving_the_store_matches_reading(self):
        memory = decay_only_memory(2, 4, rate=0.3)
        memory.write(0, torch.ones(4), time=0.0)
        memory.write(1, torch.full((4,), 2.0), time=0.0)

        read_value = memory.read(0, 1.0).memory
        memory.evolve_to(1.0)
        assert torch.allclose(memory.memory[0], read_value, rtol=1e-6)

    def test_reading_does_not_mutate_the_store(self):
        memory = decay_only_memory(1, 4, rate=0.3)
        memory.write(0, torch.ones(4), time=0.0)
        before = memory.memory[0].clone()
        last_before = float(memory.last_time[0].item())

        _ = memory.read(0, 5.0)

        assert torch.allclose(memory.memory[0], before)
        assert float(memory.last_time[0].item()) == last_before

    def test_read_reports_the_interval_it_evolved_over(self):
        memory = decay_only_memory(1, 4, rate=0.3)
        memory.write(0, torch.ones(4), time=1.0)
        state = memory.read(0, 4.0)

        assert state.evolved_interval == pytest.approx(3.0)
        assert state.last_update_time == pytest.approx(1.0)
        assert state.time == pytest.approx(4.0)

    def test_asking_for_an_earlier_time_does_not_integrate_backwards(self):
        memory = decay_only_memory(1, 4, rate=0.3)
        memory.write(0, torch.ones(4), time=5.0)
        state = memory.read(0, 2.0)

        assert state.evolved_interval == pytest.approx(0.0)
        assert torch.allclose(state.memory, torch.ones(4))

    def test_stale_nodes_are_reported(self):
        memory = decay_only_memory(3, 4, rate=0.3)
        memory.write(0, torch.ones(4), time=1.0)
        memory.write(1, torch.ones(4), time=9.0)
        # Node 2 is never written, so it is not stale -- it is simply unobserved.
        assert memory.stale_nodes(5.0) == [1]

    def test_unobserved_node_reads_as_zero(self):
        memory = decay_only_memory(2, 4, rate=0.3)
        state = memory.read(0, 10.0)
        assert torch.allclose(state.memory, torch.zeros(4))
        assert state.evolved_interval == pytest.approx(0.0)

    def test_reset_clears_everything(self):
        memory = decay_only_memory(2, 4, rate=0.3)
        memory.write(0, torch.ones(4), time=1.0)
        memory.reset()
        assert torch.allclose(memory.memory, torch.zeros(2, 4))
        assert memory.stale_nodes(100.0) == []

    def test_validation(self):
        with pytest.raises(ValueError, match="n_nodes"):
            TemporalGraphMemory(0)
        with pytest.raises(ValueError, match="memory_dim"):
            TemporalGraphMemory(2, memory_dim=0)
        with pytest.raises(ValueError, match="integration_steps"):
            TemporalGraphMemory(2, memory_dim=4, integration_steps=0)

        memory = decay_only_memory(2, 4, rate=0.3)
        with pytest.raises(ValueError, match="outside"):
            memory.write(5, torch.ones(4), time=0.0)
        with pytest.raises(ValueError, match="outside"):
            memory.read(5, 0.0)
        with pytest.raises(ValueError, match="shape"):
            memory.write(0, torch.ones(7), time=0.0)

    def test_state_serialises(self):
        memory = decay_only_memory(1, 4, rate=0.3)
        memory.write(0, torch.ones(4), time=0.0)
        json.dumps(memory.read(0, 1.0).to_dict(), allow_nan=False)


class TestVectorField:
    def test_a_zero_network_reduces_the_field_to_decay(self):
        field = NeuralODEField(4, rate=0.25)
        with torch.no_grad():
            for parameter in field.net.parameters():
                parameter.zero_()

        state = torch.tensor([[1.0, 2.0, 3.0, 4.0]])
        derivative = field(state, torch.tensor([0.0]))
        assert torch.allclose(derivative, -0.25 * state, atol=1e-6)

    def test_the_learned_part_is_used_when_it_is_not_zero(self):
        field = NeuralODEField(4, rate=0.25, hidden_dim=8)
        state = torch.tensor([[1.0, 2.0, 3.0, 4.0]])
        derivative = field(state, torch.tensor([0.0]))
        assert not torch.allclose(derivative, -0.25 * state, atol=1e-6)

    def test_a_positive_rate_is_required(self):
        # A zero rate would let the memory learn to stop moving, reproducing the
        # staleness the ODE exists to remove.
        with pytest.raises(ValueError, match="rate"):
            NeuralODEField(4, rate=0.0)


class TestTemporalGraphNetwork:
    def _network(self, seed: int = 1) -> TemporalGraphNetwork:
        return TemporalGraphNetwork(
            n_nodes=6, node_feature_dim=3, memory_dim=16, message_dim=12, seed=seed
        )

    def test_an_event_updates_the_target_memory(self):
        network = self._network()
        before = network.memory.memory[1].clone()
        network.process_event(0, 1, 0.0, [0.1, 0.2, 0.3])
        after = network.flush(1)
        assert not torch.allclose(before, after)

    def test_aggregation_averages_rather_than_accumulates(self):
        """More events of the same kind must not push further than one.

        A sum would make a node's memory depend on how many messages arrived, so a
        burst of identical observations would move it arbitrarily far.
        """
        single = self._network(seed=3)
        single.process_event(0, 1, 0.0, [1.0, 0.0, 0.0])
        first = single.flush(1)

        repeated = self._network(seed=3)
        for _ in range(5):
            repeated.process_event(0, 1, 0.0, [1.0, 0.0, 0.0])
        second = repeated.flush(1)

        assert torch.allclose(first, second, atol=1e-6)

    def test_pending_messages_are_cleared_on_flush(self):
        network = self._network()
        network.process_event(0, 1, 0.0, [0.0, 0.0, 0.0])
        assert network.pending_count(1) == 1
        network.flush(1)
        assert network.pending_count(1) == 0

    def test_flush_with_nothing_pending_is_a_no_op(self):
        network = self._network()
        before = network.memory.memory[2].clone()
        after = network.flush(2)
        assert torch.allclose(before, after)

    def test_irregular_sampling_needs_no_common_grid(self):
        """The fusion the Neural ODE exists for.

        Node 1 is observed a thousand times over the same span in which node 5 is
        observed twice. Neither is resampled onto the other's grid: node 5's
        memory advances on its own clock, and the fast node's events do not touch
        it.
        """
        network = self._network()
        # Fast pair: a millisecond-spaced stream across [0, 1).
        for step in range(1000):
            network.process_event(0, 1, step * 0.001, [0.1, 0.2, 0.3])
        network.flush(1)
        # Slow pair: two observations a whole period apart.
        network.process_event(4, 5, 0.0, [0.9, 0.1, 0.0])
        slow_after_first = network.flush(5)

        # The fast node's traffic did not touch the slow node's clock.
        assert float(network.memory.last_time[5].item()) == pytest.approx(0.0)

        # But the slow node's state is defined and moving at any instant asked for.
        at_zero = network.memory.read(5, 0.0).memory
        at_half = network.memory.read(5, 0.5).memory
        at_one = network.memory.read(5, 1.0).memory

        assert torch.allclose(at_zero, slow_after_first, atol=1e-6)
        assert not torch.allclose(at_zero, at_half)
        assert not torch.allclose(at_half, at_one)

    def test_both_a_fast_and_a_slow_node_can_be_queried_at_the_same_instant(self):
        network = self._network()
        for step in range(50):
            network.process_event(0, 1, step * 0.02, [0.1, 0.2, 0.3])
        network.flush(1)
        network.process_event(4, 5, 0.0, [0.9, 0.1, 0.0])
        network.flush(5)

        fast = network.embed(1, 1.0)
        slow = network.embed(5, 1.0)
        assert fast.shape == slow.shape == (network.memory_dim,)
        assert not torch.allclose(fast, slow)

    def test_events_are_placed_by_timestamp_not_arrival_order(self):
        """Composes with the watermarking in the streaming module.

        An event carrying an earlier timestamp than one already seen is still
        stored against its own time, so the memory is a function of the event
        stream rather than of network jitter.
        """
        network = self._network()
        network.process_event(0, 1, 100.0, [1.0, 0.0, 0.0])
        network.flush(1)
        later_state = network.memory.read(1, 100.0).memory

        # A straggler for time 50 arrives afterwards.
        network.process_event(0, 1, 50.0, [1.0, 0.0, 0.0])
        network.flush(1)
        # The store's clock did not move backwards.
        assert float(network.memory.last_time[1].item()) == pytest.approx(100.0)
        assert not torch.allclose(network.memory.read(1, 100.0).memory, later_state)

    def test_gradients_flow_to_the_vector_field(self):
        network = self._network()
        network.process_event(0, 1, 0.0, [0.1, 0.2, 0.3])
        network.flush(1)
        embedding = network.embed(1, 1.0)
        embedding.sum().backward()

        gradients = [p.grad for p in network.memory.field.parameters() if p.grad is not None]
        assert gradients, "the vector field received no gradient"
        assert any(float(g.abs().sum()) > 0 for g in gradients)

    def test_prediction_is_reproducible_for_a_seed(self):
        first = self._network(seed=7)
        second = self._network(seed=7)
        for network in (first, second):
            network.process_event(0, 1, 0.0, [0.5, 0.5, 0.5])
            network.flush(1)
        assert first.decode(1, 1.0) == pytest.approx(second.decode(1, 1.0))

    def test_different_seeds_give_different_predictions(self):
        first = self._network(seed=1)
        second = self._network(seed=2)
        for network in (first, second):
            network.process_event(0, 1, 0.0, [0.5, 0.5, 0.5])
            network.flush(1)
        assert first.decode(1, 1.0) != pytest.approx(second.decode(1, 1.0))

    def test_validation(self):
        with pytest.raises(ValueError, match="node_feature_dim"):
            TemporalGraphNetwork(n_nodes=3, node_feature_dim=0)

        network = self._network()
        with pytest.raises(ValueError, match="outside"):
            network.process_event(99, 1, 0.0, [0.0, 0.0, 0.0])
        with pytest.raises(ValueError, match="features have"):
            network.process_event(0, 1, 0.0, [0.0, 0.0])

    def test_configuration_serialises(self):
        json.dumps(self._network().to_dict(), allow_nan=False)


class TestComposesWithTheEventStream:
    def test_a_streaming_event_feeds_the_temporal_graph(self):
        """The Phase 2 stream drives the Phase 3 model.

        The aggregator assigns events to windows on event time and reports a
        watermark; this consumes the same events. Nothing about the timing logic
        is reimplemented here, which is the point of the composition.
        """
        from backend.modules.data.streaming import MarketEvent, TumblingWindowAggregator

        instruments = {"SOFR": 0, "ESTR": 1, "CDS": 2}
        network = TemporalGraphNetwork(
            n_nodes=3, node_feature_dim=2, memory_dim=8, message_dim=8, seed=5
        )
        aggregator = TumblingWindowAggregator(width_ns=1_000, allowed_lateness_ns=200)

        events = [
            MarketEvent("SOFR", 0, 1.0),
            MarketEvent("ESTR", 100, 2.0),
            MarketEvent("CDS", 250, 3.0),
            MarketEvent("SOFR", 900, 4.0),
        ]
        aggregator.add_all(events)
        watermark = aggregator.tracker.watermark_ns
        assert watermark is not None

        for index, event in enumerate(events):
            network.process_event(
                instruments[event.instrument],
                (instruments[event.instrument] + 1) % 3,
                event.event_time_ns / 1_000.0,
                [event.value, float(event.event_time_ns) / 1_000.0],
            )
        for node in range(3):
            network.flush(node)

        embedding = network.embed(0, watermark / 1_000.0)
        assert embedding.shape == (8,)
        assert torch.all(torch.isfinite(embedding))
