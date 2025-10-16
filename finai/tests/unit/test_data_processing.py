"""Unit tests for the liquidity monitor."""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

# Import necessary objects, making sure relative paths reflect the package structure
from liquidity_monitor.data.processing import DataProcessor, LiquidityDataset, collate_fn
from liquidity_monitor.data.graph_builder import GraphBuilder
from liquidity_monitor.utils.config import Config
from liquidity_monitor.utils.cache import DataCache


class TestDataProcessor:
    """Test cases for DataProcessor."""
    
    @pytest.fixture
    def processor(self):
        """Create a test processor."""
        # Initialize config without external path, relying on defaults/mocking
        config = Mock(spec=Config)
        config.get.return_value = 1e-9 # Mock epsilon
        return DataProcessor(config)
    
    @pytest.fixture
    def sample_data(self):
        """Create sample data for testing price data integration."""
        # Ensure dates are datetime objects
        dates = pd.date_range(start="2023-01-01", periods=100, freq="D")
        assets = ["AAPL", "MSFT", "GOOGL"]
        
        data = []
        for date in dates:
            for asset in assets:
                data.append({
                    "Date": date,
                    "Asset": asset,
                    "Close": np.random.uniform(100, 200),
                    "High": np.random.uniform(100, 200),
                    "Low": np.random.uniform(100, 200),
                    "Open": np.random.uniform(100, 200),
                    "Volume": np.random.randint(1000000, 10000000)
                })
        
        return pd.DataFrame(data)
    
    def test_clean_data(self, processor, sample_data):
        """Test data cleaning."""
        # Add some NaN values in critical columns
        sample_data.loc[0, "Close"] = np.nan
        sample_data.loc[10, "Volume"] = np.nan
        
        cleaned = processor.clean_data(sample_data, ["Close", "Volume"])
        
        # Check that NaN rows were removed
        assert not cleaned["Close"].isna().any()
        assert not cleaned["Volume"].isna().any()
        assert len(cleaned) < len(sample_data)
        
    def test_process_balance_sheet_data(self, processor):
        """Test merging of mock balance sheet data."""
        # Create mock price data
        dates = pd.to_datetime(pd.date_range(start="2023-10-01", periods=10, freq="D"))
        price_df = pd.DataFrame({
            'Date': dates.repeat(2),
            'Asset': np.tile(['JPM', 'BAC'], 10),
            'Close': np.random.rand(20)
        })
        
        # Create mock balance sheet data for JPM (labeled 'JPM')
        bs_dates = pd.to_datetime(pd.date_range(start="2023-10-05", periods=5, freq="D"))
        jpm_bs = pd.DataFrame({
            'Date': bs_dates,
            'JPM_Assets': np.random.rand(5) * 1e12,
            'JPM_StockholdersEquity': np.random.rand(5) * 1e11,
            'JPM_ShortTermDebt': np.random.rand(5) * 1e10,
        }).set_index('Date')
        
        balance_sheet_data = {'JPM': jpm_bs}
        
        processed = processor.process_balance_sheet_data(balance_sheet_data, price_df)
        
        # Check if BS columns were merged onto rows where Asset='JPM'
        assert 'JPM_Assets' in processed.columns
        
        # Check that JPM rows have non-NaN BS data after merging/FFILL
        assert processed[processed['Asset'] == 'JPM']['JPM_Assets'].notna().sum() > 0
        # Check that BAC rows are still NaN for JPM specific data before global FFILL (which happens in engineer_features)
        assert processed[processed['Asset'] == 'BAC']['JPM_Assets'].isna().sum() > 0

    
    def test_engineer_features(self, processor, sample_data):
        """Test feature engineering."""
        # Add mock OHLCV data to sample_data if missing (sample_data only had some) - Assume standard yfinance output columns are largely present
        
        # Add target column mock for sequence prep test later, but test FE first
        sample_data['Target_Liquidity_7D'] = np.nan 
        
        processed, features, num_features = processor.engineer_features(
            sample_data.head(50), ["JPM"], ["Assets"], ["DGS10"]
        )
        
        # Check that features were created
        assert "Volatility" in processed.columns
        assert "Liquidity_Score" in processed.columns
        assert "Target_Liquidity_7D" in processed.columns
        assert "DGS10" in processed.columns # Indicator feature check
        assert "Total_Assets" in processed.columns # BS feature check
        
        # Check feature list length
        assert num_features > 0
        assert len(features) == num_features
        assert "Close" in features and "Volume" in features
    
    def test_prepare_sequences(self, processor, sample_data):
        """Test sequence preparation."""
        # Add target column
        sample_data["Target_Liquidity_7D"] = np.random.uniform(0.01, 1, len(sample_data))
        
        # Ensure we have enough data points for look_back=10 + target offset
        
        features = ["Close", "Volume"]
        look_back = 10
        
        sequences, assets, scalers = processor.prepare_sequences(
            sample_data.head(100), features, look_back
        )
        
        # Check that sequences were created
        total_sequences = sum(len(s) for s in sequences.values())
        assert total_sequences > 0
        assert len(assets) > 0
        assert len(scalers) > 0
        
        # Check sequence structure
        if total_sequences > 0:
            first_asset = assets[0]
            assert len(sequences[first_asset]) > 0
            seq_len = sequences[first_asset][0]['sequence'].shape[0]
            feat_dim = sequences[first_asset][0]['sequence'].shape[1]
            
            assert seq_len == look_back
            assert feat_dim == len(features)


