"""Multi-scale trainer for heterogeneous data sources."""

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import pandas as pd
import numpy as np
from typing import Any, Dict, Tuple, List, Optional
from dataclasses import dataclass
import logging
from pathlib import Path
import json

from .models import create_model
from .model_io import safe_torch_load, safe_torch_save

logger = logging.getLogger(__name__)


@dataclass
class MultiScaleTrainingMetrics:
    """Training metrics for multi-scale models."""
    train_loss: List[float]
    val_loss: List[float]
    test_loss: float
    test_mae: float
    test_rmse: float
    test_r2: float
    per_source_metrics: Dict[str, Dict]
    best_epoch: int
    total_epochs: int
    model_path: str
    predictions_path: str
    baseline_comparison: Optional[Dict[str, Any]] = None


class MultiSourceDataset(Dataset):
    """
    Dataset that handles multiple data sources with different scales.

    Key features:
    - Per-source normalization (not global)
    - Preserves source identity
    - Creates sequences per source
    """

    def __init__(self, data: pd.DataFrame, sequence_length: int = 30, source_to_id: dict = None,
                 source_stats: dict = None):
        """
        Args:
            data: DataFrame with columns: Date, Value, source_code
            sequence_length: Number of time steps
            source_to_id: Optional pre-defined source to ID mapping (for test/val sets)
            source_stats: Optional pre-computed per-source normalization stats
                ``{source: {'mean': float, 'std': float}}`` from the TRAINING
                split. Val/test datasets must be built with the training stats:
                the model was trained in the training split's standardized
                space, so normalizing an evaluation split with its own stats
                both leaks that split into the reported metric and evaluates
                the model in a space it never saw. When omitted (training
                split), stats are computed per source from observed values.
        """
        self.sequence_length = sequence_length
        self.data = data.copy()

        # ``source_code`` identifies a feed, not necessarily a single time
        # series.  Panel feeds (for example AI4Risk's bank-to-bank edges) must
        # keep their entity history separate or a window will jump from one
        # edge to another at the same quarter.  ``series_id`` is added by the
        # DATA formatter for those panels; legacy frames without it retain the
        # original source grouping.
        self.series_column = 'series_id' if 'series_id' in self.data.columns else 'source_code'
        if 'source_code' in self.data.columns:
            self.sources = self.data['source_code'].dropna().astype(str).unique()
        else:
            self.sources = self.data[self.series_column].dropna().astype(str).unique()

        # Use provided mapping or create new one
        if source_to_id is not None:
            self.source_to_id = source_to_id
        else:
            self.source_to_id = {str(src): i for i, src in enumerate(self.sources)}

        # Per-source normalization stats. `external_stats` marks a dataset that
        # must not invent its own: a source with no training-split stats was
        # never trained on and is skipped rather than standardized ad hoc.
        self.external_stats = source_stats is not None
        if self.external_stats:
            self.source_stats = {
                src: {'mean': float(st['mean']), 'std': float(st['std'])}
                for src, st in source_stats.items()
            }
        else:
            self.source_stats = {}

        # Store sequences per source
        self.sequences = []
        self.targets = []
        self.source_ids = []

        if self.series_column == 'source_code':
            series_groups = self.data.groupby('source_code', sort=False, dropna=False)
        else:
            series_groups = self.data.groupby('series_id', sort=False, dropna=False)

        for _, source_data in series_groups:
            source_data = source_data.copy()
            source = (
                str(source_data['source_code'].iloc[0])
                if 'source_code' in source_data.columns
                else str(source_data[self.series_column].iloc[0])
            )
            source_data = source_data.sort_values('Date')

            # Extract values - use 'Close' column from timeseries data. Gaps are
            # preserved and imputed with the observed mean below, never carried
            # forward: forward-filling would present the encoder with a level
            # that had not been published at that timestamp.
            value_column = 'Close' if 'Close' in source_data.columns else 'Value'
            values = (
                pd.to_numeric(source_data[value_column], errors='coerce')
                .to_numpy(dtype=float)
            )
            if len(values) < 2:
                logger.warning("Skipping source '%s' – not enough points (%d)", source, len(values))
                continue

            observed = np.isfinite(values)
            observed_values = values[observed]
            if observed_values.size == 0:
                logger.warning("Skipping source '%s' – no observed values", source)
                continue

            # Normalization stats: from the training split when provided, else
            # computed PER SOURCE from observed values only.
            if self.external_stats:
                if source not in self.source_stats:
                    logger.warning(
                        "Skipping source '%s' – no training-split statistics for it; "
                        "refusing to standardize an evaluation split with its own stats",
                        source,
                    )
                    continue
                mean = self.source_stats[source]['mean']
                std = self.source_stats[source]['std']
                if not np.isfinite(std) or std <= 0.0:
                    std = 1.0
            else:
                mean = float(observed_values.mean())
                std = float(observed_values.std() + 1e-8)
                self.source_stats[source] = {'mean': mean, 'std': std}

            # Normalize, then impute unobserved entries at the standardised mean.
            normalized = (values - mean) / std
            normalized = np.where(np.isfinite(normalized), normalized, 0.0)

            # Create sequences for this source
            # Skip sources not in the mapping (can happen in test/val sets)
            if source not in self.source_to_id:
                logger.warning(f"Skipping source '{source}' - not in training set")
                continue

            # Allow shorter sequences by shrinking the window and padding
            window = min(sequence_length, len(normalized) - 1)
            if window < 1:
                logger.warning("Skipping source '%s' – unable to form sequences", source)
                continue

            for i in range(len(normalized) - window):
                # Never train on an imputed target: the label would be a
                # substituted mean rather than an observation, and the model
                # would be rewarded for reproducing it.
                if not observed[i + window]:
                    continue
                seq = normalized[i:i + window]
                if len(seq) < sequence_length:
                    pad_width = sequence_length - len(seq)
                    # Zero-pad at the standardised mean, matching the inference
                    # path (`RealPredictionEngine._prepare_sequence`). Edge
                    # padding replicated the oldest observation instead, so a
                    # short-window source was trained on a different padding
                    # law than the one applied to it at prediction time.
                    seq = np.pad(seq, (pad_width, 0), mode='constant', constant_values=0.0)
                self.sequences.append(seq)
                self.targets.append(normalized[i + window])
                self.source_ids.append(self.source_to_id[source])

        self.sequences = np.array(self.sequences)
        self.targets = np.array(self.targets)
        self.source_ids = np.array(self.source_ids)

        logger.info(f"Created multi-source dataset: {len(self.sequences)} sequences from {len(self.sources)} sources")
        for source, stats in self.source_stats.items():
            logger.info(f"  {source}: mean={stats['mean']:.2f}, std={stats['std']:.2f}")

    def __len__(self):
        return len(self.sequences)

    def __getitem__(self, idx):
        return (
            torch.FloatTensor(self.sequences[idx]),
            torch.FloatTensor([self.targets[idx]]),
            torch.LongTensor([self.source_ids[idx]])
        )

    def denormalize(self, values, source_ids):
        """Denormalize predictions back to original scale per source."""
        # Create reverse mapping from id to source name
        id_to_source = {v: k for k, v in self.source_to_id.items()}

        denormalized = []
        for val, src_id in zip(values, source_ids):
            # Map numeric id back to source name
            source = id_to_source.get(src_id)
            if source is None or source not in self.source_stats:
                # Use first source as fallback if source not found
                source = self.sources[0]
            stats = self.source_stats[source]
            denorm_val = val * stats['std'] + stats['mean']
            denormalized.append(denorm_val)
        return np.array(denormalized)


class MultiScaleTemporalAttentionModel(nn.Module):
    """
    Temporal Attention model with per-source processing.

    This is the RIGHT approach for multi-scale data:
    1. Separate encoding per source type
    2. Shared temporal attention
    3. Source-aware prediction head
    """

    def __init__(
        self,
        num_sources: int,
        sequence_length: int = 30,
        d_model: int = 128,
        nhead: int = 8,
        num_layers: int = 3,
        dropout: float = 0.1
    ):
        super().__init__()

        self.num_sources = num_sources
        self.d_model = d_model

        # Per-source input encoders
        self.source_encoders = nn.ModuleList([
            nn.Sequential(
                nn.Linear(sequence_length, d_model),
                nn.LayerNorm(d_model),
                nn.ReLU(),
                nn.Dropout(dropout)
            )
            for _ in range(num_sources)
        ])

        # Source embeddings
        self.source_embeddings = nn.Embedding(num_sources, d_model)

        # Shared temporal attention
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=d_model * 4,
            dropout=dropout,
            batch_first=True,
            activation='gelu'
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)

        # Per-source prediction heads
        self.source_predictors = nn.ModuleList([
            nn.Sequential(
                nn.Linear(d_model, d_model // 2),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(d_model // 2, 1)
            )
            for _ in range(num_sources)
        ])

    def forward(self, x, source_ids):
        """
        Args:
            x: (batch, sequence_length)
            source_ids: (batch,) - which source each sample belongs to

        Returns:
            predictions: (batch, 1)
        """
        batch_size = x.size(0)

        # Encode per source
        encoded = []
        for i in range(batch_size):
            src_id = source_ids[i].item()
            x_i = x[i].unsqueeze(0)  # (1, seq_len)
            encoded_i = self.source_encoders[src_id](x_i)
            encoded.append(encoded_i)

        encoded = torch.cat(encoded, dim=0)  # (batch, d_model)

        # Add source embeddings
        src_embeds = self.source_embeddings(source_ids.squeeze())
        encoded = encoded + src_embeds

        # Temporal attention (add sequence dimension)
        encoded_seq = encoded.unsqueeze(1)  # (batch, 1, d_model)
        attended = self.transformer(encoded_seq)
        attended = attended.squeeze(1)  # (batch, d_model)

        # Predict per source
        predictions = []
        for i in range(batch_size):
            src_id = source_ids[i].item()
            pred_i = self.source_predictors[src_id](attended[i].unsqueeze(0))
            predictions.append(pred_i)

        predictions = torch.cat(predictions, dim=0)

        return predictions


class MultiScaleTrainer:
    """Trainer for multi-scale, multi-source data."""

    def __init__(self, model_type: str, device: torch.device, config: Dict):
        self.model_type = model_type
        self.device = device
        self.config = config

        self.model = None
        self.optimizer = None
        self.criterion = nn.MSELoss()
        self.best_val_loss = float('inf')
        self.use_amp = bool(config.get('mixed_precision', True)) and self.device.type == 'cuda'
        self.scaler = torch.amp.GradScaler('cuda', enabled=self.use_amp)

    def train(
        self,
        train_df: pd.DataFrame,
        val_df: pd.DataFrame,
        test_df: pd.DataFrame,
        output_dir: str
    ) -> MultiScaleTrainingMetrics:
        """
        Train model on multi-source data.

        Args:
            train_df, val_df, test_df: DataFrames with Date, Value, source_code columns
            output_dir: Where to save results

        Returns:
            MultiScaleTrainingMetrics
        """
        logger.info(f"Starting MULTI-SCALE training with {self.model_type} model")

        # Create datasets with per-source normalization
        sequence_length = self.config.get('sequence_length', 30)

        # Create train dataset first to get source mapping AND normalization
        # stats. Val/test are built with the training stats and the training
        # source map: each split standardizing itself is a leak (the split's
        # own data informs the reported metric) and a space mismatch (the
        # model's outputs live in the training split's standardized space).
        train_dataset = MultiSourceDataset(train_df, sequence_length=sequence_length)

        val_dataset = MultiSourceDataset(
            val_df,
            sequence_length=sequence_length,
            source_to_id=train_dataset.source_to_id,
            source_stats=train_dataset.source_stats,
        )
        test_dataset = MultiSourceDataset(
            test_df,
            sequence_length=sequence_length,
            source_to_id=train_dataset.source_to_id,
            source_stats=train_dataset.source_stats,
        )

        # Empty splits are a loud failure, not a warning. An empty validation
        # loader used to make `_validate` report 0.0 forever, which froze model
        # selection at the epoch-0 checkpoint while the job "completed
        # successfully" -- the production defect reproduced in
        # backend/tests/test_trainer_composition.py.
        if len(train_dataset) == 0:
            raise ValueError("Training dataset is empty - no valid sequences created")
        if len(val_dataset) == 0:
            raise ValueError(
                "Validation dataset is empty: no validation source has enough "
                "rows to form a window under the training source map. Refusing "
                "to train, because model selection against an empty split is "
                "meaningless (it silently ships the epoch-0 checkpoint). Check "
                "the train/val split: it must be chronological within sources, "
                "not a positional cut across a source-major frame."
            )
        if len(test_dataset) == 0:
            raise ValueError(
                "Test dataset is empty: no test source has enough rows to form "
                "a window under the training source map. Refusing to report "
                "evaluation metrics for data that does not exist."
            )

        # Get number of sources
        num_sources = len(train_dataset.sources)
        logger.info(f"Training with {num_sources} data sources")
        logger.info(f"Dataset sizes: Train={len(train_dataset)}, Val={len(val_dataset)}, Test={len(test_dataset)}")

        # Create data loaders
        batch_size = self.config.get('batch_size', 32)

        train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
        val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)
        test_loader = DataLoader(test_dataset, batch_size=batch_size, shuffle=False)

        # Create model
        if self.model_type in ['temporal_attention', 'transformer']:
            self.model = MultiScaleTemporalAttentionModel(
                num_sources=num_sources,
                sequence_length=sequence_length,
                d_model=self.config.get('d_model', 128),
                nhead=self.config.get('nhead', 8),
                num_layers=self.config.get('num_layers', 3),
                dropout=self.config.get('dropout', 0.1)
            ).to(self.device)
        else:
            # For now, use temporal attention as default
            logger.warning(f"Model type {self.model_type} not fully integrated with multi-scale, using temporal_attention")
            self.model = MultiScaleTemporalAttentionModel(
                num_sources=num_sources,
                sequence_length=sequence_length,
                d_model=self.config.get('d_model', 128),
                nhead=self.config.get('nhead', 8),
                num_layers=self.config.get('num_layers', 3),
                dropout=self.config.get('dropout', 0.1)
            ).to(self.device)

        logger.info(f"Model created with {sum(p.numel() for p in self.model.parameters()):,} parameters")

        # Optimizer
        learning_rate = self.config.get('learning_rate', 0.001)
        self.optimizer = optim.AdamW(
            self.model.parameters(),
            lr=learning_rate,
            weight_decay=self.config.get('weight_decay', 0.01)
        )

        # Learning rate scheduler
        scheduler = optim.lr_scheduler.ReduceLROnPlateau(
            self.optimizer, mode='min', factor=0.5, patience=5
        )

        # Training loop
        epochs = self.config.get('epochs', self.config.get('num_epochs', 50))
        train_losses = []
        val_losses = []
        best_epoch = 0

        logger.info(f"Training for {epochs} epochs...")

        for epoch in range(epochs):
            # Train
            train_loss = self._train_epoch(train_loader)
            train_losses.append(train_loss)

            # Validate
            val_loss = self._validate(val_loader)
            val_losses.append(val_loss)

            # Learning rate scheduling
            scheduler.step(val_loss)

            # Save best model
            if val_loss < self.best_val_loss:
                self.best_val_loss = val_loss
                best_epoch = epoch
                model_path = Path(output_dir) / 'best_model.pt'
                safe_torch_save({
                    'epoch': epoch,
                    'model_state_dict': self.model.state_dict(),
                    'optimizer_state_dict': self.optimizer.state_dict(),
                    'train_loss': train_loss,
                    'val_loss': val_loss,
                    'config': self.config,
                    'model_type': self.model_type,
                    'source_stats': train_dataset.source_stats,
                    'sources': train_dataset.sources.tolist()
                }, model_path)

            # Log progress
            if (epoch + 1) % 10 == 0 or epoch == 0:
                logger.info(f"Epoch {epoch + 1}/{epochs} - "
                           f"Train Loss: {train_loss:.6f}, Val Loss: {val_loss:.6f}, "
                           f"Best Val: {self.best_val_loss:.6f} (epoch {best_epoch + 1})")

        # Load best model
        checkpoint = safe_torch_load(model_path)
        self.model.load_state_dict(checkpoint['model_state_dict'])

        # Test evaluation
        logger.info("Evaluating on test set...")
        test_metrics = self._evaluate_test(test_loader, test_dataset)

        # Save predictions
        predictions_path = Path(output_dir) / 'predictions.csv'
        test_metrics['predictions_df'].to_csv(predictions_path, index=False)

        # Per-source metrics
        per_source_metrics = self._compute_per_source_metrics(test_metrics['predictions_df'])

        logger.info(f"Test Results - Loss: {test_metrics['test_loss']:.6f}, "
                   f"MAE: {test_metrics['mae']:.4f}, RMSE: {test_metrics['rmse']:.4f}, "
                   f"R²: {test_metrics['r2']:.4f}")

        for source, metrics in per_source_metrics.items():
            logger.info(f"  {source}: MAE={metrics['mae']:.2f}, RMSE={metrics['rmse']:.2f}, R²={metrics['r2']:.4f}")

        baseline_comparison = None
        try:
            baseline_comparison = self._baseline_comparison(test_dataset)
        except Exception as exc:  # noqa: BLE001 - lift is a credibility report, not a result
            logger.warning("Multi-scale baseline comparison skipped: %s", exc)

        # Save training history
        history_path = Path(output_dir) / 'training_history.json'
        with open(history_path, 'w') as f:
            json.dump({
                'train_loss': train_losses,
                'val_loss': val_losses,
                'best_epoch': best_epoch,
                'config': self.config,
                'per_source_metrics': per_source_metrics
            }, f, indent=2)

        return MultiScaleTrainingMetrics(
            train_loss=train_losses,
            val_loss=val_losses,
            test_loss=test_metrics['test_loss'],
            test_mae=test_metrics['mae'],
            test_rmse=test_metrics['rmse'],
            test_r2=test_metrics['r2'],
            per_source_metrics=per_source_metrics,
            best_epoch=best_epoch,
            total_epochs=epochs,
            model_path=str(model_path),
            predictions_path=str(predictions_path),
            baseline_comparison=baseline_comparison
        )

    def _baseline_comparison(self, test_dataset: "MultiSourceDataset") -> Optional[Dict[str, Any]]:
        """Walk-forward lift over simple baselines, per source.

        The single-scale trainer has reported this since round two; the
        multi-scale trainer did not, so its complexity went unpriced. Same
        convention: the trained artefact is frozen while persistence and AR(1)
        refit per fold, on each source's own denormalized series, folded
        within the source so no fold crosses a seam.
        """
        from backend.modules.engine.backtesting import (
            WalkForwardBacktester,
            WalkForwardConfig,
        )

        class _FrozenMultiScaleAdapter:
            def __init__(self, trainer, source_id, stats, seq_len):
                self.trainer = trainer
                self.source_id = source_id
                self.stats = stats
                self.seq_len = seq_len

            def fit(self, X, y):
                return self

            def predict(self, X):
                flat = np.asarray(X, dtype=np.float32)
                windows = flat.reshape(-1, self.seq_len, 1)
                model = self.trainer.model
                model.eval()
                with torch.no_grad():
                    ids = torch.full((windows.shape[0], 1), self.source_id, dtype=torch.long)
                    out = model(torch.FloatTensor(windows), ids)
                return out.detach().cpu().numpy().ravel() * self.stats['std'] + self.stats['mean']

        config = WalkForwardConfig(n_splits=3, test_size=0.2, gap=0, expanding=True, min_train_size=5)
        seq_len = int(self.config.get('sequence_length', 30))
        per_source: Dict[str, Any] = {}
        lifts = []

        for source, stats in test_dataset.source_stats.items():
            source_id = test_dataset.source_to_id.get(source)
            if source_id is None:
                continue
            frame = test_dataset.data[test_dataset.data['source_code'] == source].sort_values('Date')
            value_col = 'Close' if 'Close' in frame.columns else 'Value'
            values = pd.to_numeric(frame[value_col], errors='coerce').to_numpy(dtype=float)
            values = values[np.isfinite(values)]
            if values.size < seq_len + 10:
                per_source[source] = {"skipped": "series too short for folds"}
                continue
            normalized = (values - stats['mean']) / stats['std']
            windows = np.lib.stride_tricks.sliding_window_view(normalized, seq_len)
            targets_raw = values[seq_len:]
            if windows.shape[0] < 30 or targets_raw.size != windows.shape[0]:
                per_source[source] = {"skipped": "not enough windows"}
                continue
            adapter = _FrozenMultiScaleAdapter(self, source_id, stats, seq_len)
            features = windows.reshape(windows.shape[0], -1)
            try:
                comparison = WalkForwardBacktester(lambda: adapter, config).compare(
                    features, targets_raw, baselines=("persistence", "ar1")
                )
            except (TypeError, ValueError) as exc:
                per_source[source] = {"skipped": str(exc)}
                continue
            payload = comparison.to_dict()
            per_source[source] = {
                "primary_metrics": payload["primary"]["metrics"],
                "baseline_metrics": {name: res["metrics"] for name, res in payload["baselines"].items()},
                "lift": payload["lift"],
            }
            for lift in payload["lift"].values():
                if isinstance(lift, (int, float)) and np.isfinite(lift):
                    lifts.append(float(lift))

        if not per_source:
            return None
        return {
            "aggregation": "per_source",
            "per_source": per_source,
            "mean_lift": float(np.mean(lifts)) if lifts else None,
        }

    def _train_epoch(self, dataloader: DataLoader) -> float:
        """Train for one epoch."""
        self.model.train()
        total_loss = 0.0

        for sequences, targets, source_ids in dataloader:
            sequences = sequences.to(self.device)
            targets = targets.to(self.device)
            source_ids = source_ids.to(self.device)

            # Forward pass
            self.optimizer.zero_grad()
            with torch.amp.autocast('cuda', enabled=self.use_amp):
                outputs = self.model(sequences, source_ids)

                # Compute loss
                loss = self.criterion(outputs, targets)

            # Backward pass (GradScaler is a no-op when AMP is inactive)
            self.scaler.scale(loss).backward()
            self.scaler.unscale_(self.optimizer)
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
            self.scaler.step(self.optimizer)
            self.scaler.update()

            total_loss += loss.item()

        return total_loss / len(dataloader)

    def _validate(self, dataloader: DataLoader) -> float:
        """Validate model.

        An empty loader is a hard error, never a 0.0 loss: 0.0 is the best
        loss the selector can ever see, so returning it silently froze model
        selection at whichever checkpoint existed first.
        """
        if len(dataloader) == 0:
            raise ValueError(
                "Validation dataloader is empty; refusing to report a 0.0 loss "
                "that would freeze model selection at the first checkpoint"
            )

        self.model.eval()
        total_loss = 0.0

        with torch.no_grad():
            for sequences, targets, source_ids in dataloader:
                sequences = sequences.to(self.device)
                targets = targets.to(self.device)
                source_ids = source_ids.to(self.device)

                outputs = self.model(sequences, source_ids)
                loss = self.criterion(outputs, targets)

                total_loss += loss.item()

        return total_loss / len(dataloader)

    def _evaluate_test(self, dataloader: DataLoader, dataset: MultiSourceDataset) -> Dict:
        """Comprehensive test set evaluation."""
        if len(dataloader) == 0:
            logger.warning("Test dataloader is empty, returning default metrics")
            return {
                'test_loss': 0.0,
                'mae': 0.0,
                'rmse': 0.0,
                'r2': 0.0,
                'predictions_df': pd.DataFrame(columns=['source', 'actual', 'predicted', 'error', 'abs_error', 'pct_error'])
            }

        self.model.eval()
        all_predictions = []
        all_targets = []
        all_source_ids = []

        with torch.no_grad():
            for sequences, targets, source_ids in dataloader:
                sequences = sequences.to(self.device)
                source_ids = source_ids.to(self.device)

                outputs = self.model(sequences, source_ids)

                all_predictions.extend(outputs.cpu().numpy().flatten())
                all_targets.extend(targets.numpy().flatten())
                all_source_ids.extend(source_ids.cpu().numpy().flatten())

        all_predictions = np.array(all_predictions)
        all_targets = np.array(all_targets)
        all_source_ids = np.array(all_source_ids)

        # Denormalize per source
        predictions_denorm = dataset.denormalize(all_predictions, all_source_ids)
        targets_denorm = dataset.denormalize(all_targets, all_source_ids)

        # Compute metrics
        mse = np.mean((predictions_denorm - targets_denorm) ** 2)
        mae = np.mean(np.abs(predictions_denorm - targets_denorm))
        rmse = np.sqrt(mse)

        # R² score
        ss_res = np.sum((targets_denorm - predictions_denorm) ** 2)
        ss_tot = np.sum((targets_denorm - targets_denorm.mean()) ** 2)
        r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

        # Get source names - map from numeric id to source name
        id_to_source = {v: k for k, v in dataset.source_to_id.items()}
        source_names = [id_to_source.get(sid, dataset.sources[0]) for sid in all_source_ids]

        # Create predictions dataframe
        predictions_df = pd.DataFrame({
            'source': source_names,
            'actual': targets_denorm,
            'predicted': predictions_denorm,
            'error': targets_denorm - predictions_denorm,
            'abs_error': np.abs(targets_denorm - predictions_denorm),
            'pct_error': np.abs((targets_denorm - predictions_denorm) / (targets_denorm + 1e-8)) * 100
        })

        return {
            'test_loss': mse,
            'mae': mae,
            'rmse': rmse,
            'r2': r2,
            'predictions_df': predictions_df
        }

    def _compute_per_source_metrics(self, predictions_df: pd.DataFrame) -> Dict[str, Dict]:
        """Compute metrics per data source."""
        if predictions_df.empty or 'source' not in predictions_df.columns:
            return {}

        per_source = {}

        for source in predictions_df['source'].unique():
            source_df = predictions_df[predictions_df['source'] == source]

            mse = np.mean(source_df['error'] ** 2)
            mae = np.mean(source_df['abs_error'])
            rmse = np.sqrt(mse)

            ss_res = np.sum(source_df['error'] ** 2)
            ss_tot = np.sum((source_df['actual'] - source_df['actual'].mean()) ** 2)
            r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

            per_source[source] = {
                'mae': float(mae),
                'rmse': float(rmse),
                'r2': float(r2),
                'num_samples': len(source_df)
            }

        return per_source
