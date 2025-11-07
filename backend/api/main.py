"""
BEACON API - Banking Early Alert Comprehensive Observation Network
Powered by BNE (Banking Network Engine)

FastAPI application entry point for BEACON system.
Copyright © 2025 BNE (Banking Network Engine). All rights reserved.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
import os

from .routes import (
    data_sources,
    assets,
    jobs,
    jobs_ws,
    config,
    system,
    errors,
    catalogue,
    pipeline,
    results,
    explainability,
    data_explorer_v2,
    reports_v2,
    models_v1,
    predictions_v2,
    countries,
    notifications,
    data_quality,
    analytics,
    alert_rules,
    reports,
)
from backend.database import init_db, close_db

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Initializing database...")
    init_db()

    # Populate catalogue if empty
    from backend.database import SessionLocal
    from backend.models.data_catalogue import DataCatalogueItem
    db = SessionLocal()
    try:
        count = db.query(DataCatalogueItem).count()
        if count == 0:
            logger.info("Catalogue is empty, populating with default items...")
            from backend.scripts.populate_catalogue import populate_catalogue
            populate_catalogue()
            logger.info("Catalogue populated successfully")
        else:
            logger.info(f"Catalogue already contains {count} items")
    except Exception as e:
        logger.error(f"Failed to check/populate catalogue: {e}")
    finally:
        db.close()

    logger.info("Application startup complete")
    yield
    # Shutdown
    logger.info("Closing database connections...")
    close_db()
    logger.info("Application shutdown complete")


app = FastAPI(
    title="BEACON API - Banking Network Engine",
    description="Banking Early Alert Comprehensive Observation Network - Production-grade systemic liquidity risk monitoring",
    version="2.0.0",
    lifespan=lifespan
)

# CORS middleware for frontend access
# In production, set ALLOWED_ORIGINS environment variable
default_allowed_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:6789",
    "http://127.0.0.1:6789",
]

if os.getenv("ALLOWED_ORIGINS"):
    allowed_origins = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "").split(",") if origin.strip()]
else:
    allowed_origins = default_allowed_origins

allow_credentials = os.getenv("ALLOW_CREDENTIALS", "true").lower() not in {"false", "0", "no"}

if "*" in allowed_origins:
    allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Include routers
app.include_router(pipeline.router, prefix="/api/v1/pipeline", tags=["Pipeline (DATA-ENGINE-RESULTS)"])
app.include_router(results.router, prefix="/api/v1/results", tags=["Results & Reports"])
app.include_router(explainability.router, prefix="/api/v1/explainability", tags=["AI Explainability (EU Compliant)"])
app.include_router(catalogue.router, prefix="/api/v1/catalogue", tags=["Data Catalogue"])
app.include_router(data_sources.router, prefix="/api/v1/data-sources", tags=["Data Sources"])
app.include_router(assets.router, prefix="/api/v1/assets", tags=["Assets"])
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["Jobs"])
app.include_router(jobs_ws.router, prefix="/api/v1/jobs", tags=["Jobs WebSocket"])
app.include_router(config.router, prefix="/api/v1/config", tags=["Configuration"])
app.include_router(system.router, prefix="/api/v1/system", tags=["System"])
app.include_router(errors.router, prefix="/api/v1/errors", tags=["Error Logging"])
app.include_router(data_explorer_v2.router, prefix="/api/v2", tags=["Data Explorer v2"])
app.include_router(reports_v2.router, prefix="/api/v2", tags=["Reports v2"])
app.include_router(predictions_v2.router, prefix="/api/v2", tags=["Predictions v2"])
app.include_router(models_v1.router, prefix="/api/v1/models", tags=["Model Catalogue"])
app.include_router(models_v1.router, prefix="/api/models", tags=["Model Catalogue"])
app.include_router(countries.router, prefix="/api/v1/countries", tags=["Country Profiles"])
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["Notifications"])
app.include_router(data_quality.router, prefix="/api/v1/data-quality", tags=["Data Quality"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["Advanced Analytics"])
app.include_router(alert_rules.router, prefix="/api/v1/alert-rules", tags=["Alert Rules"])
app.include_router(reports.router, prefix="/api/v1/reports", tags=["Reports"])


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "BEACON API - Banking Network Engine",
        "description": "Banking Early Alert Comprehensive Observation Network",
        "tagline": "Your early warning system for systemic liquidity risk",
        "version": "2.0.0",
        "status": "operational",
        "docs": "/docs",
        "copyright": "© 2025 BNE (Banking Network Engine). All rights reserved."
    }


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "database": "connected"
    }