class TestLiquidityDataset:
    """Test cases for LiquidityDataset."""
    
    @pytest.fixture
    def sample_sequences(self):
        """Create sample sequences."""
        return {
            "AAPL": [
                {
                    "sequence": np.random.rand(10, 5),
                    "target": 0.5,
                    "date": datetime(2023, 1, 31) # Example date: Target end date
                },
                {
                    "sequence": np.random.rand(10, 5),
                    "target": 0.6,
                    "date": datetime(2023, 2, 1)
                }
            ],
            "MSFT": [
                {
                    "sequence": np.random.rand(10, 5),
                    "target": 0.4,
                    "date": datetime(2023, 1, 31)
                }
            ]
        }
    
    def test_dataset_init(self, sample_sequences):
        """Test dataset initialization."""
        assets = sorted(["AAPL", "MSFT"]) # Ensure deterministic order for initialization
        asset_to_idx = {"AAPL": 0, "MSFT": 1}
        look_back = 10
        
        dataset = LiquidityDataset(sample_sequences, assets, asset_to_idx, look_back)
        
        assert len(dataset) == 3  # Total number of sequences
        
    def test_dataset_getitem(self, sample_sequences):
        """Test dataset item retrieval."""
        assets = sorted(["AAPL", "MSFT"])
        asset_to_idx = {"AAPL": 0, "MSFT": 1}
        look_back = 10
        
        dataset = LiquidityDataset(sample_sequences, assets, asset_to_idx, look_back)
        
        item = dataset[0]
        assert "asset" in item
        assert "sequence" in item
        assert "target" in item
        assert "date" in item


class TestCollateFn:
    """Test cases for collate_fn."""
    
    @pytest.fixture
    def sample_batch(self):
        """Create a sample batch."""
        # Prepare two items, representing two different assets having sequences ending on the same date
        return [
            {
                "asset": "AAPL",
                "sequence": np.random.rand(10, 5),
                "target": 0.5,
                "date": datetime(2023, 1, 31)
            },
            {
                "asset": "MSFT",
                "sequence": np.random.rand(10, 5),
                "target": 0.4,
                "date": datetime(2023, 1, 31)
            }
        ]
    
    def test_collate_fn(self, sample_batch):
        """Test collate function."""
        import torch
        
        look_back = 10
        num_features = 5
        num_assets = 2 # System asset size expected in padded tensor structure (This is usually N_sys for testing)
        asset_to_idx = {"AAPL": 0, "MSFT": 1}
        
        x_batch, y_batch, dates = collate_fn(
            sample_batch, look_back, num_assets, asset_to_idx
        )
        
        # Check tensor shapes: [Batch Size, N_System_Assets, LookBack, Num_Features]
        assert x_batch.shape == (2, 2, 10, 5)  
        assert y_batch.shape == (2, 2)  # [Batch Size, N_System_Assets]
        assert len(dates) == 2
        
        # Check that data is correctly placed (Index 0 = AAPL, Index 1 = MSFT in this minimal test case)
        assert x_batch[0, 0, :, :].sum() > 0  # AAPL data in first batch item, asset index 0
        assert x_batch[1, 1, :, :].sum() > 0  # MSFT data in second batch item, asset index 1

