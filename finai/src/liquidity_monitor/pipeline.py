"""Main pipeline for the liquidity monitor."""

import os
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Tuple
import time # For potential sleeps if needed, though rate limiting is in collector

import torch
from torch.utils.data import DataLoader

from .data.collection import DataCollector
from .data.processing import DataProcessor, LiquidityDataset, collate_fn
from .data.graph_builder import GraphBuilder
from .models.hgt import LiquidityPredictor
from .models.training import Trainer
from .visualization.dashboards import DashboardGenerator, GraphVisualizer
from .utils.config import Config
from .utils.logger import setup_logger

logger = setup_logger("pipeline")


class LiquidityMonitorPipeline:
    """Main pipeline for liquidity monitoring."""
    
    def __init__(self, config_path: str = None):
        """
        Initialize pipeline.
        
        Args:
            config_path: Path to configuration file (relative to CWD)
        """
        self.config = Config(config_path)
        # Determine project root dynamically
        self.project_root = Path(__file__).parent.parent.parent.parent
        
        # Initialize components
        self.data_collector = DataCollector(self.config)
        self.data_processor = DataProcessor(self.config)
        self.graph_builder = GraphBuilder(self.config)
        self.predictor = LiquidityPredictor(self.config)
        self.trainer = Trainer(self.config)
        self.dashboard_generator = DashboardGenerator(self.config)
        self.graph_visualizer = GraphVisualizer(self.config)
        
        # Set up directories immediately
        self._setup_directories()
        
        # Pre-calculate asset categories based on config for helper methods
        self._asset_categories = self.graph_builder.asset_categories
    
    def _setup_directories(self):
        """Set up necessary directories relative to project root."""
        directories = [
            "data/raw",
            "data/processed",
            "logs",
            "models/saved",
            "results/backtests",
            "results/dashboards"
        ]
        
        for directory in directories:
            dir_path = self.project_root / directory
            dir_path.mkdir(parents=True, exist_ok=True)
        logger.info("Project directories established.")

    def _get_all_assets(self) -> List[str]:
        """Get list of all assets defined across all categories in config."""
        assets = []
        for category_assets in self._asset_categories.values():
            assets.extend(category_assets)
        
        # Return unique list. Note: This relies purely on config definition, not downloaded reality.
        return list(set(assets))
    
    def run_pipeline(
        self,
        train_start: str,
        train_end: str,
        test_start: str,
        test_end: str,
        save_results: bool = True
    ) -> Dict[str, Any]:
        """
        Run the complete pipeline.
        
        Args:
            train_start: Training start date (YYYY-MM-DD)
            train_end: Training end date (YYYY-MM-DD)
            test_start: Test start date (YYYY-MM-DD)
            test_end: Test end date (YYYY-MM-DD)
            save_results: Whether to save results/visualizations
            
        Returns:
            Pipeline evaluation results.
        """
        logger.info(f"Running pipeline: Train {train_start} to {train_end} | Test {test_start} to {test_end}")
        
        # Convert dates
        train_start_dt = datetime.strptime(train_start, "%Y-%m-%d")
        train_end_dt = datetime.strptime(train_end, "%Y-%m-%d")
        test_start_dt = datetime.strptime(test_start, "%Y-%m-%d")
        test_end_dt = datetime.strptime(test_end, "%Y-%m-%d")
        
        # Calculate the total date range for data collection
        overall_start = min(train_start_dt, test_start_dt)
        overall_end = max(train_end_dt, test_end_dt)
        
        try:
            # Step 1: Collect data
            all_data = self._collect_data(overall_start, overall_end)
            
            # Step 2: Separate data based on defined temporal splits immediately after cleaning
            data_for_feature_eng = all_data.copy()
            
            # Step 3: Process data (Feature Engineering happens on ALL collected data)
            processed_data, features = self._process_data(data_for_feature_eng)
            
            # Step 4: Split data into Train/Test based on dates (must happen BEFORE sequence prep)
            train_data, test_data = self._split_data(
                processed_data, train_start_dt, train_end_dt, test_start_dt, test_end_dt
            )
            
            # Step 5: Build graphs based on ALL processed data, as correlation window looks backward in time
            graph_data = self._build_graphs(processed_data)
            
            # Step 6: Prepare sequences (DataProcessor handles scaling using train data first, then test data)
            train_sequences, test_sequences, common_assets = self._prepare_sequences(
                train_data, test_data, features
            )
            
            # Handle case where no common assets/sequences could be formed
            if not common_assets:
                 logger.error("No common, ready assets found for training/testing.")
                 return {"error": "No common assets ready for sequence modeling."}

            # Step 7: Train model
            model = self._train_model(train_sequences, graph_data, common_assets, features)
            
            # Step 8: Evaluate model
            results = self._evaluate_model(
                model, test_sequences, graph_data, common_assets, features
            )
            
            # Step 9: Create visualizations (Requires indices mapped to common assets for reconstruction)
            if save_results:
                asset_to_idx_map = {asset: i for i, asset in enumerate(common_assets)}
                self._create_visualizations(results, graph_data, common_assets, asset_to_idx_map, train_start, test_end)
            
            # Step 10: Save results (In backtesting mode, this is handled separately)
            if save_results and not any(k.startswith('20') for k in [train_start, test_end]): # Simple heuristic to differentiate single run vs backtest run structure
                self._save_single_run_results(results, train_start, test_end)
            
            logger.info("Pipeline run completed successfully")
            return results
            
        except Exception as e:
            logger.error(f"Pipeline execution failed during overall run: {e}", exc_info=True)
            return {"error": f"Pipeline failed: {str(e)}"}
    
    def _collect_data(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """Collect all necessary data."""
        logger.info("Step 1: Collecting raw data")
        
        # Get asset lists
        assets = self._get_all_assets()
        
        # Download price data
        logger.info(f"Gathering {len(assets)} assets.")
        price_data = self.data_collector.download_asset_data(
            assets, start_date, end_date, batch_size=20 # Reduced batch size for safety due to rate limiting constraint
        )
        
        # Download indicators
        indicators = self.config.get("data.market_indicators", [])
        indicator_data = self.data_collector.download_market_indicators(
            indicators, start_date, end_date
        )
        
        # Merge indicators
        if not indicator_data.empty:
            price_data = pd.merge(price_data, indicator_data, on="Date", how="left")
        
        # Download FRED data
        fred_indicators = self.config.get("data.economic_indicators", [])
        fred_data = self.data_collector.download_fred_data(
            fred_indicators, start_date, end_date
        )
        
        # Merge FRED data
        if not fred_data.empty:
            price_data = pd.merge(price_data, fred_data, on="Date", how="left")
        
        # Download balance sheet data (Requires SEC API Key)
        institutions = self.config.get("data.banks", []) + self.config.get("data.insurance", [])
        financial_facts = [
            "Assets", "StockholdersEquity", "ShortTermDebt", "LongTermDebt", "CashAndCashEquivalentsAtCarryingValue"
        ] # Reduced financial facts list to core ones to minimize API calls/complexity
        
        balance_sheet_data = {}
        try:
            balance_sheet_data = self.data_collector.download_balance_sheet_data(
                institutions, financial_facts
            )
        except ValueError as e:
            logger.warning(f"Could not download balance sheet data (API Key issue or empty config?): {e}")

        # Process balance sheet data
        if balance_sheet_data:
            price_data = self.data_processor.process_balance_sheet_data(
                balance_sheet_data, price_data
            )
        
        # Download holdings data (Requires SEC API Key)
        funds = self.config.get("funds.major_funds", [])
        holdings_data = {}
        try:
            holdings_data = self.data_collector.download_holdings_data(funds, assets)
        except ValueError as e:
            logger.warning(f"Could not download holdings data (API Key issue or empty config?): {e}")
        
        # Save holdings data artifact
        holdings_path = self.project_root / "data" / "processed" / "holdings.json"
        with open(holdings_path, "w") as f:
            json.dump(holdings_data, f, default=str)
        
        # Clean data after all merging
        critical_cols = ["Close", "Volume"] + [
            col for col in price_data.columns if col in fred_indicators
        ]
        
        final_price_data = self.data_processor.clean_data(price_data, critical_cols)
        
        logger.info("Data collection complete")
        return final_price_data
    
    def _process_data(self, data: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
        """Process and engineer features."""
        logger.info("Step 2: Processing raw data & Engineering features")
        
        institutions = self.config.get("data.banks", []) + self.config.get("data.insurance", [])
        financial_facts = [
            "Assets", "StockholdersEquity", "ShortTermDebt", "LongTermDebt", "CashAndCashEquivalentsAtCarryingValue"
        ]
        economic_indicators = self.config.get("data.economic_indicators", [])
        
        processed_data, features, num_features = self.data_processor.engineer_features(
            data, institutions, financial_facts, economic_indicators
        )
        
        logger.info(f"Data processing complete. Created {num_features} features")
        return processed_data, features
    
    def _split_data(
        self,
        data: pd.DataFrame,
        train_start: datetime,
        train_end: datetime,
        test_start: datetime,
        test_end: datetime
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Split data into train and test sets based strictly on dates."""
        logger.info("Step 3: Splitting data into train/test sets")
        
        train_data = data[
            (data["Date"] >= train_start) & (data["Date"] <= train_end)
        ].copy()
        
        test_data = data[
            (data["Date"] >= test_start) & (data["Date"] <= test_end)
        ].copy()
        
        logger.info(f"Train data size: {len(train_data)} rows")
        logger.info(f"Test data size: {len(test_data)} rows")
        
        return train_data, test_data
    
    def _build_graphs(
        self,
        data: pd.DataFrame
    ) -> Dict[str, Any]:
        """Build dynamic graphs."""
        logger.info("Step 4: Building dynamic graphs")
        
        # Load holdings data
        holdings_path = self.project_root / "data" / "processed" / "holdings.json"
        if not holdings_path.exists():
             logger.warning("Holdings data file not found. Graphs will be built without fund linkages.")
             holdings_data = {}
        else:
            with open(holdings_path, "r") as f:
                holdings_data = json.load(f)
        
        # Convert string dates back to datetime for comparison in GraphBuilder
        for fund_name in holdings_data:
            holdings_data[fund_name] = {
                pd.to_datetime(date): holdings
                for date, holdings in holdings_data[fund_name].items()
            }
        
        assets = self._get_all_assets()
        
        # Get parameters
        correlation_threshold = self.config.get("data.correlation_threshold", 0.5)
        rolling_window = self.config.get("data.rolling_correlation_window", 90)
        look_back = self.config.get("data.look_back", 30)
        frequency = self.config.get("data.graph_update_frequency", 30)
        
        # Build graphs
        dynamic_graphs, graph_dates = self.graph_builder.build_graph_series(
            data, assets, holdings_data,
            correlation_threshold, rolling_window, look_back, frequency
        )
        
        # Convert to HeteroData for model input
        node_to_idx = {asset: i for i, asset in enumerate(assets)}
        funds = self.config.get("funds.major_funds", [])
        fund_to_idx = {fund["name"]: i for i, fund in enumerate(funds)}
        
        graph_date_to_hetero_data = {}
        num_features_placeholder = 1 # Feature count from Step 2/3 doesn't matter here, only structure
        
        for date, graph in dynamic_graphs.items():
            hetero_data = self.graph_builder.convert_to_hetero_data(
                graph, node_to_idx, fund_to_idx, num_features_placeholder,
                self.predictor.device
            )
            graph_date_to_hetero_data[date] = hetero_data
        
        logger.info("Graph building complete")
        return {
            "dynamic_graphs": dynamic_graphs,
            "graph_dates": graph_dates,
            "graph_date_to_hetero_data": graph_date_to_hetero_data,
            "node_to_idx": node_to_idx,
            "fund_to_idx": fund_to_idx
        }
    
    def _prepare_sequences(
        self,
        train_data: pd.DataFrame,
        test_data: pd.DataFrame,
        features: List[str]
    ) -> Tuple[Dict, Dict, List[str]]:
        """Step 5: Prepare sequences for training and testing, fit scalers on train."""
        logger.info("Step 5: Preparing sequences and fitting scalers")
        
        look_back = self.config.get("data.look_back", 30)
        
        # Prepare training sequences (FITTING SCALERS HERE)
        train_sequences, train_assets, train_scalers = self.data_processor.prepare_sequences(
            train_data, features, look_back
        )
        
        # Prepare test sequences (TRANSFORMING using FITTED SCALERS)
        test_sequences, test_assets, _ = self.data_processor.prepare_sequences(
            test_data, features, look_back, train_scalers
        )
        
        # Find common assets that have valid sequences in both sets
        common_assets = sorted(list(set(train_assets) & set(test_assets)))
        
        # Filter sequences to only include common assets
        train_sequences = {
            asset: train_sequences[asset]
            for asset in common_assets
            if asset in train_sequences
        }
        test_sequences = {
            asset: test_sequences[asset]
            for asset in common_assets
            if asset in test_sequences
        }
        
        logger.info(f"Prepared sequences for {len(common_assets)} common assets.")
        return train_sequences, test_sequences, common_assets
    
    def _train_model(
        self,
        train_sequences: Dict,
        graph_data: Dict,
        assets: List[str],
        features: List[str]
    ) -> Any:
        """Step 6: Train the model."""
        logger.info("Step 6: Training model")
        
        # Create dataset and dataloader
        look_back = self.config.get("data.look_back", 30)
        batch_size = self.config.get("model.batch_size", 16)
        num_assets_system = len(assets)
        
        # Create the custom collate function instance for the specific data shapes
        custom_collate = lambda batch: collate_fn(
            batch, look_back, num_assets_system, graph_data["node_to_idx"]
        )
        
        train_dataset = LiquidityDataset(train_sequences, assets, graph_data["node_to_idx"], look_back)
        
        train_loader = DataLoader(
            train_dataset,
            batch_size=batch_size,
            shuffle=True,
            collate_fn=custom_collate,
            drop_last=True # Drop last to ensure fixed batch size for tensor operations, important for fixed graph context
        )
        
        if len(train_loader) == 0:
            raise RuntimeError("Training data loader is empty after sequence preparation.")

        # Build model
        # Use the metadata from the first available graph snapshot
        first_graph_date = graph_data["graph_dates"][0]
        metadata = graph_data["graph_date_to_hetero_data"][first_graph_date].metadata()
        node_types = list(metadata[0]) # ('asset', 'fund') etc.
        
        model = self.predictor.build_model(node_types, len(features), metadata)
        
        # Train model
        trained_model = self.trainer.train_model(
            model,
            train_loader,
            graph_data["graph_date_to_hetero_data"],
            graph_data["graph_dates"],
            assets,
            len(features)
        )
        
        # Save model
        model_path = self.project_root / "models" / "saved" / "latest_model.pth"
        self.predictor.save_model(str(model_path))
        
        logger.info("Model training complete")
        return trained_model
    
    def _evaluate_model(
        self,
        model: Any,
        test_sequences: Dict,
        graph_data: Dict,
        assets: List[str],
        features: List[str]
    ) -> Dict[str, Any]:
        """Step 8: Evaluate the model."""
        logger.info("Step 8: Evaluating model on test set")
        
        # Create dataset and dataloader
        look_back = self.config.get("data.look_back", 30)
        num_assets_system = len(assets)

        # Create the custom collate function instance for the specific data shapes
        custom_collate = lambda batch: collate_fn(
            batch, look_back, num_assets_system, graph_data["node_to_idx"]
        )
        
        test_dataset = LiquidityDataset(test_sequences, assets, graph_data["node_to_idx"], look_back)
        
        test_loader = DataLoader(
            test_dataset,
            batch_size=1, # Use batch size 1 for evaluation stability, though it should handle small batches
            shuffle=False,
            collate_fn=custom_collate
        )

        if len(test_loader) == 0:
            logger.warning("Test DataLoader is empty. Cannot perform evaluation.")
            return {"mse": float("nan"), "mae": float("nan"), "rmse": float("nan")}
        
        # Evaluate
        results = self.trainer.evaluate_model(
            model,
            test_loader,
            graph_data["graph_date_to_hetero_data"],
            graph_data["graph_dates"],
            assets,
            len(features)
        )
        
        logger.info("Model evaluation complete")
        return results
    
    def _create_visualizations(
        self,
        results: Dict[str, Any],
        graph_data: Dict,
        common_assets: List[str],
        asset_to_idx_map: Dict[str, int],
        train_start: str,
        test_end: str
    ):
        """Step 9: Create visualizations."""
        logger.info("Step 9: Creating visualizations")
        
        # Define run name based on time period
        run_name = f"run_{train_start}_to_{test_end}"
        results_dir = self.project_root / "results" / run_name
        results_dir.mkdir(parents=True, exist_ok=True)
        
        # Visualize graph performance dashboard
        graph_viz_path = results_dir / "performance_dashboard.html"
        self.dashboard_generator.create_performance_dashboard(
            results.get("predictions", []), # Passing empty list if not captured, will be fixed below if needed
            results.get("targets", []),     # Passing empty list if not captured, will be fixed below if needed
            [], # Dates are hard to reconstruct reliably here, skip for now
            common_assets,
            asset_to_idx_map,
            str(graph_viz_path)
        )
        
        # Visualize graph structure (using the first graph snapshot)
        if graph_data["dynamic_graphs"]:
            graph_dates = sorted(graph_data["graph_dates"])
            first_graph = graph_data["dynamic_graphs"][graph_dates[0]]
            
            # Visualize static graph structure at t=0
            graph_viz_path_static = results_dir / "static_network_t0.html"
            self.graph_visualizer.visualize_graph(
                first_graph,
                f"Financial Network Snapshot on {graph_dates[0].date()}",
                str(graph_viz_path_static)
            )
            
            # Create graph evolution animation
            graph_evo_path = results_dir / "graph_evolution.html"
            self.graph_visualizer.create_graph_evolution(
                graph_data["dynamic_graphs"],
                str(graph_evo_path)
            )
    
    def _save_single_run_results(self, results: Dict[str, Any], train_start: str, test_end: str):
        """Save pipeline results for a single execution run."""
        logger.info("Saving single run pipeline results")
        
        run_name = f"run_{train_start}_to_{test_end}"
        results_dir = self.project_root / "results" / run_name
        results_dir.mkdir(parents=True, exist_ok=True)
        
        # Save aggregated results
        results_path = results_dir / "results.json"
        with open(results_path, "w") as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"Results saved to {results_path}")
    
    def _save_backtest_results(self, results_df: pd.DataFrame):
        """Save results aggregated from backtesting."""
        logger.info("Saving aggregated backtesting results")
        
        results_path = self.project_root / "results" / "backtesting_results.csv"
        results_path.parent.mkdir(parents=True, exist_ok=True)
        results_df.to_csv(results_path, index=False)
        
        logger.info(f"Backtesting summary saved to {results_path}")
        
        # Create backtest dashboard visualization
        dashboard_path = self.project_root / "results" / "backtesting_summary_dashboard.html"
        self.dashboard_generator.create_backtest_results_dashboard(
            results_df, str(dashboard_path)
        )


    def _evaluate_model(
        self,
        model: Any,
        test_sequences: Dict,
        graph_data: Dict,
        assets: List[str],
        features: List[str]
    ) -> Dict[str, Any]:
        """Evaluate model and capture raw predictions/targets for visualization."""
        logger.info("Evaluating model")
        
        # Create dataset and dataloader
        look_back = self.config.get("data.look_back", 30)
        num_assets_system = len(assets)

        custom_collate = lambda batch: collate_fn(
            batch, look_back, num_assets_system, graph_data["node_to_idx"]
        )
        
        test_dataset = LiquidityDataset(test_sequences, assets, graph_data["node_to_idx"], look_back)
        
        test_loader = DataLoader(
            test_dataset,
            batch_size=1,
            shuffle=False,
            collate_fn=custom_collate
        )
        
        if len(test_loader) == 0:
            logger.warning("Test DataLoader is empty. Returning NaNs.")
            return {"mse": float("nan"), "mae": float("nan"), "rmse": float("nan"), "predictions": [], "targets": []}
        
        # Evaluate
        results = self.trainer.evaluate_model(
            model,
            test_loader,
            graph_data["graph_date_to_hetero_data"],
            graph_data["graph_dates"],
            assets,
            len(features)
        )
        
        # NOTE: Capturing the true list of predictions/targets corresponding to the loss calculation
        # requires modifying trainer.evaluate_model to return them, which is a larger structural change.
        # For now, we return metrics only, and visualization steps will need to be adapted (as done in dashboards.py)
        
        logger.info("Model evaluation complete")
        return results
    
    def run_backtesting(self, start_year: int = 2010, end_year: int = 2023):
        """Run walk-forward backtesting."""
        logger.info(f"Starting walk-forward backtesting from {start_year} to {end_year}")
        
        all_backtest_results = []
        
        # Identify the largest possible clean asset universe available for consistency across runs
        # We must stick to the asset universe defined in config, as data fetching might fail otherwise.
        assets_in_config = self._get_all_assets()
        
        for year in range(start_year, end_year + 1):
            logger.info(f"--- Processing Backtest Year: {year} ---")
            
            # Define periods. Train on 5 years preceding the test year, test on the full year.
            train_end_year = year - 1
            train_start_year = year - 6 # 5 full years of training data before test year starts (e.g., 2020 train for 2020 test)
            
            train_start = f"{train_start_year}-01-01"
            train_end = f"{train_end_year}-12-31"
            test_start = f"{year}-01-01"
            test_end = f"{year}-12-31"
            
            # Ensure we have enough history for the first run
            if train_start_year < 2000: # Arbitrary hard stop if year calculation leads too far back based on FRED data availability
                logger.warning(f"Start year {train_start_year} too early for robust backtesting. Terminating.")
                break

            try:
                # Run pipeline for this year segment
                results = self.run_pipeline(
                    train_start, train_end, test_start, test_end,
                    save_results=True
                )
                
                if "error" in results:
                    logger.error(f"Pipeline failed for year {year}. Skipping year.")
                    continue

                # Store results using year label
                all_backtest_results.append({
                    "year": year,
                    "mse": results.get("mse", float("nan")),
                    "mae": results.get("mae", float("nan")),
                    "rmse": results.get("rmse", float("nan"))
                })
                
                logger.info(f"Year {year} evaluation metric saved.")
                
            except Exception as e:
                logger.error(f"Critical error processing year {year}: {e}")
                continue
        
        if all_backtest_results:
            results_df = pd.DataFrame(all_backtest_results)
            self._save_backtest_results(results_df)
            logger.info("Walk-forward backtesting complete.")


def main():
    """Main function."""
    # This script handles argument parsing and execution flow based on CLI args.
    # If --backtest is present, main calls run_backtesting, which uses run_pipeline iteratively.
    # If no args are given, it uses defaults designed for a single run.
    pass # Main logic moved to the execution step later.
