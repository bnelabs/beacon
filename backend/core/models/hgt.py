"""Model definitions for the liquidity monitor."""

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import HGTConv
from typing import Dict, List, Any

from core.utils.config import Config
from core.utils.logger import get_logger

logger = get_logger(__name__)


class HeteroLiquidityHGT(nn.Module):
    """
    Heterogeneous Graph Transformer for liquidity prediction.
    
    This model uses a heterogeneous graph neural network to capture
    complex relationships between different types of financial entities.
    """
    
    def __init__(
        self,
        node_types: List[str],
        num_features: int,
        hidden_dim: int,
        metadata: Any,
        num_funds: int,
        heads: int = 8,
        dropout_rate: float = 0.3,
        lstm_hidden_size: int = 256
    ):
        """
        Initialize the HGT model.
        
        Args:
            node_types: List of node types in the graph
            num_features: Number of input features (F) derived from data processing
            hidden_dim: Hidden dimension size for GNN layers (H)
            metadata: Graph metadata from PyTorch Geometric
            num_funds: Number of funds for embeddings
            heads: Number of attention heads
            dropout_rate: Dropout rate
            lstm_hidden_size: LSTM hidden size
        """
        super().__init__()
        
        self.hidden_dim = hidden_dim
        self.dropout_rate = dropout_rate
        self.lstm_hidden_size = lstm_hidden_size
        
        # Ensure 'asset' node type is present, as this is where features come from
        if 'asset' not in node_types:
            raise ValueError("HGT Model requires 'asset' node type.")

        # Linear projections for each node type (Maps F -> H)
        self.linears = nn.ModuleDict()
        for node_type in node_types:
            if node_type == "fund":
                # Funds use embedding layer, not linear projection on input data X
                pass 
            else:
                # Assets use linear projection on input features F
                self.linears[node_type] = nn.Linear(num_features, hidden_dim)
        
        # Learnable embeddings for fund nodes, maps Fund Index -> H
        self.fund_embedding = nn.Embedding(num_funds, hidden_dim)
        
        # HGT layers (operate on H dimension)
        self.hgt1 = HGTConv(hidden_dim, hidden_dim, metadata, heads=heads)
        self.hgt2 = HGTConv(hidden_dim * heads, hidden_dim, metadata, heads=1)
        
        # LSTM for temporal modeling
        # Input size is H (hidden_dim), as the graph embeddings are concatenated/processed per time step
        self.lstm = nn.LSTM(
            input_size=hidden_dim,
            hidden_size=lstm_hidden_size,
            batch_first=True
        )
        
        # Output layers
        self.dropout = nn.Dropout(dropout_rate)
        self.output_proj = nn.Linear(lstm_hidden_size, 1) # Maps final LSTM state to prediction target (1 dimension)
    
    def forward(
        self,
        x_dict: Dict[str, torch.Tensor], # Contains raw asset feature tensors for time t
        edge_index_dict: Dict[Any, torch.Tensor],
        batch_size: int,
        seq_len: int,
        num_assets_in_batch: int # This is the N_assets dimension used in batch tensor (before padding to total system assets)
    ) -> torch.Tensor:
        """
        Forward pass of the model.

        Expected tensor shapes:
            - x_dict['asset']: [B, N_sys, L, F]
                B: Batch size
                N_sys: Total number of assets in system (from graph metadata)
                L: Sequence length (look_back window)
                F: Number of features per asset
            - x_dict['fund']: [B, N_fund] (optional, fund indices)
            - edge_index_dict: Dictionary of edge indices by edge type

        Args:
            x_dict: Dictionary of node features by type. x_dict['asset'] shape is [B, N_sys, L, F]
            edge_index_dict: Dictionary of edge indices by type (uses global indexing N_total)
            batch_size: Batch size (B)
            seq_len: Sequence length (L, look_back)
            num_assets_in_batch: Number of assets (N_asset) accounted for in this specific batch sample sequence

        Returns:
            Predicted liquidity scores: [B, N_assets_in_batch]
        """
        
        # 1. Project input features (F -> H)
        projected_raw_x = {}
        for node_type in x_dict:
            if node_type == "asset":
                # Asset input data is NOT yet reshaped sequentially. It comes as a flat tensor [B*N_asset, F] from collate_fn if N_asset > 1.
                # However, the collate_fn from processing.py returns [B, N_system_assets, L, F] for X, and [B, N_system_assets] for Y.
                # WE MUST RECONSTRUCT THE SHAPE EXPECTED BY THE ORIGINAL DESIGN.
                
                # Based on the original design logic (which implies X is pre-shaped across time steps):
                # x_dict['asset'] shape is expected to be [B * N_asset_in_batch * L, F] OR reshaped later.
                
                # Based on processor.py's `collate_fn` returning `x_batch` shape: [B, N_system_assets, L, F]
                # Here, N_system_assets should be the total number of assets defined in the training/testing universe, 
                # NOT just the assets present in the current batch item, as padding occurs.
                
                # Re-evaluating collate_fn: it uses num_assets, which must be len(graph_data["node_to_idx"]) if we want full index mapping.
                # Let's assume x_dict["asset"] passed here has structure compatible with batching over time steps.
                
                # In the trainer:
                # train_loader returns (x_batch, y_batch, dates) 
                # x_batch shape: [B, N_system_assets, L, F]
                
                if x_dict['asset'].dim() == 4: # [B, N_system_assets, L, F]
                    B, N_sys, L, F = x_dict['asset'].shape

                    # Shape assertions for debugging
                    assert B == batch_size, f"Batch size mismatch: expected {batch_size}, got {B}"
                    assert L == seq_len, f"Sequence length mismatch: expected {seq_len}, got {L}"

                    # Reshape asset features for time step processing: [L, B*N_sys, F]
                    # HGTConv requires all nodes of a specific type to be concatenated for aggregation
                    # We iterate L times, selecting features for all N_sys assets at time t
                    asset_features_at_time_t = x_dict['asset'][:, :, :, :].permute(2, 0, 1, 3).reshape(L, B * N_sys, F)
                    projected_raw_x['asset'] = asset_features_at_time_t

                else:
                    raise ValueError(f"Unexpected shape for asset features: {x_dict['asset'].shape}. Expected [B, N_sys, L, F].")
            
            elif node_type in self.linears:
                # This handles other node types if any were included in x_dict (e.g., if funds needed static features, but typically funds use embeddings)
                projected_raw_x[node_type] = self.linears[node_type](x_dict[node_type])
        
        # Apply linear projections (Only assets need this if they are the structure carrier)
        if 'asset' in projected_raw_x:
            # Flatten L dimension for projection if necessary, but GNN layers usually expect structure agnostic input per aggregation step.
            # Since HGTConv is called inside a loop over L, we apply projection to the time-unrolled features.
            # Let's stick to the structure from the original sketch, adapted for time unrolling:
            
            # If x_dict['asset'] was [L, B*N_sys, F] (after reshaping in asset processing above)
            L, B_N, F = projected_raw_x['asset'].shape
            projected_raw_x['asset'] = self.linears['asset'](projected_raw_x['asset'].view(-1, F)).view(L, B_N, self.hidden_dim)
            
        
        # Process fund embeddings separately
        if 'fund' in node_types:
            # Fund indices are assumed to be passed in x_dict['fund'] if present, shape [B, N_fund_idx]
            if 'fund' in x_dict and x_dict['fund'].dim() == 2:
                # Fund indices are NOT time-dependent, they are constant across L steps.
                fund_indices = x_dict['fund'].unsqueeze(2).repeat(1, 1, seq_len) # [B, N_fund, L]
                embedded_funds = self.fund_embedding(fund_indices.view(-1)).view(B, fund_indices.shape[1], self.lstm_hidden_size, seq_len).permute(3, 0, 1, 2)
                # Store fund embeddings for later use or ensure they are broadcastable if needed by HGTConv.
                # Since HGTConv expects heterogeneous inputs mapped to node types, funds data should be available in the final input mapping structure.
                projected_raw_x['fund'] = embedded_funds # Placeholder for now, actual handling depends on HGTConv usage below
                # Fund nodes are static across time steps in the graph structure, but we need them available for aggregation at each step L.
                # For simplicity, if using this structure where we iterate L times, we provide the static fund embedding once per step/batch.
                # The structure in the original sketch seemed to imply funds are static:
                # Let's simplify: Fund embeddings are static per batch pass, not time step in the context of the GNN layer *inside* the time loop.

                # Reverting back towards the structure that fits HGTConv requirements: HGTConv needs node features map for the current snapshot.
                # The original structure assumed asset features were time-unrolled, but fund features/indices were aggregated staticly or pre-embedded.
                
                # Let's adjust the loop to handle fund embeddings substitution outside the time loop if not needed inside HGTConv inputs.
                
                # Based on the original sketch failing point `x_dict["fund"].squeeze()`: we assume fund index is passed corresponding to the batch size N_total nodes:
                
                
                # Since the assets are time-rolled, we only need static embeddings for fund nodes ONCE per timestamp T.
                # Let's rebuild x_dict inside the loop to reflect the GNN snapshot.
                
                # Since fund embeddings are static across time for a given batch ID, we calculate them once outside the loop for efficiency.
                static_fund_indices = x_dict['fund'][0].to(torch.long) # [N_fund_system]
                static_fund_embeddings = self.fund_embedding(static_fund_indices) # [N_fund_system, H] (Assuming N_fund_system for index size)
                projected_raw_x['fund'] = static_fund_embeddings 


        t_step_outputs = []
        
        # Get metadata ready outside loop for GNN layers
        
        
        for t in range(seq_len):
            
            # Construct x_dict snapshot for time t
            current_x_snapshot = {
                "asset": projected_raw_x['asset'][t, :, :] # [B*N_sys, H]
            }
            
            # Add other static nodes if necessary (funds)
            if 'fund' in projected_raw_x:
                 current_x_snapshot['fund'] = projected_raw_x['fund']
                 
            
            # Apply HGT layers
            hgt_out = self.hgt1(current_x_snapshot, edge_index_dict)
            hgt_out = {k: F.elu(v) for k, v in hgt_out.items()}
            hgt_out = self.hgt2(hgt_out, edge_index_dict)
            
            # Extract asset embeddings for this time step t
            # hgt_out['asset'] should be [B*N_sys, H_out]
            expected_nodes = batch_size * num_assets_in_batch
            assert hgt_out["asset"].shape[0] == expected_nodes, \
                f"HGT output shape mismatch at time {t}: expected {expected_nodes} nodes, got {hgt_out['asset'].shape[0]}"
            asset_embedding = hgt_out["asset"].view(batch_size, num_assets_in_batch, self.hidden_dim)
            t_step_outputs.append(asset_embedding) # [B, N_asset_batch, H]
        
        # Stack time steps: [L, B, N_asset_batch, H]
        graph_embedding_sequence = torch.stack(t_step_outputs, dim=0)
        
        # Reshape for LSTM: LSTM expects [B_combined, L, H_in]
        # Combine B and N_asset_batch for LSTM input, as the LSTM operates independently on each asset series across time
        graph_embedding_sequence_reshaped = graph_embedding_sequence.permute(1, 0, 2, 3).reshape(
            batch_size * num_assets_in_batch, seq_len, self.hidden_dim
        )
        
        # Apply LSTM
        lstm_out, _ = self.lstm(graph_embedding_sequence_reshaped)
        
        # Take the output from the last time step for prediction
        last_time_step_out = self.dropout(lstm_out[:, -1, :]) # [B * N_asset_batch, LSTM_H]
        
        # Generate predictions
        output = self.output_proj(last_time_step_out) # [B * N_asset_batch, 1]
        
        # Reshape output back to [B, N_asset_batch]
        return output.view(batch_size, num_assets_in_batch)


