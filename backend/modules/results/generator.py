"""RESULTS Module Generator - Comprehensive reporting and visualization."""

import logging
import os
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import pandas as pd
import numpy as np

from modules.engine.orchestrator import EngineResult, RiskScores

logger = logging.getLogger(__name__)


class ReportSection(str, Enum):
    EXECUTIVE_SUMMARY = "executive_summary"
    GEOGRAPHIC_ANALYSIS = "geographic_analysis"
    INSTITUTIONAL_PROFILES = "institutional_profiles"
    MARKET_LIQUIDITY = "market_liquidity"
    FUNDING_LIQUIDITY = "funding_liquidity"
    SYSTEMIC_RISK = "systemic_risk"
    RECOMMENDATIONS = "recommendations"
    VISUALIZATIONS = "visualizations"


@dataclass
class ExecutiveSummary:
    """Executive summary of risk analysis."""
    overall_risk_score: float  # 0-100
    risk_level: str  # low, medium, high, critical

    critical_alerts: List[Dict[str, str]]
    top_risk_factors: List[Dict[str, Any]]
    key_recommendations: List[str]
    key_findings: List[str]

    num_alerts: int
    num_institutions: int
    data_points_analyzed: int

    period: str
    generated_at: datetime


@dataclass
class GeographicAnalysis:
    """Regional risk breakdown."""
    regional_scores: Dict[str, float]  # region -> score
    cross_border_risks: List[Dict[str, Any]]
    contagion_paths: List[Dict[str, Any]]
    
    visualizations: Dict[str, str]  # chart_name -> data_path


@dataclass
class InstitutionalProfile:
    """Individual institution risk profile."""
    institution_id: str
    name: str
    
    market_liquidity_score: float
    funding_liquidity_score: float
    systemic_importance: float
    
    vulnerabilities: List[str]
    strengths: List[str]
    recommendations: List[str]


@dataclass
class Recommendation:
    """Actionable recommendation."""
    target: str  # regulator, bank, payment_system
    priority: str  # critical, high, medium, low
    category: str  # capital, liquidity, operational
    
    title: str
    description: str
    rationale: str
    
    actions: List[Dict[str, Any]]
    expected_impact: str
    timeframe: str


@dataclass
class ComprehensiveReport:
    """Complete risk analysis report."""
    job_id: str
    
    executive_summary: ExecutiveSummary
    geographic_analysis: GeographicAnalysis
    institutional_profiles: List[InstitutionalProfile]
    
    market_liquidity_report: Dict[str, Any]
    funding_liquidity_report: Dict[str, Any]
    systemic_risk_report: Dict[str, Any]
    
    recommendations: List[Recommendation]
    visualizations: Dict[str, Any]
    
    generated_at: datetime
    version: str


