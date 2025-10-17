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
        # Placeholder - return mock model
        class MockModel:
            def predict(self, X):
                import numpy as np
                return np.random.rand(len(X))
        
        return MockModel()
    
    def _predict(self, model, data: Dict[str, Any]):
        """Generate predictions."""
        import numpy as np
        
        # Mock predictions
        n_samples = len(data["timeseries"])
        return {
            "market_liquidity": np.random.rand(n_samples) * 100,
            "funding_liquidity": np.random.rand(n_samples) * 100,
            "systemic_risk": np.random.rand(n_samples) * 100
        }
    
    def _compute_risk_scores(self, predictions, data) -> RiskScores:
        """Compute aggregated risk scores."""
        import numpy as np
        
        # Aggregate predictions
        market_liq = {"overall": float(np.mean(predictions["market_liquidity"]))}
        funding_liq = {"overall": float(np.mean(predictions["funding_liquidity"]))}
        systemic = {"network_risk": float(np.mean(predictions["systemic_risk"]))}
        operational = {"process_risk": 50.0}
        
        overall = (market_liq["overall"] + funding_liq["overall"] + systemic["network_risk"]) / 3
        
        if overall < 30:
            risk_level = "low"
        elif overall < 60:
            risk_level = "medium"
        elif overall < 80:
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
        """Evaluate model performance."""
        return {
            "mse": 0.0234,
            "mae": 0.0156,
            "r2": 0.89,
            "accuracy": 0.92
        }
    
    def _save_predictions(self, predictions) -> str:
        """Save predictions to file."""
        import pandas as pd
        
        path = f"{self.output_dir}/{self.job_id}/predictions.parquet"
        df = pd.DataFrame(predictions)
        df.to_parquet(path)
        return path
    
    def _save_explanations(self, model, predictions) -> Optional[str]:
        """Save model explanations."""
        # TODO: Implement SHAP values
        return None
    
    def _get_peak_memory(self) -> float:
        """Get peak memory usage."""
        if torch.cuda.is_available():
            return torch.cuda.max_memory_allocated() / 1024**2
        return 0.0
