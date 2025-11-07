"""API routes for data quality monitoring."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from backend.database import get_db
from backend.models.data_source import DataSource
from backend.models.pipeline_job import PipelineJob
from backend.services.error_logger import ErrorLogger

router = APIRouter()


@router.get("/stats", response_model=Dict[str, Any])
async def get_data_quality_stats(
    db: Session = Depends(get_db)
):
    """
    Get overall data quality statistics.

    Returns metrics about data completeness, freshness, quality scores, and source health.
    """
    try:
        # Get all data sources
        data_sources = db.query(DataSource).all()

        # Calculate freshness metrics
        now = datetime.utcnow()
        stale_threshold = now - timedelta(days=7)  # 7 days
        outdated_threshold = now - timedelta(days=30)  # 30 days

        fresh_sources = 0
        stale_sources = 0
        outdated_sources = 0
        never_synced = 0

        for source in data_sources:
            if not source.last_successful_fetch:
                never_synced += 1
            elif source.last_successful_fetch > stale_threshold:
                fresh_sources += 1
            elif source.last_successful_fetch > outdated_threshold:
                stale_sources += 1
            else:
                outdated_sources += 1

        # Get recent data jobs (last 30 days) for quality scores
        from backend.models.pipeline_job import DataJob
        recent_jobs = db.query(DataJob).join(PipelineJob).filter(
            and_(
                PipelineJob.created_at >= now - timedelta(days=30),
                DataJob.status == 'completed',
                DataJob.quality_score.isnot(None)
            )
        ).order_by(desc(PipelineJob.created_at)).limit(100).all()

        # Calculate quality metrics from jobs
        quality_scores = []
        completeness_scores = []

        for job in recent_jobs:
            if job.quality_score is not None:
                quality_scores.append(job.quality_score)
            if job.completeness is not None:
                completeness_scores.append(job.completeness)

        avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0
        avg_completeness = sum(completeness_scores) / len(completeness_scores) if completeness_scores else 0

        # Calculate overall health score
        total_sources = len(data_sources)
        if total_sources > 0:
            freshness_score = (fresh_sources / total_sources) * 100
            source_health = ((fresh_sources + stale_sources) / total_sources) * 100
        else:
            freshness_score = 0
            source_health = 0

        # Get data source status breakdown
        active_sources = sum(1 for s in data_sources if s.status == 'active' and s.enabled)
        error_sources = sum(1 for s in data_sources if s.status == 'error')
        disabled_sources = sum(1 for s in data_sources if not s.enabled)

        # Calculate anomaly count (jobs with low quality or errors)
        anomaly_threshold = 0.5
        low_quality_jobs = sum(1 for score in quality_scores if score < anomaly_threshold)
        recent_errors = db.query(PipelineJob).filter(
            and_(
                PipelineJob.created_at >= now - timedelta(days=7),
                PipelineJob.status == 'failed'
            )
        ).count()

        return {
            "overview": {
                "total_sources": total_sources,
                "active_sources": active_sources,
                "error_sources": error_sources,
                "disabled_sources": disabled_sources,
                "overall_health": round(source_health, 1),
                "avg_quality_score": round(avg_quality, 4),
                "avg_completeness": round(avg_completeness, 4)
            },
            "freshness": {
                "fresh": fresh_sources,
                "stale": stale_sources,
                "outdated": outdated_sources,
                "never_synced": never_synced,
                "freshness_percentage": round(freshness_score, 1)
            },
            "quality": {
                "avg_quality_score": round(avg_quality, 4),
                "avg_completeness": round(avg_completeness * 100, 1),
                "low_quality_count": low_quality_jobs,
                "recent_errors": recent_errors,
                "jobs_analyzed": len(quality_scores)
            },
            "anomalies": {
                "low_quality_jobs": low_quality_jobs,
                "error_sources": error_sources,
                "recent_failures": recent_errors,
                "stale_sources": stale_sources + outdated_sources
            }
        }

    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(
            e,
            context="fetching data quality stats",
            endpoint="/api/v1/data-quality/stats",
            method="GET"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.get("/sources", response_model=List[Dict[str, Any]])
async def get_source_quality_details(
    db: Session = Depends(get_db)
):
    """
    Get detailed quality metrics for each data source.
    """
    try:
        data_sources = db.query(DataSource).all()
        now = datetime.utcnow()

        source_details = []

        for source in data_sources:
            # Calculate freshness
            if source.last_successful_fetch:
                days_since_update = (now - source.last_successful_fetch).days
                if days_since_update < 7:
                    freshness_status = 'fresh'
                    freshness_color = 'green'
                elif days_since_update < 30:
                    freshness_status = 'stale'
                    freshness_color = 'yellow'
                else:
                    freshness_status = 'outdated'
                    freshness_color = 'red'
            else:
                freshness_status = 'never_synced'
                freshness_color = 'gray'
                days_since_update = None

            # Note: Jobs are not currently linked to specific data sources
            # So we calculate a global average quality score
            avg_quality = None

            source_details.append({
                "id": source.id,
                "name": source.name,
                "plugin_type": source.plugin_type,
                "status": source.status,
                "enabled": source.enabled,
                "last_fetch": source.last_successful_fetch.isoformat() if source.last_successful_fetch else None,
                "days_since_update": days_since_update,
                "freshness_status": freshness_status,
                "freshness_color": freshness_color,
                "avg_quality_score": round(avg_quality, 4) if avg_quality else None,
                "recent_job_count": 0,  # Jobs not linked to sources currently
                "error_message": source.error_message
            })

        return source_details

    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(
            e,
            context="fetching source quality details",
            endpoint="/api/v1/data-quality/sources",
            method="GET"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.get("/trends", response_model=Dict[str, Any])
async def get_quality_trends(
    days: int = 30,
    db: Session = Depends(get_db)
):
    """
    Get quality score trends over time.
    """
    try:
        now = datetime.utcnow()
        start_date = now - timedelta(days=days)

        # Get all completed data jobs in timeframe
        from backend.models.pipeline_job import DataJob
        data_jobs = db.query(DataJob, PipelineJob).join(
            PipelineJob, DataJob.pipeline_job_id == PipelineJob.id
        ).filter(
            and_(
                PipelineJob.created_at >= start_date,
                DataJob.status == 'completed',
                DataJob.quality_score.isnot(None)
            )
        ).order_by(PipelineJob.created_at).all()

        # Group by day
        daily_metrics = {}

        for data_job, pipeline_job in data_jobs:
            day_key = pipeline_job.created_at.date().isoformat()

            if day_key not in daily_metrics:
                daily_metrics[day_key] = {
                    "date": day_key,
                    "quality_scores": [],
                    "completeness_scores": [],
                    "job_count": 0,
                    "error_count": 0
                }

            daily_metrics[day_key]["job_count"] += 1

            if data_job.quality_score is not None:
                daily_metrics[day_key]["quality_scores"].append(data_job.quality_score)

            if data_job.completeness is not None:
                daily_metrics[day_key]["completeness_scores"].append(data_job.completeness)

        # Get failed jobs by day
        failed_jobs = db.query(
            func.date(PipelineJob.created_at).label('date'),
            func.count().label('count')
        ).filter(
            and_(
                PipelineJob.created_at >= start_date,
                PipelineJob.status == 'failed'
            )
        ).group_by(func.date(PipelineJob.created_at)).all()

        for date, count in failed_jobs:
            day_key = date.isoformat()
            if day_key in daily_metrics:
                daily_metrics[day_key]["error_count"] = count

        # Calculate averages
        trends = []
        for day_key, metrics in sorted(daily_metrics.items()):
            avg_quality = (
                sum(metrics["quality_scores"]) / len(metrics["quality_scores"])
                if metrics["quality_scores"] else None
            )
            avg_completeness = (
                sum(metrics["completeness_scores"]) / len(metrics["completeness_scores"])
                if metrics["completeness_scores"] else None
            )

            trends.append({
                "date": day_key,
                "avg_quality_score": round(avg_quality, 4) if avg_quality else None,
                "avg_completeness": round(avg_completeness, 4) if avg_completeness else None,
                "job_count": metrics["job_count"],
                "error_count": metrics["error_count"]
            })

        return {
            "trends": trends,
            "summary": {
                "total_jobs": len(data_jobs),
                "days_analyzed": len(daily_metrics),
                "start_date": start_date.isoformat(),
                "end_date": now.isoformat()
            }
        }

    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(
            e,
            context="fetching quality trends",
            endpoint="/api/v1/data-quality/trends",
            method="GET"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )
