"""API routes for scenario analysis."""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
import pandas as pd
import torch

from services.error_logger import ErrorLogger
from auth import fastapi_users, current_active_user
from models.user import User

router = APIRouter()

@router.post("/run")
async def run_scenario(
    model_version_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_active_user)
):
    """Run a scenario analysis with uploaded data."""
    try:
        # 1. Load model
        model_version = db.query(ModelVersion).filter(ModelVersion.id == model_version_id).first()
        if not model_version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Model version not found."
            )

        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        model = torch.load(model_version.model_path, map_location=device)
        model.eval()

        # 2. Load data from uploaded CSV
        df = pd.read_csv(file.file)

        # 3. Run inference
        predictions = model.predict(df)

        return predictions.to_dict(orient="records")

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
