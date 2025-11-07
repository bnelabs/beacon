"""Alert rule model for customizable alerting system."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, JSON, Float
from sqlalchemy.sql import func
from backend.database import Base


class AlertRule(Base):
    """
    Stores user-defined alert rules for monitoring various metrics.

    Rules can monitor:
    - Data quality scores
    - Model performance
    - Job success rates
    - System health metrics
    """
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, index=True)

    # Rule identification
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=False)  # data_quality, model_performance, job_execution, system_health

    # Rule configuration
    metric_type = Column(String(100), nullable=False)  # quality_score, success_rate, rmse, execution_time, etc.
    condition_operator = Column(String(20), nullable=False)  # lt, lte, gt, gte, eq, neq
    threshold_value = Column(Float, nullable=False)

    # Time window for evaluation
    evaluation_window_minutes = Column(Integer, default=60)  # Check over last X minutes
    evaluation_frequency_minutes = Column(Integer, default=15)  # How often to check

    # Status
    is_enabled = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)  # Can be temporarily disabled by system

    # Notification settings
    notification_priority = Column(String(20), default='medium')  # low, medium, high, urgent
    notification_message_template = Column(Text, nullable=True)  # Custom message template

    # Metadata
    rule_config = Column(JSON, nullable=True)  # Additional configuration
    last_triggered_at = Column(DateTime(timezone=True), nullable=True)
    last_evaluated_at = Column(DateTime(timezone=True), nullable=True)
    trigger_count = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_by = Column(String(100), default='system')

    def __repr__(self):
        return f"<AlertRule(id={self.id}, name='{self.name}', metric='{self.metric_type}', enabled={self.is_enabled})>"
