"""Business logic for system configuration."""

from sqlalchemy.orm import Session
import yaml
import os
import logging
import psutil
import torch

from schemas.config import (
    SystemConfigResponse,
    ModelParamsUpdate,
    DataParamsUpdate,
    TrainingParamsUpdate
)

logger = logging.getLogger(__name__)

# Path to config file
# In Docker, config is mounted at /app/configs/config.yaml
CONFIG_PATH = os.getenv("CONFIG_PATH", "/app/configs/config.yaml")


from services.configuration_service import ConfigurationService

class ConfigService:
    """Service for managing system configuration."""

    def __init__(self, db: Session):
        self.db = db
        self.config_service = ConfigurationService(db)

    def get_system_config(self) -> SystemConfigResponse:
        """Get current system configuration."""
        config = self.config_service.get_active_configuration()
        if not config:
            raise ValueError("No active configuration found in the database.")

        config_data = config.config_data

        # Get system information
        memory = psutil.virtual_memory()
        cpu_count = psutil.cpu_count()
        gpu_available = torch.cuda.is_available()
        gpu_count = torch.cuda.device_count() if gpu_available else 0

        return SystemConfigResponse(
            model_params={
                "hidden_dim": config_data.get("model", {}).get("hidden_dim", 128),
                "num_heads": config_data.get("model", {}).get("num_heads", 8),
                "num_layers": config_data.get("model", {}).get("num_layers", 3),
                "dropout": config_data.get("model", {}).get("dropout", 0.3),
                "learning_rate": config_data.get("model", {}).get("learning_rate", 0.001)
            },
            data_params={
                "start_date_days": config_data.get("data", {}).get("start_date_days", 7300),
                "look_back": config_data.get("data", {}).get("look_back", 30),
                "correlation_threshold": config_data.get("data", {}).get("correlation_threshold", 0.5),
                "api_rate_limit_seconds": config_data.get("data", {}).get("api_rate_limit_seconds", 2.0)
            },
            training_params={
                "batch_size": config_data.get("training", {}).get("batch_size", 32),
                "num_epochs": config_data.get("training", {}).get("num_epochs", 100),
                "early_stopping_patience": config_data.get("training", {}).get("early_stopping_patience", 10),
                "validation_split": config_data.get("training", {}).get("validation_split", 0.2)
            },
            system_info={
                "cpu_cores": cpu_count,
                "memory_gb": round(memory.total / (1024 ** 3), 2),
                "gpu_available": gpu_available,
                "gpu_count": gpu_count
            }
        )

    def update_model_params(self, params: ModelParamsUpdate) -> SystemConfigResponse:
        """Update model parameters."""
        config = self._load_config()

        if "model" not in config:
            config["model"] = {}

        if params.hidden_dim is not None:
            config["model"]["hidden_dim"] = params.hidden_dim
        if params.num_heads is not None:
            config["model"]["num_heads"] = params.num_heads
        if params.num_layers is not None:
            config["model"]["num_layers"] = params.num_layers
        if params.dropout is not None:
            config["model"]["dropout"] = params.dropout
        if params.learning_rate is not None:
            config["model"]["learning_rate"] = params.learning_rate

        self._save_config(config)
        logger.info(f"Updated model parameters: {params.dict(exclude_none=True)}")

        return self.get_system_config()

    def update_data_params(self, params: DataParamsUpdate) -> SystemConfigResponse:
        """Update data collection parameters."""
        config = self._load_config()

        if "data" not in config:
            config["data"] = {}

        if params.look_back is not None:
            config["data"]["look_back"] = params.look_back
        if params.correlation_threshold is not None:
            config["data"]["correlation_threshold"] = params.correlation_threshold
        if params.api_rate_limit_seconds is not None:
            config["data"]["api_rate_limit_seconds"] = params.api_rate_limit_seconds

        self._save_config(config)
        logger.info(f"Updated data parameters: {params.dict(exclude_none=True)}")

        return self.get_system_config()

    def update_training_params(self, params: TrainingParamsUpdate) -> SystemConfigResponse:
        """Update training parameters."""
        config = self._load_config()

        if "training" not in config:
            config["training"] = {}

        if params.batch_size is not None:
            config["training"]["batch_size"] = params.batch_size
        if params.num_epochs is not None:
            config["training"]["num_epochs"] = params.num_epochs
        if params.early_stopping_patience is not None:
            config["training"]["early_stopping_patience"] = params.early_stopping_patience
        if params.validation_split is not None:
            config["training"]["validation_split"] = params.validation_split

        self._save_config(config)
        logger.info(f"Updated training parameters: {params.dict(exclude_none=True)}")

        return self.get_system_config()
