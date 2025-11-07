"""API routes for alert rules management."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from backend.database import get_db
from backend.models.alert_rule import AlertRule
from backend.schemas.alert_rule import AlertRuleCreate, AlertRuleUpdate, AlertRuleResponse, AlertRuleListResponse
from backend.services.error_logger import ErrorLogger

router = APIRouter()


@router.get("", response_model=AlertRuleListResponse)
async def list_alert_rules(
    enabled_only: bool = False,
    category: str = None,
    db: Session = Depends(get_db)
):
    """List all alert rules."""
    try:
        query = db.query(AlertRule)
        if enabled_only:
            query = query.filter(AlertRule.is_enabled == True)
        if category:
            query = query.filter(AlertRule.category == category)

        rules = query.order_by(AlertRule.created_at.desc()).all()
        return AlertRuleListResponse(rules=rules, total=len(rules))
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="listing alert rules", endpoint="/api/v1/alert-rules", method="GET")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message})


@router.post("", response_model=AlertRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_alert_rule(
    rule: AlertRuleCreate,
    db: Session = Depends(get_db)
):
    """Create new alert rule."""
    try:
        db_rule = AlertRule(**rule.model_dump())
        db.add(db_rule)
        db.commit()
        db.refresh(db_rule)
        return db_rule
    except Exception as e:
        db.rollback()
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="creating alert rule", endpoint="/api/v1/alert-rules", method="POST")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message})


@router.get("/{rule_id}", response_model=AlertRuleResponse)
async def get_alert_rule(rule_id: int, db: Session = Depends(get_db)):
    """Get specific alert rule."""
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"user_friendly": "Alert rule not found"})
    return rule


@router.put("/{rule_id}", response_model=AlertRuleResponse)
async def update_alert_rule(
    rule_id: int,
    rule_update: AlertRuleUpdate,
    db: Session = Depends(get_db)
):
    """Update alert rule."""
    try:
        rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
        if not rule:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"user_friendly": "Alert rule not found"})

        for key, value in rule_update.model_dump(exclude_unset=True).items():
            setattr(rule, key, value)

        db.commit()
        db.refresh(rule)
        return rule
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="updating alert rule", endpoint=f"/api/v1/alert-rules/{rule_id}", method="PUT")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message})


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(rule_id: int, db: Session = Depends(get_db)):
    """Delete alert rule."""
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"user_friendly": "Alert rule not found"})

    db.delete(rule)
    db.commit()
