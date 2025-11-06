"""Service for World Bank API integration."""

import requests
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from backend.models.country import CountryProfile, CountryIndicator
from backend.schemas.country import CountryProfileCreate, CountryIndicatorCreate

logger = logging.getLogger(__name__)

WORLD_BANK_API_BASE = "https://api.worldbank.org/v2"
OPENDATASOFT_API_BASE = "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/worldbank-country-profile"

# Key indicators to sync
DEFAULT_INDICATORS = {
    # Economic
    "NY.GDP.MKTP.CD": ("GDP (current US$)", "economic"),
    "NY.GDP.PCAP.CD": ("GDP per capita (current US$)", "economic"),
    "NY.GDP.MKTP.KD.ZG": ("GDP growth (annual %)", "economic"),
    "FP.CPI.TOTL.ZG": ("Inflation, consumer prices (annual %)", "economic"),
    "SL.UEM.TOTL.ZS": ("Unemployment, total (% of total labor force)", "economic"),

    # Financial
    "FS.AST.PRVT.GD.ZS": ("Domestic credit to private sector (% of GDP)", "financial"),
    "GC.DOD.TOTL.GD.ZS": ("Central government debt, total (% of GDP)", "financial"),
    "GC.BAL.CASH.GD.ZS": ("Cash surplus/deficit (% of GDP)", "financial"),
    "BN.CAB.XOKA.GD.ZS": ("Current account balance (% of GDP)", "financial"),

    # Social
    "SP.POP.TOTL": ("Population, total", "social"),
    "SP.URB.TOTL.IN.ZS": ("Urban population (% of total)", "social"),

    # Infrastructure
    "IT.CEL.SETS.P2": ("Mobile cellular subscriptions (per 100 people)", "infrastructure"),
    "IT.NET.USER.ZS": ("Individuals using the Internet (% of population)", "infrastructure"),
}


