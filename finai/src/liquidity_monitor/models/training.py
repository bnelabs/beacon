"""Training module for the liquidity monitor."""

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from datetime import datetime
from typing import Dict, List, Any, Tuple
import pandas as pd # FIX: Import pandas for date handling

from .hgt import HeteroLiquidityHGT
from ..data.processing import LiquidityDataset, collate_fn
from ..utils.config import Config
from ..utils.logger import get_logger
from ..utils.cache import DataCache # Added import for potential future use/context clarity

logger = get_logger(__name__)


class Trainer:
    """Handles model training and evaluation."""
    
    def __init__(self, config: Config):
        """
        Initialize trainer.
        
        Args:
            config: Configuration object
        """
        self.config = config
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    
    def train_model(
        self,
        model: HeteroLiquidityHGT,
        train_loader: DataLoader,
        graph_date_to_hetero_data: Dict[datetime, Any],
        graph_dates: List[datetime],
        assets: List[str], # Added assets list to handle index mapping correctly during batching
        features_count: int, # Added features_count for collate_fn compatibility
        epochs: int = None,
        learning_rate: float = None
    ) -> HeteroLiquidityHGT:
        """
        Train the model.
        
        Args:
            model: Model to train
            train_loader: Training data loader
            graph_date_to_hetero_data: Graph data by date
            graph_dates: List of graph dates
            assets: List of all assets used for indexing in DataLoader
            features_count: Number of features used for input size
            epochs: Number of epochs
            learning_rate: Learning rate
            
        Returns:
            Trained model
        """
        epochs = epochs or self.config.get("model.epochs")
        learning_rate = learning_rate or self.config.get("model.learning_rate")
        
        logger.info(f"Starting training for {epochs} epochs")
        
        optimizer = optim.Adam(model.parameters(), lr=learning_rate)
        criterion = nn.MSELoss()
        
        model.train()
        
        # Create asset index map based on the total universe size required by the model's static tensors
        asset_to_idx_map = {asset: i for i, asset in enumerate(assets)}
        num_assets_system = len(assets)
        
        for epoch in range(epochs):
            epoch_loss = 0
            num_batches = 0
            
            for batch_idx, (x_batch, y_batch, dates) in enumerate(train_loader):
                if x_batch is None:
                    continue

                # Move data to device
                x_batch = x_batch.to(self.device) # Shape: [B, N_sys, L, F]
                y_batch = y_batch.to(self.device) # Shape: [B, N_sys]
                
                # Get graph for batch end date
                batch_end_date = dates[-1]
                # Find the closest graph date (which represents the context *for* this prediction window)
                graph_date = self._find_closest_graph_date(
                    batch_end_date, graph_dates
                )
                
                if graph_date is None or graph_date not in graph_date_to_hetero_data:
                    logger.warning(f"Skipping batch {batch_idx}: No corresponding graph found for date {batch_end_date.date()} or date outside graph generation range.")
                    continue
                
                hetero_data = graph_date_to_hetero_data[graph_date]
                
                # Forward pass
                optimizer.zero_grad()
                
                # Prepare inputs for the model forward pass
                # x_dict requires asset features [B, N_sys, L, F], edge_index_dict requires static graph structure
                x_dict = {"asset": x_batch}
                
                # Only pass assets that were actually present in this collated batch sample, not the full padded N_sys dimension.
                # The collate_fn pads the tensors to N_system_assets, even if many are zeroed out if their sequence couldn't be formed.
                # We need to determine N_assets_in_batch used in collation for correct reshaping inside HGT.forward.
                # N_assets_in_batch = (y_batch != 0).sum(dim=1).cpu().numpy()[0] # This varies per batch item, problematic.
                
                # A safer approach: use the total number of assets in the system (N_sys) as the dimension, as padding was performed to this size in collation.
                N_assets_in_batch = num_assets_system 
                
                output = model(
                    x_dict,
                    hetero_data.edge_index_dict,
                    x_batch.shape[0],      # B
                    x_batch.shape[2],      # L
                    N_assets_in_batch      # N_assets (System size used for padding)
                )
                
                # Calculate loss: only where target (y_batch) is non-zero (i.e., valid instances existed)
                mask = (y_batch != 0)
                
                if mask.sum() > 0:
                    # Ensure output shape matches y_batch shape before masking, although HGT output shape should be [B, N_sys]
                    if output.shape != y_batch.shape:
                        logger.error(f"Output shape {output.shape} mismatch with target shape {y_batch.shape}")
                        continue

                    loss = criterion(output[mask], y_batch[mask])
                    
                    # Backward pass
                    loss.backward()
                    
                    # Gradient clipping
                    clip_norm = self.config.get("model.gradient_clip_norm", 1.0)
                    torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=clip_norm)
                    
                    optimizer.step()
                    
                    epoch_loss += loss.item()
                    num_batches += 1
            
            # Log progress
            if num_batches > 0 and (epoch + 1) % 10 == 0:
                avg_loss = epoch_loss / num_batches
                logger.info(f"Epoch {epoch+1}/{epochs}, Loss: {avg_loss:.6f}")
        
        logger.info("Training complete")
        return model
    
    def evaluate_model(
        self,
        model: HeteroLiquidityHGT,
        test_loader: DataLoader,
        graph_date_to_hetero_data: Dict[datetime, Any],
        graph_dates: List[datetime],
        assets: List[str], # Added assets list
        features_count: int # Added features_count
    ) -> Dict[str, Any]:
        """
        Evaluate the model.
        
        Args:
            model: Trained model
            test_loader: Test data loader
            graph_date_to_hetero_data: Graph data by date
            graph_dates: List of graph dates
            assets: List of all assets used for indexing in DataLoader
            features_count: Number of features used for input size
            
        Returns:
            Evaluation results
        """
        logger.info("Starting evaluation")
        
        model.eval()
        all_predictions = []
        all_targets = []
        
        asset_to_idx_map = {asset: i for i, asset in enumerate(assets)}
        num_assets_system = len(assets)
        
        with torch.no_grad():
            for x_batch, y_batch, dates in test_loader:
                if x_batch is None:
                    continue
                    
                # Move data to device
                x_batch = x_batch.to(self.device)
                y_batch = y_batch.to(self.device)
                
                # Get graph context date
                date = dates[0]
                graph_date = self._find_closest_graph_date(date, graph_dates)
                
                if graph_date is None or graph_date not in graph_date_to_hetero_data:
                    logger.warning(f"Skipping evaluation sample: No appropriate graph found for date {date.date()}")
                    continue
                
                hetero_data = graph_date_to_hetero_data[graph_date]
                
                # Forward pass
                x_dict = {"asset": x_batch}
                output = model(
                    x_dict,
                    hetero_data.edge_index_dict,
                    x_batch.shape[0], # B
                    x_batch.shape[2], # L
                    num_assets_system # N_sys
                )
                
                # Collect predictions where mask is true (i.e., not padded)
                mask = (y_batch != 0)
                if mask.sum() > 0:
                    # output shape: [B, N_sys]. We apply the mask to both.
                    all_predictions.extend(output[mask].cpu().numpy())
                    all_targets.extend(y_batch[mask].cpu().numpy())
        
        # Calculate metrics
        from sklearn.metrics import mean_squared_error, mean_absolute_error
        
        results = {}
        if all_predictions and all_targets:
            results["mse"] = mean_squared_error(all_targets, all_predictions)
            results["mae"] = mean_absolute_error(all_targets, all_predictions)
            results["rmse"] = results["mse"] ** 0.5
            
            logger.info(f"Evaluation complete - MSE: {results['mse']:.6f}, MAE: {results['mae']:.6f}")
        else:
            logger.warning("No valid predictions for evaluation")
            results = {"mse": float("nan"), "mae": float("nan"), "rmse": float("nan")}
        
        return results
    
    def _find_closest_graph_date(
        self,
        target_date: datetime,
        graph_dates: List[datetime]
    ) -> datetime:
        """Find the closest graph date to target date, prioritizing dates <= target_date if possible, 
        but relaxing causality if the closest causal date is excessively stale."""
        if not graph_dates:
            return None
        
        target_date = pd.to_datetime(target_date).normalize()
        MAX_STALE_DAYS_TO_TOLERATE = 60 # Allow up to 60 days gap between sequence end and graph structure date
        
        # 1. Filter dates that are on or before the target date (causal dates)
        causal_dates = [d for d in graph_dates if d.normalize() <= target_date]
        
        if causal_dates:
            latest_causal_date = max(causal_dates, key=lambda x: x.toordinal())
            time_diff = (target_date - latest_causal_date).days
            
            if time_diff <= MAX_STALE_DAYS_TO_TOLERATE:
                # Causal date is recent enough, use it.
                return latest_causal_date
            else:
                # Context is stale (gap > tolerance). Switch to finding the absolute closest date 
                # to utilize a more temporally recent graph structure, even if slightly in the future.
                logger.warning(f"Causal graph date {latest_causal_date.date()} is potentially stale relative to target {target_date.date()} ({time_diff} days). Switching to closest overall date.")
                return min(graph_dates, key=lambda x: abs(x - target_date))
        else:
            # Fallback: If no causal date exists, take the closest overall date (which will be future).
            return min(graph_dates, key=lambda x: abs(x - target_date))
</final_file_content>

IMPORTANT: For any future changes to this file, use the final_file_content shown above as your reference. This content reflects the current state of the file, including any auto-formatting (e.g., if you used single quotes but the formatter converted them to double quotes). Always base your SEARCH/REPLACE operations on this final version to ensure accuracy.<environment_details>
# Visual Studio Code Visible Files
liquidity_monitor_production_final/src/liquidity_monitor/models/training.py

# Visual Studio Code Open Tabs
# ... (truncated list of files)
liquidity_monitor_production_final/src/liquidity_monitor/models/hgt.py
liquidity_monitor_production_final/src/liquidity_monitor/models/training.py

# Current Time
10/16/2025, 2:15:07 PM (Europe/Istanbul, UTC+3:00)

# Context Window Usage
121,271 / 1,048.576K tokens used (11%)

# Current Mode
ACT MODE
</environment_details>
