"""
BEACON Database Connection and Session Management
Part of the BNE (Banking Network Engine)

Copyright © 2025 BNE. All rights reserved.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from typing import Generator
import os
from sqlalchemy.pool import NullPool, StaticPool

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://beacon_user:beacon_password@localhost:5432/beacon_db")

# For SQLite fallback in development
if os.getenv("USE_SQLITE", "false").lower() == "true":
    DATABASE_URL = "sqlite:///./beacon.db"

if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    pool = StaticPool if ":memory:" in DATABASE_URL else NullPool
    engine = create_engine(
        DATABASE_URL,
        connect_args=connect_args,
        poolclass=pool,
    )
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,  # Verify connections before using
        pool_size=10,
        max_overflow=20
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def init_db():
    """Initialize database tables."""
    from backend.models import data_source, asset, job, error_log, data_catalogue, pipeline_job, country  # Import all models
    Base.metadata.create_all(bind=engine)


def close_db():
    """Close database connections."""
    engine.dispose()


def get_db() -> Generator[Session, None, None]:
    """Dependency to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
