"""REAL Prediction Engine - NO PLACEHOLDERS - EU AI Act Compliant."""

import torch
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import logging
from pathlib import Path
import json

from modules.explainability.shap_explainer import ModelExplainer
from modules.risk.bank_analyzer import BankRiskAnalyzer, MultiBankAnalysis, generate_executive_summary

logger = logging.getLogger(__name__)


@dataclass
class PredictionResult:
    """REAL prediction result with explainability."""
    job_id: str
    model_path: str

    # Predictions
    predictions_df: pd.DataFrame  # All predictions with explanations

    # Risk analysis
    per_bank_risks: Dict[str, Any]  # bank_id -> risk profile
    multi_bank_analysis: Optional[MultiBankAnalysis]

    # Explainability (EU AI Act compliant)
    feature_importances: Dict[str, float]
    confidence_intervals: Dict[str, tuple]
    explanation_report: str

    # Metrics
    metrics: Dict[str, float]

    # User-friendly summary
    executive_summary: str


class RealPredictionEngine:
    """
    REAL Prediction Engine - NO MOCK DATA.

    Features:
    1. Uses trained models (not random predictions)
    2. EU AI Act compliant explainability
    3. Per-bank risk analysis
    4. Contagion/cascade simulation
    5. Human-readable reports
    """

    def __init__(self, model_path: str, device: torch.device, config: Dict):
        self.model_path = model_path
        self.device = device
        self.config = config
        self.sequence_length = self.config.get('sequence_length', 30)

        self.model_config = {}
        self.source_stats: Dict[str, Dict[str, float]] = {}
        self.sources: List[str] = []
        self.source_to_id: Dict[str, int] = {}

        # Load trained model
        self.model = self._load_model(model_path)
        self.model.eval()

        # Initialize explainability
        self.explainer = ModelExplainer(self.model, device)
        self.bank_analyzer = BankRiskAnalyzer(
            self.model,
            device,
            sequence_length=self.sequence_length,
            source_stats=self.source_stats,
            source_to_id=self.source_to_id
        )

        logger.info(f"Loaded model from {model_path}")

    def apply_scenario(
        self,
        input_data: pd.DataFrame,
        scenario: Dict[str, Any]
    ) -> pd.DataFrame:
        """
        Apply 'what-if' scenario transformations to input data.

        Supported scenarios:
        - liquidity_freeze: Reduce interbank lending
        - policy_intervention: Rate cuts, QE
        - bank_failure: Specific bank default
        - market_crash: Equity/volatility shocks
        - regional_shock: Geographic stress
        - sovereign_crisis: Sovereign debt stress
        - commodity_shock: Oil/commodity price changes
        - operational_risk: Cyber attacks, system failures
        - combined: Multiple simultaneous stresses

        Args:
            input_data: DataFrame with Date, Value, source_code (and optionally bank_id)
            scenario: Dictionary with scenario parameters

        Returns:
            Modified DataFrame with scenario applied
        """
        scenario_type = scenario.get('type', 'custom')
        modified_data = input_data.copy()

        logger.info(f"Applying scenario: {scenario_type}")

        if scenario_type == 'liquidity_freeze':
            # Reduce interbank exposures
            reduction = scenario.get('interbank_lending_reduction', 0.5)

            # Handle both network data (source_bank/target_bank) and time-series data (source_code)
            if 'source_bank' in modified_data.columns and 'target_bank' in modified_data.columns:
                # Network data from AI4Risk plugin - reduce all interbank exposures
                modified_data['Value'] *= (1 - reduction)
            elif 'source_code' in modified_data.columns:
                # Time-series data - reduce interbank-related sources
                modified_data.loc[
                    modified_data['source_code'].str.contains('INTERBANK|AI4RISK', na=False),
                    'Value'
                ] *= (1 - reduction)

        elif scenario_type == 'policy_intervention':
            # Apply rate cut (or hike if negative)
            rate_cut_bps = scenario.get('rate_cut_bps', 0)
            if rate_cut_bps != 0:
                modified_data.loc[
                    modified_data['source_code'].str.contains('RATE|SOFR|ESTR|EURIBOR|FED_FUNDS', na=False),
                    'Value'
                ] += rate_cut_bps / 10000  # Convert bps to decimal

            # Apply QE (increase liquidity)
            qe_amount = scenario.get('qe_amount', 0)
            if qe_amount > 0:
                liquidity_boost = qe_amount / 1e12  # Normalize
                modified_data.loc[
                    modified_data['source_code'].str.contains('RESERVES|M2|LIQUIDITY', na=False),
                    'Value'
                ] *= (1 + liquidity_boost)

        elif scenario_type == 'bank_failure':
            # Simulate bank failure by setting its metrics to critical
            failed_bank = scenario.get('failed_bank_id')
            haircut = scenario.get('exposure_haircut', 0.3)

            if failed_bank and 'bank_id' in modified_data.columns:
                # Failed bank's equity goes to zero
                modified_data.loc[
                    (modified_data['bank_id'] == failed_bank) &
                    (modified_data['source_code'].str.contains('EQUITY|CAPITAL', na=False)),
                    'Value'
                ] = 0

                # Counterparties take haircut on exposures
                if 'target_bank' in modified_data.columns:
                    modified_data.loc[
                        modified_data['target_bank'] == failed_bank,
                        'Value'
                    ] *= (1 - haircut)

        elif scenario_type == 'market_crash':
            # Apply stock market crash
            stock_drop = scenario.get('stock_drop_pct', 0.20)
            vol_spike = scenario.get('volatility_spike', 2.0)

            modified_data.loc[
                modified_data['source_code'].str.contains('STOCK|SPX|EURO|NIKKEI|HSI|EQUITY', na=False),
                'Value'
            ] *= (1 - stock_drop)

            modified_data.loc[
                modified_data['source_code'].str.contains('VIX|VOLATILITY|MOVE', na=False),
                'Value'
            ] *= vol_spike

            # Widen credit spreads
            spread_widening = scenario.get('credit_spread_widening', 0)
            if spread_widening > 0:
                modified_data.loc[
                    modified_data['source_code'].str.contains('SPREAD|TED|CREDIT', na=False),
                    'Value'
                ] += spread_widening

        elif scenario_type == 'regional_shock':
            # Apply regional shocks
            region_shocks = scenario.get('regional_shocks', [])
            for shock in region_shocks:
                region = shock['region']
                magnitude = shock['magnitude']

                # Apply shock to all data sources in region
                if 'region' in modified_data.columns:
                    modified_data.loc[
                        modified_data['region'] == region,
                        'Value'
                    ] *= (1 + magnitude)

        elif scenario_type == 'sovereign_crisis':
            # Sovereign debt crisis
            spread_widening = scenario.get('sovereign_spread_widening', 0.04)
            modified_data.loc[
                modified_data['source_code'].str.contains('BOND|YIELD|10Y|2Y', na=False),
                'Value'
            ] += spread_widening

            # Banking stress from sovereign exposure
            banking_stress = scenario.get('banking_stress', {})
            deposit_flight = banking_stress.get('deposit_flight', 0)
            if deposit_flight > 0 and 'bank_id' in modified_data.columns:
                modified_data.loc[
                    modified_data['source_code'].str.contains('DEPOSIT', na=False),
                    'Value'
                ] *= (1 - deposit_flight)

        elif scenario_type == 'commodity_shock':
            # Oil/commodity price shock
            oil_increase = scenario.get('oil_price_increase', 0)
            if oil_increase > 0:
                modified_data.loc[
                    modified_data['source_code'].str.contains('OIL|WTI|BRENT', na=False),
                    'Value'
                ] *= (1 + oil_increase)

            # Inflation impact
            inflation_spike = scenario.get('inflation_spike', 0)
            if inflation_spike > 0:
                modified_data.loc[
                    modified_data['source_code'].str.contains('CPI|HICP|INFLATION', na=False),
                    'Value'
                ] += inflation_spike

        elif scenario_type == 'operational_risk':
            # Cyber attack or operational disruption
            confidence_shock = scenario.get('market_disruption', {}).get('confidence_shock', 0.15)
            modified_data.loc[
                modified_data['source_code'].str.contains('VIX|VOLATILITY', na=False),
                'Value'
            ] *= (1 + confidence_shock)

        elif scenario_type == 'combined':
            # Apply multiple stresses recursively
            for sub_scenario_type in ['policy_intervention', 'market_crash', 'liquidity_freeze']:
                if any(k in scenario for k in ['rate_cut_bps', 'stock_drop_pct', 'interbank_lending_reduction']):
                    # Create sub-scenario: unpack original first, then override type to avoid infinite recursion
                    sub_scenario = {**scenario, 'type': sub_scenario_type}
                    modified_data = self.apply_scenario(modified_data, sub_scenario)

        logger.info(f"Scenario applied: {scenario_type}")
        return modified_data

    def _load_model(self, model_path: str) -> torch.nn.Module:
        """Load trained PyTorch model."""
        checkpoint = torch.load(model_path, map_location=self.device)

        # Recreate model architecture
        from modules.engine.multi_scale_trainer import MultiScaleTemporalAttentionModel

        # Get config from checkpoint
        config = checkpoint.get('config', {})
        self.model_config = config
        self.sequence_length = config.get('sequence_length', self.config.get('sequence_length', 30))
        self.source_stats = checkpoint.get('source_stats', {}) or {}
        self.sources = checkpoint.get('sources', []) or []
        self.source_to_id = {src: idx for idx, src in enumerate(self.sources)}

        sources = checkpoint.get('sources', [])
        num_sources = max(len(sources), 1)

        model = MultiScaleTemporalAttentionModel(
            num_sources=num_sources,
            sequence_length=self.sequence_length,
            d_model=config.get('d_model', 128),
            nhead=config.get('nhead', 8),
            num_layers=config.get('num_layers', 3),
            dropout=config.get('dropout', 0.1)
        )

        model.load_state_dict(checkpoint['model_state_dict'])
        model.to(self.device)

        return model

    def predict(
        self,
        input_data: pd.DataFrame,
        bank_exposures: Optional[Dict[tuple, float]] = None
    ) -> PredictionResult:
        """
        Make predictions with full explainability.

        Args:
            input_data: DataFrame with Date, Value, source_code (and optionally bank_id)
            bank_exposures: Inter-bank exposures for contagion analysis

        Returns:
            PredictionResult with predictions and explanations
        """
        logger.info("Starting REAL prediction with explainability")

        # Check if multi-bank scenario
        has_bank_id = 'bank_id' in input_data.columns

        if has_bank_id:
            # Multi-bank analysis
            return self._predict_multi_bank(input_data, bank_exposures)
        else:
            # Single entity analysis
            return self._predict_single(input_data)

    def _predict_single(self, input_data: pd.DataFrame) -> PredictionResult:
        """Predict for single entity."""

        # Group by source
        predictions_list = []
        explanations = {}
        feature_importances_total = {}

        for source_code in input_data['source_code'].unique():
            source_data = input_data[input_data['source_code'] == source_code]
            source_data = source_data.sort_values('Date')

            # Get source ID
            source_id = self._map_source_id(source_code)

            # Prepare sequence - use 'Close' column from timeseries data
            value_column = 'Close' if 'Close' in source_data.columns else 'Value'
            series = source_data[value_column].astype(float)
            series = series.ffill().bfill()
            values = series.fillna(0).values
            sequence, stats = self._prepare_sequence(values, source_code)

            # Get explanation
            explanation = self.explainer.explain_prediction(
                sequence,
                source_id,
                [f"t-{i}" for i in range(self.sequence_length)],
                actual_value=float(values[-1]) if len(values) else None
            )

            normalized_prediction = float(explanation.prediction_value)
            denorm_prediction = self._denormalize_prediction(normalized_prediction, stats)

            predictions_list.append({
                'source': source_code,
                'prediction': denorm_prediction,
                'risk_score': normalized_prediction,
                'confidence_lower': explanation.confidence_lower,
                'confidence_upper': explanation.confidence_upper,
                'explanation': explanation.explanation_text
            })

            explanations[source_code] = explanation

            # Aggregate feature importances
            for feature, importance in explanation.feature_contributions.items():
                if np.isnan(importance):
                    continue
                feature_importances_total[feature] = feature_importances_total.get(feature, 0.0) + importance

        predictions_df = pd.DataFrame(predictions_list)

        # Generate executive summary
        if not predictions_df.empty:
            avg_risk = float(predictions_df['risk_score'].mean())
            max_risk = float(predictions_df['risk_score'].max())
            min_risk = float(predictions_df['risk_score'].min())
        else:
            avg_risk = max_risk = min_risk = 0.0

        executive_summary = f"""
LIQUIDITY RISK PREDICTION SUMMARY

Overall Risk Level: {avg_risk * 100:.1f}%
Maximum Risk: {max_risk * 100:.1f}%
Data Sources Analyzed: {len(predictions_df)}

KEY FINDINGS:
{self._generate_key_findings(predictions_df, explanations)}

This analysis is EU AI Act compliant with full explainability.
All predictions include confidence intervals and feature attributions.
"""

        return PredictionResult(
            job_id=self.config.get('job_id', 'unknown'),
            model_path=self.model_path,
            predictions_df=predictions_df,
            per_bank_risks={},
            multi_bank_analysis=None,
            feature_importances=feature_importances_total,
            confidence_intervals={
                src: (exp.confidence_lower, exp.confidence_upper)
                for src, exp in explanations.items()
            },
            explanation_report=self._generate_explanation_report(explanations),
            metrics={
                'avg_risk_score': avg_risk,
                'max_risk_score': max_risk,
                'min_risk_score': min_risk,
                'avg_prediction_value': float(predictions_df['prediction'].mean()) if not predictions_df.empty else 0.0,
                'max_prediction_value': float(predictions_df['prediction'].max()) if not predictions_df.empty else 0.0,
                'min_prediction_value': float(predictions_df['prediction'].min()) if not predictions_df.empty else 0.0
            },
            executive_summary=executive_summary
        )

    def _predict_multi_bank(
        self,
        input_data: pd.DataFrame,
        bank_exposures: Optional[Dict[tuple, float]]
    ) -> PredictionResult:
        """Predict for multiple banks with contagion analysis."""

        logger.info("Multi-bank prediction with contagion analysis")

        # Group data by bank
        bank_data = {}
        for bank_id in input_data['bank_id'].unique():
            bank_data[bank_id] = input_data[input_data['bank_id'] == bank_id]

        # Run multi-bank analysis
        multi_bank_analysis = self.bank_analyzer.analyze_multiple_banks(
            bank_data,
            bank_exposures,
            feature_names=[f"t-{i}" for i in range(self.sequence_length)]
        )

        # Extract predictions
        predictions_list = []
        per_bank_risks = {}

        for bank_id, profile in multi_bank_analysis.bank_profiles.items():
            predictions_list.append({
                'bank_id': bank_id,
                'bank_name': profile.bank_name,
                'overall_risk': profile.overall_liquidity_risk,
                'market_liquidity_risk': profile.market_liquidity_risk,
                'funding_liquidity_risk': profile.funding_liquidity_risk,
                'risk_level': profile.risk_level,
                'systemic_importance': profile.systemic_importance,
                'confidence_lower': profile.confidence_lower,
                'confidence_upper': profile.confidence_upper,
                'explanation': profile.explanation.explanation_text,
                'top_vulnerability': profile.top_vulnerabilities[0] if profile.top_vulnerabilities else 'N/A'
            })

            per_bank_risks[bank_id] = asdict(profile)

        predictions_df = pd.DataFrame(predictions_list)

        # Generate executive summary
        executive_summary = generate_executive_summary(multi_bank_analysis)

        # Aggregate feature importances
        feature_importances = {}
        for profile in multi_bank_analysis.bank_profiles.values():
            for feature, importance in profile.explanation.feature_contributions.items():
                feature_importances[feature] = feature_importances.get(feature, 0) + abs(importance)

        return PredictionResult(
            job_id=self.config.get('job_id', 'unknown'),
            model_path=self.model_path,
            predictions_df=predictions_df,
            per_bank_risks=per_bank_risks,
            multi_bank_analysis=multi_bank_analysis,
            feature_importances=feature_importances,
            confidence_intervals={
                bank_id: (profile.confidence_lower, profile.confidence_upper)
                for bank_id, profile in multi_bank_analysis.bank_profiles.items()
            },
            explanation_report=self._generate_multi_bank_explanation_report(multi_bank_analysis),
            metrics={
                'avg_risk': multi_bank_analysis.avg_risk,
                'max_risk': multi_bank_analysis.max_risk,
                'systemic_risk': multi_bank_analysis.systemic_risk_score,
                'num_high_risk': multi_bank_analysis.num_high_risk,
                'num_critical_risk': multi_bank_analysis.num_critical_risk
            },
            executive_summary=executive_summary
        )

    def _map_source_id(self, source_code: str) -> int:
        if self.source_to_id and source_code in self.source_to_id:
            return int(self.source_to_id[source_code])
        if self.source_to_id:
            logger.warning(f"Source '{source_code}' not seen during training - defaulting to source id 0")
            return 0
        return 0

    def _prepare_sequence(self, values: np.ndarray, source_code: str) -> tuple[torch.Tensor, Dict[str, float]]:
        values = np.asarray(values, dtype=np.float32)
        stats = self.source_stats.get(source_code, {})
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

    def _denormalize_prediction(self, normalized_value: float, stats: Dict[str, float]) -> float:
        mean = stats.get('mean', 0.0)
        std = stats.get('std', 1.0)
        return float(normalized_value * std + mean)

    def _generate_key_findings(self, predictions_df: pd.DataFrame, explanations: Dict) -> str:
        """Generate key findings text."""
        findings = []

        # Find highest risk source (skip if all NaN)
        valid_predictions = predictions_df['prediction'].dropna()
        if len(valid_predictions) > 0:
            max_risk_row = predictions_df.loc[valid_predictions.idxmax()]
            findings.append(f"- Highest risk in: {max_risk_row['source']} ({max_risk_row['prediction'] * 100:.1f}%)")
        else:
            findings.append("- No valid risk predictions available")

        # Find most important features
        all_features = {}
        for exp in explanations.values():
            for feature, importance in exp.feature_contributions.items():
                all_features[feature] = all_features.get(feature, 0) + abs(importance)

        top_feature = max(all_features.items(), key=lambda x: x[1])
        findings.append(f"- Primary risk driver: {top_feature[0]}")

        # Confidence assessment
        avg_confidence_width = predictions_df.apply(
            lambda row: row['confidence_upper'] - row['confidence_lower'], axis=1
        ).mean()

        if avg_confidence_width < 0.1:
            findings.append("- Model confidence: HIGH (narrow prediction intervals)")
        elif avg_confidence_width < 0.3:
            findings.append("- Model confidence: MODERATE")
        else:
            findings.append("- Model confidence: LOW (wide prediction intervals - more data needed)")

        return "\n".join(findings)

    def _generate_explanation_report(self, explanations: Dict) -> str:
        """Generate detailed explanation report."""
        report = "DETAILED EXPLANATION REPORT\n" + "="*50 + "\n\n"

        for source, exp in explanations.items():
            report += f"Source: {source}\n"
            report += f"Prediction: {exp.prediction_value:.4f}\n"
            report += f"Confidence: [{exp.confidence_lower:.4f}, {exp.confidence_upper:.4f}]\n\n"

            report += "Top Contributing Factors:\n"
            for i, (feature, contrib, direction) in enumerate(exp.top_drivers, 1):
                report += f"  {i}. {feature}: {contrib:.4f} ({direction} risk)\n"

            report += f"\n{exp.explanation_text}\n"
            report += "\n" + "-"*50 + "\n\n"

        return report

    def _generate_multi_bank_explanation_report(self, analysis: MultiBankAnalysis) -> str:
        """Generate multi-bank explanation report."""
        report = "MULTI-BANK ANALYSIS REPORT\n" + "="*70 + "\n\n"

        report += f"Date: {analysis.analysis_date}\n"
        report += f"Banks Analyzed: {analysis.num_banks}\n"
        report += f"Systemic Risk Score: {analysis.systemic_risk_score * 100:.1f}%\n\n"

        report += "INDIVIDUAL BANK ASSESSMENTS:\n" + "-"*70 + "\n"
        for bank_id, profile in analysis.bank_profiles.items():
            report += f"\n{profile.bank_name} ({bank_id}):\n"
            report += f"  Overall Risk: {profile.overall_liquidity_risk * 100:.1f}% ({profile.risk_level})\n"
            report += f"  Confidence: [{profile.confidence_lower * 100:.1f}%, {profile.confidence_upper * 100:.1f}%]\n"
            report += f"  Systemic Importance: {profile.systemic_importance * 100:.1f}%\n"

            if profile.top_vulnerabilities:
                report += f"  Key Vulnerabilities:\n"
                for vuln in profile.top_vulnerabilities[:2]:
                    report += f"    - {vuln}\n"

            if profile.recommendations:
                report += f"  Recommendations:\n"
                for rec in profile.recommendations[:2]:
                    report += f"    - {rec}\n"

        if analysis.systemic_banks:
            report += "\n\nSYSTEMICALLY IMPORTANT BANKS:\n" + "-"*70 + "\n"
            for bank_id, importance, reason in analysis.systemic_banks:
                report += f"  {bank_id}: {importance * 100:.1f}% importance ({reason})\n"

        if analysis.cascade_scenarios:
            report += "\n\nCONTAGION SCENARIOS:\n" + "-"*70 + "\n"
            for bank_id, cascade in analysis.cascade_scenarios.items():
                report += f"  If {bank_id} fails:\n"
                report += f"    - Total failures: {cascade['total_failures']}\n"
                report += f"    - Cascade depth: {cascade['cascade_depth']} rounds\n"
                report += f"    - Affected banks: {', '.join(cascade['affected_banks'])}\n"

        report += "\n" + "="*70 + "\n"
        report += "This report is EU AI Act compliant with full model explainability.\n"

        return report
