"""API routes for data quality monitoring.

Two writers produce quality evidence, and this module reads both:

* the **production job path** -- ``POST /api/v1/jobs``, per-source manual
  sync and the scheduler all run ``run_data_collection``, which stores the
  gate's verdict in ``Job.result`` (``quality_score``, ``completeness``) and
  the originating source in ``Job.parameters.data_source_id``;
* the **pipeline route** -- ``POST /api/v1/pipeline`` writes ``DataJob`` rows.

Reading only the second (as this module did until the pipeline-review fix
for finding F2) left the Data Quality page empty on every deployment that
collected through the documented path.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone

from backend.database import get_db
from backend.models.data_source import DataSource
from backend.models.job import Job
from backend.models.pipeline_job import PipelineJob
from backend.modules.data.quality_gate import QualityPolicy
from backend.services.error_logger import ErrorLogger

router = APIRouter()

#: "Low quality" means below the gate's certification floor. The previous
#: 0.5 threshold compared against 0-100 scores, so nothing was ever counted
#: -- a vacuous metric (the failure class the ledger calls an infrastructure
#: lie). The floor is read from the policy, not restated as a magic number.
LOW_QUALITY_THRESHOLD = QualityPolicy().min_quality_score

#: Cap on how many completed jobs each evidence query inspects, mirroring the
#: limit the DataJob query always had.
EVIDENCE_JOB_LIMIT = 200


def _collection_job_evidence(db: Session, since: datetime) -> List[Dict[str, Any]]:
    """Quality evidence from the production job path, newest first.

    ``Job.result`` and ``Job.parameters`` are JSON columns; they are parsed
    Python-side so the query is identical on SQLite and PostgreSQL (no
    dialect-specific JSON path operators).
    """
    jobs = (
        db.query(Job)
        .filter(
            Job.job_type == "data_collection",
            Job.status == "completed",
            Job.created_at >= since,
        )
        .order_by(desc(Job.created_at))
        .limit(EVIDENCE_JOB_LIMIT)
        .all()
    )
    evidence: List[Dict[str, Any]] = []
    for job in jobs:
        result = job.result if isinstance(job.result, dict) else {}
        score = result.get("quality_score")
        if score is None:
            continue  # a completed job with no gate verdict has no score to report
        parameters = job.parameters if isinstance(job.parameters, dict) else {}
        completeness = result.get("completeness")
        evidence.append({
            "job_id": f"job_{job.id}",
            "created_at": job.created_at,
            "quality_score": float(score),
            "completeness": float(completeness) if completeness is not None else None,
            "data_source_id": parameters.get("data_source_id"),
        })
    return evidence


def _pipeline_job_evidence(db: Session, since: datetime) -> List[Dict[str, Any]]:
    """Quality evidence from the ``/api/v1/pipeline`` route's DataJob rows."""
    from backend.models.pipeline_job import DataJob

    rows = (
        db.query(DataJob, PipelineJob)
        .join(PipelineJob, DataJob.pipeline_job_id == PipelineJob.id)
        .filter(
            and_(
                PipelineJob.created_at >= since,
                DataJob.status == 'completed',
                DataJob.quality_score.isnot(None),
            )
        )
        .order_by(desc(PipelineJob.created_at))
        .limit(EVIDENCE_JOB_LIMIT)
        .all()
    )
    return [
        {
            "job_id": pipeline_job.job_id,
            "created_at": pipeline_job.created_at,
            "quality_score": float(data_job.quality_score),
            "completeness": (
                float(data_job.completeness) if data_job.completeness is not None else None
            ),
            "data_source_id": None,  # the pipeline route does not scope to one source
        }
        for data_job, pipeline_job in rows
    ]


