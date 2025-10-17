"""Populate the data catalogue with comprehensive financial data items."""

import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal, init_db
from models.data_catalogue import DataCatalogueItem, DataCategory, DataRegion, RiskType
from models.data_source import DataSource


def populate_catalogue():
    """Populate comprehensive financial data catalogue."""
    db = SessionLocal()

    try:
        # Clear existing catalogue
        db.query(DataCatalogueItem).delete()
        db.commit()

        # Get or create data sources
        sources = {}
        for source_data in [
            {"name": "ECB", "plugin_type": "ecb", "description": "European Central Bank"},
            {"name": "FRED", "plugin_type": "fred", "description": "Federal Reserve Economic Data"},
            {"name": "Yahoo Finance", "plugin_type": "yfinance", "description": "Yahoo Finance"},
            {"name": "Alpha Vantage", "plugin_type": "alpha_vantage", "description": "Alpha Vantage"},
            {"name": "SEC EDGAR", "plugin_type": "sec_edgar", "description": "SEC Company Filings"},
            {"name": "World Bank", "plugin_type": "world_bank", "description": "World Bank Open Data"},
            {"name": "BIS", "plugin_type": "bis", "description": "Bank for International Settlements"},
            {"name": "IMF", "plugin_type": "imf", "description": "International Monetary Fund Data"},
        ]:
            source = db.query(DataSource).filter(DataSource.name == source_data["name"]).first()
            if not source:
                source = DataSource(
                    name=source_data["name"],
                    plugin_type=source_data["plugin_type"],
                    description=source_data["description"],
                    enabled=True,
                    status="active",
                    config={}
                )
                db.add(source)
                db.commit()
                db.refresh(source)
            sources[source_data["name"]] = source

        # Comprehensive catalogue items
        catalogue_items = [
            # ============================================
            # EXCHANGE RATES - EUROPE
            # ============================================
            {
                "code": "EXR_EUR_USD",
                "name": "EUR/USD Exchange Rate",
                "description": "Euro to US Dollar exchange rate",
                "category": DataCategory.EXCHANGE_RATES,
                "region": DataRegion.EUROPE,
                "risk_types": [RiskType.MARKET_LIQUIDITY.value, RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["ECB"].id,
                "endpoint": "EXR/D.USD.EUR.SP00.A",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "USD per EUR",
                "default_selected": True,
                "priority": 100,
                "tags": ["forex", "major_pair", "europe", "us"]
            },
            {
                "code": "EXR_EUR_GBP",
                "name": "EUR/GBP Exchange Rate",
                "description": "Euro to British Pound exchange rate",
                "category": DataCategory.EXCHANGE_RATES,
                "region": DataRegion.EUROPE,
                "risk_types": [RiskType.MARKET_LIQUIDITY.value],
                "data_source_id": sources["ECB"].id,
                "endpoint": "EXR/D.GBP.EUR.SP00.A",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "GBP per EUR",
                "default_selected": True,
                "priority": 90,
                "tags": ["forex", "major_pair", "europe", "uk"]
            },
            {
                "code": "EXR_EUR_JPY",
                "name": "EUR/JPY Exchange Rate",
                "description": "Euro to Japanese Yen exchange rate",
                "category": DataCategory.EXCHANGE_RATES,
                "region": DataRegion.EUROPE,
                "risk_types": [RiskType.MARKET_LIQUIDITY.value],
                "data_source_id": sources["ECB"].id,
                "endpoint": "EXR/D.JPY.EUR.SP00.A",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "JPY per EUR",
                "default_selected": True,
                "priority": 85,
                "tags": ["forex", "major_pair", "europe", "asia"]
            },
            {
                "code": "EXR_EUR_CHF",
                "name": "EUR/CHF Exchange Rate",
                "description": "Euro to Swiss Franc exchange rate",
                "category": DataCategory.EXCHANGE_RATES,
                "region": DataRegion.EUROPE,
                "risk_types": [RiskType.MARKET_LIQUIDITY.value],
                "data_source_id": sources["ECB"].id,
                "endpoint": "EXR/D.CHF.EUR.SP00.A",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "CHF per EUR",
                "default_selected": True,
                "priority": 80,
                "tags": ["forex", "safe_haven", "europe"]
            },
            {
                "code": "EXR_EUR_CNY",
                "name": "EUR/CNY Exchange Rate",
                "description": "Euro to Chinese Yuan exchange rate",
                "category": DataCategory.EXCHANGE_RATES,
                "region": DataRegion.EUROPE,
                "risk_types": [RiskType.MARKET_LIQUIDITY.value],
                "data_source_id": sources["ECB"].id,
                "endpoint": "EXR/D.CNY.EUR.SP00.A",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "CNY per EUR",
                "default_selected": True,
                "priority": 75,
                "tags": ["forex", "emerging", "asia"]
            },

            # ============================================
            # INTEREST RATES - EUROPE
            # ============================================
            {
                "code": "IR_EONIA",
                "name": "EONIA Rate",
                "description": "Euro OverNight Index Average - Euro area overnight rate",
                "category": DataCategory.INTEREST_RATES,
                "region": DataRegion.EUROPE,
                "risk_types": [RiskType.FUNDING_LIQUIDITY.value, RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["ECB"].id,
                "endpoint": "FM/D.U2.EUR.4F.KR.EON.LEV",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "percentage",
                "default_selected": True,
                "priority": 100,
                "tags": ["money_market", "overnight", "benchmark"]
            },
            {
                "code": "IR_EURIBOR_1M",
                "name": "EURIBOR 1 Month",
                "description": "Euro Interbank Offered Rate - 1 month maturity",
                "category": DataCategory.INTEREST_RATES,
                "region": DataRegion.EUROPE,
                "risk_types": [RiskType.FUNDING_LIQUIDITY.value, RiskType.MARKET_LIQUIDITY.value],
                "data_source_id": sources["ECB"].id,
                "endpoint": "FM/D.U2.EUR.4F.KR.MRR_FR.LEV",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "percentage",
                "default_selected": True,
                "priority": 90,
                "tags": ["money_market", "interbank", "benchmark"]
            },
            {
                "code": "IR_ECB_DEPOSIT",
                "name": "ECB Deposit Facility Rate",
                "description": "ECB deposit facility rate - floor for overnight rates",
                "category": DataCategory.CENTRAL_BANK,
                "region": DataRegion.EUROPE,
                "risk_types": [RiskType.SYSTEMIC_RISK.value, RiskType.FUNDING_LIQUIDITY.value],
                "data_source_id": sources["ECB"].id,
                "endpoint": "FM/D.U2.EUR.4F.KR.DFR.LEV",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "percentage",
                "default_selected": True,
                "priority": 95,
                "tags": ["policy_rate", "central_bank"]
            },

            # ============================================
            # INTEREST RATES - US
            # ============================================
            {
                "code": "IR_SOFR",
                "name": "SOFR Rate",
                "description": "Secured Overnight Financing Rate - US overnight rate",
                "category": DataCategory.INTEREST_RATES,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.FUNDING_LIQUIDITY.value, RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["FRED"].id,
                "endpoint": "SOFR",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "percentage",
                "default_selected": True,
                "priority": 100,
                "tags": ["money_market", "overnight", "benchmark", "us"]
            },
            {
                "code": "IR_FED_FUNDS",
                "name": "Federal Funds Rate",
                "description": "Federal Reserve target federal funds rate",
                "category": DataCategory.CENTRAL_BANK,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.SYSTEMIC_RISK.value, RiskType.FUNDING_LIQUIDITY.value],
                "data_source_id": sources["FRED"].id,
                "endpoint": "FEDFUNDS",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "percentage",
                "default_selected": True,
                "priority": 100,
                "tags": ["policy_rate", "central_bank", "us"]
            },
            {
                "code": "IR_LIBOR_3M",
                "name": "LIBOR 3 Month (Historical)",
                "description": "London Interbank Offered Rate 3 month (discontinued 2023)",
                "category": DataCategory.INTEREST_RATES,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.FUNDING_LIQUIDITY.value],
                "data_source_id": sources["FRED"].id,
                "endpoint": "USD3MTD156N",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "percentage",
                "default_selected": False,
                "priority": 50,
                "tags": ["money_market", "historical", "interbank"]
            },
            {
                "code": "IR_US_10Y",
                "name": "US 10 Year Treasury Yield",
                "description": "US Treasury 10-year constant maturity yield",
                "category": DataCategory.BONDS,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.MARKET_LIQUIDITY.value, RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["FRED"].id,
                "endpoint": "DGS10",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "percentage",
                "default_selected": True,
                "priority": 95,
                "tags": ["bonds", "treasury", "benchmark", "us"]
            },
            {
                "code": "IR_US_2Y",
                "name": "US 2 Year Treasury Yield",
                "description": "US Treasury 2-year constant maturity yield",
                "category": DataCategory.BONDS,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.MARKET_LIQUIDITY.value],
                "data_source_id": sources["FRED"].id,
                "endpoint": "DGS2",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "percentage",
                "default_selected": True,
                "priority": 85,
                "tags": ["bonds", "treasury", "us"]
            },

            # ============================================
            # BANKING & CREDIT - EUROPE
            # ============================================
            {
                "code": "BANK_EU_DEPOSITS",
                "name": "Euro Area Bank Deposits",
                "description": "Total deposits held at monetary financial institutions",
                "category": DataCategory.BANKING,
                "region": DataRegion.EUROPE,
                "risk_types": [RiskType.FUNDING_LIQUIDITY.value, RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["ECB"].id,
                "endpoint": "BSI/M.U2.N.A.L20.A.1.U2.2240.Z01.E",
                "frequency": "monthly",
                "granularity": "macro",
                "unit": "EUR millions",
                "default_selected": True,
                "priority": 85,
                "tags": ["banking", "deposits", "mfi"]
            },
            {
                "code": "BANK_EU_LOANS",
                "name": "Euro Area Bank Loans",
                "description": "Total loans by monetary financial institutions",
                "category": DataCategory.BANKING,
                "region": DataRegion.EUROPE,
                "risk_types": [RiskType.CREDIT_RISK.value, RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["ECB"].id,
                "endpoint": "BSI/M.U2.N.A.A20.A.1.U2.2240.Z01.E",
                "frequency": "monthly",
                "granularity": "macro",
                "unit": "EUR millions",
                "default_selected": True,
                "priority": 85,
                "tags": ["banking", "credit", "loans"]
            },

            # ============================================
            # BANKING & CREDIT - US
            # ============================================
            {
                "code": "BANK_US_RESERVES",
                "name": "US Bank Reserves",
                "description": "Total reserves of depository institutions with Federal Reserve",
                "category": DataCategory.BANKING,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.FUNDING_LIQUIDITY.value, RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["FRED"].id,
                "endpoint": "TOTRESNS",
                "frequency": "weekly",
                "granularity": "macro",
                "unit": "USD millions",
                "default_selected": True,
                "priority": 90,
                "tags": ["banking", "reserves", "federal_reserve"]
            },
            {
                "code": "BANK_US_COMMERCIAL_LOANS",
                "name": "US Commercial & Industrial Loans",
                "description": "Commercial and industrial loans at all commercial banks",
                "category": DataCategory.BANKING,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.CREDIT_RISK.value, RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["FRED"].id,
                "endpoint": "BUSLOANS",
                "frequency": "weekly",
                "granularity": "macro",
                "unit": "USD billions",
                "default_selected": True,
                "priority": 80,
                "tags": ["banking", "credit", "commercial"]
            },
            {
                "code": "CREDIT_US_SPREAD",
                "name": "US Credit Spread (BAA-AAA)",
                "description": "Corporate BAA minus AAA bond yield spread",
                "category": DataCategory.CREDIT_MARKETS,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.MARKET_LIQUIDITY.value, RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["FRED"].id,
                "endpoint": "BAA10Y",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "percentage_points",
                "default_selected": True,
                "priority": 90,
                "tags": ["credit", "spread", "corporate_bonds"]
            },

            # ============================================
            # MONEY MARKET & LIQUIDITY - US
            # ============================================
            {
                "code": "MM_TED_SPREAD",
                "name": "TED Spread",
                "description": "3-month LIBOR minus 3-month Treasury bill rate (credit risk indicator)",
                "category": DataCategory.MONEY_MARKET,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.SYSTEMIC_RISK.value, RiskType.FUNDING_LIQUIDITY.value],
                "data_source_id": sources["FRED"].id,
                "endpoint": "TEDRATE",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "percentage_points",
                "default_selected": True,
                "priority": 95,
                "tags": ["spread", "credit_risk", "systemic"]
            },
            {
                "code": "MM_US_M2",
                "name": "US M2 Money Supply",
                "description": "M2 money stock - broad measure of money supply",
                "category": DataCategory.MONEY_MARKET,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["FRED"].id,
                "endpoint": "M2SL",
                "frequency": "monthly",
                "granularity": "macro",
                "unit": "USD billions",
                "default_selected": True,
                "priority": 80,
                "tags": ["money_supply", "monetary_policy"]
            },

            # ============================================
            # ECONOMIC INDICATORS - US
            # ============================================
            {
                "code": "ECON_US_GDP",
                "name": "US GDP",
                "description": "US Gross Domestic Product",
                "category": DataCategory.ECONOMIC_INDICATORS,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["FRED"].id,
                "endpoint": "GDP",
                "frequency": "quarterly",
                "granularity": "macro",
                "unit": "USD billions",
                "default_selected": True,
                "priority": 90,
                "tags": ["gdp", "economic_growth"]
            },
            {
                "code": "ECON_US_UNEMPLOYMENT",
                "name": "US Unemployment Rate",
                "description": "Civilian unemployment rate",
                "category": DataCategory.ECONOMIC_INDICATORS,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["FRED"].id,
                "endpoint": "UNRATE",
                "frequency": "monthly",
                "granularity": "macro",
                "unit": "percentage",
                "default_selected": True,
                "priority": 85,
                "tags": ["employment", "labor_market"]
            },
            {
                "code": "ECON_US_CPI",
                "name": "US CPI Inflation",
                "description": "Consumer Price Index for All Urban Consumers",
                "category": DataCategory.ECONOMIC_INDICATORS,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["FRED"].id,
                "endpoint": "CPIAUCSL",
                "frequency": "monthly",
                "granularity": "macro",
                "unit": "index",
                "default_selected": True,
                "priority": 85,
                "tags": ["inflation", "prices"]
            },

            # ============================================
            # ECONOMIC INDICATORS - EUROPE
            # ============================================
            {
                "code": "ECON_EU_HICP",
                "name": "Euro Area HICP Inflation",
                "description": "Harmonised Index of Consumer Prices",
                "category": DataCategory.ECONOMIC_INDICATORS,
                "region": DataRegion.EUROPE,
                "risk_types": [RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["ECB"].id,
                "endpoint": "ICP/M.U2.N.000000.4.ANR",
                "frequency": "monthly",
                "granularity": "macro",
                "unit": "percentage",
                "default_selected": True,
                "priority": 85,
                "tags": ["inflation", "prices", "europe"]
            },

            # ============================================
            # STOCKS - MAJOR INDICES
            # ============================================
            {
                "code": "STOCK_SPX",
                "name": "S&P 500 Index",
                "description": "Standard & Poor's 500 stock market index",
                "category": DataCategory.STOCKS,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.MARKET_LIQUIDITY.value, RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["Yahoo Finance"].id,
                "endpoint": "^GSPC",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "index",
                "default_selected": True,
                "priority": 95,
                "tags": ["equity", "index", "us"]
            },
            {
                "code": "STOCK_VIX",
                "name": "VIX Volatility Index",
                "description": "CBOE Volatility Index - market fear gauge",
                "category": DataCategory.STOCKS,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.MARKET_LIQUIDITY.value, RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["Yahoo Finance"].id,
                "endpoint": "^VIX",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "index",
                "default_selected": True,
                "priority": 100,
                "tags": ["volatility", "risk", "derivatives"]
            },
            {
                "code": "STOCK_EUROSTOXX50",
                "name": "Euro Stoxx 50",
                "description": "European blue-chip stock index",
                "category": DataCategory.STOCKS,
                "region": DataRegion.EUROPE,
                "risk_types": [RiskType.MARKET_LIQUIDITY.value],
                "data_source_id": sources["Yahoo Finance"].id,
                "endpoint": "^STOXX50E",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "index",
                "default_selected": True,
                "priority": 90,
                "tags": ["equity", "index", "europe"]
            },
            {
                "code": "STOCK_NIKKEI",
                "name": "Nikkei 225",
                "description": "Japanese stock market index",
                "category": DataCategory.STOCKS,
                "region": DataRegion.ASIA,
                "risk_types": [RiskType.MARKET_LIQUIDITY.value],
                "data_source_id": sources["Yahoo Finance"].id,
                "endpoint": "^N225",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "index",
                "default_selected": True,
                "priority": 85,
                "tags": ["equity", "index", "asia", "japan"]
            },
            {
                "code": "STOCK_HSI",
                "name": "Hang Seng Index",
                "description": "Hong Kong stock market index",
                "category": DataCategory.STOCKS,
                "region": DataRegion.ASIA,
                "risk_types": [RiskType.MARKET_LIQUIDITY.value],
                "data_source_id": sources["Yahoo Finance"].id,
                "endpoint": "^HSI",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "index",
                "default_selected": True,
                "priority": 80,
                "tags": ["equity", "index", "asia", "hong_kong"]
            },

            # ============================================
            # COMMODITIES
            # ============================================
            {
                "code": "COMM_OIL_WTI",
                "name": "WTI Crude Oil",
                "description": "West Texas Intermediate crude oil price",
                "category": DataCategory.COMMODITIES,
                "region": DataRegion.GLOBAL,
                "risk_types": [RiskType.MARKET_LIQUIDITY.value, RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["FRED"].id,
                "endpoint": "DCOILWTICO",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "USD per barrel",
                "default_selected": True,
                "priority": 85,
                "tags": ["commodities", "energy", "oil"]
            },
            {
                "code": "COMM_GOLD",
                "name": "Gold Price",
                "description": "Gold fixing price (London PM)",
                "category": DataCategory.COMMODITIES,
                "region": DataRegion.GLOBAL,
                "risk_types": [RiskType.MARKET_LIQUIDITY.value],
                "data_source_id": sources["FRED"].id,
                "endpoint": "GOLDPMGBD228NLBM",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "USD per troy ounce",
                "default_selected": True,
                "priority": 80,
                "tags": ["commodities", "precious_metals", "safe_haven"]
            },

            # ============================================
            # SEC EDGAR - BANKING SECTOR
            # ============================================
            {
                "code": "SEC_BANK_FINANCIALS",
                "name": "Major Bank Financial Statements",
                "description": "10-K/10-Q filings for major US banks (JPM, BAC, C, WFC, GS, MS)",
                "category": DataCategory.BANKING,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.FUNDING_LIQUIDITY.value, RiskType.CREDIT_RISK.value, RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["SEC EDGAR"].id,
                "endpoint": "filings",
                "frequency": "quarterly",
                "granularity": "micro",
                "unit": "USD",
                "default_selected": True,
                "priority": 95,
                "tags": ["banks", "financials", "10-k", "10-q", "balance_sheet"]
            },
            {
                "code": "SEC_INSTITUTIONAL_HOLDINGS",
                "name": "Institutional Holdings (13F)",
                "description": "13F filings showing institutional investor holdings in banks and financial stocks",
                "category": DataCategory.BANKING,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.MARKET_LIQUIDITY.value, RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["SEC EDGAR"].id,
                "endpoint": "filings",
                "frequency": "quarterly",
                "granularity": "meso",
                "unit": "USD",
                "default_selected": True,
                "priority": 85,
                "tags": ["institutional", "13f", "holdings", "ownership"]
            },

            # ============================================
            # BIS - BANK FOR INTERNATIONAL SETTLEMENTS
            # ============================================
            {
                "code": "BIS_GLOBAL_LIQUIDITY",
                "name": "BIS Global Liquidity Indicators",
                "description": "Global liquidity indicators tracking cross-border credit flows",
                "category": DataCategory.BANKING,
                "region": DataRegion.GLOBAL,
                "risk_types": [RiskType.FUNDING_LIQUIDITY.value, RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["BIS"].id,
                "endpoint": "gli",
                "frequency": "quarterly",
                "granularity": "macro",
                "unit": "USD billions",
                "default_selected": True,
                "priority": 90,
                "tags": ["global", "cross_border", "credit_flows"]
            },
            {
                "code": "BIS_CREDIT_TO_GDP",
                "name": "BIS Credit-to-GDP Gap",
                "description": "Credit-to-GDP gap indicator for systemic risk assessment",
                "category": DataCategory.CREDIT_MARKETS,
                "region": DataRegion.GLOBAL,
                "risk_types": [RiskType.SYSTEMIC_RISK.value, RiskType.CREDIT_RISK.value],
                "data_source_id": sources["BIS"].id,
                "endpoint": "credit_to_gdp",
                "frequency": "quarterly",
                "granularity": "macro",
                "unit": "percentage_points",
                "default_selected": True,
                "priority": 95,
                "tags": ["credit_gap", "early_warning", "systemic"]
            },
            {
                "code": "BIS_DEBT_SERVICE_RATIO",
                "name": "BIS Debt Service Ratio",
                "description": "Debt service ratio tracking debt sustainability",
                "category": DataCategory.CREDIT_MARKETS,
                "region": DataRegion.GLOBAL,
                "risk_types": [RiskType.CREDIT_RISK.value, RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["BIS"].id,
                "endpoint": "dsr",
                "frequency": "quarterly",
                "granularity": "macro",
                "unit": "percentage",
                "default_selected": True,
                "priority": 85,
                "tags": ["debt_sustainability", "household_debt"]
            },

            # ============================================
            # IMF - INTERNATIONAL MONETARY FUND
            # ============================================
            {
                "code": "IMF_FSI",
                "name": "IMF Financial Soundness Indicators",
                "description": "Banking sector financial soundness indicators",
                "category": DataCategory.BANKING,
                "region": DataRegion.GLOBAL,
                "risk_types": [RiskType.SYSTEMIC_RISK.value, RiskType.CREDIT_RISK.value],
                "data_source_id": sources["IMF"].id,
                "endpoint": "fsi",
                "frequency": "quarterly",
                "granularity": "macro",
                "unit": "percentage",
                "default_selected": True,
                "priority": 90,
                "tags": ["financial_stability", "banking_health", "capital_adequacy"]
            },
            {
                "code": "IMF_IFS_RESERVES",
                "name": "IMF International Financial Statistics - Reserves",
                "description": "Foreign exchange reserves and reserve assets",
                "category": DataCategory.CENTRAL_BANK,
                "region": DataRegion.GLOBAL,
                "risk_types": [RiskType.FUNDING_LIQUIDITY.value, RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["IMF"].id,
                "endpoint": "ifs",
                "frequency": "monthly",
                "granularity": "macro",
                "unit": "USD millions",
                "default_selected": True,
                "priority": 85,
                "tags": ["reserves", "forex", "central_bank"]
            },

            # ============================================
            # WORLD BANK - DEVELOPMENT DATA
            # ============================================
            {
                "code": "WB_BANK_CAPITAL_RATIO",
                "name": "World Bank Bank Capital to Assets Ratio",
                "description": "Bank regulatory capital to risk-weighted assets",
                "category": DataCategory.BANKING,
                "region": DataRegion.GLOBAL,
                "risk_types": [RiskType.SYSTEMIC_RISK.value, RiskType.CREDIT_RISK.value],
                "data_source_id": sources["World Bank"].id,
                "endpoint": "FB.BNK.CAPA.ZS",
                "frequency": "annual",
                "granularity": "macro",
                "unit": "percentage",
                "default_selected": True,
                "priority": 80,
                "tags": ["capital_adequacy", "regulatory_capital"]
            },
            {
                "code": "WB_BANK_NPL",
                "name": "World Bank Bank Non-Performing Loans",
                "description": "Bank nonperforming loans to gross loans ratio",
                "category": DataCategory.CREDIT_MARKETS,
                "region": DataRegion.GLOBAL,
                "risk_types": [RiskType.CREDIT_RISK.value, RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["World Bank"].id,
                "endpoint": "FB.AST.NPER.ZS",
                "frequency": "annual",
                "granularity": "macro",
                "unit": "percentage",
                "default_selected": True,
                "priority": 90,
                "tags": ["credit_quality", "npl", "loan_quality"]
            },
            {
                "code": "WB_DOMESTIC_CREDIT",
                "name": "World Bank Domestic Credit to Private Sector",
                "description": "Domestic credit provided by financial sector",
                "category": DataCategory.CREDIT_MARKETS,
                "region": DataRegion.GLOBAL,
                "risk_types": [RiskType.CREDIT_RISK.value, RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["World Bank"].id,
                "endpoint": "FS.AST.PRVT.GD.ZS",
                "frequency": "annual",
                "granularity": "macro",
                "unit": "percentage_of_gdp",
                "default_selected": True,
                "priority": 80,
                "tags": ["domestic_credit", "private_sector"]
            },

            # ============================================
            # ADDITIONAL FRED INDICATORS
            # ============================================
            {
                "code": "FRED_REPO_RATE",
                "name": "US Overnight Repo Rate",
                "description": "Overnight repurchase agreement rate",
                "category": DataCategory.MONEY_MARKET,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.FUNDING_LIQUIDITY.value, RiskType.MARKET_LIQUIDITY.value],
                "data_source_id": sources["FRED"].id,
                "endpoint": "RRPONTSYD",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "percentage",
                "default_selected": True,
                "priority": 90,
                "tags": ["repo", "money_market", "funding"]
            },
            {
                "code": "FRED_BANK_ASSETS",
                "name": "US Total Bank Assets",
                "description": "Total assets of all commercial banks",
                "category": DataCategory.BANKING,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["FRED"].id,
                "endpoint": "TLAACBW027SBOG",
                "frequency": "weekly",
                "granularity": "macro",
                "unit": "USD billions",
                "default_selected": True,
                "priority": 85,
                "tags": ["banking", "assets", "size"]
            },
            {
                "code": "FRED_FED_BALANCE_SHEET",
                "name": "Federal Reserve Balance Sheet",
                "description": "Total assets of the Federal Reserve",
                "category": DataCategory.CENTRAL_BANK,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.SYSTEMIC_RISK.value, RiskType.FUNDING_LIQUIDITY.value],
                "data_source_id": sources["FRED"].id,
                "endpoint": "WALCL",
                "frequency": "weekly",
                "granularity": "macro",
                "unit": "USD billions",
                "default_selected": True,
                "priority": 95,
                "tags": ["central_bank", "balance_sheet", "qe"]
            },
            {
                "code": "FRED_LIBOR_OIS_SPREAD",
                "name": "LIBOR-OIS Spread (Historical)",
                "description": "3-month LIBOR minus OIS spread - credit risk indicator",
                "category": DataCategory.MONEY_MARKET,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.FUNDING_LIQUIDITY.value, RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["FRED"].id,
                "endpoint": "THREEFYTP03",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "percentage_points",
                "default_selected": False,
                "priority": 60,
                "tags": ["spread", "credit_risk", "historical"]
            },
            {
                "code": "FRED_COMMERCIAL_PAPER",
                "name": "US Commercial Paper Outstanding",
                "description": "Total commercial paper outstanding",
                "category": DataCategory.MONEY_MARKET,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.FUNDING_LIQUIDITY.value, RiskType.MARKET_LIQUIDITY.value],
                "data_source_id": sources["FRED"].id,
                "endpoint": "COMPOUT",
                "frequency": "weekly",
                "granularity": "macro",
                "unit": "USD billions",
                "default_selected": True,
                "priority": 85,
                "tags": ["commercial_paper", "short_term_funding"]
            },
            {
                "code": "FRED_FINANCIAL_STRESS",
                "name": "St. Louis Fed Financial Stress Index",
                "description": "Weekly financial stress indicator",
                "category": DataCategory.ECONOMIC_INDICATORS,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.SYSTEMIC_RISK.value, RiskType.MARKET_LIQUIDITY.value],
                "data_source_id": sources["FRED"].id,
                "endpoint": "STLFSI2",
                "frequency": "weekly",
                "granularity": "macro",
                "unit": "index",
                "default_selected": True,
                "priority": 100,
                "tags": ["stress_index", "systemic_risk", "early_warning"]
            },
            {
                "code": "FRED_MOVE_INDEX",
                "name": "MOVE Index (Bond Market Volatility)",
                "description": "Merrill Lynch Option Volatility Estimate Index - bond market volatility",
                "category": DataCategory.BONDS,
                "region": DataRegion.NORTH_AMERICA,
                "risk_types": [RiskType.MARKET_LIQUIDITY.value, RiskType.SYSTEMIC_RISK.value],
                "data_source_id": sources["FRED"].id,
                "endpoint": "MOVE",
                "frequency": "daily",
                "granularity": "macro",
                "unit": "index",
                "default_selected": True,
                "priority": 90,
                "tags": ["volatility", "bonds", "risk"]
            },
        ]

        # Insert all catalogue items
        for item_data in catalogue_items:
            item = DataCatalogueItem(**item_data)
            db.add(item)

        db.commit()
        print(f"✅ Successfully populated catalogue with {len(catalogue_items)} items")

        # Print summary
        print("\n📊 Catalogue Summary:")
        for category in DataCategory:
            count = db.query(DataCatalogueItem).filter(DataCatalogueItem.category == category).count()
            print(f"  - {category.value}: {count} items")

        print("\n🌍 Regional Distribution:")
        for region in DataRegion:
            count = db.query(DataCatalogueItem).filter(DataCatalogueItem.region == region).count()
            print(f"  - {region.value}: {count} items")

        default_count = db.query(DataCatalogueItem).filter(DataCatalogueItem.default_selected == True).count()
        print(f"\n⭐ Default selected items: {default_count}")

    except Exception as e:
        print(f"❌ Error populating catalogue: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("🚀 Initializing database...")
    init_db()
    print("📚 Populating data catalogue...")
    populate_catalogue()
    print("✅ Done!")
