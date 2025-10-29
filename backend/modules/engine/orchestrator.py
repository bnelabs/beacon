"""ENGINE Module Orchestrator - ML Processing and Risk Computation."""

import logging
from typing import Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
import torch
import pandas as pd
import numpy as np
from torch_geometric.data import Data
from modules.engine.gnn_model import GNNModel
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

            num_node_features = preprocessed["features"].shape[1]
            num_classes = 2  # Assuming binary classification (risk vs. no risk)
            model = self._get_model(num_node_features, num_classes)

            metrics = self._train_model(model, preprocessed)
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
            
            evaluation_metrics = self._evaluate(metrics, preprocessed)
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
                performance_metrics=evaluation_metrics,
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
    
    def _get_model(self, num_node_features, num_classes):
        """Load or train model."""
        return GNNModel(
            num_node_features=num_node_features,
            hidden_channels=self.config.get("hidden_channels", 64),
            num_classes=num_classes,
        ).to(self.device)

    def _train_model(self, model, data: Dict[str, Any]):
        """Train the model."""
        logger.info(f"[{self.job_id}] Training GNN model")

        optimizer = torch.optim.Adam(model.parameters(), lr=self.config.get("lr", 0.01))
        criterion = torch.nn.CrossEntropyLoss()

        # Create a realistic target variable
        vix_data = data["timeseries"][data["timeseries"]["asset"] == "VIX"]
        vix_data = vix_data.set_index("date")
        vix_data["risky"] = (vix_data["close"] > 20).astype(int)
        target = vix_data["risky"]

        # Align features with the target and get the labels
        features_df = data["features"].join(target, how="inner")
        labels = torch.tensor(features_df["risky"].values, dtype=torch.long).to(self.device)

        # Create a graph data object using only the features that have labels
        features = torch.tensor(features_df.drop(columns=["risky"]).values, dtype=torch.float).to(self.device)

        # Create edge index for a fully connected graph
        num_nodes = features.shape[0]
        edge_index = torch.combinations(torch.arange(num_nodes), r=2).t().contiguous()
        edge_index = edge_index.to(self.device)

        graph_data = Data(x=features, edge_index=edge_index, y=labels)

        model.train()
        for epoch in range(self.config.get("epochs", 10)):
            optimizer.zero_grad()
            out = model(graph_data)
            loss = criterion(out, graph_data.y)
            loss.backward()
            optimizer.step()
            logger.info(f"[{self.job_id}] Epoch {epoch+1}, Loss: {loss.item()}")

        return {"loss": loss.item()}

    def _predict(self, model, data: Dict[str, Any]):
        """Generate predictions."""
        logger.info(f"[{self.job_id}] Generating predictions")
        model.eval()

        features = torch.tensor(data["features"].values, dtype=torch.float).to(self.device)
        num_nodes = features.shape[0]
        edge_index = torch.combinations(torch.arange(num_nodes), r=2).t().contiguous()
        edge_index = edge_index.to(self.device)

        graph_data = Data(x=features, edge_index=edge_index)

        with torch.no_grad():
            out = model(graph_data)

        return torch.exp(out).cpu().numpy()

    def _compute_risk_scores(self, predictions, data) -> RiskScores:
        """Compute aggregated risk scores."""
        logger.info(f"[{self.job_id}] Computing enhanced risk scores")

        risk_probabilities = predictions[:, 1]

        # Enhanced Market Liquidity: based on volatility assets
        vix_related_assets = [c for c in data["features"].columns if "VIX" in c]
        market_liq_score = data["features"][vix_related_assets].mean(axis=1).mean() * 10

        # Enhanced Funding Liquidity: based on interest rate spreads
        interest_rate_spreads = [c for c in data["features"].columns if "spread" in c.lower()]
        funding_liq_score = data["features"][interest_rate_spreads].mean(axis=1).mean() * 10

        # Systemic Risk: based on graph properties and prediction variance
        systemic_risk_score = np.std(risk_probabilities) * 200

        # Operational Risk: simple placeholder based on prediction confidence
        operational_risk_score = (1 - np.mean(np.abs(risk_probabilities - 0.5))) * 100

        # Combine scores with weights
        overall = (market_liq_score * 0.3) + (funding_liq_score * 0.3) + (systemic_risk_score * 0.4)
        overall = np.clip(overall, 0, 100)

        if overall < 30:
            risk_level = "low"
        elif overall < 60:
            risk_level = "medium"
        elif overall < 80:
            risk_level = "high"
        else:
            risk_level = "critical"

        return RiskScores(
            market_liquidity={"score": market_liq_score},
            funding_liquidity={"score": funding_liq_score},
            systemic_risk={"score": systemic_risk_score},
            operational_risk={"score": operational_risk_score},
            overall_score=overall,
            risk_level=risk_level
        )
    
    def _evaluate(self, metrics, data) -> Dict[str, float]:
        """Evaluate model performance."""
        # In a real scenario, you would have a more sophisticated evaluation
        return metrics

    def _save_predictions(self, predictions) -> str:
        """Save predictions to file."""
        path = f"{self.output_dir}/{self.job_id}/predictions.parquet"
        pd.DataFrame(predictions, columns=["no_risk_prob", "risk_prob"]).to_parquet(path)
        return path

    def _save_explanations(self, model, predictions) -> Optional[str]:
        """Save model explanations."""
        # For a baseline model, we can save the model itself
        import pickle
        path = f"{self.output_dir}/{self.job_id}/model.pkl"
        with open(path, "wb") as f:
            pickle.dump(model, f)
        return path
    
    def _get_peak_memory(self) -> float:
        """Get peak memory usage."""
        if torch.cuda.is_available():
            return torch.cuda.max_memory_allocated() / 1024**2
        return 0.0
