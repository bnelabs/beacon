"""Prediction and backtest exploration endpoints."""

from __future__ import annotations

import os
from datetime import datetime
from typing import List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from models.job import Job
from schemas.predictions_v2 import PredictionReport, PredictionNode, PredictionTimeline, BacktestReport
from services.error_logger import ErrorLogger

router = APIRouter()


def _load_job(db: Session, job_id: int) -> Job:
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"technical": f"Job {job_id} not found", "user_friendly": "Job not found."},
        )
    return job


def _progress(job: Job) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "job_id": job.id,
            "status": job.status,
            "progress": job.progress or 0.0,
            "current_step": job.current_step,
        },
    )


def _load_predictions_df(path: Optional[str]) -> Optional[pd.DataFrame]:
    if not path or not os.path.exists(path):
        return None
    try:
        return pd.read_parquet(path)
    except Exception:
        return None


def _extract_nodes(df: pd.DataFrame) -> List[PredictionNode]:
    nodes: List[PredictionNode] = []
    if "source" not in df.columns:
        return nodes

    for _, row in df.iterrows():
        risk_value = None
        if "risk_score" in row:
            risk_value = row["risk_score"]
        elif "prediction" in row:
            risk_value = row["prediction"]
        else:
            for col in row.index[::-1]:
                if isinstance(row[col], (int, float)):
                    risk_value = row[col]
                    break

        node = PredictionNode(
            source=str(row["source"]),
            risk=float(risk_value) if risk_value is not None else 0.0,
            confidence_lower=float(row.get("confidence_lower", 0.0)) if pd.notna(row.get("confidence_lower")) else None,
            confidence_upper=float(row.get("confidence_upper", 0.0)) if pd.notna(row.get("confidence_upper")) else None,
            additional={
                key: row[key]
                for key in ["bank_id", "bank_name", "risk_level", "overall_risk"]
                if key in df.columns and pd.notna(row.get(key))
            },
        )
        nodes.append(node)

    return nodes


def _build_timeline(df: pd.DataFrame) -> List[PredictionTimeline]:
    if "timestamps" not in df.columns and "date" not in df.columns:
        return []

    timeline_column = "timestamps" if "timestamps" in df.columns else "date"
    timeline: List[PredictionTimeline] = []
    for timestamp, group in df.groupby(timeline_column):
        try:
            ts = pd.to_datetime(timestamp).to_pydatetime()
        except Exception:
            ts = None
        timeline.append(PredictionTimeline(timestamp=ts, nodes=_extract_nodes(group)))
    return timeline


@router.get("/predictions/{job_id}", response_model=PredictionReport)
async def get_prediction_report(job_id: int, db: Session = Depends(get_db)):
    try:
        job = _load_job(db, job_id)
        if job.job_type != "prediction":
            raise HTTPException(status_code=400, detail="Job is not a prediction job")

        if job.status != "completed":
            return _progress(job)

        result = job.result or {}
        df = _load_predictions_df(result.get("predictions_path"))
        nodes = _extract_nodes(df) if df is not None else []
        timeline = _build_timeline(df) if df is not None else []

        report = PredictionReport(
            job_id=job.id,
            status=job.status,
            summary_metrics=result.get("metrics", {}),
            feature_importances=result.get("feature_importances", {}),
            nodes=nodes,
            timeline=timeline,
            regions=result.get("regions") or [],
            countries=result.get("countries") or [],
        )
        return report

    except HTTPException:
        raise
    except Exception as exc:
        error_logger = ErrorLogger(db)
        error = error_logger.log_error(
            exc,
            context="getting prediction report",
            endpoint=f"/api/v2/predictions/{job_id}",
            method="GET",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error.technical_message, "user_friendly": error.user_message},
        )


@router.get("/reports/backtest/{job_id}", response_model=BacktestReport)
async def get_backtest_report(job_id: int, db: Session = Depends(get_db)):
    try:
        job = _load_job(db, job_id)
        if job.job_type != "backtest":
            raise HTTPException(status_code=400, detail="Job is not a backtest job")

        if job.status != "completed":
            return _progress(job)

        result = job.result or {}
        report = BacktestReport(
            job_id=job.id,
            status=job.status,
            metrics=result.get("backtest_metrics", {}),
            metadata={
                "train_samples": result.get("train_samples"),
                "test_samples": result.get("test_samples"),
                "completed_at": result.get("completed_at"),
                "regions": result.get("regions") or [],
                "countries": result.get("countries") or [],
            },
        )
        return report

    except HTTPException:
        raise
    except Exception as exc:
        error_logger = ErrorLogger(db)
        error = error_logger.log_error(
            exc,
            context="getting backtest report",
            endpoint=f"/api/v2/reports/backtest/{job_id}",
            method="GET",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error.technical_message, "user_friendly": error.user_message},
        )
