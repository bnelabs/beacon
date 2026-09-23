"""
BEACON API - Banking Early Alert Comprehensive Observation Network
Powered by BNE (Banking Network Engine)

FastAPI application entry point for BEACON system.
Copyright © 2025 BNE (Banking Network Engine). All rights reserved.
"""

import hmac
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager, suppress
import asyncio
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
    network,
    observations,
)
from backend import __version__
from backend.database import DATABASE_URL, init_db, close_db
from backend.exceptions import BeaconError
from backend.api.job_events import relay_job_updates

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    #
    # `init_db()` is `Base.metadata.create_all()`. On PostgreSQL that made the
    # application a *second* schema owner alongside Alembic, and the two
    # disagreed: `20251107_152125` created `notifications.metadata` while
    # `backend/models/notification.py` declares `extra_data`, so which column a
    # database had depended on whether the API or the migration reached it
    # first. It also meant a database built by the app carried no
    # `alembic_version` row, so the next `alembic upgrade head` replayed the
    # whole chain over an existing schema and failed on the first duplicate.
    #
    # PostgreSQL schema is now owned by exactly one thing: the `migrate` service
    # in docker-compose.yml, which backend waits on with
    # `service_completed_successfully`. SQLite stays on create_all because the
    # test suite and local development build a throwaway database per run and
    # running Alembic there would only add a second thing to keep in sync.
    if DATABASE_URL.startswith("sqlite"):
        logger.info("Initializing SQLite development schema...")
        init_db()
    else:
        logger.info(
            "PostgreSQL schema is owned by Alembic (the compose `migrate` "
            "service); not calling create_all()"
        )

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

    # Relay job updates from the bus to this process's WebSocket clients.
    # Job progress is written by the Celery worker — a different process — so the
    # socket cannot be driven by in-process calls alone. See
    # backend/api/job_events.py and docs/api.md.
    relay_task = asyncio.create_task(
        relay_job_updates(jobs_ws.manager.broadcast), name="job-update-relay"
    )

    logger.info("Application startup complete")
    yield
    # Shutdown
    relay_task.cancel()
    with suppress(asyncio.CancelledError):
        await relay_task
    logger.info("Closing database connections...")
    close_db()
    logger.info("Application shutdown complete")


app = FastAPI(
    title="BEACON API - Banking Network Engine",
    description="Banking Early Alert Comprehensive Observation Network - Production-grade systemic liquidity risk monitoring",
    version=__version__,
    lifespan=lifespan
)

# Optional bearer-token gate (P4). BEACON ships single-operator and
# unauthenticated by default; deployments that need multi-tenant hygiene set
# BEACON_API_TOKEN and every /api/* call must carry it. Documentation
# endpoints stay open so the gate is discoverable rather than a brick wall.
_AUTH_EXEMPT_PREFIXES = ("/docs", "/redoc", "/openapi.json", "/health")


@app.middleware("http")
async def bearer_token_gate(request, call_next):
    token = os.getenv("BEACON_API_TOKEN", "").strip()
    path = request.url.path
    if not token or not path.startswith("/api") or path.startswith(_AUTH_EXEMPT_PREFIXES):
        return await call_next(request)
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(value.strip(), token):
        return JSONResponse(
            status_code=401,
            content={"detail": "BEACON_API_TOKEN is set; supply Authorization: Bearer <token>"},
        )
    return await call_next(request)

# CORS middleware for frontend access
# In production, set ALLOWED_ORIGINS environment variable
default_allowed_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:6789",
    "http://127.0.0.1:6789",
    # The production frontend container serves on 9876 (see docker-compose.yml).
    # Without these the browser blocks every API call from the Dockerised UI.
    "http://localhost:9876",
    "http://127.0.0.1:9876",
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
app.include_router(network.router, prefix="/api/v1/network", tags=["Network Graph & Bilateral Exposures"])
# The point-in-time reader for indicator vintages. ``observations_as_of`` has had
# no production caller since the vintage-log migration; this router is the caller.
app.include_router(observations.router, prefix="/api/v1/observations", tags=["Observations (Point-in-Time)"])

# This API exposes no metrics endpoint.


@app.exception_handler(BeaconError)
async def beacon_error_handler(request: Request, exc: BeaconError) -> JSONResponse:
    """Return domain errors as a stable, machine-readable payload.

    Clients branch on ``code`` rather than parsing message text, so a
    data-quality rejection is distinguishable from an upstream outage.
    """
    logger.warning("%s %s -> %s: %s", request.method, request.url.path, exc.code, exc)
    return JSONResponse(status_code=exc.http_status, content=exc.to_dict())


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
