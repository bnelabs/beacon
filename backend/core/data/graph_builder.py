"""Graph building module for creating heterogeneous financial networks."""

import pandas as pd
import numpy as np
import networkx as nx
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple

import torch
from torch_geometric.data import HeteroData

from core.utils.config import Config
from core.utils.logger import get_logger

logger = get_logger(__name__)


class GraphBuilder:
    """Builds heterogeneous graphs from financial data."""
    
    def __init__(self, config: Config):
        """
        Initialize graph builder.
        
        Args:
            config: Configuration object
        """
        self.config = config
        project_root = Path(__file__).parent.parent.parent.parent.parent
        self.asset_categories = {
            "banks": config.get("data.banks", []),
            "insurance": config.get("data.insurance", []),
            "asset_managers": config.get("data.asset_managers", []),
            "tech": config.get("data.tech_stocks", []),
            "energy": config.get("data.energy_stocks", []),
            "etf": config.get("data.etfs", []),
            "crypto": config.get("data.crypto", []),
            "international_bank": (
                config.get("data.european_banks", []) +
                config.get("data.asian_banks", [])
            )
        }
    
    def build_dynamic_graph(
        self,
        data: pd.DataFrame,
        date: datetime,
        assets: List[str],
        holdings_data: Dict[str, Dict],
        correlation_threshold: float,
        rolling_window: int,
    ) -> nx.DiGraph:
        """
        Build a dynamic heterogeneous graph for a specific date.
        
        Args:
            data: Price data
            date: Date to build graph for
            assets: List of all assets managed by the system
            holdings_data: Holdings data by fund
            correlation_threshold: Threshold for correlation edges
            rolling_window: Rolling window for correlation calculation
            
        Returns:
            Heterogeneous graph
        """
        logger.debug(f"Building graph for {date.date()}")
        
        G = nx.DiGraph()
        
        # Add nodes (Assets and Funds)
        self._add_nodes(G, assets)
        self._add_fund_nodes(G, holdings_data)
        
        # Add edges
        self._add_correlation_edges(G, data, date, assets, correlation_threshold, rolling_window)
        self._add_holdings_edges(G, holdings_data, date, assets)
        self._add_sector_edges(G)
        
        return G
    
    def _add_nodes(self, G: nx.DiGraph, assets: List[str]):
        """Add asset nodes with their types."""
        for category, category_assets in self.asset_categories.items():
            for asset in category_assets:
                if asset in assets:
                    G.add_node(asset, node_type=category)
        
        # Ensure all assets listed in the global 'assets' list (which might be missing from categories if config is incomplete) are added.
        for asset in assets:
             if asset not in G:
                 G.add_node(asset, node_type="unknown_asset")

    
    def _add_fund_nodes(self, G: nx.DiGraph, holdings_data: Dict[str, Dict]):
        """Add fund nodes."""
        for fund_name in holdings_data:
            G.add_node(fund_name, node_type="fund")
    
    def _add_correlation_edges(
        self,
        G: nx.DiGraph,
        data: pd.DataFrame,
        date: datetime,
        assets: List[str],
        threshold: float,
        window: int
    ):
        """Add correlation edges between assets."""
        end_date = pd.to_datetime(date)
        start_date = end_date - timedelta(days=window)

        # Filter data only for existing assets and the date window
        window_data = data[(data["Date"] >= start_date) & (data["Date"] <= end_date) & (data["Asset"].isin(assets))]
        
        if window_data.empty:
            return
        
        # Calculate correlation matrix on Close prices (which have been scaled/filled by DataProcessor)
        pivot_data = window_data.pivot_table(index="Date", columns="Asset", values="Close")
        
        if pivot_data.shape[1] < 2:
            return
        
        correlation_matrix = pivot_data.corr()
        
        # Add edges for high correlations
        asset_list_in_corr = correlation_matrix.columns.tolist()
        
        for i, asset1 in enumerate(asset_list_in_corr):
            for j, asset2 in enumerate(asset_list_in_corr):
                if i < j and asset1 in G and asset2 in G:
                    corr = correlation_matrix.loc[asset1, asset2]
                    if not pd.isna(corr) and abs(corr) > threshold:
                        G.add_edge(asset1, asset2, edge_type="correlates_with", weight=corr)
                        G.add_edge(asset2, asset1, edge_type="correlates_with", weight=corr)
    
    def _add_holdings_edges(
        self,
        G: nx.DiGraph,
        holdings_data: Dict[str, Dict],
        date: datetime,
        assets: List[str]
    ):
        """Add holdings edges from funds to assets."""
        end_date = pd.to_datetime(date)
        MAX_HOLDING_AGE_DAYS = 120 # Maximum age for a holding report to be relevant (as per original script)
        
        for fund_name, holdings_by_date in holdings_data.items():
            if fund_name not in G or G.nodes[fund_name]['node_type'] != 'fund':
                continue
            
            # Find closest holdings date
            closest_date = None
            min_diff = timedelta(days=MAX_HOLDING_AGE_DAYS + 1)
            
            for holdings_date in holdings_by_date:
                diff = abs(holdings_date - end_date)
                if diff < min_diff:
                    min_diff = diff
                    closest_date = holdings_date
            
            # Add edges if within the tolerance window
            if closest_date and min_diff < timedelta(days=MAX_HOLDING_AGE_DAYS):
                holdings = holdings_by_date[closest_date]
                for holding in holdings:
                    asset = holding["ticker"]
                    if asset in G:
                        G.add_edge(
                            fund_name,
                            asset,
                            edge_type="holds_equity",
                            weight=holding.get("value", 1.0) # Use fair value as weight
                        )
    
    def _add_sector_edges(self, G: nx.DiGraph):
        """Add edges between assets in the same sector."""
        for category, category_assets in self.asset_categories.items():
            
            # Filter assets that actually exist in the current graph G context
            existing_assets = [a for a in category_assets if a in G]
            
            for i, asset1 in enumerate(existing_assets):
                for j, asset2 in enumerate(existing_assets):
                    if i < j:
                        G.add_edge(
                            asset1,
                            asset2,
                            edge_type=f"same_sector_{category}",
                            weight=1.0
                        )
                        G.add_edge(
                            asset2,
                            asset1,
                            edge_type=f"same_sector_{category}",
                            weight=1.0
                        )
    
    def build_graph_series(
        self,
        data: pd.DataFrame,
        assets: List[str],
        holdings_data: Dict[str, Dict],
        correlation_threshold: float,
        rolling_window: int,
        look_back: int,
        frequency: int = 30
    ) -> Tuple[Dict[datetime, nx.DiGraph], List[datetime]]:
        """
        Build a series of dynamic graphs.
        
        Args:
            data: Price data
            assets: List of all assets
            holdings_data: Holdings data
            correlation_threshold: Threshold for correlation edges
            rolling_window: Rolling window for correlation
            look_back: Look-back period (used to determine minimum data requirement)
            frequency: Frequency of graph updates (days)
            
        Returns:
            Tuple of (graph dictionary, list of graph dates)
        """
        logger.info("Building dynamic graph series")
        
        # Ensure data dates are datetime objects
        data['Date'] = pd.to_datetime(data['Date'])
        
        unique_dates = sorted(data["Date"].unique())
        
        # A graph date must have sufficient preceding data (look_back)
        min_date_for_graph = unique_dates[0] + timedelta(days=rolling_window)
        
        # Select dates that are far enough into the series to support correlation window
        valid_dates = [d for d in unique_dates if d >= min_date_for_graph]

        # Select graph dates based on frequency, respecting the look_back requirement for target prediction
        graph_dates = valid_dates[look_back::frequency]
        
        dynamic_graphs = {}
        for date in graph_dates:
            graph = self.build_dynamic_graph(
                data, date, assets, holdings_data,
                correlation_threshold, rolling_window
            )
            dynamic_graphs[date] = graph
        
        logger.info(f"Built {len(dynamic_graphs)} graphs up to date {graph_dates[-1].date() if graph_dates else 'N/A'}")
        return dynamic_graphs, graph_dates
    
    def convert_to_hetero_data(
        self,
        graph: nx.DiGraph,
        node_to_idx: Dict[str, int],
        fund_to_idx: Dict[str, int],
        num_features: int,
        device: torch.device
    ) -> HeteroData:
        """
        Convert NetworkX graph to PyTorch Geometric HeteroData for a single time step.
        
        Args:
            graph: NetworkX graph (single timestep snapshot)
            node_to_idx: Mapping from asset names to indices (all system assets)
            fund_to_idx: Mapping from fund names to indices (all system funds)
            num_features: Number of input features (F) for asset nodes (x dimensions)
            device: Device to place tensors on
            
        Returns:
            HeteroData object representing the graph structure and empty feature matrices (nodes are indexed by total count)
        """
        data = HeteroData()
        
        # --- Node Setup: Determine total number of nodes for each metadata type ---
        asset_nodes = [n for n, attrs in graph.nodes(data=True) if attrs.get("node_type") != "fund"]
        fund_nodes = [n for n, attrs in graph.nodes(data=True) if attrs.get("node_type") == "fund"]
        
        # Use the full index mapping sizes as dimensions for feature matrices in GNN layers
        num_assets_system = len(node_to_idx)
        num_funds_system = len(fund_to_idx)

        # Add node features placeholder (x) initialized to zero
        # NOTE: In the training loop, the actual features (x_dict["asset"]) will be padded/sized to match these dimensions based on batching.
        if asset_nodes:
            data["asset"].x = torch.zeros(num_assets_system, num_features, device=device)
        if fund_nodes:
            # Fund features are handled by embedding layers later, but we declare the node type
            # Feature dimension for funds is often different or derived from embedding layer size. Here we use hidden_dim later.
            # We assign None here as the input features passed to HGTConv (`x_dict`) are only asset features from the snapshot.
            data["fund"].x = torch.zeros(num_funds_system, num_features, device=device) # Using F as placeholder dimension
        
        # --- Edge Setup ---
        edge_map = {}
        
        for u, v, attrs in graph.edges(data=True):
            edge_type = attrs.get("edge_type", "unknown")
            src_type = graph.nodes[u].get("node_type", "unknown")
            dst_type = graph.nodes[v].get("node_type", "unknown")
            
            key = (src_type, edge_type, dst_type)
            
            if key not in edge_map:
                edge_map[key] = []
            
            # Map nodes to indices using the global index maps
            u_idx, v_idx = None, None
            
            if src_type == "fund":
                if u in fund_to_idx: u_idx = fund_to_idx[u]
            elif src_type != "fund":
                if u in node_to_idx: u_idx = node_to_idx[u]
            
            if dst_type == "fund":
                if v in fund_to_idx: v_idx = fund_to_idx[v]
            elif dst_type != "fund":
                if v in node_to_idx: v_idx = node_to_idx[v]

            if u_idx is not None and v_idx is not None:
                edge_map[key].append([u_idx, v_idx])
        
        # Add edges to HeteroData
        for (src_type, edge_type, dst_type), edges in edge_map.items():
            if edges:
                # Edge index needs to be transposed for PyG: [2, num_edges]
                edges_tensor = torch.tensor(edges, dtype=torch.long, device=device).t().contiguous()
                data[src_type, edge_type, dst_type].edge_index = edges_tensor
        
        # Metadata generation relies on the keys present in the graph, which might not cover all defined node/edge types
        # PyG automatically derives metadata, but we ensure the node/edge types are recognized by the HGTConv layer later.
        
        return data
