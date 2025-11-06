"""Schemas for trained model endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Any, List, Optional
from typing import Literal

from pydantic import BaseModel, Field


class ModelMetrics(BaseModel):
    """Model evaluation metrics."""

    mae: Optional[float] = None
    rmse: Optional[float] = None
    r2: Optional[float] = None
    accuracy: Optional[float] = None
    best_val_loss: Optional[float] = None


class ModelSummary(BaseModel):
    """Summary information for trained models."""

    model_config = {"protected_namespaces": ()}

    model_id: int
    name: str
    created_at: Optional[datetime]
    status: str
    model_type: Optional[str]
    model_version: Optional[str]
    metrics: ModelMetrics
    tags: List[str]
    data_job_id: Optional[int]
    predictions_available: bool


class ModelDetail(BaseModel):
    """Detailed information for a trained model."""

    model_config = {"protected_namespaces": ()}

    model_id: int
    created_at: Optional[datetime]
    completed_at: Optional[datetime]
    status: str
    parameters: Dict[str, Any]
    metrics: Dict[str, Any]
    result: Dict[str, Any]
    data_job_id: Optional[int]
    predictions_path: Optional[str]
    visualizations: Dict[str, Any]


class ScenarioAdjustment(BaseModel):
    """Adjustment for a scenario simulation."""

    source: str
    type: Literal['pct', 'bps', 'absolute'] = 'pct'
    value: float


class RegionalShock(BaseModel):
    """Regional shock specification."""

    region: str = Field(description="Region code: NA, EU_WEST, EU_SOUTH, ASIA, LATAM, AFRICA, MIDDLE_EAST, GLOBAL")
    magnitude: float = Field(description="Shock magnitude as decimal (e.g., 0.10 for 10% shock)")


class ScenarioParameters(BaseModel):
    """Enhanced scenario parameters for comprehensive what-if analysis."""

    # Scenario type and metadata
    type: Optional[str] = Field(None, description="Scenario type: liquidity_freeze, policy_intervention, bank_failure, market_crash, regional_shock, etc.")
    scenario_id: Optional[str] = Field(None, description="Pre-configured scenario ID from scenario library")

    # Policy intervention parameters
    rate_cut_bps: Optional[float] = Field(None, description="Interest rate change in basis points (negative for hikes)")
    qe_amount: Optional[float] = Field(None, description="Quantitative easing amount in currency units")

    # Market stress parameters
    stock_drop_pct: Optional[float] = Field(None, description="Stock market drop as percentage (0.20 = 20% drop)")
    volatility_spike: Optional[float] = Field(None, description="Volatility multiplier (2.0 = double VIX)")
    credit_spread_widening: Optional[float] = Field(None, description="Credit spread widening in percentage points")

    # Liquidity freeze parameters
    interbank_lending_reduction: Optional[float] = Field(None, description="Reduction in interbank lending (0.70 = 70% reduction)")

    # Bank failure parameters
    failed_bank_id: Optional[str] = Field(None, description="ID of bank that fails")
    exposure_haircut: Optional[float] = Field(None, description="Haircut on exposures to failed bank (0.50 = 50% loss)")

    # Regional shocks
    regional_shocks: List[RegionalShock] = Field(default_factory=list, description="List of regional shocks to apply")

    # Sovereign crisis parameters
    sovereign_spread_widening: Optional[float] = Field(None, description="Sovereign bond spread widening")
    banking_stress: Optional[Dict[str, Any]] = Field(None, description="Banking stress parameters (deposit_flight, funding_cost_increase, etc.)")

    # Commodity shocks
    oil_price_increase: Optional[float] = Field(None, description="Oil price increase as percentage (1.00 = 100% increase)")
    inflation_spike: Optional[float] = Field(None, description="Inflation increase in percentage points")

    # Operational risk
    market_disruption: Optional[Dict[str, Any]] = Field(None, description="Market disruption parameters (trading_halt_duration, confidence_shock)")

    # Additional adjustments (legacy support)
    adjustments: List[ScenarioAdjustment] = Field(default_factory=list, description="Custom adjustments to specific data sources")


class ScenarioRequest(BaseModel):
    """Enhanced scenario simulation input with comprehensive what-if capabilities."""

    name: Optional[str] = Field(None, description="Scenario name")
    horizon_days: int = Field(30, description="Prediction horizon in days (7, 14, 21, or 30)")
    scenario: ScenarioParameters = Field(default_factory=ScenarioParameters, description="Scenario parameters")

    # Backwards compatibility
    adjustments: List[ScenarioAdjustment] = Field(default_factory=list, description="Legacy adjustments field")


class ScenarioResponse(BaseModel):
    """Scenario simulation result."""

    scenario_id: str
    model_id: int
    name: str
    horizon_days: int
    created_at: datetime
    summary: Dict[str, Any]
    predictions: List[Dict[str, Any]]
    adjustments: List[ScenarioAdjustment] = Field(default_factory=list)
    executive_summary: Optional[str] = None
    feature_importances: Dict[str, float] = Field(default_factory=dict)
    storage_path: Optional[str] = None
