"""API routes for trained model catalogue."""

from __future__ import annotations

import os
from typing import List, Optional

from uuid import uuid4
from datetime import datetime, timedelta
from pathlib import Path

import json
import math
import pandas as pd
import torch

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models.job import Job
from schemas.models_v1 import (
    ModelSummary,
    ModelDetail,
    ModelMetrics,
    ScenarioAdjustment,
    ScenarioRequest,
    ScenarioResponse,
)
from services.error_logger import ErrorLogger
from modules.engine.prediction_engine import RealPredictionEngine

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


def _load_timeseries(data_job_id: int) -> pd.DataFrame:
    path = Path(f"/app/data/jobs/{data_job_id}/timeseries.parquet")
    if not path.exists():
        raise FileNotFoundError(f"Timeseries data not found for job {data_job_id}")
    df = pd.read_parquet(path)
    return df


def _apply_adjustments(df: pd.DataFrame, adjustments: List[ScenarioAdjustment], horizon_days: int) -> pd.DataFrame:
    if not adjustments:
        return df

    scenario_df = df.copy()

    if "Date" in scenario_df.columns:
        scenario_df["Date"] = pd.to_datetime(scenario_df["Date"], errors="coerce")
        max_date = scenario_df["Date"].max()
        if pd.isna(max_date):
            date_mask = pd.Series(True, index=scenario_df.index)
        else:
            date_mask = scenario_df["Date"] >= (max_date - timedelta(days=horizon_days))
    else:
        date_mask = pd.Series(True, index=scenario_df.index)

    numeric_columns = [
        col
        for col in [
            "Open",
            "High",
            "Low",
            "Close",
            "open",
            "high",
            "low",
            "close",
            "Value",
            "value",
        ]
        if col in scenario_df.columns
    ]

    for adjustment in adjustments:
        source = adjustment.source.upper()
        source_mask = scenario_df.get("source_code", pd.Series(dtype=str)).astype(str).str.upper() == source
        mask = source_mask & date_mask

        if not mask.any():
            continue

        if adjustment.type == "pct":
            factor = 1.0 + adjustment.value / 100.0
            scenario_df.loc[mask, numeric_columns] = (
                scenario_df.loc[mask, numeric_columns] * factor
            )
        elif adjustment.type == "bps":
            delta = adjustment.value / 10000.0
            scenario_df.loc[mask, numeric_columns] = (
                scenario_df.loc[mask, numeric_columns] + delta
            )
        else:  # absolute
            scenario_df.loc[mask, numeric_columns] = (
                scenario_df.loc[mask, numeric_columns] + adjustment.value
            )

    if "Date" in scenario_df.columns:
        scenario_df["Date"] = scenario_df["Date"].dt.strftime("%Y-%m-%d")

    return scenario_df


@router.post("/{model_id}/simulate", response_model=ScenarioResponse)
async def simulate_model(
    model_id: int,
    scenario: ScenarioRequest,
    db: Session = Depends(get_db),
):
    try:
        job = db.query(Job).filter(Job.id == model_id, Job.job_type == "training").first()
        if not job or not job.result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "technical": f"Model job {model_id} not found",
                    "user_friendly": "Model not found or has no results."
                },
            )

        result = job.result or {}
        model_path = result.get("model_path") or result.get("best_model_path")
        if not model_path or not Path(model_path).exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "technical": "Model file missing",
                    "user_friendly": "Trained model artefact is not available."
                },
            )

        data_job_id = result.get("data_source_job")
        if not data_job_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "technical": "Training job missing data reference",
                    "user_friendly": "Model does not reference source data."
                },
            )

        base_df = _load_timeseries(data_job_id)
        adjusted_df = _apply_adjustments(base_df, scenario.adjustments, scenario.horizon_days)

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        engine = RealPredictionEngine(
            model_path=model_path,
            device=device,
            config=result.get("config", {}),
        )

        prediction_result = engine.predict(adjusted_df)
        predictions_df = prediction_result.predictions_df.copy()

        raw_feature_importances = prediction_result.feature_importances or {}
        feature_importances: dict[str, float] = {}
        for key, value in raw_feature_importances.items():
            if value is None:
                continue
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                continue
            if math.isnan(numeric_value):
                continue
            feature_importances[str(key)] = numeric_value

        scenario_id = str(uuid4())
        scenario_dir = Path("/app/results/scenarios") / str(model_id) / scenario_id
        scenario_dir.mkdir(parents=True, exist_ok=True)

        predictions_path = scenario_dir / "predictions.json"
        predictions_df.to_json(predictions_path, orient="records")

        meta_path = scenario_dir / "meta.json"
        timestamp = datetime.utcnow()
        meta_payload = {
            "scenario_id": scenario_id,
            "model_id": model_id,
            "name": scenario.name or f"Scenario {scenario_id[:8]}",
            "horizon_days": scenario.horizon_days,
            "created_at": timestamp.isoformat(),
            "adjustments": [adjustment.dict() for adjustment in scenario.adjustments],
            "executive_summary": prediction_result.executive_summary,
            "feature_importances": feature_importances,
        }
        with meta_path.open("w") as meta_file:
            json.dump(meta_payload, meta_file)

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

        response = ScenarioResponse(
            scenario_id=scenario_id,
            model_id=model_id,
            name=scenario.name or f"Scenario {scenario_id[:8]}",
            horizon_days=scenario.horizon_days,
            created_at=timestamp,
            summary=summary,
            predictions=predictions,
            adjustments=scenario.adjustments,
            executive_summary=prediction_result.executive_summary,
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
        created_at = datetime.fromisoformat(created_at_str) if created_at_str else datetime.utcnow()

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