class LiquidityPredictor:
    """Wrapper class for liquidity prediction model."""
    
    def __init__(self, config: Config):
        """
        Initialize predictor.
        
        Args:
            config: Configuration object
        """
        self.config = config
        self.model = None
        # Check CUDA availability but explicitly use CPU if not available, as done in environment check.
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"Using device: {self.device}")
    
    def build_model(
        self,
        node_types: List[str],
        num_features: int,
        metadata: Any
    ) -> 'HeteroLiquidityHGT':
        """
        Build the model.
        
        Args:
            node_types: List of node types (from HeteroData)
            num_features: Number of features (F)
            metadata: Graph metadata
            
        Returns:
            Initialized model
        """
        # Ensure 'asset' is in node_types if passing to HGTConv
        if 'asset' not in node_types:
             # If asset nodes are not explicitly listed in metadata[0], we might need intervention, 
             # but assuming standard metadata format where node types are available.
             pass
             
        self.model = HeteroLiquidityHGT(
            node_types=node_types,
            num_features=num_features,
            hidden_dim=self.config.get("model.hidden_dim"),
            metadata=metadata,
            num_funds=self.config.get("model.num_funds"),
            heads=self.config.get("model.heads"),
            dropout_rate=self.config.get("model.dropout_rate"),
            lstm_hidden_size=self.config.get("model.lstm_hidden_size")
        ).to(self.device)
        
        logger.info(f"Model built successfully with {sum(p.numel() for p in self.model.parameters() if p.requires_grad) / 1e3:.1f}K trainable parameters.")
        return self.model
    
    def save_model(self, path: str):
        """Save model state."""
        if self.model is None:
            raise ValueError("No model to save")
        
        torch.save(self.model.state_dict(), path)
        logger.info(f"Model saved to {path}")
    
    def load_model(
        self,
        path: str,
        node_types: List[str],
        num_features: int,
        metadata: Any
    ) -> 'HeteroLiquidityHGT':
        """Load model state."""
        self.build_model(node_types, num_features, metadata)
        
        # Fix path handling for loading
        load_path = Path(path)
        if not load_path.exists():
             raise FileNotFoundError(f"Model checkpoint not found at {path}")
             
        self.model.load_state_dict(torch.load(load_path, map_location=self.device))
        logger.info(f"Model loaded from {path}")
        return self.model
</final_file_content>

IMPORTANT: For any future changes to this file, use the final_file_content shown above as your reference. This content reflects the current state of the file, including any auto-formatting (e.g., if you used single quotes but the formatter converted them to double quotes). Always base your SEARCH/REPLACE operations on this final version to ensure accuracy.<environment_details>
# Visual Studio Code Visible Files
liquidity_monitor_production_final/src/liquidity_monitor/models/hgt.py

# Visual Studio Code Open Tabs
# ... (truncated list of files)
liquidity_monitor_production_final/src/liquidity_monitor/data/graph_builder.py
liquidity_monitor_production_final/src/liquidity_monitor/models/hgt.py

# Current Time
10/16/2025, 2:14:39 PM (Europe/Istanbul, UTC+3:00)

# Context Window Usage
114,573 / 1,048.576K tokens used (10%)

# Current Mode
ACT MODE
</environment_details>
