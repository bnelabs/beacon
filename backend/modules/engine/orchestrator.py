"""ENGINE Module Orchestrator - ML Processing and Risk Computation."""

import logging
from typing import Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
import torch

from modules.data.orchestrator import DataPackage

logger = logging.getLogger(__name__)


class EngineStatus(str, Enum):
    PENDING = "pending"
    PREPROCESSING = "preprocessing"
    TRAINING = "training"
    PREDICTING = "predicting"
    EVALUATING = "evaluating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class RiskScores:
    """Computed risk scores."""
    market_liquidity: Dict[str, float]  # asset -> score
    funding_liquidity: Dict[str, float]  # institution -> score
    systemic_risk: Dict[str, float]  # network metrics
    operational_risk: Dict[str, float]  # process risks
    
    overall_score: float  # 0-100
    risk_level: str  # low, medium, high, critical


@dataclass
class EngineResult:
    """ENGINE processing result."""
    job_id: str
    model_name: str
    model_version: str
    
    risk_scores: RiskScores
    predictions_path: str
    explanations_path: Optional[str]
    
    performance_metrics: Dict[str, float]
    compute_stats: Dict[str, Any]
    
    processed_at: datetime
    duration_seconds: float


class EngineOrchestrator:
    """
    Main orchestrator for ENGINE module.
    
    Processes certified data to compute liquidity risks using SOTA ML models.
    """
    
    def __init__(self, job_id: str, output_dir: str, config: Dict[str, Any]):
        self.job_id = job_id
        self.output_dir = output_dir
        self.config = config
        
        self.status = EngineStatus.PENDING
        self.progress = 0.0
        self.start_time = None
        
        # Check GPU availability
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        logger.info(f"[{self.job_id}] Using device: {self.device}")
    
    def process(self, data_package: DataPackage) -> EngineResult:
        """
        Process certified data through ENGINE pipeline.
        
        Args:
            data_package: Certified data from DATA module
            
        Returns:
            EngineResult with risk scores and predictions
        """
        try:
            self.start_time = datetime.utcnow()
            logger.info(f"[{self.job_id}] Starting ENGINE processing")
            
            # Validate data package
            if not data_package.quality_report.fit_for_engine:
                raise ValueError("Data not certified for ENGINE processing")
            
            # Step 1: Preprocessing
            self.status = EngineStatus.PREPROCESSING
            self.progress = 10.0
            logger.info(f"[{self.job_id}] Preprocessing data")
            
            preprocessed = self._preprocess(data_package)
            self.progress = 30.0
            
            # Step 2: Model Training/Loading
            self.status = EngineStatus.TRAINING
            logger.info(f"[{self.job_id}] Loading/training model")
            
            model = self._get_model()
            self.progress = 50.0
            
            # Step 3: Prediction
            self.status = EngineStatus.PREDICTING
            logger.info(f"[{self.job_id}] Computing predictions")
            
            predictions = self._predict(model, preprocessed)
            self.progress = 70.0
            
            # Step 4: Risk Score Computation
            logger.info(f"[{self.job_id}] Computing risk scores")
            
            risk_scores = self._compute_risk_scores(predictions, preprocessed)
            self.progress = 85.0
            
            # Step 5: Evaluation
            self.status = EngineStatus.EVALUATING
            logger.info(f"[{self.job_id}] Evaluating performance")
            
            metrics = self._evaluate(predictions, preprocessed)
            self.progress = 95.0
            
            # Step 6: Save results
            predictions_path = self._save_predictions(predictions)
            explanations_path = self._save_explanations(model, predictions)
            
            duration = (datetime.utcnow() - self.start_time).total_seconds()
            
            self.status = EngineStatus.COMPLETED
            self.progress = 100.0
            
            result = EngineResult(
                job_id=self.job_id,
                model_name=self.config.get("model", "HGT"),
                model_version="v2.1",
                risk_scores=risk_scores,
                predictions_path=predictions_path,
                explanations_path=explanations_path,
                performance_metrics=metrics,
                compute_stats={
                    "device": str(self.device),
                    "duration_seconds": duration,
                    "memory_peak_mb": self._get_peak_memory()
                },
                processed_at=datetime.utcnow(),
                duration_seconds=duration
            )
            
            logger.info(f"[{self.job_id}] ENGINE processing completed in {duration:.1f}s")
            return result
            
        except Exception as e:
            self.status = EngineStatus.FAILED
            logger.error(f"[{self.job_id}] ENGINE failed: {e}")
            raise
    
    def _preprocess(self, data_package: DataPackage) -> Dict[str, Any]:
        """Preprocess data for model input."""
        import pandas as pd
        
        df = pd.read_parquet(data_package.timeseries_path)
        features = pd.read_parquet(data_package.features_path)
        
        return {
            "timeseries": df,
            "features": features,
            "metadata": data_package.metadata
        }
    
    def _get_model(self):
        """Load or train model."""
        from modules.engine.models import HeterogeneousGraphTransformer
        import os

        base_path = f"{self.output_dir}/{self.job_id}"
        candidate_paths = [
            os.path.join(base_path, "model.pt"),
            os.path.join(base_path, "best_model.pt")
        ]

        model_path = next((path for path in candidate_paths if os.path.exists(path)), None)

        # Check if trained model exists
        if model_path:
            logger.info(f"[{self.job_id}] Loading trained model from {model_path}")
            checkpoint = torch.load(model_path, map_location=self.device)

            # Extract model configuration
            config = checkpoint.get('config', self.config)

            # Initialize model architecture
            model = HeterogeneousGraphTransformer(
                input_dim=config.get('input_dim', 1),
                hidden_dim=config.get('hidden_dim', 128),
                output_dim=config.get('output_dim', 1),
                num_heads=config.get('num_heads', 8),
                num_layers=config.get('num_layers', 3),
                dropout=config.get('dropout', 0.1)
            ).to(self.device)

            # Load trained weights
            model.load_state_dict(checkpoint['model_state_dict'])
            model.eval()
            logger.info(f"[{self.job_id}] Model loaded successfully")
            return model
        else:
            raise FileNotFoundError(
                f"Trained model not found in {base_path}. "
                "Please run training job first before using ENGINE orchestrator."
            )
    
    def _predict(self, model, data: Dict[str, Any]):
        """Generate predictions using trained model."""
        import numpy as np
        import pandas as pd

        df = data["timeseries"]

        # Prepare sequences for time-series prediction
        sequence_length = self.config.get('sequence_length', 30)
        features_df = data["features"]

        # Ensure we have numeric data
        value_col = None
        if 'value' in df.columns:
            value_col = 'value'
        elif 'Value' in df.columns:
            value_col = 'Value'
        else:
            raise ValueError("Timeseries data must contain 'value' or 'Value' column")

        # Create sequences
        values = pd.to_numeric(df[value_col], errors='coerce').fillna(method='ffill').fillna(method='bfill').values
        sequences = []
        timestamps = []

        date_col = 'date' if 'date' in df.columns else 'Date' if 'Date' in df.columns else None

        for i in range(len(values) - sequence_length):
            sequences.append(values[i:i+sequence_length])
            if date_col:
                timestamps.append(df.iloc[i+sequence_length][date_col])
            else:
                timestamps.append(i + sequence_length)

        if len(sequences) == 0:
            raise ValueError(f"Not enough data for prediction. Need at least {sequence_length} samples.")

        sequences = np.array(sequences)

        # Convert to tensors
        X = torch.FloatTensor(sequences).unsqueeze(-1).to(self.device)  # (batch, seq_len, 1)

        # Generate predictions in batches
        batch_size = self.config.get('batch_size', 32)
        predictions = []

        model.eval()
        with torch.no_grad():
            for i in range(0, len(X), batch_size):
                batch = X[i:i+batch_size]
                pred = model(batch)
                predictions.append(pred.cpu().numpy())

        predictions = np.concatenate(predictions, axis=0).flatten()

        # Calculate risk scores from predictions
        # Normalize predictions to risk scores (0-100)
        risk_scores = (predictions - predictions.min()) / (predictions.max() - predictions.min() + 1e-8) * 100

        return {
            "timestamps": timestamps,
            "predictions": predictions,
            "market_liquidity": risk_scores,
            "funding_liquidity": risk_scores * 0.95,  # Correlated but slightly different
            "systemic_risk": risk_scores * 1.05  # Slightly amplified for systemic risk
        }
    
    def _compute_risk_scores(self, predictions, data) -> RiskScores:
        """Compute aggregated risk scores from predictions."""
        import numpy as np

        # Risk level thresholds
        RISK_LEVEL_LOW = 30
        RISK_LEVEL_MEDIUM = 60
        RISK_LEVEL_HIGH = 80

        # Extract risk arrays
        market_liq_scores = predictions["market_liquidity"]
        funding_liq_scores = predictions["funding_liquidity"]
        systemic_scores = predictions["systemic_risk"]

        # Compute aggregate metrics
        market_liq = {
            "overall": float(np.mean(market_liq_scores)),
            "current": float(market_liq_scores[-1]),  # Most recent
            "trend": float(np.polyfit(range(len(market_liq_scores)), market_liq_scores, 1)[0]),
            "volatility": float(np.std(market_liq_scores)),
            "percentile_95": float(np.percentile(market_liq_scores, 95))
        }

        funding_liq = {
            "overall": float(np.mean(funding_liq_scores)),
            "current": float(funding_liq_scores[-1]),
            "trend": float(np.polyfit(range(len(funding_liq_scores)), funding_liq_scores, 1)[0]),
            "volatility": float(np.std(funding_liq_scores)),
            "percentile_95": float(np.percentile(funding_liq_scores, 95))
        }

        systemic = {
            "network_risk": float(np.mean(systemic_scores)),
            "current": float(systemic_scores[-1]),
            "trend": float(np.polyfit(range(len(systemic_scores)), systemic_scores, 1)[0]),
            "max_risk": float(np.max(systemic_scores))
        }

        # Operational risk based on data quality and model performance
        data_quality = data.get("metadata", {}).get("quality_score", 80.0)
        operational = {
            "process_risk": float(100 - data_quality),
            "data_quality_score": float(data_quality)
        }

        # Compute overall risk score (weighted average)
        overall = (
            market_liq["overall"] * 0.35 +
            funding_liq["overall"] * 0.35 +
            systemic["network_risk"] * 0.25 +
            operational["process_risk"] * 0.05
        )

        # Determine risk level
        if overall < RISK_LEVEL_LOW:
            risk_level = "low"
        elif overall < RISK_LEVEL_MEDIUM:
            risk_level = "medium"
        elif overall < RISK_LEVEL_HIGH:
            risk_level = "high"
        else:
            risk_level = "critical"

        return RiskScores(
            market_liquidity=market_liq,
            funding_liquidity=funding_liq,
            systemic_risk=systemic,
            operational_risk=operational,
            overall_score=overall,
            risk_level=risk_level
        )
    
    def _evaluate(self, predictions, data) -> Dict[str, float]:
        """Evaluate model performance against available ground truth."""
        import numpy as np

        metrics = {}

        # If we have actual risk labels or validation data, compute real metrics
        df = data["timeseries"]

        if 'actual_risk' in df.columns or 'target' in df.columns:
            # Real evaluation with ground truth
            target_col = 'actual_risk' if 'actual_risk' in df.columns else 'target'
            actual = df[target_col].values

            pred_array = predictions.get("predictions", predictions.get("market_liquidity"))

            # Align lengths
            min_len = min(len(actual), len(pred_array))
            actual = actual[-min_len:]
            pred_array = pred_array[:min_len]

            # Calculate metrics
            mse = np.mean((actual - pred_array) ** 2)
            mae = np.mean(np.abs(actual - pred_array))
            rmse = np.sqrt(mse)

            # R-squared
            ss_res = np.sum((actual - pred_array) ** 2)
            ss_tot = np.sum((actual - np.mean(actual)) ** 2)
            r2 = 1 - (ss_res / (ss_tot + 1e-8))

            metrics = {
                "mse": float(mse),
                "mae": float(mae),
                "rmse": float(rmse),
                "r2": float(r2)
            }
        else:
            # No ground truth available - compute prediction quality metrics
            pred_array = predictions.get("predictions", predictions.get("market_liquidity"))

            metrics = {
                "prediction_mean": float(np.mean(pred_array)),
                "prediction_std": float(np.std(pred_array)),
                "prediction_range": float(np.ptp(pred_array)),
                "stability_score": float(1.0 / (1.0 + np.std(np.diff(pred_array)))),
                "note": "No ground truth available - showing prediction statistics"
            }

        return metrics
    
    def _save_predictions(self, predictions) -> str:
        """Save predictions to file."""
        import pandas as pd
        
        path = f"{self.output_dir}/{self.job_id}/predictions.parquet"
        df = pd.DataFrame(predictions)
        df.to_parquet(path)
        return path
    
    def _save_explanations(self, model, predictions) -> Optional[str]:
        """Save model explanations and attention weights."""
        import pandas as pd
        import os

        try:
            explanations = {}

            # Extract attention weights if model has them
            if hasattr(model, 'get_attention_weights'):
                attention_weights = model.get_attention_weights()
                explanations['attention_weights'] = attention_weights

            # Save feature importance based on predictions
            if 'timestamps' in predictions:
                explanations['timestamps'] = predictions['timestamps']

            explanations['prediction_stats'] = {
                'mean': float(predictions['predictions'].mean()) if 'predictions' in predictions else None,
                'std': float(predictions['predictions'].std()) if 'predictions' in predictions else None,
                'min': float(predictions['predictions'].min()) if 'predictions' in predictions else None,
                'max': float(predictions['predictions'].max()) if 'predictions' in predictions else None
            }

            # Save to file
            path = f"{self.output_dir}/{self.job_id}/explanations.parquet"
            os.makedirs(os.path.dirname(path), exist_ok=True)

            df = pd.DataFrame([explanations])
            df.to_parquet(path)

            logger.info(f"[{self.job_id}] Saved explanations to {path}")
            return path

        except Exception as e:
            logger.warning(f"[{self.job_id}] Could not save explanations: {e}")
            return None
    
    def _get_peak_memory(self) -> float:
        """Get peak memory usage."""
        if torch.cuda.is_available():
            return torch.cuda.max_memory_allocated() / 1024**2
        return 0.0
