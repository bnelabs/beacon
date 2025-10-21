"""Service for interacting with a secrets management vault."""

import os
import hvac
import logging

logger = logging.getLogger(__name__)

class SecretsService:
    """Service for managing secrets in HashiCorp Vault."""

    def __init__(self):
        self.vault_addr = os.getenv("VAULT_ADDR")
        self.vault_token = os.getenv("VAULT_TOKEN")
        
        if not self.vault_addr or not self.vault_token:
            raise ValueError("VAULT_ADDR and VAULT_TOKEN must be set in the environment.")

        self.client = hvac.Client(url=self.vault_addr, token=self.vault_token)
        if not self.client.is_authenticated():
            raise ConnectionError("Failed to authenticate with Vault.")

    def get_secret(self, secret_path: str, secret_key: str) -> str:
        """Retrieve a secret from the vault."""
        try:
            response = self.client.secrets.kv.v2.read_secret_version(path=secret_path)
            return response['data']['data'][secret_key]
        except Exception as e:
            logger.error(f"Failed to retrieve secret from {secret_path}: {e}")
            raise

    def set_secret(self, secret_path: str, secret_data: dict):
        """Set a secret in the vault."""
        try:
            self.client.secrets.kv.v2.create_or_update_secret(
                path=secret_path,
                secret=secret_data,
            )
        except Exception as e:
            logger.error(f"Failed to set secret at {secret_path}: {e}")
            raise
