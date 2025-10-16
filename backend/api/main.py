"""FastAPI application entry point for Liquidity Monitor."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from .routes import data_sources, assets, jobs, config, system, errors
from database import init_db, close_db

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Initializing database...")
    init_db()
    logger.info("Application startup complete")
    yield
    # Shutdown
    logger.info("Closing database connections...")
    close_db()
    logger.info("Application shutdown complete")


app = FastAPI(
    title="Liquidity Monitor API",
    description="Production-grade financial liquidity risk monitoring system",
    version="2.0.0",
    lifespan=lifespan
)

# CORS middleware for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],  # React dev servers
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(data_sources.router, prefix="/api/v1/data-sources", tags=["Data Sources"])
app.include_router(assets.router, prefix="/api/v1/assets", tags=["Assets"])
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["Jobs"])
app.include_router(config.router, prefix="/api/v1/config", tags=["Configuration"])
app.include_router(system.router, prefix="/api/v1/system", tags=["System"])
app.include_router(errors.router, prefix="/api/v1/errors", tags=["Error Logging"])


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Liquidity Monitor API",
        "version": "2.0.0",
        "status": "operational",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "database": "connected"
    }