def _quality_evidence(db: Session, since: datetime) -> List[Dict[str, Any]]:
    """Both writers, one list."""
    return _collection_job_evidence(db, since) + _pipeline_job_evidence(db, since)


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalise a DB timestamp to aware UTC before any freshness maths.

    PostgreSQL timestamptz hands back aware datetimes; SQLite (development
    and the test suite) hands back naive ones, and subtracting or comparing
    across that boundary raises TypeError -- the same reason
    ``api/routes/pipeline.py`` and ``services/scheduling`` normalise first.
    Naive stamps are UTC by the pipeline's stated convention.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


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
        now = datetime.now(timezone.utc)
        stale_threshold = now - timedelta(days=7)  # 7 days
        outdated_threshold = now - timedelta(days=30)  # 30 days

        fresh_sources = 0
        stale_sources = 0
        outdated_sources = 0
        never_synced = 0

        for source in data_sources:
            last_fetch = _ensure_utc(source.last_successful_fetch)
            if not last_fetch:
                never_synced += 1
            elif last_fetch > stale_threshold:
                fresh_sources += 1
            elif last_fetch > outdated_threshold:
                stale_sources += 1
            else:
                outdated_sources += 1

        # Quality evidence from BOTH collection writers: the production job
        # path (Job.result JSON) and the pipeline route (DataJob rows).
        evidence = _quality_evidence(db, now - timedelta(days=30))

        quality_scores = [item["quality_score"] for item in evidence]
        completeness_scores = [
            item["completeness"] for item in evidence if item["completeness"] is not None
        ]

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

        # Calculate anomaly count (jobs below the gate's certification floor,
        # plus recent failures from BOTH writers)
        low_quality_jobs = sum(1 for score in quality_scores if score < LOW_QUALITY_THRESHOLD)
        recent_errors = db.query(PipelineJob).filter(
            and_(
                PipelineJob.created_at >= now - timedelta(days=7),
                PipelineJob.status == 'failed'
            )
        ).count()
        recent_errors += db.query(Job).filter(
            Job.job_type == "data_collection",
            Job.status == "failed",
            Job.created_at >= now - timedelta(days=7),
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
                # Both writers store completeness as a 0-100 percentage (the
                # gate's component scale), and the frontend renders this value
                # verbatim as "%" with 90/70 thresholds. The previous *100
                # double-scaled it (a 97% panel displayed as 9700%).
                "avg_completeness": round(avg_completeness, 4),
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
        now = datetime.now(timezone.utc)

        # Production collection jobs ARE linked to their source: scheduled and
        # manual syncs both carry data_source_id in Job.parameters (see
        # services/scheduling.collection_parameters). The previous "jobs are
        # not currently linked" comment went stale when per-source scheduling
        # landed; the link is parsed Python-side for SQLite/PostgreSQL parity.
        since = now - timedelta(days=30)
        scores_by_source: Dict[int, List[float]] = {}
        counts_by_source: Dict[int, int] = {}
        for item in _collection_job_evidence(db, since):
            source_id = item.get("data_source_id")
            if source_id is None:
                continue
            try:
                source_id = int(source_id)
            except (TypeError, ValueError):
                continue
            scores_by_source.setdefault(source_id, []).append(item["quality_score"])
            counts_by_source[source_id] = counts_by_source.get(source_id, 0) + 1

        source_details = []

        for source in data_sources:
            # Calculate freshness (normalised: SQLite stamps are naive UTC)
            last_fetch = _ensure_utc(source.last_successful_fetch)
            if last_fetch:
                days_since_update = (now - last_fetch).days
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

            scores = scores_by_source.get(source.id, [])
            avg_quality = sum(scores) / len(scores) if scores else None

            source_details.append({
                "id": source.id,
                "name": source.name,
                "plugin_type": source.plugin_type,
                "status": source.status,
                "enabled": source.enabled,
                "last_fetch": last_fetch.isoformat() if last_fetch else None,
                "days_since_update": days_since_update,
                "freshness_status": freshness_status,
                "freshness_color": freshness_color,
                "avg_quality_score": round(avg_quality, 4) if avg_quality is not None else None,
                "recent_job_count": counts_by_source.get(source.id, 0),
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
        now = datetime.now(timezone.utc)
        start_date = now - timedelta(days=days)

        # Daily buckets from BOTH writers, keyed by completion date.
        evidence = [
            item for item in _quality_evidence(db, start_date) if item.get("created_at")
        ]

        daily_metrics = {}

        for item in evidence:
            day_key = item["created_at"].date().isoformat()

            if day_key not in daily_metrics:
                daily_metrics[day_key] = {
                    "date": day_key,
                    "quality_scores": [],
                    "completeness_scores": [],
                    "job_count": 0,
                    "error_count": 0
                }

            daily_metrics[day_key]["job_count"] += 1
            daily_metrics[day_key]["quality_scores"].append(item["quality_score"])
            if item["completeness"] is not None:
                daily_metrics[day_key]["completeness_scores"].append(item["completeness"])

        # Get failed jobs by day (pipeline route)
        failed_jobs = db.query(
            func.date(PipelineJob.created_at).label('date'),
            func.count().label('count')
        ).filter(
            and_(
                PipelineJob.created_at >= start_date,
                PipelineJob.status == 'failed'
            )
        ).group_by(func.date(PipelineJob.created_at)).all()

        # Failed collections from the production job path, same window.
        failed_collection_jobs = db.query(
            func.date(Job.created_at).label('date'),
            func.count().label('count')
        ).filter(
            and_(
                Job.job_type == "data_collection",
                Job.status == "failed",
                Job.created_at >= start_date,
            )
        ).group_by(func.date(Job.created_at)).all()

        for date, count in list(failed_jobs) + list(failed_collection_jobs):
            day_key = date.isoformat() if hasattr(date, "isoformat") else str(date)
            if day_key in daily_metrics:
                daily_metrics[day_key]["error_count"] += count

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
                "total_jobs": len(evidence),
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
