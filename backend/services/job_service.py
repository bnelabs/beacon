"""Business logic for job management."""

from sqlalchemy.orm import Session
from typing import List, Optional
import logging
from datetime import datetime
import json

from models.job import Job
from schemas.job import JobCreate
from .enhanced_error_translator import translate_error_enhanced

logger = logging.getLogger(__name__)


class JobService:
    """Service for managing background jobs."""

    def __init__(self, db: Session):
        self.db = db

    def list_jobs(
        self,
        job_type: Optional[str] = None,
        status_filter: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Job]:
        """List jobs with optional filtering."""
        query = self.db.query(Job)

        if job_type:
            query = query.filter(Job.job_type == job_type)
        if status_filter:
            query = query.filter(Job.status == status_filter)

        return query.order_by(Job.created_at.desc()).limit(limit).offset(offset).all()

    def get_job(self, job_id: int) -> Optional[Job]:
        """Get a specific job by ID."""
        return self.db.query(Job).filter(Job.id == job_id).first()

    def create_job(self, job: JobCreate) -> Job:
        """Create and start a new background job."""
        # Validate job type
        valid_types = ["data_collection", "training", "prediction", "backtest"]
        if job.job_type not in valid_types:
            raise ValueError(f"Invalid job type. Must be one of: {', '.join(valid_types)}")

        # Create job record
        db_job = Job(
            job_type=job.job_type,
            parameters=job.parameters,
            status="pending"
        )

        self.db.add(db_job)
        self.db.commit()
        self.db.refresh(db_job)

        # Submit to Celery
        try:
            from tasks.celery_app import dispatch_job
            task = dispatch_job.delay(db_job.id, job.job_type, job.parameters)

            # Update with Celery task ID
            db_job.celery_task_id = task.id
            self.db.commit()
            self.db.refresh(db_job)

            logger.info(f"Created job {db_job.id} (type: {job.job_type}, celery_id: {task.id})")
        except Exception as e:
            # Update job status to failed
            db_job.status = "failed"
            db_job.error_message = str(e)
            translated = translate_error_enhanced(e, context="starting job")
            db_job.user_friendly_error = json.dumps(translated)
            self.db.commit()
            logger.error(f"Failed to submit job {db_job.id} to Celery: {e}")

        return db_job

    def update_job_status(
        self,
        job_id: int,
        status: str,
        progress: Optional[float] = None,
        current_step: Optional[str] = None,
        error_message: Optional[str] = None,
        user_friendly_error: Optional[str] = None,
        result: Optional[dict] = None
    ) -> Optional[Job]:
        """Update job status (called by Celery tasks)."""
        db_job = self.get_job(job_id)
        if not db_job:
            return None

        db_job.status = status
        if progress is not None:
            db_job.progress = progress
        if current_step is not None:
            db_job.current_step = current_step
        if error_message:
            db_job.error_message = error_message
        if user_friendly_error:
            db_job.user_friendly_error = user_friendly_error
        if result:
            db_job.result = result

        # Update timestamps (use timezone-aware datetime)
        from datetime import timezone
        if status == "running" and not db_job.started_at:
            db_job.started_at = datetime.now(timezone.utc)
        elif status in ["completed", "failed"]:
            db_job.completed_at = datetime.now(timezone.utc)
            if db_job.started_at:
                elapsed = (db_job.completed_at - db_job.started_at).total_seconds()
                db_job.execution_time_seconds = elapsed

        self.db.commit()
        self.db.refresh(db_job)
        return db_job

    def cancel_job(self, job_id: int) -> bool:
        """Cancel a running job."""
        db_job = self.get_job(job_id)
        if not db_job or db_job.status in ["completed", "failed"]:
            return False

        # Revoke Celery task if it exists
        if db_job.celery_task_id:
            try:
                from tasks.celery_app import celery_app
                celery_app.control.revoke(db_job.celery_task_id, terminate=True)
            except Exception as e:
                logger.warning(f"Failed to revoke Celery task {db_job.celery_task_id}: {e}")

        # Update job status
        from datetime import timezone
        db_job.status = "failed"
        db_job.error_message = "Job cancelled by user"
        db_job.user_friendly_error = "This job was cancelled by the user."
        db_job.completed_at = datetime.now(timezone.utc)

        self.db.commit()
        logger.info(f"Cancelled job {job_id}")
        return True
