"""REAL Model Trainer - Actual training implementation."""

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import pandas as pd
import numpy as np
from typing import Dict, Tuple, List, Optional
from dataclasses import dataclass
import logging
from pathlib import Path
import json

from .models import create_model

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

        # Extract features and target
        self.features = data[feature_cols].ffill().fillna(0).values
        self.target = data[target_col].ffill().fillna(0).values

        # Store original stats BEFORE normalization
        self.target_mean = float(np.mean(self.target))
        self.target_std = float(np.std(self.target) + 1e-8)

        # Normalize
        self.feature_mean = self.features.mean(axis=0)
        self.feature_std = self.features.std(axis=0) + 1e-8
        self.features = (self.features - self.feature_mean) / self.feature_std

        self.target = (self.target - self.target_mean) / self.target_std

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
    """REAL model trainer with actual training loop."""

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
        logger.info(f"Starting REAL training with {self.model_type} model")
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
        self.model = create_model(self.model_type, input_size, self.config).to(self.device)

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
        epochs = self.config.get('epochs', 50)
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
                torch.save({
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
        checkpoint = torch.load(model_path)
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
            predictions_path=str(predictions_path)
        )

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
