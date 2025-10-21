"""Business logic for model registry management."""

from sqlalchemy.orm import Session
from typing import List, Optional

from models.model import Model, ModelVersion
from schemas.model import ModelResponse, ModelVersionResponse

class ModelService:
    """Service for managing models and model versions."""

    def __init__(self, db: Session):
        self.db = db

    def list_model_versions(self) -> List[ModelVersion]:
        """List all model versions."""
        return self.db.query(ModelVersion).all()

    def promote_model_version(self, version_id: int) -> Optional[ModelVersion]:
        """Promote a model version to production."""
        db_model_version = self.db.query(ModelVersion).filter(ModelVersion.id == version_id).first()
        if not db_model_version:
            return None

        # Deactivate any other production models for this model
        self.db.query(ModelVersion).filter(
            ModelVersion.model_id == db_model_version.model_id,
            ModelVersion.stage == "Production"
        ).update({"stage": "Staging"})

        db_model_version.stage = "Production"
        self.db.commit()
        self.db.refresh(db_model_version)
        return db_model_version

    def get_model_drift_report(self, version_id: int) -> Optional[dict]:
        """Retrieve the data drift report for a specific model version."""
        db_model_version = self.db.query(ModelVersion).filter(ModelVersion.id == version_id).first()
        if not db_model_version:
            return None

        # Assuming the drift report is stored in the model_version.metrics field
        # This is a simplification, in a real scenario, it might be stored as a separate artifact
        return db_model_version.metrics.get("drift_report")