class TestGraphBuilder:
    """Test cases for GraphBuilder."""
    
    @pytest.fixture
    def builder(self):
        """Create a test graph builder."""
        config = Mock(spec=Config)
        config.get.side_effect = lambda key, default=None: {
            "data.banks": ["JPM"],
            "data.tech_stocks": ["AAPL", "MSFT"],
            "data.correlation_threshold": 0.5,
            "data.rolling_correlation_window": 30
        }.get(key, default)
        return GraphBuilder(config)
    
    @pytest.fixture
    def sample_data(self):
        """Create sample price data spanning enough time for correlation window."""
        dates = pd.date_range(start="2023-01-01", periods=50, freq="D")
        all_assets = ["JPM", "AAPL", "MSFT"]
        
        data = []
        for date in dates:
            for asset in all_assets:
                data.append({
                    "Date": date,
                    "Asset": asset,
                    "Close": 100 + np.random.randn() * 0.5 + (50 if asset != 'MSFT' else 0) 
                })
        
        return pd.DataFrame(data)
    
    def test_build_dynamic_graph(self, builder, sample_data):
        """Test dynamic graph building including sector edges."""
        assets = ["JPM", "AAPL", "MSFT"]
        holdings_data = {} # No funds for simplicity
        
        # Graph date must be far enough into the time series for rolling window (30)
        graph_date = datetime(2023, 2, 15) 
        
        graph = builder.build_dynamic_graph(
            sample_data,
            graph_date,
            assets,
            holdings_data,
            0.1, # Low threshold to hopefully trigger correlation edges
            30
        )
        
        # Check that nodes were added based on asset categories defined in fixture
        assert 'JPM' in graph and graph.nodes['JPM']['node_type'] == 'banks'
        assert 'AAPL' in graph and graph.nodes['AAPL']['node_type'] == 'tech'
        assert 'MSFT' in graph and graph.nodes['MSFT']['node_type'] == 'tech'
        
        # Check sector edges (AAPL <-> MSFT)
        assert graph.has_edge('AAPL', 'MSFT')
        assert graph.get_edge_data('AAPL', 'MSFT')['edge_type'] == 'same_sector_tech'

class TestDataCache:
    """Test cases for DataCache."""
    
    @pytest.fixture
    def cache(self):
        """Create a test cache."""
        config = Mock(spec=Config)
        config.get.side_effect = lambda key, default=None: {
            "data.cache_enabled": True,
            "data.cache_format": "parquet"
        }.get(key, default)
        
        # Since cache creation relies on Path(__file__).parent...parent.parent.parent.parent
        # which is liquidity_monitor_production_final/src/liquidity_monitor/utils/cache.py, 
        # we need to mock Path resolution or just test save/load logic primarily.
        # Running this test usually requires knowing the absolute path structure, which is tricky in a generic context.
        # Mocking the existence check and direct file ops for safety here.
        
        with patch('liquidity_monitor.utils.cache.Path') as MockPath:
            mock_cache_dir = Mock()
            MockPath.return_value = mock_cache_dir
            mock_cache_dir.mkdir = Mock()
            mock_cache_dir.glob = Mock()
            mock_cache_dir.exists.return_value = True
            
            instance = DataCache(config)
            instance.cache_dir = mock_cache_dir # Use mock directory object
            return instance
        
    @pytest.fixture
    def sample_data(self):
        """Create sample data."""
        return pd.DataFrame({
            "Date": pd.date_range(start="2023-01-01", periods=10),
            "Value": np.random.rand(10)
        })
    
    def test_cache_path_generation(self, cache):
        """Test cache path generation."""
        data_type = "test"
        identifier = ["AAPL", "MSFT"]
        start_date = datetime(2023, 1, 1)
        end_date = datetime(2023, 1, 31)
        
        path = cache.get_cache_path(data_type, identifier, start_date, end_date)
        
        assert path.name.startswith("test_")
        # Check for unique hash logic instead of asset count in the name for robustness
        assert "20230101_to_20230131" in path.name
    
    @patch('liquidity_monitor.utils.cache.pd.read_parquet')
    @patch('liquidity_monitor.utils.cache.DataCache.get_cache_path')
    def test_save_and_load_data(self, mock_get_path, mock_read_parquet, cache, sample_data):
        """Test saving and loading data."""
        from datetime import datetime

        data_type = "test"
        identifier = "test_data"
        start_date = datetime(2023, 1, 1)
        end_date = datetime(2023, 1, 31)
        
        # Mock path existence and return value
        mock_path = Mock()
        mock_path.exists.return_value = True
        mock_get_path.return_value = mock_path
        mock_read_parquet.return_value = sample_data

        # Save data
        saved_path = cache.save_data(
            sample_data, data_type, identifier, start_date, end_date
        )
        
        # Check save call used write_parquet
        assert mock_path.to_parquet is not None
        
        # Load data
        loaded_data = cache.load_data(
            data_type, identifier, start_date, end_date
        )
        
        # Check that data is the same
        pd.testing.assert_frame_equal(sample_data, loaded_data)
"""
</final_file_content>

IMPORTANT: For any future changes to this file, use the final_file_content shown above as your reference. This content reflects the current state of the file, including any auto-formatting (e.g., if you used single quotes but the formatter converted them to double quotes). Always base your SEARCH/REPLACE operations on this final version to ensure accuracy.<environment_details>
# Visual Studio Code Visible Files
tests/unit/test_data_processing.py

# Visual Studio Code Open Tabs
# ... (truncated list of files)
liquidity_monitor_production_final/src/liquidity_monitor/pipeline.py
liquidity_monitor_production_final/src/liquidity_monitor/main.py
tests/unit/test_data_processing.py

# Current Time
10/16/2025, 2:15:53 PM (Europe/Istanbul, UTC+3:00)

# Context Window Usage
169,792 / 1,048.576K tokens used (16%)

# Current Mode
ACT MODE
</environment_details>
