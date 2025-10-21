"""Business logic for managing pipelines."""

from sqlalchemy.orm import Session
from typing import List, Optional

from models.job import Job
from services.job_service import JobService

class PipelineService:
    """Service for managing pipelines of jobs."""

    def __init__(self, db: Session):
        self.db = db
        self.job_service = JobService(db)

    def trigger_retraining_pipeline(self, model_version_id: int):
        """Trigger a retraining pipeline for a given model version."""
        # 1. Create a new data collection job
        data_collection_job = self.job_service.create_job(
            job_type="data_collection",
            parameters={}
        )

        # 2. Create a new training job that depends on the data collection job
        training_job = self.job_service.create_job(
            job_type="training",
            parameters={
                "data_job_id": data_collection_job.id,
                "model_version_id": model_version_id,
            }
        )

        return [data_collection_job, training_job]
