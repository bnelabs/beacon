"""Data processing and feature engineering module."""

import pandas as pd
import numpy as np
import torch
from datetime import datetime
from typing import List, Dict, Any, Tuple
from torch.utils.data import Dataset, DataLoader

from sklearn.preprocessing import MinMaxScaler

from ..utils.config import Config
from ..utils.logger import get_logger

logger = get_logger(__name__)


class LiquidityDataset(Dataset):
    """Custom Dataset for handling time series data samples."""
    def __init__(self, sequences_by_asset, assets, asset_to_idx, look_back):
        self.sequences_by_asset = sequences_by_asset
        self.assets = assets
        self.asset_to_idx = asset_to_idx
        self.look_back = look_back
        
        self.all_sequences = []
        for asset in assets:
            if asset in sequences_by_asset:
                for seq_data in sequences_by_asset[asset]:
                    self.all_sequences.append({
                        'asset': asset,
                        'sequence': seq_data['sequence'],
                        'target': seq_data['target'],
                        'date': seq_data['date']
                    })
        # Sort by date to ensure temporal ordering when loaded in batch
        self.all_sequences.sort(key=lambda x: x['date'])
    
    def __len__(self):
        return len(self.all_sequences)
    
    def __getitem__(self, idx):
        return self.all_sequences[idx]


def collate_fn(batch, look_back, num_assets, asset_to_idx):
    """
    Custom collate function to handle jagged sequences and pad to the max number of assets.
    
    This function assumes the batch data structure derived from the original script logic
    which seems to imply that `num_features` should be inferred from the sequence shape, 
    and we need an index mapping for assets present in the batch to place them correctly.
    """
    if not batch:
        return None, None, []

    # Determine features dimensions from the first sequence item that exists
    first_item = next((item for item in batch if item['asset'] in asset_to_idx), None)
    if not first_item:
         # This case implies batch contains assets not accounted for in asset_to_idx mapping (which shouldn't happen if pre-filtered correctly)
         return None, None, []
         
    num_features = first_item['sequence'].shape[1] 
    
    batch_size = len(batch)
    
    # Initialize tensors: [batch_size, num_assets, look_back, num_features]
    x_batch = torch.zeros(batch_size, num_assets, look_back, num_features, dtype=torch.float)
    # Initialize targets: [batch_size, num_assets]
    y_batch = torch.zeros(batch_size, num_assets, dtype=torch.float)
    dates = []
    
    for i, item in enumerate(batch):
        asset = item['asset']
        if asset not in asset_to_idx:
            logger.warning(f"Asset {asset} not found in asset index mapping during collation, skipping batch item {i}.")
            continue
            
        asset_idx = asset_to_idx[asset]
        
        # Place sequence data
        x_batch[i, asset_idx, :, :] = torch.tensor(item['sequence'], dtype=torch.float)
        # Place target data
        y_batch[i, asset_idx] = item['target']
        dates.append(item['date'])
        
    return x_batch, y_batch, dates