class ResultsGenerator:
    """
    Main generator for RESULTS module.
    
    Creates comprehensive reports with visualizations and recommendations.
    """
    
    def __init__(self, job_id: str, output_dir: str):
        self.job_id = job_id
        self.output_dir = output_dir

    def _load_predictions_dataframe(self, predictions_path: Optional[str]) -> Optional[pd.DataFrame]:
        """Load predictions file into a DataFrame if available."""
        if not predictions_path:
            return None

        path = Path(predictions_path)
        if not path.exists():
            logger.warning(f"[{self.job_id}] Predictions file not found at {predictions_path}")
            return None

        try:
            if path.suffix == ".parquet":
                return pd.read_parquet(path)
            if path.suffix == ".csv":
                return pd.read_csv(path)
            if path.suffix == ".json":
                return pd.read_json(path)
        except Exception as exc:
            logger.error(f"[{self.job_id}] Failed to load predictions from {predictions_path}: {exc}")
            return None

        logger.warning(f"[{self.job_id}] Unsupported predictions format: {predictions_path}")
        return None

    @staticmethod
    def _safe_float(value: Any) -> float:
        """Coerce values to float, returning NaN on failure."""
        try:
            if value is None:
                return float('nan')
            return float(value)
        except (TypeError, ValueError):
            return float('nan')
    
    def generate(self, engine_result: EngineResult) -> ComprehensiveReport:
        """
        Generate comprehensive risk analysis report.
        
        Args:
            engine_result: Results from ENGINE module
            
        Returns:
            ComprehensiveReport with all sections
        """
        try:
            logger.info(f"[{self.job_id}] Generating comprehensive report")
            
            # Section 1: Executive Summary
            logger.info(f"[{self.job_id}] Generating executive summary")
            exec_summary = self._generate_executive_summary(engine_result)
            
            # Section 2: Geographic Analysis
            logger.info(f"[{self.job_id}] Analyzing geographic risks")
            geo_analysis = self._generate_geographic_analysis(engine_result)
            
            # Section 3: Institutional Profiles
            logger.info(f"[{self.job_id}] Building institutional profiles")
            inst_profiles = self._generate_institutional_profiles(engine_result)
            
            # Section 4-6: Detailed Risk Reports
            logger.info(f"[{self.job_id}] Creating detailed risk reports")
            market_liq = self._generate_market_liquidity_report(engine_result)
            funding_liq = self._generate_funding_liquidity_report(engine_result)
            systemic = self._generate_systemic_risk_report(engine_result)
            
            # Section 7: Recommendations
            logger.info(f"[{self.job_id}] Formulating recommendations")
            recommendations = self._generate_recommendations(engine_result.risk_scores)
            
            # Section 8: Visualizations
            logger.info(f"[{self.job_id}] Creating visualizations")
            visualizations = self._create_visualizations(engine_result)
            
            report = ComprehensiveReport(
                job_id=self.job_id,
                executive_summary=exec_summary,
                geographic_analysis=geo_analysis,
                institutional_profiles=inst_profiles,
                market_liquidity_report=market_liq,
                funding_liquidity_report=funding_liq,
                systemic_risk_report=systemic,
                recommendations=recommendations,
                visualizations=visualizations,
                generated_at=datetime.now(timezone.utc),
                version="1.0.0"
            )
            
            logger.info(f"[{self.job_id}] Report generation completed")
            return report
            
        except Exception as e:
            logger.error(f"[{self.job_id}] Report generation failed: {e}")
            raise
    
    def _generate_executive_summary(self, engine_result: EngineResult) -> ExecutiveSummary:
        """Generate executive summary."""

        risk_scores = engine_result.risk_scores
        predictions_df = self._load_predictions_dataframe(engine_result.predictions_path)

        num_institutions = 0
        data_points = 0
        analysis_period = "Not available"
        key_findings: List[str] = []

        if predictions_df is not None and not predictions_df.empty:
            data_points = len(predictions_df)

            entity_columns = ['bank_id', 'institution_id', 'institution', 'source', 'counterparty']
            id_col = next((col for col in entity_columns if col in predictions_df.columns), None)
            if id_col:
                num_institutions = int(predictions_df[id_col].nunique())

            # Determine analysis period
            if 'date' in predictions_df.columns:
                dates = pd.to_datetime(predictions_df['date'], errors='coerce').dropna()
                if not dates.empty:
                    analysis_period = f"{dates.min().date()} to {dates.max().date()}"
            elif 'timestamp' in predictions_df.columns:
                dates = pd.to_datetime(predictions_df['timestamp'], errors='coerce').dropna()
                if not dates.empty:
                    analysis_period = f"{dates.min().date()} to {dates.max().date()}"

            if 'prediction' in predictions_df.columns:
                predictions_numeric = pd.to_numeric(predictions_df['prediction'], errors='coerce').dropna()
                if not predictions_numeric.empty:
                    key_findings.append(f"Average predicted liquidity stress: {predictions_numeric.mean():.2f}")
                    key_findings.append(f"Maximum predicted liquidity stress: {predictions_numeric.max():.2f}")
                    key_findings.append(f"Prediction volatility (std dev): {predictions_numeric.std():.2f}")

            if 'error' in predictions_df.columns:
                errors_numeric = pd.to_numeric(predictions_df['error'], errors='coerce').dropna()
                if not errors_numeric.empty:
                    key_findings.append(f"Mean prediction error: {errors_numeric.mean():.4f}")

        # Add fallbacks based on available risk scores
        market_liq = risk_scores.market_liquidity
        funding_liq = risk_scores.funding_liquidity
        systemic = risk_scores.systemic_risk

        market_overall = self._safe_float(market_liq.get('overall', market_liq.get('current')))
        funding_overall = self._safe_float(funding_liq.get('overall', funding_liq.get('current')))
        systemic_overall = self._safe_float(systemic.get('network_risk', systemic.get('current')))

        if not key_findings:
            if np.isfinite(market_overall):
                key_findings.append(f"Market liquidity score (overall): {market_overall:.2f}")
            if np.isfinite(funding_overall):
                key_findings.append(f"Funding liquidity score (overall): {funding_overall:.2f}")
            if np.isfinite(systemic_overall):
                key_findings.append(f"Systemic network risk: {systemic_overall:.2f}")

        critical_alerts = []
        if risk_scores.overall_score > 80:
            critical_alerts.append({
                "level": "critical",
                "message": "Systemic risk at critical levels - immediate action required"
            })

        top_risk_factors = [
            {"factor": "Market Liquidity Stress", "score": market_overall, "trend": self._safe_float(market_liq.get('trend', 0.0))},
            {"factor": "Funding Pressure", "score": funding_overall, "trend": self._safe_float(funding_liq.get('trend', 0.0))},
            {"factor": "Network Contagion Risk", "score": systemic_overall, "trend": self._safe_float(systemic.get('trend', 0.0))}
        ]

        key_recommendations = [
            "Increase liquidity buffers for high-risk institutions",
            "Enhance cross-border coordination mechanisms",
            "Implement additional stress testing scenarios"
        ]

        return ExecutiveSummary(
            overall_risk_score=risk_scores.overall_score,
            risk_level=risk_scores.risk_level,
            critical_alerts=critical_alerts,
            top_risk_factors=top_risk_factors,
            key_recommendations=key_recommendations,
            key_findings=key_findings,
            num_alerts=len(critical_alerts),
            num_institutions=num_institutions,
            data_points_analyzed=data_points,
            period=analysis_period,
            generated_at=datetime.now(timezone.utc)
        )
    
    def _generate_geographic_analysis(self, engine_result: EngineResult) -> GeographicAnalysis:
        """Generate geographic risk analysis."""

        predictions_df = self._load_predictions_dataframe(engine_result.predictions_path)

        regional_scores: Dict[str, float] = {}
        cross_border_risks: List[Dict[str, Any]] = []
        contagion_paths: List[Dict[str, Any]] = []
        visualizations: Dict[str, Any] = {}

        if predictions_df is not None and not predictions_df.empty:
            if {'region', 'prediction'}.issubset(predictions_df.columns):
                grouped = (
                    predictions_df
                    .dropna(subset=['region', 'prediction'])
                    .assign(prediction=lambda df: pd.to_numeric(df['prediction'], errors='coerce'))
                    .dropna(subset=['prediction'])
                    .groupby('region')['prediction']
                    .mean()
                    .sort_values(ascending=False)
                )
                regional_scores = {str(region): float(score) for region, score in grouped.items()}
                if regional_scores:
                    visualizations['regional_average_risk'] = {
                        "type": "bar",
                        "labels": list(regional_scores.keys()),
                        "values": list(regional_scores.values())
                    }

            cross_border_cols = {'from_region', 'to_region', 'exposure'}
            if cross_border_cols.issubset(predictions_df.columns):
                flows = (
                    predictions_df
                    .dropna(subset=list(cross_border_cols))
                    .assign(exposure=lambda df: pd.to_numeric(df['exposure'], errors='coerce'))
                    .dropna(subset=['exposure'])
                    .groupby(['from_region', 'to_region'])['exposure']
                    .sum()
                    .reset_index()
                    .sort_values('exposure', ascending=False)
                )
                cross_border_risks = [
                    {
                        "from": str(row['from_region']),
                        "to": str(row['to_region']),
                        "exposure": float(row['exposure'])
                    }
                    for _, row in flows.head(10).iterrows()
                ]

            if {'path_id', 'regions_in_path', 'probability'}.issubset(predictions_df.columns):
                contagion_paths = [
                    {
                        "path_id": str(row['path_id']),
                        "regions": row['regions_in_path'],
                        "probability": float(row['probability'])
                    }
                    for _, row in predictions_df.dropna(subset=['path_id']).iterrows()
                ]

        return GeographicAnalysis(
            regional_scores=regional_scores,
            cross_border_risks=cross_border_risks,
            contagion_paths=contagion_paths,
            visualizations=visualizations
        )
    
    def _generate_institutional_profiles(self, engine_result: EngineResult) -> List[InstitutionalProfile]:
        """Generate institution-level profiles from risk scores."""

        predictions_df = self._load_predictions_dataframe(engine_result.predictions_path)
        profiles: List[InstitutionalProfile] = []

        entity_columns = ['bank_id', 'institution_id', 'institution', 'source']
        metric_candidates = ['prediction', 'predicted', 'risk_score', 'market_liquidity']
        funding_candidates = ['funding_liquidity', 'funding_score']
        systemic_candidates = ['systemic_risk', 'systemic_score']

        if predictions_df is not None and not predictions_df.empty:
            id_col = next((col for col in entity_columns if col in predictions_df.columns), None)
            metric_col = next((col for col in metric_candidates if col in predictions_df.columns), None)

            if id_col and metric_col:
                funding_col = next((col for col in funding_candidates if col in predictions_df.columns), None)
                systemic_col = next((col for col in systemic_candidates if col in predictions_df.columns), None)

                grouped = predictions_df.groupby(id_col)

                for entity_id, group in grouped:
                    market_values = pd.to_numeric(group[metric_col], errors='coerce').dropna()
                    if market_values.empty:
                        continue

                    funding_values = pd.to_numeric(group[funding_col], errors='coerce').dropna() if funding_col else market_values
                    systemic_values = pd.to_numeric(group[systemic_col], errors='coerce').dropna() if systemic_col else market_values

                    vulnerabilities: List[str] = []
                    strengths: List[str] = []

                    market_mean = float(market_values.mean())
                    funding_mean = float(funding_values.mean())
                    systemic_mean = float(systemic_values.mean())

                    if market_mean > 70:
                        vulnerabilities.append("Market liquidity risk above supervisory comfort zone")
                    if funding_mean > 70:
                        vulnerabilities.append("Sustained funding pressures detected")
                    if systemic_mean > 70:
                        vulnerabilities.append("High contagion centrality")

                    if market_values.std() < 10:
                        strengths.append("Stable market liquidity conditions")
                    if funding_mean < 40:
                        strengths.append("Resilient funding profile")
                    if systemic_mean < 40:
                        strengths.append("Low network contagion influence")

                    recommendations: List[str] = []
                    if market_mean > 60:
                        recommendations.append("Deploy additional market-making capacity and pre-arranged funding lines")
                    if funding_mean > 60:
                        recommendations.append("Broaden tenor mix and diversify liability sources")
                    if systemic_mean > 60:
                        recommendations.append("Coordinate with peer institutions on joint liquidity drills")

                    profiles.append(
                        InstitutionalProfile(
                            institution_id=str(entity_id),
                            name=str(entity_id),
                            market_liquidity_score=market_mean,
                            funding_liquidity_score=funding_mean,
                            systemic_importance=systemic_mean,
                            vulnerabilities=vulnerabilities or ["No acute vulnerabilities detected"],
                            strengths=strengths or ["Maintain current liquidity governance"],
                            recommendations=recommendations or ["Continue monitoring risk dashboards"]
                        )
                    )

        if not profiles:
            # Fallback to aggregate profile derived from risk scores
            market_liq = engine_result.risk_scores.market_liquidity
            funding_liq = engine_result.risk_scores.funding_liquidity
            systemic_risk = engine_result.risk_scores.systemic_risk

            market_score = float(market_liq.get('overall', market_liq.get('current', np.nan)))
            funding_score = float(funding_liq.get('overall', funding_liq.get('current', np.nan)))
            systemic_importance = float(systemic_risk.get('network_risk', systemic_risk.get('current', np.nan)))

            vulnerabilities = []
            if np.isfinite(market_score) and market_score > 70:
                vulnerabilities.append("Elevated market liquidity stress")
            if np.isfinite(funding_score) and funding_score > 70:
                vulnerabilities.append("Intensifying funding outflows")
            if np.isfinite(systemic_importance) and systemic_importance > 70:
                vulnerabilities.append("High contagion sensitivity")

            strengths = []
            if np.isfinite(market_score) and market_score < 40:
                strengths.append("Stable market-making conditions")
            if np.isfinite(funding_score) and funding_score < 40:
                strengths.append("Comfortable funding buffers")
            if market_liq.get('trend', 0) < 0:
                strengths.append("Improving market liquidity trajectory")

            recommendations = []
            if np.isfinite(market_score) and market_score > 60:
                recommendations.append("Enhance secondary market liquidity provision")
            if np.isfinite(funding_score) and funding_score > 60:
                recommendations.append("Accelerate contingency funding planning")
            if np.isfinite(systemic_importance) and systemic_importance > 60:
                recommendations.append("Review interbank exposure limits")

            profiles.append(
                InstitutionalProfile(
                    institution_id="AGGREGATE",
                    name="System Aggregate Profile",
                    market_liquidity_score=market_score if np.isfinite(market_score) else 0.0,
                    funding_liquidity_score=funding_score if np.isfinite(funding_score) else 0.0,
                    systemic_importance=systemic_importance if np.isfinite(systemic_importance) else 0.0,
                    vulnerabilities=vulnerabilities or ["No critical vulnerabilities detected"],
                    strengths=strengths or ["Monitoring recommended"],
                    recommendations=recommendations or ["Continue supervisory monitoring"]
                )
            )

        return profiles
    
    def _generate_market_liquidity_report(self, engine_result: EngineResult) -> Dict[str, Any]:
        """Generate market liquidity analysis."""
        metrics = engine_result.risk_scores.market_liquidity
        predictions_df = self._load_predictions_dataframe(engine_result.predictions_path)

        report = {
            "overall_score": self._safe_float(metrics.get('overall', metrics.get('current'))),
            "current_score": self._safe_float(metrics.get('current', np.nan)),
            "trend": self._safe_float(metrics.get('trend', 0.0)),
            "volatility": self._safe_float(metrics.get('volatility', np.nan)),
            "percentile_95": self._safe_float(metrics.get('percentile_95', np.nan)),
            "data_points": 0,
            "recent_observations": []
        }

        if predictions_df is not None and not predictions_df.empty:
            metric_col = None
            for candidate in ['market_liquidity', 'prediction', 'predicted']:
                if candidate in predictions_df.columns:
                    metric_col = candidate
                    break

            if metric_col:
                series = pd.to_numeric(predictions_df[metric_col], errors='coerce').dropna()
                report["data_points"] = int(len(series))
                report["recent_observations"] = [float(x) for x in series.tail(10)]
                if not np.isfinite(report["overall_score"]) and not series.empty:
                    report["overall_score"] = float(series.mean())

        return report
    
    def _generate_funding_liquidity_report(self, engine_result: EngineResult) -> Dict[str, Any]:
        """Generate funding liquidity analysis."""
        metrics = engine_result.risk_scores.funding_liquidity
        predictions_df = self._load_predictions_dataframe(engine_result.predictions_path)

        report = {
            "overall_score": self._safe_float(metrics.get('overall', metrics.get('current'))),
            "current_score": self._safe_float(metrics.get('current', np.nan)),
            "trend": self._safe_float(metrics.get('trend', 0.0)),
            "volatility": self._safe_float(metrics.get('volatility', np.nan)),
            "percentile_95": self._safe_float(metrics.get('percentile_95', np.nan)),
            "data_points": 0
        }

        if predictions_df is not None and not predictions_df.empty:
            if 'funding_liquidity' in predictions_df.columns:
                series = pd.to_numeric(predictions_df['funding_liquidity'], errors='coerce').dropna()
                report["data_points"] = int(len(series))
                if not np.isfinite(report["overall_score"]) and not series.empty:
                    report["overall_score"] = float(series.mean())

        return report
    
    def _generate_systemic_risk_report(self, engine_result: EngineResult) -> Dict[str, Any]:
        """Generate systemic risk analysis."""
        metrics = engine_result.risk_scores.systemic_risk
        report = {
            "network_risk": self._safe_float(metrics.get('network_risk', np.nan)),
            "current": self._safe_float(metrics.get('current', np.nan)),
            "trend": self._safe_float(metrics.get('trend', 0.0)),
            "max_risk": self._safe_float(metrics.get('max_risk', np.nan))
        }

        explanations_df = self._load_predictions_dataframe(engine_result.explanations_path) if engine_result.explanations_path else None
        if explanations_df is not None and 'attention_weights' in explanations_df.columns:
            report["attention_weights"] = explanations_df['attention_weights'].tolist()

        return report
    
    def _generate_recommendations(self, risk_scores: RiskScores) -> List[Recommendation]:
        """Generate actionable recommendations."""
        
        recommendations = []
        
        # For Regulators
        if risk_scores.overall_score > 70:
            recommendations.append(Recommendation(
                target="regulator",
                priority="high",
                category="capital",
                title="Increase Countercyclical Capital Buffer",
                description="Raise CCyB from 0% to 1.5% for all systemic institutions",
                rationale="Elevated systemic risk requires additional loss-absorbing capacity",
                actions=[
                    {"action": "Announce CCyB increase", "deadline": "30 days"},
                    {"action": "Implement phase-in schedule", "deadline": "12 months"}
                ],
                expected_impact="Reduce probability of system-wide distress by 15-20%",
                timeframe="12-18 months"
            ))
        
        # For Banks
        recommendations.append(Recommendation(
            target="bank",
            priority="medium",
            category="liquidity",
            title="Enhance Liquidity Risk Management",
            description="Implement real-time liquidity monitoring and stress testing",
            rationale="Current funding pressures require more frequent monitoring",
            actions=[
                {"action": "Deploy intraday liquidity monitoring", "deadline": "90 days"},
                {"action": "Increase cash buffers by 10%", "deadline": "60 days"}
            ],
            expected_impact="Improve resilience to funding shocks",
            timeframe="3-6 months"
        ))
        
        # For Payment Systems
        recommendations.append(Recommendation(
            target="payment_system",
            priority="medium",
            category="operational",
            title="Optimize Collateral Management",
            description="Implement automated collateral optimization and real-time monitoring",
            rationale="Reduce settlement risk and operational inefficiencies",
            actions=[
                {"action": "Deploy collateral optimization engine", "deadline": "6 months"},
                {"action": "Integrate with participant systems", "deadline": "9 months"}
            ],
            expected_impact="Reduce settlement fails by 30-40%",
            timeframe="9-12 months"
        ))
        
        return recommendations
    
    def _create_visualizations(self, engine_result: EngineResult) -> Dict[str, Any]:
        """Create visualization data."""
        predictions_df = self._load_predictions_dataframe(engine_result.predictions_path)
        visuals: Dict[str, Any] = {}

        if predictions_df is not None and not predictions_df.empty:
            if {'timestamps', 'market_liquidity'}.issubset(predictions_df.columns):
                ts_df = predictions_df[['timestamps', 'market_liquidity']].dropna()
                if not ts_df.empty:
                    visuals['market_liquidity_timeseries'] = {
                        "type": "line",
                        "data": {
                            "timestamps": ts_df['timestamps'].tolist(),
                            "values": [float(x) for x in pd.to_numeric(ts_df['market_liquidity'], errors='coerce').fillna(0)]
                        },
                        "title": "Market Liquidity Trajectory"
                    }

            if 'funding_liquidity' in predictions_df.columns:
                funding_series = pd.to_numeric(predictions_df['funding_liquidity'], errors='coerce').dropna()
                if not funding_series.empty:
                    visuals['funding_liquidity_histogram'] = {
                        "type": "histogram",
                        "data": [float(x) for x in funding_series],
                        "bins": 20
                    }

            id_col = next((col for col in ['bank_id', 'institution', 'source'] if col in predictions_df.columns), None)
            risk_col = next((col for col in ['prediction', 'predicted', 'risk_score', 'systemic_risk'] if col in predictions_df.columns), None)
            if id_col and risk_col:
                grouped = (
                    predictions_df[[id_col, risk_col]]
                    .dropna()
                    .assign(risk=lambda df: pd.to_numeric(df[risk_col], errors='coerce'))
                    .dropna(subset=['risk'])
                    .groupby(id_col)['risk']
                    .mean()
                    .reset_index()
                )
                if not grouped.empty:
                    edges: List[Dict[str, Any]] = []
                    edge_cols = {'from_node', 'to_node', 'exposure'}
                    if edge_cols.issubset(predictions_df.columns):
                        edges = [
                            {
                                "from": str(row['from_node']),
                                "to": str(row['to_node']),
                                "exposure": float(row['exposure'])
                            }
                            for _, row in (
                                predictions_df[list(edge_cols)]
                                .dropna()
                                .assign(exposure=lambda df: pd.to_numeric(df['exposure'], errors='coerce'))
                                .dropna(subset=['exposure'])
                                .iterrows()
                            )
                        ]

                    visuals['network_nodes'] = {
                        "type": "network",
                        "nodes": [
                            {"id": str(row[id_col]), "risk": float(row['risk'])}
                            for _, row in grouped.iterrows()
                        ],
                        "edges": edges
                    }

        visuals['overall_risk_gauge'] = {
            "type": "gauge",
            "value": float(engine_result.risk_scores.overall_score),
            "label": engine_result.risk_scores.risk_level
        }

        return visuals


