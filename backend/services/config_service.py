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


class ConfigService:
    """Service for managing system configuration."""

    def __init__(self, db: Session):
        self.db = db

    def _load_config(self) -> dict:
        """Load configuration from YAML file."""
        try:
            with open(CONFIG_PATH, "r") as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            raise

    def _save_config(self, config: dict):
        """Save configuration to YAML file."""
        try:
            with open(CONFIG_PATH, "w") as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)
            logger.info("Configuration saved successfully")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            raise

    def get_system_config(self) -> SystemConfigResponse:
        """Get current system configuration."""
        config = self._load_config()

        # Get system information
        memory = psutil.virtual_memory()
        cpu_count = psutil.cpu_count()
        gpu_available = torch.cuda.is_available()
        gpu_count = torch.cuda.device_count() if gpu_available else 0

        return SystemConfigResponse(
            model_params={
                "hidden_dim": config.get("model", {}).get("hidden_dim", 128),
                "num_heads": config.get("model", {}).get("num_heads", 8),
                "num_layers": config.get("model", {}).get("num_layers", 3),
                "dropout": config.get("model", {}).get("dropout", 0.3),
                "learning_rate": config.get("model", {}).get("learning_rate", 0.001)
            },
            data_params={
                "start_date_days": config.get("data", {}).get("start_date_days", 7300),
                "look_back": config.get("data", {}).get("look_back", 30),
                "correlation_threshold": config.get("data", {}).get("correlation_threshold", 0.5),
                "api_rate_limit_seconds": config.get("data", {}).get("api_rate_limit_seconds", 2.0)
            },
            training_params={
                "batch_size": config.get("training", {}).get("batch_size", 32),
                "num_epochs": config.get("training", {}).get("num_epochs", 100),
                "early_stopping_patience": config.get("training", {}).get("early_stopping_patience", 10),
                "validation_split": config.get("training", {}).get("validation_split", 0.2)
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
