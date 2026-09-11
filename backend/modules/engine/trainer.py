"""Model trainer."""

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
class TrainingMetrics:
    """Training metrics and results."""
    train_loss: List[float]
    val_loss: List[float]
    test_loss: float
    test_mae: float
    test_rmse: float
    test_r2: float
    best_epoch: int
    total_epochs: int
    model_path: str
    predictions_path: str
    baseline_comparison: Optional[Dict[str, Any]] = None


class _FrozenSequenceModelAdapter:
    """Expose a trained sequence model to :class:`WalkForwardBacktester`.

    The harness works on 2-D design matrices, so each row here is one flattened
    window; ``predict`` reshapes it back and runs the frozen artefact. ``fit`` is
    a no-op on purpose -- the comparison measures the trained model out-of-sample
    against baselines that are free to refit on every fold, which is the
    conservative direction for a credibility claim about model complexity.
    """

    def __init__(
        self,
        model: torch.nn.Module,
        device: torch.device,
        sequence_length: int,
        n_features: int,
        target_mean: float,
        target_std: float,
    ) -> None:
        self.model = model
        self.device = device
        self.sequence_length = int(sequence_length)
        self.n_features = int(n_features)
        self.target_mean = float(target_mean)
        self.target_std = float(target_std)

    def fit(self, X, y) -> "_FrozenSequenceModelAdapter":  # noqa: N803 - harness duck type
        return self

    def predict(self, X) -> np.ndarray:  # noqa: N803 - harness duck type
        flat = np.asarray(X, dtype=np.float32)
        windows = flat.reshape(-1, self.sequence_length, self.n_features)
        self.model.eval()
        with torch.no_grad():
            outputs = self.model(torch.FloatTensor(windows).to(self.device))
        return outputs.detach().cpu().numpy().ravel() * self.target_std + self.target_mean


class TimeSeriesDataset(Dataset):
    """Dataset for time series data."""

    def __init__(self, data: pd.DataFrame, sequence_length: int = 30,
                 target_col: str = 'Value', feature_cols: Optional[List[str]] = None):
        """
        Args:
            data: DataFrame with date index and features
            sequence_length: Number of time steps to look back
            target_col: Column to predict
            feature_cols: Feature columns to use (if None, use all numeric)
        """
        self.sequence_length = sequence_length
        self.target_col = target_col

        # Get numeric columns
        if feature_cols is None:
            feature_cols = data.select_dtypes(include=[np.number]).columns.tolist()
            if target_col in feature_cols:
                feature_cols.remove(target_col)

        self.feature_cols = feature_cols

        # Extract features and target. Gaps stay as NaN and are imputed with each
        # column's own observed mean below -- never forward-filled, which would
        # carry a stale level across the gap and present the model with values
        # that had not been published at those timestamps.
        self.features = (
            data[feature_cols]
            .apply(pd.to_numeric, errors='coerce')
            .to_numpy(dtype=float)
        )
        self.target = pd.to_numeric(data[target_col], errors='coerce').to_numpy(dtype=float)

        # Statistics are computed from observed values only. Treating a gap as
        # zero would drag the mean toward zero and inflate the variance.
        target_observed_mask = np.isfinite(self.target)
        target_observed = self.target[target_observed_mask]
        self.target_mean = float(target_observed.mean()) if target_observed.size else 0.0
        self.target_std = float(target_observed.std()) + 1e-8 if target_observed.size else 1.0

        feature_observed_mask = np.isfinite(self.features)
        feature_counts = feature_observed_mask.sum(axis=0)
        feature_sums = np.where(feature_observed_mask, self.features, 0.0).sum(axis=0)
        self.feature_mean = np.divide(
            feature_sums,
            feature_counts,
            out=np.zeros_like(feature_sums, dtype=float),
            where=feature_counts > 0,
        )

        centered = np.where(
            feature_observed_mask, self.features - self.feature_mean, 0.0
        )
        feature_variance = np.divide(
            (centered ** 2).sum(axis=0),
            feature_counts,
            out=np.zeros_like(feature_sums, dtype=float),
            where=feature_counts > 0,
        )
        self.feature_std = np.sqrt(feature_variance) + 1e-8

        # Impute at the observed mean (standardised value 0) rather than carrying
        # the previous observation forward.
        self.features = centered / self.feature_std
        self.target = (
            np.where(target_observed_mask, self.target - self.target_mean, 0.0)
            / self.target_std
        )

        # Create sequences
        self.sequences = []
        self.targets = []

        for i in range(len(data) - sequence_length):
            self.sequences.append(self.features[i:i + sequence_length])
            self.targets.append(self.target[i + sequence_length])

        self.sequences = np.array(self.sequences)
        self.targets = np.array(self.targets)

        logger.info(f"Created dataset with {len(self.sequences)} sequences, "
                   f"{len(feature_cols)} features, sequence_length={sequence_length}")

    def __len__(self):
        return len(self.sequences)

    def __getitem__(self, idx):
        return (
            torch.FloatTensor(self.sequences[idx]),
            torch.FloatTensor([self.targets[idx]])
        )

    def denormalize(self, values):
        """Denormalize predictions back to original scale."""
        return values * self.target_std + self.target_mean


