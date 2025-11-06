"""API routes for results and reports."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import logging
import os
import json
from pathlib import Path

from backend.database import get_db
from backend.models.job import Job
from backend.modules.results.generator import ResultsGenerator

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
async def list_results(
    job_type: Optional[str] = Query(None, description="Filter by job type"),
    status: Optional[str] = Query("completed", description="Filter by status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    List all available results/reports.

    Returns jobs that have completed successfully and have results.
    """
    query = db.query(Job).filter(Job.status == status)

    if job_type:
        query = query.filter(Job.job_type == job_type)

    # Only return jobs with results
    jobs = query.filter(Job.result.isnot(None)).order_by(Job.completed_at.desc()).offset(offset).limit(limit).all()

    return {
        "total": query.count(),
        "results": [
            {
                "job_id": job.id,
                "job_type": job.job_type,
                "status": job.status,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "execution_time_seconds": job.execution_time_seconds,
                "result_summary": job.result,
                "has_report": _check_report_exists(job.id)
            }
            for job in jobs
        ]
    }


@router.get("/{job_id}")
async def get_result(
    job_id: int,
    db: Session = Depends(get_db)
):
    """
    Get complete result details for a specific job.

    Returns the job result along with any generated reports.
    """
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "completed":
        raise HTTPException(status_code=400, detail=f"Job is not completed (status: {job.status})")

    # Check if comprehensive report exists
    report_path = f"/app/results/job_{job_id}_report.json"
    report_data = None

    if os.path.exists(report_path):
        try:
            with open(report_path, 'r') as f:
                report_data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load report for job {job_id}: {e}")

    return {
        "job_id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "parameters": job.parameters,
        "result": job.result,
        "report": report_data,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "execution_time_seconds": job.execution_time_seconds,
        "peak_memory_mb": job.peak_memory_mb
    }


@router.get("/{job_id}/executive-summary")
async def get_executive_summary(
    job_id: int,
    db: Session = Depends(get_db)
):
    """Get executive summary for a completed job."""
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job not completed")

    # Try to load report
    report_path = f"/app/results/job_{job_id}_report.json"

    if not os.path.exists(report_path):
        # Generate summary from job result
        return _generate_summary_from_result(job)

    try:
        with open(report_path, 'r') as f:
            report_data = json.load(f)
            return report_data.get("executive_summary", _generate_summary_from_result(job))
    except Exception as e:
        logger.error(f"Failed to load report: {e}")
        return _generate_summary_from_result(job)


@router.get("/{job_id}/visualizations")
async def get_visualizations(
    job_id: int,
    db: Session = Depends(get_db)
):
    """Get available visualizations for a job."""
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check for visualization files
    viz_dir = f"/app/results/job_{job_id}/visualizations"
    visualizations = []

    if os.path.exists(viz_dir):
        for file in Path(viz_dir).glob("*.png"):
            visualizations.append({
                "name": file.stem,
                "path": str(file),
                "type": "image/png"
            })
        for file in Path(viz_dir).glob("*.json"):
            visualizations.append({
                "name": file.stem,
                "path": str(file),
                "type": "application/json"
            })

    return {
        "job_id": job_id,
        "visualizations": visualizations
    }


@router.get("/{job_id}/data-quality")
async def get_data_quality(
    job_id: int,
    db: Session = Depends(get_db)
):
    """Get data quality report for a data collection job."""
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.job_type != "data_collection":
        raise HTTPException(status_code=400, detail="Data quality only available for data collection jobs")

    result = job.result or {}

    return {
        "job_id": job_id,
        "quality_score": result.get("quality_score", 0),
        "completeness": result.get("completeness", 0),
        "fit_for_engine": result.get("fit_for_engine", False),
        "anomalies_detected": result.get("anomalies_detected", 0),
        "anomalies_fixed": result.get("anomalies_fixed", 0),
        "warnings": result.get("warnings", []),
        "errors": result.get("errors", [])
    }


@router.get("/{job_id}/risk-scores")
async def get_risk_scores(
    job_id: int,
    db: Session = Depends(get_db)
):
    """Get risk scores for a completed prediction/backtest job."""
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.job_type not in ["prediction", "backtest", "training"]:
        raise HTTPException(status_code=400, detail="Risk scores only available for prediction/backtest/training jobs")

    result = job.result or {}

    # Extract risk scores from result
    risk_scores = {
        "overall_risk_score": result.get("overall_risk_score", 0),
        "market_liquidity": result.get("market_liquidity_score", 0),
        "funding_liquidity": result.get("funding_liquidity_score", 0),
        "systemic_risk": result.get("systemic_risk_score", 0),
        "risk_level": result.get("risk_level", "unknown")
    }

    return {
        "job_id": job_id,
        "risk_scores": risk_scores,
        "timestamp": job.completed_at.isoformat() if job.completed_at else None
    }


@router.delete("/{job_id}")
async def delete_result(
    job_id: int,
    db: Session = Depends(get_db)
):
    """Delete result data for a specific job (keeps job record)."""
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Clear result data but keep job record
    job.result = None
    db.commit()

    # Delete associated files
    result_dir = f"/app/results/job_{job_id}"
    if os.path.exists(result_dir):
        import shutil
        try:
            shutil.rmtree(result_dir)
            logger.info(f"Deleted result files for job {job_id}")
        except Exception as e:
            logger.error(f"Failed to delete result files: {e}")

    return {
        "message": f"Result data deleted for job {job_id}",
        "job_id": job_id
    }


# Helper functions

def _check_report_exists(job_id: int) -> bool:
    """Check if a comprehensive report exists for a job."""
    report_path = f"/app/results/job_{job_id}_report.json"
    return os.path.exists(report_path)


def _generate_summary_from_result(job: Job) -> dict:
    """Generate a simple summary from job result when full report doesn't exist."""
    result = job.result or {}

    if job.job_type == "data_collection":
        return {
            "title": "Data Collection Summary",
            "job_id": job.id,
            "status": "completed",
            "quality_score": result.get("quality_score", 0),
            "completeness": result.get("completeness", 0),
            "key_metrics": {
                "fit_for_engine": result.get("fit_for_engine", False),
                "anomalies_detected": result.get("anomalies_detected", 0)
            }
        }
    elif job.job_type == "training":
        return {
            "title": "Model Training Summary",
            "job_id": job.id,
            "status": job.status,
            "message": result.get("message", "Training completed")
        }
    elif job.job_type == "prediction":
        return {
            "title": "Prediction Summary",
            "job_id": job.id,
            "status": job.status,
            "message": result.get("message", "Predictions generated")
        }
    elif job.job_type == "backtest":
        return {
            "title": "Backtest Summary",
            "job_id": job.id,
            "status": job.status,
            "windows": result.get("num_windows", 0),
            "metrics": {
                "mse": result.get("avg_mse"),
                "mae": result.get("avg_mae")
            }
        }
    else:
        return {
            "title": "Job Summary",
            "job_id": job.id,
            "status": job.status,
            "result": result
        }
