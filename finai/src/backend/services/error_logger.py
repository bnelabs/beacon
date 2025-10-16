"""Error logging service for tracking and analyzing errors."""

import traceback
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session

from ..models.error_log import ErrorLog
from .enhanced_error_translator import EnhancedErrorTranslator

logger = logging.getLogger(__name__)


class ErrorLogger:
    """Service for logging and tracking errors."""

    def __init__(self, db: Session):
        self.db = db
        self.translator = EnhancedErrorTranslator()

    def log_error(
        self,
        exception: Exception,
        context: str = "",
        endpoint: Optional[str] = None,
        method: Optional[str] = None,
        request_data: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> ErrorLog:
        """
        Log an error to the database.

        Args:
            exception: The exception that occurred
            context: Context about what was being done
            endpoint: API endpoint where error occurred
            method: HTTP method
            request_data: Request data that caused the error
            user_id: User identifier
            session_id: Session identifier

        Returns:
            ErrorLog instance
        """
        # Translate error to structured format
        error_details = self.translator.translate(exception, context)

        # Get stack trace
        stack_trace = ''.join(traceback.format_exception(
            type(exception),
            exception,
            exception.__traceback__
        ))

        # Check if similar error exists recently (deduplication)
        existing_error = self._find_similar_error(
            error_type=type(exception).__name__,
            context=context,
            endpoint=endpoint
        )

        if existing_error:
            # Update existing error occurrence
            existing_error.occurrence_count += 1
            existing_error.last_occurred_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(existing_error)
            return existing_error

        # Create new error log
        error_log = ErrorLog(
            severity=error_details.severity.value,
            category=error_details.category.value,
            error_type=type(exception).__name__,
            user_message=error_details.user_message,
            technical_message=error_details.technical_message,
            context=context,
            endpoint=endpoint,
            method=method,
            solutions=error_details.solutions,
            stack_trace=stack_trace,
            request_data=request_data,
            user_id=user_id,
            session_id=session_id,
            resolved=False
        )

        self.db.add(error_log)
        self.db.commit()
        self.db.refresh(error_log)

        logger.info(f"Logged error: {error_log.id} - {error_log.category}/{error_log.severity}")
        return error_log

    def _find_similar_error(
        self,
        error_type: str,
        context: str,
        endpoint: Optional[str],
        time_window_minutes: int = 60
    ) -> Optional[ErrorLog]:
        """
        Find similar error that occurred recently (for deduplication).

        Args:
            error_type: Exception type name
            context: Operation context
            endpoint: API endpoint
            time_window_minutes: Time window to check for duplicates

        Returns:
            Existing ErrorLog if found, None otherwise
        """
        from datetime import timedelta

        cutoff_time = datetime.utcnow() - timedelta(minutes=time_window_minutes)

        query = self.db.query(ErrorLog).filter(
            ErrorLog.error_type == error_type,
            ErrorLog.context == context,
            ErrorLog.created_at >= cutoff_time,
            ErrorLog.resolved == False
        )

        if endpoint:
            query = query.filter(ErrorLog.endpoint == endpoint)

        return query.first()

    def get_recent_errors(
        self,
        limit: int = 100,
        severity: Optional[str] = None,
        category: Optional[str] = None,
        resolved: Optional[bool] = None
    ) -> list[ErrorLog]:
        """
        Get recent errors with optional filtering.

        Args:
            limit: Maximum number of errors to return
            severity: Filter by severity
            category: Filter by category
            resolved: Filter by resolution status

        Returns:
            List of ErrorLog instances
        """
        query = self.db.query(ErrorLog)

        if severity:
            query = query.filter(ErrorLog.severity == severity)
        if category:
            query = query.filter(ErrorLog.category == category)
        if resolved is not None:
            query = query.filter(ErrorLog.resolved == resolved)

        return query.order_by(ErrorLog.created_at.desc()).limit(limit).all()

    def get_error_statistics(self) -> Dict[str, Any]:
        """
        Get error statistics for analytics.

        Returns:
            Dictionary with error statistics
        """
        from sqlalchemy import func
        from datetime import timedelta

        now = datetime.utcnow()
        day_ago = now - timedelta(days=1)
        week_ago = now - timedelta(days=7)

        # Total errors
        total = self.db.query(func.count(ErrorLog.id)).scalar()

        # Errors by severity
        by_severity = dict(
            self.db.query(ErrorLog.severity, func.count(ErrorLog.id))
            .group_by(ErrorLog.severity)
            .all()
        )

        # Errors by category
        by_category = dict(
            self.db.query(ErrorLog.category, func.count(ErrorLog.id))
            .group_by(ErrorLog.category)
            .all()
        )

        # Recent errors (last 24 hours)
        recent_24h = self.db.query(func.count(ErrorLog.id)).filter(
            ErrorLog.created_at >= day_ago
        ).scalar()

        # Recent errors (last 7 days)
        recent_7d = self.db.query(func.count(ErrorLog.id)).filter(
            ErrorLog.created_at >= week_ago
        ).scalar()

        # Unresolved errors
        unresolved = self.db.query(func.count(ErrorLog.id)).filter(
            ErrorLog.resolved == False
        ).scalar()

        # Most common errors
        most_common = self.db.query(
            ErrorLog.error_type,
            ErrorLog.category,
            func.sum(ErrorLog.occurrence_count).label('total_occurrences')
        ).group_by(
            ErrorLog.error_type,
            ErrorLog.category
        ).order_by(
            func.sum(ErrorLog.occurrence_count).desc()
        ).limit(10).all()

        return {
            "total_errors": total,
            "by_severity": by_severity,
            "by_category": by_category,
            "recent_24h": recent_24h,
            "recent_7d": recent_7d,
            "unresolved": unresolved,
            "most_common": [
                {
                    "error_type": error_type,
                    "category": category,
                    "occurrences": int(count)
                }
                for error_type, category, count in most_common
            ]
        }

    def mark_resolved(self, error_id: int, resolution_notes: str) -> bool:
        """
        Mark an error as resolved.

        Args:
            error_id: Error log ID
            resolution_notes: Notes about the resolution

        Returns:
            True if successful, False if error not found
        """
        error_log = self.db.query(ErrorLog).filter(ErrorLog.id == error_id).first()

        if not error_log:
            return False

        error_log.resolved = True
        error_log.resolution_notes = resolution_notes
        error_log.resolved_at = datetime.utcnow()

        self.db.commit()
        return True
