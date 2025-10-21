"""Business logic for configuration management."""

from sqlalchemy.orm import Session
from typing import List, Optional

from models.configuration import Configuration
from schemas.config import ConfigurationCreate, ConfigurationUpdate

class ConfigurationService:
    """Service for managing configurations."""

    def __init__(self, db: Session):
        self.db = db

    def list_configurations(self) -> List[Configuration]:
        """List all configurations."""
        return self.db.query(Configuration).all()

    def get_configuration(self, config_id: int) -> Optional[Configuration]:
        """Get a specific configuration by ID."""
        return self.db.query(Configuration).filter(Configuration.id == config_id).first()

    def get_active_configuration(self) -> Optional[Configuration]:
        """Get the active configuration."""
        return self.db.query(Configuration).filter(Configuration.is_active == True).first()

    def create_configuration(self, config: ConfigurationCreate) -> Configuration:
        """Create a new configuration."""
        db_config = Configuration(
            name=config.name,
            config_data=config.config_data,
            created_by=config.created_by,
        )
        self.db.add(db_config)
        self.db.commit()
        self.db.refresh(db_config)
        return db_config

    def update_configuration(
        self, config_id: int, update: ConfigurationUpdate
    ) -> Optional[Configuration]:
        """Update an existing configuration."""
        db_config = self.get_configuration(config_id)
        if not db_config:
            return None

        if update.config_data is not None:
            db_config.config_data = update.config_data
        if update.is_active is not None:
            if update.is_active:
                # Deactivate all other configurations
                self.db.query(Configuration).filter(Configuration.id != config_id).update({"is_active": False})
            db_config.is_active = update.is_active

        self.db.commit()
        self.db.refresh(db_config)
        return db_config
