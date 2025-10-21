"""SQLAlchemy model for error logging and tracking."""

from sqlalchemy import Integer, String, DateTime, JSON, Text, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from typing import Optional, List, Dict, Any
from database import Base


class ErrorLog(Base):
    """Error log model for tracking and analyzing system errors."""
    __tablename__ = "error_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Error classification
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # info, warning, error, critical
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # network, auth, validation, etc.
    error_type: Mapped[str] = mapped_column(String(100), nullable=False)  # Python exception type

    # Error messages
    user_message: Mapped[str] = mapped_column(Text, nullable=False)  # User-friendly message
    technical_message: Mapped[Optional[str]] = mapped_column(Text)  # Full technical error

    # Context
    context: Mapped[Optional[str]] = mapped_column(String(200))  # What operation was being performed
    endpoint: Mapped[Optional[str]] = mapped_column(String(200))  # API endpoint if applicable
    method: Mapped[Optional[str]] = mapped_column(String(10))  # HTTP method if applicable

    # Additional data
    solutions: Mapped[Optional[List[str]]] = mapped_column(JSON)  # List of suggested solutions
    stack_trace: Mapped[Optional[str]] = mapped_column(Text)  # Full stack trace
    request_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)  # Request data that caused the error

    # Resolution tracking
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # User info
    user_id: Mapped[Optional[str]] = mapped_column(String(100))  # If user authentication exists
    session_id: Mapped[Optional[str]] = mapped_column(String(100))  # Session identifier

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Occurrence tracking
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    last_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<ErrorLog(id={self.id}, severity={self.severity}, category={self.category})>"
