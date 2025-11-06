"""v2 report endpoints for data quality artefacts."""

from __future__ import annotations

import json
import math
import os
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.job import Job
from backend.schemas.reports_v2 import (
    BriefQualityMetrics,
    BriefReportResponse,
    DetailedAssetReport,
    DetailedReportResponse,
    JobProgressResponse,
)
from backend.services.error_logger import ErrorLogger

router = APIRouter()


def _load_job(db: Session, job_id: int) -> Job:
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "technical": f"Job {job_id} not found",
                "user_friendly": "This job doesn't exist or has been archived.",
            },
        )
    return job


def _load_timeseries(path: Optional[str]) -> Optional[pd.DataFrame]:
    if not path or not os.path.exists(path):
        return None
    try:
        return pd.read_parquet(path)
    except Exception:
        return None


def _value_column(df: pd.DataFrame) -> Optional[str]:
    for candidate in ("value", "Value"):
        if candidate in df.columns:
            return candidate
    numeric_cols = [col for col in df.columns if pd.api.types.is_numeric_dtype(df[col])]
    if numeric_cols:
        return numeric_cols[0]
    return None


def _date_column(df: pd.DataFrame) -> Optional[str]:
    for candidate in ("date", "Date", "timestamp", "Timestamp"):
        if candidate in df.columns:
            return candidate
    return None


def _brief_response(job: Job, df: Optional[pd.DataFrame]) -> BriefReportResponse:
    result = job.result or {}
    quality_score = result.get("quality_score")
    completeness = result.get("completeness")
    consistency = result.get("consistency")
    timeliness = result.get("timeliness")

    downloaded = 0
    total_rows = 0
    start_date = None
    end_date = None

    if df is not None and not df.empty and "source_code" in df.columns:
        downloaded = df["source_code"].nunique()
        total_rows = len(df)
        date_col = _date_column(df)
        if date_col:
            try:
                dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
                if not dates.empty:
                    start_date = dates.min().to_pydatetime()
                    end_date = dates.max().to_pydatetime()
            except Exception:
                pass

    metrics = BriefQualityMetrics(
        completeness=completeness,
        consistency=consistency,
        timeliness=timeliness,
    )

    return BriefReportResponse(
        job_id=job.id,
        status=job.status,
        downloaded=downloaded,
        failed=max(0, (result.get("anomalies_detected") or 0) - (result.get("anomalies_fixed") or 0)),
        fit_for_purpose_score=quality_score,
        quality_metrics=metrics,
        coverage_start=start_date,
        coverage_end=end_date,
        total_observations=total_rows,
        dataset_path=result.get("output_path"),
        regions=result.get("regions") or [],
        countries=result.get("countries") or [],
    )


def _detailed_response(job: Job, df: Optional[pd.DataFrame]) -> DetailedReportResponse:
    result = job.result or {}
    if df is None or df.empty or "source_code" not in df.columns:
        return DetailedReportResponse(
            job_id=job.id,
            status=job.status,
            fit_for_engine=bool(result.get("fit_for_engine", False)),
            assets=[],
            totals=BriefQualityMetrics(
                completeness=result.get("completeness"),
                consistency=result.get("consistency"),
                timeliness=result.get("timeliness"),
            ),
            regions=result.get("regions") or [],
            countries=result.get("countries") or [],
        )

    assets: list[DetailedAssetReport] = []

    value_col = _value_column(df)
    date_col = _date_column(df)

    for source_code, subset in df.groupby("source_code"):
        records = len(subset)
        missing_values = 0
        values = None
        anomaly_ratio = None
        value_mean = None
        value_std = None
        latest_value = None
        coverage_start = None
        coverage_end = None
        latest_timestamp = None

        if value_col:
            coerced = pd.to_numeric(subset[value_col], errors="coerce")
            missing_values = int(coerced.isna().sum())
            values = coerced.dropna()
            if not values.empty:
                value_mean = float(values.mean())
                std_value = values.std()
                value_std = float(std_value) if std_value is not None else None
                latest_value = float(values.iloc[-1])
                if value_std and value_std > 0:
                    z_scores = (values - value_mean) / value_std
                    anomalies = (z_scores.abs() > 3).sum()
                    anomaly_ratio = float(anomalies / len(values))
                else:
                    anomaly_ratio = 0.0

        if date_col:
            dates = pd.to_datetime(subset[date_col], errors="coerce").dropna()
            if not dates.empty:
                coverage_start = dates.min().to_pydatetime()
                coverage_end = dates.max().to_pydatetime()
                latest_timestamp = dates.iloc[-1].to_pydatetime()

        if value_mean is not None and (math.isnan(value_mean) or math.isinf(value_mean)):
            value_mean = None
        if value_std is not None and (math.isnan(value_std) or math.isinf(value_std)):
            value_std = None
        if latest_value is not None and (math.isnan(latest_value) or math.isinf(latest_value)):
            latest_value = None
        if anomaly_ratio is not None and (math.isnan(anomaly_ratio) or math.isinf(anomaly_ratio)):
            anomaly_ratio = None

        assets.append(
            DetailedAssetReport(
                source_code=str(source_code),
                records=records,
                missing_values=missing_values,
                coverage_start=coverage_start,
                coverage_end=coverage_end,
                latest_timestamp=latest_timestamp,
                latest_value=latest_value,
                value_mean=value_mean,
                value_std=value_std,
                anomaly_ratio=anomaly_ratio,
            )
        )

    assets.sort(key=lambda item: item.source_code)

    return DetailedReportResponse(
        job_id=job.id,
        status=job.status,
        fit_for_engine=bool(result.get("fit_for_engine", False)),
        assets=assets,
        totals=BriefQualityMetrics(
            completeness=result.get("completeness"),
            consistency=result.get("consistency"),
            timeliness=result.get("timeliness"),
        ),
        regions=result.get("regions") or [],
        countries=result.get("countries") or [],
    )


def _progress_response(job: Job) -> JSONResponse:
    payload = JobProgressResponse(
        job_id=job.id,
        status=job.status,
        progress=job.progress or 0.0,
        current_step=job.current_step,
    )
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=payload.model_dump())


@router.get("/reports/brief/{job_id}", response_model=BriefReportResponse)
async def get_brief_report(job_id: int, db: Session = Depends(get_db)):
    try:
        job = _load_job(db, job_id)
        if job.status != "completed":
            return _progress_response(job)

        result = job.result or {}
        df = _load_timeseries(result.get("output_path"))
        brief = _brief_response(job, df)
        return brief
    except HTTPException:
        raise
    except Exception as exc:
        error_logger = ErrorLogger(db)
        error = error_logger.log_error(
            exc,
            context="getting v2 brief report",
            endpoint=f"/api/v2/reports/brief/{job_id}",
            method="GET",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error.technical_message, "user_friendly": error.user_message},
        )


@router.get("/reports/detailed/{job_id}", response_model=DetailedReportResponse)
async def get_detailed_report(job_id: int, db: Session = Depends(get_db)):
    try:
        job = _load_job(db, job_id)
        if job.status != "completed":
            return _progress_response(job)

        result = job.result or {}
        df = _load_timeseries(result.get("output_path"))
        detailed = _detailed_response(job, df)
        return detailed
    except HTTPException:
        raise
    except Exception as exc:
        error_logger = ErrorLogger(db)
        error = error_logger.log_error(
            exc,
            context="getting v2 detailed report",
            endpoint=f"/api/v2/reports/detailed/{job_id}",
            method="GET",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error.technical_message, "user_friendly": error.user_message},
        )
