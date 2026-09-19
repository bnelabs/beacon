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

#: Opt-in for scoring with randomly initialized weights. Mirrors the
#: ``BEACON_ALLOW_UNSAFE_CHECKPOINT_LOAD`` pattern in ``model_io``: the default
#: is fail-closed, and the override exists for smoke tests, not production.
UNTRAINED_FALLBACK_ENV_VAR = "BEACON_ALLOW_UNTRAINED_FALLBACK"
_TRUTHY = {"1", "true", "yes", "on"}


def _untrained_fallback_allowed() -> bool:
    """Whether the environment explicitly permits the untrained fallback model."""
    return os.getenv(UNTRAINED_FALLBACK_ENV_VAR, "").strip().lower() in _TRUTHY


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

    #: What ``overall_score`` actually measures, stated explicitly. The model
    #: emits standardized one-step-ahead indicator predictions, which are not
    #: a calibrated risk scale; until calibration exists, ``risk_level`` is
    #: ``"uncalibrated"`` and this field carries the units and provenance so
    #: no consumer has to guess. See README.md §Scoring and validation.
    score_semantics: Dict[str, Any] = field(default_factory=dict)


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

        if not _untrained_fallback_allowed():
            # Fail closed. A randomly initialized network does not produce a
            # "lightweight fallback" risk score; it produces noise, and the
            # reporting layer downstream cannot tell the two apart. This is the
            # same category as the synthetic data the DATA stage refuses to
            # fabricate: an invented number presented as a measurement.
            raise PredictionBlockedError(
                "No trained checkpoint found; refusing to score with randomly "
                "initialized weights. Train a model first (run_training) and "
                "point the pipeline at its output directory, or -- for smoke "
                f"tests only -- set {UNTRAINED_FALLBACK_ENV_VAR}=1 to accept "
                "that the resulting scores are noise.",
                context={
                    "job_id": self.job_id,
                    "searched_paths": candidate_paths,
                },
            )

        logger.warning(
            "[%s] SECURITY: trained model not found in %s and %s is set, so "
            "scoring proceeds with an UNTRAINED fallback model. Its outputs are "
            "noise, not measurements, and must not be used for decisions.",
            self.job_id, base_path, UNTRAINED_FALLBACK_ENV_VAR,
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
        """Score per-source rolling windows with the loaded model.

        Three properties the previous implementation lacked, each of which
        decides whether the scores mean anything:

        * **Windows never straddle sources.** The payload is a long-format
          concatenation; treating it as one series gave every source boundary
          a window mixing two unrelated indicators -- the exact artefact
          ``backtesting.py``'s seam logic exists to prevent.
        * **Per-source normalization with the checkpoint's training stats.**
          The model was trained on standardized windows; feeding raw-scale
          values (Nikkei at ~38,000 next to a basis at ~0.01) produced outputs
          divorced from anything the model learned. When a source has no
          checkpoint stats, the payload's own observed stats are used and the
          substitution is recorded, because that normalization sees the
          evaluated window and makes the scores optimistic.
        * **Real source IDs.** The source embedding the model was trained with
          is passed per window instead of a constant 0.

        Returns raw model scores in the training-standardized space, plus the
        per-score source and window-end position so downstream alignment is
        explicit. No companion channels are manufactured.
        """
        import numpy as np
        import pandas as pd

        df = data["timeseries"]

        if 'value' in df.columns:
            value_col = 'value'
        elif 'Value' in df.columns:
            value_col = 'Value'
        else:
            raise ValueError("Timeseries data must contain 'value' or 'Value' column")

        source_col = next(
            (candidate for candidate in ('source_code', 'source') if candidate in df.columns),
            None,
        )
        group_col = 'series_id' if 'series_id' in df.columns else source_col

        date_col = None
        for candidate in ('date', 'Date'):
            if candidate in df.columns:
                date_col = candidate
                break

        sequence_length = max(2, int(self.sequence_length))

        if group_col is None:
            groups = [("__single__", df)]
        else:
            groups = list(df.groupby(group_col, sort=True))

        scores_parts = []
        timestamp_parts = []
        source_parts = []
        series_parts = []
        endpos_parts = []
        stats_provenance: Dict[str, str] = {}
        dropped_for_history = 0

        for raw_series, group in groups:
            source = (
                str(group[source_col].iloc[0])
                if source_col is not None and not group.empty
                else str(raw_series)
            )
            series = str(raw_series)
            ordered = (
                group.sort_values(date_col)
                if date_col is not None and date_col in group.columns
                else group
            )
            raw = pd.to_numeric(ordered[value_col], errors='coerce').to_numpy(dtype=float)
            finite = raw[np.isfinite(raw)]
            if finite.size == 0:
                logger.warning(
                    "[%s] Series %s (source %s) has no numeric values; skipped",
                    self.job_id,
                    series,
                    source,
                )
                continue

            checkpoint_stats = (self.source_stats or {}).get(source)
            if checkpoint_stats:
                stats_provenance[source] = "checkpoint"
                mean = float(checkpoint_stats.get('mean', 0.0))
                std = float(checkpoint_stats.get('std', 1.0))
            else:
                stats_provenance[source] = "payload"
                mean = float(finite.mean())
                std = float(finite.std())
            if not np.isfinite(std) or std == 0.0:
                std = 1.0

            # Gaps are imputed at the standardised mean, never carried forward.
            normalized = (raw - mean) / std
            normalized = np.where(np.isfinite(normalized), normalized, 0.0)

            if normalized.size <= sequence_length:
                dropped_for_history += int(normalized.size)
                logger.warning(
                    "[%s] Series %s (source %s) has %d row(s), too few for a %d-step window; skipped",
                    self.job_id, series, source, normalized.size, sequence_length,
                )
                continue

            windows = np.lib.stride_tricks.sliding_window_view(normalized, sequence_length)

            if self.source_to_id and source in self.source_to_id:
                source_id = int(self.source_to_id[source])
            else:
                if self.source_to_id:
                    logger.warning(
                        "[%s] Source %r was not seen during training - defaulting to source id 0",
                        self.job_id, source,
                    )
                source_id = 0

            batch_size = max(1, int(self.config.get('batch_size', 32)))
            chunk_scores = []
            model.eval()
            with torch.no_grad():
                for start in range(0, windows.shape[0], batch_size):
                    chunk = np.asarray(windows[start:start + batch_size], dtype=np.float32)
                    inputs = torch.FloatTensor(chunk).to(self.device)
                    source_ids = torch.full(
                        (chunk.shape[0], 1), source_id, dtype=torch.long, device=self.device
                    )
                    # Two calling conventions exist: the multi-scale encoder
                    # takes (x, source_ids); the fallback predictor takes
                    # (batch, seq, dim).
                    try:
                        output = model(inputs, source_ids)
                    except TypeError:
                        output = model(inputs.unsqueeze(-1))
                    flat = output.detach().cpu().numpy().astype(float).reshape(chunk.shape[0], -1)
                    chunk_scores.append(flat[:, 0])

            scores = np.concatenate(chunk_scores)
            ends = np.arange(sequence_length - 1, normalized.size)
            if date_col is not None and date_col in ordered.columns:
                window_timestamps = np.asarray(ordered[date_col])[ends]
            else:
                window_timestamps = ends

            scores_parts.append(scores)
            timestamp_parts.append(window_timestamps)
            source_parts.append(np.full(scores.size, source, dtype=object))
            series_parts.append(np.full(scores.size, series, dtype=object))
            endpos_parts.append(ends)

        if not scores_parts:
            # Too little history anywhere in the payload. Return no scores;
            # `_compute_risk_scores` refuses to aggregate an empty array
            # rather than rescaling the raw series into a fake score vector.
            return {
                "timestamps": [],
                "scores": np.asarray([], dtype=float),
                "sources": np.asarray([], dtype=object),
                "series_ids": np.asarray([], dtype=object),
                "score_end_positions": np.asarray([], dtype=int),
                "insufficient_history": True,
                "stats_provenance": stats_provenance,
                "n_dropped_for_history": int(dropped_for_history),
            }

        optimistic = sorted(s for s, origin in stats_provenance.items() if origin == "payload")
        if optimistic:
            logger.warning(
                "[%s] Normalisation for %s came from the evaluated payload rather "
                "than the checkpoint, so scores for those sources are optimistic: "
                "the normalisation saw the window being scored",
                self.job_id, optimistic,
            )

        return {
            "timestamps": np.concatenate(timestamp_parts),
            "scores": np.concatenate(scores_parts),
            "sources": np.concatenate(source_parts),
            "series_ids": np.concatenate(series_parts),
            "score_end_positions": np.concatenate(endpos_parts),
            "insufficient_history": False,
            "stats_provenance": stats_provenance,
            "n_dropped_for_history": int(dropped_for_history),
        }

    def _compute_risk_scores(self, predictions, data) -> RiskScores:
        """Aggregate the model's scores and attach real measurements.

        No risk channel is synthesised here, and no risk LEVEL is invented.
        The model's output is a one-step-ahead prediction of each indicator's
        *standardized next value*: it is unbounded, can be negative, and its
        sign meaning depends on the indicator. It is not a probability and not
        a 0-100 quantity, so the previous version -- which thresholded the raw
        mean at 30/60/80 and banded it low/medium/high/critical -- compared a
        standardized regression output against a percentage scale. Until a
        calibrated mapping from model output to risk exists (see
        README.md, Scoring and validation), the honest risk level is
        "uncalibrated" and the score is reported in the model's own units with
        its semantics attached.
        """
        import numpy as np

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

        return RiskScores(
            model_score={
                "overall": overall,
                "current": float(scores[-1]),
                "n_windows": int(scores.size),
            },
            overall_score=overall,
            risk_level="uncalibrated",
            # Empty: no interbank liability network reaches the engine, and a
            # network property cannot be inferred from one institution's series.
            systemic_risk={},
            operational_risk={
                "process_risk": float(100 - data_quality),
                "data_quality_score": float(data_quality),
            },
            score_semantics={
                "units": (
                    "standardized one-step-ahead indicator prediction "
                    "(train-split normalisation); unbounded, signed, not a probability"
                ),
                "calibrated": False,
                "risk_level_note": (
                    "no calibrated mapping from model output to a risk level exists; "
                    "risk_level is reported as 'uncalibrated' rather than banded "
                    "(README.md, Scoring and validation)"
                ),
                "stats_provenance": dict(predictions.get("stats_provenance") or {}),
            },
        )

    def _evaluate(self, predictions, data) -> Dict[str, float]:
        """Evaluate model performance against available ground truth.

        A score produced by the window ending at within-source position ``t``
        predicts position ``t + 1`` (that is the training target convention),
        so alignment against a ground-truth column shifts by one row *within
        the same source*. The previous version compared the flat score array
        against the flat target column with no shift and no source awareness,
        which paired every prediction with the wrong row and differenced
        across source seams.

        Without a ground-truth column, only distributional statistics of the
        scores are reported. The former ``stability_score`` (``1/(1+std(diff))``)
        was removed: smoothness of an uncalibrated score is not evidence of
        prediction quality, and presenting it as a metric manufactured one.
        """
        import numpy as np
        import pandas as pd

        metrics: Dict[str, float] = {}
        df = data["timeseries"]

        pred_array = np.asarray(predictions.get("scores", []), dtype=float)
        source_array = np.asarray(predictions.get("sources", []), dtype=object)
        series_array = np.asarray(
            predictions.get("series_ids", predictions.get("sources", [])),
            dtype=object,
        )
        endpos_array = np.asarray(predictions.get("score_end_positions", []), dtype=int)

        target_col = None
        for candidate in ('actual_risk', 'target'):
            if candidate in df.columns:
                target_col = candidate
                break

        if target_col is not None and pred_array.size and source_array.size == pred_array.size:
            source_col = next(
                (candidate for candidate in ('source_code', 'source') if candidate in df.columns),
                None,
            )
            group_col = 'series_id' if 'series_id' in df.columns else source_col
            date_col = None
            for candidate in ('date', 'Date'):
                if candidate in df.columns:
                    date_col = candidate
                    break

            score_frame = pd.DataFrame({
                "source": source_array.astype(str),
                "series": series_array.astype(str),
                "end_pos": endpos_array,
                "score": pred_array,
            })
            # The prediction for the window ending at position t targets row
            # t+1 of the same source's date-ordered series.
            score_frame["target_pos"] = score_frame["end_pos"] + 1

            target_frames = []
            groups = (
                [("__single__", df)] if group_col is None
                else list(df.groupby(group_col, sort=True))
            )
            for raw_series, group in groups:
                ordered = (
                    group.sort_values(date_col)
                    if date_col is not None and date_col in group.columns
                    else group
                )
                values = pd.to_numeric(ordered[target_col], errors='coerce').to_numpy(dtype=float)
                if values.size < 2:
                    continue
                source = (
                    str(group[source_col].iloc[0])
                    if source_col is not None and not group.empty
                    else str(raw_series)
                )
                target_frames.append(pd.DataFrame({
                    "source": source,
                    "series": str(raw_series),
                    "target_pos": np.arange(1, values.size),
                    "actual": values[1:],
                }))

            if target_frames:
                merged = score_frame.merge(
                    pd.concat(target_frames, ignore_index=True),
                    on=["series", "target_pos"],
                    how="inner",
                )
                merged = merged[np.isfinite(merged["actual"]) & np.isfinite(merged["score"])]

                if not merged.empty:
                    actual = merged["actual"].to_numpy(dtype=float)
                    predicted = merged["score"].to_numpy(dtype=float)
                    mse = float(np.mean((actual - predicted) ** 2))
                    ss_res = float(np.sum((actual - predicted) ** 2))
                    ss_tot = float(np.sum((actual - np.mean(actual)) ** 2))
                    metrics = {
                        "mse": mse,
                        "mae": float(np.mean(np.abs(actual - predicted))),
                        "rmse": float(np.sqrt(mse)),
                        "r2": float(1 - (ss_res / (ss_tot + 1e-8))),
                        "n_aligned": int(actual.size),
                    }
                    return metrics

            metrics = {
                "note": (
                    "Ground-truth column present but no prediction aligned to a "
                    "finite target row within its source"
                ),
            }
            return metrics

        # No ground truth available - report score distribution only.
        if pred_array.size:
            metrics = {
                "prediction_mean": float(np.mean(pred_array)),
                "prediction_std": float(np.std(pred_array)),
                "prediction_min": float(np.min(pred_array)),
                "prediction_max": float(np.max(pred_array)),
                "note": "No ground truth available - showing prediction statistics",
            }
        return metrics

    def _save_predictions(self, predictions) -> str:
        """Save the per-window scores (with source and window-end) to parquet."""
        import numpy as np
        import pandas as pd

        path = f"{self.output_dir}/{self.job_id}/predictions.parquet"
        os.makedirs(os.path.dirname(path), exist_ok=True)

        array_keys = ("timestamps", "scores", "sources", "series_ids", "score_end_positions")
        columns = {
            key: np.asarray(
                predictions.get(
                    key,
                    predictions.get("sources", []) if key == "series_ids" else [],
                )
            )
            for key in array_keys
        }
        lengths = {key: value.size for key, value in columns.items()}
        if len(set(lengths.values())) > 1:
            raise ValueError(f"Prediction arrays disagree in length: {lengths}")
        df = pd.DataFrame(columns)
        df["insufficient_history"] = bool(predictions.get("insufficient_history", False))
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
