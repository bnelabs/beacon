"""API routes for data catalogue management."""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from database import get_db
from models.data_catalogue import DataCatalogueItem, DataCategory, DataRegion, RiskType
from schemas.catalogue import (
    DataCatalogueItemResponse,
    CatalogueFilterRequest,
    CatalogueSummaryResponse,
    BulkCatalogueSelectRequest
)
from services.error_logger import ErrorLogger

router = APIRouter()


@router.get("", response_model=List[DataCatalogueItemResponse])
@router.get("/", response_model=List[DataCatalogueItemResponse])
async def list_catalogue_items(
    category: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    risk_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    enabled_only: bool = Query(True),
    default_only: bool = Query(False),
    db: Session = Depends(get_db)
):
    """
    List available data catalogue items with filtering.

    **For non-technical users:** Browse all available financial data sources you can track.
    Filter by category (exchange rates, stocks, etc.), region (US, Europe, Asia), or search by name.
    """
    try:
        query = db.query(DataCatalogueItem)

        # Apply filters
        if category:
            query = query.filter(DataCatalogueItem.category == category)

        if region:
            query = query.filter(DataCatalogueItem.region == region)

        if risk_type:
            # JSON array contains query
            query = query.filter(DataCatalogueItem.risk_types.contains([risk_type]))

        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                (DataCatalogueItem.name.ilike(search_pattern)) |
                (DataCatalogueItem.description.ilike(search_pattern)) |
                (DataCatalogueItem.code.ilike(search_pattern))
            )

        if enabled_only:
            query = query.filter(DataCatalogueItem.enabled == True)

        if default_only:
            query = query.filter(DataCatalogueItem.default_selected == True)

        # Order by priority (descending) then name
        query = query.order_by(
            DataCatalogueItem.priority.desc(),
            DataCatalogueItem.name
        )

        items = query.all()
        return items

    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(
            e,
            context="listing catalogue items",
            endpoint="/api/v1/catalogue",
            method="GET"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.get("/summary", response_model=CatalogueSummaryResponse)
async def get_catalogue_summary(db: Session = Depends(get_db)):
    """
    Get summary statistics for the data catalogue.

    **For non-technical users:** See how many data sources are available,
    broken down by type, region, and risk category.
    """
    try:
        total_items = db.query(DataCatalogueItem).count()
        enabled_count = db.query(DataCatalogueItem).filter(DataCatalogueItem.enabled == True).count()
        default_count = db.query(DataCatalogueItem).filter(DataCatalogueItem.default_selected == True).count()

        # Count by category
        by_category = {}
        for category in DataCategory:
            count = db.query(DataCatalogueItem).filter(
                DataCatalogueItem.category == category
            ).count()
            by_category[category.value] = count

        # Count by region
        by_region = {}
        for region in DataRegion:
            count = db.query(DataCatalogueItem).filter(
                DataCatalogueItem.region == region
            ).count()
            by_region[region.value] = count

        # Count by risk type (approximate - items can have multiple risk types)
        by_risk_type = {}
        for risk in RiskType:
            count = db.query(DataCatalogueItem).filter(
                DataCatalogueItem.risk_types.contains([risk.value])
            ).count()
            by_risk_type[risk.value] = count

        return CatalogueSummaryResponse(
            total_items=total_items,
            by_category=by_category,
            by_region=by_region,
            by_risk_type=by_risk_type,
            default_selected_count=default_count,
            enabled_count=enabled_count
        )

    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(
            e,
            context="getting catalogue summary",
            endpoint="/api/v1/catalogue/summary",
            method="GET"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.get("/defaults", response_model=List[DataCatalogueItemResponse])
async def get_default_items(db: Session = Depends(get_db)):
    """
    Get default selected catalogue items.

    **For non-technical users:** These are the recommended data sources that cover
    major markets (US, Europe, Asia) and key liquidity risk indicators. Great starting point!
    """
    try:
        items = db.query(DataCatalogueItem).filter(
            DataCatalogueItem.default_selected == True,
            DataCatalogueItem.enabled == True
        ).order_by(
            DataCatalogueItem.priority.desc()
        ).all()

        return items

    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(
            e,
            context="getting default catalogue items",
            endpoint="/api/v1/catalogue/defaults",
            method="GET"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.get("/categories", response_model=List[dict])
async def get_categories():
    """
    Get list of available data categories.

    **For non-technical users:** See all types of financial data available
    (exchange rates, stocks, bonds, banking, etc.).
    """
    return [
        {
            "value": cat.value,
            "label": cat.value.replace("_", " ").title(),
            "description": _get_category_description(cat)
        }
        for cat in DataCategory
    ]


@router.get("/regions", response_model=List[dict])
async def get_regions():
    """
    Get list of available regions.

    **For non-technical users:** See which geographic regions we cover
    (North America, Europe, Asia, etc.).
    """
    return [
        {
            "value": reg.value,
            "label": reg.value.replace("_", " ").title(),
            "description": _get_region_description(reg)
        }
        for reg in DataRegion
    ]


@router.get("/risk-types", response_model=List[dict])
async def get_risk_types():
    """
    Get list of risk types.

    **For non-technical users:** See different types of liquidity risks we monitor.
    """
    return [
        {
            "value": risk.value,
            "label": risk.value.replace("_", " ").title(),
            "description": _get_risk_type_description(risk)
        }
        for risk in RiskType
    ]


@router.get("/{item_id}", response_model=DataCatalogueItemResponse)
async def get_catalogue_item(
    item_id: int,
    db: Session = Depends(get_db)
):
    """Get details of a specific catalogue item."""
    try:
        item = db.query(DataCatalogueItem).filter(DataCatalogueItem.id == item_id).first()

        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "technical": f"Catalogue item {item_id} not found",
                    "user_friendly": "This data source doesn't exist in our catalogue."
                }
            )

        return item

    except HTTPException:
        raise
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(
            e,
            context="getting catalogue item",
            endpoint=f"/api/v1/catalogue/{item_id}",
            method="GET"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


def _get_category_description(cat: DataCategory) -> str:
    """Get description for category."""
    descriptions = {
        DataCategory.EXCHANGE_RATES: "Currency exchange rates between major currencies",
        DataCategory.INTEREST_RATES: "Interest rates including overnight rates, LIBOR, SOFR, etc.",
        DataCategory.BANKING: "Banking sector statistics - deposits, loans, reserves",
        DataCategory.STOCKS: "Stock market indices and individual equities",
        DataCategory.BONDS: "Government and corporate bond yields",
        DataCategory.COMMODITIES: "Commodity prices including oil, gold, etc.",
        DataCategory.ECONOMIC_INDICATORS: "GDP, unemployment, inflation, and other economic data",
        DataCategory.MONEY_MARKET: "Money market rates and monetary aggregates",
        DataCategory.CREDIT_MARKETS: "Credit spreads and corporate bond markets",
        DataCategory.DERIVATIVES: "Options, futures, and derivative market data",
        DataCategory.FOREX: "Foreign exchange and currency markets",
        DataCategory.CENTRAL_BANK: "Central bank policy rates and operations",
    }
    return descriptions.get(cat, "")


def _get_region_description(reg: DataRegion) -> str:
    """Get description for region."""
    descriptions = {
        DataRegion.GLOBAL: "Global or cross-regional data",
        DataRegion.NORTH_AMERICA: "United States, Canada, Mexico",
        DataRegion.EUROPE: "European Union and European countries",
        DataRegion.ASIA: "Asian countries including China, Japan, India",
        DataRegion.LATIN_AMERICA: "Central and South American countries",
        DataRegion.MIDDLE_EAST: "Middle Eastern countries",
        DataRegion.AFRICA: "African countries",
    }
    return descriptions.get(reg, "")


def _get_risk_type_description(risk: RiskType) -> str:
    """Get description for risk type."""
    descriptions = {
        RiskType.MARKET_LIQUIDITY: "Ability to buy/sell assets without significant price impact",
        RiskType.FUNDING_LIQUIDITY: "Ability to obtain funding and meet cash obligations",
        RiskType.SYSTEMIC_RISK: "Risk of collapse of entire financial system or market",
        RiskType.OPERATIONAL_RISK: "Risk from failed internal processes or external events",
    }
    return descriptions.get(risk, "")