class DataProcessor:
    """Processes and engineers features from raw data."""
    
    def __init__(self, config: Config):
        """
        Initialize data processor.
        
        Args:
            config: Configuration object
        """
        self.config = config
        self.epsilon = self.config.get("data.numerical_stability_epsilon", 1e-9)
    
    def clean_data(self, data: pd.DataFrame, critical_cols: List[str]) -> pd.DataFrame:
        """
        Clean and prepare raw data.
        
        Args:
            data: Raw DataFrame
            critical_cols: Columns that must not be null
            
        Returns:
            Cleaned DataFrame
        """
        logger.info("Cleaning data")
        
        # Ensure Date parsing consistency before grouping
        if 'Date' in data.columns:
            data['Date'] = pd.to_datetime(data['Date'])

        # Get columns that are not Date or Asset
        non_asset_cols = [col for col in data.columns if col not in ["Date", "Asset"]]
        
        # Group by Asset and forward-fill
        data[non_asset_cols] = data.groupby("Asset")[non_asset_cols].ffill()
        
        # Drop rows with NaN values in critical columns
        initial_rows = len(data)
        data = data.dropna(subset=critical_cols)
        dropped_rows = initial_rows - len(data)
        
        if dropped_rows > 0:
            logger.info(f"Dropped {dropped_rows} rows with missing critical data")
        
        data = data.reset_index(drop=True)
        logger.info("Data cleaning complete")
        
        return data
    
    def process_balance_sheet_data(
        self,
        balance_sheet_data: Dict[str, pd.DataFrame],
        all_data: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Process and merge balance sheet data.
        
        Args:
            balance_sheet_data: Dictionary of balance sheet DataFrames
            all_data: Main price data DataFrame
            
        Returns:
            DataFrame with merged balance sheet data
        """
        logger.info("Processing balance sheet data")
        
        if not balance_sheet_data or all_data.empty:
            logger.warning("No balance sheet data or main data to process.")
            return all_data
        
        # Create a daily date range from existing data
        daily_dates = pd.date_range(
            start=all_data["Date"].min(),
            end=all_data["Date"].max(),
            freq="D"
        )
        
        # For joining BS data, we process it across dates first
        all_bs_data_frames = []
        
        for institution, df in balance_sheet_data.items():
            if not df.empty:
                # Reindex to daily frequency and forward-fill for this institution's features
                if df.index.name != 'Date':
                     df = df.reset_index().rename(columns={'index': 'Date'})
                
                # Merge with daily dates to ensure alignment, then re-index asset-wise in the final merge
                df_daily = df.reindex(daily_dates, method="ffill")
                
                # Need to map these financial facts back to their originating asset/entity
                # Since balance sheet data is currently indexed by Date only, we temporarily add 'Asset' column 
                # based on which institution it belongs to, for ultimate merge in the main DataFrame.
                df_daily['Asset'] = institution 
                all_bs_data_frames.append(df_daily)
            else:
                logger.warning(f"No balance sheet data for {institution}")
        
        if not all_bs_data_frames:
            return all_data

        # Combine all institutions' daily balance sheet data
        daily_bs_df = pd.concat(all_bs_data_frames, ignore_index=False) # Keep index (Date) for merging
        
        # Merge aggregated BS data back onto main time series data
        all_data = pd.merge(all_data, daily_bs_df.reset_index(), on=["Date", "Asset"], how="left")
        
        # Clean up NaNs created by the merge (forward filling asset-specific data is handled below if needed, 
        # but since the BS data itself was already ffilled daily, we rely on that for structure)
        
        logger.info("Balance sheet data processing complete")
        return all_data
    
    def engineer_features(
        self,
        data: pd.DataFrame,
        institutions: List[str],
        financial_facts: List[str],
        economic_indicators: List[str]
    ) -> Tuple[pd.DataFrame, List[str], int]:
        """
        Engineer features from raw data.
        
        Args:
            data: Input DataFrame
            institutions: List of institutions for balance sheet features
            financial_facts: List of financial facts
            economic_indicators: List of economic indicators
            
        Returns:
            Tuple of (processed DataFrame, feature list, number of features)
        """
        logger.info("Engineering features")
        
        # Calculate basic features
        pct_change = data.groupby("Asset")["Close"].pct_change()
        data["Volatility"] = (
            pct_change
            .rolling(window=10)
            .std()
        )
        
        data["Avg_Volume"] = (
            data.groupby("Asset")["Volume"]
            .transform(lambda x: x.rolling(window=10).mean())
        )
        
        # Improved numerical stability for Amihud illiquidity
        data["Amihud"] = (
            pct_change.abs() / 
            (data["Volume"] + self.epsilon)
        )
        
        data["Spread_Proxy"] = (data["High"] - data["Low"]) / (data["Close"] + self.epsilon)
        
        # Calculate liquidity score with improved stability
        data["Liquidity_Score"] = (
            data["Avg_Volume"] / 
            ((data["Volatility"] + self.epsilon) * (data["Close"] + self.epsilon))
        ).fillna(0).replace([np.inf, -np.inf], 0)
        
        # Create target variable: Liquidity 7 days forward, log-transformed average of next 7 days
        data["Target_Liquidity_7D"] = (
            data.groupby("Asset")["Liquidity_Score"]
            .transform(lambda x: x.shift(-7).rolling(window=7).mean())
        )
        
        # Create balance sheet features
        self._create_balance_sheet_features(data, institutions, financial_facts)
        
        # Create market indicator features
        self._create_market_indicator_features(data)
        
        # Define feature list (must include indicators if they exist in data)
        base_features = [
            "Close", "Volume", "Volatility", "Avg_Volume", "Amihud", "Spread_Proxy",
        ]
        
        # Indicator features based on config/presence
        indicator_features = []
        if "^VIX" in data.columns:
            indicator_features.extend(["VIX", "VIX_Change_1D", "VIX_Change_5D"])
        if "DGS10" in data.columns and "DGS2" in data.columns:
            indicator_features.append("Yield_Curve_Spread")
        if "TEDRATE" in data.columns:
            indicator_features.append("TED_Spread")
        
        # Add balance sheet features that should exist if institutions were in config
        bs_features = ["Total_Assets", "Debt_to_Equity", "Cash_Ratio"]
        
        features = base_features + indicator_features + bs_features
        
        # Filter to only existing features used for input (excluding target/Date/Asset)
        features = [f for f in features if f in data.columns and f not in ["Date", "Asset", "Target_Liquidity_7D"]]
        num_features = len(features)
        
        logger.info(f"Feature engineering complete. Created {num_features} features")
        
        return data, features, num_features
    
    def _create_balance_sheet_features(
        self,
        data: pd.DataFrame,
        institutions: List[str],
        financial_facts: List[str]
    ):
        """Create features from balance sheet data and forward-fill across assets."""
        logger.info("Creating balance sheet features")
        
        # Total assets feature - sum across similar entity types (since BS measures are institution-specific)
        # NOTE: In the original setup, institution names are used as asset identifiers temporarily during merge, 
        # but they should map correctly based on the merge logic in process_balance_sheet_data.
        # Since BS data is merged based on institution/asset name, we can assume institution names are present in 'Asset' column contextually.
        
        # Total assets feature (Simple cumulative sum for now, should ideally be averaged across assets of that type)
        # For simplification matching original intent: Total_Assets will hold the specific asset's (institution's) total assets value ffilled.
        for institution in institutions:
            assets_col = f"{institution}_Assets"
            if assets_col in data.columns:
                # Ffill is already done daily in process_balance_sheet_data, but we ensure it aligns with the current asset row
                mask = data["Asset"] == institution
                data.loc[mask, "Total_Assets"] = data.loc[mask, assets_col]
        
        # Debt-to-equity ratio
        for institution in institutions:
            assets_col = f"{institution}_Assets"
            equity_col = f"{institution}_StockholdersEquity"
            debt_col = f"{institution}_LongTermDebt"
            
            if all(col in data.columns for col in [assets_col, equity_col, debt_col]):
                mask = data["Asset"] == institution
                # Ensure denominator is not zero
                data.loc[mask, "Debt_to_Equity"] = (
                    data.loc[mask, debt_col] / 
                    (data.loc[mask, equity_col] + self.epsilon)
                ).fillna(0)
        
        # Cash ratio
        for institution in institutions:
            cash_col = f"{institution}_CashAndCashEquivalentsAtCarryingValue"
            short_term_debt_col = f"{institution}_ShortTermDebt"
            
            if all(col in data.columns for col in [cash_col, short_term_debt_col]):
                mask = data["Asset"] == institution
                data.loc[mask, "Cash_Ratio"] = (
                    data.loc[mask, cash_col] / 
                    (data.loc[mask, short_term_debt_col] + self.epsilon)
                ).fillna(0)

        # Forward fill these specific features across ALL assets, as they are macroeconomic/firm-level features that should propagate if missing temporarily.
        bs_features_created = [f"Total_Assets", "Debt_to_Equity", "Cash_Ratio"]
        for feat in bs_features_created:
             if feat in data.columns:
                 # Fill NaN values within each asset group for these features, then apply a final bfill across all assets if needed.
                 data[feat] = data.groupby('Asset')[feat].ffill().bfill()
        
    
    def _create_market_indicator_features(self, data: pd.DataFrame):
        """Create features from market indicators."""
        logger.info("Creating market indicator features")
        
        # VIX features (applied across all assets as they are market-wide risks)
        if "^VIX" in data.columns:
            data["VIX"] = data["^VIX"]
            data["VIX_Change_1D"] = data["VIX"].pct_change(1)
            data["VIX_Change_5D"] = data["VIX"].pct_change(5)
        
        # Yield curve spread
        if all(col in data.columns for col in ["DGS10", "DGS2"]):
            data["Yield_Curve_Spread"] = data["DGS10"] - data["DGS2"]
        
        # TED spread
        if "TEDRATE" in data.columns:
            data["TED_Spread"] = data["TEDRATE"]
            
        # Forward fill market indicators across all assets ensures every asset row has the indicator data
        current_cols = ["VIX", "VIX_Change_1D", "VIX_Change_5D", "Yield_Curve_Spread", "TED_Spread"]
        for col in current_cols:
            if col in data.columns:
                data[col] = data.groupby('Asset')[col].ffill().bfill()
    
    def prepare_sequences(
        self,
        data: pd.DataFrame,
        features: List[str],
        look_back: int,
        scalers: Dict[str, MinMaxScaler] = None
    ) -> Tuple[Dict[str, List[Dict]], List[str], Dict[str, MinMaxScaler]]:
        """
        Prepare sequences for time series modeling.
        
        Args:
            data: Input DataFrame (must contain Date, Asset, Target_Liquidity_7D, and features)
            features: List of feature columns
            look_back: Look-back window for sequences
            scalers: Pre-fitted scalers for each asset
            
        Returns:
            Tuple of (sequences by asset, valid assets, scalers)
        """
        logger.info("Preparing sequences for modeling")
        
        valid_assets = []
        sequences_by_asset = {}
        train_scalers = {} if scalers is None else scalers
        
        # Pre-calculate asset-to-index map based on the entire dataset's unique assets 
        # used for padding in collate_fn, but for sequence generation, we only care about seen assets.
        # We will generate scalers per asset for correct feature scaling independent of other assets.
        
        all_unique_assets = data["Asset"].unique()
        
        for asset in all_unique_assets:
            logger.debug(f"Processing {asset}")
            asset_data = data[data["Asset"] == asset].sort_values("Date").copy()
            
            # 1. Check for sufficiency and drop rows where Target is NaN (future data)
            asset_data = asset_data.dropna(subset=["Target_Liquidity_7D"])
            asset_data = asset_data.reset_index(drop=True)
            
            if len(asset_data) < look_back:
                logger.debug(f"Skipping {asset}: insufficient data points after target lookup ({len(asset_data)} available)")
                continue
            
            # 2. Feature cleaning: Drop rows where input features are NaN
            asset_data_clean = asset_data.dropna(subset=features)
            
            if len(asset_data_clean) < look_back:
                 logger.debug(f"Skipping {asset}: insufficient data points after feature cleaning ({len(asset_data_clean)} available)")
                 continue
                 
            asset_data_clean = asset_data_clean.reset_index(drop=True)
            
            # 3. Scale features
            if scalers and asset in scalers:
                scaler = scalers[asset]
                asset_data_clean[features] = scaler.transform(asset_data_clean[features])
            else:
                scaler = MinMaxScaler()
                asset_data_clean[features] = scaler.fit_transform(asset_data_clean[features])
                train_scalers[asset] = scaler # Store scaler only if fitting (i.e., creation mode)
            
            # 4. Create sequences
            sequences = []
            # We look back L steps, and the target corresponds to the L-th step after the window ends
            for i in range(len(asset_data_clean) - look_back):
                sequence = asset_data_clean[features].iloc[i:i+look_back].values
                
                # Target corresponds to the state *after* the lookback window ends
                target_value = asset_data_clean["Target_Liquidity_7D"].iloc[i+look_back] 
                sequence_end_date = asset_data_clean["Date"].iloc[i+look_back]
                
                if np.isfinite(target_value):
                    sequences.append({
                        "sequence": sequence,
                        "target": np.log1p(target_value),
                        "date": sequence_end_date
                    })
            
            if sequences:
                sequences_by_asset[asset] = sequences
                valid_assets.append(asset)
        
        if not sequences_by_asset:
            raise ValueError("No sequences could be created from the data")
        
        logger.info(f"Prepared sequences for {len(valid_assets)} assets")
        
        return sequences_by_asset, valid_assets, train_scalers