class ModelTrainer:
    """Trainer with the training/validation loop."""

    def __init__(self, model_type: str, device: torch.device, config: Dict):
        self.model_type = model_type
        self.device = device
        self.config = config

        self.model = None
        self.optimizer = None
        self.criterion = nn.MSELoss()
        self.best_val_loss = float('inf')

    def train(self, train_df: pd.DataFrame, val_df: pd.DataFrame, test_df: pd.DataFrame,
              output_dir: str) -> TrainingMetrics:
        """
        Train model on data.

        Args:
            train_df: Training data
            val_df: Validation data
            test_df: Test data
            output_dir: Where to save results

        Returns:
            TrainingMetrics with results
        """
        logger.info(f"Starting training with {self.model_type} model")
        logger.info(f"Train: {len(train_df)}, Val: {len(val_df)}, Test: {len(test_df)} records")

        # Create datasets
        sequence_length = self.config.get('sequence_length', 30)

        train_dataset = TimeSeriesDataset(train_df, sequence_length=sequence_length)
        val_dataset = TimeSeriesDataset(val_df, sequence_length=sequence_length)
        test_dataset = TimeSeriesDataset(test_df, sequence_length=sequence_length)

        # Create data loaders
        batch_size = self.config.get('batch_size', 32)

        train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
        val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)
        test_loader = DataLoader(test_dataset, batch_size=batch_size, shuffle=False)

        # Create model
        input_size = len(train_dataset.feature_cols)
        self.model = create_model(
            self.model_type, self.config, input_size=input_size
        ).to(self.device)

        logger.info(f"Model created: {self.model_type}, input_size={input_size}")
        logger.info(f"Model parameters: {sum(p.numel() for p in self.model.parameters()):,}")

        # Create optimizer
        learning_rate = self.config.get('learning_rate', 0.001)
        self.optimizer = optim.Adam(self.model.parameters(), lr=learning_rate)

        # Learning rate scheduler
        scheduler = optim.lr_scheduler.ReduceLROnPlateau(
            self.optimizer, mode='min', factor=0.5, patience=5, verbose=True
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
                    'model_type': self.model_type
                }, model_path)

            # Log progress
            if (epoch + 1) % 10 == 0:
                logger.info(f"Epoch {epoch + 1}/{epochs} - "
                           f"Train Loss: {train_loss:.6f}, Val Loss: {val_loss:.6f}, "
                           f"Best Val: {self.best_val_loss:.6f} (epoch {best_epoch + 1})")

        # Load best model for testing
        checkpoint = safe_torch_load(model_path)
        self.model.load_state_dict(checkpoint['model_state_dict'])

        # Test evaluation
        logger.info("Evaluating on test set...")
        test_metrics = self._evaluate_test(test_loader, test_dataset)

        # Save predictions
        predictions_path = Path(output_dir) / 'predictions.csv'
        test_metrics['predictions_df'].to_csv(predictions_path, index=False)

        logger.info(f"Test Results - Loss: {test_metrics['test_loss']:.6f}, "
                   f"MAE: {test_metrics['mae']:.4f}, RMSE: {test_metrics['rmse']:.4f}, "
                   f"R²: {test_metrics['r2']:.4f}")

        # Save training history
        history_path = Path(output_dir) / 'training_history.json'
        with open(history_path, 'w') as f:
            json.dump({
                'train_loss': train_losses,
                'val_loss': val_losses,
                'best_epoch': best_epoch,
                'config': self.config
            }, f, indent=2)

        baseline_comparison = self._baseline_comparison(test_dataset)

        return TrainingMetrics(
            train_loss=train_losses,
            val_loss=val_losses,
            test_loss=test_metrics['test_loss'],
            test_mae=test_metrics['mae'],
            test_rmse=test_metrics['rmse'],
            test_r2=test_metrics['r2'],
            best_epoch=best_epoch,
            total_epochs=epochs,
            model_path=str(model_path),
            predictions_path=str(predictions_path),
            baseline_comparison=baseline_comparison,
        )

    def _baseline_comparison(self, dataset: "TimeSeriesDataset") -> Optional[Dict[str, Any]]:
        """Report walk-forward lift over simple baselines.

        A bespoke attention model earns its complexity only by beating something
        simple on the same folds under the same seam-free metrics. The trained
        artefact is frozen here while the baselines refit per fold, so a positive
        lift is a conservative claim. Returns ``None`` (with a logged reason) when
        the test window is too short or the model is not single-input.
        """
        from backend.modules.engine.backtesting import WalkForwardBacktester, WalkForwardConfig

        windows = np.asarray(dataset.sequences, dtype=np.float32)
        if windows.ndim != 3 or windows.shape[0] < 30:
            logger.info(
                "Baseline comparison skipped: %s window(s) is too few for walk-forward folds",
                0 if windows.ndim != 3 else int(windows.shape[0]),
            )
            return None

        sequence_length = int(windows.shape[1])
        n_features = int(windows.shape[2])
        features = windows.reshape(windows.shape[0], -1)
        target = dataset.denormalize(np.asarray(dataset.targets, dtype=float))

        adapter = _FrozenSequenceModelAdapter(
            model=self.model,
            device=self.device,
            sequence_length=sequence_length,
            n_features=n_features,
            target_mean=float(dataset.target_mean),
            target_std=float(dataset.target_std),
        )
        config = WalkForwardConfig(n_splits=3, test_size=0.2, gap=0, expanding=True, min_train_size=5)
        try:
            # The factory returns the same frozen adapter every fold: `fit` is a
            # no-op, so there is no state to leak between folds.
            comparison = WalkForwardBacktester(lambda: adapter, config).compare(
                features, target, baselines=("persistence", "ar1")
            )
        except (TypeError, ValueError) as exc:
            logger.warning("Baseline comparison skipped: %s", exc)
            return None

        payload = comparison.to_dict()
        return {
            "config": payload["primary"]["config"],
            "aggregation": payload["primary"]["aggregation"],
            "primary_metrics": payload["primary"]["metrics"],
            "baseline_metrics": {
                name: result["metrics"] for name, result in payload["baselines"].items()
            },
            "lift": payload["lift"],
            "lift_convention": payload["lift_convention"],
            "lower_is_better": payload["lower_is_better"],
        }

    def _train_epoch(self, dataloader: DataLoader) -> float:
        """Train for one epoch."""
        self.model.train()
        total_loss = 0.0

        for sequences, targets in dataloader:
            sequences = sequences.to(self.device)
            targets = targets.to(self.device)

            # Forward pass
            self.optimizer.zero_grad()
            outputs = self.model(sequences)

            # Compute loss
            loss = self.criterion(outputs, targets)

            # Backward pass
            loss.backward()
            self.optimizer.step()

            total_loss += loss.item()

        return total_loss / len(dataloader)

    def _validate(self, dataloader: DataLoader) -> float:
        """Validate model."""
        self.model.eval()
        total_loss = 0.0

        with torch.no_grad():
            for sequences, targets in dataloader:
                sequences = sequences.to(self.device)
                targets = targets.to(self.device)

                outputs = self.model(sequences)
                loss = self.criterion(outputs, targets)

                total_loss += loss.item()

        return total_loss / len(dataloader)

    def _evaluate_test(self, dataloader: DataLoader, dataset: TimeSeriesDataset) -> Dict:
        """Comprehensive test set evaluation."""
        self.model.eval()
        all_predictions = []
        all_targets = []

        with torch.no_grad():
            for sequences, targets in dataloader:
                sequences = sequences.to(self.device)
                outputs = self.model(sequences)

                all_predictions.extend(outputs.cpu().numpy().flatten())
                all_targets.extend(targets.cpu().numpy().flatten())

        all_predictions = np.array(all_predictions)
        all_targets = np.array(all_targets)

        # Denormalize
        predictions_denorm = dataset.denormalize(all_predictions)
        targets_denorm = dataset.denormalize(all_targets)

        # Compute metrics
        mse = np.mean((predictions_denorm - targets_denorm) ** 2)
        mae = np.mean(np.abs(predictions_denorm - targets_denorm))
        rmse = np.sqrt(mse)

        # R² score
        ss_res = np.sum((targets_denorm - predictions_denorm) ** 2)
        ss_tot = np.sum((targets_denorm - targets_denorm.mean()) ** 2)
        r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

        # Create predictions dataframe
        predictions_df = pd.DataFrame({
            'actual': targets_denorm,
            'predicted': predictions_denorm,
            'error': targets_denorm - predictions_denorm,
            'abs_error': np.abs(targets_denorm - predictions_denorm)
        })

        return {
            'test_loss': mse,
            'mae': mae,
            'rmse': rmse,
            'r2': r2,
            'predictions_df': predictions_df
        }
