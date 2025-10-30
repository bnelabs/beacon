"""Per-Bank Liquidity Risk Analysis - Multi-Institution Support."""

import torch
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import logging

from modules.explainability.shap_explainer import ModelExplainer, NetworkExplainer, ExplanationResult
from .constants import (
    RISK_THRESHOLD_LOW,
    RISK_THRESHOLD_MODERATE,
    RISK_THRESHOLD_HIGH,
    HIGH_RISK_THRESHOLD,
    CRITICAL_RISK_THRESHOLD,
    WEIGHT_INDIVIDUAL_RISK,
    WEIGHT_SYSTEMIC_CONCENTRATION,
    WEIGHT_NETWORK_INTERCONNECTEDNESS,
    VOLATILITY_NORMALIZATION_FACTOR,
    TREND_NORMALIZATION_FACTOR,
    OPERATIONAL_RISK_MINIMUM,
    OPERATIONAL_RISK_MAXIMUM,
    OPERATIONAL_RISK_DEFAULT,
    WEIGHT_DATA_COMPLETENESS,
    WEIGHT_DATA_CONSISTENCY,
    RECENT_DATA_WINDOW
)

logger = logging.getLogger(__name__)


@dataclass
class BankRiskProfile:
    """Complete risk profile for a single bank."""
    bank_id: str
    bank_name: str

    # Risk scores (0-1)
    overall_liquidity_risk: float
    market_liquidity_risk: float
    funding_liquidity_risk: float
    operational_risk: float

    # Confidence bounds
    confidence_lower: float
    confidence_upper: float

    # Explanations
    explanation: ExplanationResult
    risk_level: str  # low, medium, high, critical

    # Systemic importance
    systemic_importance: float
    network_position: str  # hub, peripheral, intermediate

    # Vulnerabilities and strengths
    top_vulnerabilities: List[str]
    top_strengths: List[str]

    # Recommendations
    recommendations: List[str]


@dataclass
class MultiBankAnalysis:
    """Analysis across multiple banks."""
    analysis_date: str
    num_banks: int

    # Individual bank profiles
    bank_profiles: Dict[str, BankRiskProfile]

    # Network effects
    contagion_matrix: pd.DataFrame  # Bank-to-bank contagion effects
    systemic_banks: List[Tuple[str, float, str]]  # (bank_id, importance, reason)

    # Cascade simulations
    cascade_scenarios: Dict[str, Dict]  # bank_id -> cascade_result

    # Aggregate statistics
    avg_risk: float
    max_risk: float
    num_high_risk: int
    num_critical_risk: int

    # System-wide metrics
    network_density: float
    systemic_risk_score: float


