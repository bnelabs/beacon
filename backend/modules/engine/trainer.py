"""Model trainer."""

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import pandas as pd
import numpy as np
from typing import Any, Dict, Tuple, List, Optional
from dataclasses import dataclass, replace
import shutil
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
                 target_col: str = 'Value', feature_cols: Optional[List[str]] = None,
                 norm_stats: Optional[Dict[str, Any]] = None):
        """
        Args:
            data: DataFrame with date index and features
            sequence_length: Number of time steps to look back
            target_col: Column to predict
            feature_cols: Feature columns to use (if None, use all numeric)
            norm_stats: Optional normalization statistics captured from the
                TRAINING dataset (:meth:`normalization_stats`). Val/test
                datasets must be built with the training stats: each split
                standardizing itself evaluates the model in a space it never
                saw and leaks the split's own data into the reported metric.
        """
        self.sequence_length = sequence_length
        self.target_col = target_col

        # Get numeric columns
        if norm_stats is not None:
            # The training split decides the feature columns; an evaluation
            # frame missing one is an error, not a silent schema change.
            feature_cols = list(norm_stats['feature_cols'])
            missing = [c for c in feature_cols if c not in data.columns]
            if missing:
                raise ValueError(
                    f"Evaluation frame is missing training feature columns: {missing}"
                )
        elif feature_cols is None:
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

        # Statistics come from the TRAINING split when provided (norm_stats),
        # otherwise from this frame's observed values only. Treating a gap as
        # zero would drag the mean toward zero and inflate the variance, so
        # only observed entries contribute either way.
        target_observed_mask = np.isfinite(self.target)
        feature_observed_mask = np.isfinite(self.features)
        if norm_stats is not None:
            self.target_mean = float(norm_stats['target_mean'])
            self.target_std = float(norm_stats['target_std'])
            self.feature_mean = np.asarray(norm_stats['feature_mean'], dtype=float)
            self.feature_std = np.asarray(norm_stats['feature_std'], dtype=float)
        else:
            target_observed = self.target[target_observed_mask]
            self.target_mean = float(target_observed.mean()) if target_observed.size else 0.0
            self.target_std = float(target_observed.std()) + 1e-8 if target_observed.size else 1.0

            feature_counts = feature_observed_mask.sum(axis=0)
            feature_sums = np.where(feature_observed_mask, self.features, 0.0).sum(axis=0)
            self.feature_mean = np.divide(
                feature_sums,
                feature_counts,
                out=np.zeros_like(feature_sums, dtype=float),
                where=feature_counts > 0,
            )

            feature_variance = np.divide(
                (np.where(feature_observed_mask, self.features - self.feature_mean, 0.0) ** 2).sum(axis=0),
                feature_counts,
                out=np.zeros_like(feature_sums, dtype=float),
                where=feature_counts > 0,
            )
            self.feature_std = np.sqrt(feature_variance) + 1e-8

        centered = np.where(
            feature_observed_mask, self.features - self.feature_mean, 0.0
        )

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

    def normalization_stats(self) -> Dict[str, Any]:
        """Capture the stats an evaluation split must reuse.

        Built from the TRAINING dataset and passed to val/test datasets as
        ``norm_stats``, so every split lives in one standardized space -- the
        one the model was trained in.
        """
        return {
            'feature_cols': list(self.feature_cols),
            'target_mean': float(self.target_mean),
            'target_std': float(self.target_std),
            'feature_mean': np.asarray(self.feature_mean, dtype=float).tolist(),
            'feature_std': np.asarray(self.feature_std, dtype=float).tolist(),
        }


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
        # Mixed precision is real now (the README claimed it before it
        # existed): active only on CUDA, fp32 elsewhere and in validation.
        self.use_amp = bool(config.get('mixed_precision', True)) and self.device.type == 'cuda'
        self.scaler = torch.amp.GradScaler('cuda', enabled=self.use_amp)

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

        # Create datasets. Val/test reuse the TRAINING split's normalization
        # stats: each split standardizing itself evaluates the model in a
        # space it never saw, and lets the evaluation split's own data leak
        # into the reported metric.
        sequence_length = self.config.get('sequence_length', 30)

        train_dataset = TimeSeriesDataset(train_df, sequence_length=sequence_length)
        train_stats = train_dataset.normalization_stats()
        val_dataset = TimeSeriesDataset(val_df, sequence_length=sequence_length,
                                        norm_stats=train_stats)
        test_dataset = TimeSeriesDataset(test_df, sequence_length=sequence_length,
                                         norm_stats=train_stats)

        # Empty splits are a loud failure, not a warning: an empty validation
        # loader makes model selection meaningless, and an empty test loader
        # would report metrics for data that does not exist.
        if len(train_dataset) == 0:
            raise ValueError(
                "Training dataset is empty - no valid sequences created "
                f"(need more than sequence_length={sequence_length} rows)"
            )
        if len(val_dataset) == 0:
            raise ValueError(
                "Validation dataset is empty - refusing to train, because "
                "model selection against an empty split silently ships the "
                "first checkpoint. Check that the train/val split is "
                "chronological and leaves enough rows for a window."
            )
        if len(test_dataset) == 0:
            raise ValueError(
                "Test dataset is empty - refusing to report evaluation metrics "
                "for data that does not exist."
            )

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
        from backend.modules.engine.backtesting import (
            CPCVBacktester,
            WalkForwardBacktester,
            WalkForwardConfig,
        )
        from backend.modules.engine.cpcv import CPCVConfig

        # Which validation schemes to report. An unrecognised value raises rather
        # than being ignored: a caller who asks for CPCV and silently receives only
        # walk-forward would believe a stronger claim was checked than actually was.
        scheme = str(self.config.get("validation_scheme", "walk_forward")).strip().lower()
        if scheme not in ("walk_forward", "cpcv", "both"):
            raise ValueError(
                f"validation_scheme must be one of 'walk_forward', 'cpcv', 'both'; "
                f"got {scheme!r}"
            )

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

        walk_forward_payload: Optional[Dict[str, Any]] = None
        if scheme in ("walk_forward", "both"):
            try:
                # The factory returns the same frozen adapter every fold: `fit` is a
                # no-op, so there is no state to leak between folds.
                comparison = WalkForwardBacktester(lambda: adapter, config).compare(
                    features, target, baselines=("persistence", "ar1")
                )
            except (TypeError, ValueError) as exc:
                logger.warning("Walk-forward comparison skipped: %s", exc)
                if scheme == "walk_forward":
                    return None
            else:
                payload = comparison.to_dict()
                walk_forward_payload = {
                    "config": payload["primary"]["config"],
                    "aggregation": payload["primary"]["aggregation"],
                    "primary_metrics": payload["primary"]["metrics"],
                    "baseline_metrics": {
                        name: result["metrics"]
                        for name, result in payload["baselines"].items()
                    },
                    "lift": payload["lift"],
                    "lift_convention": payload["lift_convention"],
                    "lower_is_better": payload["lower_is_better"],
                }

        cpcv_payload: Optional[Dict[str, Any]] = None
        if scheme in ("cpcv", "both"):
            cpcv_config = CPCVConfig(
                n_groups=int(self.config.get("cpcv_n_groups", 6)),
                n_test_groups=int(self.config.get("cpcv_n_test_groups", 2)),
                label_horizon=int(self.config.get("cpcv_label_horizon", 0)),
                embargo_pct=float(self.config.get("cpcv_embargo_pct", 0.0)),
            )
            try:
                cpcv_payload = CPCVBacktester(lambda: adapter, cpcv_config).run(
                    features, target
                ).to_dict()
            except (TypeError, ValueError) as exc:
                logger.warning("CPCV comparison skipped: %s", exc)
                if scheme == "cpcv":
                    return None

        if walk_forward_payload is None and cpcv_payload is None:
            return None

        result: Dict[str, Any] = {
            "validation_scheme": scheme,
            "walk_forward": walk_forward_payload,
            "cpcv": cpcv_payload,
        }
        # Walk-forward's fields stay at the top level when it ran, so existing
        # consumers are unaffected. A `cpcv`-only run deliberately omits them
        # rather than presenting CPCV numbers under a walk-forward key.
        if walk_forward_payload is not None:
            result.update(walk_forward_payload)
        return result

    def _train_epoch(self, dataloader: DataLoader) -> float:
        """Train for one epoch."""
        self.model.train()
        total_loss = 0.0

        for sequences, targets in dataloader:
            sequences = sequences.to(self.device)
            targets = targets.to(self.device)

            # Forward pass
            self.optimizer.zero_grad()
            with torch.amp.autocast('cuda', enabled=self.use_amp):
                outputs = self.model(sequences)

                # Compute loss
                loss = self.criterion(outputs, targets)

            # Backward pass (GradScaler is a no-op when AMP is inactive)
            self.scaler.scale(loss).backward()
            self.scaler.unscale_(self.optimizer)
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
            self.scaler.step(self.optimizer)
            self.scaler.update()

            total_loss += loss.item()

        return total_loss / len(dataloader)

    def _validate(self, dataloader: DataLoader) -> float:
        """Validate model.

        An empty loader is a hard error: the previous code divided by
        ``len(dataloader)`` (a ZeroDivisionError), and the multi-scale twin
        returned 0.0, which froze model selection at the first checkpoint.
        """
        if len(dataloader) == 0:
            raise ValueError(
                "Validation dataloader is empty; refusing to report a loss "
                "that would make model selection meaningless"
            )
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


