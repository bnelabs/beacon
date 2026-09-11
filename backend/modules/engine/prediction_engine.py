"""Prediction engine: model inference, risk series, and systemic analysis.

On explainability
-----------------

This module previously advertised "EU AI Act compliant explainability" while
delegating to a hand-rolled attribution routine that computed
``gradient * input * attention``, normalised it to sum to one, and presented the
result as SHAP values. It did not satisfy EU AI Act expectations and was not
SHAP:

* The attention term was fake. When the model had no ``transformer`` attribute
  the helper returned ``None``; when it did, it returned *uniform* weights
  (``np.ones(seq_len) / seq_len``). The "attention-weighted attribution" was
  therefore gradient attribution multiplied by a constant, which changes nothing
  about the ranking while implying a mechanism that was never read.
* ``gradient * input`` is a local linear surrogate. It is not a Shapley value:
  it carries no efficiency, symmetry, dummy or additivity guarantee, and it
  misattributes features whose effect on the output is non-monotone. The module
  docstring of the removed explainer claimed it worked "without black boxes"
  while producing attributions that are themselves unverifiable.
* The reported "confidence intervals" came from MC-dropout over a network whose
  dropout was switched on by calling ``model.train()`` on a model that had been
  loaded for inference -- so the intervals described a different network from
  the one that produced the prediction.

Local attribution is now provided by SubgraphX
(:mod:`backend.modules.engine.subgraphx`), which returns a connected subgraph with
a defined game-theoretic objective rather than a per-feature scalar. Applying it
requires a network and a value function over that network, which this engine's
payload does not carry, so ``feature_importances`` remains empty here rather than
being filled with something unverifiable.

Uncertainty intervals are likewise reported as unavailable until conformal
calibration is in place; the confidence fields are ``None`` and
``confidence_method`` records why.
"""

import torch
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import logging
from pathlib import Path
import json

from backend.exceptions import SchemaValidationError
from backend.modules.data.quality_gate import (
    UNVERIFIED_OVERRIDE_ENV,
    AttestationResolver,
    QualityAttestation,
)
from backend.modules.engine.backtesting import boundaries_from_group_sizes
from backend.modules.engine.model_io import safe_torch_load
from backend.modules.risk.bank_analyzer import BankRiskAnalyzer, MultiBankAnalysis, generate_executive_summary

logger = logging.getLogger(__name__)


@dataclass
class PredictionResult:
    """Prediction result, systemic analysis, and an honest provenance record."""
    job_id: str
    model_path: str

    # Predictions
    predictions_df: pd.DataFrame  # All predictions, one row per source

    # Risk analysis
    per_bank_risks: Dict[str, Any]  # bank_id -> risk profile
    multi_bank_analysis: Optional[MultiBankAnalysis]

    # Attribution. Empty because this payload carries no network to explain; see
    # the module docstring. SubgraphX (modules/engine/subgraphx.py) supplies it
    # when a liability network and a game value are available.
    feature_importances: Dict[str, float]
    confidence_intervals: Dict[str, tuple]
    explanation_report: str

    # Metrics
    metrics: Dict[str, float]

    # User-friendly summary
    executive_summary: str


