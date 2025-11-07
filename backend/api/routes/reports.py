"""API routes for report generation and export."""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
import io
import json

from backend.database import get_db
from backend.models.job import Job
from backend.models.data_source import DataSource
from backend.services.error_logger import ErrorLogger

router = APIRouter()


@router.get("/summary")
async def get_report_summary(
    report_type: str = Query("platform", description="Report type: platform, jobs, data_quality, models"),
    days: int = Query(30, description="Time period in days"),
    db: Session = Depends(get_db)
):
    """Get report summary data."""
    try:
        if report_type == "platform":
            total_jobs = db.query(Job).count()
            total_sources = db.query(DataSource).count()

            return {
                "report_type": report_type,
                "generated_at": datetime.utcnow().isoformat(),
                "period_days": days,
                "summary": {
                    "total_jobs": total_jobs,
                    "total_data_sources": total_sources,
                    "status": "operational"
                }
            }

        return {"report_type": report_type, "generated_at": datetime.utcnow().isoformat(), "message": "Report type not yet implemented"}

    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="generating report summary", endpoint="/api/v1/reports/summary", method="GET")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message})


@router.get("/export/json")
async def export_report_json(
    report_type: str = Query("platform"),
    days: int = Query(30),
    db: Session = Depends(get_db)
):
    """Export report as JSON."""
    try:
        report_data = {
            "report_type": report_type,
            "generated_at": datetime.utcnow().isoformat(),
            "period_days": days,
            "data": {
                "total_jobs": db.query(Job).count(),
                "total_sources": db.query(DataSource).count()
            }
        }

        json_str = json.dumps(report_data, indent=2)
        return StreamingResponse(
            io.BytesIO(json_str.encode()),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=beacon_report_{datetime.utcnow().strftime('%Y%m%d')}.json"}
        )

    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="exporting report", endpoint="/api/v1/reports/export/json", method="GET")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message})
