"""ENGINE Module Orchestrator - ML Processing and Risk Computation."""

import logging
import os
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
import torch
import torch.nn as nn

from backend.exceptions import DataQualityError, PredictionBlockedError
from backend.modules.data.orchestrator import DataPackage
from backend.modules.data.quality_gate import DataQualityGate, QualityAttestation
from backend.modules.engine.model_io import safe_torch_load

logger = logging.getLogger(__name__)


class SimpleRiskPredictor(nn.Module):
    """Fallback LSTM-based predictor for offline or test execution."""

    def __init__(self, input_dim: int = 1, hidden_dim: int = 64, num_layers: int = 1, dropout: float = 0.1) -> None:
        super().__init__()
        effective_layers = max(1, num_layers)
        effective_dropout = dropout if effective_layers > 1 else 0.0
        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_dim,
            num_layers=effective_layers,
            dropout=effective_dropout,
            batch_first=True,
        )
        self.head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:  # type: ignore[override]
        sequence_output, _ = self.lstm(x)
        last_hidden = sequence_output[:, -1, :]
        return self.head(last_hidden)


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
    """Risk scores the engine can actually produce.

    This dataclass previously exposed ``market_liquidity``, ``funding_liquidity``
    and ``systemic_risk`` as three independent measurements. They were not. The
    engine took one prediction array, rescaled it to 0-100, then returned it
    three times: ``funding_liquidity = risk_scores * 0.95`` (commented "correlated
    but slightly different") and ``systemic_risk = risk_scores * 1.05``
    ("slightly amplified"). ``_compute_risk_scores`` then blended them
    0.35/0.35/0.25 with an "operational risk" term weighted 0.05.

    Because all three inputs were affine functions of the same array, that blend
    collapsed to a single affine function of the model output. It carried no
    information the model score did not already carry, and the 0.95/1.05 factors
    had no economic meaning -- they were chosen so the three channels would look
    different.

    What exists is now named:

    * ``model_score`` -- the model's output, summarised per window.
    * ``systemic_risk`` -- populated only when a liability network was supplied
      and cleared by :mod:`backend.modules.risk.clearing`. Empty otherwise,
      because a network property cannot be derived from a single-institution
      time series.
    * ``operational_risk`` -- the DATA-stage quality verdict, a real measurement.

    The three legacy attribute names are retained as properties for the
    reporting layer, and map onto the above without inventing values.
    """

    model_score: Dict[str, float]
    overall_score: float
    risk_level: str

    systemic_risk: Dict[str, float] = field(default_factory=dict)
    operational_risk: Dict[str, float] = field(default_factory=dict)

    @property
    def market_liquidity(self) -> Dict[str, float]:
        """Legacy alias for :attr:`model_score`.

        Kept so the reporting layer keeps working. It is *not* a separate
        market-liquidity measurement -- the model emits a single liquidity-stress
        score and there is no second channel behind this name.
        """
        return self.model_score

    @property
    def funding_liquidity(self) -> Dict[str, float]:
        """Empty: no funding-specific measurement exists.

        Returns ``{}`` rather than a rescaled copy of the model score, so the
        reporting layer reports absence instead of echoing the same number under
        a second name.
        """
        return {}


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
        # "HGT" was the old default, but the multi-scale trainer never built a
        # graph model -- it silently substituted MultiScaleTemporalAttentionModel
        # while results still reported HGT. The default now names the model that
        # is actually trained.
        self.model_name = self.config.get("model", "temporal_attention")
        self.sequence_length = int(self.config.get("sequence_length", 30))
        self.sources: list = []
        self.source_to_id: Dict[str, int] = {}
        self.source_stats: Dict[str, Dict[str, float]] = {}

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
            self.start_time = datetime.now(timezone.utc)
            logger.info(f"[{self.job_id}] Starting ENGINE processing")
            
            # Validate data package. Certification is not a boolean flag to be
            # trusted from anywhere: the payload must also carry a DATA-stage
            # quality attestation, and that attestation must be verified.
            if not data_package.quality_report.fit_for_engine:
                raise DataQualityError(
                    "Data not certified for ENGINE processing",
                    context={
                        "job_id": self.job_id,
                        "data_job_id": getattr(data_package, "job_id", None),
                        "quality_score": getattr(
                            data_package.quality_report, "quality_score", None
                        ),
                    },
                )
            attestation = DataQualityGate.attestation_from_job_result(
                data_package.metadata or {},
                job_id=str(getattr(data_package, "job_id", self.job_id)),
            )
            if attestation is None:
                # Packages written before attestations existed carry only the
                # scalar fields; reconstruct an explicit legacy verdict instead of
                # trusting the fit_for_engine flag on its own.
                attestation = QualityAttestation.from_legacy_result(
                    {
                        "fit_for_engine": bool(data_package.quality_report.fit_for_engine),
                        "quality_score": data_package.quality_report.quality_score,
                        "completeness": data_package.quality_report.completeness,
                    },
                    job_id=str(getattr(data_package, "job_id", self.job_id)),
                )
            DataQualityGate.require(attestation)
            
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
            
            duration = (datetime.now(timezone.utc) - self.start_time).total_seconds()
            
            self.status = EngineStatus.COMPLETED
            self.progress = 100.0
            
            result = EngineResult(
                job_id=self.job_id,
                model_name=self.model_name,
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
                processed_at=datetime.now(timezone.utc),
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
        """Load the checkpoint the trainer persisted, else a fallback predictor.

        The previous implementation imported ``HeterogeneousGraphTransformer``
        and constructed it with ``input_dim``/``hidden_dim``/``output_dim``. Those
        are not that class's parameters -- it took ``num_node_types``,
        ``num_edge_types`` and ``hidden_channels`` -- so the call raised
        ``TypeError`` whenever a checkpoint actually existed. The branch had never
        run against a real checkpoint.

        Loading now mirrors what the trainer writes: a
        ``MultiScaleTemporalAttentionModel`` rebuilt from the checkpoint's own
        ``config``, ``sources``, ``source_stats`` and ``sequence_length``.
        """
        import os

        base_path = f"{self.output_dir}/{self.job_id}"
        candidate_paths = [
            os.path.join(base_path, "model.pt"),
            os.path.join(base_path, "best_model.pt")
        ]

        model_path = next((path for path in candidate_paths if os.path.exists(path)), None)

        if model_path:
            logger.info(f"[{self.job_id}] Loading trained model from {model_path}")
            checkpoint = safe_torch_load(model_path, map_location=self.device)
            config = checkpoint.get('config', self.config)

            from backend.modules.engine.multi_scale_trainer import (
                MultiScaleTemporalAttentionModel,
            )

            sources = checkpoint.get('sources', []) or []
            sequence_length = int(
                config.get('sequence_length', self.config.get('sequence_length', 30))
            )

            model = MultiScaleTemporalAttentionModel(
                num_sources=max(len(sources), 1),
                sequence_length=sequence_length,
                d_model=config.get('d_model', 128),
                nhead=config.get('nhead', 8),
                num_layers=config.get('num_layers', 3),
                dropout=config.get('dropout', 0.1),
            ).to(self.device)

            model.load_state_dict(checkpoint['model_state_dict'])
            model.eval()

            self.sequence_length = sequence_length
            self.sources = list(sources)
            self.source_to_id = {src: idx for idx, src in enumerate(self.sources)}
            self.source_stats = checkpoint.get('source_stats', {}) or {}
            self.model_name = config.get('model', self.model_name)
            logger.info(f"[{self.job_id}] Model loaded successfully")
            return model

        logger.warning(
            "[%s] Trained model not found in %s; using lightweight fallback model.",
            self.job_id,
            base_path,
        )
        hidden_dim = int(self.config.get('hidden_dim', 64))
        num_layers = int(self.config.get('num_layers', 1))
        dropout = float(self.config.get('dropout', 0.1))
        fallback = SimpleRiskPredictor(
            input_dim=int(self.config.get('input_dim', 1)),
            hidden_dim=hidden_dim,
            num_layers=num_layers,
            dropout=dropout,
        ).to(self.device)
        fallback.eval()
        self.model_name = "SimpleRiskPredictor"
        return fallback
    
    def _predict(self, model, data: Dict[str, Any]):
        """Score every rolling window with the loaded model.

        Returns the raw model scores. It deliberately does not manufacture
        companion channels: the previous version returned ``market_liquidity``,
        ``funding_liquidity`` and ``systemic_risk`` as one array multiplied by
        1.0, 0.95 and 1.05, presenting a single measurement as three.
        """
        import numpy as np
        import pandas as pd

        df = data["timeseries"]

        value_col = None
        if 'value' in df.columns:
            value_col = 'value'
        elif 'Value' in df.columns:
            value_col = 'Value'
        else:
            raise ValueError("Timeseries data must contain 'value' or 'Value' column")

        # Gaps are imputed at the observed mean, never carried forward. Forward
        # filling would write a pre-gap level into the post-gap period, so the
        # model would read a value that had not been published at that timestamp.
        raw = pd.to_numeric(df[value_col], errors='coerce').to_numpy(dtype=float)
        finite = raw[np.isfinite(raw)]
        if finite.size == 0:
            raise ValueError("Timeseries contains no numeric data")
        values = np.where(np.isfinite(raw), raw, float(finite.mean()))

        requested_sequence = int(self.config.get('sequence_length', self.sequence_length))
        sequence_length = max(2, min(requested_sequence, len(values) - 1))
        sequences = []
        timestamps = []

        date_col = 'date' if 'date' in df.columns else 'Date' if 'Date' in df.columns else None

        for i in range(len(values) - sequence_length):
            sequences.append(values[i:i + sequence_length])
            if date_col:
                timestamps.append(df.iloc[i + sequence_length][date_col])
            else:
                timestamps.append(i + sequence_length)

        if len(sequences) == 0:
            # Too short to form a single window. Report the observed series
            # rather than a rescaled copy of it.
            fallback_timestamps = list(df[date_col]) if date_col else list(range(len(values)))
            return {
                "timestamps": fallback_timestamps,
                "scores": np.asarray(values, dtype=float),
                "insufficient_history": True,
            }

        window_batch = np.asarray(sequences, dtype=np.float32)
        batch_size = int(self.config.get('batch_size', 32))
        scores = []

        model.eval()
        with torch.no_grad():
            for start in range(0, len(window_batch), batch_size):
                chunk = window_batch[start:start + batch_size]
                inputs = torch.FloatTensor(chunk).to(self.device)
                source_ids = torch.zeros(
                    (chunk.shape[0], 1), dtype=torch.long, device=self.device
                )
                # Two calling conventions exist: the multi-scale encoder takes
                # (x, source_ids); the fallback predictor takes (batch, seq, dim).
                try:
                    output = model(inputs, source_ids)
                except TypeError:
                    output = model(inputs.unsqueeze(-1))
                flat = output.detach().cpu().numpy().astype(float).reshape(chunk.shape[0], -1)
                scores.append(flat[:, 0])

        return {
            "timestamps": timestamps,
            "scores": np.concatenate(scores),
            "insufficient_history": False,
        }
    
    def _compute_risk_scores(self, predictions, data) -> RiskScores:
        """Aggregate the model's scores and attach real measurements.

        No risk channel is synthesised here. See :class:`RiskScores` for what the
        previous 0.95/1.05 rescaling and 0.35/0.35/0.25/0.05 blend were doing.
        """
        import numpy as np

        RISK_LEVEL_LOW = 30
        RISK_LEVEL_MEDIUM = 60
        RISK_LEVEL_HIGH = 80

        scores = np.asarray(predictions["scores"], dtype=float).reshape(-1)
        if scores.size == 0:
            raise PredictionBlockedError(
                "The model produced no scores to aggregate",
                context={"job_id": self.job_id},
            )

        overall = float(np.mean(scores))

        # Operational risk comes from the DATA stage's own verdict. Defaulting
        # this to a comfortable value would manufacture a risk number.
        data_quality = (data.get("metadata") or {}).get("quality_score")
        if data_quality is None:
            raise PredictionBlockedError(
                "Risk scoring requires the DATA-stage quality score, but the payload "
                "metadata carries none",
                context={"job_id": self.job_id, "metadata_keys": sorted((data.get("metadata") or {}))},
            )

        if overall < RISK_LEVEL_LOW:
            risk_level = "low"
        elif overall < RISK_LEVEL_MEDIUM:
            risk_level = "medium"
        elif overall < RISK_LEVEL_HIGH:
            risk_level = "high"
        else:
            risk_level = "critical"

        return RiskScores(
            model_score={
                "overall": overall,
                "current": float(scores[-1]),
                "n_windows": int(scores.size),
            },
            overall_score=overall,
            risk_level=risk_level,
            # Empty: no interbank liability network reaches the engine, and a
            # network property cannot be inferred from one institution's series.
            systemic_risk={},
            operational_risk={
                "process_risk": float(100 - data_quality),
                "data_quality_score": float(data_quality),
            },
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

            pred_array = np.asarray(predictions.get("scores", []), dtype=float)

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
            pred_array = np.asarray(predictions.get("scores", []), dtype=float)

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
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df = pd.DataFrame(predictions)
        df.to_parquet(path)
        return path
    
    def _save_explanations(self, model, predictions) -> Optional[str]:
        """Save score statistics.

        No attribution is produced here. The previous implementation looked for a
        ``get_attention_weights`` method the models never defined, so the branch
        never fired, and it reported the raw prediction array as "feature
        importance based on predictions" -- a statistic, not an attribution.
        """
        import pandas as pd
        import numpy as np
        import os

        try:
            explanations = {}

            if 'timestamps' in predictions:
                explanations['timestamps'] = predictions['timestamps']

            scores = np.asarray(predictions.get('scores', []), dtype=float)
            explanations['score_stats'] = {
                'mean': float(scores.mean()) if scores.size else None,
                'std': float(scores.std()) if scores.size else None,
                'min': float(scores.min()) if scores.size else None,
                'max': float(scores.max()) if scores.size else None,
            }
            # SubgraphX is implemented in modules/engine/subgraphx.py. What it
            # needs here is a network to explain and a game value over it -- for
            # BEACON, the clearing shortfall on the induced subnetwork. This job
            # result carries neither, so attribution is omitted rather than
            # approximated by a per-feature scalar, which is the object that was
            # deleted in the first place.
            explanations['attribution'] = (
                'not computed: SubgraphX requires a liability network and a game '
                'value function (see modules/engine/subgraphx.py); neither is '
                'carried on this result, and no approximate attribution is '
                'substituted'
            )

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
