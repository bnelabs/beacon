"""Visualization module for the liquidity monitor."""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import networkx as nx
from pathlib import Path

from ..utils.config import Config
from ..utils.logger import get_logger

logger = get_logger(__name__)


class DashboardGenerator:
    """Generates interactive dashboards for visualizing results."""
    
    def __init__(self, config: Config):
        """
        Initialize dashboard generator.
        
        Args:
            config: Configuration object
        """
        self.config = config
        self.project_root = Path(__file__).parent.parent.parent.parent.parent
    
    def create_performance_dashboard(
        self,
        predictions: List[float],
        targets: List[float],
        dates: List[datetime],
        assets: List[str], # Used for mapping asset index to name if needed
        asset_to_idx: Dict[str, int],
        output_path: str
    ) -> str:
        """
        Create a dashboard showing model performance.
        
        Args:
            predictions: Model predictions (flattened list of valid predictions)
            targets: Actual target values (flattened list corresponding to predictions)
            dates: Corresponding dates (length matches predictions/targets)
            assets: List of all system assets (N_sys)
            asset_to_idx: Mapping from asset names to indices (0 to N_sys-1)
            output_path: Path to save the dashboard
            
        Returns:
            Path to saved dashboard
        """
        logger.info("Creating performance dashboard")
        
        # 1. Overall Performance Plot (Time Series)
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=("Time Series: Overall Actual vs. Predicted", "Error Distribution (Histogram)", "Prediction vs Target (Scatter)", "Asset Performance (Sample)"),
            specs=[[{"colspan": 1}, {"rowspan": 1}], [None, {"colspan": 1}]], # Structure adjustment needed for 4 plots in a 2x2 grid
        )
        
        # For overall time series, we aggregate predictions/targets if they were batched across assets per date.
        # Since predictions/targets here are flattened lists of *valid* asset predictions across all time steps, 
        # we cannot reliably plot a simple time series unless we aggregate them per date.
        
        # Calculate daily averages for overall view
        if dates:
            agg_df = pd.DataFrame({'Date': dates, 'Target': targets, 'Prediction': predictions})
            daily_agg = agg_df.groupby('Date').agg(
                Target_Mean=('Target', 'mean'),
                Prediction_Mean=('Prediction', 'mean')
            ).reset_index()
            
            fig.add_trace(
                go.Scatter(
                    x=daily_agg['Date'],
                    y=daily_agg['Prediction_Mean'],
                    mode="lines",
                    name="Predicted (Mean)",
                    line=dict(color="red", dash="dash")
                ),
                row=1, col=1
            )
            
            fig.add_trace(
                go.Scatter(
                    x=daily_agg['Date'],
                    y=daily_agg['Target_Mean'],
                    mode="lines",
                    name="Actual (Mean)",
                    line=dict(color="blue")
                ),
                row=1, col=1
            )

        # 2. Error distribution (Histogram)
        errors = np.array(predictions) - np.array(targets)
        fig.add_trace(
            go.Histogram(
                x=errors,
                nbinsx=50,
                name="Error Distribution"
            ),
            row=1, col=2
        )
        
        # 3. Prediction vs Target scatter
        fig.add_trace(
            go.Scatter(
                x=targets,
                y=predictions,
                mode="markers",
                name="Predictions",
                marker=dict(
                    size=5,
                    opacity=0.5,
                    color=np.array(targets),
                    colorscale="Viridis",
                    showscale=True,
                    colorbar=dict(title="Target Value", x=1.02)
                )
            ),
            row=2, col=2
        )
        
        # Add diagonal line for perfect predictions
        min_val = min(min(targets) if targets else 0, min(predictions) if predictions else 0)
        max_val = max(max(targets) if targets else 0, max(predictions) if predictions else 0)
        if max_val > min_val:
            fig.add_trace(
                go.Scatter(
                    x=[min_val, max_val],
                    y=[min_val, max_val],
                    mode="lines",
                    name="Perfect Prediction",
                    line=dict(color="black", dash="dot"),
                    showlegend=False
                ),
                row=2, col=2
            )

        # 4. Sample Asset Performance Plot (Requires reshaping predictions/targets if they are flat lists)
        
        # **Note on Asset Performance Plot**: Since we only have flat lists (all_predictions, all_targets), 
        # we cannot easily reconstruct which asset corresponds to which prediction in the flat list without 
        # complex date/asset tracking from the DataLoader, which isn't propagated easily here.
        # We will skip plotting individual asset performance time series for simplicity, relying on the overall mean and error distribution.
        # The original sketch had an implicit reliance on dates corresponding 1:1 to asset-flattened predictions, 
        # which is non-trivial when multiple assets/time steps appear in one batch.
        
        # Adjust layout for 3 plots instead of 4 messy ones:
        fig.update_layout(
            title="Liquidity Monitor Model Performance Summary",
            height=850,
            width=1200,
            hovermode="closest",
        )
        
        # Update axes (adjusting layout based on actual traces added)
        fig.update_xaxes(title_text="Date", row=1, col=1)
        fig.update_yaxes(title_text="Mean Liquidity Score", row=1, col=1)
        fig.update_xaxes(title_text="Error Value", row=1, col=2)
        fig.update_yaxes(title_text="Count", row=1, col=2)
        fig.update_xaxes(title_text="Actual Target (Log1p)", row=2, col=2)
        fig.update_yaxes(title_text="Predicted Target (Log1p)", row=2, col=2)


        # Save dashboard
        fig.write_html(output_path)
        logger.info(f"Performance dashboard saved to {output_path}")
        
        return output_path
    
    def create_backtest_results_dashboard(
        self,
        backtest_results: pd.DataFrame,
        output_path: str
    ) -> str:
        """
        Create a dashboard showing backtesting results.
        
        Args:
            backtest_results: DataFrame with backtesting results (must contain 'year', 'mse', 'mae', 'rmse')
            output_path: Path to save the dashboard
            
        Returns:
            Path to saved dashboard
        """
        logger.info("Creating backtest results dashboard")
        
        # Create figure with subplots
        fig = make_subplots(
            rows=2, cols=1,
            subplot_titles=("Performance Metrics by Year", "Performance Metrics Distribution (Averages)"),
            vertical_spacing=0.15
        )
        
        # Performance metrics by year
        fig.add_trace(
            go.Scatter(
                x=backtest_results["year"].astype(str), # Treat year as category for plotting distinct points
                y=backtest_results["mse"],
                mode="lines+markers",
                name="MSE",
                line=dict(color="blue")
            ),
            row=1, col=1
        )
        
        fig.add_trace(
            go.Scatter(
                x=backtest_results["year"].astype(str),
                y=backtest_results["mae"],
                mode="lines+markers",
                name="MAE",
                line=dict(color="red")
            ),
            row=1, col=1
        )
        
        # Performance metrics distribution (Averages/Std Dev)
        avg_mse = backtest_results["mse"].mean()
        avg_mae = backtest_results["mae"].mean()
        std_mse = backtest_results["mse"].std()
        std_mae = backtest_results["mae"].std()
        
        bar_x = ["MSE", "MAE"]
        avg_y = [avg_mse, avg_mae]
        std_y = [std_mse, std_mae]
        
        fig.add_trace(
            go.Bar(
                x=bar_x,
                y=avg_y,
                name="Average",
                marker_color="lightblue",
                error_y=dict(
                    type="data",
                    array=std_y,
                    visible=True,
                    thickness=1.5
                ),
                offsetgroup=0
            ),
            row=2, col=1
        )
        
        # Update layout
        fig.update_layout(
            title="Walk-Forward Backtesting Results Summary",
            height=750,
            showlegend=True
        )
        
        fig.update_xaxes(title_text="Year", row=1, col=1)
        fig.update_yaxes(title_text="Error Metric Value", row=1, col=1)
        fig.update_xaxes(title_text="Metric", row=2, col=1)
        fig.update_yaxes(title_text="Value", row=2, col=1)
        
        # Save dashboard
        fig.write_html(output_path)
        logger.info(f"Backtest results dashboard saved to {output_path}")
        
        return output_path


