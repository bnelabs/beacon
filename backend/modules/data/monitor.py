"""Data Monitor - Real-time status tracking."""

import logging
from datetime import datetime
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

class DataMonitor:
    def __init__(self, db: Session, job_id: str):
        self.db = db
        self.job_id = job_id
        self.start_time = None

    def start(self):
        self.start_time = datetime.utcnow()
        logger.info(f"[{self.job_id}] Monitor started")

    def update(self, status: str, progress: float, message: str):
        logger.info(f"[{self.job_id}] {progress:.1f}% - {message}")

    def complete(self, message: str):
        duration = (datetime.utcnow() - self.start_time).total_seconds()
        logger.info(f"[{self.job_id}] Completed in {duration:.1f}s - {message}")

    def fail(self, error: str):
        logger.error(f"[{self.job_id}] Failed - {error}")
