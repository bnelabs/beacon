"""Contagion channel decomposition and liability-side sensitivity.

Round-eight adoption. Two policy questions the engines could answer but never
reported:

1. **Which channel produced the loss?** Clearing at fixed prices, fire-sale
   feedback (forced liquidation moving prices), and the margin/price spiral
   amplification are separate mechanisms with different interventions. The
   fire-sale solver already isolates its feedback via the lambda=0
   counterfactual; the spiral records its amplification per institution.
   This module assembles those measured increments into one decomposition
   instead of leaving each in its own silo. Channels that were not run are
   ``None`` with a reason -- an absent channel is missing information, not
   zero contribution.

2. **How sensitive is the clearing outcome to each bilateral liability?**
   The importance ranking shocks *endowments*; the literature (sensitivity
   of the clearing vector to individual interbank claims) also asks about
   the liability side. ``liability_sensitivity`` perturbs the top-k bilateral
   claims by a declared fraction and reports the resulting change in total
   shortfall: which edges the system is actually exposed to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

from .clearing import ClearingResult, MultiplexClearingEngine, NetworkLayer

__all__ = ["ChannelDecomposition", "decompose_channels", "liability_sensitivity"]


@dataclass(frozen=True)
class ChannelDecomposition:
    """Measured increments per contagion channel, with absences named."""

    direct_clearing: float
    fire_sale_feedback: Optional[float] = None
    spiral_amplification: Optional[float] = None
    total_measured: Optional[float] = None
    notes: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, object]:
        return {
            "direct_clearing": self.direct_clearing,
            "fire_sale_feedback": self.fire_sale_feedback,
            "spiral_amplification": self.spiral_amplification,
            "total_measured": self.total_measured,
            "notes": list(self.notes),
        }


def decompose_channels(
    clearing: Optional[ClearingResult],
    fire_sale=None,
    spirals: Optional[Dict[str, object]] = None,
) -> ChannelDecomposition:
    """Assemble measured channel increments from existing engine results."""
    notes: List[str] = []

    if clearing is None:
        return ChannelDecomposition(
            direct_clearing=0.0,
            notes=("clearing was not run: balance sheet unknown; no channel can be measured",),
        )

    direct = float(clearing.total_shortfall)

    feedback: Optional[float] = None
    if fire_sale is not None and getattr(fire_sale, "feedback_shortfall", None) is not None:
        feedback = float(fire_sale.feedback_shortfall)
    else:
        notes.append("fire-sale channel not run: holdings/prices/capital not supplied")

    spiral_increment: Optional[float] = None
    if spirals:
        total = 0.0
        counted = 0
        for result in spirals.values():
            extra_price = float(getattr(result, "total_price_change", 0.0)) - float(
                getattr(result, "initial_price_change", 0.0)
            )
            position = abs(float(getattr(result, "initial_position", 0.0)))
            total += extra_price * position
            counted += 1
        spiral_increment = total if counted else None
    if spiral_increment is None:
        notes.append("spiral channel not run: no clearing shortfall to shock it with")

    measured = direct + (feedback or 0.0) + (spiral_increment or 0.0)
    return ChannelDecomposition(
        direct_clearing=direct,
        fire_sale_feedback=feedback,
        spiral_amplification=spiral_increment,
        total_measured=measured,
        notes=tuple(notes),
    )


def liability_sensitivity(
    layers: Sequence[NetworkLayer],
    endowments: np.ndarray,
    node_ids: Sequence[str],
    *,
    top_k: int = 25,
    perturb_fraction: float = 0.01,
) -> List[Dict[str, object]]:
    """Change in total shortfall per +1% perturbation of the top-k liabilities.

    Each of the ``top_k`` largest bilateral claims is scaled by
    ``1 + perturb_fraction`` and the network re-cleared; the reported delta is
    per unit fraction, so entries are comparable across edges of different
    size. Expensive by nature (one clear per edge): bounded by ``top_k``.
    """
    if not 0 < perturb_fraction < 1:
        raise ValueError("perturb_fraction must be in (0, 1)")
    if len(layers) != 1:
        raise ValueError("liability sensitivity is defined for a single-layer network")

    layer = layers[0]
    matrix = np.asarray(layer.liabilities, dtype=float)
    baseline = MultiplexClearingEngine(layers, node_ids=list(node_ids)).clear(np.asarray(endowments, dtype=float))
    base_shortfall = float(baseline.total_shortfall)

    flat = [(i, j, matrix[i, j]) for i in range(matrix.shape[0]) for j in range(matrix.shape[1]) if matrix[i, j] > 0]
    flat.sort(key=lambda triple: triple[2], reverse=True)

    out: List[Dict[str, object]] = []
    for i, j, amount in flat[:top_k]:
        perturbed = matrix.copy()
        perturbed[i, j] *= 1.0 + perturb_fraction
        perturbed_layer = NetworkLayer(name=layer.name, liabilities=perturbed, seniority=layer.seniority)
        result = MultiplexClearingEngine([perturbed_layer], node_ids=list(node_ids)).clear(np.asarray(endowments, dtype=float))
        delta = float(result.total_shortfall) - base_shortfall
        out.append({
            "debtor": node_ids[i],
            "creditor": node_ids[j],
            "amount": float(amount),
            "delta_shortfall_per_unit_fraction": delta / perturb_fraction,
        })
    out.sort(key=lambda entry: abs(entry["delta_shortfall_per_unit_fraction"]), reverse=True)
    return out
