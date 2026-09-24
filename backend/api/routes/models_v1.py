"""API routes for trained model catalogue."""

from __future__ import annotations

import os
from typing import List

from datetime import datetime, timezone
from pathlib import Path

import json
import math
import pandas as pd

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.job import Job
from backend.schemas.models_v1 import (
    ModelSummary,
    ModelDetail,
    ModelMetrics,
    ScenarioAdjustment,
    ScenarioRequest,
    ScenarioResponse,
)
from backend.services.error_logger import ErrorLogger
from backend.modules.data.quality_gate import DataQualityGate
from backend.services.scenario_service import (
    _apply_adjustments,  # re-exported: existing tests import helpers from this module
    _load_timeseries,
    _run_network_clearing,
    execute_scenario,
    ScenarioError,
)

# torch and RealPredictionEngine are imported lazily inside
# ``scenario_service.execute_scenario`` (the only path in this router that
# runs inference). This router is imported by ``backend.api.main`` at
# startup, so importing the prediction engine -- which pulls torch -- at
# module scope would load the heavy ML runtime into the base API container
# just to serve the model *catalogue* (list/detail/scenario reads that never
# touch a model). Deferring it keeps those reads cheap and confines the
# torch footprint to the inference path.

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



@router.post("/{model_id}/simulate", response_model=ScenarioResponse)
async def simulate_model(
    model_id: int,
    scenario: ScenarioRequest,
    db: Session = Depends(get_db),
):
    try:
        return execute_scenario(db, model_id, scenario)
    except ScenarioError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    except HTTPException:
        raise
    except Exception as exc:
        error_logger = ErrorLogger(db)
        error = error_logger.log_error(
            exc,
            context="simulate model",
            endpoint=f"/api/models/{model_id}/simulate",
            method="POST",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error.technical_message, "user_friendly": error.user_message},
        )


@router.get("/{model_id}/scenarios/{scenario_id}", response_model=ScenarioResponse)
async def get_scenario(
    model_id: int,
    scenario_id: str,
    db: Session = Depends(get_db),
):
    try:
        scenario_dir = Path("/app/results/scenarios") / str(model_id) / scenario_id
        predictions_path = scenario_dir / "predictions.json"
        if not predictions_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "technical": f"Scenario {scenario_id} not found",
                    "user_friendly": "Scenario results are not available."
                },
            )

        predictions_df = pd.read_json(predictions_path)

        meta_path = scenario_dir / "meta.json"
        meta = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())

        raw_feature_importances = meta.get("feature_importances") or {}
        feature_importances: dict[str, float] = {}
        for key, value in raw_feature_importances.items():
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                continue
            if math.isnan(numeric_value):
                continue
            feature_importances[str(key)] = numeric_value

        summary = {
            "avg_risk_score": float(predictions_df["risk_score"].mean()) if not predictions_df.empty else 0.0,
            "max_risk_score": float(predictions_df["risk_score"].max()) if not predictions_df.empty else 0.0,
            "min_risk_score": float(predictions_df["risk_score"].min()) if not predictions_df.empty else 0.0,
            "num_series": int(predictions_df.shape[0]),
        }

        predictions = []
        for record in predictions_df.to_dict(orient="records"):
            predictions.append(
                {
                    "source": record.get("source"),
                    "prediction": record.get("prediction"),
                    "risk_score": record.get("risk_score"),
                    "confidence_lower": record.get("confidence_lower"),
                    "confidence_upper": record.get("confidence_upper"),
                    "explanation": record.get("explanation"),
                }
            )

        adjustments_payload = meta.get("adjustments", [])
        adjustments = [ScenarioAdjustment(**adj) for adj in adjustments_payload if isinstance(adj, dict)]

        created_at_str = meta.get("created_at")
        created_at = datetime.fromisoformat(created_at_str) if created_at_str else datetime.now(timezone.utc)

        response = ScenarioResponse(
            scenario_id=scenario_id,
            model_id=model_id,
            name=meta.get("name") or f"Scenario {scenario_id[:8]}",
            horizon_days=int(meta.get("horizon_days") or 30),
            created_at=created_at,
            summary=summary,
            predictions=predictions,
            adjustments=adjustments,
            executive_summary=meta.get("executive_summary"),
            feature_importances=feature_importances,
            storage_path=str(predictions_path),
        )
        return response

    except HTTPException:
        raise
    except Exception as exc:
        error_logger = ErrorLogger(db)
        error = error_logger.log_error(
            exc,
            context="get scenario",
            endpoint=f"/api/models/{model_id}/scenarios/{scenario_id}",
            method="GET",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error.technical_message, "user_friendly": error.user_message},
        )