def default_training_windows(
    date_min: Any,
    date_max: Any,
    train_fraction: float = 0.8,
) -> Tuple[Any, Any, Any]:
    """Derive chronological train/test window boundaries from the payload's own range.

    Returns ``(train_start, train_end, test_end)`` as pandas Timestamps. The
    test window is the strictly-later remainder of the observed span: rows with
    ``date <= train_end`` train, rows with ``date > train_end`` test, so the
    boundary day cannot appear in both.

    This replaces the previous hardcoded defaults (2023-01-01..2024-12-31),
    which silently discarded live data outside a fixed historical window --
    including the most recent observations, the ones a monitoring product
    exists to score.
    """
    import pandas as pd

    dmin = pd.to_datetime(date_min)
    dmax = pd.to_datetime(date_max)
    if pd.isna(dmin) or pd.isna(dmax):
        raise ValueError("Cannot derive training windows from an empty or unparsable date range")
    if dmax <= dmin:
        raise ValueError(
            f"Payload date range is degenerate (min={dmin}, max={dmax}); "
            "cannot derive chronological training windows"
        )
    if not 0.0 < train_fraction < 1.0:
        raise ValueError(f"train_fraction must be in (0, 1), got {train_fraction}")
    train_end = dmin + (dmax - dmin) * train_fraction
    return dmin, train_end, dmax


