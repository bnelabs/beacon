"""API routes for asset management."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from models.asset import Asset
from schemas.asset import (
    AssetCreate,
    AssetUpdate,
    AssetResponse,
    AssetBulkCreate,
    AssetBulkResponse
)
from services.asset_service import AssetService
from services.error_logger import ErrorLogger

router = APIRouter()


@router.get("", response_model=List[AssetResponse])
@router.get("/", response_model=List[AssetResponse])
async def list_assets(
    enabled_only: bool = False,
    asset_type: str = None,
    sector: str = None,
    region: str = None,
    db: Session = Depends(get_db)
):
    """
    List all configured assets.

    **For non-technical users:** View all the stocks, bonds, or other assets
    you're monitoring. You can filter by type, sector, or region.
    """
    try:
        service = AssetService(db)
        return service.list_assets(
            enabled_only=enabled_only,
            asset_type=asset_type,
            sector=sector,
            region=region
        )
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="listing assets", endpoint="/api/v1/assets", method="GET")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_asset(
    asset_id: int,
    db: Session = Depends(get_db)
):
    """
    Get details of a specific asset.

    **For non-technical users:** View information about a specific stock, bond, or asset.
    """
    try:
        service = AssetService(db)
        asset = service.get_asset(asset_id)
        if not asset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "technical": f"Asset {asset_id} not found",
                    "user_friendly": "This asset doesn't exist. It may have been removed."
                }
            )
        return asset
    except HTTPException:
        raise
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="retrieving asset", endpoint=f"/api/v1/assets/{asset_id}", method="GET")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.post("", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def create_asset(
    asset: AssetCreate,
    db: Session = Depends(get_db)
):
    """
    Add a new asset to monitor.

    **For non-technical users:** Start monitoring a new stock, bond, or asset.
    Enter the ticker symbol (like AAPL for Apple) and select which data source to use.
    """
    try:
        service = AssetService(db)
        return service.create_asset(asset)
    except ValueError as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="adding asset", endpoint="/api/v1/assets", method="POST", request_data=asset.dict())
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="adding asset", endpoint="/api/v1/assets", method="POST", request_data=asset.dict())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.post("/bulk", response_model=AssetBulkResponse)
async def create_assets_bulk(
    bulk_create: AssetBulkCreate,
    db: Session = Depends(get_db)
):
    """
    Add multiple assets at once.

    **For non-technical users:** Upload a list of stocks or assets to monitor.
    The system will try to add each one and tell you which ones succeeded and which failed.
    """
    try:
        service = AssetService(db)
        return service.create_assets_bulk(bulk_create.assets)
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="adding multiple assets", endpoint="/api/v1/assets/bulk", method="POST", request_data={"asset_count": len(bulk_create.assets)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.put("/{asset_id}", response_model=AssetResponse)
async def update_asset(
    asset_id: int,
    asset_update: AssetUpdate,
    db: Session = Depends(get_db)
):
    """
    Update an existing asset.

    **For non-technical users:** Modify the settings for a stock or asset you're monitoring.
    You can change the liquidity alert threshold or enable/disable monitoring.
    """
    try:
        service = AssetService(db)
        updated = service.update_asset(asset_id, asset_update)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "technical": f"Asset {asset_id} not found",
                    "user_friendly": "This asset doesn't exist. It may have been removed."
                }
            )
        return updated
    except HTTPException:
        raise
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="updating asset", endpoint=f"/api/v1/assets/{asset_id}", method="PUT", request_data=asset_update.dict())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    asset_id: int,
    db: Session = Depends(get_db)
):
    """
    Remove an asset from monitoring.

    **For non-technical users:** Stop monitoring a stock or asset.
    This won't delete historical data, but will stop collecting new data for it.
    """
    try:
        service = AssetService(db)
        deleted = service.delete_asset(asset_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "technical": f"Asset {asset_id} not found",
                    "user_friendly": "This asset doesn't exist. It may have already been removed."
                }
            )
    except HTTPException:
        raise
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="removing asset", endpoint=f"/api/v1/assets/{asset_id}", method="DELETE")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )
