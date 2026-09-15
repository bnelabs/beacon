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

from backend.modules.engine.orchestrator import EngineResult, RiskScores

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
    
    risk_score: Optional[float]
    risk_level: Optional[str]
    score_units: str
    systemic_importance: Optional[float]
    
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
    
    model_score_report: Dict[str, Any]
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
            market_liq = self._generate_model_score_report(engine_result)
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
                model_score_report=market_liq,
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
        market_liq = risk_scores.model_score
        funding_liq = {}  # no funding-specific measurement exists
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

        # Only measured channels appear as factors. A channel with no
        # measurement behind it (funding liquidity has none today; systemic
        # needs a liability network) is listed as absent rather than rendered
        # as a NaN or a zero score -- an unmeasured channel dressed as a
        # factor is exactly the fabrication this report exists to avoid.
        top_risk_factors = []
        for name, score, channel in (
            ("Market Liquidity Stress", market_overall, market_liq),
            ("Funding Pressure", funding_overall, funding_liq),
            ("Network Contagion Risk", systemic_overall, systemic),
        ):
            if np.isfinite(score):
                top_risk_factors.append({
                    "factor": name,
                    "score": score,
                    "trend": self._safe_float(channel.get('trend', 0.0)),
                })
            else:
                top_risk_factors.append({
                    "factor": name,
                    "score": None,
                    "trend": None,
                    "status": "not_measured",
                })

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
        """Per-entity profiles carrying only what was measured.

        Round seven rewrite: the previous version synthesised per-channel
        means (market/funding) from a single model score and thresholded them
        into vulnerabilities, strengths and recommendations -- narrative
        manufactured from one number. Profiles now carry the entity's model
        score in its own units, the level band the analyzer assigned when one
        exists, and empty (not invented) qualitative lists.
        """
        predictions_df = self._load_predictions_dataframe(engine_result.predictions_path)
        profiles: List[InstitutionalProfile] = []

        semantics = getattr(engine_result.risk_scores, "score_semantics", {}) or {}
        units = str(semantics.get("units", "standardized one-step-ahead indicator prediction"))

        if predictions_df is not None and not predictions_df.empty:
            entity_col = next(
                (c for c in ('bank_id', 'institution_id', 'institution', 'source') if c in predictions_df.columns),
                None,
            )
            score_col = next(
                (c for c in ('risk_score', 'prediction', 'predicted') if c in predictions_df.columns),
                None,
            )
            if entity_col and score_col:
                for _, row in predictions_df.iterrows():
                    score = pd.to_numeric(row.get(score_col), errors='coerce')
                    level = row.get('risk_level') if 'risk_level' in predictions_df.columns else None
                    profiles.append(
                        InstitutionalProfile(
                            institution_id=str(row[entity_col]),
                            name=str(row.get('bank_name', row[entity_col])),
                            risk_score=None if pd.isna(score) else float(score),
                            risk_level=None if level is None or (isinstance(level, float) and pd.isna(level)) else str(level),
                            score_units=units,
                            systemic_importance=(
                                float(row['systemic_importance'])
                                if 'systemic_importance' in predictions_df.columns
                                and not pd.isna(pd.to_numeric(row['systemic_importance'], errors='coerce'))
                                else None
                            ),
                            vulnerabilities=[],
                            strengths=[],
                            recommendations=[],
                        )
                    )

        if not profiles:
            overall = self._safe_float(engine_result.risk_scores.model_score.get('overall'))
            profiles.append(
                InstitutionalProfile(
                    institution_id="portfolio",
                    name="Aggregate (no per-entity payload)",
                    risk_score=None if not np.isfinite(overall) else overall,
                    risk_level=engine_result.risk_scores.risk_level,
                    score_units=units,
                    systemic_importance=None,
                    vulnerabilities=[],
                    strengths=[],
                    recommendations=[],
                )
            )
        return profiles

    def _generate_model_score_report(self, engine_result: EngineResult) -> Dict[str, Any]:
        """Report the model's own scores, in their own units, with semantics.

        Renamed from "market liquidity" in round seven: the engine emits one
        standardized one-step-ahead score per source, and calling it a market
        liquidity channel misdescribed both the model and the channel.
        """
        metrics = engine_result.risk_scores.model_score
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
            for candidate in ['prediction', 'predicted', 'risk_score']:
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
        """Funding liquidity is not measured by this platform.

        The previous version synthesised the channel from the model score via
        a 0.95 multiplier (round-one finding) and later returned an empty
        dict that reporters rendered as NaN factors. The honest report is an
        explicit not-measured status: absence, visible as absence.
        """
        return {
            "status": "not_measured",
            "reason": (
                "no funding-specific measurement exists in the platform; the "
                "model emits one standardized liquidity-stress score per source"
            ),
            "overall_score": None,
            "current_score": None,
            "trend": None,
            "data_points": 0,
            "recent_observations": [],
        }

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
                    # Un-readable entries are dropped, not zeroed. The previous
                    # `.fillna(0)` turned "this value could not be read" into "market
                    # liquidity was exactly zero", which on a liquidity chart reads as a
                    # total seizure -- the most alarming possible reading, invented from a
                    # parsing failure. Both lists are filtered by the same mask so the
                    # timestamps and the values cannot drift out of alignment.
                    liquidity = pd.to_numeric(ts_df['market_liquidity'], errors='coerce')
                    readable = liquidity.notna()
                    if readable.any():
                        visuals['market_liquidity_timeseries'] = {
                            "type": "line",
                            "data": {
                                "timestamps": ts_df.loc[readable, 'timestamps'].tolist(),
                                "values": [float(x) for x in liquidity[readable]]
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
        import os

        output_path = f"{self.output_dir}/{report.job_id}/report.pdf"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.platypus import (
                SimpleDocTemplate,
                Paragraph,
                Spacer,
                Table,
                TableStyle,
                PageBreak,
            )
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_CENTER

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

        except Exception as exc:  # pragma: no cover - optional dependency
            logger.warning(
                "[%s] ReportLab unavailable for PDF export: %s. Writing textual fallback.",
                report.job_id,
                exc,
            )
            summary = report.executive_summary
            fallback_content = (
                "BEACON Liquidity Risk Report\n"
                f"Overall Risk Score: {summary.overall_risk_score:.1f}/100\n"
                f"Risk Level: {summary.risk_level}\n"
                f"Generated: {report.generated_at.isoformat()}\n"
            )
            with open(output_path, "w", encoding="utf-8") as handle:
                handle.write(fallback_content)
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
        import os

        output_path = f"{self.output_dir}/{report.job_id}/report.xlsx"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        try:
            import pandas as pd

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

        except Exception as exc:  # pragma: no cover - optional dependency
            logger.warning(
                "[%s] Excel export unavailable: %s. Writing CSV fallback with .xlsx extension.",
                report.job_id,
                exc,
            )
            summary = report.executive_summary
            fallback_lines = [
                "Metric,Value",
                f"Overall Risk Score,{summary.overall_risk_score:.2f}",
                f"Risk Level,{summary.risk_level}",
                f"Generated,{report.generated_at.isoformat()}",
            ]
            with open(output_path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(fallback_lines))
            return output_path
