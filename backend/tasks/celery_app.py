"""Celery application configuration."""

from celery import Celery
import os

# Redis configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Create Celery app
celery_app = Celery(
    "beacon",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["tasks.job_tasks"]
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max per task
    task_soft_time_limit=3300,  # Soft limit at 55 minutes
    worker_prefetch_multiplier=1,  # Process one task at a time
    worker_max_tasks_per_child=50,  # Restart worker after 50 tasks (memory cleanup)
)


@celery_app.task(name="dispatch_job", bind=True)
def dispatch_job(self, job_id: int, job_type: str, parameters: dict = None):
    """
    Dispatch a job to the appropriate handler.

    This is the entry point for all background jobs.
    """
    from .job_tasks import (
        run_data_collection,
        run_training,
        run_prediction,
        run_backtest
    )

    # Map job types to task functions
    task_map = {
        "data_collection": run_data_collection,
        "training": run_training,
        "prediction": run_prediction,
        "backtest": run_backtest
    }

    task_func = task_map.get(job_type)
    if not task_func:
        raise ValueError(f"Unknown job type: {job_type}")

    # Execute the appropriate task
    return task_func.apply_async(args=[job_id, parameters or {}])