@dataclass
class RiskSeriesResult:
    """A per-timestep risk series, ordered in time and aligned to the input rows.

    :meth:`RealPredictionEngine.predict` collapses each data source to a single
    score -- the value for its most recent timestep -- which cannot be scored
    against per-row targets. Return-based and drawdown metrics need a series, so
    :meth:`RealPredictionEngine.predict_risk_series` rolls the same window and
    the same normalisation across the payload.

    Rows are grouped by source and time-ordered inside each group, so
    ``boundaries`` marks the seam between consecutive sources: those seams are
    not observations and must never be differenced as if they were.
    """

    frame: pd.DataFrame
    boundaries: List[int]
    sources: List[str]
    n_dropped_for_history: int
    truncated: Dict[str, int]
    stats_provenance: Dict[str, str]
    batch_size: int
    max_steps: Optional[int] = None

    @property
    def n_steps(self) -> int:
        return int(self.frame.shape[0])

    @property
    def n_sources(self) -> int:
        return len(self.sources)

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready metadata. The row-level series is not inlined here."""
        return {
            "n_sources": self.n_sources,
            "n_steps": self.n_steps,
            "n_dropped_for_history": int(self.n_dropped_for_history),
            "boundaries": [int(value) for value in self.boundaries],
            "sources": list(self.sources),
            "truncated": dict(self.truncated),
            "stats_provenance": dict(self.stats_provenance),
            "batch_size": int(self.batch_size),
            "max_steps": None if self.max_steps is None else int(self.max_steps),
            "ordering": "source_major_then_time",
        }


class RealPredictionEngine:
    """
    Prediction engine backed by a trained model.

    Responsibilities:
    1. Load a trained model and refuse to run without a data-quality attestation
    2. Per-source risk scoring and rolled per-timestep risk series
    3. Per-institution and network-level risk analysis
    4. Multiplex clearing of supplied interbank exposures when a balance sheet
       is available (see :mod:`backend.modules.risk.clearing`)
    5. Human-readable reports
    """

    def __init__(
        self,
        model_path: str,
        device: torch.device,
        config: Dict,
        quality_attestation: Optional[QualityAttestation] = None,
    ):
        self.model_path = model_path
        self.device = device
        self.config = config
        self.sequence_length = self.config.get('sequence_length', 30)

        # Predictions are refused unless the payload was quality-attested by the
        # DATA stage. The verdict is resolved from an explicit argument (or this
        # engine's configured default) and never from `DataFrame.attrs`: pandas
        # does not preserve attrs through groupby/merge/concat, so frame metadata
        # cannot carry a governance-critical check. The only override is the
        # environment-gated BEACON_ALLOW_UNVERIFIED_DATA, which production
        # refuses outright.
        if (
            self.config.get('allow_unverified_data')
            or self.config.get('require_quality_attestation') is False
        ):
            logger.warning(
                "Ignoring allow_unverified_data/require_quality_attestation from engine config: "
                "the attestation override is controlled solely by the %s environment variable",
                UNVERIFIED_OVERRIDE_ENV,
            )
        self._attestations = AttestationResolver(quality_attestation)

        self.model_config = {}
        self.source_stats: Dict[str, Dict[str, float]] = {}
        self.sources: List[str] = []
        self.source_to_id: Dict[str, int] = {}

        # Load trained model
        self.model = self._load_model(model_path)
        self.model.eval()

        # BankRiskAnalyzer scores institutions directly from the model and runs
        # clearing on supplied exposures. There is no separate explainer: local
        # attribution was removed rather than reimplemented, because the previous
        # gradient*attention routine produced unverifiable numbers.
        self.bank_analyzer = BankRiskAnalyzer(
            self.model,
            device,
            sequence_length=self.sequence_length,
            source_stats=self.source_stats,
            source_to_id=self.source_to_id
        )

        logger.info(f"Loaded model from {model_path}")

    def apply_scenario(
        self,
        input_data: pd.DataFrame,
        scenario: Dict[str, Any]
    ) -> pd.DataFrame:
        """
        Apply 'what-if' scenario transformations to input data.

        Supported scenarios:
        - liquidity_freeze: Reduce interbank lending
        - policy_intervention: Rate cuts, QE
        - bank_failure: Specific bank default
        - market_crash: Equity/volatility shocks
        - regional_shock: Geographic stress
        - sovereign_crisis: Sovereign debt stress
        - commodity_shock: Oil/commodity price changes
        - operational_risk: Cyber attacks, system failures
        - combined: Multiple simultaneous stresses

        Args:
            input_data: DataFrame with Date, Value, source_code (and optionally bank_id)
            scenario: Dictionary with scenario parameters

        Returns:
            Modified DataFrame with scenario applied
        """
        scenario_type = scenario.get('type', 'custom')
        modified_data = input_data.copy()

        logger.info(f"Applying scenario: {scenario_type}")

        if scenario_type == 'liquidity_freeze':
            # Reduce interbank exposures
            reduction = scenario.get('interbank_lending_reduction', 0.5)

            # Handle both network data (source_bank/target_bank) and time-series data (source_code)
            if 'source_bank' in modified_data.columns and 'target_bank' in modified_data.columns:
                # Network data from AI4Risk plugin - reduce all interbank exposures
                modified_data['Value'] *= (1 - reduction)
            elif 'source_code' in modified_data.columns:
                # Time-series data - reduce interbank-related sources
                modified_data.loc[
                    modified_data['source_code'].str.contains('INTERBANK|AI4RISK', na=False),
                    'Value'
                ] *= (1 - reduction)

        elif scenario_type == 'policy_intervention':
            # Apply rate cut (or hike if negative)
            rate_cut_bps = scenario.get('rate_cut_bps', 0)
            if rate_cut_bps != 0:
                modified_data.loc[
                    modified_data['source_code'].str.contains('RATE|SOFR|ESTR|EURIBOR|FED_FUNDS', na=False),
                    'Value'
                ] += rate_cut_bps / 10000  # Convert bps to decimal

            # Apply QE (increase liquidity)
            qe_amount = scenario.get('qe_amount', 0)
            if qe_amount > 0:
                liquidity_boost = qe_amount / 1e12  # Normalize
                modified_data.loc[
                    modified_data['source_code'].str.contains('RESERVES|M2|LIQUIDITY', na=False),
                    'Value'
                ] *= (1 + liquidity_boost)

        elif scenario_type == 'bank_failure':
            # Simulate bank failure by setting its metrics to critical
            failed_bank = scenario.get('failed_bank_id')
            haircut = scenario.get('exposure_haircut', 0.3)

            if failed_bank and 'bank_id' in modified_data.columns:
                # Failed bank's equity goes to zero
                modified_data.loc[
                    (modified_data['bank_id'] == failed_bank) &
                    (modified_data['source_code'].str.contains('EQUITY|CAPITAL', na=False)),
                    'Value'
                ] = 0

                # Counterparties take haircut on exposures
                if 'target_bank' in modified_data.columns:
                    modified_data.loc[
                        modified_data['target_bank'] == failed_bank,
                        'Value'
                    ] *= (1 - haircut)

        elif scenario_type == 'market_crash':
            # Apply stock market crash
            stock_drop = scenario.get('stock_drop_pct', 0.20)
            vol_spike = scenario.get('volatility_spike', 2.0)

            modified_data.loc[
                modified_data['source_code'].str.contains('STOCK|SPX|EURO|NIKKEI|HSI|EQUITY', na=False),
                'Value'
            ] *= (1 - stock_drop)

            modified_data.loc[
                modified_data['source_code'].str.contains('VIX|VOLATILITY|MOVE', na=False),
                'Value'
            ] *= vol_spike

            # Widen credit spreads
            spread_widening = scenario.get('credit_spread_widening', 0)
            if spread_widening > 0:
                modified_data.loc[
                    modified_data['source_code'].str.contains('SPREAD|TED|CREDIT', na=False),
                    'Value'
                ] += spread_widening

        elif scenario_type == 'regional_shock':
            # Apply regional shocks
            region_shocks = scenario.get('regional_shocks', [])
            for shock in region_shocks:
                region = shock['region']
                magnitude = shock['magnitude']

                # Apply shock to all data sources in region
                if 'region' in modified_data.columns:
                    modified_data.loc[
                        modified_data['region'] == region,
                        'Value'
                    ] *= (1 + magnitude)

        elif scenario_type == 'sovereign_crisis':
            # Sovereign debt crisis
            spread_widening = scenario.get('sovereign_spread_widening', 0.04)
            modified_data.loc[
                modified_data['source_code'].str.contains('BOND|YIELD|10Y|2Y', na=False),
                'Value'
            ] += spread_widening

            # Banking stress from sovereign exposure
            banking_stress = scenario.get('banking_stress', {})
            deposit_flight = banking_stress.get('deposit_flight', 0)
            if deposit_flight > 0 and 'bank_id' in modified_data.columns:
                modified_data.loc[
                    modified_data['source_code'].str.contains('DEPOSIT', na=False),
                    'Value'
                ] *= (1 - deposit_flight)

        elif scenario_type == 'commodity_shock':
            # Oil/commodity price shock
            oil_increase = scenario.get('oil_price_increase', 0)
            if oil_increase > 0:
                modified_data.loc[
                    modified_data['source_code'].str.contains('OIL|WTI|BRENT', na=False),
                    'Value'
                ] *= (1 + oil_increase)

            # Inflation impact
            inflation_spike = scenario.get('inflation_spike', 0)
            if inflation_spike > 0:
                modified_data.loc[
                    modified_data['source_code'].str.contains('CPI|HICP|INFLATION', na=False),
                    'Value'
                ] += inflation_spike

        elif scenario_type == 'operational_risk':
            # Cyber attack or operational disruption
            confidence_shock = scenario.get('market_disruption', {}).get('confidence_shock', 0.15)
            modified_data.loc[
                modified_data['source_code'].str.contains('VIX|VOLATILITY', na=False),
                'Value'
            ] *= (1 + confidence_shock)

        elif scenario_type == 'combined':
            # Apply multiple stresses recursively
            for sub_scenario_type in ['policy_intervention', 'market_crash', 'liquidity_freeze']:
                if any(k in scenario for k in ['rate_cut_bps', 'stock_drop_pct', 'interbank_lending_reduction']):
                    # Create sub-scenario: unpack original first, then override type to avoid infinite recursion
                    sub_scenario = {**scenario, 'type': sub_scenario_type}
                    modified_data = self.apply_scenario(modified_data, sub_scenario)

        logger.info(f"Scenario applied: {scenario_type}")
        return modified_data

    def _load_model(self, model_path: str) -> torch.nn.Module:
        """Load trained PyTorch model."""
        checkpoint = safe_torch_load(model_path, map_location=self.device)

        # Recreate model architecture
        from backend.modules.engine.multi_scale_trainer import MultiScaleTemporalAttentionModel

        # Get config from checkpoint
        config = checkpoint.get('config', {})
        self.model_config = config
        self.sequence_length = config.get('sequence_length', self.config.get('sequence_length', 30))
        self.source_stats = checkpoint.get('source_stats', {}) or {}
        self.sources = checkpoint.get('sources', []) or []
        self.source_to_id = {src: idx for idx, src in enumerate(self.sources)}

        sources = checkpoint.get('sources', [])
        num_sources = max(len(sources), 1)

        model = MultiScaleTemporalAttentionModel(
            num_sources=num_sources,
            sequence_length=self.sequence_length,
            d_model=config.get('d_model', 128),
            nhead=config.get('nhead', 8),
            num_layers=config.get('num_layers', 3),
            dropout=config.get('dropout', 0.1)
        )

        model.load_state_dict(checkpoint['model_state_dict'])
        model.to(self.device)

        return model

    @property
    def quality_attestation(self) -> Optional[QualityAttestation]:
        """The attestation this engine falls back to when none is passed in."""
        return self._attestations.default_attestation

    @quality_attestation.setter
    def quality_attestation(self, attestation: Optional[QualityAttestation]) -> None:
        self._attestations.set_default(attestation)

    def set_quality_attestation(self, attestation: Optional[QualityAttestation]) -> None:
        """Attach the DATA-stage quality verdict to this engine instance."""
        self._attestations.set_default(attestation)

    def _enforce_data_quality(
        self, attestation: Optional[QualityAttestation] = None
    ) -> Optional[QualityAttestation]:
        """Refuse to predict on data that was not attested by the DATA stage.

        The attestation is an explicit value threaded through the pipeline, not a
        DataFrame attribute, so no reshaping step can silently drop it.

        Raises:
            PredictionBlockedError: No verified attestation is available.
        """
        return self._attestations.resolve(attestation)

    def predict(
        self,
        input_data: pd.DataFrame,
        bank_exposures: Optional[Dict[tuple, float]] = None,
        bank_endowments: Optional[Dict[str, float]] = None,
        *,
        attestation: Optional[QualityAttestation] = None,
        spiral_parameters: Optional[Dict[str, Any]] = None,
        latent_dynamics_scenario: Optional[Any] = None,
        counterfactual_scenario: Optional[Any] = None,
    ) -> PredictionResult:
        """
        Score the payload and, when a balance sheet is supplied, clear the network.

        Args:
            input_data: DataFrame with Date, Value, source_code (and optionally bank_id)
            bank_exposures: Inter-bank exposures, ``(debtor, creditor) ->`` amount.
                Enables the topological part of the network analysis.
            bank_endowments: ``bank_id ->`` external assets available to meet
                obligations. Required together with ``bank_exposures`` for the
                Eisenberg-Noe clearing equilibrium and contagion paths; without
                it the analysis reports that the balance sheet is unknown rather
                than substituting the model's own risk score for capital.
            attestation: DATA-stage quality verdict for this payload. Overrides the
                engine-level default; pass it explicitly when the frame has been
                transformed since the gate ran.
            spiral_parameters: ``bank_id ->``
                :class:`~backend.modules.risk.liquidity_spiral.SpiralParameters`.
                When supplied, each institution that failed to pay in the clearing
                equilibrium has its shortfall turned into the adverse price move its
                forced sale implies, and the Brunnermeier-Pedersen spiral is solved
                from there. Requires ``bank_exposures`` and ``bank_endowments``,
                because the shock *is* the clearing shortfall.
            latent_dynamics_scenario: Optional
                :class:`~backend.modules.engine.latent_dynamics.LatentDynamicsScenario`.
                When supplied, each analysed institution's declared initial latent
                stress state is advanced stochastically and the terminal
                dispersion is attached to the analysis and rendered in the report.
                Its drift and diffusion are caller inputs, so the result is a
                **simulated scenario dispersion under a declared SDE, not a
                calibrated prediction interval**; it is never written into the
                ``confidence_*`` fields.
            counterfactual_scenario: Optional
                :class:`~backend.modules.engine.counterfactual.CounterfactualScenario`.
                When supplied, the declared structural model's abduction /
                intervention / propagation is run and the answer is attached to the
                analysis and rendered in the report. It is **conditional on the
                declared model** -- an answer to "what follows from this
                intervention given this model", not a forecast -- and the outcome
                reports that explicitly.

        Returns:
            PredictionResult with per-source risk scores and network analysis
        """
        logger.info("Starting prediction")

        self._enforce_data_quality(attestation)

        # Check if multi-bank scenario
        has_bank_id = 'bank_id' in input_data.columns

        if has_bank_id:
            # Multi-bank analysis
            return self._predict_multi_bank(
                input_data,
                bank_exposures,
                bank_endowments,
                spiral_parameters,
                latent_dynamics_scenario,
                counterfactual_scenario,
            )
        else:
            # Single entity analysis
            return self._predict_single(input_data)

    def predict_risk_series(
        self,
        input_data: pd.DataFrame,
        *,
        attestation: Optional[QualityAttestation] = None,
        max_steps: Optional[int] = None,
        batch_size: int = 256,
    ) -> RiskSeriesResult:
        """Predict a risk level for every timestep that has enough history.

        ``predict()`` returns one score per data source -- the value for its most
        recent timestep -- which cannot be scored against per-row targets.
        Return-based metrics (Sharpe, Sortino, drawdown, Calmar, VaR/CVaR) need a
        series ordered in time, so this rolls the same window, the same source
        mapping and the same normalisation across the payload.

        Predictions come back grouped by source and time-ordered within each
        group; ``boundaries`` records the seam between consecutive sources so
        those seams are never differenced as if they were observations.

        ``max_steps`` caps the timesteps inferred per source, keeping the most
        recent ones, because every step costs a model forward pass; ``None``
        disables the cap. ``batch_size`` controls how many windows share one
        forward pass.

        Raises:
            SchemaValidationError: The payload cannot yield a risk series.
        """
        self._enforce_data_quality(attestation)

        if 'source_code' not in input_data.columns:
            raise SchemaValidationError(
                "A per-timestep risk series requires a 'source_code' column",
                context={"columns": [str(column) for column in input_data.columns]},
            )

        sequence_length = int(self.sequence_length)
        if sequence_length < 1:
            raise SchemaValidationError(
                f"sequence_length must be positive, got {sequence_length}"
            )

        step_cap: Optional[int] = None if max_steps is None else int(max_steps)
        if step_cap is not None and step_cap <= sequence_length:
            raise SchemaValidationError(
                f"max_steps={step_cap} cannot fill a {sequence_length}-step window"
            )
        window_batch = max(1, int(batch_size))

        # Keep the caller's row positions so each prediction can be aligned with
        # its own row (and therefore with that row's target) without relying on
        # the frame index being unique.
        working = input_data.assign(
            __row_offset=np.arange(input_data.shape[0], dtype=int)
        )

        frames: List[pd.DataFrame] = []
        sources: List[str] = []
        group_sizes: List[int] = []
        truncated: Dict[str, int] = {}
        stats_provenance: Dict[str, str] = {}
        dropped_for_history = 0

        for raw_source, group in working.groupby('source_code', sort=True):
            source_code = str(raw_source)
            ordered = group.sort_values('Date') if 'Date' in group.columns else group
            value_column = 'Close' if 'Close' in ordered.columns else 'Value'
            if value_column not in ordered.columns:
                raise SchemaValidationError(
                    "Payload has neither a 'Close' nor a 'Value' column for source "
                    f"{source_code}"
                )

            # Gaps stay as NaN here. They are imputed with the standardised mean
            # below, after normalisation -- never forward-filled, which would
            # carry a pre-gap level across the gap and let the rolling window see
            # values that were not published at those timestamps.
            values = (
                pd.to_numeric(ordered[value_column], errors='coerce')
                .astype(float)
                .to_numpy(dtype=float)
            )
            if step_cap is not None and values.size > step_cap:
                truncated[source_code] = int(values.size - step_cap)
                values = values[-step_cap:]
                ordered = ordered.iloc[-step_cap:]

            if values.size <= sequence_length:
                dropped_for_history += int(values.size)
                logger.warning(
                    "Risk series: source %s has %d row(s), too few for a %d-step window",
                    source_code,
                    values.size,
                    sequence_length,
                )
                continue

            # Reuse `_prepare_sequence`'s normalisation so a rolling prediction is
            # directly comparable with the point prediction `predict()` returns
            # for the same row. Checkpoint stats are the training-time ones;
            # falling back to stats computed over the evaluated window is
            # recorded, because that fallback lets the normalisation see the
            # future and makes the resulting metrics optimistic.
            _, stats = self._prepare_sequence(values, source_code)
            stats_provenance[source_code] = (
                "checkpoint" if self.source_stats.get(source_code) else "payload_window"
            )
            mean = float(stats.get('mean', 0.0))
            std = float(stats.get('std', 1.0)) or 1.0
            normalized = (values - mean) / std
            # Impute unobserved entries at the standardised mean rather than
            # carrying the previous value forward.
            normalized = np.where(np.isfinite(normalized), normalized, 0.0)

            windows = np.lib.stride_tricks.sliding_window_view(normalized, sequence_length)
            scores = self._score_windows(
                windows, self._map_source_id(source_code), window_batch
            )

            # Row i of `windows` ends at index i + sequence_length - 1.
            ends = np.arange(sequence_length - 1, values.size)
            frame = pd.DataFrame({
                'source': source_code,
                'row_offset': np.asarray(ordered['__row_offset'])[ends],
                'risk_score': scores,
                'prediction': scores * std + mean,
            })
            if 'Date' in ordered.columns:
                frame['Date'] = np.asarray(ordered['Date'])[ends]

            dropped_for_history += sequence_length - 1
            frames.append(frame)
            sources.append(source_code)
            group_sizes.append(int(frame.shape[0]))

        if not frames:
            raise SchemaValidationError(
                "No source in the payload has enough history for a per-timestep risk series",
                context={
                    "sequence_length": sequence_length,
                    "max_steps": step_cap,
                    "rows": int(input_data.shape[0]),
                },
            )

        optimistic = sorted(
            source
            for source, origin in stats_provenance.items()
            if origin == "payload_window"
        )
        if optimistic:
            logger.warning(
                "Risk series normalisation for %s came from the evaluated window rather "
                "than the checkpoint, so metrics on those sources are optimistic: the "
                "normalisation saw the future",
                optimistic,
            )

        return RiskSeriesResult(
            frame=pd.concat(frames, ignore_index=True),
            boundaries=[int(value) for value in boundaries_from_group_sizes(group_sizes)],
            sources=sources,
            n_dropped_for_history=int(dropped_for_history),
            truncated=truncated,
            stats_provenance=stats_provenance,
            batch_size=window_batch,
            max_steps=step_cap,
        )

    def _score_windows(
        self, windows: np.ndarray, source_id: int, batch_size: int
    ) -> np.ndarray:
        """Run the frozen model over pre-normalised windows, in batches."""
        total = int(windows.shape[0])
        scores = np.empty(total, dtype=float)
        self.model.eval()
        with torch.no_grad():
            for start in range(0, total, batch_size):
                chunk = np.asarray(windows[start:start + batch_size], dtype=np.float32)
                inputs = torch.FloatTensor(chunk).to(self.device)
                source_ids = torch.full(
                    (chunk.shape[0], 1),
                    int(source_id),
                    dtype=torch.long,
                    device=self.device,
                )
                outputs = self.model(inputs, source_ids)
                flat = outputs.detach().cpu().numpy().astype(float).reshape(chunk.shape[0], -1)
                scores[start:start + chunk.shape[0]] = flat[:, 0]
        return scores

    def _predict_single(self, input_data: pd.DataFrame) -> PredictionResult:
        """Predict for single entity."""

        # Group by source
        predictions_list = []
        confidence_intervals: Dict[str, tuple] = {}

        for source_code in input_data['source_code'].unique():
            source_data = input_data[input_data['source_code'] == source_code]
            source_data = source_data.sort_values('Date')

            # Get source ID
            source_id = self._map_source_id(source_code)

            # Prepare sequence from the 'Close' column when present. Gaps are
            # preserved rather than forward-filled: carrying a stale observation
            # into the future feeds the model values that were not published at
            # that timestamp, which is look-ahead.
            value_column = 'Close' if 'Close' in source_data.columns else 'Value'
            values = pd.to_numeric(
                source_data[value_column], errors='coerce'
            ).to_numpy(dtype=float)
            sequence, stats = self._prepare_sequence(values, source_code)

            normalized_prediction = self._score_sequence(sequence, source_id)
            denorm_prediction = self._denormalize_prediction(normalized_prediction, stats)

            predictions_list.append({
                'source': source_code,
                'prediction': denorm_prediction,
                'risk_score': normalized_prediction,
                # No calibrated interval exists yet. Reported as None rather
                # than as an MC-dropout interval, which described a different
                # network from the one that produced this score.
                'confidence_lower': None,
                'confidence_upper': None,
            })
            confidence_intervals[source_code] = (None, None)

        predictions_df = pd.DataFrame(predictions_list)

        # Generate executive summary
        if not predictions_df.empty:
            avg_risk = float(predictions_df['risk_score'].mean())
            max_risk = float(predictions_df['risk_score'].max())
            min_risk = float(predictions_df['risk_score'].min())
        else:
            avg_risk = max_risk = min_risk = 0.0

        executive_summary = f"""
