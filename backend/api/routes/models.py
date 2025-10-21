"""API routes for model registry management."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from schemas.model import ModelResponse, ModelVersionResponse, ModelPromoteRequest
from services.model_service import ModelService
from services.error_logger import ErrorLogger
from auth import fastapi_users, current_active_user, current_active_superuser
from models.user import User

router = APIRouter()

@router.get("/", response_model=List[ModelVersionResponse])
async def list_model_versions(
    db: Session = Depends(get_db),
    user: User = Depends(current_active_user)
):
    """List all model versions."""
    try:
        service = ModelService(db)
        return service.list_model_versions()
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="listing model versions", endpoint="/api/v1/models", method="GET")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )

@router.post("/versions/{version_id}/promote", response_model=ModelVersionResponse)
async def promote_model_version(
    version_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_active_superuser)
):
    """Promote a model version to production."""
    try:
        service = ModelService(db)
        promoted_model = service.promote_model_version(version_id)
        if not promoted_model:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"technical": f"Model version {version_id} not found", "user_friendly": "Model version not found."}
            )
        return promoted_model
    except Exception as e:
        error_logger = ErrorLogger(db)
                error_log = error_logger.log_error(e, context="promoting model version", endpoint=f"/api/v1/models/versions/{version_id}/promote", method="POST")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
                )
        
        @router.get("/versions/{version_id}/drift_report")
        async def get_model_drift_report(
            version_id: int,
            db: Session = Depends(get_db),
            user: User = Depends(current_active_user)
        ):
            """Retrieve the data drift report for a specific model version."""
            try:
                from services.model_service import ModelService
                service = ModelService(db)
                drift_report = service.get_model_drift_report(version_id)
                if not drift_report:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail={"technical": f"Drift report for model version {version_id} not found", "user_friendly": "Drift report not available."}
                    )
                return drift_report
            except Exception as e:
                error_logger = ErrorLogger(db)
                error_log = error_logger.log_error(e, context="retrieving model drift report", endpoint=f"/api/v1/models/versions/{version_id}/drift_report", method="GET")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
                )
        
