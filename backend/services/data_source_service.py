"""Business logic for data source management."""

from sqlalchemy.orm import Session
from typing import List, Optional
import logging

from models.data_source import DataSource
from schemas.data_source import (
    DataSourceCreate,
    DataSourceUpdate,
    DataSourceTestRequest,
    DataSourceTestResponse
)

logger = logging.getLogger(__name__)


from services.secrets_service import SecretsService

class DataSourceService:
    """Service for managing data sources."""

    def __init__(self, db: Session):
        self.db = db
        self.secrets_service = SecretsService()

    def list_data_sources(self, enabled_only: bool = False) -> List[DataSource]:
        """List all data sources."""
        query = self.db.query(DataSource)
        if enabled_only:
            query = query.filter(DataSource.enabled == True)
        return query.order_by(DataSource.created_at.desc()).all()

    def get_data_source(self, data_source_id: int) -> Optional[DataSource]:
        """Get a specific data source by ID."""
        db_data_source = self.db.query(DataSource).filter(DataSource.id == data_source_id).first()
        if db_data_source and db_data_source.config.get("api_key_vault_ref"):
            try:
                api_key = self.secrets_service.get_secret(db_data_source.config["api_key_vault_ref"], "api_key")
                db_data_source.config["api_key"] = api_key
            except Exception as e:
                logger.error(f"Failed to retrieve secret for data source {db_data_source.id}: {e}")
        return db_data_source

    def create_data_source(self, data_source: DataSourceCreate) -> DataSource:
        """Create a new data source."""
        # Check for duplicate name
        existing = self.db.query(DataSource).filter(DataSource.name == data_source.name).first()
        if existing:
            raise ValueError(f"Data source with name '{data_source.name}' already exists")

        # Validate plugin type
        valid_plugins = ["yfinance", "fred", "alpha_vantage", "csv", "custom_api"]
        if data_source.plugin_type not in valid_plugins:
            raise ValueError(f"Invalid plugin type. Must be one of: {', '.join(valid_plugins)}")

        config = data_source.config.copy()
        if "api_key" in config:
            api_key = config.pop("api_key")
            secret_path = f"beacon/datasource/{data_source.name}/api_key"
            self.secrets_service.set_secret(secret_path, {"api_key": api_key})
            config["api_key_vault_ref"] = secret_path

        db_data_source = DataSource(
            name=data_source.name,
            plugin_type=data_source.plugin_type,
            config=config,
            description=data_source.description,
            enabled=data_source.enabled,
            status="active"
        )

        self.db.add(db_data_source)
        self.db.commit()
        self.db.refresh(db_data_source)

        logger.info(f"Created data source: {data_source.name} (type: {data_source.plugin_type})")
        return db_data_source

    def update_data_source(self, data_source_id: int, update: DataSourceUpdate) -> Optional[DataSource]:
        """Update an existing data source."""
        db_data_source = self.get_data_source(data_source_id)
        if not db_data_source:
            return None

        # Update fields if provided
        if update.name is not None:
            # Check for duplicate name (excluding current record)
            existing = (
                self.db.query(DataSource)
                .filter(DataSource.name == update.name, DataSource.id != data_source_id)
                .first()
            )
            if existing:
                raise ValueError(f"Data source with name '{update.name}' already exists")
            db_data_source.name = update.name

        if update.plugin_type is not None:
            db_data_source.plugin_type = update.plugin_type
        if update.config is not None:
            config = update.config.copy()
            if "api_key" in config:
                api_key = config.pop("api_key")
                secret_path = f"beacon/datasource/{db_data_source.name}/api_key"
                self.secrets_service.set_secret(secret_path, {"api_key": api_key})
                config["api_key_vault_ref"] = secret_path
            db_data_source.config = config
        if update.description is not None:
            db_data_source.description = update.description
        if update.enabled is not None:
            db_data_source.enabled = update.enabled
            if not update.enabled:
                db_data_source.status = "disabled"

        self.db.commit()
        self.db.refresh(db_data_source)

        logger.info(f"Updated data source: {db_data_source.name}")
        return db_data_source

    def delete_data_source(self, data_source_id: int) -> bool:
        """Delete a data source."""
        db_data_source = self.get_data_source(data_source_id)
        if not db_data_source:
            return False

        self.db.delete(db_data_source)
        self.db.commit()

        logger.info(f"Deleted data source: {db_data_source.name}")
        return True

    def test_data_source(self, test_request: DataSourceTestRequest) -> DataSourceTestResponse:
        """Test a data source configuration."""
        try:
            # Import plugin system
            from plugins.base import get_plugin

            # Get the appropriate plugin
            plugin_class = get_plugin(test_request.plugin_type)
            if not plugin_class:
                return DataSourceTestResponse(
                    success=False,
                    message=f"Unknown plugin type: {test_request.plugin_type}"
                )

            # Instantiate and test
            plugin = plugin_class(test_request.config)
            result = plugin.test_connection()

            if result["success"]:
                return DataSourceTestResponse(
                    success=True,
                    message="Connection successful! Data source is working correctly.",
                    details=result.get("details")
                )
            else:
                return DataSourceTestResponse(
                    success=False,
                    message=f"Connection failed: {result.get('message', 'Unknown error')}",
                    details=result.get("details")
                )

        except Exception as e:
            logger.error(f"Error testing data source: {e}")
            return DataSourceTestResponse(
                success=False,
                message=f"Test failed: {str(e)}"
            )
