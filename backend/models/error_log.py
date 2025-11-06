"""SQLAlchemy model for error logging and tracking."""

from sqlalchemy import Column, Integer, String, DateTime, JSON, Text, Boolean
from sqlalchemy.sql import func
from backend.database import Base


class ErrorLog(Base):
    """Error log model for tracking and analyzing system errors."""
    __tablename__ = "error_logs"

    id = Column(Integer, primary_key=True, index=True)

    # Error classification
    severity = Column(String(20), nullable=False, index=True)  # info, warning, error, critical
    category = Column(String(50), nullable=False, index=True)  # network, auth, validation, etc.
    error_type = Column(String(100), nullable=False)  # Python exception type

    # Error messages
    user_message = Column(Text, nullable=False)  # User-friendly message
    technical_message = Column(Text)  # Full technical error

    # Context
    context = Column(String(200))  # What operation was being performed
    endpoint = Column(String(200))  # API endpoint if applicable
    method = Column(String(10))  # HTTP method if applicable

    # Additional data
    solutions = Column(JSON)  # List of suggested solutions
    stack_trace = Column(Text)  # Full stack trace
    request_data = Column(JSON)  # Request data that caused the error

    # Resolution tracking
    resolved = Column(Boolean, default=False)
    resolution_notes = Column(Text)
    resolved_at = Column(DateTime(timezone=True))

    # User info
    user_id = Column(String(100))  # If user authentication exists
    session_id = Column(String(100))  # Session identifier

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Occurrence tracking
    occurrence_count = Column(Integer, default=1)
    last_occurred_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<ErrorLog(id={self.id}, severity={self.severity}, category={self.category})>"
