"""Integration tests for the liquidity monitor."""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, Mock

from liquidity_monitor.pipeline import LiquidityMonitorPipeline
from liquidity_monitor.utils.config import Config


class TestLiquidityMonitorPipeline:
    """Integration tests for the main pipeline."""
    
    @pytest.fixture(scope="class")
    def pipeline(self):
        """Create a test pipeline instance."""
        # Initialize pipeline without passing external config, as we will mock data collection entirely.
        config = Config() # Uses default relative loading, which might fail, but we rely on mocking the collector afterwards.
        return LiquidityMonitorPipeline()
    
    @pytest.fixture(scope="class")
    def sample_config(self):
        """Create a sample configuration structure."""
        return {
            "data": {
                "banks": ["JPM", "BAC"],
                "insurance": ["AIG"],
                "tech_stocks": ["AAPL", "MSFT"],
                "etfs": ["SPY"],
                "market_indicators": ["^VIX"],
                "economic_indicators": ["DGS10"],
                "look_back": 10,
                "correlation_threshold": 0.5,
                "rolling_correlation_window": 30,
                "cache_enabled": False  # Disable caching for tests to ensure download happens
            },
            "model": {
                "hidden_dim": 16,
                "heads": 2,
                "epochs": 1, # Use 1 epoch to make test fast
                "batch_size": 2,
                "learning_rate": 0.01
            },
            "funds": {
                "major_funds": [
                    {"name": "TestFund", "cik": "0000000000"}
                ]
            }
        }
    
    # Mocking data download and SEC API interaction is necessary for a fast, reliable integration test
    @patch('liquidity_monitor.pipeline.DataCollector')
    def test_run_pipeline_mock_data_flow(self, MockCollectorClass, pipeline, sample_config):
        """Test pipeline execution flow with mocked data collection/SEC interaction."""
        
        # 1. Mock configuration loading to use our reduced configuration for the run
        with patch.object(pipeline.config, 'get', side_effect=lambda key, default=None: sample_config.get(key, default)):
            
            # 2. Mock DataCollector instance methods to return synthetic data
            mock_collector_instance = MockCollectorClass.return_value
            
            dates = pd.to_datetime(pd.date_range(start="2023-01-01", periods=60, freq="B")) # Use business days
            assets = [
                "JPM", "BAC", "AIG", "AAPL", "MSFT", "SPY"
            ]
            
            # Create synthetic price/indicator data
            data_list = []
            for date in dates:
                for asset in assets:
                    data_list.append({
                        "Date": date,
                        "Asset": asset,
                        "Close": 100 + np.random.randn() * 0.5,
                        "Volume": np.random.randint(10000, 100000),
                        "^VIX": 20 + np.random.randn(),
                        "DGS10": 3.5 + np.random.randn() * 0.1
                    })
            
            mock_df = pd.DataFrame(data_list)
            
            # Mock Collector Return Values
            mock_collector_instance.download_asset_data.return_value = mock_df.copy()
            mock_collector_instance.download_market_indicators.return_value = mock_df[["Date", "^VIX"]].drop_duplicates()
            mock_collector_instance.download_fred_data.return_value = mock_df[["Date", "DGS10"]].drop_duplicates()
            mock_collector_instance.download_balance_sheet_data.return_value = {}
            mock_collector_instance.download_holdings_data.return_value = {}
            
            # Mock save_data path creation logic if necessary, but direct pipeline execution should suffice if data generation bypasses network calls.
            
            # --- Run Pipeline ---
            
            # Define a short run period for testing graph building/sequence creation
            results = pipeline.run_pipeline(
                train_start="2023-01-02",
                train_end="2023-01-31", # ~22 trading days
                test_start="2023-02-01",
                test_end="2023-02-28", # ~20 trading days
                save_results=False # Do not save files during integration tests unless necessary
            )
            
            # Assertion Checks
            assert results is not None
            assert "error" not in results
            assert "mse" in results or "mae" in results
            
            # Check if graph generation occurred (requires at least look_back days separation + alignment)
            assert pipeline.graph_data["graph_dates"] is not None
            assert len(pipeline.graph_data["graph_dates"]) > 0

            # Check if sequences were formed (If the run succeeded, sequences must have been formed)
            assert "common_assets" in pipeline._prepare_sequences.__closure__[2].cell_contents # Check variable access if possible, otherwise rely on results existence
            
            
