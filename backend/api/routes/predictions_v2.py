"""Prediction and backtest exploration endpoints."""

from __future__ import annotations

import os
from datetime import datetime
from typing import List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.job import Job
from backend.schemas.predictions_v2 import PredictionReport, PredictionNode, PredictionTimeline, BacktestReport
from backend.services.error_logger import ErrorLogger

router = APIRouter()

# Metrics that are meaningful for a risk state. The portfolio statistics that
# used to be listed here (Sharpe, Sortino, max drawdown, Calmar, volatility,
# VaR/CVaR) were removed: they describe returns on a priced asset, and a risk
# score is a latent state, not a price.
_QUANT_METRIC_KEYS = (
    "directional_accuracy",
    "hit_rate",
    "mse",
    "mae",
    "rmse",
    "r2",
)


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
        # The score is risk_score, or the prediction when no risk score was
        # recorded. A refused row carries NaN in both, and NaN is not a
        # number: it travels as null. The old fallback chain ended in "any
        # numeric column, scanned backwards" -- which on a row with uncertainty
        # columns would have served epistemic variance as if it were a risk
        # score. Absence is reported as absence.
        risk_value = None
        for candidate in ("risk_score", "prediction"):
            if candidate in row and pd.notna(row[candidate]):
                risk_value = row[candidate]
                break

        node = PredictionNode(
            source=str(row["source"]),
            risk=float(risk_value) if risk_value is not None else None,
            confidence_lower=float(row.get("confidence_lower", 0.0)) if pd.notna(row.get("confidence_lower")) else None,
            confidence_upper=float(row.get("confidence_upper", 0.0)) if pd.notna(row.get("confidence_upper")) else None,
            additional={
                key: row[key]
                for key in [
                    "bank_id", "bank_name", "risk_level", "overall_risk",
                    # Why a score is absent (or what it carries): the refusal
                    # state and the decomposition travel with the node.
                    "confidence_method", "uncertainty_status",
                    "uncertainty_reasons", "aleatoric_var", "epistemic_var",
                    "epistemic_share",
                ]
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


@router.get("/reports/validation/{job_id}")
async def get_validation_report(job_id: int, db: Session = Depends(get_db)):
    """Predictive-validity report for a backtest job.

    Round-five wiring stores per-source event metrics (ROC AUC, average
    precision, conservative lead-time statistics against declared stress
    events) in the backtest result when the job carried an
    ``event_definition``. This endpoint surfaces them as a first-class
    report -- and says plainly when a job was never validated, because a
    missing validation is a status, not an error and not a zero.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.job_type != "backtest":
        raise HTTPException(status_code=400, detail="Validation reports exist for backtest jobs only")

    result = job.result or {}
    backtest_metrics = result.get("backtest_metrics", {}) or {}
    event_metrics = backtest_metrics.get("event_metrics")

    if not event_metrics:
        return {
            "job_id": job_id,
            "status": "not_validated",
            "reason": (
                "this backtest ran without an event_definition, so no stress "
                "events were labelled and no predictive-validity statistics "
                "exist; re-run the backtest with an event definition to "
                "measure precision, recall and lead time"
            ),
            "validation": None,
        }

    by_source = event_metrics.get("by_source", {}) or {}
    measured = {
        name: payload for name, payload in by_source.items()
        if isinstance(payload, dict) and "roc_auc" in payload
    }
    aucs = [payload["roc_auc"] for payload in measured.values() if payload.get("roc_auc") is not None]
    return {
        "job_id": job_id,
        "status": "validated",
        "validation": {
            "definition": event_metrics.get("definition"),
            "sources_measured": len(measured),
            "sources_skipped": {
                name: payload for name, payload in by_source.items() if name not in measured
            },
            "mean_roc_auc": float(sum(aucs) / len(aucs)) if aucs else None,
            "by_source": by_source,
            "quant_metrics": {
                key: backtest_metrics.get(key)
                for key in ("mse", "mae", "rmse", "r2", "directional_accuracy", "hit_rate")
            },
        },
    }


@router.get("/reports/backtest/{job_id}", response_model=BacktestReport)
async def get_backtest_report(job_id: int, db: Session = Depends(get_db)):
    try:
        job = _load_job(db, job_id)
        if job.job_type != "backtest":
            raise HTTPException(status_code=400, detail="Job is not a backtest job")

        if job.status != "completed":
            return _progress(job)

        result = job.result or {}
        backtest_metrics = result.get("backtest_metrics", {}) or {}

        quant_metrics = result.get("quant_metrics")
        if not quant_metrics:
            quant_metrics = {
                key: backtest_metrics.get(key)
                for key in _QUANT_METRIC_KEYS
                if key in backtest_metrics
            } or None

        walk_forward = result.get("walk_forward") or backtest_metrics.get("walk_forward")

        report = BacktestReport(
            job_id=job.id,
            status=job.status,
            metrics=backtest_metrics,
            metadata={
                "train_samples": result.get("train_samples"),
                "test_samples": result.get("test_samples"),
                "completed_at": result.get("completed_at"),
                "regions": result.get("regions") or [],
                "countries": result.get("countries") or [],
            },
            quant_metrics=quant_metrics,
            walk_forward=walk_forward,
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
