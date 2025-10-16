"""Data collection module for fetching financial data."""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path
import time # Added import for rate limiting

import yfinance as yf
from fredapi import Fred
from sec_api import QueryApi
from tenacity import retry, stop_after_attempt, wait_exponential

from ..utils.config import Config
from ..utils.logger import get_logger
from ..utils.validation import (
    validate_asset_data,
    validate_indicator_data,
    validate_fred_data
)
from ..utils.cache import DataCache

logger = get_logger(__name__)


class DataCollector:
    """Collects financial data from various sources."""
    
    def __init__(self, config: Config):
        """
        Initialize data collector.

        Args:
            config: Configuration object

        Raises:
            ValueError: If required API keys are not configured
        """
        self.config = config
        self._fred_client = None
        self._sec_client = None
        self.cache = DataCache(config)

        # Validate API keys at initialization
        try:
            fred_key = self.config.get_api_key("FRED")
            if not fred_key or fred_key == "":
                logger.warning("FRED_API_KEY not set. FRED data collection will fail.")
        except Exception as e:
            logger.warning(f"FRED_API_KEY validation failed: {e}")

        try:
            sec_key = self.config.get_api_key("SEC")
            if not sec_key or sec_key == "":
                logger.warning("SEC_API_KEY not set. SEC data collection will fail.")
        except Exception as e:
            logger.warning(f"SEC_API_KEY validation failed: {e}")
    
    @property
    def fred_client(self) -> Fred:
        """Get FRED API client."""
        if self._fred_client is None:
            api_key = self.config.get_api_key("FRED")
            self._fred_client = Fred(api_key=api_key)
        return self._fred_client
    
    @property
    def sec_client(self) -> QueryApi:
        """Get SEC API client."""
        if self._sec_client is None:
            api_key = self.config.get_api_key("SEC")
            self._sec_client = QueryApi(api_key=api_key)
        return self._sec_client
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def download_asset_data(
        self,
        assets: List[str],
        start_date: datetime,
        end_date: datetime,
        batch_size: int = 50
    ) -> pd.DataFrame:
        """
        Download asset price data in batches.
        
        Args:
            assets: List of asset tickers
            start_date: Start date for data
            end_date: End date for data
            batch_size: Number of assets to download at once
            
        Returns:
            DataFrame with asset price data
        """
        logger.info(f"Downloading asset data from {start_date.date()} to {end_date.date()}")
        
        # Check cache first
        cached_data = self.cache.load_data("assets", assets, start_date, end_date)
        if cached_data is not None:
            logger.info("Using cached asset data")
            return cached_data
        
        all_data = []
        
        # Optimize by downloading in batches
        for i in range(0, len(assets), batch_size):
            batch_assets = assets[i:i + batch_size]
            logger.info(f"Downloading batch {i//batch_size + 1}/{(len(assets)-1)//batch_size + 1} ({len(batch_assets)} assets)")
            
            try:
                # Download batch data
                batch_data = yf.download(
                    batch_assets,
                    start=start_date,
                    end=end_date,
                    progress=False,
                    auto_adjust=True
                )
                
                if batch_data.empty:
                    logger.warning(f"No data returned for batch {i//batch_size + 1}")
                    continue
                
                # Process and validate data
                # Handle single vs multi-ticker download structure
                if len(batch_assets) == 1:
                    # Single ticker: yfinance may return simple columns without MultiIndex
                    if not isinstance(batch_data.columns, pd.MultiIndex):
                        # Convert to MultiIndex format for consistent processing
                        batch_data = batch_data.copy()
                        batch_data.columns = pd.MultiIndex.from_product(
                            [batch_data.columns, batch_assets],
                            names=['Metric', 'Asset']
                        )
                        logger.debug(f"Converted single asset data to MultiIndex format")

                # Check if batch_data has a MultiIndex before stacking.
                if isinstance(batch_data.columns, pd.MultiIndex):
                    # Flatten MultiIndex columns: e.g. ('Close', 'JPM') -> ('JPM', 'Close') 
                    batch_data.columns = [(asset, metric) for metric, asset in batch_data.columns.swaplevel()]
                    
                    # Then stack, ensuring 'Asset' is the second level we stack on
                    batch_data = batch_data.stack(level=1, future_stack=True)
                    batch_data = batch_data.rename_axis(["Date", "Asset"]).reset_index()

                    # Rename columns to conform to schema (Close, Volume are present, Open/High/Low might be too)
                    batch_data = batch_data.rename(columns={'Adj Close': 'Close'})
                    
                    # Final cleanup for column names if needed (only keep required schema columns + Asset/Date)
                    required_cols = ['Date', 'Asset', 'Close', 'High', 'Low', 'Open', 'Volume']
                    batch_data = batch_data[[col for col in batch_data.columns if col in required_cols]]
                    
                else:
                    # Fallback if batch_data is not MultiIndex after conversion attempts
                    logger.error(f"Unexpected column structure for batch {i//batch_size + 1}: {batch_data.columns.tolist()}")
                    logger.error(f"Batch assets: {batch_assets}, Data shape: {batch_data.shape}")
                    logger.warning(f"Skipping batch {i//batch_size + 1} due to incompatible data structure")
                    continue


                validation_result = validate_asset_data(batch_data)
                if validation_result["valid"]:
                    all_data.append(validation_result["data"])
                    logger.info(f"Batch {i//batch_size + 1} validation passed")
                else:
                    logger.warning(f"Batch {i//batch_size + 1} validation failed")
                    logger.debug(f"Validation errors: {validation_result['errors']}")
                    
            except Exception as e:
                logger.error(f"Error downloading batch {i//batch_size + 1} for assets {batch_assets}: {e}")
                continue
            
            # CRITICAL FIX: Introduce rate limiting (Supervisor Feedback)
            # Make rate limiting configurable via config
            if i + batch_size < len(assets):
                sleep_time = self.config.get("data.api_rate_limit_seconds", 2.0)
                logger.debug(f"Rate limiting: sleeping for {sleep_time} seconds")
                time.sleep(sleep_time)
        
        if not all_data:
            raise ValueError("No asset data was successfully downloaded")
        
        # Combine all batches
        result = pd.concat(all_data, ignore_index=True)
        
        # Save to cache
        self.cache.save_data(result, "assets", assets, start_date, end_date)
        
        logger.info(f"Successfully downloaded {len(result)} rows of asset data")
        return result
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def download_market_indicators(
        self,
        indicators: List[str],
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """
        Download market indicator data.
        
        Args:
            indicators: List of indicator tickers
            start_date: Start date for data
            end_date: End date for data
            
        Returns:
            DataFrame with indicator data
        """
        logger.info(f"Downloading market indicators from {start_date.date()} to {end_date.date()}")
        
        # Check cache first
        cached_data = self.cache.load_data("indicators", indicators, start_date, end_date)
        if cached_data is not None:
            logger.info("Using cached indicator data")
            return cached_data
        
        # Optimize by downloading all indicators at once
        indicators_str = " ".join(indicators)
        
        try:
            # Data download
            data = yf.download(
                indicators_str,
                start=start_date,
                end=end_date,
                progress=False,
                auto_adjust=True
            )
            
            if data.empty:
                logger.warning("No indicator data returned")
                return pd.DataFrame(columns=["Date"])
            
            # Process data - yfinance often returns MultiIndex structure here too if multiple symbols are requested
            data = data.reset_index()
            
            if isinstance(data.columns, pd.MultiIndex):
                # If multiple indicators, there's usually a multi-index, check if 'Close' is the metric level
                # We will look for the metric level that contains the indicator names
                
                # Flatten if necessary
                if 'Date' not in data.columns:
                    data = data.reset_index()
                
                # If indicators are returned as columns named (Metric, Ticker), we need to flatten/pivot
                # Since we are downloading specific indicators, they are usually columns themselves, possibly nested.
                # For simplicity and robustness, we iterate over requested indicators and check columns directly 
                # after making sure we have a clean set of columns.
                
                # If yfinance returns multiple metrics (Open, High, Low, Close, Volume, Adj Close) for each indicator, 
                # it usually creates a MultiIndex where one level is Metric and the other is Ticker.
                
                # Rename columns to ensure basic structure before validation loop
                new_columns = []
                for col in data.columns:
                    if isinstance(col, tuple) and len(col) == 2:
                        metric, ticker = col
                        if ticker in indicators:
                            ticker = ticker.replace('^', '') # Clean ticker string
                            if metric == 'Adj Close':
                                new_columns.append(ticker)
                            elif metric == 'Close': # Sometimes 'Close' is present, prioritize 'Adj Close' (which yfinance calls 'Close' if auto_adjust=True and the column doesn't exist)
                                new_columns.append(ticker)
                            else:
                                new_columns.append(f"{ticker}_{metric}") # Keep complex ones named
                        else:
                             new_columns.append(col)
                    elif isinstance(col, str) and col in indicators:
                        new_columns.append(col)
                    else:
                        new_columns.append(col)
                data.columns = new_columns
            
            
            # Validate each indicator column
            valid_cols = ["Date"]
            for indicator in indicators:
                # Only test indicators that successfully returned data columns
                clean_indicator = indicator.replace('^', '')
                if clean_indicator in data.columns:
                    indicator_data = data[["Date", clean_indicator]].copy()
                    indicator_data = indicator_data.rename(columns={clean_indicator: "Value"})
                    
                    validation_result = validate_indicator_data(indicator_data)
                    if validation_result["valid"]:
                        # Keep validated data, rename back to original indicator name
                        data[clean_indicator] = validation_result["data"]["Value"]
                        valid_cols.append(clean_indicator)
                        logger.info(f"Indicator {indicator} validation passed")
                    else:
                        logger.warning(f"Indicator {indicator} validation failed")
                        logger.debug(f"Validation errors: {validation_result['errors']}")
                else:
                    logger.warning(f"Indicator {indicator} not found in downloaded data columns.")


            # Final DataFrame only containing Date and successfully validated indicators
            data = data[["Date"] + [col for col in data.columns if col in indicators and col.replace('^','') in valid_cols]]


            # Save to cache
            self.cache.save_data(data, "indicators", indicators, start_date, end_date)
            
            logger.info(f"Successfully downloaded {len(data.columns) - 1} indicators")
            return data
            
        except Exception as e:
            logger.error(f"Error downloading indicators: {e}")
            return pd.DataFrame(columns=["Date"])
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def download_fred_data(
        self,
        indicators: List[str],
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """
        Download economic data from FRED.
        
        Args:
            indicators: List of FRED series IDs
            start_date: Start date for data
            end_date: End date for data
            
        Returns:
            DataFrame with FRED data
        """
        logger.info(f"Downloading FRED data from {start_date.date()} to {end_date.date()}")
        
        # Check cache first
        cached_data = self.cache.load_data("fred", indicators, start_date, end_date)
        if cached_data is not None:
            logger.info("Using cached FRED data")
            return cached_data
        
        all_series = []
        
        for series_id in indicators:
            try:
                logger.info(f"Downloading {series_id} from FRED")
                # Use self.fred_client.get_series which handles date range implicitly if start/end date are passed
                series = self.fred_client.get_series(series_id, start=start_date, end=end_date)
                
                if not series.empty:
                    all_series.append(series.rename(series_id))
                    logger.info(f"Successfully downloaded {series_id}")
                else:
                    logger.warning(f"No data returned for {series_id}")
                    
            except Exception as e:
                logger.error(f"Error downloading {series_id}: {e}")
                continue
        
        if not all_series:
            logger.warning("No FRED data was successfully downloaded")
            return pd.DataFrame(columns=["Date"])
        
        # Combine all series
        result = pd.concat(all_series, axis=1)
        result = result.reset_index().rename(columns={"index": "Date"})
        
        # Forward-fill to handle weekends/holidays
        result = result.ffill()
        
        # Validate data
        validation_result = validate_fred_data(result)
        if validation_result["valid"]:
            # Save to cache
            self.cache.save_data(result, "fred", indicators, start_date, end_date)
            logger.info(f"Successfully downloaded {len(result.columns) - 1} FRED series")
            return validation_result["data"]
        else:
            logger.warning("FRED data validation failed")
            return result
    
    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=8, max=30))
    def download_balance_sheet_data(
        self,
        institutions: List[str],
        financial_facts: List[str]
    ) -> Dict[str, pd.DataFrame]:
        """
        Download balance sheet data from SEC EDGAR.
        
        Args:
            institutions: List of institution tickers
            financial_facts: List of financial facts to fetch
            
        Returns:
            Dictionary mapping institutions to balance sheet data
        """
        logger.info("Downloading balance sheet data from SEC EDGAR")
        
        balance_sheet_data = {}
        
        for institution in institutions:
            logger.info(f"Fetching financial data for {institution}")
            institution_data = {}
            
            for fact in financial_facts:
                query = {
                    "query": {
                        "query_string": {
                            "query": f"ticker:{institution} AND formType:\\"10-K\\" AND concept.name:\\"{fact}\\""
                        }
                    },
                    "from": "0",
                    "size": "20",
                    "sort": [{"filedAt": {"order": "desc"}}]
                }
                
                try:
                    filings = self.sec_client.get_filings(query)
                    
                    points = []
                    for filing in filings["filings"]:
                        # SEC API returns filing date information; we need to structure holdings by specific filing/period end date
                        filing_date = pd.to_datetime(filing["filedAt"])

                        if "xbrl" in filing and "facts" in filing["xbrl"]:
                            for fact_data in filing["xbrl"]["facts"]:
                                if fact_data["concept"]["name"] == fact:
                                    period_end = fact_data["period"].get("end")
                                    if period_end:
                                        points.append({
                                            "Date": pd.to_datetime(period_end),
                                            "Value": fact_data["value"]
                                        })
                    
                    if points:
                        df = pd.DataFrame(points)
                        df = df.drop_duplicates("Date").set_index("Date").sort_index()
                        # Ensure the column name matches the expected output format for future processing
                        df = df.rename(columns={"Value": f"{institution}_{fact}"})
                        institution_data[fact] = df
                        logger.info(f"Successfully fetched {len(points)} data points for {fact} from {institution}")
                    else:
                        logger.warning(f"No data points found for {fact} for {institution}")
                        
                except Exception as e:
                    logger.error(f"Error fetching data for {fact} for {institution}: {e}")
            
            if institution_data:
                # Concatenate all facts for one institution across dates
                # Since we are combining DataFrames indexed by Date with potentially differing lengths, 
                # simple concat will align them automatically by index (Date).
                combined_df = pd.concat(institution_data.values(), axis=1)
                balance_sheet_data[institution] = combined_df
        
        return balance_sheet_data
    
    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=8, max=30))
    def download_holdings_data(
        self,
        major_funds: List[Dict[str, str]],
        assets: List[str]
    ) -> Dict[str, Dict[datetime, List[Dict[str, Any]]]]:
        """
        Download 13F holdings data.
        
        Args:
            major_funds: List of major funds with CIKs
            assets: List of assets to filter holdings by
            
        Returns:
            Dictionary mapping fund names to holdings data by date
        """
        logger.info("Downloading 13F holdings data")
        
        holdings_data = {}
        
        for fund in major_funds:
            fund_name = fund["name"]
            fund_cik = fund["cik"]
            
            logger.info(f"Fetching 13F filings for {fund_name} (CIK: {fund_cik})")
            
            query = {
                "query": {
                    "query_string": {
                        "query": f"cik:{fund_cik} AND formType:\\"13F-HR\\""
                    }
                },
                "from": "0",
                "size": "5",
                "sort": [{"filedAt": {"order": "desc"}}]
            }
            
            try:
                filings = self.sec_client.get_filings(query)
                
                if not filings["filings"]:
                    logger.warning(f"No 13F filings found for {fund_name}")
                    continue
                
                holdings_by_date = {}
                
                for filing in filings["filings"]:
                    filing_date = pd.to_datetime(filing["filedAt"])
                    holdings = []
                    
                    if "holdings" in filing:
                        for holding in filing["holdings"]:
                            # Ticker cleaning is crucial as SEC data can be messy
                            ticker = holding.get("ticker")
                            if ticker and ticker in assets:
                                holdings.append({
                                    "ticker": ticker,
                                    "value": holding.get("value", 0),
                                    "shares": holding.get("shrsOrPrnAmt", {}).get("sshPrnamt", 0)
                                })
                    
                    if holdings:
                        holdings_by_date[filing_date] = holdings
                
                if holdings_by_date:
                    holdings_data[fund_name] = holdings_by_date
                    logger.info(f"Found holdings for {fund_name} on {len(holdings_by_date)} filing dates")
                
            except Exception as e:
                logger.error(f"Error fetching 13F holdings for {fund_name}: {e}")
        
        return holdings_data
    
    def save_data(self, data: pd.DataFrame, filename: str, data_dir: str = None) -> Path:
        """
        Save data to file.
        
        Args:
            data: DataFrame to save
            filename: Name of the file
            data_dir: Directory to save data in (relative path segments)
            
        Returns:
            Path to saved file
        """
        if data_dir is None:
            # Default to /data/processed if not specified (used only by pipeline/main, not cache loading)
            data_dir = Path(__file__).parent.parent.parent.parent.parent / "data" / "processed"
        else:
            # If explicitly passed (e.g., for test data saving), use it
            data_dir = Path(data_dir)
        
        data_dir.mkdir(parents=True, exist_ok=True)
        file_path = data_dir / filename
        
        # Use Parquet for stability if possible, otherwise CSV
        try:
            data.to_parquet(file_path, index=False)
            logger.info(f"Data saved efficiently to {file_path} (Parquet)")
        except Exception:
            data.to_csv(file_path, index=False)
            logger.warning(f"Saved data to {file_path} using CSV fallback")
        
        return file_path