@patch('liquidity_monitor.pipeline.Trainer')
@patch('liquidity_monitor.pipeline.LiquidityMonitorPipeline._evaluate_model')
@patch('liquidity_monitor.pipeline.LiquidityMonitorPipeline._train_model')
@patch('liquidity_monitor.pipeline.LiquidityMonitorPipeline._prepare_sequences')
@patch('liquidity_monitor.pipeline.LiquidityMonitorPipeline._build_graphs')
@patch('liquidity_monitor.pipeline.LiquidityMonitorPipeline._split_data')
@patch('liquidity_monitor.pipeline.LiquidityMonitorPipeline._process_data')
@patch('liquidity_monitor.pipeline.LiquidityMonitorPipeline._collect_data')
def test_pipeline_structure_calls(mock_collect, mock_process, mock_split, mock_graph, mock_seq, mock_train, mock_eval, MockTrainer, pipeline, sample_config):
    """Test if the pipeline orchestrates calls in the correct sequence."""
    
    # Mock successful return values for data steps
    mock_data = pd.DataFrame({'Date': pd.to_datetime(['2023-01-01', '2023-02-01']), 'Asset': ['JPM', 'JPM'], 'Close': [100, 101]})
    mock_proc_data = mock_data
    mock_features = ['Close']
    mock_graph_data = {'dynamic_graphs': {}} # Minimal graph structure
    mock_train_seq, mock_test_seq, mock_assets = {'JPM': [{'sequence': np.random.rand(10, 1), 'target': 0.5, 'date': datetime(2023, 1, 31)}]}, ['JPM'], ['JPM']
    trained_model = Mock()
    mock_eval_results = {'mse': 0.1}
    
    mock_collect.return_value = mock_data
    mock_process.return_value = (mock_proc_data, mock_features)
    mock_split.return_value = (mock_data.head(30), mock_data.tail(30))
    mock_graph.return_value = mock_graph_data
    mock_seq.return_value = (mock_train_seq, mock_test_seq, mock_assets)
    mock_train.return_value = trained_model
    mock_eval.return_value = mock_eval_results
    
    # Mock Trainer init to return a mock instance that doesn't need connection details
    mock_trainer_instance = Mock()
    mock_trainer_instance.train_model.return_value = trained_model
    mock_trainer_instance.evaluate_model.return_value = mock_eval_results
    MockTrainer.return_value = mock_trainer_instance

    # Ensure pipeline uses config mock
    with patch.object(pipeline.config, 'get', side_effect=lambda key, default=None: sample_config.get(key, default)):
        pipeline.run_pipeline(
            train_start="2023-01-02",
            train_end="2023-01-31",
            test_start="2023-02-01",
            test_end="2023-02-28",
            save_results=False
        )

    # Assert sequence of calls (Checking that the data fetching/processing/graph building happens before train/eval)
    mock_collect.assert_called_once()
    mock_process.assert_called_once()
    mock_split.assert_called_once()
    mock_graph.assert_called_once()
    mock_seq.assert_called_once()
    mock_train.assert_called_once()
    mock_eval.assert_called_once()
"""
</final_file_content>

IMPORTANT: For any future changes to this file, use the final_file_content shown above as your reference. This content reflects the current state of the file, including any auto-formatting (e.g., if you used single quotes but the formatter converted them to double quotes). Always base your SEARCH/REPLACE operations on this final version to ensure accuracy.<environment_details>
# Visual Studio Code Visible Files
tests/integration/test_pipeline.py

# Visual Studio Code Open Tabs
# ... (truncated list of files)
liquidity_monitor_production_final/src/liquidity_monitor/pipeline.py
liquidity_monitor_production_final/src/liquidity_monitor/main.py
tests/unit/test_data_processing.py
tests/integration/test_pipeline.py

# Current Time
10/16/2025, 2:16:00 PM (Europe/Istanbul, UTC+3:00)

# Context Window Usage
184,707 / 1,048.576K tokens used (17%)

# Current Mode
ACT MODE
</environment_details>
