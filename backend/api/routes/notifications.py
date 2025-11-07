"""API routes for notifications."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional

from backend.database import get_db
from backend.schemas.notification import (
    NotificationCreate,
    NotificationResponse,
    NotificationListResponse,
    NotificationUpdate,
    NotificationStats
)
from backend.services.notification_service import NotificationService

router = APIRouter()


@router.get("", response_model=NotificationListResponse)
@router.get("/", response_model=NotificationListResponse)
async def list_notifications(
    unread_only: bool = False,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    include_dismissed: bool = False,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """
    List notifications with optional filters.

    **For non-technical users:** View all your system alerts and notifications.
    You can filter by unread, category (model, data, job, etc.), or priority level.
    """
    service = NotificationService(db)
    notifications = service.list_notifications(
        unread_only=unread_only,
        category=category,
        priority=priority,
        include_dismissed=include_dismissed,
        include_archived=include_archived,
        limit=limit,
        offset=offset
    )

    total = len(notifications)
    unread_count = service.get_unread_count()

    return NotificationListResponse(
        notifications=[NotificationResponse.model_validate(n) for n in notifications],
        total=total,
        unread_count=unread_count
    )


@router.get("/stats", response_model=NotificationStats)
async def get_notification_stats(
    db: Session = Depends(get_db)
):
    """
    Get notification statistics.

    **For non-technical users:** See a summary of your notifications including
    unread count, breakdown by priority and category.
    """
    service = NotificationService(db)
    stats = service.get_stats()
    return NotificationStats(**stats)


@router.get("/{notification_id}", response_model=NotificationResponse)
async def get_notification(
    notification_id: int,
    db: Session = Depends(get_db)
):
    """
    Get a specific notification by ID.

    **For non-technical users:** View details of a specific notification.
    """
    service = NotificationService(db)
    notification = service.get_notification(notification_id)

    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification {notification_id} not found"
        )

    return NotificationResponse.model_validate(notification)


@router.post("", response_model=NotificationResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=NotificationResponse, status_code=status.HTTP_201_CREATED)
async def create_notification(
    notification: NotificationCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new notification.

    **For non-technical users:** Create a custom notification or alert.
    This is typically used by the system automatically, but can be used manually.
    """
    service = NotificationService(db)
    created = service.create_notification(notification)
    return NotificationResponse.model_validate(created)


@router.patch("/{notification_id}", response_model=NotificationResponse)
async def update_notification(
    notification_id: int,
    update: NotificationUpdate,
    db: Session = Depends(get_db)
):
    """
    Update a notification (mark as read, dismissed, etc.).

    **For non-technical users:** Update the status of a notification.
    Common actions include marking as read or dismissing.
    """
    service = NotificationService(db)
    updated = service.update_notification(notification_id, update)

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification {notification_id} not found"
        )

    return NotificationResponse.model_validate(updated)


@router.post("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_as_read(
    notification_id: int,
    db: Session = Depends(get_db)
):
    """
    Mark a notification as read.

    **For non-technical users:** Mark a notification as read to remove it
    from your unread count.
    """
    service = NotificationService(db)
    updated = service.mark_as_read(notification_id)

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification {notification_id} not found"
        )

    return NotificationResponse.model_validate(updated)


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_notifications_as_read(
    category: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Mark all notifications as read.

    **For non-technical users:** Clear all unread notifications at once.
    Optionally filter by category to only mark certain types as read.
    """
    service = NotificationService(db)
    service.mark_all_as_read(category=category)


@router.post("/{notification_id}/dismiss", response_model=NotificationResponse)
async def dismiss_notification(
    notification_id: int,
    db: Session = Depends(get_db)
):
    """
    Dismiss a notification.

    **For non-technical users:** Dismiss a notification to hide it from your list.
    Dismissed notifications can be viewed later in settings.
    """
    service = NotificationService(db)
    updated = service.dismiss_notification(notification_id)

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification {notification_id} not found"
        )

    return NotificationResponse.model_validate(updated)


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: int,
    db: Session = Depends(get_db)
):
    """
    Delete a notification permanently.

    **For non-technical users:** Permanently remove a notification.
    This action cannot be undone.
    """
    service = NotificationService(db)
    deleted = service.delete_notification(notification_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification {notification_id} not found"
        )
