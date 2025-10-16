"""API routes for error reporting and analytics."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from ...database import get_db
from ...models.error_log import ErrorLog
from ...services.error_logger import ErrorLogger

router = APIRouter()


class ErrorReportRequest(BaseModel):
    """Schema for client-side error reporting."""
    message: str
    stack_trace: Optional[str] = None
    context: Optional[str] = None
    page_url: Optional[str] = None
    user_agent: Optional[str] = None


class ErrorLogResponse(BaseModel):
    """Schema for error log response."""
    id: int
    severity: str
    category: str
    error_type: str
    user_message: str
    technical_message: Optional[str]
    context: Optional[str]
    solutions: Optional[List[str]]
    occurrence_count: int
    resolved: bool
    created_at: str
    last_occurred_at: str

    class Config:
        from_attributes = True


class ErrorStatsResponse(BaseModel):
    """Schema for error statistics response."""
    total_errors: int
    by_severity: dict
    by_category: dict
    recent_24h: int
    recent_7d: int
    unresolved: int
    most_common: List[dict]


@router.get("/", response_model=List[ErrorLogResponse])
async def list_errors(
    limit: int = 100,
    severity: Optional[str] = None,
    category: Optional[str] = None,
    resolved: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """
    List error logs with filtering.

    **For non-technical users:** View all errors that have occurred in the system.
    You can filter by severity (how serious) and category (what type of error).
    """
    logger = ErrorLogger(db)
    errors = logger.get_recent_errors(
        limit=limit,
        severity=severity,
        category=category,
        resolved=resolved
    )

    return [
        ErrorLogResponse(
            id=error.id,
            severity=error.severity,
            category=error.category,
            error_type=error.error_type,
            user_message=error.user_message,
            technical_message=error.technical_message,
            context=error.context,
            solutions=error.solutions,
            occurrence_count=error.occurrence_count,
            resolved=error.resolved,
            created_at=error.created_at.isoformat(),
            last_occurred_at=error.last_occurred_at.isoformat()
        )
        for error in errors
    ]


@router.get("/statistics", response_model=ErrorStatsResponse)
async def get_error_statistics(db: Session = Depends(get_db)):
    """
    Get error statistics and analytics.

    **For non-technical users:** See a summary of all errors - how many occurred,
    what types are most common, and which ones need attention.
    """
    logger = ErrorLogger(db)
    stats = logger.get_error_statistics()
    return ErrorStatsResponse(**stats)


@router.get("/{error_id}", response_model=ErrorLogResponse)
async def get_error_detail(
    error_id: int,
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific error.

    **For non-technical users:** View all details about an error including
    suggested solutions and technical information.
    """
    error = db.query(ErrorLog).filter(ErrorLog.id == error_id).first()

    if not error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Error log not found"
        )

    return ErrorLogResponse(
        id=error.id,
        severity=error.severity,
        category=error.category,
        error_type=error.error_type,
        user_message=error.user_message,
        technical_message=error.technical_message,
        context=error.context,
        solutions=error.solutions,
        occurrence_count=error.occurrence_count,
        resolved=error.resolved,
        created_at=error.created_at.isoformat(),
        last_occurred_at=error.last_occurred_at.isoformat()
    )


@router.post("/report")
async def report_client_error(
    error_report: ErrorReportRequest,
    db: Session = Depends(get_db)
):
    """
    Report a client-side error.

    **For non-technical users:** This is used automatically by the web interface
    to report errors that occur in your browser.
    """
    try:
        # Create a pseudo-exception for logging
        class ClientError(Exception):
            pass

        exception = ClientError(error_report.message)
        exception.__traceback__ = None

        logger = ErrorLogger(db)
        error_log = logger.log_error(
            exception=exception,
            context=error_report.context or "client-side",
            endpoint=error_report.page_url,
            method="CLIENT",
            request_data={
                "user_agent": error_report.user_agent,
                "stack_trace": error_report.stack_trace
            }
        )

        return {
            "success": True,
            "error_id": error_log.id,
            "message": "Error reported successfully"
        }

    except Exception as e:
        # Don't fail if error reporting fails
        print(f"Failed to report client error: {e}")
        return {
            "success": False,
            "message": "Failed to report error"
        }


@router.post("/{error_id}/resolve")
async def resolve_error(
    error_id: int,
    resolution_notes: str,
    db: Session = Depends(get_db)
):
    """
    Mark an error as resolved.

    **For non-technical users:** Mark an error as fixed after you've addressed
    the underlying issue. Add notes about how it was resolved.
    """
    logger = ErrorLogger(db)
    success = logger.mark_resolved(error_id, resolution_notes)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Error log not found"
        )

    return {
        "success": True,
        "message": "Error marked as resolved"
    }


@router.delete("/{error_id}")
async def delete_error_log(
    error_id: int,
    db: Session = Depends(get_db)
):
    """
    Delete an error log entry.

    **For non-technical users:** Remove an error from the log.
    Use this for test errors or errors that are no longer relevant.
    """
    error = db.query(ErrorLog).filter(ErrorLog.id == error_id).first()

    if not error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Error log not found"
        )

    db.delete(error)
    db.commit()

    return {
        "success": True,
        "message": "Error log deleted"
    }
