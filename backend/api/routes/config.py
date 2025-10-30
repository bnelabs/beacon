"""API routes for system configuration."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from schemas.config import (
    SystemConfigResponse,
    ModelParamsUpdate,
    DataParamsUpdate,
    TrainingParamsUpdate,
    TrainingDefaultsResponse,
)
from services.config_service import ConfigService
from services.error_logger import ErrorLogger

router = APIRouter()


@router.get("", response_model=SystemConfigResponse)
@router.get("/", response_model=SystemConfigResponse)
async def get_system_config(db: Session = Depends(get_db)):
    """
    Get current system configuration.

    **For non-technical users:** View all the current settings for the system,
    including model parameters, data collection settings, and training options.
    """
    try:
        service = ConfigService(db)
        return service.get_system_config()
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="retrieving configuration", endpoint="/api/v1/config", method="GET")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.put("/model", response_model=SystemConfigResponse)
async def update_model_params(
    params: ModelParamsUpdate,
    db: Session = Depends(get_db)
):
    """
    Update model parameters.

    **For non-technical users:** Change how the AI model works.
    - **Hidden Dimension**: Model complexity (higher = more powerful but slower)
    - **Num Heads**: How many perspectives the model uses
    - **Num Layers**: Model depth (more layers = better patterns but slower)
    - **Dropout**: Helps prevent overfitting (0.0 to 0.9)
    - **Learning Rate**: How fast the model learns (0.00001 to 0.1)
    """
    try:
        service = ConfigService(db)
        return service.update_model_params(params)
    except ValueError as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="updating model settings", endpoint="/api/v1/config/model", method="PUT", request_data=params.dict())
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="updating model settings", endpoint="/api/v1/config/model", method="PUT", request_data=params.dict())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.put("/data", response_model=SystemConfigResponse)
async def update_data_params(
    params: DataParamsUpdate,
    db: Session = Depends(get_db)
):
    """
    Update data collection parameters.

    **For non-technical users:** Change how data is collected.
    - **Look Back**: How many days of history to use (1-365)
    - **Correlation Threshold**: Minimum similarity between assets (0.0-1.0)
    - **API Rate Limit**: Wait time between API calls to avoid hitting limits
    """
    try:
        service = ConfigService(db)
        return service.update_data_params(params)
    except ValueError as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="updating data settings", endpoint="/api/v1/config/data", method="PUT", request_data=params.dict())
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="updating data settings", endpoint="/api/v1/config/data", method="PUT", request_data=params.dict())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.put("/training", response_model=SystemConfigResponse)
async def update_training_params(
    params: TrainingParamsUpdate,
    db: Session = Depends(get_db)
):
    """
    Update training parameters.

    **For non-technical users:** Change how the model is trained.
    - **Batch Size**: Number of examples processed at once (higher = faster but more memory)
    - **Num Epochs**: How many times to go through the data (more = better but slower)
    - **Early Stopping Patience**: Stop if no improvement after N epochs
    - **Validation Split**: Portion of data used for validation (0.1-0.5)
    """
    try:
        service = ConfigService(db)
        return service.update_training_params(params)
    except ValueError as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="updating training settings", endpoint="/api/v1/config/training", method="PUT", request_data=params.dict())
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="updating training settings", endpoint="/api/v1/config/training", method="PUT", request_data=params.dict())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.get("/training-defaults", response_model=TrainingDefaultsResponse)
async def get_training_defaults(db: Session = Depends(get_db)):
    """Expose default training configuration for frontend UI."""
    try:
        service = ConfigService(db)
        return service.get_training_defaults()
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(
            e,
            context="retrieving training defaults",
            endpoint="/api/v1/config/training-defaults",
            method="GET",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message},
        )
