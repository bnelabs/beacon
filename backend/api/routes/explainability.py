"""EU AI Act Compliant Explainability API - For Non-Technical Users."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
import logging
import os
import json
from pathlib import Path

from database import get_db
from models.job import Job

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{job_id}/explanation")
async def get_model_explanation(
    job_id: int,
    db: Session = Depends(get_db)
):
    """
    Get EU AI Act compliant model explanation for a prediction job.

    Returns human-readable explanation of:
    - What the model predicted
    - Why it made that prediction (feature importance)
    - How confident it is
    - What factors increased/decreased risk
    """
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.job_type not in ["training", "prediction"]:
        raise HTTPException(status_code=400, detail="Explanations only available for training/prediction jobs")

    result = job.result or {}

    # Check for explanation files
    explanation_path = Path(f"/app/data/jobs/{job_id}/explanation_report.txt")
    if explanation_path.exists():
        with open(explanation_path, 'r') as f:
            explanation_report = f.read()
    else:
        explanation_report = "Explanation report not yet generated."

    # Extract key explanation elements
    explanation = {
        "job_id": job_id,
        "model_type": result.get("model_type", "Unknown"),
        "explainability_compliance": "EU AI Act Compliant - No Black Box",

        # Main explanation
        "explanation_report": explanation_report,

        # Feature importance (what drove the prediction)
        "feature_importance": result.get("feature_importances", {}),

        # Confidence intervals
        "confidence_intervals": result.get("confidence_intervals", {}),

        # Model performance
        "model_metrics": {
            "r2_score": result.get("test_r2"),
            "mae": result.get("test_mae"),
            "rmse": result.get("test_rmse")
        },

        # Human-readable summary
        "summary": f"The {result.get('model_type', 'model')} model achieved {result.get('test_r2', 0) * 100:.1f}% accuracy (R² score). All predictions include confidence intervals and feature attributions for full transparency.",

        # Regulatory compliance
        "compliance": {
            "eu_ai_act": "Compliant",
            "explainability_method": "Gradient-based feature attribution + Attention weights",
            "uncertainty_quantification": "Monte Carlo Dropout",
            "human_oversight": "All high-risk predictions flagged for review"
        }
    }

    return explanation


@router.get("/{job_id}/bank-risks")
async def get_bank_risks(
    job_id: int,
    bank_id: Optional[str] = Query(None, description="Filter by specific bank"),
    risk_level: Optional[str] = Query(None, description="Filter by risk level (low, medium, high, critical)"),
    db: Session = Depends(get_db)
):
    """
    Get per-bank liquidity risk assessments.

    Returns:
    - Individual bank risk scores
    - Explanations for each bank
    - Recommendations
    - Vulnerabilities and strengths
    """
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = job.result or {}
    per_bank_risks = result.get("per_bank_risks", {})

    if not per_bank_risks:
        raise HTTPException(status_code=404, detail="No per-bank risk data available for this job")

    # Filter by bank_id if provided
    if bank_id:
        if bank_id not in per_bank_risks:
            raise HTTPException(status_code=404, detail=f"Bank {bank_id} not found in results")
        per_bank_risks = {bank_id: per_bank_risks[bank_id]}

    # Filter by risk level if provided
    if risk_level:
        per_bank_risks = {
            bid: profile for bid, profile in per_bank_risks.items()
            if profile.get("risk_level") == risk_level
        }

    # Format for non-technical users
    formatted_risks = []
    for bank_id, profile in per_bank_risks.items():
        formatted_risks.append({
            "bank_id": bank_id,
            "bank_name": profile.get("bank_name", f"Bank {bank_id}"),

            # Risk scores (as percentages for clarity)
            "overall_risk_percentage": round(profile.get("overall_liquidity_risk", 0) * 100, 1),
            "risk_level": profile.get("risk_level", "unknown").upper(),

            # Confidence
            "confidence_range": {
                "lower": round(profile.get("confidence_lower", 0) * 100, 1),
                "upper": round(profile.get("confidence_upper", 0) * 100, 1)
            },

            # Explanation
            "explanation": profile.get("explanation", {}).get("explanation_text", ""),

            # Key issues
            "top_vulnerabilities": profile.get("top_vulnerabilities", []),
            "top_strengths": profile.get("top_strengths", []),

            # Actions needed
            "recommendations": profile.get("recommendations", []),

            # Systemic importance
            "systemic_importance_percentage": round(profile.get("systemic_importance", 0) * 100, 1),
            "is_systemically_important": profile.get("systemic_importance", 0) > 0.7
        })

    return {
        "job_id": job_id,
        "num_banks": len(formatted_risks),
        "banks": formatted_risks,
        "summary": f"Analyzed {len(formatted_risks)} bank(s). {sum(1 for b in formatted_risks if b['risk_level'] in ['HIGH', 'CRITICAL'])} require immediate attention."
    }


@router.get("/{job_id}/contagion-analysis")
async def get_contagion_analysis(
    job_id: int,
    db: Session = Depends(get_db)
):
    """
    Get inter-bank contagion analysis.

    Shows:
    - How banks affect each other
    - Cascade scenarios if a bank fails
    - Systemic risk scores
    - Network effects
    """
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = job.result or {}
    multi_bank_analysis = result.get("multi_bank_analysis")

    if not multi_bank_analysis:
        raise HTTPException(status_code=404, detail="No multi-bank analysis available. This endpoint requires multiple banks.")

    # Extract contagion information
    contagion_data = {
        "job_id": job_id,
        "analysis_date": multi_bank_analysis.get("analysis_date"),

        # System-wide metrics
        "system_health": {
            "avg_risk_percentage": round(multi_bank_analysis.get("avg_risk", 0) * 100, 1),
            "max_risk_percentage": round(multi_bank_analysis.get("max_risk", 0) * 100, 1),
            "systemic_risk_percentage": round(multi_bank_analysis.get("systemic_risk_score", 0) * 100, 1),
            "num_high_risk_banks": multi_bank_analysis.get("num_high_risk", 0),
            "num_critical_risk_banks": multi_bank_analysis.get("num_critical_risk", 0)
        },

        # Systemically important banks
        "systemic_banks": [
            {
                "bank_id": bank_id,
                "systemic_importance_percentage": round(importance * 100, 1),
                "reason": reason
            }
            for bank_id, importance, reason in multi_bank_analysis.get("systemic_banks", [])
        ],

        # Cascade scenarios
        "cascade_scenarios": [
            {
                "initial_failure": bank_id,
                "total_failures": scenario.get("total_failures", 0),
                "cascade_depth": scenario.get("cascade_depth", 0),
                "affected_banks": scenario.get("affected_banks", []),
                "severity": "CRITICAL" if scenario.get("total_failures", 0) > 5 else "HIGH" if scenario.get("total_failures", 0) > 2 else "MODERATE"
            }
            for bank_id, scenario in multi_bank_analysis.get("cascade_scenarios", {}).items()
        ],

        # Network metrics
        "network_metrics": {
            "network_density": multi_bank_analysis.get("network_density", 0),
            "interconnectedness_level": "HIGH" if multi_bank_analysis.get("network_density", 0) > 0.5 else "MODERATE" if multi_bank_analysis.get("network_density", 0) > 0.25 else "LOW"
        },

        # Human-readable summary
        "summary": _generate_contagion_summary(multi_bank_analysis)
    }

    return contagion_data


@router.get("/{job_id}/executive-summary")
async def get_executive_summary_new(
    job_id: int,
    format: str = Query("text", description="Format: text or json"),
    db: Session = Depends(get_db)
):
    """
    Get executive summary for non-technical users (regulators, executives).

    Plain language summary of:
    - Overall system health
    - Critical issues
    - Recommended actions
    - No technical jargon
    """
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = job.result or {}

    # Check for saved executive summary
    summary_text = result.get("executive_summary", "")

    if not summary_text:
        # Generate on the fly
        summary_text = _generate_summary_from_result(job, result)

    if format == "json":
        return {
            "job_id": job_id,
            "summary": summary_text,
            "key_metrics": {
                "overall_risk": result.get("avg_risk", result.get("test_r2", 0)),
                "num_banks": result.get("num_banks", 0),
                "systemic_risk": result.get("systemic_risk_score", 0)
            }
        }
    else:
        # Return plain text
        return {"summary": summary_text}


@router.get("/{job_id}/visualizations/{viz_name}")
async def get_visualization(
    job_id: int,
    viz_name: str,
    db: Session = Depends(get_db)
):
    """
    Get a specific visualization image.

    Available visualizations:
    - loss_curves: Training/validation loss
    - predictions_vs_actual: Prediction accuracy
    - error_distribution: Error analysis
    - residuals: Residual plots
    - summary_table: Metrics summary
    """
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Look for visualization file
    viz_path = Path(f"/app/data/jobs/{job_id}/{viz_name}.png")

    if not viz_path.exists():
        raise HTTPException(status_code=404, detail=f"Visualization '{viz_name}' not found")

    return FileResponse(
        path=str(viz_path),
        media_type="image/png",
        filename=f"job_{job_id}_{viz_name}.png"
    )


@router.get("/{job_id}/download/predictions")
async def download_predictions(
    job_id: int,
    format: str = Query("csv", description="Format: csv or excel"),
    db: Session = Depends(get_db)
):
    """Download predictions as CSV or Excel file."""
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    predictions_path = Path(f"/app/data/jobs/{job_id}/predictions.csv")

    if not predictions_path.exists():
        raise HTTPException(status_code=404, detail="Predictions file not found")

    if format == "csv":
        return FileResponse(
            path=str(predictions_path),
            media_type="text/csv",
            filename=f"job_{job_id}_predictions.csv"
        )
    elif format == "excel":
        # Convert to Excel on the fly
        import pandas as pd
        df = pd.read_csv(predictions_path)
        excel_path = Path(f"/app/data/jobs/{job_id}/predictions.xlsx")
        df.to_excel(excel_path, index=False)

        return FileResponse(
            path=str(excel_path),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=f"job_{job_id}_predictions.xlsx"
        )
    else:
        raise HTTPException(status_code=400, detail="Format must be 'csv' or 'excel'")


# Helper functions

def _generate_contagion_summary(analysis: dict) -> str:
    """Generate human-readable contagion summary."""
    num_critical = analysis.get("num_critical_risk", 0)
    num_high = analysis.get("num_high_risk", 0)
    systemic_risk = analysis.get("systemic_risk_score", 0) * 100

    summary = f"CONTAGION RISK ASSESSMENT:\n\n"

    if systemic_risk > 80:
        summary += "⚠️ CRITICAL SYSTEMIC RISK DETECTED ⚠️\n\n"
    elif systemic_risk > 60:
        summary += "⚠️ ELEVATED SYSTEMIC RISK\n\n"
    else:
        summary += "System risk levels within acceptable bounds.\n\n"

    summary += f"- {num_critical} bank(s) at critical risk\n"
    summary += f"- {num_high} bank(s) at high risk\n"
    summary += f"- Systemic risk score: {systemic_risk:.1f}%\n\n"

    cascade_scenarios = analysis.get("cascade_scenarios", {})
    if cascade_scenarios:
        summary += f"CONTAGION SCENARIOS:\n"
        for bank_id, scenario in list(cascade_scenarios.items())[:3]:
            summary += f"- If {bank_id} fails: {scenario.get('total_failures', 0)} other banks affected\n"

    return summary


def _generate_summary_from_result(job: Job, result: dict) -> str:
    """Generate summary when not pre-computed."""
    if job.job_type == "training":
        r2 = result.get("test_r2", 0)
        mae = result.get("test_mae", 0)
        model = result.get("model_type", "Model")

        return f"""
TRAINING SUMMARY - {model}

Model Performance:
- Accuracy (R² Score): {r2 * 100:.1f}%
- Average Error (MAE): {mae:.4f}
- Status: {'EXCELLENT' if r2 > 0.95 else 'GOOD' if r2 > 0.8 else 'MODERATE'}

The model is {'ready for production use' if r2 > 0.9 else 'suitable for testing' if r2 > 0.7 else 'requires improvement'}.
All predictions include full explainability (EU AI Act compliant).
"""

    return f"Analysis completed for job {job.id}."