def split_train_val_by_date(
    df: "pd.DataFrame",
    date_col: str,
    val_fraction: float = 0.2,
) -> Tuple["pd.DataFrame", "pd.DataFrame", Any]:
    """Split a training frame into (train, val) chronologically by date.

    The validation subset is the most recent ``val_fraction`` of the frame's
    own date span; every source keeps its temporal order, and no validation
    date precedes a training date. Returns ``(train_df, val_df, cutoff)``.

    This replaces a positional ``iloc`` 80/20 cut. On the source-major frames
    the collector produces, a positional cut splits by *source*, not by time:
    the validation set ends up holding sources the training set never saw,
    whose IDs are not in the training source map -- so the multi-scale
    dataset skips them, validation is empty, and model selection freezes at
    the epoch-0 checkpoint.
    """
    import pandas as pd

    if not 0.0 < val_fraction < 1.0:
        raise ValueError(f"val_fraction must be in (0, 1), got {val_fraction}")
    if date_col not in df.columns:
        raise ValueError(f"No column '{date_col}' to split on; columns are {sorted(df.columns)}")
    dates = pd.to_datetime(df[date_col], errors='coerce')
    dmin, dmax = dates.min(), dates.max()
    if pd.isna(dmin) or pd.isna(dmax):
        raise ValueError(f"Column '{date_col}' has no parsable dates; cannot split chronologically")
    if dmax <= dmin:
        raise ValueError(
            f"Training window spans a single timestamp ({dmin}); cannot hold out "
            "a chronological validation subset"
        )
    cutoff = dmin + (dmax - dmin) * (1.0 - val_fraction)
    train_part = df[dates <= cutoff]
    val_part = df[dates > cutoff]
    if train_part.empty or val_part.empty:
        raise ValueError(
            "Chronological split produced an empty side; the training window is "
            "too short for the requested validation fraction"
        )
    return train_part, val_part, cutoff


def train_ensemble(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
    output_dir: str,
    model_type: str,
    device: torch.device,
    config: Dict[str, Any],
) -> Tuple[TrainingMetrics, List[str]]:
    """Train ``ensemble_size`` independent members; member 0 stays ``best_model.pt``.

    Why a separate entry point instead of a loop inside :meth:`ModelTrainer.train`:
    the epistemic term in :mod:`backend.modules.engine.uncertainty` is the
    *disagreement between independently trained members*, and independence is
    the caller's contract to keep (the module's docstring says so explicitly).
    Fresh ``ModelTrainer`` instances under distinct torch seeds give each member
    its own weight initialisation and its own DataLoader shuffle order (both are
    drawn from the global RNG at construction/iteration time). Members sharing a
    seed would agree more than the truth warrants and the decomposition would
    understate model ignorance -- the wrong direction to be wrong in.

    Member 0 keeps the canonical ``best_model.pt`` name, so every existing
    consumer (prediction engine, reports, the training result record) works
    unchanged on an ensembled job; members 1..M-1 land beside it as
    ``ensemble_member_{k}.pt``, which is where
    :class:`~backend.modules.engine.prediction_engine.RealPredictionEngine`
    discovers them. The returned metrics are member 0's -- an ensemble does not
    yet have a combined evaluation, and reporting one member's numbers as "the"
    numbers is stated here rather than hidden.

    Returns:
        ``(metrics, member_paths)`` -- member 0's metrics and every member's
        checkpoint path in member order.
    """
    ensemble_size = max(1, int(config.get('ensemble_size', 1) or 1))
    base_seed = int(config.get('seed', 42) or 42)
    root = Path(output_dir)
    members_root = root / 'ensemble_members'
    member_paths: List[str] = []
    metrics: Optional[TrainingMetrics] = None

    for member_index in range(ensemble_size):
        # Each member trains in its own directory: train() writes
        # best_model.pt / predictions.csv / training_history.json into its
        # output_dir, and letting members share one directory would leave the
        # LAST member's artifacts under the canonical names -- a silent
        # provenance swap the result record would not mention.
        member_dir = members_root / str(member_index)
        member_dir.mkdir(parents=True, exist_ok=True)
        torch.manual_seed(base_seed + member_index)
        trainer = ModelTrainer(model_type=model_type, device=device, config=dict(config))
        member_metrics = trainer.train(
            train_df=train_df, val_df=val_df, test_df=test_df, output_dir=str(member_dir)
        )
        if member_index == 0:
            # Member 0 keeps the canonical names, so every existing consumer
            # (prediction engine, reports, the training result record) reads
            # an ensembled job's output exactly like a single-model job's.
            final_model = root / 'best_model.pt'
            final_predictions = root / 'predictions.csv'
            final_history = root / 'training_history.json'
            (member_dir / 'best_model.pt').replace(final_model)
            (member_dir / 'predictions.csv').replace(final_predictions)
            (member_dir / 'training_history.json').replace(final_history)
            metrics = replace(
                member_metrics,
                model_path=str(final_model),
                predictions_path=str(final_predictions),
            )
            member_paths.append(str(final_model))
        else:
            destination = root / f'ensemble_member_{member_index}.pt'
            (member_dir / 'best_model.pt').replace(destination)
            member_paths.append(str(destination))
        logger.info(
            "Ensemble member %d/%d trained (seed %d) -> %s",
            member_index + 1, ensemble_size, base_seed + member_index, member_paths[-1],
        )

    shutil.rmtree(members_root, ignore_errors=True)

    if metrics is None:  # pragma: no cover - ensemble_size >= 1 guarantees a member
        raise RuntimeError("train_ensemble produced no members")
    return metrics, member_paths
