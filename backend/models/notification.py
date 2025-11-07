"""Notification model for alerts and system events."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, JSON
from sqlalchemy.sql import func
from backend.database import Base


class Notification(Base):
    """
    Stores system notifications and alerts.

    Notifications are triggered by important events like:
    - High risk scores detected
    - Model training completed
    - Data quality issues
    - Job failures
    """
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)

    # Notification content
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    notification_type = Column(String(50), nullable=False)  # info, warning, error, success, alert
    category = Column(String(50), nullable=True)  # model, data, job, system, risk

    # Priority and urgency
    priority = Column(String(20), nullable=False, default='medium')  # low, medium, high, critical
    is_urgent = Column(Boolean, default=False)

    # Status
    is_read = Column(Boolean, default=False)
    is_dismissed = Column(Boolean, default=False)
    is_archived = Column(Boolean, default=False)

    # Action links
    action_url = Column(String(500), nullable=True)
    action_label = Column(String(100), nullable=True)

    # Related entities
    related_entity_type = Column(String(50), nullable=True)  # job, model, datasource
    related_entity_id = Column(Integer, nullable=True)

    # Extra data (JSON)
    extra_data = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=True)
    dismissed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<Notification(id={self.id}, title='{self.title}', type='{self.notification_type}', priority='{self.priority}')>"
