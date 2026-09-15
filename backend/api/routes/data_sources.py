"""API routes for data source management."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import Any, Dict, List

from backend.database import get_db
from backend.models.data_source import DataSource
from backend.schemas.data_source import (
    DataSourceCreate,
    DataSourceUpdate,
    DataSourceResponse,
    DataSourceTestRequest,
    DataSourceTestResponse
)
from backend.services.data_source_service import DataSourceService
from backend.services.error_logger import ErrorLogger
from backend.services.scheduling import (
    backoff_factor,
    enqueue_collection,
    has_open_collection,
    next_due_at,
)
from backend.schemas.job import JobResponse

router = APIRouter()


@router.get("", response_model=List[DataSourceResponse])
@router.get("/", response_model=List[DataSourceResponse])
async def list_data_sources(
    enabled_only: bool = False,
    db: Session = Depends(get_db)
):
    """
    List all configured data sources.

    **For non-technical users:** This shows all the data feeds you've set up
    (like Yahoo Finance, FRED, etc.). You can see which ones are working and which
    ones have errors.
    """
    try:
        service = DataSourceService(db)
        return service.list_data_sources(enabled_only=enabled_only)
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="listing data sources", endpoint="/api/v1/data-sources", method="GET")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.get("/disclosure")
async def get_provenance_disclosure(
    db: Session = Depends(get_db)
):
    """Provenance disclosure: every feed, its publisher, and what is inferred.

    **For auditors and operators:** answers, for this deployment, *where each
    input comes from* -- publisher, provenance class (supervisory publication,
    official statistics, regulatory filing, market observation, research
    dataset, operator declaration), key requirements derived from each
    plugin's own declaration, configured/enabled counts and catalogue
    coverage -- plus the platform's data policy and the list of **inferred**
    inputs (today: the bilateral network estimated from declared aggregate
    marginals, which is labelled everywhere and never stored as an
    observation).

    Registered before ``/{data_source_id}`` so the literal path wins over the
    integer parameter route.
    """
    from backend.modules.data.provenance import build_disclosure

    try:
        return build_disclosure(db)
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="building provenance disclosure", endpoint="/api/v1/data-sources/disclosure", method="GET")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.get("/health", response_model=Dict[str, Any])
async def data_source_health(db: Session = Depends(get_db)):
    """Feed health: cadence, last outcome, and what is overdue, per source.

    **For non-technical users:** one row per connected feed answering "when
    did it last succeed, how long did it take, how many rows arrived, and is
    the next refresh due or late". A feed that keeps failing shows a growing
    retry interval (the backoff), so "quiet" never silently means "broken".
    """
    now = datetime.now(timezone.utc)
    sources = []
    for source in db.query(DataSource).order_by(DataSource.name).all():
        due = next_due_at(source, now)
        sources.append(
            {
                "id": source.id,
                "name": source.name,
                "plugin_type": source.plugin_type,
                "enabled": bool(source.enabled),
                "status": source.status,
                "error_message": source.error_message,
                "sync_interval_minutes": source.sync_interval_minutes,
                "scheduled": source.sync_interval_minutes is not None,
                "backoff_factor": backoff_factor(source.consecutive_failures),
                "consecutive_failures": int(source.consecutive_failures or 0),
                "last_successful_fetch": (
                    source.last_successful_fetch.isoformat()
                    if source.last_successful_fetch
                    else None
                ),
                "last_sync_started_at": (
                    source.last_sync_started_at.isoformat()
                    if source.last_sync_started_at
                    else None
                ),
                "last_sync_duration_ms": source.last_sync_duration_ms,
                "last_sync_rows": source.last_sync_rows,
                "collection_running": has_open_collection(db, source.id),
                "next_due_at": due.isoformat() if due else None,
                "overdue": bool(due is not None and now >= due),
            }
        )
    return {"generated_at": now.isoformat(), "sources": sources}


@router.get("/{data_source_id}", response_model=DataSourceResponse)
async def get_data_source(
    data_source_id: int,
    db: Session = Depends(get_db)
):
    """
    Get details of a specific data source.

    **For non-technical users:** View the configuration and status of a single data feed.
    """
    try:
        service = DataSourceService(db)
        data_source = service.get_data_source(data_source_id)
        if not data_source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "technical": f"Data source {data_source_id} not found",
                    "user_friendly": "This data source doesn't exist. It may have been deleted."
                }
            )
        return data_source
    except HTTPException:
        raise
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="retrieving data source", endpoint=f"/api/v1/data-sources/{data_source_id}", method="GET")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.post("", response_model=DataSourceResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=DataSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_data_source(
    data_source: DataSourceCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new data source.

    **For non-technical users:** Add a new data feed to the system.
    Fill in the name, select the type (Yahoo Finance, FRED, etc.), and provide
    any required information like API keys.
    """
    try:
        service = DataSourceService(db)
        return service.create_data_source(data_source)
    except ValueError as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="creating data source", endpoint="/api/v1/data-sources", method="POST", request_data=data_source.dict())
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="creating data source", endpoint="/api/v1/data-sources", method="POST", request_data=data_source.dict())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.put("/{data_source_id}", response_model=DataSourceResponse)
async def update_data_source(
    data_source_id: int,
    data_source_update: DataSourceUpdate,
    db: Session = Depends(get_db)
):
    """
    Update an existing data source.

    **For non-technical users:** Modify the settings of an existing data feed.
    You can change the API key, enable/disable it, or update other settings.
    """
    try:
        service = DataSourceService(db)
        updated = service.update_data_source(data_source_id, data_source_update)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "technical": f"Data source {data_source_id} not found",
                    "user_friendly": "This data source doesn't exist. It may have been deleted."
                }
            )
        return updated
    except HTTPException:
        raise
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="updating data source", endpoint=f"/api/v1/data-sources/{data_source_id}", method="PUT", request_data=data_source_update.dict())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.post("/{data_source_id}/sync", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def sync_data_source(
    data_source_id: int,
    db: Session = Depends(get_db)
):
    """Queue a real collection job for this source.

    **For non-technical users:** "Sync now" used to stamp a time and do
    nothing else; the refresh you expected never happened. It now queues the
    same collection job the scheduler queues -- watch it under Jobs, with
    progress, results and failures like any other run.
    """
    source = db.get(DataSource, data_source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "technical": f"Data source {data_source_id} not found",
                "user_friendly": "We couldn't locate that data source. It may have been removed."
            }
        )
    if not source.enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "technical": f"Data source {data_source_id} is disabled",
                "user_friendly": "That data source is disabled. Enable it before syncing."
            }
        )
    if has_open_collection(db, data_source_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "technical": f"A collection for data source {data_source_id} is already running",
                "user_friendly": "A collection for this source is already running. Wait for it to finish."
            }
        )
    try:
        return enqueue_collection(db, source, origin="manual")
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(
            e,
            context="queueing data source collection",
            endpoint=f"/api/v1/data-sources/{data_source_id}/sync",
            method="POST"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.post("/{data_source_id}/probe", response_model=DataSourceTestResponse)
async def probe_data_source(
    data_source_id: int,
    db: Session = Depends(get_db)
):
    """Test the saved configuration of one source against its live provider.

    **For non-technical users:** "Can we actually reach this feed, right now,
    with the settings we have?" -- answered without waiting for a scheduled
    collection to fail. Environment-held API keys are injected exactly as the
    collector injects them, so a keyed feed probes the same way it runs.
    """
    source = db.get(DataSource, data_source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "technical": f"Data source {data_source_id} not found",
                "user_friendly": "We couldn't locate that data source. It may have been removed."
            }
        )
    from backend.plugins import config_with_env_keys

    service = DataSourceService(db)
    request = DataSourceTestRequest(
        plugin_type=source.plugin_type,
        config=config_with_env_keys(source.plugin_type, source.config),
    )
    return service.test_data_source(request)


@router.delete("/{data_source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_data_source(
    data_source_id: int,
    db: Session = Depends(get_db)
):
    """
    Delete a data source.

    **For non-technical users:** Remove a data feed from the system.
    Warning: This will stop collecting data from this source.
    """
    try:
        service = DataSourceService(db)
        deleted = service.delete_data_source(data_source_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "technical": f"Data source {data_source_id} not found",
                    "user_friendly": "This data source doesn't exist. It may have already been deleted."
                }
            )
    except HTTPException:
        raise
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="deleting data source", endpoint=f"/api/v1/data-sources/{data_source_id}", method="DELETE")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.post("/test", response_model=DataSourceTestResponse)
async def test_data_source(
    test_request: DataSourceTestRequest,
    db: Session = Depends(get_db)
):
    """
    Test a data source configuration before saving it.

    **For non-technical users:** Check if your data feed settings are correct
    before you save them. This will verify your API key and connection work.
    """
    try:
        service = DataSourceService(db)
        return service.test_data_source(test_request)
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="testing data source", endpoint="/api/v1/data-sources/test", method="POST", request_data=test_request.dict())
        return DataSourceTestResponse(
            success=False,
            message=error_log.user_message,
            details={"technical_error": error_log.technical_message}
        )
