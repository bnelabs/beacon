"""Custom API plugin for flexible integrations."""

import requests
import pandas as pd
from datetime import datetime
from typing import Dict, Any, List, Optional
import logging

from .base import DataSourcePlugin, register_plugin

logger = logging.getLogger(__name__)


class CustomAPIPlugin(DataSourcePlugin):
    """Plugin for custom REST API integrations."""

    def validate_config(self) -> None:
        """Validate custom API configuration."""
        if not self.config.get('base_url'):
            raise ValueError("API base URL is required")

        # Optional authentication
        auth_type = self.config.get('auth_type', 'none')
        if auth_type == 'api_key' and not self.config.get('api_key'):
            raise ValueError("API key is required when auth_type is 'api_key'")
        elif auth_type == 'bearer' and not self.config.get('bearer_token'):
            raise ValueError("Bearer token is required when auth_type is 'bearer'")

    def test_connection(self) -> Dict[str, Any]:
        """Test custom API connectivity."""
        try:
            base_url = self.config['base_url']
            test_endpoint = self.config.get('test_endpoint', '/health')
            url = f"{base_url.rstrip('/')}{test_endpoint}"

            headers = self._get_headers()

            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                return {
                    "success": True,
                    "message": f"Successfully connected to custom API",
                    "details": {
                        "status_code": response.status_code,
                        "url": url
                    }
                }
            else:
                return {
                    "success": False,
                    "message": f"API returned status code {response.status_code}"
                }

        except requests.exceptions.Timeout:
            return {
                "success": False,
                "message": "Connection timeout. Please check the API URL and your internet connection."
            }
        except requests.exceptions.ConnectionError:
            return {
                "success": False,
                "message": "Could not connect to API. Please check the base URL."
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}"
            }

    def _get_headers(self) -> Dict[str, str]:
        """Build request headers based on auth configuration."""
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        auth_type = self.config.get('auth_type', 'none')

        if auth_type == 'api_key':
            key_name = self.config.get('api_key_header', 'X-API-Key')
            headers[key_name] = self.config['api_key']
        elif auth_type == 'bearer':
            headers['Authorization'] = f"Bearer {self.config['bearer_token']}"

        return headers

    def fetch_asset_data(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Fetch asset data from custom API.

        Expected API response format (JSON):
        {
            "data": [
                {
                    "date": "2024-01-01",
                    "symbol": "AAPL",
                    "open": 100.0,
                    "high": 105.0,
                    "low": 99.0,
                    "close": 104.0,
                    "volume": 1000000
                }
            ]
        }
        """
        try:
            base_url = self.config['base_url']
            asset_endpoint = self.config.get('asset_endpoint', '/assets')
            url = f"{base_url.rstrip('/')}{asset_endpoint}"

            headers = self._get_headers()

            params = {
                'symbols': ','.join(symbols),
                'start_date': start_date.strftime('%Y-%m-%d'),
                'end_date': end_date.strftime('%Y-%m-%d')
            }

            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()

            # Extract data array
            if 'data' in data:
                records = data['data']
            elif isinstance(data, list):
                records = data
            else:
                logger.error("Unexpected API response format")
                return None

            if not records:
                logger.warning("API returned no data")
                return None

            # Convert to DataFrame
            df = pd.DataFrame(records)

            # Normalize column names
            column_mapping = {
                'date': 'Date',
                'symbol': 'Asset',
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume'
            }
            df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})

            # Ensure required columns exist
            required_cols = ['Date', 'Asset', 'Open', 'High', 'Low', 'Close', 'Volume']
            if not all(col in df.columns for col in required_cols):
                logger.error(f"API response missing required columns. Got: {list(df.columns)}")
                return None

            # Convert types
            df['Date'] = pd.to_datetime(df['Date'])
            for col in ['Open', 'High', 'Low', 'Close']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce').astype('Int64')

            df = df[required_cols]

            logger.info(f"Fetched {len(df)} rows from custom API")
            return df

        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error from custom API: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching from custom API: {e}")
            return None

    def fetch_indicator_data(
        self,
        indicator_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Fetch indicator data from custom API.

        Expected API response format (JSON):
        {
            "data": [
                {"date": "2024-01-01", "value": 23000},
                {"date": "2024-02-01", "value": 23500}
            ]
        }
        """
        try:
            base_url = self.config['base_url']
            indicator_endpoint = self.config.get('indicator_endpoint', '/indicators')
            url = f"{base_url.rstrip('/')}{indicator_endpoint}/{indicator_id}"

            headers = self._get_headers()

            params = {
                'start_date': start_date.strftime('%Y-%m-%d'),
                'end_date': end_date.strftime('%Y-%m-%d')
            }

            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()

            # Extract data array
            if 'data' in data:
                records = data['data']
            elif isinstance(data, list):
                records = data
            else:
                logger.error("Unexpected API response format")
                return None

            if not records:
                logger.warning("API returned no indicator data")
                return None

            # Convert to DataFrame
            df = pd.DataFrame(records)

            # Normalize column names
            df = df.rename(columns={'date': 'Date', 'value': 'Value'})

            # Ensure required columns
            if 'Date' not in df.columns or 'Value' not in df.columns:
                logger.error(f"API response missing Date or Value columns. Got: {list(df.columns)}")
                return None

            # Convert types
            df['Date'] = pd.to_datetime(df['Date'])
            df['Value'] = pd.to_numeric(df['Value'], errors='coerce')

            df = df[['Date', 'Value']].sort_values('Date')

            logger.info(f"Fetched {len(df)} indicator observations from custom API")
            return df

        except Exception as e:
            logger.error(f"Error fetching indicator from custom API: {e}")
            return None

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Get custom API configuration schema."""
        return {
            "base_url": {
                "type": "string",
                "required": True,
                "label": "API Base URL",
                "help": "Base URL of your API (e.g., https://api.example.com/v1)",
                "placeholder": "https://api.example.com/v1"
            },
            "auth_type": {
                "type": "select",
                "required": False,
                "default": "none",
                "label": "Authentication Type",
                "options": ["none", "api_key", "bearer"],
                "help": "How to authenticate with the API"
            },
            "api_key": {
                "type": "string",
                "required": False,
                "label": "API Key",
                "help": "Your API key (only if auth_type is 'api_key')",
                "secret": True
            },
            "api_key_header": {
                "type": "string",
                "required": False,
                "default": "X-API-Key",
                "label": "API Key Header Name",
                "help": "HTTP header name for API key (default: X-API-Key)"
            },
            "bearer_token": {
                "type": "string",
                "required": False,
                "label": "Bearer Token",
                "help": "Your bearer token (only if auth_type is 'bearer')",
                "secret": True
            },
            "test_endpoint": {
                "type": "string",
                "required": False,
                "default": "/health",
                "label": "Test Endpoint",
                "help": "Endpoint to test connectivity"
            },
            "asset_endpoint": {
                "type": "string",
                "required": False,
                "default": "/assets",
                "label": "Asset Data Endpoint",
                "help": "Endpoint to fetch asset price data"
            },
            "indicator_endpoint": {
                "type": "string",
                "required": False,
                "default": "/indicators",
                "label": "Indicator Data Endpoint",
                "help": "Endpoint to fetch indicator data"
            }
        }

    @classmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        """Get plugin metadata."""
        return {
            "name": "Custom API",
            "description": "Connect to your own REST API or any third-party API with a custom integration",
            "version": "1.0.0",
            "author": "Liquidity Monitor",
            "free": True,
            "registration_required": False,
            "registration_url": None,
            "data_types": ["stocks", "bonds", "commodities", "indicators", "custom"],
            "flexible": True
        }


# Register the plugin
register_plugin("custom_api", CustomAPIPlugin)
