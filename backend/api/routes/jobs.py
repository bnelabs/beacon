"""API routes for job management."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from models.job import Job
from schemas.job import (
    JobCreate,
    JobResponse,
    JobListFilter
)
from services.job_service import JobService
from services.error_logger import ErrorLogger

router = APIRouter()


@router.get("/", response_model=List[JobResponse])
async def list_jobs(
    job_type: str = None,
    status_filter: str = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """
    List background jobs.

    **For non-technical users:** View all the tasks running in the system
    (like data collection, model training, predictions). You can see their progress
    and whether they completed successfully.
    """
    try:
        service = JobService(db)
        return service.list_jobs(
            job_type=job_type,
            status_filter=status_filter,
            limit=limit,
            offset=offset
        )
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="listing jobs", endpoint="/api/v1/jobs", method="GET")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: int,
    db: Session = Depends(get_db)
):
    """
    Get details of a specific job.

    **For non-technical users:** Check the status and results of a specific task.
    If it failed, you'll see an explanation of what went wrong.
    """
    try:
        service = JobService(db)
        job = service.get_job(job_id)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "technical": f"Job {job_id} not found",
                    "user_friendly": "This job doesn't exist. It may have been cleaned up."
                }
            )
        return job
    except HTTPException:
        raise
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="retrieving job", endpoint=f"/api/v1/jobs/{job_id}", method="GET")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.post("/", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    job: JobCreate,
    db: Session = Depends(get_db)
):
    """
    Start a new background job.

    **For non-technical users:** Start a task like collecting data, training the model,
    or running predictions. The job will run in the background and you can check its progress.

    **Job Types:**
    - `data_collection`: Download latest market data
    - `training`: Train the AI model
    - `prediction`: Generate liquidity predictions
    - `backtest`: Test the model on historical data
    """
    try:
        service = JobService(db)
        return service.create_job(job)
    except ValueError as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="starting job", endpoint="/api/v1/jobs", method="POST", request_data=job.dict())
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="starting job", endpoint="/api/v1/jobs", method="POST", request_data=job.dict())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_job(
    job_id: int,
    db: Session = Depends(get_db)
):
    """
    Cancel a running job.

    **For non-technical users:** Stop a task that's currently running.
    This is useful if you accidentally started the wrong job or need to free up resources.
    """
    try:
        service = JobService(db)
        cancelled = service.cancel_job(job_id)
        if not cancelled:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "technical": f"Job {job_id} not found or already completed",
                    "user_friendly": "This job doesn't exist or has already finished."
                }
            )
    except HTTPException:
        raise
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="cancelling job", endpoint=f"/api/v1/jobs/{job_id}", method="DELETE")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )
