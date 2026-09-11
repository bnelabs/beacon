"""Temporal encoders for liquidity-risk prediction.

What was removed and why
------------------------

``HeterogeneousGraphTransformer`` (``HGTConv``), ``MultiScaleGNN`` (``GATConv``)
and the ``EnsembleModel`` that wrapped them are gone. Each consumed a single
static adjacency matrix built once per 24-hour batch.

That construction cannot represent interbank contagion:

* The adjacency was a Pearson correlation above a hand-picked threshold
  (``0.5``, see the removed ``DataFormatter.build_graph``). Correlation is
  co-movement, not exposure. Two institutions moving together are not thereby
  owed money by each other, and no clearing algorithm can be run on a
  correlation matrix.
* One matrix per daily batch asserts that the network is frozen between
  batches. Funding stress transmits on the timescale of margin calls and repo
  rollovers -- minutes to hours -- so a 24-hour graph samples the process
  roughly four orders of magnitude too slowly. Shocks arrive between samples
  and are invisible.
* Message passing over a static graph cannot express state that evolves
  between events, so the model had no way to represent a node whose funding
  position changed and then reverted inside one batch.

Worth recording: none of this was reachable from the training path anyway.
``MultiScaleTrainer`` accepted ``model_type='HGT'``, warned that it was "not
fully integrated", and silently trained ``MultiScaleTemporalAttentionModel``
instead -- while the job result still reported ``model_type="HGT"``. The graph
models were dead code that made the system *claim* a capability it never used.

Graph modelling returns as a temporal multiplex network with continuous-time
node memory (``modules/engine/multiplex.py``), where each layer is a distinct
economic relation -- funding, balance-sheet similarity, CCP clearing -- rather
than edges inferred from price co-movement.
"""

import torch
import torch.nn as nn
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class TemporalAttentionNetwork(nn.Module):
    """
    Temporal Attention Network for time series.

    Uses self-attention to capture long-range temporal dependencies.
    Better than LSTM for irregular sampling or long sequences.
    """

    def __init__(
        self,
        input_size: int,
        d_model: int = 128,
        nhead: int = 8,
        num_layers: int = 4,
        dim_feedforward: int = 512,
        dropout: float = 0.1
    ):
        super().__init__()

        self.input_projection = nn.Linear(input_size, d_model)

        # Learnable positional encoding
        self.positional_encoding = nn.Parameter(torch.randn(1, 1000, d_model))

        # Transformer encoder
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=dim_feedforward,
            dropout=dropout,
            batch_first=True,
            activation='gelu'
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)

        # Output head with skip connection
        self.output_head = nn.Sequential(
            nn.Linear(d_model, d_model // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model // 2, 1)
        )

    def forward(self, x):
        """
        Args:
            x: (batch_size, sequence_length, input_size)
        Returns:
            predictions: (batch_size, 1)
        """
        batch_size, seq_len, _ = x.shape

        # Project to d_model
        x = self.input_projection(x)

        # Add positional encoding
        x = x + self.positional_encoding[:, :seq_len, :]

        # Transformer encoding
        encoded = self.transformer(x)

        # Use last time step + average pooling
        last_encoded = encoded[:, -1, :]
        avg_encoded = encoded.mean(dim=1)
        combined = (last_encoded + avg_encoded) / 2

        # Prediction
        out = self.output_head(combined)

        return out


class LSTMForecaster(nn.Module):
    """LSTM encoder with a prediction head.

    The previous ``create_model("lstm")`` branch returned a bare ``nn.LSTM``,
    whose output is a tuple -- so it could not be trained by the loop, which
    calls ``self.model(sequences)`` and treats the result as a tensor. This
    wrapper gives the branch the same interface as the other encoders.
    """

    def __init__(
        self,
        input_size: int,
        hidden_size: int = 128,
        num_layers: int = 2,
        dropout: float = 0.2
    ):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0
        )
        self.head = nn.Linear(hidden_size, 1)

    def forward(self, x):
        _, (h_n, _) = self.lstm(x)
        return self.head(h_n[-1])


def create_model(
    model_type: str,
    config: Dict,
    input_size: Optional[int] = None
) -> nn.Module:
    """
    Factory function to create temporal encoders.

    Args:
        model_type: 'temporal_attention' | 'transformer' | 'lstm'
        config: Model configuration
        input_size: Overrides ``config['input_size']`` when given. The
            single-scale trainer knows the real feature width only after it has
            built its dataset, so it passes the value positionally.

    Returns:
        Initialized model
    """
    model_type = model_type.lower()

    if input_size is None:
        input_size = config.get('input_size', 1)

    if model_type in ['temporal_attention', 'transformer']:
        return TemporalAttentionNetwork(
            input_size=input_size,
            d_model=config.get('d_model', 128),
            nhead=config.get('nhead', 8),
            num_layers=config.get('num_layers', 4),
            dropout=config.get('dropout', 0.1)
        )

    if model_type == 'lstm':
        return LSTMForecaster(
            input_size=input_size,
            hidden_size=config.get('hidden_size', 128),
            num_layers=config.get('num_layers', 2),
            dropout=config.get('dropout', 0.2)
        )

    raise ValueError(
        f"Unknown model type: {model_type}. "
        "Supported: temporal_attention, transformer, lstm. "
        "Graph models (hgt, gnn, ensemble) were removed -- see the module "
        "docstring; the static-graph construction they relied on could not "
        "represent contagion."
    )
