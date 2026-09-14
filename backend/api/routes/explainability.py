"""Model-output transparency endpoints — honest by construction.

An earlier version of this module returned ``"eu_ai_act": "Compliant"``,
``"explainability_method": "Gradient-based feature attribution + Attention
weights"``, ``"uncertainty_quantification": "Monte Carlo Dropout"`` and a
summary asserting that "all predictions include confidence intervals and
feature attributions". All three methods had been **removed** from the codebase
in an earlier review round (the attribution routine presented gradient*input
scaled by uniform attention as SHAP; the dropout intervals described a
different network than the one scoring), and confidence intervals are
reported as unavailable until conformal calibration lands. The endpoint was
asserting the exact things the rest of the repository had repudiated.

What these endpoints serve now is what actually exists:

* the saved model-output report (the engine writes one per prediction job),
* attribution status ``not_computed`` with the reason and the module that
  will provide it once a liability network and a game value are available
  (``backend/modules/engine/subgraphx.py``),
* uncertainty status ``not_calibrated`` with the calibration roadmap pointer,
* the metrics the job really recorded,
* per-institution profiles with their scores in the model's own units --
  never multiplied into percentages, never defaulted to zero when absent.

No compliance claim is made anywhere in this module. Compliance is an
audit outcome, not a response field.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import logging
from pathlib import Path

from backend.database import get_db
from backend.models.job import Job

logger = logging.getLogger(__name__)

router = APIRouter()

_ATTRIBUTION_NOT_COMPUTED = {
    "status": "not_computed",
    "reason": (
        "Local feature attribution requires a network to explain and a game "
        "value over it (e.g. the clearing shortfall on the induced "
        "subnetwork). This job carries neither, and no per-feature scalar is "
        "substituted: the removed gradient*attention routine mispresented "
        "itself as SHAP, and repeating that under a new name would repeat the "
        "defect."
    ),
    "provider_when_available": "backend.modules.engine.subgraphx",
}

_UNCERTAINTY_NOT_CALIBRATED = {
    "status": "not_calibrated",
    "reason": (
        "Calibrated intervals require a held-out calibration set per source "
        "(split conformal). Until then the confidence fields are null rather "
        "than an interval from a method that described a different network."
    ),
    "roadmap": "docs/QUANT_REVIEW_2026-09.md (Phase 2)",
}


@router.get("/{job_id}/explanation")
async def get_model_explanation(
    job_id: int,
    db: Session = Depends(get_db),
):
    """
    Serve the transparency card for a training or prediction job.

    Returns what the job actually produced: its saved model-output report,
    the metrics it recorded, and explicit not-computed / not-calibrated
    statuses for attribution and uncertainty. It makes no regulatory
    compliance claim; see the module docstring for why the previous version's
    claims were removed.
    """
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.job_type not in ["training", "prediction"]:
        raise HTTPException(status_code=400, detail="Explanations only available for training/prediction jobs")

    result = job.result or {}

    explanation_path = Path(f"/app/data/jobs/{job_id}/explanation_report.txt")
    if explanation_path.exists():
        explanation_report = explanation_path.read_text(encoding="utf-8")
    else:
        explanation_report = result.get(
            "explanation_report",
            "No model-output report was saved for this job.",
        )

    metrics = {
        key: result.get(key)
        for key in ("test_r2", "test_mae", "test_rmse", "best_val_loss", "epochs_trained")
        if result.get(key) is not None
    }

    return {
        "job_id": job_id,
        "job_type": job.job_type,
        "model_type": result.get("model_type"),
        "explanation_report": explanation_report,
        "attribution": _ATTRIBUTION_NOT_COMPUTED,
        "uncertainty": _UNCERTAINTY_NOT_CALIBRATED,
        "model_metrics": metrics,
        "feature_importances": result.get("feature_importances") or {},
        "compliance": {
            "claims": "none",
            "note": (
                "Regulatory compliance is an audit outcome and is not asserted "
                "by this API. The previous 'EU AI Act Compliant' field was "
                "removed because the methods it named no longer exist here."
            ),
        },
    }


@router.get("/{job_id}/bank-risks")
async def get_bank_risks(
    job_id: int,
    bank_id: Optional[str] = Query(None, description="Filter by specific bank"),
    risk_level: Optional[str] = Query(None, description="Filter by risk level (low, medium, high, critical, uncalibrated)"),
    db: Session = Depends(get_db),
):
    """
    Per-institution profiles from a multi-bank prediction job.

    Scores are reported in the model's own standardized units with the level
    band the analyzer assigned; nothing is converted to a percentage and
    absent measurements stay null.
    """
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = job.result or {}
    per_bank_risks = result.get("per_bank_risks", {})

    if not per_bank_risks:
        raise HTTPException(status_code=404, detail="No per-bank risk data available for this job")

    if bank_id:
        if bank_id not in per_bank_risks:
            raise HTTPException(status_code=404, detail=f"Bank {bank_id} not found in results")
        per_bank_risks = {bank_id: per_bank_risks[bank_id]}

    if risk_level:
        per_bank_risks = {
            bid: profile for bid, profile in per_bank_risks.items()
            if profile.get("risk_level") == risk_level
        }

    formatted_risks: List[dict] = []
    for bid, profile in per_bank_risks.items():
        formatted_risks.append({
            "bank_id": bid,
            "bank_name": profile.get("bank_name"),
            # The analyzer's score, in its own units, with the band it
            # assigned. Not a percentage: see docs/QUANT_REVIEW_2026-09.md F6.
            "risk_score": profile.get("risk_score"),
            "risk_level": profile.get("risk_level"),
            "score_units": "standardized one-step-ahead indicator prediction",
            "systemic_importance": profile.get("systemic_importance"),
            "systemic_importance_method": profile.get("systemic_importance_method"),
            "network_position": profile.get("network_position"),
            "gross_liabilities": profile.get("gross_liabilities"),
            "gross_claims": profile.get("gross_claims"),
            "confidence_lower": profile.get("confidence_lower"),
            "confidence_upper": profile.get("confidence_upper"),
            "confidence_method": profile.get("confidence_method"),
            "top_vulnerabilities": profile.get("top_vulnerabilities") or [],
            "recommendations": profile.get("recommendations") or [],
        })

    return {
        "job_id": job_id,
        "count": len(formatted_risks),
        "banks": formatted_risks,
        "semantics": {
            "risk_score": (
                "standardized model output; the band is the analyzer's "
                "thresholding of it, pending calibration (docs/"
                "QUANT_REVIEW_2026-09.md, Phase 2)"
            ),
            "confidence_bounds": "null until conformal calibration is wired",
        },
    }
