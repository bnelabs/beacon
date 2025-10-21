"""API routes for configuration management."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from schemas.config import ConfigurationCreate, ConfigurationUpdate, ConfigurationResponse
from services.configuration_service import ConfigurationService
from services.error_logger import ErrorLogger
from auth import fastapi_users, current_active_user, current_active_superuser
from models.user import User

router = APIRouter()

@router.post("/", response_model=ConfigurationResponse, status_code=status.HTTP_201_CREATED)

async def create_configuration(

    config: ConfigurationCreate,

    db: Session = Depends(get_db),

    user: User = Depends(current_active_superuser)

):

    """Create a new configuration."""

    try:

        service = ConfigurationService(db)

        return service.create_configuration(config)

    except Exception as e:

        error_logger = ErrorLogger(db)

        error_log = error_logger.log_error(e, context="creating configuration", endpoint="/api/v1/configurations", method="POST")

        raise HTTPException(

            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,

            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}

        )



@router.get("/", response_model=List[ConfigurationResponse])

async def list_configurations(

    db: Session = Depends(get_db),

    user: User = Depends(current_active_user)

):

    """

    List all configurations."""

    try:

        service = ConfigurationService(db)

        return service.list_configurations()

    except Exception as e:

        error_logger = ErrorLogger(db)

        error_log = error_logger.log_error(e, context="listing configurations", endpoint="/api/v1/configurations", method="GET")

        raise HTTPException(

            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,

            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}

        )



@router.put("/{config_id}", response_model=ConfigurationResponse)

async def update_configuration(

    config_id: int,

    config: ConfigurationUpdate,

    db: Session = Depends(get_db),

    user: User = Depends(current_active_superuser)

):

    """

    Update an existing configuration."""

    try:

        service = ConfigurationService(db)

        updated_config = service.update_configuration(config_id, config)

        if not updated_config:

            raise HTTPException(

                status_code=status.HTTP_404_NOT_FOUND,

                detail={"technical": f"Configuration {config_id} not found", "user_friendly": "Configuration not found."}

            )

        return updated_config

    except Exception as e:

        error_logger = ErrorLogger(db)

        error_log = error_logger.log_error(e, context="updating configuration", endpoint=f"/api/v1/configurations/{config_id}", method="PUT")

        raise HTTPException(

            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,

            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}

        )


