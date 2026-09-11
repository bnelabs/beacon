"""Temporal Graph Network with Neural ODEs for irregular sampling.

What this replaces
------------------

The deleted HGT ran once per 24-hour batch over one static adjacency. Node state
between batches did not exist: a bank's funding position at 14:00 was whatever the
last batch had computed, and the model had no way to represent that it had moved.
That is fatal for the stated goal, because funding stress transmits on the scale of
margin calls and repo rollovers -- minutes to hours -- so a daily graph samples the
process roughly four orders of magnitude too slowly.

A Temporal Graph Network (Rossi et al., 2020) keeps a *memory* per node and updates
it asynchronously, event by event, rather than recomputing everything on a
schedule. Two things follow that the batch model could not express: the arrival of
an event changes exactly the nodes it touches, and every other node's state is
well defined at every instant rather than only at batch boundaries.

Why a Neural ODE is needed for the slow nodes
---------------------------------------------

A TGN alone leaves the memory frozen between one node's events. For a node
observed every millisecond that is harmless -- the next event is microseconds
away. For a node observed quarterly it is not: freezing its memory for 90 days
means the model behaves as though nothing happened to it for a quarter, and the
only alternative the batch approach offered was to pad or resample onto a common
grid, which invents observations that were never made.

Instead the memory *evolves continuously* between observations, according to a
learned vector field::

    dz/dt = f_theta(z, t)

solved with a fourth-order Runge-Kutta integrator. Millisecond repo data and
quarterly GDP then share one latent state space with no common grid and no
fabricated points: each node's state is advanced to the instant it is needed.

The solver is the part with a checkable answer
----------------------------------------------

RK4 has a known convergence order and known solutions for simple fields, and the
tests use both. Integrating ``dz/dt = -z`` from 0 to T must reproduce ``exp(-T)``,
and halving the step must cut the error by roughly ``2^4`` -- a property no
misimplemented integrator reproduces. The nonlinear field ``dz/dt = z^2``, with
closed form ``z(t) = z0 / (1 - z0 t)``, checks that the agreement is not an
artefact of linearity.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import torch
import torch.nn as nn

logger = logging.getLogger(__name__)

__all__ = [
    "TimeEncoder",
    "NeuralODEField",
    "rk4_step",
    "rk4_integrate",
    "exponential_decay",
    "TemporalGraphMemory",
    "TemporalGraphNetwork",
    "MemoryState",
]

FieldFn = Callable[[torch.Tensor, torch.Tensor], torch.Tensor]


# ---------------------------------------------------------------------------
# Time encoding
# ---------------------------------------------------------------------------

class TimeEncoder(nn.Module):
    """Fourier features of a time interval.

    A raw scalar ``dt`` is a poor input: it grows without bound and its useful
    variation is concentrated near zero, so a network given raw seconds cannot
    distinguish microseconds from milliseconds and also represent years. Fixed
    geometric frequencies across several decades cover both, which is the same
    construction the TGN paper uses for exactly this reason.

    Args:
        dim: Number of frequency pairs. The encoding has ``2 * dim`` features.
        base: Slowest angular frequency.
        growth: Ratio between successive frequencies.
    """

    def __init__(self, dim: int = 8, base: float = 1.0, growth: float = 10.0) -> None:
        super().__init__()
        if dim < 1:
            raise ValueError(f"dim must be positive, got {dim}")
        if base <= 0:
            raise ValueError(f"base must be positive, got {base}")
        if growth <= 1:
            raise ValueError(f"growth must exceed 1, got {growth}")
        self.dim = int(dim)
        frequencies = torch.tensor(
            [base * (growth ** index) for index in range(self.dim)], dtype=torch.float32
        )
        self.register_buffer("frequencies", frequencies)

    @property
    def output_dim(self) -> int:
        return 2 * self.dim

    def forward(self, delta: torch.Tensor) -> torch.Tensor:
        """Encode non-negative time intervals."""
        values = torch.as_tensor(delta, dtype=torch.float32).reshape(-1, 1)
        if bool(torch.any(values < 0)):
            raise ValueError("time intervals must be non-negative")
        scaled = values * self.frequencies.reshape(1, -1)
        return torch.cat([torch.cos(scaled), torch.sin(scaled)], dim=-1)


# ---------------------------------------------------------------------------
# Integrator
# ---------------------------------------------------------------------------

def rk4_step(field: FieldFn, state: torch.Tensor, time: torch.Tensor, step: float) -> torch.Tensor:
    """One classical fourth-order Runge-Kutta step."""
    k1 = field(state, time)
    k2 = field(state + 0.5 * step * k1, time + 0.5 * step)
    k3 = field(state + 0.5 * step * k2, time + 0.5 * step)
    k4 = field(state + step * k3, time + step)
    return state + (step / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def rk4_integrate(
    field: FieldFn,
    state: torch.Tensor,
    t0: float,
    t1: float,
    steps: int = 8,
) -> torch.Tensor:
    """Integrate ``dz/dt = field(z, t)`` from ``t0`` to ``t1``.

    ``steps`` is the number of RK4 steps, so the step size is ``(t1 - t0) / steps``.
    Accuracy is the caller's to choose: the truncation error falls as ``h^4``, so
    doubling the step count cuts it roughly sixteenfold. A default of 8 is enough
    to track a smooth decay over an interval where the state changes by an order of
    magnitude, and deliberately not more, because this runs once per query per
    node and a node observed quarterly needs a long span.

    Args:
        field: Vector field ``(state, time) -> d(state)/dt``.
        state: Current state, any shape.
        t0, t1: Integration bounds. ``t1`` may be less than ``t0`` (backwards).
        steps: Number of RK4 steps. Must be positive.

    Returns:
        The state at ``t1``.
    """
    if steps < 1:
        raise ValueError(f"steps must be positive, got {steps}")
    if t0 == t1:
        return state

    step = (t1 - t0) / steps
    current = state
    time = torch.as_tensor(t0, dtype=state.dtype, device=state.device)
    step_size = torch.as_tensor(step, dtype=state.dtype, device=state.device)
    for _ in range(steps):
        current = rk4_step(field, current, time, float(step_size))
        time = time + step_size
    return current


def exponential_decay(
    state: torch.Tensor, interval: float, rate: float
) -> torch.Tensor:
    """Closed-form solution of ``dz/dt = -rate * z``.

    Carried here rather than in the tests because it is the reference the
    integrator is checked against, and the check is only meaningful if the
    reference is independent of the solver.
    """
    if interval < 0:
        raise ValueError(f"interval must be non-negative, got {interval}")
    decay = math.exp(-float(rate) * float(interval))
    return state * decay


# ---------------------------------------------------------------------------
# Vector field
# ---------------------------------------------------------------------------

class NeuralODEField(nn.Module):
    """A learned vector field ``f_theta(z, t)``.

    The time input is the *interval since the node was last updated*, encoded,
    rather than an absolute timestamp. An absolute clock would force the field to
    learn the whole history of the sample; an interval makes the same field apply
    to a node seen a millisecond ago and one seen a quarter ago.
    """

    def __init__(
        self,
        state_dim: int,
        hidden_dim: int = 64,
        time_dim: int = 8,
        rate: float = 0.1,
    ) -> None:
        super().__init__()
        if state_dim < 1:
            raise ValueError(f"state_dim must be positive, got {state_dim}")
        self.state_dim = int(state_dim)
        self.time_encoder = TimeEncoder(dim=time_dim)
        self.net = nn.Sequential(
            nn.Linear(self.state_dim + self.time_encoder.output_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, self.state_dim),
        )
        # A decay floor. Without it the field can learn zero and the memory never
        # moves between events, which reproduces exactly the staleness the ODE is
        # here to remove.
        self.rate = float(rate)
        if self.rate <= 0:
            raise ValueError(f"rate must be positive, got {rate}")

    def forward(self, state: torch.Tensor, t: torch.Tensor) -> torch.Tensor:
        encoded = self.time_encoder(torch.as_tensor(t).reshape(-1))
        if encoded.shape[0] != state.shape[0]:
            expanded = encoded.mean(dim=0, keepdim=True).expand(state.shape[0], -1)
        else:
            expanded = encoded
        learned = self.net(torch.cat([state, expanded], dim=-1))
        return learned - self.rate * state


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

@dataclass
class MemoryState:
    """Snapshot of one node's memory, with its provenance."""

    node: int
    time: float
    last_update_time: float
    evolved_interval: float
    memory: torch.Tensor

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node": int(self.node),
            "time": float(self.time),
            "last_update_time": float(self.last_update_time),
            "evolved_interval": float(self.evolved_interval),
            "memory_norm": float(torch.linalg.vector_norm(self.memory).item()),
        }