class BankRiskAnalyzer:
    """
    Analyzes liquidity risk for multiple banks.

    For each bank:
    - Individual risk assessment
    - Explainable predictions
    - Vulnerability identification

    For the system:
    - Inter-bank dependencies
    - Contagion analysis
    - Systemic risk computation
    """

    def __init__(
        self,
        model: torch.nn.Module,
        device: torch.device,
        sequence_length: int,
        source_stats: Dict[str, Dict[str, float]],
        source_to_id: Dict[str, int]
    ):
        self.model = model
        self.device = device
        self.explainer = ModelExplainer(model, device)
        self.network_explainer = NetworkExplainer()
        self.sequence_length = sequence_length
        self.source_stats = source_stats or {}
        self.source_to_id = source_to_id or {}

    def analyze_multiple_banks(
        self,
        bank_data: Dict[str, pd.DataFrame],  # bank_id -> timeseries DataFrame
        bank_exposures: Optional[Dict[Tuple[str, str], float]] = None,  # (from, to) -> exposure
        feature_names: Optional[List[str]] = None
    ) -> MultiBankAnalysis:
        """
        Analyze liquidity risk for multiple banks.

        Args:
            bank_data: Dict mapping bank_id to their timeseries data
            bank_exposures: Inter-bank exposures (optional)
            feature_names: Feature names for explainability

        Returns:
            MultiBankAnalysis with per-bank and system-wide results
        """
        logger.info(f"Analyzing {len(bank_data)} banks")

        # Analyze each bank individually
        bank_profiles = {}
        bank_predictions = {}

        for bank_id, df in bank_data.items():
            profile = self._analyze_single_bank(bank_id, df, feature_names)
            bank_profiles[bank_id] = profile
            bank_predictions[bank_id] = profile.overall_liquidity_risk

        # Network analysis (if exposures provided)
        if bank_exposures:
            contagion_matrix = self.network_explainer.compute_contagion_matrix(
                bank_predictions, bank_exposures
            )

            systemic_banks = self.network_explainer.identify_systemic_banks(
                bank_predictions, bank_exposures
            )

            # Simulate cascades for high-risk banks
            cascade_scenarios = {}
            for bank_id, risk in bank_predictions.items():
                if risk > HIGH_RISK_THRESHOLD:  # High risk
                    cascade = self.network_explainer.simulate_cascade(
                        bank_id, bank_predictions, bank_exposures
                    )
                    cascade_scenarios[bank_id] = cascade

            # Network density
            num_banks = len(bank_data)
            actual_connections = len(bank_exposures)
            max_connections = num_banks * (num_banks - 1)
            network_density = actual_connections / max_connections if max_connections > 0 else 0

        else:
            # No network data
            contagion_matrix = pd.DataFrame()
            systemic_banks = []
            cascade_scenarios = {}
            network_density = 0

        # Aggregate statistics
        risks = [p.overall_liquidity_risk for p in bank_profiles.values()]
        avg_risk = float(np.mean(risks))
        max_risk = float(np.max(risks))
        num_high_risk = sum(1 for r in risks if r > HIGH_RISK_THRESHOLD)
        num_critical_risk = sum(1 for r in risks if r > CRITICAL_RISK_THRESHOLD)

        # System-wide risk
        systemic_risk_score = self._compute_systemic_risk(
            bank_predictions, contagion_matrix, systemic_banks
        )

        return MultiBankAnalysis(
            analysis_date=pd.Timestamp.now().isoformat(),
            num_banks=len(bank_data),
            bank_profiles=bank_profiles,
            contagion_matrix=contagion_matrix,
            systemic_banks=systemic_banks,
            cascade_scenarios=cascade_scenarios,
            avg_risk=avg_risk,
            max_risk=max_risk,
            num_high_risk=num_high_risk,
            num_critical_risk=num_critical_risk,
            network_density=network_density,
            systemic_risk_score=systemic_risk_score
        )

    def _analyze_single_bank(
        self,
        bank_id: str,
        df: pd.DataFrame,
        feature_names: Optional[List[str]] = None
    ) -> BankRiskProfile:
        """Analyze a single bank's risk."""

        # Prepare data for model
        # Assume df has 'Date' and 'Value' columns
        if len(df) == 0:
            raise ValueError(f"No data provided for bank {bank_id}")

        if 'source_code' in df.columns and df['source_code'].notna().any():
            source_code = df['source_code'].dropna().iloc[0]
            df = df[df['source_code'] == source_code]
        else:
            source_code = None

        value_column = 'Close' if 'Close' in df.columns else 'Value'
        series = df[value_column].astype(float)
        series = series.ffill().bfill()
        values = series.fillna(0).values

        if len(values) < self.sequence_length:
            logger.warning(f"Bank {bank_id} has only {len(values)} data points")

        sequence, stats = self._prepare_sequence(values, source_code)
        sequence = sequence.to(self.device)

        # Get source ID (assume 0 if not specified)
        source_id = self._map_source_id(source_code)

        # Get prediction with explanation
        explanation = self.explainer.explain_prediction(
            sequence, source_id,
            feature_names or [f"t-{i}" for i in range(self.sequence_length)],
            actual_value=float(values[-1]) if len(values) > 0 else None
        )

        # Classify risk level
        risk_value = float(explanation.prediction_value)
        if risk_value < RISK_THRESHOLD_LOW:
            risk_level = "low"
        elif risk_value < RISK_THRESHOLD_MODERATE:
            risk_level = "medium"
        elif risk_value < RISK_THRESHOLD_HIGH:
            risk_level = "high"
        else:
            risk_level = "critical"

        # Extract vulnerabilities and strengths
        top_vulnerabilities = explanation.risk_factors[:3]
        top_strengths = explanation.mitigating_factors[:3]

        # Generate recommendations
        recommendations = self._generate_recommendations(risk_value, risk_level, explanation)

        # Extract separate risk components from prediction data
        # Use the sequence tensor (not DataFrame) for risk computations
        market_liquidity_risk = self._compute_market_liquidity_risk(sequence, risk_value)
        funding_liquidity_risk = self._compute_funding_liquidity_risk(sequence, risk_value)
        operational_risk = self._compute_operational_risk(sequence)

        return BankRiskProfile(
            bank_id=bank_id,
            bank_name=f"Bank {bank_id}",  # Would come from database
            overall_liquidity_risk=risk_value,
            market_liquidity_risk=market_liquidity_risk,
            funding_liquidity_risk=funding_liquidity_risk,
            operational_risk=operational_risk,
            confidence_lower=explanation.confidence_lower,
            confidence_upper=explanation.confidence_upper,
            explanation=explanation,
            risk_level=risk_level,
            systemic_importance=0.0,  # Computed in network analysis
            network_position="unknown",
            top_vulnerabilities=top_vulnerabilities,
            top_strengths=top_strengths,
            recommendations=recommendations
        )

    def _map_source_id(self, source_code: Optional[str]) -> int:
        if source_code and source_code in self.source_to_id:
            return int(self.source_to_id[source_code])
        if self.source_to_id:
            logger.warning(f"Source '{source_code}' not seen during training - defaulting to 0")
        return 0

    def _prepare_sequence(self, values: np.ndarray, source_code: Optional[str]) -> Tuple[torch.Tensor, Dict[str, float]]:
        values = np.asarray(values, dtype=np.float32)
        stats = self.source_stats.get(source_code, {}) if source_code else {}
        mean = float(stats.get('mean', np.mean(values) if len(values) else 0.0))
        std = float(stats.get('std', np.std(values) + 1e-8 if len(values) else 1.0))
        if std == 0.0:
            std = 1.0

        normalized = (values - mean) / std if len(values) else np.zeros(self.sequence_length, dtype=np.float32)

        if len(normalized) >= self.sequence_length:
            normalized = normalized[-self.sequence_length:]
        else:
            pad_value = normalized[0] if len(normalized) else 0.0
            normalized = np.pad(
                normalized,
                (self.sequence_length - len(normalized), 0),
                mode='constant',
                constant_values=pad_value
            )

        sequence = torch.FloatTensor(normalized)
        return sequence, {'mean': mean, 'std': std}

    def _compute_market_liquidity_risk(self, bank_data: torch.Tensor, overall_risk: float) -> float:
        """Compute market liquidity risk component from bank data features."""

        # If we can extract market-specific features from the data
        # Market liquidity is affected by bid-ask spreads, trading volumes, price volatility
        try:
            # Convert tensor to numpy for analysis
            data_np = bank_data.cpu().numpy() if torch.is_tensor(bank_data) else bank_data

            # Compute volatility as a proxy for market liquidity stress
            if len(data_np.shape) > 1:
                volatility = np.std(data_np[:, 0]) if data_np.shape[1] > 0 else 0.0
            else:
                volatility = np.std(data_np)

            # Recent trend analysis
            recent_data = data_np[-RECENT_DATA_WINDOW:] if len(data_np) >= RECENT_DATA_WINDOW else data_np
            trend = np.polyfit(range(len(recent_data)), recent_data.flatten(), 1)[0]

            # Combine overall risk with market-specific indicators
            # Higher volatility and negative trend increase market liquidity risk
            volatility_factor = min(volatility / VOLATILITY_NORMALIZATION_FACTOR, 1.0)  # Normalize to 0-1
            trend_factor = max(-trend, 0) / TREND_NORMALIZATION_FACTOR  # Negative trends increase risk

            market_risk = overall_risk * 0.7 + volatility_factor * 0.2 + trend_factor * 0.1

            return float(np.clip(market_risk, 0.0, 1.0))

        except Exception as e:
            logger.warning(f"Could not compute market liquidity risk: {e}")
            # Fallback: slightly lower than overall risk
            return float(overall_risk * 0.9)

    def _compute_funding_liquidity_risk(self, bank_data: torch.Tensor, overall_risk: float) -> float:
        """Compute funding liquidity risk component from bank data features."""

        # Funding liquidity is affected by funding access, rollover risk, maturity mismatches
        try:
            data_np = bank_data.cpu().numpy() if torch.is_tensor(bank_data) else bank_data

            # Analyze data stability and concentration
            if len(data_np.shape) > 1:
                stability = 1.0 - np.std(data_np[:, 0]) / (np.mean(np.abs(data_np[:, 0])) + 1e-8)
            else:
                stability = 1.0 - np.std(data_np) / (np.mean(np.abs(data_np)) + 1e-8)

            # Lower stability means higher funding risk
            instability_factor = max(1.0 - stability, 0.0)

            # Funding risk tends to be slightly higher than overall risk during stress
            funding_risk = overall_risk * 0.8 + instability_factor * 0.2

            return float(np.clip(funding_risk, 0.0, 1.0))

        except Exception as e:
            logger.warning(f"Could not compute funding liquidity risk: {e}")
            # Fallback: slightly higher than overall risk
            return float(min(overall_risk * 1.1, 1.0))

    def _compute_operational_risk(self, bank_data: torch.Tensor) -> float:
        """Compute operational risk from data quality and completeness."""

        try:
            data_np = bank_data.cpu().numpy() if torch.is_tensor(bank_data) else bank_data

            # Operational risk is based on data quality indicators
            # Missing data, irregularities, and gaps increase operational risk
            data_flat = data_np.flatten()

            # Check for data irregularities
            if len(data_flat) > 0:
                # Data completeness (no NaN or extreme values)
                completeness = 1.0 - (np.isnan(data_flat).sum() / len(data_flat))

                # Data consistency (low coefficient of variation)
                if np.mean(data_flat) != 0:
                    cv = np.std(data_flat) / abs(np.mean(data_flat))
                    consistency = 1.0 / (1.0 + cv)
                else:
                    consistency = 0.5

                # Operational risk is inverse of data quality
                operational_risk = 1.0 - (0.6 * completeness + 0.4 * consistency)

                # Typically operational risk is lower than market/funding risks
                return float(np.clip(operational_risk * 0.5, OPERATIONAL_RISK_MINIMUM, OPERATIONAL_RISK_MAXIMUM))
            else:
                return OPERATIONAL_RISK_DEFAULT  # Default moderate operational risk

        except Exception as e:
            logger.warning(f"Could not compute operational risk: {e}")
            return OPERATIONAL_RISK_DEFAULT  # Default moderate operational risk

    def _compute_systemic_risk(
        self,
        bank_predictions: Dict[str, float],
        contagion_matrix: pd.DataFrame,
        systemic_banks: List[Tuple[str, float, str]]
    ) -> float:
        """Compute overall systemic risk score."""

        if len(bank_predictions) == 0:
            return 0.0

        # Component 1: Average individual risk
        avg_individual_risk = np.mean(list(bank_predictions.values()))

        # Component 2: Concentration of risk in systemic banks
        if systemic_banks:
            systemic_risk_concentration = np.mean([score for _, score, _ in systemic_banks[:3]])
        else:
            systemic_risk_concentration = 0.0

        # Component 3: Network interconnectedness
        if not contagion_matrix.empty:
            # Average off-diagonal contagion effect
            np_matrix = contagion_matrix.values
            np.fill_diagonal(np_matrix, 0)
            avg_contagion = np_matrix.mean()
        else:
            avg_contagion = 0.0

        systemic_risk = (
            WEIGHT_INDIVIDUAL_RISK * avg_individual_risk +
            WEIGHT_SYSTEMIC_CONCENTRATION * systemic_risk_concentration +
            WEIGHT_NETWORK_INTERCONNECTEDNESS * min(avg_contagion * 10, 1.0)  # Scale to 0-1
        )

        return float(systemic_risk)

    def _generate_recommendations(
        self,
        risk_value: float,
        risk_level: str,
        explanation: ExplanationResult
    ) -> List[str]:
        """Generate actionable recommendations."""

        recommendations = []

        if risk_level in ["high", "critical"]:
            recommendations.append(
                "URGENT: Increase High-Quality Liquid Assets (HQLA) by at least 15%"
            )
            recommendations.append(
                "Reduce reliance on short-term wholesale funding"
            )
            recommendations.append(
                "Activate contingency funding plan and stress test liquidity buffers"
            )

        if risk_level == "medium":
            recommendations.append(
                "Monitor intraday liquidity positions more frequently (at least hourly)"
            )
            recommendations.append(
                "Review and diversify funding sources"
            )

        # Specific recommendations based on risk drivers
        for driver_name, _, _ in explanation.top_drivers[:2]:
            if "funding" in driver_name.lower():
                recommendations.append(
                    f"Address funding pressure in {driver_name} - consider extending maturities"
                )
            elif "market" in driver_name.lower():
                recommendations.append(
                    f"Mitigate market liquidity risk in {driver_name} - reduce concentrated positions"
                )

        return recommendations[:5]  # Top 5


