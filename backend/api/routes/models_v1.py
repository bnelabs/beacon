"""API routes for trained model catalogue."""

from __future__ import annotations

import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models.job import Job
from schemas.models_v1 import ModelSummary, ModelDetail, ModelMetrics
from services.error_logger import ErrorLogger

router = APIRouter()


def _extract_metrics(job: Job) -> ModelMetrics:
    result = job.result or {}
    return ModelMetrics(
        mae=result.get("test_mae") or result.get("mae"),
        rmse=result.get("test_rmse") or result.get("rmse"),
        r2=result.get("test_r2") or result.get("r2"),
        accuracy=result.get("accuracy"),
        best_val_loss=result.get("best_val_loss"),
    )


def _model_tags(job: Job) -> List[str]:
    result = job.result or {}
    tags = []
    if model_type := result.get("model_type"):
        tags.append(model_type.lower())
    if result.get("multi_scale"):
        tags.append("multi-scale")
    if result.get("device"):
        tags.append(result["device"])
    return tags


@router.get("", response_model=List[ModelSummary])
@router.get("/", response_model=List[ModelSummary])
async def list_models(db: Session = Depends(get_db)):
    """List completed training jobs that can serve as models."""
    try:
        jobs = (
            db.query(Job)
            .filter(Job.job_type == "training", Job.status == "completed", Job.result.isnot(None))
            .order_by(Job.completed_at.desc())
            .all()
        )

        summaries = []
        for job in jobs:
            result = job.result or {}
            summaries.append(
                ModelSummary(
                    model_id=job.id,
                    name=result.get("model_type", "Unknown Model").upper(),
                    created_at=job.created_at,
                    status=job.status,
                    model_type=result.get("model_type"),
                    model_version=result.get("model_version"),
                    metrics=_extract_metrics(job),
                    tags=_model_tags(job),
                    data_job_id=result.get("data_source_job"),
                    predictions_available=bool(result.get("predictions_path")),
                )
            )
        return summaries

    except Exception as exc:
        error_logger = ErrorLogger(db)
        error = error_logger.log_error(
            exc,
            context="listing models",
            endpoint="/api/v1/models",
            method="GET",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error.technical_message, "user_friendly": error.user_message},
        )


@router.get("/{model_id}", response_model=ModelDetail)
async def get_model(model_id: int, db: Session = Depends(get_db)):
    """Retrieve details for a specific trained model."""
    try:
        job = db.query(Job).filter(Job.id == model_id, Job.job_type == "training").first()
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"technical": f"Model job {model_id} not found", "user_friendly": "Model not found."},
            )

        if not job.result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"technical": f"Model job {model_id} has no result", "user_friendly": "Model results unavailable."},
            )

        result = job.result or {}
        predictions_path = result.get("predictions_path")
        visualizations = {}
        if predictions_path and os.path.exists(predictions_path.replace(".parquet", "_visualizations.json")):
            visuals_file = predictions_path.replace(".parquet", "_visualizations.json")
            try:
                import json

                with open(visuals_file, "r") as handle:
                    visualizations = json.load(handle)
            except Exception:
                visualizations = {}

        detail = ModelDetail(
            model_id=job.id,
            created_at=job.created_at,
            completed_at=job.completed_at,
            status=job.status,
            parameters=result.get("config", {}),
            metrics=result,
            result=result,
            data_job_id=result.get("data_source_job"),
            predictions_path=predictions_path,
            visualizations=visualizations,
        )
        return detail

    except HTTPException:
        raise
    except Exception as exc:
        error_logger = ErrorLogger(db)
        error = error_logger.log_error(
            exc,
            context="getting model detail",
            endpoint=f"/api/v1/models/{model_id}",
            method="GET",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error.technical_message, "user_friendly": error.user_message},
        )