class WorldBankService:
    """Service for syncing data from World Bank API."""

    def __init__(self, db: Session):
        self.db = db
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'BEACON/1.0 (Banking Network Engine)'
        })

    def fetch_country_list(self) -> List[Dict[str, Any]]:
        """Fetch list of all countries from World Bank."""
        try:
            url = f"{WORLD_BANK_API_BASE}/country?format=json&per_page=300"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            data = response.json()
            if len(data) > 1:
                countries = data[1]  # World Bank returns [metadata, data]
                return [c for c in countries if c.get('region', {}).get('value') != 'Aggregates']
            return []
        except Exception as e:
            logger.error(f"Failed to fetch country list: {e}")
            return []

    def fetch_indicator_data(
        self,
        country_code: str,
        indicator_code: str,
        start_year: int = 2000,
        end_year: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch indicator data for a specific country."""
        if end_year is None:
            end_year = datetime.now().year

        try:
            url = (
                f"{WORLD_BANK_API_BASE}/country/{country_code}/indicator/{indicator_code}"
                f"?format=json&date={start_year}:{end_year}&per_page=100"
            )
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            data = response.json()
            if len(data) > 1:
                return data[1] or []
            return []
        except Exception as e:
            logger.error(f"Failed to fetch indicator {indicator_code} for {country_code}: {e}")
            return []

    def fetch_country_profile_opendatasoft(self, country_code: str) -> Dict[str, Any]:
        """Fetch comprehensive country profile from OpenDataSoft."""
        try:
            url = f"{OPENDATASOFT_API_BASE}/records"
            params = {
                "where": f"country_code='{country_code}'",
                "limit": 100
            }
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            return data.get('results', [])
        except Exception as e:
            logger.error(f"Failed to fetch OpenDataSoft data for {country_code}: {e}")
            return []

    def sync_country_profile(self, country_data: Dict[str, Any]) -> Optional[CountryProfile]:
        """Sync a single country profile to database."""
        try:
            country_code = country_data.get('id', '')
            if len(country_code) != 3:
                return None

            # Check if country exists
            existing = self.db.query(CountryProfile).filter(
                CountryProfile.country_code == country_code
            ).first()

            # Extract data
            profile_data = {
                'country_code': country_code,
                'country_name': country_data.get('name', ''),
                'region': country_data.get('region', {}).get('value'),
                'capital': country_data.get('capitalCity'),
                'latitude': country_data.get('latitude'),
                'longitude': country_data.get('longitude'),
                'iso_alpha_3': country_data.get('iso2Code'),
            }

            if existing:
                for key, value in profile_data.items():
                    if value is not None:
                        setattr(existing, key, value)
                existing.last_updated = datetime.utcnow()
                return existing
            else:
                new_profile = CountryProfile(**profile_data)
                self.db.add(new_profile)
                return new_profile

        except Exception as e:
            logger.error(f"Failed to sync country profile: {e}")
            return None

    def sync_indicator(
        self,
        country_code: str,
        indicator_code: str,
        indicator_name: str,
        category: str,
        data_points: List[Dict[str, Any]]
    ) -> int:
        """Sync indicator data to database."""
        records_created = 0

        try:
            for point in data_points:
                if point.get('value') is None:
                    continue

                year = int(point.get('date', 0))
                if year == 0:
                    continue

                # Check if record exists
                existing = self.db.query(CountryIndicator).filter(
                    CountryIndicator.country_code == country_code,
                    CountryIndicator.indicator_code == indicator_code,
                    CountryIndicator.year == year
                ).first()

                if not existing:
                    indicator = CountryIndicator(
                        country_code=country_code,
                        indicator_code=indicator_code,
                        indicator_name=indicator_name,
                        category=category,
                        year=year,
                        value=Decimal(str(point['value'])),
                        source='World Bank',
                        last_updated=datetime.utcnow()
                    )
                    self.db.add(indicator)
                    records_created += 1
                else:
                    existing.value = Decimal(str(point['value']))
                    existing.last_updated = datetime.utcnow()

        except Exception as e:
            logger.error(f"Failed to sync indicator {indicator_code} for {country_code}: {e}")

        return records_created

    def calculate_risk_score(self, country: CountryProfile) -> float:
        """Calculate risk score based on economic indicators."""
        score = 50.0  # Start at medium risk

        try:
            # Debt-to-GDP risk (higher = worse)
            if country.debt_to_gdp:
                debt_ratio = float(country.debt_to_gdp)
                if debt_ratio > 90:
                    score += 20
                elif debt_ratio > 60:
                    score += 10
                elif debt_ratio < 30:
                    score -= 10

            # Inflation risk
            if country.inflation_rate:
                inflation = float(country.inflation_rate)
                if inflation > 10:
                    score += 20
                elif inflation > 5:
                    score += 10
                elif inflation < 2:
                    score += 5  # Deflation risk

            # Unemployment risk
            if country.unemployment_rate:
                unemployment = float(country.unemployment_rate)
                if unemployment > 15:
                    score += 15
                elif unemployment > 10:
                    score += 10

            # GDP growth (negative = risk)
            if country.gdp_growth_rate:
                gdp_growth = float(country.gdp_growth_rate)
                if gdp_growth < -2:
                    score += 15
                elif gdp_growth < 0:
                    score += 10
                elif gdp_growth > 5:
                    score -= 10

            # Credit-to-GDP (too high = bubble risk)
            if country.credit_to_gdp:
                credit_ratio = float(country.credit_to_gdp)
                if credit_ratio > 150:
                    score += 15
                elif credit_ratio > 100:
                    score += 5

            # Current account balance
            if country.current_account_balance:
                ca_balance = float(country.current_account_balance)
                if ca_balance < -5:
                    score += 10

            # Clamp score
            score = max(0, min(100, score))

            # Determine risk level
            if score < 30:
                risk_level = 'low'
            elif score < 60:
                risk_level = 'medium'
            elif score < 80:
                risk_level = 'high'
            else:
                risk_level = 'critical'

            country.risk_score = Decimal(str(score))
            country.risk_level = risk_level

        except Exception as e:
            logger.error(f"Failed to calculate risk score: {e}")

        return score

    def sync_all_countries(
        self,
        country_codes: Optional[List[str]] = None,
        start_year: int = 2000,
        indicators: Optional[Dict[str, tuple]] = None
    ) -> Dict[str, Any]:
        """Sync all countries or specific list."""
        if indicators is None:
            indicators = DEFAULT_INDICATORS

        stats = {
            'countries_synced': 0,
            'indicators_synced': 0,
            'records_created': 0,
            'errors': []
        }

        try:
            # Fetch country list
            countries = self.fetch_country_list()
            if country_codes:
                countries = [c for c in countries if c.get('id') in country_codes]

            logger.info(f"Syncing {len(countries)} countries...")

            for country_data in countries[:50]:  # Limit to 50 for initial sync
                try:
                    # Sync country profile
                    country = self.sync_country_profile(country_data)
                    if not country:
                        continue

                    stats['countries_synced'] += 1

                    # Sync indicators
                    for indicator_code, (indicator_name, category) in indicators.items():
                        data_points = self.fetch_indicator_data(
                            country.country_code,
                            indicator_code,
                            start_year
                        )

                        if data_points:
                            created = self.sync_indicator(
                                country.country_code,
                                indicator_code,
                                indicator_name,
                                category,
                                data_points
                            )
                            stats['records_created'] += created
                            if created > 0:
                                stats['indicators_synced'] += 1

                    # Update country profile with latest indicators
                    self._update_country_from_indicators(country)

                    # Calculate risk score
                    self.calculate_risk_score(country)

                    self.db.commit()

                except Exception as e:
                    logger.error(f"Failed to sync country {country_data.get('id')}: {e}")
                    stats['errors'].append(str(e))
                    self.db.rollback()

        except Exception as e:
            logger.error(f"Failed to sync countries: {e}")
            stats['errors'].append(str(e))

        return stats

    def _update_country_from_indicators(self, country: CountryProfile):
        """Update country profile with latest indicator values."""
        try:
            current_year = datetime.now().year

            # Get latest indicators
            indicators = self.db.query(CountryIndicator).filter(
                CountryIndicator.country_code == country.country_code,
                CountryIndicator.year >= current_year - 2
            ).all()

            # Map indicators to country fields
            indicator_map = {
                'NY.GDP.MKTP.CD': 'gdp_usd',
                'NY.GDP.PCAP.CD': 'gdp_per_capita',
                'NY.GDP.MKTP.KD.ZG': 'gdp_growth_rate',
                'FP.CPI.TOTL.ZG': 'inflation_rate',
                'SL.UEM.TOTL.ZS': 'unemployment_rate',
                'FS.AST.PRVT.GD.ZS': 'credit_to_gdp',
                'GC.DOD.TOTL.GD.ZS': 'debt_to_gdp',
                'GC.BAL.CASH.GD.ZS': 'fiscal_balance',
                'BN.CAB.XOKA.GD.ZS': 'current_account_balance',
                'SP.POP.TOTL': 'population',
            }

            for indicator in indicators:
                field_name = indicator_map.get(indicator.indicator_code)
                if field_name and indicator.value is not None:
                    setattr(country, field_name, indicator.value)

        except Exception as e:
            logger.error(f"Failed to update country from indicators: {e}")
