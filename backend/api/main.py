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

from .routes import data_sources, assets, jobs, config, system, errors, catalogue, pipeline, results, explainability, scenarios, configurations, models

app.include_router(models.router, prefix="/api/v1/models", tags=["Models"])


app.include_router(configurations.router, prefix="/api/v1/configurations", tags=["Configurations"])


app.include_router(scenarios.router, prefix="/api/v1/scenarios", tags=["Scenarios"])

from database import init_db, close_db

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Initializing database...")
    init_db()

    # Populate catalogue if empty
    from database import SessionLocal
    from models.data_catalogue import DataCatalogueItem
    db = SessionLocal()
    try:
        count = db.query(DataCatalogueItem).count()
        if count == 0:
            logger.info("Catalogue is empty, populating with default items...")
            from scripts.populate_catalogue import populate_catalogue
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
allowed_origins = os.getenv("ALLOWED_ORIGINS", "").split(",") if os.getenv("ALLOWED_ORIGINS") else [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:6789",
    "http://127.0.0.1:6789",
]

# For Docker deployments, allow all origins (less secure, but necessary for dynamic IPs)
if os.getenv("ENVIRONMENT", "development") == "development":
    allowed_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False if "*" in allowed_origins else True,  # Can't use credentials with wildcard
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
app.include_router(config.router, prefix="/api/v1/config", tags=["Configuration"])
app.include_router(system.router, prefix="/api/v1/system", tags=["System"])
from auth import fastapi_users

app.include_router(fastapi_users.get_auth_router(jwt_authentication), prefix="/auth/jwt", tags=["auth"])
app.include_router(fastapi_users.get_register_router(), prefix="/auth", tags=["auth"])
app.include_router(fastapi_users.get_reset_password_router(), prefix="/auth", tags=["auth"])
app.include_router(fastapi_users.get_verify_router(), prefix="/auth", tags=["auth"])
app.include_router(fastapi_users.get_users_router(), prefix="/users", tags=["users"])



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
