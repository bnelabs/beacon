"""RESULTS Module Generator - Comprehensive reporting and visualization."""

import logging
from typing import Dict, List, Any
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

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
            exec_summary = self._generate_executive_summary(engine_result.risk_scores)
            
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
                generated_at=datetime.utcnow(),
                version="1.0.0"
            )
            
            logger.info(f"[{self.job_id}] Report generation completed")
            return report
            
        except Exception as e:
            logger.error(f"[{self.job_id}] Report generation failed: {e}")
            raise
    
    def _generate_executive_summary(self, risk_scores: RiskScores) -> ExecutiveSummary:
        """Generate executive summary."""
        
        critical_alerts = []
        if risk_scores.overall_score > 80:
            critical_alerts.append({
                "level": "critical",
                "message": "Systemic risk at critical levels - immediate action required"
            })
        
        top_risk_factors = [
            {"factor": "Market Liquidity Stress", "score": list(risk_scores.market_liquidity.values())[0], "trend": "increasing"},
            {"factor": "Funding Pressure", "score": list(risk_scores.funding_liquidity.values())[0], "trend": "stable"},
            {"factor": "Network Contagion Risk", "score": list(risk_scores.systemic_risk.values())[0], "trend": "increasing"}
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
            period="2024-01-01 to 2024-12-31",
            generated_at=datetime.utcnow()
        )
    
    def _generate_geographic_analysis(self, engine_result: EngineResult) -> GeographicAnalysis:
        """Generate geographic risk analysis."""
        
        regional_scores = {
            "North America": 65.0,
            "Europe": 58.0,
            "Asia": 72.0
        }
        
        cross_border_risks = [
            {"from": "Asia", "to": "Europe", "risk": 45.0, "channel": "trade_finance"},
            {"from": "North America", "to": "Asia", "risk": 38.0, "channel": "derivatives"}
        ]
        
        return GeographicAnalysis(
            regional_scores=regional_scores,
            cross_border_risks=cross_border_risks,
            contagion_paths=[],
            visualizations={}
        )
    
    def _generate_institutional_profiles(self, engine_result: EngineResult) -> List[InstitutionalProfile]:
        """Generate institution-level profiles from risk scores."""
        import numpy as np

        profiles = []

        # Extract risk metrics
        market_liq = engine_result.risk_scores.market_liquidity
        funding_liq = engine_result.risk_scores.funding_liquidity
        systemic_risk = engine_result.risk_scores.systemic_risk

        # If we have institution-specific data, create individual profiles
        # Otherwise create an aggregate profile
        market_score = market_liq.get('overall', market_liq.get('current', 50.0))
        funding_score = funding_liq.get('overall', funding_liq.get('current', 50.0))
        systemic_importance = systemic_risk.get('network_risk', systemic_risk.get('current', 50.0))

        # Generate vulnerabilities based on scores
        vulnerabilities = []
        if market_score > 70:
            vulnerabilities.append("Elevated market liquidity risk")
        if funding_score > 70:
            vulnerabilities.append("Funding liquidity pressures")
        if systemic_importance > 70:
            vulnerabilities.append("High systemic importance")

        market_volatility = market_liq.get('volatility', 0)
        if market_volatility > 15:
            vulnerabilities.append("High market volatility")

        # Generate strengths
        strengths = []
        if market_score < 40:
            strengths.append("Stable market liquidity position")
        if funding_score < 40:
            strengths.append("Strong funding liquidity")

        trend = market_liq.get('trend', 0)
        if trend < 0:
            strengths.append("Improving risk trend")

        # Generate recommendations
        recommendations = []
        if market_score > 60:
            recommendations.append("Enhance market-making capacity during stress")
        if funding_score > 60:
            recommendations.append("Diversify funding sources and extend maturities")
        if systemic_importance > 60:
            recommendations.append("Strengthen liquidity buffers beyond regulatory minimums")

        # Create aggregate institutional profile
        profile = InstitutionalProfile(
            institution_id="AGGREGATE_ANALYSIS",
            name="System-Wide Assessment",
            market_liquidity_score=float(market_score),
            funding_liquidity_score=float(funding_score),
            systemic_importance=float(systemic_importance),
            vulnerabilities=vulnerabilities if vulnerabilities else ["No significant vulnerabilities detected"],
            strengths=strengths if strengths else ["Monitoring required"],
            recommendations=recommendations if recommendations else ["Continue monitoring key metrics"]
        )

        profiles.append(profile)
        return profiles
    
    def _generate_market_liquidity_report(self, engine_result: EngineResult) -> Dict[str, Any]:
        """Generate market liquidity analysis."""
        return {
            "overall_liquidity": "moderate",
            "stressed_markets": ["corporate_bonds", "emerging_market_debt"],
            "bid_ask_spreads": {"avg": 0.25, "max": 1.2},
            "market_depth_score": 68.0
        }
    
    def _generate_funding_liquidity_report(self, engine_result: EngineResult) -> Dict[str, Any]:
        """Generate funding liquidity analysis."""
        return {
            "overnight_stress": "elevated",
            "lcr_avg": 125.0,
            "nsfr_avg": 115.0,
            "vulnerable_institutions": 12
        }
    
    def _generate_systemic_risk_report(self, engine_result: EngineResult) -> Dict[str, Any]:
        """Generate systemic risk analysis."""
        return {
            "network_centrality": {"top_nodes": ["BANK_001", "BANK_003"]},
            "contagion_probability": 0.35,
            "cascade_simulation": {"max_failures": 8, "total_exposure": 2.5e9}
        }
    
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
        
        return {
            "risk_heatmap": {
                "type": "heatmap",
                "data": [[65, 58, 72], [70, 55, 68]],
                "labels": {"x": ["North America", "Europe", "Asia"], "y": ["Market Liq", "Funding Liq"]}
            },
            "time_series": {
                "type": "line",
                "data": {"dates": ["2024-01", "2024-02"], "values": [60, 65]},
                "title": "Risk Evolution"
            },
            "network_graph": {
                "type": "network",
                "nodes": [{"id": "BANK_001", "risk": 70}, {"id": "BANK_002", "risk": 55}],
                "edges": [{"from": "BANK_001", "to": "BANK_002", "exposure": 1.5e8}]
            }
        }


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
            story.append(Paragraph(f"{i}. <b>{rec.priority.upper()}</b>: {rec.action}", styles['Normal']))
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
        from datetime import datetime

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
                    'Generated At'
                ],
                'Value': [
                    f"{summary.overall_risk_score:.2f}",
                    summary.risk_level,
                    summary.num_alerts,
                    summary.num_institutions,
                    summary.data_points_analyzed,
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
                    'Action': rec.action,
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
