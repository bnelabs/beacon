"""Service for managing notifications."""

from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from typing import List, Optional, Dict
from datetime import datetime

from backend.models.notification import Notification
from backend.schemas.notification import NotificationCreate, NotificationUpdate


class NotificationService:
    """Service for creating and managing notifications."""

    def __init__(self, db: Session):
        self.db = db

    def create_notification(self, notification: NotificationCreate) -> Notification:
        """Create a new notification."""
        db_notification = Notification(**notification.model_dump())
        self.db.add(db_notification)
        self.db.commit()
        self.db.refresh(db_notification)
        return db_notification

    def get_notification(self, notification_id: int) -> Optional[Notification]:
        """Get a notification by ID."""
        return self.db.query(Notification).filter(Notification.id == notification_id).first()

    def list_notifications(
        self,
        unread_only: bool = False,
        category: Optional[str] = None,
        priority: Optional[str] = None,
        include_dismissed: bool = False,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0
    ) -> List[Notification]:
        """List notifications with filters."""
        query = self.db.query(Notification)

        if unread_only:
            query = query.filter(Notification.is_read == False)

        if category:
            query = query.filter(Notification.category == category)

        if priority:
            query = query.filter(Notification.priority == priority)

        if not include_dismissed:
            query = query.filter(Notification.is_dismissed == False)

        if not include_archived:
            query = query.filter(Notification.is_archived == False)

        # Filter out expired notifications
        query = query.filter(
            (Notification.expires_at == None) | (Notification.expires_at > datetime.utcnow())
        )

        query = query.order_by(desc(Notification.created_at))
        query = query.limit(limit).offset(offset)

        return query.all()

    def update_notification(
        self,
        notification_id: int,
        update: NotificationUpdate
    ) -> Optional[Notification]:
        """Update a notification."""
        notification = self.get_notification(notification_id)
        if not notification:
            return None

        update_data = update.model_dump(exclude_unset=True)

        # Update timestamps based on status changes
        if 'is_read' in update_data and update_data['is_read']:
            update_data['read_at'] = datetime.utcnow()

        if 'is_dismissed' in update_data and update_data['is_dismissed']:
            update_data['dismissed_at'] = datetime.utcnow()

        for key, value in update_data.items():
            setattr(notification, key, value)

        self.db.commit()
        self.db.refresh(notification)
        return notification

    def mark_as_read(self, notification_id: int) -> Optional[Notification]:
        """Mark notification as read."""
        return self.update_notification(
            notification_id,
            NotificationUpdate(is_read=True)
        )

    def mark_all_as_read(self, category: Optional[str] = None) -> int:
        """Mark all notifications as read, optionally filtered by category."""
        query = self.db.query(Notification).filter(Notification.is_read == False)

        if category:
            query = query.filter(Notification.category == category)

        count = query.update({
            'is_read': True,
            'read_at': datetime.utcnow()
        })
        self.db.commit()
        return count

    def dismiss_notification(self, notification_id: int) -> Optional[Notification]:
        """Dismiss a notification."""
        return self.update_notification(
            notification_id,
            NotificationUpdate(is_dismissed=True)
        )

    def archive_notification(self, notification_id: int) -> Optional[Notification]:
        """Archive a notification."""
        return self.update_notification(
            notification_id,
            NotificationUpdate(is_archived=True)
        )

    def delete_notification(self, notification_id: int) -> bool:
        """Delete a notification."""
        notification = self.get_notification(notification_id)
        if not notification:
            return False

        self.db.delete(notification)
        self.db.commit()
        return True

    def get_unread_count(self, category: Optional[str] = None) -> int:
        """Get count of unread notifications."""
        query = self.db.query(func.count(Notification.id)).filter(
            Notification.is_read == False,
            Notification.is_dismissed == False,
            Notification.is_archived == False
        )

        if category:
            query = query.filter(Notification.category == category)

        return query.scalar() or 0

    def get_stats(self) -> Dict:
        """Get notification statistics."""
        total = self.db.query(func.count(Notification.id)).filter(
            Notification.is_archived == False
        ).scalar() or 0

        unread = self.get_unread_count()

        # Count by priority
        by_priority = {}
        priority_counts = self.db.query(
            Notification.priority,
            func.count(Notification.id)
        ).filter(
            Notification.is_archived == False,
            Notification.is_read == False
        ).group_by(Notification.priority).all()

        for priority, count in priority_counts:
            by_priority[priority] = count

        # Count by category
        by_category = {}
        category_counts = self.db.query(
            Notification.category,
            func.count(Notification.id)
        ).filter(
            Notification.is_archived == False,
            Notification.is_read == False,
            Notification.category != None
        ).group_by(Notification.category).all()

        for category, count in category_counts:
            by_category[category or 'other'] = count

        # Count urgent
        urgent = self.db.query(func.count(Notification.id)).filter(
            Notification.is_urgent == True,
            Notification.is_read == False,
            Notification.is_archived == False
        ).scalar() or 0

        return {
            'total': total,
            'unread': unread,
            'by_priority': by_priority,
            'by_category': by_category,
            'urgent': urgent
        }

    def create_job_notification(
        self,
        job_id: int,
        job_status: str,
        job_type: str,
        error_message: Optional[str] = None
    ) -> Notification:
        """Create a notification for a job status change."""
        if job_status == 'completed':
            return self.create_notification(NotificationCreate(
                title=f"{job_type.replace('_', ' ').title()} Job Completed",
                message=f"Job #{job_id} has completed successfully.",
                notification_type='success',
                category='job',
                priority='low',
                action_url=f'/jobs?selected={job_id}',
                action_label='View Job',
                related_entity_type='job',
                related_entity_id=job_id
            ))
        elif job_status == 'failed':
            return self.create_notification(NotificationCreate(
                title=f"{job_type.replace('_', ' ').title()} Job Failed",
                message=f"Job #{job_id} failed: {error_message or 'Unknown error'}",
                notification_type='error',
                category='job',
                priority='high',
                is_urgent=True,
                action_url=f'/jobs?selected={job_id}',
                action_label='View Error',
                related_entity_type='job',
                related_entity_id=job_id
            ))
        else:
            return None

    def create_risk_alert(
        self,
        entity_name: str,
        risk_score: float,
        threshold: float,
        entity_id: Optional[int] = None
    ) -> Notification:
        """Create a notification for a high risk alert."""
        return self.create_notification(NotificationCreate(
            title=f"High Risk Alert: {entity_name}",
            message=f"Risk score of {risk_score:.2f} exceeds threshold of {threshold:.2f}",
            notification_type='alert',
            category='risk',
            priority='critical',
            is_urgent=True,
            action_url='/results' if entity_id else None,
            action_label='View Details',
            metadata={'risk_score': risk_score, 'threshold': threshold}
        ))

    def create_data_quality_alert(
        self,
        source_name: str,
        issue_description: str,
        severity: str = 'medium'
    ) -> Notification:
        """Create a notification for data quality issues."""
        priority_map = {
            'low': 'low',
            'medium': 'medium',
            'high': 'high',
            'critical': 'critical'
        }

        return self.create_notification(NotificationCreate(
            title=f"Data Quality Issue: {source_name}",
            message=issue_description,
            notification_type='warning',
            category='data',
            priority=priority_map.get(severity, 'medium'),
            is_urgent=severity in ['high', 'critical'],
            action_url='/datasources',
            action_label='View Data Sources'
        ))
