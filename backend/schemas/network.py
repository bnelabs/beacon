"""Schemas for the network estimation surface.

``POST /api/v1/network/estimate`` accepts *declared aggregate* interbank
totals and returns an estimated bilateral network with uncertainty-propagated
clearing bands. The schema enforces the declaration contract at the boundary:
non-negative finite totals, at least two institutions, bounded draw counts and
percentiles. Anything the estimator itself refuses (all-zero totals, shocks
naming unknown institutions) is raised downstream and translated to a typed
422 by the route.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NetworkEstimateRequest(BaseModel):
    """Declared aggregates plus the scenario the estimate is cleared under."""

    model_config = ConfigDict(extra="forbid")

    interbank_assets: Dict[str, float] = Field(
        ...,
        description=(
            "institution -> total interbank claims (what it is owed), as "
            "declared by the operator from published aggregates (e.g. FDIC "
            "call reports). Becomes the column sums of the estimated matrix."
        ),
    )
    interbank_liabilities: Dict[str, float] = Field(
        ...,
        description=(
            "institution -> total interbank obligations (what it owes). "
            "Becomes the row sums of the estimated matrix."
        ),
    )
    endowment_ratio: float = Field(
        0.10,
        gt=0.0,
        le=1.0,
        description=(
            "Declared external-asset buffer: each institution's endowment is "
            "this fraction of its interbank obligations. An operator "
            "assumption, never an estimate."
        ),
    )
    shocks: Optional[Dict[str, float]] = Field(
        None,
        description=(
            "institution -> fraction of its endowment destroyed before "
            "clearing, in [0, 1]. Applied identically to the point estimate "
            "and every structural draw."
        ),
    )
    n_draws: int = Field(
        64,
        ge=1,
        le=256,
        description="Number of marginal-preserving structural draws to clear.",
    )
    concentration: float = Field(
        1.0,
        gt=0.0,
        le=1e6,
        description=(
            "Dirichlet concentration of the structure bootstrap. 1.0 is the "
            "flat Bayesian bootstrap; larger values collapse the draws "
            "toward the point estimate."
        ),
    )
    seed: Optional[int] = Field(
        None,
        description="RNG seed; the same seed reproduces the same bands.",
    )
    include_min_density: bool = Field(
        True,
        description=(
            "Also compute the minimum-support completion, the concentrated "
            "corner that brackets the maximum-entropy one."
        ),
    )
    percentiles: List[float] = Field(
        default_factory=lambda: [5.0, 50.0, 95.0],
        min_length=1,
        max_length=7,
        description="Percentiles of the draw distribution to report.",
    )

    @field_validator("interbank_assets", "interbank_liabilities")
    @classmethod
    def _totals_are_declared_and_sane(cls, value: Dict[str, float]) -> Dict[str, float]:
        if len(value) < 2:
            raise ValueError("a bilateral network needs at least two institutions")
        for name, amount in value.items():
            if not name or not name.strip():
                raise ValueError("institution identifiers must be non-empty")
            if amount != amount or amount in (float("inf"), float("-inf")):
                raise ValueError(f"total for {name!r} must be finite")
            if amount < 0:
                raise ValueError(f"total for {name!r} must be non-negative")
        return value

    @field_validator("shocks")
    @classmethod
    def _shocks_are_fractions(cls, value: Optional[Dict[str, float]]) -> Optional[Dict[str, float]]:
        if value is None:
            return None
        for name, fraction in value.items():
            if fraction != fraction or not 0.0 <= fraction <= 1.0:
                raise ValueError(f"shock fraction for {name!r} must be in [0, 1]")
        return value

    @field_validator("percentiles")
    @classmethod
    def _percentiles_in_range(cls, value: List[float]) -> List[float]:
        for pct in value:
            if pct != pct or not 0.0 <= pct <= 100.0:
                raise ValueError("percentiles must be within [0, 100]")
        return sorted(value)
