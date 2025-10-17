"""Business logic for asset management."""

from sqlalchemy.orm import Session
from typing import List, Optional
import logging

from models.asset import Asset
from schemas.asset import AssetCreate, AssetUpdate, AssetBulkResponse

logger = logging.getLogger(__name__)


class AssetService:
    """Service for managing assets."""

    def __init__(self, db: Session):
        self.db = db

    def list_assets(
        self,
        enabled_only: bool = False,
        asset_type: Optional[str] = None,
        sector: Optional[str] = None,
        region: Optional[str] = None
    ) -> List[Asset]:
        """List all assets with optional filtering."""
        query = self.db.query(Asset)

        if enabled_only:
            query = query.filter(Asset.enabled == True)
        if asset_type:
            query = query.filter(Asset.asset_type == asset_type)
        if sector:
            query = query.filter(Asset.sector == sector)
        if region:
            query = query.filter(Asset.region == region)

        return query.order_by(Asset.symbol).all()

    def get_asset(self, asset_id: int) -> Optional[Asset]:
        """Get a specific asset by ID."""
        return self.db.query(Asset).filter(Asset.id == asset_id).first()

    def create_asset(self, asset: AssetCreate) -> Asset:
        """Create a new asset."""
        # Check for duplicate symbol
        existing = self.db.query(Asset).filter(Asset.symbol == asset.symbol).first()
        if existing:
            raise ValueError(f"Asset with symbol '{asset.symbol}' already exists")

        # Verify data source exists
        from models.data_source import DataSource
        data_source = self.db.query(DataSource).filter(DataSource.id == asset.data_source_id).first()
        if not data_source:
            raise ValueError(f"Data source with ID {asset.data_source_id} not found")

        db_asset = Asset(
            symbol=asset.symbol,
            name=asset.name,
            asset_type=asset.asset_type,
            sector=asset.sector,
            region=asset.region,
            liquidity_threshold=asset.liquidity_threshold,
            enabled=asset.enabled,
            data_source_id=asset.data_source_id
        )

        self.db.add(db_asset)
        self.db.commit()
        self.db.refresh(db_asset)

        logger.info(f"Created asset: {asset.symbol}")
        return db_asset

    def create_assets_bulk(self, assets: List[AssetCreate]) -> AssetBulkResponse:
        """Create multiple assets at once."""
        created = 0
        failed = 0
        errors = []

        for asset in assets:
            try:
                self.create_asset(asset)
                created += 1
            except Exception as e:
                failed += 1
                errors.append(f"{asset.symbol}: {str(e)}")
                logger.warning(f"Failed to create asset {asset.symbol}: {e}")

        logger.info(f"Bulk creation: {created} created, {failed} failed")
        return AssetBulkResponse(created=created, failed=failed, errors=errors)

    def update_asset(self, asset_id: int, update: AssetUpdate) -> Optional[Asset]:
        """Update an existing asset."""
        db_asset = self.get_asset(asset_id)
        if not db_asset:
            return None

        # Update fields if provided
        if update.symbol is not None:
            # Check for duplicate symbol (excluding current record)
            existing = (
                self.db.query(Asset)
                .filter(Asset.symbol == update.symbol, Asset.id != asset_id)
                .first()
            )
            if existing:
                raise ValueError(f"Asset with symbol '{update.symbol}' already exists")
            db_asset.symbol = update.symbol

        if update.name is not None:
            db_asset.name = update.name
        if update.asset_type is not None:
            db_asset.asset_type = update.asset_type
        if update.sector is not None:
            db_asset.sector = update.sector
        if update.region is not None:
            db_asset.region = update.region
        if update.liquidity_threshold is not None:
            db_asset.liquidity_threshold = update.liquidity_threshold
        if update.enabled is not None:
            db_asset.enabled = update.enabled
        if update.data_source_id is not None:
            # Verify new data source exists
            from models.data_source import DataSource
            data_source = self.db.query(DataSource).filter(DataSource.id == update.data_source_id).first()
            if not data_source:
                raise ValueError(f"Data source with ID {update.data_source_id} not found")
            db_asset.data_source_id = update.data_source_id

        self.db.commit()
        self.db.refresh(db_asset)

        logger.info(f"Updated asset: {db_asset.symbol}")
        return db_asset

    def delete_asset(self, asset_id: int) -> bool:
        """Delete an asset."""
        db_asset = self.get_asset(asset_id)
        if not db_asset:
            return False

        self.db.delete(db_asset)
        self.db.commit()

        logger.info(f"Deleted asset: {db_asset.symbol}")
        return True