def generate_executive_summary(analysis: MultiBankAnalysis) -> str:
    """Generate non-technical executive summary."""

    summary = f"""
EXECUTIVE SUMMARY - Banking System Liquidity Risk Analysis
Date: {analysis.analysis_date}
Banks Analyzed: {analysis.num_banks}

OVERALL SYSTEM HEALTH:
- Average Risk Level: {analysis.avg_risk * 100:.1f}% ({_risk_to_text(analysis.avg_risk)})
- Highest Risk: {analysis.max_risk * 100:.1f}%
- Banks Requiring Immediate Attention: {analysis.num_critical_risk}
- Banks Under Elevated Stress: {analysis.num_high_risk}
- Systemic Risk Score: {analysis.systemic_risk_score * 100:.1f}%

CRITICAL FINDINGS:
"""

    # Add critical banks
    critical_banks = [
        (bank_id, profile) for bank_id, profile in analysis.bank_profiles.items()
        if profile.risk_level == "critical"
    ]

    if critical_banks:
        summary += f"\n{len(critical_banks)} BANK(S) AT CRITICAL RISK LEVELS:\n"
        for bank_id, profile in critical_banks[:5]:
            summary += f"- {profile.bank_name}: {profile.overall_liquidity_risk * 100:.1f}% risk\n"
            summary += f"  Key Issue: {profile.top_vulnerabilities[0] if profile.top_vulnerabilities else 'N/A'}\n"

    # Add systemic banks
    if analysis.systemic_banks:
        summary += f"\nSYSTEMICALLY IMPORTANT INSTITUTIONS:\n"
        for bank_id, importance, reason in analysis.systemic_banks[:3]:
            summary += f"- {bank_id}: Importance Score {importance * 100:.1f}% ({reason})\n"

    # Add contagion warnings
    if analysis.cascade_scenarios:
        summary += f"\nCONTAGION RISK WARNINGS:\n"
        for bank_id, cascade in list(analysis.cascade_scenarios.items())[:2]:
            summary += f"- If {bank_id} fails: {cascade['total_failures']} other banks at risk\n"

    summary += "\nRECOMMENDED ACTIONS:\n"
    # Aggregate recommendations from all critical/high risk banks
    all_recommendations = []
    for profile in analysis.bank_profiles.values():
        if profile.risk_level in ["critical", "high"]:
            all_recommendations.extend(profile.recommendations)

    # Get unique recommendations
    unique_recs = list(dict.fromkeys(all_recommendations))[:5]
    for i, rec in enumerate(unique_recs, 1):
        summary += f"{i}. {rec}\n"

    return summary


def _risk_to_text(risk: float) -> str:
    """Convert risk score to human-readable text."""
    if risk < 0.3:
        return "LOW RISK"
    elif risk < 0.6:
        return "MODERATE RISK"
    elif risk < 0.85:
        return "HIGH RISK"
    else:
        return "CRITICAL RISK"
