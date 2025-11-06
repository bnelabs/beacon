"""API routes for country profiles."""

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import List, Optional
from datetime import datetime

from backend.database import get_db
from backend.models.country import CountryProfile, CountryIndicator
from backend.schemas.country import (
    CountryProfileResponse,
    CountryIndicatorResponse,
    CountryListResponse,
    CountrySearchFilters,
    CountryComparisonRequest,
    CountryComparisonResponse,
    WorldBankSyncRequest,
    WorldBankSyncResponse
)
from backend.services.world_bank_service import WorldBankService

router = APIRouter()


@router.get("/", response_model=CountryListResponse)
def list_countries(
    search: Optional[str] = Query(None, description="Search by name or code"),
    region: Optional[str] = Query(None, description="Filter by region"),
    risk_level: Optional[str] = Query(None, description="Filter by risk level"),
    min_gdp: Optional[float] = Query(None, description="Minimum GDP in USD"),
    max_gdp: Optional[float] = Query(None, description="Maximum GDP in USD"),
    min_population: Optional[int] = Query(None, description="Minimum population"),
    has_banking_data: Optional[bool] = Query(None, description="Has bank count data"),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    List all countries with optional filters.

    **For non-technical users:** Browse and filter countries to find the ones
    you want to analyze. You can search by name, filter by region, GDP size,
    or risk level.
    """
    query = db.query(CountryProfile)

    # Apply filters
    if search:
        search_filter = or_(
            CountryProfile.country_name.ilike(f"%{search}%"),
            CountryProfile.country_code.ilike(f"%{search}%")
        )
        query = query.filter(search_filter)

    if region:
        query = query.filter(CountryProfile.region == region)

    if risk_level:
        query = query.filter(CountryProfile.risk_level == risk_level)

    if min_gdp is not None:
        query = query.filter(CountryProfile.gdp_usd >= min_gdp)

    if max_gdp is not None:
        query = query.filter(CountryProfile.gdp_usd <= max_gdp)

    if min_population is not None:
        query = query.filter(CountryProfile.population >= min_population)

    if has_banking_data:
        query = query.filter(CountryProfile.bank_count.isnot(None))

    # Get total count
    total = query.count()

    # Get paginated results
    countries = query.order_by(CountryProfile.country_name).offset(offset).limit(limit).all()

    filters_applied = CountrySearchFilters(
        search=search,
        region=region,
        risk_level=risk_level,
        min_gdp=min_gdp,
        max_gdp=max_gdp,
        min_population=min_population,
        has_banking_data=has_banking_data
    )

    return CountryListResponse(
        total=total,
        countries=countries,
        filters_applied=filters_applied
    )


@router.get("/{country_code}", response_model=CountryProfileResponse)
def get_country(country_code: str, db: Session = Depends(get_db)):
    """
    Get detailed information for a specific country.

    **For non-technical users:** View all available data for a country including
    economic indicators, banking sector info, and risk assessment.
    """
    country = db.query(CountryProfile).filter(
        CountryProfile.country_code == country_code.upper()
    ).first()

    if not country:
        raise HTTPException(status_code=404, detail=f"Country {country_code} not found")

    return country


@router.get("/{country_code}/indicators", response_model=List[CountryIndicatorResponse])
def get_country_indicators(
    country_code: str,
    category: Optional[str] = Query(None, description="Filter by category"),
    indicator_code: Optional[str] = Query(None, description="Specific indicator"),
    start_year: Optional[int] = Query(None, description="Start year"),
    end_year: Optional[int] = Query(None, description="End year"),
    db: Session = Depends(get_db)
):
    """
    Get time series indicators for a country.

    **For non-technical users:** View historical data like GDP growth, inflation,
    and unemployment rates over time. This helps you understand trends.
    """
    query = db.query(CountryIndicator).filter(
        CountryIndicator.country_code == country_code.upper()
    )

    if category:
        query = query.filter(CountryIndicator.category == category)

    if indicator_code:
        query = query.filter(CountryIndicator.indicator_code == indicator_code)

    if start_year:
        query = query.filter(CountryIndicator.year >= start_year)

    if end_year:
        query = query.filter(CountryIndicator.year <= end_year)

    indicators = query.order_by(
        CountryIndicator.indicator_code,
        CountryIndicator.year.desc()
    ).all()

    return indicators


@router.post("/compare", response_model=CountryComparisonResponse)
def compare_countries(
    request: CountryComparisonRequest,
    db: Session = Depends(get_db)
):
    """
    Compare multiple countries side-by-side.

    **For non-technical users:** Select 2-10 countries and see how they compare
    on key metrics like GDP, population, risk level, and banking sector size.
    """
    # Fetch countries
    countries = db.query(CountryProfile).filter(
        CountryProfile.country_code.in_([c.upper() for c in request.country_codes])
    ).all()

    if len(countries) != len(request.country_codes):
        raise HTTPException(
            status_code=404,
            detail="One or more countries not found"
        )

    # Build comparison matrix
    comparison_matrix = {}
    for country in countries:
        comparison_matrix[country.country_code] = {
            'gdp_usd': float(country.gdp_usd) if country.gdp_usd else None,
            'gdp_per_capita': float(country.gdp_per_capita) if country.gdp_per_capita else None,
            'population': country.population,
            'risk_score': float(country.risk_score) if country.risk_score else None,
            'risk_level': country.risk_level,
            'bank_count': country.bank_count,
            'credit_to_gdp': float(country.credit_to_gdp) if country.credit_to_gdp else None,
            'debt_to_gdp': float(country.debt_to_gdp) if country.debt_to_gdp else None,
        }

    # Generate insights
    insights = []
    gdps = [float(c.gdp_usd) for c in countries if c.gdp_usd]
    if gdps:
        max_gdp_country = max(countries, key=lambda c: float(c.gdp_usd) if c.gdp_usd else 0)
        insights.append(f"{max_gdp_country.country_name} has the largest economy with GDP of ${float(max_gdp_country.gdp_usd):,.0f}")

    risk_scores = [(c.country_name, float(c.risk_score)) for c in countries if c.risk_score]
    if risk_scores:
        highest_risk = max(risk_scores, key=lambda x: x[1])
        lowest_risk = min(risk_scores, key=lambda x: x[1])
        insights.append(f"{highest_risk[0]} has the highest risk score ({highest_risk[1]:.1f})")
        insights.append(f"{lowest_risk[0]} has the lowest risk score ({lowest_risk[1]:.1f})")

    return CountryComparisonResponse(
        countries=countries,
        comparison_matrix=comparison_matrix,
        insights=insights,
        created_at=datetime.utcnow()
    )


@router.post("/sync", response_model=WorldBankSyncResponse)
def sync_world_bank_data(
    request: WorldBankSyncRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Sync country data from World Bank API.

    **For non-technical users:** This updates our database with the latest
    economic and financial data from the World Bank. It runs in the background
    and can take a few minutes.

    **Warning:** This is a resource-intensive operation. Use sparingly.
    """
    start_time = datetime.utcnow()

    service = WorldBankService(db)
    stats = service.sync_all_countries(
        country_codes=request.country_codes,
        start_year=request.start_year
    )

    end_time = datetime.utcnow()
    duration = (end_time - start_time).total_seconds()

    return WorldBankSyncResponse(
        status="completed" if not stats['errors'] else "completed_with_errors",
        countries_synced=stats['countries_synced'],
        indicators_synced=stats['indicators_synced'],
        records_created=stats['records_created'],
        records_updated=0,  # TODO: Track updates
        errors=stats['errors'],
        started_at=start_time,
        completed_at=end_time,
        duration_seconds=duration
    )


@router.get("/regions/list")
def list_regions(db: Session = Depends(get_db)):
    """
    Get list of all unique regions.

    **For non-technical users:** See all geographic regions covered in our database.
    """
    regions = db.query(CountryProfile.region).distinct().filter(
        CountryProfile.region.isnot(None)
    ).all()

    return {
        "regions": [r[0] for r in regions if r[0]]
    }


@router.get("/risk-levels/summary")
def risk_levels_summary(db: Session = Depends(get_db)):
    """
    Get summary of countries by risk level.

    **For non-technical users:** See how many countries fall into each risk category
    (low, medium, high, critical).
    """
    from sqlalchemy import func

    summary = db.query(
        CountryProfile.risk_level,
        func.count(CountryProfile.id).label('count')
    ).filter(
        CountryProfile.risk_level.isnot(None)
    ).group_by(CountryProfile.risk_level).all()

    return {
        "summary": [
            {"risk_level": level, "count": count}
            for level, count in summary
        ]
    }
