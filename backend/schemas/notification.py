"""Pydantic schemas for notifications."""

from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Dict, Any
from datetime import datetime


class NotificationBase(BaseModel):
    """Base notification schema."""
    title: str = Field(..., max_length=200)
    message: str
    notification_type: str = Field(..., description="Type: info, warning, error, success, alert")
    category: Optional[str] = Field(None, description="Category: model, data, job, system, risk")
    priority: str = Field(default='medium', description="Priority: low, medium, high, critical")
    is_urgent: bool = Field(default=False)
    action_url: Optional[str] = Field(None, max_length=500)
    action_label: Optional[str] = Field(None, max_length=100)
    related_entity_type: Optional[str] = Field(None, max_length=50)
    related_entity_id: Optional[int] = None
    extra_data: Optional[Dict[str, Any]] = None
    expires_at: Optional[datetime] = None


class NotificationCreate(NotificationBase):
    """Schema for creating a notification."""
    pass


class NotificationUpdate(BaseModel):
    """Schema for updating a notification."""
    is_read: Optional[bool] = None
    is_dismissed: Optional[bool] = None
    is_archived: Optional[bool] = None


class NotificationResponse(NotificationBase):
    """Schema for notification response."""
    id: int
    is_read: bool
    is_dismissed: bool
    is_archived: bool
    created_at: datetime
    read_at: Optional[datetime] = None
    dismissed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    """Schema for notification list response."""
    notifications: list[NotificationResponse]
    total: int
    unread_count: int


class NotificationStats(BaseModel):
    """Notification statistics."""
    total: int
    unread: int
    by_priority: Dict[str, int]
    by_category: Dict[str, int]
    urgent: int