LIQUIDITY RISK PREDICTION SUMMARY

Overall Risk Level: {avg_risk * 100:.1f}%
Maximum Risk: {max_risk * 100:.1f}%
Data Sources Analyzed: {len(predictions_df)}

KEY FINDINGS:
{self._generate_key_findings(predictions_df)}

Attribution and calibrated uncertainty are not reported: local feature
attribution is available through SubgraphX when a liability network and a game
value are supplied, and intervals through conformal calibration. Neither is
reported here rather than approximated.
"""

        return PredictionResult(
            job_id=self.config.get('job_id', 'unknown'),
            model_path=self.model_path,
            predictions_df=predictions_df,
            per_bank_risks={},
            multi_bank_analysis=None,
            feature_importances={},
            confidence_intervals=confidence_intervals,
            explanation_report=self._generate_explanation_report(predictions_df),
            metrics={
                'avg_risk_score': avg_risk,
                'max_risk_score': max_risk,
                'min_risk_score': min_risk,
                'avg_prediction_value': float(predictions_df['prediction'].mean()) if not predictions_df.empty else 0.0,
                'max_prediction_value': float(predictions_df['prediction'].max()) if not predictions_df.empty else 0.0,
                'min_prediction_value': float(predictions_df['prediction'].min()) if not predictions_df.empty else 0.0
            },
            executive_summary=executive_summary
        )

    def _predict_multi_bank(
        self,
        input_data: pd.DataFrame,
        bank_exposures: Optional[Dict[tuple, float]],
        bank_endowments: Optional[Dict[str, float]] = None,
        spiral_parameters: Optional[Dict[str, Any]] = None,
        latent_dynamics_scenario: Optional[Any] = None,
        counterfactual_scenario: Optional[Any] = None,
    ) -> PredictionResult:
        """Predict for multiple institutions and clear the network if possible."""

        logger.info("Multi-bank prediction with network analysis")

        # Group data by bank
        bank_data = {}
        for bank_id in input_data['bank_id'].unique():
            bank_data[bank_id] = input_data[input_data['bank_id'] == bank_id]

        # Run multi-bank analysis. Clearing runs only when both exposures and
        # endowments are supplied; otherwise the analysis reports network
        # topology and says plainly that the balance sheet is unknown. The
        # liquidity spiral is solved only when the clearing equilibrium exists,
        # because its initial shock is the clearing shortfall. The latent SDE
        # scenario needs no balance sheet: its inputs are the caller's declared
        # initial states and SDE parameters.
        multi_bank_analysis = self.bank_analyzer.analyze_multiple_banks(
            bank_data,
            bank_exposures,
            bank_endowments=bank_endowments,
            spiral_parameters=spiral_parameters,
            latent_dynamics_scenario=latent_dynamics_scenario,
            counterfactual_scenario=counterfactual_scenario,
        )

        # Extract predictions
        predictions_list = []
        per_bank_risks = {}

        for bank_id, profile in multi_bank_analysis.bank_profiles.items():
            predictions_list.append({
                'bank_id': bank_id,
                'bank_name': profile.bank_name,
                'overall_risk': profile.risk_score,
                'risk_level': profile.risk_level,
                'systemic_importance': profile.systemic_importance,
                'systemic_importance_method': profile.systemic_importance_method,
                'network_position': profile.network_position,
                'gross_liabilities': profile.gross_liabilities,
                'gross_claims': profile.gross_claims,
                'confidence_lower': profile.confidence_lower,
                'confidence_upper': profile.confidence_upper,
                'confidence_method': profile.confidence_method,
                'top_vulnerability': (
                    profile.top_vulnerabilities[0] if profile.top_vulnerabilities else 'N/A'
                ),
            })

            per_bank_risks[bank_id] = asdict(profile)

        predictions_df = pd.DataFrame(predictions_list)

        # Generate executive summary
        executive_summary = generate_executive_summary(multi_bank_analysis)

        return PredictionResult(
            job_id=self.config.get('job_id', 'unknown'),
            model_path=self.model_path,
            predictions_df=predictions_df,
            per_bank_risks=per_bank_risks,
            multi_bank_analysis=multi_bank_analysis,
            feature_importances={},
            confidence_intervals={
                bank_id: (profile.confidence_lower, profile.confidence_upper)
                for bank_id, profile in multi_bank_analysis.bank_profiles.items()
            },
            explanation_report=self._generate_multi_bank_explanation_report(multi_bank_analysis),
            metrics={
                'avg_risk': multi_bank_analysis.avg_risk,
                'max_risk': multi_bank_analysis.max_risk,
                'systemic_risk': multi_bank_analysis.systemic_risk_score,
                'num_high_risk': multi_bank_analysis.num_high_risk,
                'num_critical_risk': multi_bank_analysis.num_critical_risk
            },
            executive_summary=executive_summary
        )

    def _map_source_id(self, source_code: str) -> int:
        if self.source_to_id and source_code in self.source_to_id:
            return int(self.source_to_id[source_code])
        if self.source_to_id:
            logger.warning(f"Source '{source_code}' not seen during training - defaulting to source id 0")
            return 0
        return 0

    def _score_sequence(self, sequence: torch.Tensor, source_id: int) -> float:
        """Single forward pass for one window, with no attribution machinery."""
        inputs = sequence.unsqueeze(0).to(self.device)
        source_ids = torch.tensor(
            [[int(source_id)]], dtype=torch.long, device=self.device
        )
        self.model.eval()
        with torch.no_grad():
            output = self.model(inputs, source_ids)
        return float(output.detach().cpu().reshape(-1)[0])

    def _prepare_sequence(self, values: np.ndarray, source_code: str) -> tuple[torch.Tensor, Dict[str, float]]:
        """Normalise the tail of a series, keeping gaps as an explicit mask.

        Missing entries are **not** forward-filled. Carrying the previous
        observation forward presents the model with a value that had not been
        published at that timestamp: a series with a reporting gap would have its
        pre-gap level copied across the gap, so the model sees the future through
        a hole in the past. Instead missing entries are set to the standardised
        mean (``0``) and the observed fraction is reported, so a window that is
        mostly imputed is distinguishable from one that was fully observed.
        """
        values = np.asarray(values, dtype=np.float32)
        stats = self.source_stats.get(source_code, {})

        finite = values[np.isfinite(values)]
        default_mean = float(finite.mean()) if finite.size else 0.0
        default_std = float(finite.std()) if finite.size else 1.0
        mean = float(stats.get('mean', default_mean))
        std = float(stats.get('std', default_std))
        if not np.isfinite(std) or std == 0.0:
            std = 1.0

        if len(values):
            normalized = (values - mean) / std
            observed = np.isfinite(normalized)
            normalized = np.where(observed, normalized, 0.0).astype(np.float32)
        else:
            normalized = np.zeros(0, dtype=np.float32)
            observed = np.zeros(0, dtype=bool)

        if len(normalized) >= self.sequence_length:
            normalized = normalized[-self.sequence_length:]
            observed = observed[-self.sequence_length:]
        else:
            pad = self.sequence_length - len(normalized)
            normalized = np.pad(
                normalized, (pad, 0), mode='constant', constant_values=0.0
            )
            observed = np.pad(observed, (pad, 0), mode='constant', constant_values=False)

        sequence = torch.FloatTensor(normalized)
        return sequence, {
            'mean': mean,
            'std': std,
            'observed_fraction': float(observed.mean()) if observed.size else 0.0,
        }

    def _denormalize_prediction(self, normalized_value: float, stats: Dict[str, float]) -> float:
        mean = stats.get('mean', 0.0)
        std = stats.get('std', 1.0)
        return float(normalized_value * std + mean)

    def _generate_key_findings(self, predictions_df: pd.DataFrame) -> str:
        """Summarise the scored sources without inventing drivers.

        A "primary risk driver" and a HIGH/MODERATE/LOW confidence label were
        removed along with the attribution routine. Both descended from the
        gradient*attention values, so they inherited its unreliability -- and the
        confidence label read an interval produced by a different network than
        the one that scored the payload.
        """
        findings = []

        if predictions_df.empty or 'prediction' not in predictions_df:
            return "- No predictions were produced"

        valid = predictions_df['prediction'].dropna()
        if len(valid) > 0:
            peak = predictions_df.loc[valid.idxmax()]
            findings.append(
                f"- Highest risk score: {peak['source']} ({peak['risk_score'] * 100:.1f}%)"
            )
            findings.append(
                f"- Mean risk score across {len(valid)} source(s): {valid.mean() * 100:.1f}%"
            )
        else:
            findings.append("- No valid risk predictions available")

        findings.append(
            "- Per-feature attribution and calibrated prediction intervals are not "
            "reported (see the module docstring)"
        )
        return "\n".join(findings)

    def _generate_explanation_report(self, predictions_df: pd.DataFrame) -> str:
        """Report the scores, and state plainly what is not yet attributable."""
        report = "MODEL OUTPUT REPORT\n" + "=" * 50 + "\n\n"
        report += (
            "Local feature attribution is not reported. The previous implementation\n"
            "presented gradient*input scaled by uniform attention weights as SHAP\n"
            "values; that routine was removed rather than re-tuned. It is replaced\n"
            "by SubgraphX (modules/engine/subgraphx.py), which reports the connected\n"
            "subgraph accounting for a prediction under a caller-supplied game value\n"
            "such as the clearing shortfall. Attribution is omitted below because\n"
            "this report carries no network to explain, and a per-feature scalar is\n"
            "not the right object for a network model.\n\n"
        )

        if predictions_df.empty:
            return report + "No predictions were produced.\n"

        for _, row in predictions_df.iterrows():
            report += f"Source: {row['source']}\n"
            report += f"  Risk score: {row['risk_score']:.4f}\n"
            report += f"  Denormalised prediction: {row['prediction']:.4f}\n\n"

        report += "-" * 50 + "\n"
        return report

    def _generate_multi_bank_explanation_report(self, analysis: MultiBankAnalysis) -> str:
        """Render the network analysis, including what could not be computed."""
        report = "MULTI-INSTITUTION NETWORK REPORT\n" + "=" * 70 + "\n\n"
        report += f"Date: {analysis.analysis_date}\n"
        report += f"Institutions analysed: {analysis.num_banks}\n"

        if analysis.systemic_risk_score is None:
            report += (
                "Systemic clearing: UNAVAILABLE - interbank liabilities and/or\n"
                "endowments were not supplied. No clearing equilibrium exists to\n"
                "report, and a model risk score is not a substitute for capital.\n"
            )
        else:
            report += (
                "Unpaid fraction of system liabilities at the clearing "
                f"equilibrium: {analysis.systemic_risk_score * 100:.2f}%\n"
            )
            if analysis.clearing is not None:
                report += (
                    f"Clearing converged in {analysis.clearing.iterations} iteration(s); "
                    f"{analysis.clearing.n_defaults} institution(s) defaulted\n"
                )
        if analysis.fire_sale is None:
            report += (
                "Coupled fire-sale equilibrium: UNAVAILABLE - holdings, prices and\n"
                "capital were not supplied. The clearing figure above holds prices\n"
                "fixed; without those inputs the feedback loop that moves them\n"
                "cannot be solved, and its absence is not evidence that it is small.\n"
            )
        else:
            fire_sale = analysis.fire_sale
            if fire_sale.diverged:
                report += (
                    "Coupled fire-sale equilibrium: DIVERGED after "
                    f"{fire_sale.rounds} round(s) - {fire_sale.divergence_reason}.\n"
                    "No finite equilibrium exists for this scenario. The run-away is\n"
                    "the result, not a failure of the solver.\n"
                )
            else:
                report += (
                    "Coupled fire-sale equilibrium converged in "
                    f"{fire_sale.rounds} round(s).\n"
                )
            if fire_sale.amplification is not None:
                report += (
                    "Shortfall attributable to the liquidation feedback, with price\n"
                    "impact held at zero: "
                    f"{fire_sale.amplification.feedback_shortfall:,.2f}\n"
                )
            if fire_sale.feedback_caused_defaults:
                report += (
                    "Institutions that fail only because of the feedback: "
                    + ", ".join(fire_sale.feedback_caused_defaults)
                    + "\n"
                )
        report += "\n"

        if analysis.regulatory_stress is None:
            report += (
                "Basel III stress translation: UNAVAILABLE - per-institution liquidity,\n"
                "funding and leverage positions were not supplied. A model risk score is\n"
                "not a substitute for a regulatory ratio.\n"
            )
        else:
            stress = analysis.regulatory_stress
            if not stress.stress_applied:
                report += (
                    "Basel III stress translation: no stress was supplied, so these are\n"
                    "pre-stress ratios only.\n"
                )
            for row in stress.rows:
                report += f"\n  {row.institution_id}:\n"
                report += f"    LCR: {row.lcr_before:.3f} -> {row.lcr_after:.3f}\n"
                if row.nsfr_after is not None:
                    report += f"    NSFR: {row.nsfr_before:.3f} -> {row.nsfr_after:.3f}\n"
                if row.leverage_after is not None:
                    report += (
                        f"    Leverage ratio: {row.leverage_before:.4f} -> "
                        f"{row.leverage_after:.4f}\n"
                    )
                if row.thresholds_breached_after:
                    report += (
                        "    Breached after stress: "
                        + ", ".join(row.thresholds_breached_after)
                        + "\n"
                    )
        report += "\n"

        if analysis.crowding is None:
            report += (
                "Crowded-trade overlap: UNAVAILABLE - no holdings matrix was supplied.\n"
                "Overlap is a volatility channel invisible in exposure data: two\n"
                "institutions can hold identical positions and owe each other nothing.\n"
            )
        else:
            crowding = analysis.crowding
            score = crowding.system_crowding
            report += (
                f"Crowded-trade overlap across {len(crowding.institution_ids)} "
                f"institution(s) and {len(crowding.instrument_ids)} instrument(s); "
                f"system crowding {score.normalized:.3f} (raw {score.raw:.3f})\n"
            )
        report += "\n"

        if analysis.topology is None:
            report += (
                "Network topology: UNAVAILABLE - no persistence parameters were supplied,\n"
                "or the exposure network does not exist. Average degree and volatility can\n"
                "both be unchanged while the routes between members quietly collapse.\n"
            )
        else:
            summary = analysis.topology.summary
            report += (
                "Network topology: "
                f"{summary['beta_0']:.0f} component(s), "
                f"{summary['beta_1']:.0f} independent cycle(s), "
                f"fragmentation {summary['fragmentation']:.3f}, "
                f"redundancy {summary['redundancy']:.3f}\n"
            )
        report += "\n"

        if not analysis.liquidity_spiral:
            report += (
                "Liquidity spiral: UNAVAILABLE - no spiral parameters were supplied, or\n"
                "no institution failed to pay in the clearing equilibrium. The initial\n"
                "shock is the clearing shortfall, so with no clearing equilibrium there\n"
                "is no shock to propagate and none is invented from the model score.\n"
            )
        else:
            report += (
                "Liquidity spiral (Brunnermeier-Pedersen) for "
                f"{len(analysis.liquidity_spiral)} institution(s):\n"
            )
            for bank_id, spiral in analysis.liquidity_spiral.items():
                if spiral.collapsed:
                    outcome = "COLLAPSED - no finite equilibrium"
                elif spiral.fully_liquidated:
                    outcome = "fully liquidated"
                else:
                    outcome = f"amplification {spiral.amplification:.3f}"
                report += (
                    f"  {bank_id}: shock {spiral.shock:.6g} -> total price move "
                    f"{spiral.total_price_change:.6g} ({outcome})\n"
                )
        report += "\n"

        if analysis.latent_dynamics is None:
            report += (
                "Latent stress dispersion: UNAVAILABLE - no latent dynamics scenario\n"
                "was supplied. The SDE is not run by default: its drift, diffusion and\n"
                "initial latent states must be declared by the caller, and a dispersion\n"
                "invented from the model risk score would be a restatement of the model\n"
                "rather than a simulated latent path.\n"
            )
        else:
            latent = analysis.latent_dynamics
            report += (
                "Latent stress dispersion (simulated scenario under a caller-declared\n"
                "SDE; NOT a calibrated prediction interval):\n"
                f"  drift {latent.drift_description}\n"
                f"  diffusion {latent.diffusion_description}\n"
                f"  horizon {latent.horizon:g} in {latent.steps} step(s) of dt "
                f"{latent.dt:g}; {latent.n_paths} path(s); seed {latent.seed}; "
                f"{latent.integrator}\n"
            )
            for bank_id in latent.institution_ids:
                reference = " ".join(
                    f"{value:.6g}" for value in latent.drift_only_terminal[bank_id]
                )
                report += (
                    f"  {bank_id}: terminal dispersion "
                    f"{latent.terminal_dispersion[bank_id]:.6g}; drift-only terminal "
                    f"[{reference}]\n"
                )
            report += (
                f"  Mean dispersion across {len(latent.institution_ids)} institution(s): "
                f"{latent.mean_dispersion:.6g}; maximum {latent.max_dispersion:.6g}\n"
                "  Calibration: NONE. The drift and diffusion are caller declarations,\n"
                "  not estimates, and no coverage guarantee, threshold probability or\n"
                "  forecast follows from this dispersion. It is a simulated scenario\n"
                "  dispersion and is not written to the prediction-interval fields.\n"
            )
        report += "\n"

        if analysis.counterfactual is None:
            report += (
                "Counterfactual: UNAVAILABLE - no counterfactual scenario was supplied.\n"
                "It is not run by default: it requires a caller-declared structural\n"
                "model plus an explicit do-operation, and a counterfactual invented\n"
                "from the model risk score would be a restatement of the model rather\n"
                "than an answer to an intervention.\n"
            )
        else:
            counterfactual = analysis.counterfactual
            result = counterfactual.result
            report += (
                "Counterfactual (conditional on the caller-declared structural model;\n"
                "NOT a forecast):\n"
                f"  model: {counterfactual.reference}\n"
            )
            for item in result.interventions:
                rendered = (
                    f"{float(item.value):.6g}"
                    if np.isscalar(item.value)
                    else "a per-timestep path"
                )
                report += f"  do({item.variable} := {rendered})\n"
            report += (
                f"  affected: {', '.join(result.affected) or 'nothing'}\n"
                f"  unaffected: {', '.join(result.unaffected) or 'nothing'}\n"
                f"  largest change {result.max_absolute_effect:.6g}; trajectory "
                f"constraints "
                f"{'satisfied' if result.constraints_ok else 'VIOLATED: ' + ', '.join(result.constraint_violations)}\n"
                "  Conditionality: this answers 'what follows from this intervention\n"
                "  given this model'. It is not a prediction of the world, and a\n"
                "  misspecified coefficient yields a precise wrong answer that nothing\n"
                "  here bounds.\n"
            )
        report += "\n"

        report += "INSTITUTION ASSESSMENTS:\n" + "-" * 70 + "\n"
        for bank_id, profile in analysis.bank_profiles.items():
            report += f"\n{profile.bank_name} ({bank_id}):\n"
            report += f"  Model risk score: {profile.risk_score * 100:.1f}% ({profile.risk_level})\n"
            report += (
                f"  Systemic importance: {profile.systemic_importance * 100:.1f}% "
                f"({profile.systemic_importance_method})\n"
            )
            report += f"  Network position: {profile.network_position}\n"
            report += f"  Gross liabilities: {profile.gross_liabilities:,.2f}\n"
            report += f"  Gross claims: {profile.gross_claims:,.2f}\n"
            report += f"  Prediction interval: {profile.confidence_method}\n"

            if profile.top_vulnerabilities:
                report += "  Observed conditions:\n"
                for finding in profile.top_vulnerabilities[:2]:
                    report += f"    - {finding}\n"

            if profile.recommendations:
                report += "  Recommendations:\n"
                for recommendation in profile.recommendations[:2]:
                    report += f"    - {recommendation}\n"

        if analysis.shock_scenarios:
            report += (
                "\n\nCONTAGION SCENARIOS (total loss of external assets):\n"
                + "-" * 70 + "\n"
            )
            for bank_id, result in analysis.shock_scenarios.items():
                sequence = result.default_sequence()
                report += f"  If {bank_id} loses all external assets:\n"
                report += f"    - Institutions failing: {result.n_defaults}\n"
                report += f"    - Propagation rounds: {len(result.default_rounds)}\n"
                report += (
                    "    - Order of failure: "
                    f"{' -> '.join(sequence) if sequence else 'none'}\n"
                )

        report += "\n" + "=" * 70 + "\n"
        report += (
            "Attribution: none reported. SubgraphX (modules/engine/subgraphx.py)\n"
            "explains a prediction as a connected subgraph under a caller-supplied\n"
            "game value; this report carries no network to explain, and no\n"
            "approximate attribution is substituted.\n"
        )
        return report
