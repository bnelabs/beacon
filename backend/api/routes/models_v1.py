"""API routes for trained model catalogue."""

from __future__ import annotations

import os
from typing import List, Optional

from uuid import uuid4
from datetime import datetime, timedelta, timezone
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

# torch and RealPredictionEngine are imported lazily inside ``simulate_model``
# (the only endpoint that runs inference). This router is imported by
# ``backend.api.main`` at startup, so importing the prediction engine -- which
# pulls torch -- at module scope would load the heavy ML runtime into the base
# API container just to serve the model *catalogue* (list/detail/scenario reads
# that never touch a model). Deferring it keeps those reads cheap and confines
# the torch footprint to the inference path.

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


def _run_network_clearing(df: pd.DataFrame, scenario_parameters: dict) -> Optional[dict]:
    """Clear the interbank network for network-type scenario parameters.

    Runs the Eisenberg-Noe multiplex clearing on the latest quarter of the
    AI4Risk edge rows. Two assumptions are DECLARED in the output, never
    silently made:

    * edge orientation: ``sourceid -> targetid`` is read as "sourceid holds a
      claim on targetid", so ``liabilities[debtor, creditor]`` is built from
      ``(targetid, sourceid)``. The upstream dataset does not document the
      orientation, so the result is conditional on this reading;
    * endowments: the dataset carries no balance sheets, so each bank's
      endowment is ``endowment_fraction`` times its gross total exposure
      (default 1.0). A failed bank's endowment is set to zero -- that is the
      default event driving the cascade.
    """
    if not any(key in scenario_parameters for key in ('failed_bank_id', 'interbank_lending_reduction')):
        return None
    if 'source_bank' not in df.columns or 'target_bank' not in df.columns:
        return {"skipped": "no interbank edge rows in the payload"}
    edges = df[df['source_bank'].notna()]
    if edges.empty:
        return {"skipped": "no interbank edge rows in the payload"}

    latest_date = edges['Date'].max()
    latest = edges[edges['Date'] == latest_date]

    # The interbank panel carries a small number of negative values
    # (~0.8% of edges): a negative "exposure" is not a liability the
    # Eisenberg-Noe map can price, so those rows are excluded and the
    # exclusion is declared in the output rather than absorbed silently.
    exposures: dict = {}
    dropped_nonpositive = 0
    for row in latest.to_dict(orient='records'):
        value = row.get('Value')
        if value is None:
            continue
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            dropped_nonpositive += 1
            continue
        debtor = str(row['target_bank'])
        creditor = str(row['source_bank'])
        if debtor == creditor:
            continue
        exposures[(debtor, creditor)] = exposures.get((debtor, creditor), 0.0) + value

    node_ids = sorted({bank for pair in exposures for bank in pair})
    index = {bank: position for position, bank in enumerate(node_ids)}
    n = len(node_ids)
    matrix = [[0.0] * n for _ in range(n)]
    for (debtor, creditor), amount in exposures.items():
        matrix[index[debtor]][index[creditor]] += amount
    gross = {bank: 0.0 for bank in node_ids}
    for (debtor, _creditor), amount in exposures.items():
        gross[debtor] += amount

    fraction = float(scenario_parameters.get('endowment_fraction', 1.0))
    endowments = [fraction * gross[bank] for bank in node_ids]
    failed_bank = scenario_parameters.get('failed_bank_id')
    failed_bank_note = None
    if failed_bank is not None:
        if failed_bank not in index:
            return {
                "skipped": f"failed bank {failed_bank!r} is not present in the "
                           "latest network quarter"
            }
        endowments[index[failed_bank]] = 0.0
        failed_bank_note = {"bank": failed_bank, "endowment": 0.0}

    import numpy as np
    from backend.modules.risk.clearing import clear_multiplex, NetworkLayer

    result = clear_multiplex([NetworkLayer('interbank', np.asarray(matrix))], endowments, node_ids=node_ids)
    payload = result.to_dict()
    payload['declared_assumptions'] = {
        'edge_orientation': 'sourceid holds a claim on targetid (upstream does not document orientation)',
        'endowments': f'{fraction} x gross total exposure per bank (no balance sheets in dataset)',
        'as_of': str(latest_date),
        'failed_bank': failed_bank_note,
        'dropped_nonpositive_edges': dropped_nonpositive,
    }
    return payload


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

        # Heavy inference runtime, loaded only when a scenario is actually run.
        import torch
        from backend.modules.engine.prediction_engine import RealPredictionEngine

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        source_data_job = db.query(Job).filter(Job.id == data_job_id).first()
        attestation = DataQualityGate.attestation_from_job_result(
            source_data_job.result
            if source_data_job and isinstance(source_data_job.result, dict)
            else {},
            job_id=str(data_job_id),
        )
        engine = RealPredictionEngine(
            model_path=model_path,
            device=device,
            config=result.get("config", {}),
            quality_attestation=attestation,
        )

        # Rich scenario parameters (type, rate_cut_bps, failed_bank_id, ...).
        # The legacy adjustments above are applied first; the named scenario
        # transforms run on top of them through the engine's apply_scenario.
        # The nested ``adjustments`` field is the same legacy mechanism,
        # already applied via the top-level field, so it is dropped here.
        scenario_parameters = scenario.scenario.model_dump(exclude_none=True)
        scenario_parameters.pop("adjustments", None)
        if scenario_parameters:
            adjusted_df = engine.apply_scenario(adjusted_df, scenario_parameters)

        # Network propagation: when the scenario carries network parameters,
        # clear the latest interbank quarter under the declared assumptions
        # (see _run_network_clearing). The ML scores below are unaffected;
        # the clearing is attached to the result as its own block.
        network_analysis = _run_network_clearing(adjusted_df, scenario_parameters)

        # The scenario adjustments transform the frame, so the attestation is
        # passed explicitly rather than relying on frame metadata surviving the
        # reshape. It attests the source dataset the scenario is applied to.
        prediction_result = engine.predict(adjusted_df, attestation=attestation)
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
        timestamp = datetime.now(timezone.utc)
        meta_payload = {
            "scenario_id": scenario_id,
            "model_id": model_id,
            "name": scenario.name or f"Scenario {scenario_id[:8]}",
            "horizon_days": scenario.horizon_days,
            "created_at": timestamp.isoformat(),
            "adjustments": [adjustment.dict() for adjustment in scenario.adjustments],
            "scenario_parameters": scenario_parameters,
            "network_analysis": network_analysis,
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
            scenario_parameters=scenario_parameters,
            network_analysis=network_analysis,
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
