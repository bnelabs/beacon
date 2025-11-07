"""API routes for advanced analytics and insights."""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, desc, case
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from collections import defaultdict

from backend.database import get_db
from backend.models.job import Job
from backend.models.pipeline_job import PipelineJob, DataJob, JobStatus
from backend.services.error_logger import ErrorLogger

router = APIRouter()


@router.get("/overview", response_model=Dict[str, Any])
async def get_analytics_overview(
    days: int = Query(30, description="Number of days to analyze"),
    db: Session = Depends(get_db)
):
    """
    Get comprehensive analytics overview.

    Returns key metrics, trends, and insights across the platform.
    """
    try:
        now = datetime.utcnow()
        start_date = now - timedelta(days=days)

        # Job statistics
        total_jobs = db.query(Job).filter(Job.created_at >= start_date).count()
        completed_jobs = db.query(Job).filter(
            and_(Job.created_at >= start_date, Job.status == 'completed')
        ).count()
        failed_jobs = db.query(Job).filter(
            and_(Job.created_at >= start_date, Job.status == 'failed')
        ).count()

        success_rate = (completed_jobs / total_jobs * 100) if total_jobs > 0 else 0

        # Average execution time
        avg_exec_time = db.query(func.avg(Job.execution_time_seconds)).filter(
            and_(Job.created_at >= start_date, Job.status == 'completed')
        ).scalar() or 0

        # Model statistics (from training jobs)
        total_models = db.query(Job).filter(Job.job_type == 'training').count()
        ready_models = db.query(Job).filter(
            and_(Job.job_type == 'training', Job.status == 'completed')
        ).count()

        # Data quality trend
        from backend.models.pipeline_job import DataJob
        recent_quality_jobs = db.query(DataJob).join(PipelineJob).filter(
            and_(
                PipelineJob.created_at >= start_date,
                DataJob.quality_score.isnot(None)
            )
        ).all()

        quality_scores = [job.quality_score for job in recent_quality_jobs if job.quality_score]
        avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0

        # Completeness trend
        completeness_scores = [job.completeness for job in recent_quality_jobs if job.completeness]
        avg_completeness = sum(completeness_scores) / len(completeness_scores) if completeness_scores else 0

        # Job type distribution
        job_type_counts = db.query(
            Job.job_type,
            func.count().label('count')
        ).filter(Job.created_at >= start_date).group_by(Job.job_type).all()

        job_distribution = {job_type: count for job_type, count in job_type_counts}

        return {
            "period": {
                "days": days,
                "start_date": start_date.isoformat(),
                "end_date": now.isoformat()
            },
            "jobs": {
                "total": total_jobs,
                "completed": completed_jobs,
                "failed": failed_jobs,
                "success_rate": round(success_rate, 2),
                "avg_execution_time": round(avg_exec_time, 2),
                "distribution": job_distribution
            },
            "models": {
                "total": total_models,
                "ready": ready_models,
                "health_percentage": round((ready_models / total_models * 100) if total_models > 0 else 0, 2)
            },
            "data_quality": {
                "avg_quality_score": round(avg_quality, 4),
                "avg_completeness": round(avg_completeness, 4),
                "jobs_analyzed": len(quality_scores)
            }
        }

    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(
            e,
            context="fetching analytics overview",
            endpoint="/api/v1/analytics/overview",
            method="GET"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.get("/trends/time-series", response_model=Dict[str, Any])
async def get_time_series_trends(
    days: int = Query(30, description="Number of days to analyze"),
    metric: str = Query("quality", description="Metric to analyze: quality, completeness, jobs"),
    db: Session = Depends(get_db)
):
    """
    Get time-series trends for various metrics.
    """
    try:
        now = datetime.utcnow()
        start_date = now - timedelta(days=days)

        if metric == "quality":
            # Quality score trends
            from backend.models.pipeline_job import DataJob
            data_jobs = db.query(DataJob, PipelineJob).join(
                PipelineJob, DataJob.pipeline_job_id == PipelineJob.id
            ).filter(
                and_(
                    PipelineJob.created_at >= start_date,
                    DataJob.quality_score.isnot(None)
                )
            ).order_by(PipelineJob.created_at).all()

            daily_data = defaultdict(lambda: {"values": [], "date": None})

            for data_job, pipeline_job in data_jobs:
                day_key = pipeline_job.created_at.date().isoformat()
                daily_data[day_key]["date"] = day_key
                daily_data[day_key]["values"].append(data_job.quality_score)

            series = []
            for day_key in sorted(daily_data.keys()):
                values = daily_data[day_key]["values"]
                series.append({
                    "date": day_key,
                    "value": round(sum(values) / len(values), 4) if values else None,
                    "count": len(values),
                    "min": round(min(values), 4) if values else None,
                    "max": round(max(values), 4) if values else None
                })

            return {
                "metric": "quality_score",
                "period_days": days,
                "data_points": len(series),
                "series": series
            }

        elif metric == "completeness":
            # Completeness trends
            from backend.models.pipeline_job import DataJob
            data_jobs = db.query(DataJob, PipelineJob).join(
                PipelineJob, DataJob.pipeline_job_id == PipelineJob.id
            ).filter(
                and_(
                    PipelineJob.created_at >= start_date,
                    DataJob.completeness.isnot(None)
                )
            ).order_by(PipelineJob.created_at).all()

            daily_data = defaultdict(lambda: {"values": [], "date": None})

            for data_job, pipeline_job in data_jobs:
                day_key = pipeline_job.created_at.date().isoformat()
                daily_data[day_key]["date"] = day_key
                daily_data[day_key]["values"].append(data_job.completeness)

            series = []
            for day_key in sorted(daily_data.keys()):
                values = daily_data[day_key]["values"]
                series.append({
                    "date": day_key,
                    "value": round(sum(values) / len(values), 4) if values else None,
                    "count": len(values)
                })

            return {
                "metric": "completeness",
                "period_days": days,
                "data_points": len(series),
                "series": series
            }

        elif metric == "jobs":
            # Job execution trends
            daily_stats = db.query(
                func.date(Job.created_at).label('date'),
                func.count().label('total'),
                func.sum(case((Job.status == 'completed', 1), else_=0)).label('completed'),
                func.sum(case((Job.status == 'failed', 1), else_=0)).label('failed'),
                func.avg(Job.execution_time_seconds).label('avg_exec_time')
            ).filter(
                Job.created_at >= start_date
            ).group_by(func.date(Job.created_at)).order_by(func.date(Job.created_at)).all()

            series = []
            for stat in daily_stats:
                date_str = stat.date.isoformat()
                total = stat.total or 0
                completed = stat.completed or 0
                success_rate = (completed / total * 100) if total > 0 else 0

                series.append({
                    "date": date_str,
                    "total": total,
                    "completed": completed,
                    "failed": stat.failed or 0,
                    "success_rate": round(success_rate, 2),
                    "avg_execution_time": round(stat.avg_exec_time, 2) if stat.avg_exec_time else None
                })

            return {
                "metric": "job_execution",
                "period_days": days,
                "data_points": len(series),
                "series": series
            }

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"user_friendly": f"Unknown metric: {metric}. Supported: quality, completeness, jobs"}
            )

    except HTTPException:
        raise
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(
            e,
            context="fetching time series trends",
            endpoint="/api/v1/analytics/trends/time-series",
            method="GET"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.get("/models/performance-comparison", response_model=Dict[str, Any])
async def get_model_performance_comparison(
    db: Session = Depends(get_db)
):
    """
    Get comprehensive model performance comparison.
    """
    try:
        # Get training jobs (which represent models)
        models = db.query(Job).filter(
            and_(Job.job_type == 'training', Job.result.isnot(None))
        ).all()

        comparison_data = []
        for job in models:
            result = job.result or {}

            comparison_data.append({
                "model_id": job.id,
                "name": result.get('model_type', 'Unknown Model').upper(),
                "model_type": result.get('model_type'),
                "status": job.status,
                "r2": result.get('test_r2') or result.get('r2'),
                "rmse": result.get('test_rmse') or result.get('rmse'),
                "mae": result.get('test_mae') or result.get('mae'),
                "accuracy": result.get('accuracy'),
                "best_val_loss": result.get('best_val_loss'),
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "predictions_available": bool(result.get('predictions_path'))
            })

        # Calculate aggregate statistics
        r2_scores = [m['r2'] for m in comparison_data if m['r2'] is not None]
        rmse_scores = [m['rmse'] for m in comparison_data if m['rmse'] is not None]

        return {
            "total_models": len(comparison_data),
            "models": comparison_data,
            "aggregates": {
                "avg_r2": round(sum(r2_scores) / len(r2_scores), 4) if r2_scores else None,
                "avg_rmse": round(sum(rmse_scores) / len(rmse_scores), 4) if rmse_scores else None,
                "best_r2": round(max(r2_scores), 4) if r2_scores else None,
                "best_rmse": round(min(rmse_scores), 4) if rmse_scores else None
            }
        }

    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(
            e,
            context="fetching model performance comparison",
            endpoint="/api/v1/analytics/models/performance-comparison",
            method="GET"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.get("/distribution/risk-scores", response_model=Dict[str, Any])
async def get_risk_score_distribution(
    bins: int = Query(10, description="Number of bins for distribution"),
    db: Session = Depends(get_db)
):
    """
    Get risk score distribution across all predictions.

    Note: This endpoint requires prediction data to be available.
    """
    try:
        # This would require prediction data
        # For now, return a placeholder structure
        return {
            "bins": bins,
            "distribution": [],
            "statistics": {
                "mean": None,
                "median": None,
                "std_dev": None,
                "min": None,
                "max": None,
                "total_predictions": 0
            },
            "message": "Prediction data not yet available. Run model predictions first."
        }

    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(
            e,
            context="fetching risk score distribution",
            endpoint="/api/v1/analytics/distribution/risk-scores",
            method="GET"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.get("/insights/anomalies", response_model=Dict[str, Any])
async def get_anomaly_insights(
    days: int = Query(7, description="Number of days to analyze"),
    db: Session = Depends(get_db)
):
    """
    Detect and report anomalies in system behavior.
    """
    try:
        now = datetime.utcnow()
        start_date = now - timedelta(days=days)

        anomalies = []

        # Check for unusual failure rates
        total_jobs = db.query(Job).filter(Job.created_at >= start_date).count()
        failed_jobs = db.query(Job).filter(
            and_(Job.created_at >= start_date, Job.status == 'failed')
        ).count()

        if total_jobs > 0:
            failure_rate = (failed_jobs / total_jobs) * 100
            if failure_rate > 20:  # More than 20% failure rate
                anomalies.append({
                    "type": "high_failure_rate",
                    "severity": "high" if failure_rate > 50 else "medium",
                    "value": round(failure_rate, 2),
                    "message": f"Job failure rate is {round(failure_rate, 2)}% (threshold: 20%)",
                    "detected_at": now.isoformat()
                })

        # Check for slow execution times
        recent_exec_times = db.query(Job.execution_time_seconds).filter(
            and_(
                Job.created_at >= start_date,
                Job.status == 'completed',
                Job.execution_time_seconds.isnot(None)
            )
        ).all()

        if recent_exec_times:
            exec_times = [t[0] for t in recent_exec_times]
            avg_exec_time = sum(exec_times) / len(exec_times)
            max_exec_time = max(exec_times)

            # If max is more than 3x average, flag it
            if max_exec_time > avg_exec_time * 3:
                anomalies.append({
                    "type": "slow_execution",
                    "severity": "medium",
                    "value": round(max_exec_time, 2),
                    "message": f"Job execution time spike detected: {round(max_exec_time, 2)}s (avg: {round(avg_exec_time, 2)}s)",
                    "detected_at": now.isoformat()
                })

        # Check for data quality drops
        from backend.models.pipeline_job import DataJob
        recent_quality = db.query(DataJob).join(PipelineJob).filter(
            and_(
                PipelineJob.created_at >= start_date,
                DataJob.quality_score.isnot(None)
            )
        ).order_by(desc(PipelineJob.created_at)).limit(20).all()

        if len(recent_quality) > 5:
            recent_scores = [job.quality_score for job in recent_quality[:5]]
            older_scores = [job.quality_score for job in recent_quality[5:]]

            if recent_scores and older_scores:
                recent_avg = sum(recent_scores) / len(recent_scores)
                older_avg = sum(older_scores) / len(older_scores)

                # If recent average is 20% lower than older average
                if recent_avg < older_avg * 0.8:
                    anomalies.append({
                        "type": "quality_degradation",
                        "severity": "high",
                        "value": round(recent_avg, 4),
                        "message": f"Data quality degradation detected: {round(recent_avg, 4)} vs {round(older_avg, 4)}",
                        "detected_at": now.isoformat()
                    })

        return {
            "period_days": days,
            "anomalies_detected": len(anomalies),
            "anomalies": anomalies,
            "analysis_timestamp": now.isoformat()
        }

    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(
            e,
            context="fetching anomaly insights",
            endpoint="/api/v1/analytics/insights/anomalies",
            method="GET"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )
