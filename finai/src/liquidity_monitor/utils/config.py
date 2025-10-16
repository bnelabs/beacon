"""Configuration management utilities."""

import os
import yaml
from pathlib import Path
from typing import Dict, Any
from dotenv import load_dotenv


class Config:
    """Configuration manager for the liquidity monitor."""
    
    def __init__(self, config_path: str = None):
        """
        Initialize configuration.
        
        Args:
            config_path: Path to configuration file
        """
        # Load environment variables
        load_dotenv()
        
        # Default config path
        if config_path is None:
            # Determine project root dynamically for utility modules
            # Assuming this file is deep inside src/liquidity_monitor/utils
            project_root = Path(__file__).parent.parent.parent.parent.parent 
            config_path = project_root / "configs" / "config.yaml"
        
        self.config_path = Path(config_path)
        self._config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
        
        with open(self.config_path, "r") as f:
            # Using safe_load handles standard YAML syntax correctly.
            return yaml.safe_load(f)
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value by key.
        
        Args:
            key: Configuration key (supports dot notation, e.g., 'model.hidden_dim')
            default: Default value if key not found
            
        Returns:
            Configuration value
        """
        keys = key.split(".")
        value = self._config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def get_api_key(self, service: str) -> str:
        """
        Get API key from environment variables.
        
        Args:
            service: Service name (e.g., 'FRED', 'SEC')
            
        Returns:
            API key
            
        Raises:
            ValueError: If API key not found
        """
        key = os.getenv(f"{service.upper()}_API_KEY")
        if not key or key == f"your_{service.lower()}_api_key_here":
            raise ValueError(f"{service} API key not found in environment variables or is set to default placeholder")
        return key
    
    @property
    def data(self) -> Dict[str, Any]:
        """Get data configuration section."""
        return self._config.get("data", {})
    
    @property
    def model(self) -> Dict[str, Any]:
        """Get model configuration section."""
        return self._config.get("model", {})
    
    @property
    def simulation(self) -> Dict[str, Any]:
        """Get simulation configuration section."""
        return self._config.get("simulation", {})
    
    @property
    def funds(self) -> Dict[str, Any]:
        """Get funds configuration section."""
        return self._config.get("funds", {})
    
    def reload(self):
        """Reload configuration from file."""
        self._config = self._load_config()