class ReportExporter:
    """Export reports to various formats."""
    
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
    
    def export_pdf(self, report: ComprehensiveReport) -> str:
        """Export report as PDF using ReportLab."""
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        import os

        output_path = f"{self.output_dir}/{report.job_id}/report.pdf"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        doc = SimpleDocTemplate(output_path, pagesize=letter)
        styles = getSampleStyleSheet()
        story = []

        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#1a237e'),
            spaceAfter=30,
            alignment=TA_CENTER
        )
        story.append(Paragraph("BEACON Liquidity Risk Report", title_style))
        story.append(Spacer(1, 0.3*inch))

        # Executive Summary
        story.append(Paragraph("Executive Summary", styles['Heading2']))
        summary = report.executive_summary
        summary_data = [
            ['Metric', 'Value'],
            ['Overall Risk Score', f"{summary.overall_risk_score:.1f}/100"],
            ['Risk Level', summary.risk_level.upper()],
            ['Active Alerts', str(summary.num_alerts)],
            ['Institutions Analyzed', str(summary.num_institutions)],
            ['Data Points Processed', str(summary.data_points_analyzed)],
            ['Analysis Period', summary.period],
            ['Generated', report.generated_at.strftime('%Y-%m-%d %H:%M UTC')]
        ]

        table = Table(summary_data, colWidths=[3*inch, 2.5*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a237e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(table)
        story.append(Spacer(1, 0.3*inch))

        # Key Findings
        if summary.key_findings:
            story.append(Paragraph("Key Findings", styles['Heading2']))
            for finding in summary.key_findings[:5]:
                story.append(Paragraph(f"• {finding}", styles['Normal']))
                story.append(Spacer(1, 0.1*inch))

        story.append(PageBreak())

        # Recommendations
        story.append(Paragraph("Recommendations", styles['Heading2']))
        for i, rec in enumerate(report.recommendations[:10], 1):
            story.append(Paragraph(f"{i}. <b>{rec.priority.upper()}</b>: {rec.title}", styles['Normal']))
            story.append(Spacer(1, 0.15*inch))

        # Build PDF
        doc.build(story)
        return output_path
    
    def export_json(self, report: ComprehensiveReport) -> str:
        """Export report as JSON."""
        import json
        from dataclasses import asdict
        
        path = f"{self.output_dir}/{report.job_id}/report.json"
        
        # Convert dataclasses to dict
        report_dict = {
            "job_id": report.job_id,
            "generated_at": report.generated_at.isoformat(),
            "version": report.version,
            "executive_summary": asdict(report.executive_summary),
            "recommendations": [asdict(r) for r in report.recommendations]
        }
        
        with open(path, 'w') as f:
            json.dump(report_dict, f, indent=2, default=str)
        
        return path
    
    def export_excel(self, report: ComprehensiveReport) -> str:
        """Export report as Excel with multiple sheets."""
        import pandas as pd
        import os
        from datetime import datetime, timezone

        output_path = f"{self.output_dir}/{report.job_id}/report.xlsx"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            # Executive Summary Sheet
            summary = report.executive_summary
            summary_df = pd.DataFrame({
                'Metric': [
                    'Overall Risk Score',
                    'Risk Level',
                    'Active Alerts',
                    'Institutions Analyzed',
                    'Data Points Processed',
                    'Analysis Period',
                    'Generated At'
                ],
                'Value': [
                    f"{summary.overall_risk_score:.2f}",
                    summary.risk_level,
                    summary.num_alerts,
                    summary.num_institutions,
                    summary.data_points_analyzed,
                    summary.period,
                    report.generated_at.strftime('%Y-%m-%d %H:%M UTC')
                ]
            })
            summary_df.to_excel(writer, sheet_name='Executive Summary', index=False)

            # Key Findings Sheet
            if summary.key_findings:
                findings_df = pd.DataFrame({
                    'Finding': summary.key_findings
                })
                findings_df.to_excel(writer, sheet_name='Key Findings', index=False)

            # Recommendations Sheet
            recs_df = pd.DataFrame([
                {
                    'Priority': rec.priority,
                    'Category': rec.category,
                    'Title': rec.title,
                    'Rationale': rec.rationale,
                    'Impact': rec.expected_impact
                }
                for rec in report.recommendations
            ])
            recs_df.to_excel(writer, sheet_name='Recommendations', index=False)

            # Metadata Sheet
            metadata_df = pd.DataFrame({
                'Property': ['Job ID', 'Version', 'Generated At'],
                'Value': [report.job_id, report.version, report.generated_at.isoformat()]
            })
            metadata_df.to_excel(writer, sheet_name='Metadata', index=False)

        return output_path