class TemporalGraphMemory(nn.Module):
    """Per-node memory that evolves continuously between observations.

    Args:
        n_nodes: Size of the node universe.
        memory_dim: Width of each node's memory vector.
        field: Vector field used to advance memory. Defaults to a
            :class:`NeuralODEField` of the right width.
        integration_steps: RK4 steps per evolution. Higher is more accurate and
            slower.
    """

    def __init__(
        self,
        n_nodes: int,
        memory_dim: int = 32,
        field: Optional[NeuralODEField] = None,
        integration_steps: int = 8,
    ) -> None:
        super().__init__()
        if n_nodes < 1:
            raise ValueError(f"n_nodes must be positive, got {n_nodes}")
        if memory_dim < 1:
            raise ValueError(f"memory_dim must be positive, got {memory_dim}")
        if integration_steps < 1:
            raise ValueError(f"integration_steps must be positive, got {integration_steps}")

        self.n_nodes = int(n_nodes)
        self.memory_dim = int(memory_dim)
        self.integration_steps = int(integration_steps)
        self.field = field if field is not None else NeuralODEField(self.memory_dim)

        self.register_buffer("memory", torch.zeros(self.n_nodes, self.memory_dim))
        # Times are stored as a buffer so they survive a device move; a plain
        # Python list would silently stay on the host.
        self.register_buffer("last_time", torch.zeros(self.n_nodes, dtype=torch.float64))
        self.register_buffer("initialised", torch.zeros(self.n_nodes, dtype=torch.bool))

    def evolve_to(self, time: float) -> torch.Tensor:
        """Advance every node's memory to ``time`` and return the whole memory.

        Nodes observed quarterly and nodes observed every millisecond are advanced
        by the same field over their own intervals, so neither is padded onto the
        other's grid. A node whose last observation is in the future relative to
        ``time`` is left alone and reported by :meth:`stale_nodes`, because
        integrating backwards through an event is not a well-defined thing to do.
        """
        target = float(time)
        for node in range(self.n_nodes):
            interval = target - float(self.last_time[node].item())
            if interval <= 0 or not bool(self.initialised[node].item()):
                continue
            current = self.memory[node]
            evolved = rk4_integrate(
                self._field_for(node), current, 0.0, interval, self.integration_steps
            )
            with torch.no_grad():
                self.memory[node] = evolved.detach()
            self.last_time[node] = target
        return self.memory

    def _field_for(self, node: int) -> FieldFn:
        """The vector field for a single node, as a batch-of-one callable."""
        def field(state: torch.Tensor, time: torch.Tensor) -> torch.Tensor:
            return self.field(state.reshape(1, -1), time)[0]
        return field

    def write(self, node: int, memory: torch.Tensor, time: float) -> None:
        """Overwrite a node's memory at a given time (an event has been applied)."""
        if not 0 <= node < self.n_nodes:
            raise ValueError(f"node {node} is outside a {self.n_nodes}-node universe")
        if memory.shape != (self.memory_dim,):
            raise ValueError(
                f"memory for node {node} has shape {tuple(memory.shape)}, expected "
                f"({self.memory_dim},)"
            )
        with torch.no_grad():
            self.memory[node] = memory
        self.last_time[node] = float(time)
        self.initialised[node] = True

    def read(self, node: int, time: float) -> MemoryState:
        """Memory for one node, evolved to ``time``, without mutating the store."""
        if not 0 <= node < self.n_nodes:
            raise ValueError(f"node {node} is outside a {self.n_nodes}-node universe")

        last = float(self.last_time[node].item())
        if not bool(self.initialised[node].item()):
            return MemoryState(
                node=node,
                time=float(time),
                last_update_time=last,
                evolved_interval=0.0,
                memory=self.memory[node].detach().clone(),
            )

        interval = float(time) - last
        if interval <= 0:
            return MemoryState(
                node=node,
                time=float(time),
                last_update_time=last,
                evolved_interval=max(interval, 0.0),
                memory=self.memory[node].detach().clone(),
            )

        # Deliberately differentiable. Detaching here would sever the graph
        # between the vector field and every downstream embedding, leaving the ODE
        # permanently untrainable -- it would only ever run its initial weights.
        # Callers that store the result detach explicitly; `evolve_to` does.
        evolved = rk4_integrate(
            self._field_for(node), self.memory[node], 0.0, interval, self.integration_steps
        )
        return MemoryState(
            node=node,
            time=float(time),
            last_update_time=last,
            evolved_interval=interval,
            memory=evolved,
        )

    def stale_nodes(self, time: float) -> List[int]:
        """Initialised nodes whose last update is later than ``time``."""
        target = float(time)
        return [
            node
            for node in range(self.n_nodes)
            if bool(self.initialised[node].item())
            and float(self.last_time[node].item()) > target
        ]

    def reset(self) -> None:
        with torch.no_grad():
            self.memory.zero_()
            self.last_time.zero_()
            self.initialised.zero_()


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

