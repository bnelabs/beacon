"""
Graph Neural Network (GNN) model for BNE Engine.
"""
import torch
import torch.nn.functional as F
from torch_geometric.nn import GCNConv, GATConv, ChebConv
from torch_geometric.data import Data

class GNNModel(torch.nn.Module):
    """
    A Graph Neural Network model for risk prediction.
    This model uses a combination of Graph Convolutional and Attention layers
    to learn from the relationships between financial entities.
    """

    def __init__(self, num_node_features: int, hidden_channels: int, num_classes: int):
        super(GNNModel, self).__init__()
        self.conv1 = GCNConv(num_node_features, hidden_channels)
        self.conv2 = GATConv(hidden_channels, hidden_channels)
        self.conv3 = ChebConv(hidden_channels, hidden_channels, K=3)
        self.lin = torch.nn.Linear(hidden_channels, num_classes)

    def forward(self, data: Data) -> torch.Tensor:
        """
        Forward pass for the GNN model.
        """
        x, edge_index = data.x, data.edge_index

        x = self.conv1(x, edge_index)
        x = F.relu(x)
        x = F.dropout(x, p=0.5, training=self.training)

        x = self.conv2(x, edge_index)
        x = F.relu(x)
        x = F.dropout(x, p=0.5, training=self.training)

        x = self.conv3(x, edge_index)
        x = F.relu(x)
        x = F.dropout(x, p=0.5, training=self.training)

        x = self.lin(x)

        return F.log_softmax(x, dim=1)
