"""API routes powering the v2 data exploration experience."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from database import get_db
from models.data_catalogue import DataCatalogueItem, DataRegion
from models.data_source import DataSource
from schemas.data_explorer_v2 import (
    CatalogueAssetResponse,
    CatalogueCoverage,
    CatalogueListResponse,
    DataSourceCoverage,
    DataSourceListResponse,
    DataSourceV2Response,
)
from services.error_logger import ErrorLogger

router = APIRouter()


REGION_ALIAS = {
    "NA": DataRegion.NORTH_AMERICA,
    "NORTH_AMERICA": DataRegion.NORTH_AMERICA,
    "LATAM": DataRegion.LATIN_AMERICA,
    "LATIN_AMERICA": DataRegion.LATIN_AMERICA,
    "MENA": DataRegion.MIDDLE_EAST,
    "MIDDLE_EAST": DataRegion.MIDDLE_EAST,
    "AFRICA": DataRegion.AFRICA,
    "EU": DataRegion.EUROPE,
    "EUROPE": DataRegion.EUROPE,
    "EU_WEST": DataRegion.EUROPE,
    "EU_EAST": DataRegion.EUROPE,
    "PACIFIC": DataRegion.ASIA,
    "ASIA": DataRegion.ASIA,
    "APAC": DataRegion.ASIA,
    "GLOBAL": DataRegion.GLOBAL,
}


def _normalize_regions(region_tokens: Iterable[str]) -> List[DataRegion]:
    regions: List[DataRegion] = []
    for token in region_tokens:
        if not token:
            continue
        key = token.strip().upper()
        mapped = REGION_ALIAS.get(key)
        if not mapped:
            continue
        if mapped not in regions:
            regions.append(mapped)
    return regions


def _derive_payload_capabilities(data_source: DataSource) -> Dict[str, object]:
    config = data_source.config or {}
    capabilities = {
        "supports_historical": bool(config.get("supports_historical", True)),
        "supports_realtime": bool(config.get("supports_realtime", False)),
        "latency_minutes": config.get("latency_minutes"),
    }
    if rate_limit := config.get("rate_limit"):
        capabilities["rate_limit"] = rate_limit
    return capabilities


def _aggregate_datasource_rows(rows: Sequence[Tuple[DataSource, DataCatalogueItem]]) -> List[DataSourceV2Response]:
    grouped: Dict[int, Dict[str, object]] = {}

    for ds, item in rows:
        entry = grouped.setdefault(
            ds.id,
            {
                "datasource": ds,
                "regions": set(),
                "categories": set(),
                "risk_types": set(),
                "frequencies": set(),
                "asset_count": 0,
                "start_candidates": [],
                "end_candidates": [],
            },
        )
        if item.region:
            entry["regions"].add(item.region.value if hasattr(item.region, "value") else item.region)
        if item.category:
            entry["categories"].add(item.category.value if hasattr(item.category, "value") else item.category)
        for risk in item.risk_types or []:
            entry["risk_types"].add(risk)
        if item.frequency:
            entry["frequencies"].add(item.frequency)

        entry["asset_count"] += 1
        if item.created_at:
            entry["start_candidates"].append(item.created_at)
        if item.last_data_update:
            entry["end_candidates"].append(item.last_data_update)

    responses: List[DataSourceV2Response] = []
    for data in grouped.values():
        ds: DataSource = data["datasource"]
        frequencies = [freq for freq in data["frequencies"] if freq]
        coverage = DataSourceCoverage(
            start=min(data["start_candidates"]) if data["start_candidates"] else None,
            end=max(data["end_candidates"]) if data["end_candidates"] else None,
            frequency=sorted(frequencies),
            asset_count=data["asset_count"],
        )

        responses.append(
            DataSourceV2Response(
                id=ds.id,
                name=ds.name,
                plugin_type=ds.plugin_type,
                enabled=bool(ds.enabled),
                status=ds.status,
                description=ds.description,
                regions=sorted(data["regions"]),
                categories=sorted(data["categories"]),
                risk_types=sorted(data["risk_types"]),
                coverage=coverage,
                payload_capabilities=_derive_payload_capabilities(ds),
            )
        )

    return sorted(responses, key=lambda item: item.name.lower())


@router.get("/datasources", response_model=DataSourceListResponse)
async def list_datasources_v2(
    regions: Optional[str] = Query(None, description="Comma-separated region codes (NA, EU_WEST, MENA...)"),
    db: Session = Depends(get_db),
):
    """Return enriched datasource metadata filtered by the requested regions."""
    try:
        region_filters = _normalize_regions(regions.split(",")) if regions else []

        query = (
            db.query(DataSource, DataCatalogueItem)
            .join(DataCatalogueItem, DataCatalogueItem.data_source_id == DataSource.id)
            .filter(DataCatalogueItem.enabled == True)  # noqa: E712
        )

        if region_filters:
            query = query.filter(DataCatalogueItem.region.in_(region_filters))

        rows = query.all()
        sources = _aggregate_datasource_rows(rows)
        requested_region_codes = [region.value for region in region_filters] if region_filters else []

        return DataSourceListResponse(
            regions=requested_region_codes,
            sources=sources,
            other_connectors_supported=True,
        )

    except Exception as exc:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(
            exc,
            context="listing v2 datasources",
            endpoint="/api/v2/datasources",
            method="GET",
            request_data={"regions": regions},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message},
        )


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _build_catalogue_response(items: Sequence[DataCatalogueItem]) -> List[CatalogueAssetResponse]:
    responses: List[CatalogueAssetResponse] = []
    for item in items:
        parameters = item.parameters if isinstance(item.parameters, dict) else {}
        coverage = CatalogueCoverage(
            start=_parse_datetime(parameters.get("start_date")),
            end=item.last_data_update,
            frequency=item.frequency,
            missing_ratio=_parse_float(parameters.get("missing_ratio")),
            anomaly_score=_parse_float(parameters.get("anomaly_score")),
        )

        responses.append(
            CatalogueAssetResponse(
                id=item.id,
                code=item.code,
                name=item.name,
                description=item.description,
                category=item.category.value if hasattr(item.category, "value") else item.category,
                region=item.region.value if hasattr(item.region, "value") else item.region,
                risk_types=item.risk_types or [],
                data_source_id=item.data_source_id,
                data_source_name=item.data_source.name if item.data_source else None,
                frequency=item.frequency,
                granularity=item.granularity,
                unit=item.unit,
                enabled=bool(item.enabled),
                default_selected=bool(item.default_selected),
                tags=item.tags or [],
                priority=item.priority,
                coverage=coverage,
            )
        )
    return responses


@router.get("/datacatalog", response_model=CatalogueListResponse)
async def list_catalogue_v2(
    sources: Optional[str] = Query(None, description="Comma-separated data source IDs"),
    search: Optional[str] = Query(None, description="Free text search across code and name"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Paginated catalogue browser used by the v2 UI."""
    try:
        query = db.query(DataCatalogueItem).options(joinedload(DataCatalogueItem.data_source)).filter(
            DataCatalogueItem.enabled == True  # noqa: E712
        )

        if sources:
            try:
                source_ids = [int(s.strip()) for s in sources.split(",") if s.strip()]
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"technical": str(exc), "user_friendly": "Invalid source identifiers supplied."},
                )
            if source_ids:
                query = query.filter(DataCatalogueItem.data_source_id.in_(source_ids))

        if search:
            like_expr = f"%{search.lower()}%"
            query = query.filter(
                func.lower(DataCatalogueItem.code).like(like_expr)
                | func.lower(DataCatalogueItem.name).like(like_expr)
                | func.lower(func.coalesce(DataCatalogueItem.description, "")).like(like_expr)
            )

        total = query.count()
        items = (
            query.order_by(DataCatalogueItem.priority.desc(), DataCatalogueItem.name.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return CatalogueListResponse(
            page=page,
            page_size=page_size,
            total=total,
            assets=_build_catalogue_response(items),
        )

    except HTTPException:
        raise
    except Exception as exc:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(
            exc,
            context="listing v2 catalogue",
            endpoint="/api/v2/datacatalog",
            method="GET",
            request_data={"sources": sources, "search": search, "page": page, "page_size": page_size},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message},
        )