class TemporalGraphNetwork(nn.Module):
    """Message passing over an event stream, with continuous-time memory.

    Each event carries a source node, a destination node, a timestamp and a
    feature vector. The model computes a message, aggregates the messages a node
    has received since it was last updated, and folds them into its memory through
    a gated update. Memory is advanced continuously between events, so a node
    observed rarely is never frozen and no node is ever resampled onto a grid.

    Args:
        n_nodes: Node universe size.
        node_feature_dim: Width of the per-event feature vector.
        memory_dim: Memory width.
        message_dim: Message width.
        integration_steps: RK4 steps per memory evolution.
        seed: Seed for reproducible initialisation.
    """

    def __init__(
        self,
        n_nodes: int,
        node_feature_dim: int,
        memory_dim: int = 32,
        message_dim: int = 32,
        integration_steps: int = 8,
        seed: Optional[int] = None,
    ) -> None:
        super().__init__()
        if node_feature_dim < 1:
            raise ValueError(f"node_feature_dim must be positive, got {node_feature_dim}")

        if seed is not None:
            torch.manual_seed(seed)

        self.n_nodes = int(n_nodes)
        self.node_feature_dim = int(node_feature_dim)
        self.memory_dim = int(memory_dim)
        self.message_dim = int(message_dim)

        self.time_encoder = TimeEncoder(dim=8)
        self.memory = TemporalGraphMemory(
            n_nodes=n_nodes, memory_dim=memory_dim, integration_steps=integration_steps
        )

        # Both intervals are message inputs: the source's staleness conditions the
        # news, and the target's conditions how much its memory has drifted before
        # receiving it.
        message_input = (
            memory_dim * 2
            + node_feature_dim
            + 2 * self.time_encoder.output_dim
            + 2
        )
        self.message_fn = nn.Sequential(
            nn.Linear(message_input, message_dim),
            nn.ReLU(),
            nn.Linear(message_dim, message_dim),
        )
        self.update_fn = nn.GRUCell(message_dim, memory_dim)
        self.embedding_fn = nn.Sequential(
            nn.Linear(memory_dim + self.time_encoder.output_dim, memory_dim),
            nn.ReLU(),
        )
        self.decoder = nn.Linear(memory_dim, 1)

        # Each pending entry carries the event time as well as the message. The
        # message alone is not enough: flush must advance the node's clock to the
        # latest event it absorbed, otherwise the next read evolves from a stale
        # timestamp and silently re-applies intervals already accounted for.
        self._pending: Dict[int, List[Tuple[float, torch.Tensor]]] = {}

    def _relative_interval(self, node: int, time: float) -> float:
        last = float(self.memory.last_time[node].item())
        if not bool(self.memory.initialised[node].item()):
            return 0.0
        return max(float(time) - last, 0.0)

    def process_event(
        self,
        source: int,
        target: int,
        time: float,
        features: Sequence[float],
    ) -> torch.Tensor:
        """Ingest one event and return the updated target memory.

        The event's own time drives both the continuous evolution and the message,
        so an event that arrives out of order is handled on its own timestamp
        rather than on arrival order -- which is why this composes with the
        watermarking in :mod:`backend.modules.data.streaming`.
        """
        for node in (source, target):
            if not 0 <= node < self.n_nodes:
                raise ValueError(f"node {node} is outside a {self.n_nodes}-node universe")

        feature_tensor = torch.as_tensor(list(features), dtype=torch.float32).reshape(-1)
        if feature_tensor.numel() != self.node_feature_dim:
            raise ValueError(
                f"features have {feature_tensor.numel()} entries but the model expects "
                f"{self.node_feature_dim}"
            )

        source_interval = self._relative_interval(source, time)
        target_interval = self._relative_interval(target, time)

        source_state = self.memory.read(source, time).memory
        target_state = self.memory.read(target, time).memory

        message = self.message_fn(
            torch.cat(
                [
                    source_state,
                    target_state,
                    feature_tensor,
                    self.time_encoder(torch.tensor([source_interval])).reshape(-1),
                    self.time_encoder(torch.tensor([target_interval])).reshape(-1),
                    torch.tensor(
                        [source_interval, target_interval], dtype=torch.float32
                    ),
                ]
            )
        )

        self._pending.setdefault(target, []).append((float(time), message))
        return message

    def flush(self, node: int) -> torch.Tensor:
        """Apply the aggregated messages to a node's memory.

        Aggregation is a mean rather than a sum so that a node which happened to
        receive many events is not pushed further from its prior purely because of
        count. Splitting ingestion from application is what lets a caller batch a
        burst of events without recomputing the memory per event.
        """
        pending = self._pending.pop(node, [])
        if not pending:
            return self.memory.read(node, float(self.memory.last_time[node].item())).memory

        _times, messages = zip(*pending)
        aggregated = torch.stack(list(messages), dim=0).mean(dim=0)

        # The node's clock only ever moves forward. A straggler carries an earlier
        # timestamp, but the state at that earlier time has already been used, so
        # the message cannot be applied retroactively; it is absorbed now and the
        # clock stays where it was rather than rewinding. Monotonicity is what
        # makes the memory a function of the stream rather than of arrival jitter.
        applied_at = max(
            float(max(_times)), float(self.memory.last_time[node].item())
        )
        current = self.memory.read(node, applied_at).memory
        updated = self.update_fn(aggregated.reshape(1, -1), current.reshape(1, -1)).reshape(-1)

        self.memory.write(node, updated.detach(), applied_at)
        return updated

    def embed(self, node: int, time: float) -> torch.Tensor:
        """Node embedding at an instant, with memory evolved to that instant."""
        state = self.memory.read(node, time)
        interval = state.evolved_interval
        return self.embedding_fn(
            torch.cat(
                [
                    state.memory.reshape(-1),
                    self.time_encoder(torch.tensor([interval])).reshape(-1),
                ]
            )
        )

    def decode(self, node: int, time: float) -> float:
        """Scalar prediction for a node at an instant."""
        with torch.no_grad():
            return float(self.decoder(self.embed(node, time)).reshape(-1)[0].item())

    def pending_count(self, node: int) -> int:
        return len(self._pending.get(node, ()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_nodes": self.n_nodes,
            "memory_dim": self.memory_dim,
            "message_dim": self.message_dim,
            "node_feature_dim": self.node_feature_dim,
            "integration_steps": self.memory.integration_steps,
            "time_encoding_dim": self.time_encoder.output_dim,
        }