class GraphVisualizer:
    """Visualizes heterogeneous financial graphs."""
    
    def __init__(self, config: Config):
        """
        Initialize graph visualizer.
        
        Args:
            config: Configuration object
        """
        self.config = config
        self.color_map = {
            "banks": "blue",
            "insurance": "green",
            "asset_managers": "purple",
            "tech": "red",
            "energy": "orange",
            "etf": "pink",
            "crypto": "black",
            "international_bank": "cyan",
            "fund": "yellow",
            "unknown_asset": "gray"
        }
    
    def visualize_graph(
        self,
        graph: nx.DiGraph,
        title: str,
        output_path: str,
        layout: str = "spring"
    ) -> str:
        """
        Visualize a heterogeneous graph.
        
        Args:
            graph: NetworkX graph to visualize
            title: Title for the visualization
            output_path: Path to save the visualization
            layout: Layout algorithm for node positioning
            
        Returns:
            Path to saved visualization
        """
        logger.info(f"Visualizing graph: {title}")
        
        if graph.number_of_nodes() == 0:
            logger.warning("Graph is empty, skipping visualization.")
            return output_path
        
        # Choose layout
        if layout == "spring":
            pos = nx.spring_layout(graph, k=0.15, iterations=50, seed=42)
        elif layout == "circular":
            pos = nx.circular_layout(graph)
        else:
            # Fallback to spectral for better structure visualization if spring fails or is too slow
            pos = nx.spectral_layout(graph)
        
        # Extract node and edge information
        node_x = []
        node_y = []
        node_text = []
        node_color = []
        node_size = []
        
        # Add nodes
        for node, (x, y) in pos.items():
            node_x.append(x)
            node_y.append(y)
            
            # Get node type
            node_type = graph.nodes[node].get("node_type", "unknown")
            node_text.append(f"{node}<br>({node_type})")
            
            # Set color based on type
            node_color.append(self.color_map.get(node_type, "gray"))
            
            # Size based on degree (Assets connected to more things are larger)
            degree = graph.degree(node)
            node_size.append(10 + degree * 2)
        
        # Create node trace
        node_trace = go.Scatter(
            x=node_x,
            y=node_y,
            mode="markers+text",
            hoverinfo="text",
            text=node_text,
            textposition="top center",
            marker=dict(
                size=node_size,
                color=node_color,
                line=dict(width=1, color="black")
            )
        )
        
        # Add edges
        edge_x = []
        edge_y = []
        edge_weights = []
        
        for u, v, attrs in graph.edges(data=True):
            x0, y0 = pos[u]
            x1, y1 = pos[v]
            edge_x.extend([x0, x1, None])
            edge_y.extend([y0, y1, None])
            edge_weights.append(attrs.get('weight', 0.1))
        
        edge_trace = go.Scatter(
            x=edge_x,
            y=edge_y,
            mode="lines",
            line=dict(width=0.5, color="#888"),
            hoverinfo="none"
        )
        
        # Create figure
        fig = go.Figure(
            data=[edge_trace, node_trace],
            layout=go.Layout(
                title=title,
                titlefont_size=16,
                showlegend=False,
                hovermode="closest",
                margin=dict(b=20, l=5, r=5, t=40),
                xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                plot_bgcolor="white"
            )
        )
        
        # Save visualization
        fig.write_html(output_path)
        logger.info(f"Graph visualization saved to {output_path}")
        
        return output_path
    
    def create_graph_evolution(
        self,
        graph_series: Dict[datetime, nx.DiGraph],
        output_path: str
    ) -> str:
        """
        Create an animation showing graph evolution over time.
        
        Args:
            graph_series: Dictionary of graphs by date
            output_path: Path to save the animation
            
        Returns:
            Path to saved animation
        """
        logger.info("Creating graph evolution animation")
        
        dates = sorted(graph_series.keys())
        if not dates:
            logger.warning("No graph snapshots provided for evolution animation.")
            return output_path
            
        # Determine a static, representative layout based on all nodes across all graphs 
        # to prevent nodes jumping between frames.
        all_nodes = set()
        for graph in graph_series.values():
            all_nodes.update(graph.nodes())
        
        # Create a base graph containing all nodes (and possibly connecting nodes present in the latest graph)
        base_graph = nx.Graph()
        base_graph.add_nodes_from(all_nodes)
        
        # Connect nodes that are correlated in the final graph state, just to get a stable layout calculation
        final_graph = graph_series[dates[-1]]
        for u, v, data in final_graph.edges(data=True):
            if data.get('edge_type') == 'correlates_with':
                base_graph.add_edge(u, v)
                
        # Calculate static layout position based on the combination of all nodes and final correlations
        pos = nx.spring_layout(base_graph, k=0.15, iterations=50, seed=42)

        # Prepare frames
        frames = []
        initial_node_trace = None
        
        for i, date in enumerate(dates):
            graph = graph_series[date]
            
            # Extract node information positioning using the static 'pos'
            node_x = []
            node_y = []
            node_text = []
            node_color = []
            
            current_nodes = set(graph.nodes())
            
            for node in all_nodes: # Iterate over ALL possible nodes for consistent indexing
                x, y = pos.get(node, (0, 0)) # Use calculated position, or (0,0) if node hasn't appeared yet
                node_x.append(x)
                node_y.append(y)
                
                node_type = graph.nodes[node].get("node_type", "unknown") if node in current_nodes else "unknown"
                node_text.append(f"{node}<br>({node_type})" if node in current_nodes else f"{node}<br>(Inactive/New)")
                node_color.append(self.color_map.get(node_type, "gray") if node in current_nodes else "lightgray")
            
            # Create node trace
            node_trace = go.Scatter(
                x=node_x,
                y=node_y,
                mode="markers+text",
                hoverinfo="text",
                text=node_text,
                textposition="top center",
                marker=dict(
                    size=10,
                    color=node_color,
                    line=dict(width=1, color="black")
                )
            )
            
            if i == 0:
                initial_node_trace = node_trace

            # Add frame
            frames.append(go.Frame(
                data=[node_trace],
                name=date.strftime("%Y-%m-%d")
            ))
        
        # Add static edges (using coordinates from the static layout 'pos')
        edge_x = []
        edge_y = []
        
        for u, v in base_graph.edges():
            x0, y0 = pos[u]
            x1, y1 = pos[v]
            edge_x.extend([x0, x1, None])
            edge_y.extend([y0, y1, None])
        
        edge_trace = go.Scatter(
            x=edge_x,
            y=edge_y,
            mode="lines",
            line=dict(width=0.5, color="#888"),
            hoverinfo="none"
        )
        
        # Initialize Figure
        fig = go.Figure(
            data=[edge_trace, initial_node_trace] if initial_node_trace else [edge_trace],
            layout=go.Layout(
                title=title,
                titlefont_size=16,
                showlegend=False,
                hovermode="closest",
                margin=dict(b=20, l=5, r=5, t=80),
                xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                plot_bgcolor="white"
            )
        )
        
        fig.frames = frames
        
        # Update layout for sliders/buttons
        fig.update_layout(
            updatemenus=[
                go.layout.Updatemenu(
                    type="buttons",
                    buttons=[
                        dict(
                            label="Play",
                            method="animate",
                            args=[None, {"frame": {"duration": 500, "redraw": True},
                                    "fromcurrent": True, "transition": {"duration": 300}}],
                        )
                    ],
                    direction="left",
                    pad={"r": 10, "t": 87},
                    showactive=False,
                    x=0.0,
                    xanchor="left",
                    y=0,
                    yanchor="top"
                ),
            ],
            sliders=[
                go.layout.Slider(
                    active=0,
                    currentvalue={"prefix": "Date: "},
                    pad={"t": 50},
                    steps=[
                        {
                            "args": [[f.name], {"frame": {"duration": 0, "redraw": False},
                                                   "mode": "immediate", "transition": {"duration": 0}}],
                            "label": f.name,
                            "method": "animate"
                        }
                        for f in frames
                    ]
                )
            ]
        )
        
        # Save animation
        fig.write_html(output_path)
        logger.info(f"Graph evolution animation saved to {output_path}")
        
        return output_path
</final_file_content>

IMPORTANT: For any future changes to this file, use the final_file_content shown above as your reference. This content reflects the current state of the file, including any auto-formatting (e.g., if you used single quotes but the formatter converted them to double quotes). Always base your SEARCH/REPLACE operations on this final version to ensure accuracy.<environment_details>
# Visual Studio Code Visible Files
liquidity_monitor_production_final/src/liquidity_monitor/visualization/dashboards.py

# Visual Studio Code Open Tabs
# ... (truncated list of files)
liquidity_monitor_production_final/src/liquidity_monitor/models/training.py
liquidity_monitor_production_final/src/liquidity_monitor/visualization/dashboards.py

# Current Time
10/16/2025, 2:15:16 PM (Europe/Istanbul, UTC+3:00)

# Context Window Usage
124,534 / 1,048.576K tokens used (11%)

# Current Mode
ACT MODE
</environment_details>
