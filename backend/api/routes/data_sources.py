"""API routes for data source management."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from models.data_source import DataSource
from schemas.data_source import (
    DataSourceCreate,
    DataSourceUpdate,
    DataSourceResponse,
    DataSourceTestRequest,
    DataSourceTestResponse
)
from services.data_source_service import DataSourceService
from services.error_logger import ErrorLogger

router = APIRouter()


@router.get("", response_model=List[DataSourceResponse])
@router.get("/", response_model=List[DataSourceResponse])
async def list_data_sources(
    enabled_only: bool = False,
    db: Session = Depends(get_db)
):
    """
    List all configured data sources.

    **For non-technical users:** This shows all the data feeds you've set up
    (like Yahoo Finance, FRED, etc.). You can see which ones are working and which
    ones have errors.
    """
    try:
        service = DataSourceService(db)
        return service.list_data_sources(enabled_only=enabled_only)
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="listing data sources", endpoint="/api/v1/data-sources", method="GET")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.get("/{data_source_id}", response_model=DataSourceResponse)
async def get_data_source(
    data_source_id: int,
    db: Session = Depends(get_db)
):
    """
    Get details of a specific data source.

    **For non-technical users:** View the configuration and status of a single data feed.
    """
    try:
        service = DataSourceService(db)
        data_source = service.get_data_source(data_source_id)
        if not data_source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "technical": f"Data source {data_source_id} not found",
                    "user_friendly": "This data source doesn't exist. It may have been deleted."
                }
            )
        return data_source
    except HTTPException:
        raise
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="retrieving data source", endpoint=f"/api/v1/data-sources/{data_source_id}", method="GET")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.post("", response_model=DataSourceResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=DataSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_data_source(
    data_source: DataSourceCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new data source.

    **For non-technical users:** Add a new data feed to the system.
    Fill in the name, select the type (Yahoo Finance, FRED, etc.), and provide
    any required information like API keys.
    """
    try:
        service = DataSourceService(db)
        return service.create_data_source(data_source)
    except ValueError as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="creating data source", endpoint="/api/v1/data-sources", method="POST", request_data=data_source.dict())
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="creating data source", endpoint="/api/v1/data-sources", method="POST", request_data=data_source.dict())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.put("/{data_source_id}", response_model=DataSourceResponse)
async def update_data_source(
    data_source_id: int,
    data_source_update: DataSourceUpdate,
    db: Session = Depends(get_db)
):
    """
    Update an existing data source.

    **For non-technical users:** Modify the settings of an existing data feed.
    You can change the API key, enable/disable it, or update other settings.
    """
    try:
        service = DataSourceService(db)
        updated = service.update_data_source(data_source_id, data_source_update)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "technical": f"Data source {data_source_id} not found",
                    "user_friendly": "This data source doesn't exist. It may have been deleted."
                }
            )
        return updated
    except HTTPException:
        raise
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="updating data source", endpoint=f"/api/v1/data-sources/{data_source_id}", method="PUT", request_data=data_source_update.dict())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.delete("/{data_source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_data_source(
    data_source_id: int,
    db: Session = Depends(get_db)
):
    """
    Delete a data source.

    **For non-technical users:** Remove a data feed from the system.
    Warning: This will stop collecting data from this source.
    """
    try:
        service = DataSourceService(db)
        deleted = service.delete_data_source(data_source_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "technical": f"Data source {data_source_id} not found",
                    "user_friendly": "This data source doesn't exist. It may have already been deleted."
                }
            )
    except HTTPException:
        raise
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="deleting data source", endpoint=f"/api/v1/data-sources/{data_source_id}", method="DELETE")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.post("/test", response_model=DataSourceTestResponse)
async def test_data_source(
    test_request: DataSourceTestRequest,
    db: Session = Depends(get_db)
):
    """
    Test a data source configuration before saving it.

    **For non-technical users:** Check if your data feed settings are correct
    before you save them. This will verify your API key and connection work.
    """
    try:
        service = DataSourceService(db)
        return service.test_data_source(test_request)
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="testing data source", endpoint="/api/v1/data-sources/test", method="POST", request_data=test_request.dict())
        return DataSourceTestResponse(
            success=False,
            message=error_log.user_message,
            details={"technical_error": error_log.technical_message}
        )
