"""Regime-routed mixture of experts.

The plan routes data through a Mixture of Experts using the dual regime signal, so
that a crisis activates specialised pathways rather than pushing every input
through weights tuned for calm markets.

Why the regime signal is used explicitly rather than learned purely
------------------------------------------------------------------

A standard MoE learns its gate from the input alone. That has a well-known failure
mode -- expert collapse, where the gate settles on one or two experts and the rest
receive no gradient -- and it has a second, worse failure here: the gate has no
reason to align its experts with *regimes*. It might split by volatility, by level,
or by an artefact of the sampling, and the "crisis expert" would not be the one
that handles crises.

So the gate is the sum of a learned term and a regime prior::

    gate_logits = learned_gate(x) + regime_bias(regime_label)

The learned term keeps the routing input-dependent; the prior keeps it aligned with
the regime semantics the rest of the system already produces, and makes the routing
decisions readable -- a crisis signal visibly moves weight toward the crisis
expert. The learned term can still override the prior, so this informs the gate
rather than hard-wiring it.

Load balancing is not optional
------------------------------

Nothing above prevents collapse on its own, so the standard auxiliary loss is
included: the product of the fraction of tokens routed to each expert and the mean
gate probability assigned to it, summed over experts. It is minimised when both are
uniform, so it penalises both "one expert takes everything" and "the gate spreads
probability but the router picks the same expert regardless". It is exposed as a
loss the trainer adds, not applied silently, because its weight is a modelling
decision.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)

__all__ = [
    "RegimeSignal",
    "Expert",
    "MixtureOfExperts",
    "RoutingResult",
    "REGIME_ORDER",
]

#: Canonical regime order, matching the HMM's variance-ranked labels. The index is
#: what the routing prior keys on, so the order is part of the interface.
REGIME_ORDER: Tuple[str, ...] = ("calm", "elevated", "stressed", "crisis")


@dataclass(frozen=True)
class RegimeSignal:
    """The regime the system believes it is in, and how strongly.

    ``confidence`` scales the routing prior, so an ambiguous posterior nudges the
    gate less than a decisive one. A regime outside :data:`REGIME_ORDER` is
    accepted -- the system must be able to pass through something it has not seen
    -- but produces no prior, since inventing a mapping for an unknown label would
    be guessing.
    """

    label: str
    confidence: float = 1.0
    is_transition: bool = False

    @property
    def index(self) -> Optional[int]:
        return REGIME_ORDER.index(self.label) if self.label in REGIME_ORDER else None

    @property
    def is_known(self) -> bool:
        return self.index is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "confidence": float(self.confidence),
            "is_transition": bool(self.is_transition),
            "index": self.index,
            "is_known": self.is_known,
        }


@dataclass
class RoutingResult:
    """Output of a forward pass, with the routing evidence attached."""

    output: torch.Tensor
    gate_weights: torch.Tensor
    expert_indices: torch.Tensor
    regime: Optional[RegimeSignal]

    def utilization(self) -> np.ndarray:
        """Fraction of tokens dispatched to each expert."""
        counts = torch.bincount(
            self.expert_indices.reshape(-1),
            minlength=int(self.gate_weights.shape[-1]),
        ).float()
        total = counts.sum()
        return (counts / total).cpu().numpy() if total > 0 else counts.cpu().numpy()

    def mean_gate_probability(self) -> np.ndarray:
        return self.gate_weights.mean(dim=tuple(range(self.gate_weights.dim() - 1))).detach().cpu().numpy()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_experts": int(self.gate_weights.shape[-1]),
            "utilization": [float(x) for x in self.utilization()],
            "mean_gate_probability": [float(x) for x in self.mean_gate_probability()],
            "regime": None if self.regime is None else self.regime.to_dict(),
        }


class Expert(nn.Module):
    """One specialised pathway: a small MLP."""

    def __init__(self, input_dim: int, hidden_dim: int, output_dim: int, dropout: float = 0.0) -> None:
        super().__init__()
        if input_dim < 1 or hidden_dim < 1 or output_dim < 1:
            raise ValueError(
                f"dims must be positive, got input={input_dim}, hidden={hidden_dim}, "
                f"output={output_dim}"
            )
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, output_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class MixtureOfExperts(nn.Module):
    """Sparse mixture of experts whose gate is informed by the regime.

    Args:
        input_dim: Width of the input.
        output_dim: Width of the output.
        n_experts: Number of experts. With ``top_k`` below this, routing is sparse.
        hidden_dim: Hidden width of each expert.
        top_k: Experts activated per token. ``1`` is the cheapest and the usual
            choice; more than one gives a soft mixture and costs proportionally.
        regime_strength: How strongly the regime prior biases the gate, in logit
            units. Zero reduces the model to a plain learned-gate MoE, which is
            useful for an ablation but loses the alignment guarantee.
        dropout: Dropout inside each expert.
        seed: Seed for reproducible initialisation.
    """

    def __init__(
        self,
        input_dim: int,
        output_dim: int,
        n_experts: int = 4,
        hidden_dim: int = 64,
        top_k: int = 1,
        regime_strength: float = 2.0,
        dropout: float = 0.0,
        seed: Optional[int] = None,
    ) -> None:
        super().__init__()
        if n_experts < 2:
            raise ValueError(f"a mixture needs at least 2 experts, got {n_experts}")
        if not 1 <= top_k <= n_experts:
            raise ValueError(f"top_k must be in [1, {n_experts}], got {top_k}")
        if regime_strength < 0:
            raise ValueError(f"regime_strength must be non-negative, got {regime_strength}")
        if seed is not None:
            torch.manual_seed(seed)

        self.input_dim = int(input_dim)
        self.output_dim = int(output_dim)
        self.n_experts = int(n_experts)
        self.top_k = int(top_k)
        self.regime_strength = float(regime_strength)

        self.gate = nn.Linear(input_dim, n_experts)
        self.experts = nn.ModuleList(
            [Expert(input_dim, hidden_dim, output_dim, dropout) for _ in range(n_experts)]
        )
        # A learned, initially zero prior per regime. Starting at zero means the
        # model begins indistinguishable from a plain MoE and earns its regime
        # alignment from data rather than being handed it.
        self.register_buffer(
            "regime_prior", torch.zeros(len(REGIME_ORDER), n_experts), persistent=True
        )
        self.last_utilization: Optional[np.ndarray] = None
        self.last_gate_weights: Optional[np.ndarray] = None

    def _regime_logits(self, regime: Optional[RegimeSignal], batch_shape: torch.Size) -> Optional[torch.Tensor]:
        """Prior logits contributed by the regime, or ``None`` when unknown."""
        if regime is None or not regime.is_known or self.regime_strength == 0.0:
            return None
        prior = self.regime_prior[regime.index] * self.regime_strength * float(regime.confidence)
        return prior.reshape((1,) * len(batch_shape) + (self.n_experts,))

    def forward(
        self,
        x: torch.Tensor,
        regime: Optional[RegimeSignal] = None,
        *,
        record: bool = True,
    ) -> RoutingResult:
        """Route ``x`` to experts and combine their outputs.

        Shapes are treated as ``(..., input_dim)``, so a batch of node embeddings
        and a single embedding both work without reshaping at the call site.
        """
        if x.shape[-1] != self.input_dim:
            raise ValueError(
                f"input has width {x.shape[-1]} but the model expects {self.input_dim}"
            )

        logits = self.gate(x)
        regime_logits = self._regime_logits(regime, x.shape[:-1])
        if regime_logits is not None:
            logits = logits + regime_logits

        probabilities = F.softmax(logits, dim=-1)
        top_values, top_indices = torch.topk(probabilities, self.top_k, dim=-1)
        # Renormalise the kept experts so the output is a convex combination; an
        # unnormalised top-k is not a mixture and its scale depends on k.
        dispatch = top_values / top_values.sum(dim=-1, keepdim=True).clamp_min(1e-12)

        flat = x.reshape(-1, self.input_dim)
        expert_outputs = torch.stack([expert(flat) for expert in self.experts], dim=1)

        flat_indices = top_indices.reshape(-1, self.top_k)
        flat_dispatch = dispatch.reshape(-1, self.top_k)
        combined = torch.zeros(
            flat.shape[0], self.output_dim, dtype=expert_outputs.dtype, device=expert_outputs.device
        )
        for slot in range(self.top_k):
            chosen = flat_indices[:, slot]
            # Gather the selected expert's output for each token, then weight it.
            selected = expert_outputs[
                torch.arange(flat.shape[0], device=flat.device), chosen
            ]
            combined = combined + selected * flat_dispatch[:, slot].unsqueeze(-1)

        output = combined.reshape(x.shape[:-1] + (self.output_dim,))

        if record:
            self.last_utilization = np.asarray(
                np.bincount(flat_indices[:, 0].cpu().numpy(), minlength=self.n_experts)
                / max(flat.shape[0], 1),
                dtype=float,
            )
            self.last_gate_weights = probabilities.detach().reshape(-1, self.n_experts).mean(0).cpu().numpy()

        return RoutingResult(
            output=output,
            gate_weights=probabilities,
            expert_indices=top_indices[..., :1] if self.top_k == 1 else top_indices,
            regime=regime,
        )

    def load_balancing_loss(self, result: RoutingResult) -> torch.Tensor:
        """Switch-transformer style auxiliary loss.

        ``n_experts * sum_e (fraction dispatched to e) * (mean gate probability of e)``.
        Both factors being uniform minimises it, so it penalises an expert taking
        every token *and* a gate that spreads probability while the router keeps
        choosing the same expert. Returns a scalar; the trainer decides its weight.
        """
        flat_indices = result.expert_indices
        if flat_indices.dim() > 2:
            flat_indices = flat_indices.reshape(-1, flat_indices.shape[-1])
        one_hot = F.one_hot(flat_indices[:, 0], num_classes=self.n_experts).float()
        fraction = one_hot.mean(dim=0)
        mean_probability = result.gate_weights.reshape(-1, self.n_experts).mean(dim=0)
        return self.n_experts * torch.sum(fraction * mean_probability)

    def utilization_severity(self, tolerance: float = 0.5) -> Dict[str, Any]:
        """Whether any expert is starved, relative to a uniform share.

        Diagnostics rather than a training signal: collapse is worth surfacing on
        its own, because a model that trains happily while three of four experts
        receive nothing is a model whose capacity is a fiction.
        """
        if self.last_utilization is None:
            raise RuntimeError("no routing recorded yet; run a forward pass first")
        uniform = 1.0 / self.n_experts
        starved = [
            index
            for index, share in enumerate(self.last_utilization)
            if share < uniform * (1.0 - tolerance)
        ]
        return {
            "utilization": [float(x) for x in self.last_utilization],
            "uniform_share": uniform,
            "starved_experts": starved,
            "max_deviation": float(np.max(np.abs(self.last_utilization - uniform))),
            "is_balanced": not starved,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_dim": self.input_dim,
            "output_dim": self.output_dim,
            "n_experts": self.n_experts,
            "top_k": self.top_k,
            "regime_strength": self.regime_strength,
            "regime_order": list(REGIME_ORDER),
            "n_parameters": int(sum(p.numel() for p in self.parameters())),
        }
