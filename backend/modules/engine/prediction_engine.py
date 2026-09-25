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

Uncertainty intervals are split-conformal, computed per source from the
payload's own held-out rolling residuals when there are enough of them; a
source that cannot support a calibration window gets ``None`` bounds with
``confidence_method`` recording why -- never a zero-width or invented
interval. What remains uncalibrated is the risk *scale*: no mapping from the
standardized score to risk levels exists, and none is simulated.
"""

import torch
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict, field
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
from backend.modules.engine.multi_scale_trainer import STANDARDIZED_VALUE_CLIP
from backend.modules.engine.value_columns import VALUE_COLUMN_CANDIDATES, select_value_column
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

    # Aleatoric/epistemic decomposition state for this run (deep ensemble when
    # members exist beside the checkpoint; single-model otherwise, where the
    # split is reported not measurable rather than approximated). Defaulted so
    # existing constructor calls and the bank-level path are unaffected.
    uncertainty_summary: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskSeriesResult:
    """A per-timestep risk series, ordered in time and aligned to the input rows.

    :meth:`RealPredictionEngine.predict` collapses each data source to a single
    score -- the value for its most recent timestep -- which cannot be scored
    against per-row targets. Return-based and drawdown metrics need a series, so
    :meth:`RealPredictionEngine.predict_risk_series` rolls the same window and
    the same normalisation across the payload.

    Rows are grouped by series -- ``series_id`` when the payload carries one,
    else the feed's ``source_code`` -- and time-ordered inside each group, so
    ``boundaries`` marks the seam between consecutive series: those seams are
    not observations and must never be differenced as if they were.
    ``sources`` is the deduplicated list of feed codes; ``series_ids`` is one
    entry per series, in frame order.

    Alignment convention: the model predicts the row *after* its window ends.
    ``frame['row_offset']`` is the caller-frame position of the window's last
    input row; ``frame['predicted_row_offset']`` is the caller-frame position
    of the row the score predicts, or ``-1`` when that row falls outside the
    source's span (each source's final window). Ground-truth comparison must
    join on ``predicted_row_offset``, never on ``row_offset``.
    """

    frame: pd.DataFrame
    boundaries: List[int]
    sources: List[str]
    series_ids: List[str]
    n_dropped_for_history: int
    truncated: Dict[str, int]
    stats_provenance: Dict[str, str]
    batch_size: int
    max_steps: Optional[int] = None
    #: Rows in series that carry no usable value column at all. Such a series
    #: is skipped rather than standardised to a degenerate all-zero input,
    #: which would score as a plausible-looking value.
    n_dropped_no_values: int = 0
    #: Per-feed provenance of the source embedding used: "trained" for feeds
    #: the checkpoint learned an embedding for, "fallback_id_0" for feeds it
    #: did not. The fallback id is not an untrained slot -- with an
    #: enumerate()-built source map, id 0 is also the first trained feed's
    #: embedding, so a fallback feed's scores carry the wrong per-source
    #: component.
    embedding_provenance: Dict[str, str] = field(default_factory=dict)

    @property
    def n_steps(self) -> int:
        return int(self.frame.shape[0])

    @property
    def n_sources(self) -> int:
        return len(self.sources)

    @property
    def n_series(self) -> int:
        return len(self.series_ids)

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready metadata. The row-level series is not inlined here."""
        return {
            "n_sources": self.n_sources,
            "n_series": self.n_series,
            "n_steps": self.n_steps,
            "n_dropped_for_history": int(self.n_dropped_for_history),
            "boundaries": [int(value) for value in self.boundaries],
            "sources": list(self.sources),
            "series_ids": list(self.series_ids),
            "truncated": dict(self.truncated),
            "stats_provenance": dict(self.stats_provenance),
            "embedding_provenance": dict(self.embedding_provenance),
            "batch_size": int(self.batch_size),
            "max_steps": None if self.max_steps is None else int(self.max_steps),
            "n_dropped_no_values": int(self.n_dropped_no_values),
            "ordering": "series_major_then_time",
        }


class _EnsembleMemberAdapter:
    """Adapt a frozen checkpoint to the ``predict(X)`` member interface that
    :class:`~backend.modules.engine.uncertainty.DeepEnsemble` requires.

    Windows are scored through the engine's own batched forward pass, with the
    same source id and in the same standardised space the point score uses, so
    members are compared with each other -- and with the primary model -- on
    exactly the inputs production feeds the primary. No member gets a private
    scoring path that could drift from the one being decomposed.
    """

    def __init__(self, engine: "RealPredictionEngine", model: torch.nn.Module, source_id: int):
        self._engine = engine
        self._model = model
        self._source_id = int(source_id)

    def predict(self, X: Any) -> np.ndarray:  # noqa: N803 - harness duck type
        windows = np.asarray(X, dtype=np.float32)
        if windows.ndim == 1:
            windows = windows.reshape(1, -1)
        return self._engine._score_windows(windows, self._source_id, 256, model=self._model)


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

        # Ensemble members for the aleatoric/epistemic decomposition
        # (modules/engine/uncertainty.py). Present only when the training job
        # declared ensemble_size >= 2; with a single frozen checkpoint the
        # epistemic term is identically zero by construction, so the
        # decomposition reports itself not measurable rather than manufacturing
        # a number. See _uncertainty_for_source.
        self.ensemble_members: List[torch.nn.Module] = self._load_ensemble_members()

        # Cross-source batched inference on the single-entity path. Default
        # on: one forward pass over all sources' final windows and one over
        # all held-out calibration windows. Tests and operators can force the
        # per-source serial path (identical numbers, slower) by setting this
        # to False; the batched path also falls back to serial on any error.
        self._batch_inference = True

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

    #: Which scenario parameters each named scenario type consumes. Used both
    #: to infer the type when the caller supplies parameters without one and
    #: to decide which sub-scenarios a ``combined`` run recurses into.
    _SCENARIO_TYPE_KEYS = {
        'policy_intervention': ('rate_cut_bps', 'qe_amount'),
        'market_crash': ('stock_drop_pct', 'volatility_spike', 'credit_spread_widening'),
        'liquidity_freeze': ('interbank_lending_reduction',),
        'bank_failure': ('failed_bank_id', 'exposure_haircut'),
        'regional_shock': ('regional_shocks',),
        'sovereign_crisis': ('sovereign_spread_widening', 'banking_stress'),
        'commodity_shock': ('oil_price_increase', 'inflation_spike'),
        'operational_risk': ('market_disruption',),
    }

    def _infer_scenario_type(self, scenario: Dict[str, Any]) -> str:
        """Resolve the scenario type, inferring it from the parameters present.

        A caller may pass ``rate_cut_bps`` without a ``type``; the previous
        behaviour was to apply nothing (``type`` defaulted to ``custom``),
        which is how the API path silently ignored the rich parameters.
        """
        declared = scenario.get('type')
        if declared not in (None, '', 'custom'):
            return str(declared)
        present = {
            name
            for name, keys in self._SCENARIO_TYPE_KEYS.items()
            if any(key in scenario for key in keys)
        }
        if not present:
            return 'custom'
        return 'combined' if len(present) > 1 else next(iter(present))

    def _transform_values(
        self,
        data: pd.DataFrame,
        mask: pd.Series,
        kind: str,
        amount: float,
    ) -> None:
        """Apply ``kind`` ('mul' or 'add') to every value column the frame carries.

        The prediction paths read the per-series value column via
        ``select_value_column``: OHLC rows from ``Close``/``close``, value rows
        from ``Value``/``value``. Transforming only ``Value`` would leave the
        OHLC series (equities, FX, gold) untouched, so a scenario that is
        supposed to shock the market would silently miss exactly the sources
        the market model watches.
        """
        for column in VALUE_COLUMN_CANDIDATES:
            if column in data.columns:
                if kind == 'mul':
                    data.loc[mask, column] = data.loc[mask, column] * amount
                else:
                    data.loc[mask, column] = data.loc[mask, column] + amount

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

        When ``type`` is absent it is inferred from the parameters present
        (``_infer_scenario_type``); a ``combined`` run recurses into every
        applicable named scenario.

        Args:
            input_data: DataFrame with Date, Value, source_code (and optionally bank_id)
            scenario: Dictionary with scenario parameters

        Returns:
            Modified DataFrame with scenario applied
        """
        scenario_type = self._infer_scenario_type(scenario)
        modified_data = input_data.copy()

        logger.info(f"Applying scenario: {scenario_type}")

        if scenario_type == 'liquidity_freeze':
            # Reduce interbank exposures
            reduction = scenario.get('interbank_lending_reduction', 0.5)

            # Handle both network data (source_bank/target_bank) and time-series data (source_code)
            if 'source_bank' in modified_data.columns and 'target_bank' in modified_data.columns:
                # Network data from AI4Risk plugin - reduce the exposure rows
                # only; a mixed panel frame also carries scalar sources.
                edge_mask = modified_data['source_bank'].notna()
                self._transform_values(modified_data, edge_mask, 'mul', (1 - reduction))
            elif 'source_code' in modified_data.columns:
                # Time-series data - reduce interbank-related sources
                self._transform_values(
                    modified_data,
                    modified_data['source_code'].str.contains('INTERBANK|AI4RISK', na=False),
                    'mul',
                    (1 - reduction),
                )

        elif scenario_type == 'policy_intervention':
            # Apply rate cut (hike if negative). The rate series are quoted in
            # percent, so 1bp = 0.01 percentage points: the previous /10000
            # under-scaled the shock by a factor of 100, and the sign was
            # inverted against the schema ("negative for hikes").
            rate_cut_bps = scenario.get('rate_cut_bps', 0)
            if rate_cut_bps != 0:
                self._transform_values(
                    modified_data,
                    modified_data['source_code'].str.contains('RATE|SOFR|ESTR|EURIBOR|FED_FUNDS', na=False),
                    'add',
                    -rate_cut_bps / 100.0,
                )

            # Apply QE (increase liquidity)
            qe_amount = scenario.get('qe_amount', 0)
            if qe_amount > 0:
                liquidity_boost = qe_amount / 1e12  # Normalize
                self._transform_values(
                    modified_data,
                    modified_data['source_code'].str.contains('RESERVES|M2|LIQUIDITY', na=False),
                    'mul',
                    (1 + liquidity_boost),
                )

        elif scenario_type == 'bank_failure':
            # Simulate bank failure by setting its metrics to critical
            failed_bank = scenario.get('failed_bank_id')
            haircut = scenario.get('exposure_haircut', 0.3)

            if failed_bank and 'bank_id' in modified_data.columns:
                # Failed bank's equity goes to zero
                self._transform_values(
                    modified_data,
                    (modified_data['bank_id'] == failed_bank) &
                    (modified_data['source_code'].str.contains('EQUITY|CAPITAL', na=False)),
                    'mul',
                    0.0,
                )

                # Counterparties take haircut on exposures
                if 'target_bank' in modified_data.columns:
                    self._transform_values(
                        modified_data,
                        modified_data['target_bank'] == failed_bank,
                        'mul',
                        (1 - haircut),
                    )

            # Edge frames (AI4Risk): the failed bank's own claims go to zero and
            # the claims held on it take the declared haircut. Direction is
            # declared, not measured: an edge sourceid -> targetid is read as
            # "sourceid holds a claim on targetid" (the upstream dataset does
            # not document the orientation).
            if failed_bank and 'source_bank' in modified_data.columns and 'target_bank' in modified_data.columns:
                self._transform_values(
                    modified_data,
                    modified_data['source_bank'] == failed_bank,
                    'mul',
                    0.0,
                )
                self._transform_values(
                    modified_data,
                    modified_data['target_bank'] == failed_bank,
                    'mul',
                    (1 - haircut),
                )

        elif scenario_type == 'market_crash':
            # Apply stock market crash
            stock_drop = scenario.get('stock_drop_pct', 0.20)
            vol_spike = scenario.get('volatility_spike', 2.0)

            # Equity price series only: the collection names volatility
            # series STOCK_VIX, so the price mask must exclude the
            # volatility sources or they get a price drop and a spike.
            price_mask = (
                modified_data['source_code'].str.contains('STOCK|SPX|EURO|NIKKEI|HSI|EQUITY', na=False)
                & ~modified_data['source_code'].str.contains('VIX|VOLATILITY|MOVE', na=False)
            )
            self._transform_values(modified_data, price_mask, 'mul', (1 - stock_drop))

            self._transform_values(
                modified_data,
                modified_data['source_code'].str.contains('VIX|VOLATILITY|MOVE', na=False),
                'mul',
                vol_spike,
            )

            # Widen credit spreads
            spread_widening = scenario.get('credit_spread_widening', 0)
            if spread_widening > 0:
                self._transform_values(
                    modified_data,
                    modified_data['source_code'].str.contains('SPREAD|TED|CREDIT', na=False),
                    'add',
                    spread_widening,
                )

        elif scenario_type == 'regional_shock':
            # Apply regional shocks
            region_shocks = scenario.get('regional_shocks', [])
            if 'region' in modified_data.columns:
                for shock in region_shocks:
                    region = shock['region']
                    magnitude = shock['magnitude']
                    self._transform_values(
                        modified_data,
                        modified_data['region'] == region,
                        'mul',
                        (1 + magnitude),
                    )
            elif region_shocks:
                # Declared, not silent: the collection payload carries no
                # region column, so a regional shock cannot be located on it.
                logger.warning(
                    "regional_shock requested but the payload has no 'region' column; "
                    "no regional shock was applied"
                )

        elif scenario_type == 'sovereign_crisis':
            # Sovereign debt crisis
            spread_widening = scenario.get('sovereign_spread_widening', 0.04)
            self._transform_values(
                modified_data,
                modified_data['source_code'].str.contains('BOND|YIELD|10Y|2Y', na=False),
                'add',
                spread_widening,
            )

            # Banking stress from sovereign exposure
            banking_stress = scenario.get('banking_stress', {}) or {}
            deposit_flight = banking_stress.get('deposit_flight', 0)
            if deposit_flight > 0 and 'bank_id' in modified_data.columns:
                self._transform_values(
                    modified_data,
                    modified_data['source_code'].str.contains('DEPOSIT', na=False),
                    'mul',
                    (1 - deposit_flight),
                )

        elif scenario_type == 'commodity_shock':
            # Oil/commodity price shock
            oil_increase = scenario.get('oil_price_increase', 0)
            if oil_increase > 0:
                self._transform_values(
                    modified_data,
                    modified_data['source_code'].str.contains('OIL|WTI|BRENT', na=False),
                    'mul',
                    (1 + oil_increase),
                )

            # Inflation impact
            inflation_spike = scenario.get('inflation_spike', 0)
            if inflation_spike > 0:
                self._transform_values(
                    modified_data,
                    modified_data['source_code'].str.contains('CPI|HICP|INFLATION', na=False),
                    'add',
                    inflation_spike,
                )

        elif scenario_type == 'operational_risk':
            # Cyber attack or operational disruption
            market_disruption = scenario.get('market_disruption', {}) or {}
            confidence_shock = market_disruption.get('confidence_shock', 0.15)
            self._transform_values(
                modified_data,
                modified_data['source_code'].str.contains('VIX|VOLATILITY', na=False),
                'mul',
                (1 + confidence_shock),
            )

        elif scenario_type == 'combined':
            # Recurse into every applicable named scenario. The explicit
            # ``type`` override terminates the recursion.
            for sub_scenario_type in self._SCENARIO_TYPE_KEYS:
                if any(key in scenario for key in self._SCENARIO_TYPE_KEYS[sub_scenario_type]):
                    sub_scenario = {**scenario, 'type': sub_scenario_type}
                    modified_data = self.apply_scenario(modified_data, sub_scenario)

        logger.info(f"Scenario applied: {scenario_type}")
        return modified_data

    def _load_model(self, model_path: str) -> torch.nn.Module:
        """Load trained PyTorch model."""
        checkpoint = safe_torch_load(model_path, map_location=self.device)

        # Get config from checkpoint
        config = checkpoint.get('config', {})
        self.model_config = config
        self.sequence_length = config.get('sequence_length', self.config.get('sequence_length', 30))
        self.source_stats = checkpoint.get('source_stats', {}) or {}
        self.sources = checkpoint.get('sources', []) or []
        self.source_to_id = {src: idx for idx, src in enumerate(self.sources)}
        # The grain the checkpoint's statistics are keyed at. This engine groups
        # its payload by feed, so a checkpoint that standardizes per series has
        # no entry for a feed label: the sequence is then normalized from its own
        # observed values, and that mismatch is reported rather than passed
        # through as if the two grains were the same thing.
        self.stats_grain = str(checkpoint.get('stats_grain', 'feed'))
        self._stats_grain_mismatch_warned = False

        return self._build_model_from_checkpoint(checkpoint)

    def _build_model_from_checkpoint(self, checkpoint: Dict[str, Any]) -> torch.nn.Module:
        """Reconstruct the architecture a checkpoint dict describes and load it.

        Shared by the primary checkpoint and any ensemble members beside it,
        so a member is loaded through exactly the path the primary is.
        """
        from backend.modules.engine.multi_scale_trainer import MultiScaleTemporalAttentionModel

        config = checkpoint.get('config', {})
        sources = checkpoint.get('sources', []) or self.sources or []
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

    def _load_ensemble_members(self) -> List[torch.nn.Module]:
        """Load ``ensemble_member_*.pt`` checkpoints beside the primary model.

        Written by :func:`backend.modules.engine.trainer.train_ensemble` when a
        training job declares ``ensemble_size >= 2``. Members exist solely for
        the aleatoric/epistemic decomposition
        (:mod:`backend.modules.engine.uncertainty`): the point score stays the
        primary frozen model's, and a member that fails to load shrinks the
        ensemble loudly (logged, and the decomposition reports the real member
        count) rather than silently pretending to a size it does not have.
        """
        members: List[torch.nn.Module] = []
        directory = Path(self.model_path).parent
        for path in sorted(directory.glob('ensemble_member_*.pt')):
            try:
                checkpoint = safe_torch_load(str(path), map_location=self.device)
                member = self._build_model_from_checkpoint(checkpoint)
                member.eval()
                members.append(member)
            except Exception as exc:  # noqa: BLE001 - a broken member shrinks the ensemble, it does not kill the prediction
                logger.error("Skipping unloadable ensemble member %s: %s", path, exc)
        if members:
            logger.info(
                "Loaded %d ensemble member(s) beside %s; the uncertainty "
                "decomposition is measurable for this checkpoint",
                len(members), self.model_path,
            )
        return members

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

        Predictions come back grouped by series (``series_id`` when the payload
        carries one, else the feed's ``source_code``) and time-ordered within
        each group; ``boundaries`` records the seam between consecutive series
        so those seams are never differenced as if they were observations.

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
        series_ids: List[str] = []
        source_order: List[str] = []
        group_sizes: List[int] = []
        truncated: Dict[str, int] = {}
        stats_provenance: Dict[str, str] = {}
        embedding_provenance: Dict[str, str] = {}
        dropped_for_history = 0
        dropped_no_values = 0

        # Group at the grain the payload carries. A panel feed (``series_id``
        # present) is scored per entity; a feed without a per-entity identity
        # keeps its feed grain. This must match the grain the checkpoint's
        # statistics were keyed at -- scoring a panel as one interleaved series
        # is the defect L-43 named.
        group_col = 'series_id' if 'series_id' in input_data.columns else 'source_code'
        stats_grain = str(getattr(self, 'stats_grain', 'feed'))

        for raw_series, group in working.groupby(group_col, sort=True):
            series = str(raw_series)
            source_code = (
                str(group['source_code'].iloc[0])
                if 'source_code' in group.columns and not group.empty
                else series
            )
            ordered = group.sort_values('Date') if 'Date' in group.columns else group
            # Per-series selection: on a joined panel frame a 'Close' column
            # always exists (filled by the OHLC series), so a frame-wide
            # membership test reads an all-NaN column for value-only series
            # and the degenerate zero input scores as a plausible-looking
            # value. Select on the values, not the schema.
            value_column = select_value_column(ordered)
            if value_column is None:
                dropped_no_values += int(ordered.shape[0])
                logger.warning(
                    "Risk series: series %s has no usable value column (Close/Value); skipped",
                    series,
                )
                continue

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
                truncated[series] = int(values.size - step_cap)
                values = values[-step_cap:]
                ordered = ordered.iloc[-step_cap:]

            if values.size <= sequence_length:
                dropped_for_history += int(values.size)
                logger.warning(
                    "Risk series: series %s has %d row(s), too few for a %d-step window",
                    series,
                    values.size,
                    sequence_length,
                )
                continue

            # Normalise at the grain the checkpoint's statistics were keyed at:
            # per series for a series-grain checkpoint, per feed for a
            # feed-grain one. Looking up the wrong grain standardises an entity
            # with a scale that is not its own (the 10^2 entity scored at 10^6).
            stats_key = series if stats_grain == 'series' else source_code
            _, stats = self._prepare_sequence(values, stats_key)
            stats_provenance[series] = (
                "checkpoint" if self.source_stats.get(stats_key) else "payload_window"
            )
            mean = float(stats.get('mean', 0.0))
            std = float(stats.get('std', 1.0)) or 1.0
            normalized = (values - mean) / std
            # Impute unobserved entries at the standardised mean rather than
            # carrying the previous value forward.
            normalized = np.where(np.isfinite(normalized), normalized, 0.0)
            # Same clipping law as the training dataset builder: the windows
            # below are model inputs, and the backtest's derived targets are
            # clipped to the same range, so the scored space matches the trained
            # space.
            normalized = np.clip(
                normalized, -STANDARDIZED_VALUE_CLIP, STANDARDIZED_VALUE_CLIP
            )

            windows = np.lib.stride_tricks.sliding_window_view(normalized, sequence_length)
            # The model's per-source embedding is keyed by the feed, not the
            # entity; the entity's scale is carried by the normalisation above.
            # The fallback id is not an untrained slot: with an
            # enumerate()-built source map, id 0 is also the first trained
            # feed's embedding, so a fallback feed's scores carry the wrong
            # per-source component. Record that next to the stats provenance
            # instead of leaving it to the log.
            source_id = self._map_source_id(source_code)
            if not self.source_to_id or source_code not in self.source_to_id:
                embedding_provenance[source_code] = "fallback_id_0"
            else:
                embedding_provenance[source_code] = "trained"
            scores = self._score_windows(windows, source_id, window_batch)

            # Row i of `windows` ends at index i + sequence_length - 1, and the
            # model was trained to predict the row AFTER the window end
            # (target = normalized[i + window]). `row_offset` therefore marks
            # the row the window ends on, and `predicted_row_offset` marks the
            # row the score is a prediction FOR -- the caller-frame position of
            # the next row within the same series, or -1 for each series's
            # final window, whose predicted row lies beyond the series's span
            # and must never resolve into the next series's rows.
            ends = np.arange(sequence_length - 1, values.size)
            row_offsets = np.asarray(ordered['__row_offset'])
            next_positions = ends + 1
            predicted_row_offsets = np.where(
                next_positions < values.size,
                row_offsets[np.minimum(next_positions, values.size - 1)],
                -1,
            )
            frame = pd.DataFrame({
                'source': source_code,
                'series': series,
                'row_offset': row_offsets[ends],
                'predicted_row_offset': predicted_row_offsets,
                'risk_score': scores,
                'prediction': scores * std + mean,
            })
            if 'Date' in ordered.columns:
                frame['Date'] = np.asarray(ordered['Date'])[ends]

            dropped_for_history += sequence_length - 1
            frames.append(frame)
            series_ids.append(series)
            if source_code not in source_order:
                source_order.append(source_code)
            group_sizes.append(int(frame.shape[0]))

        if not frames:
            raise SchemaValidationError(
                "No series in the payload has enough history for a per-timestep risk series",
                context={
                    "sequence_length": sequence_length,
                    "max_steps": step_cap,
                    "rows": int(input_data.shape[0]),
                },
            )

        optimistic = sorted(
            series
            for series, origin in stats_provenance.items()
            if origin == "payload_window"
        )
        if optimistic:
            logger.warning(
                "Risk series normalisation for %s came from the evaluated window rather "
                "than the checkpoint, so metrics on those series are optimistic: the "
                "normalisation saw the future",
                optimistic,
            )

        return RiskSeriesResult(
            frame=pd.concat(frames, ignore_index=True),
            boundaries=[int(value) for value in boundaries_from_group_sizes(group_sizes)],
            sources=source_order,
            series_ids=series_ids,
            n_dropped_for_history=int(dropped_for_history),
            truncated=truncated,
            stats_provenance=stats_provenance,
            embedding_provenance=embedding_provenance,
            batch_size=window_batch,
            max_steps=step_cap,
            n_dropped_no_values=int(dropped_no_values),
        )

    def _score_windows(
        self,
        windows: np.ndarray,
        source_id: int,
        batch_size: int,
        model: Optional[torch.nn.Module] = None,
    ) -> np.ndarray:
        """Run a frozen model over pre-normalised windows, in batches.

        ``model`` defaults to the primary checkpoint; ensemble members are
        scored through the identical path so the decomposition compares
        members on exactly the windows and normalisation the point score uses.
        """
        active = model if model is not None else self.model
        total = int(windows.shape[0])
        scores = np.empty(total, dtype=float)
        active.eval()
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
                outputs = active(inputs, source_ids)
                flat = outputs.detach().cpu().numpy().astype(float).reshape(chunk.shape[0], -1)
                scores[start:start + chunk.shape[0]] = flat[:, 0]
        return scores

    def _score_windows_multi(
        self,
        windows: np.ndarray,
        source_ids: np.ndarray,
        batch_size: int,
    ) -> np.ndarray:
        """Run the frozen model over pre-normalised windows, rows carrying their
        own source id.

        The cross-source batch of :meth:`_predict_single_batched`: row ``i`` is
        scored exactly as the serial path scores it — the same normalised
        window, the same source embedding id, the same no-grad eval pass —
        with no interaction between rows (the model attends within a window
        only). Row order is preserved, so callers regroup by source exactly as
        the serial loop did.
        """
        total = int(windows.shape[0])
        scores = np.empty(total, dtype=float)
        ids = np.asarray(source_ids, dtype=np.int64)
        if ids.shape[0] != total:
            raise ValueError(
                f"source_ids length {ids.shape[0]} does not match window count {total}"
            )
        self.model.eval()
        with torch.no_grad():
            for start in range(0, total, batch_size):
                chunk = np.asarray(windows[start:start + batch_size], dtype=np.float32)
                inputs = torch.FloatTensor(chunk).to(self.device)
                chunk_ids = torch.from_numpy(
                    ids[start:start + chunk.shape[0]].astype(np.int64)
                ).reshape(-1, 1).to(self.device)
                outputs = self.model(inputs, chunk_ids)
                flat = outputs.detach().cpu().numpy().astype(float).reshape(chunk.shape[0], -1)
                scores[start:start + chunk.shape[0]] = flat[:, 0]
        return scores

    def _conformal_fit_from_scores(
        self,
        residual_targets: np.ndarray,
        scores: np.ndarray,
        final_score: float,
        alpha: float = 0.1,
    ) -> tuple:
        """Fit the split-conformal interval on batched calibration scores.

        The tail of :meth:`_conformal_interval` with the scoring step already
        done: same calibrator, same residual evidence, same interval rule, so
        a source's bounds are identical to the serial path's for the same
        windows.
        """
        from backend.modules.engine.conformal import SplitConformalCalibrator

        calibrator = SplitConformalCalibrator(alpha=alpha)
        calibrator.fit(residual_targets, scores[: residual_targets.size])
        interval = calibrator.interval(float(final_score))
        return interval.lower, interval.upper, f"split_conformal_alpha_{alpha}"


    def _predict_single(self, input_data: pd.DataFrame) -> PredictionResult:
        """Predict for single entity.

        Scores every source through the batched path (one forward pass over
        all sources' final windows, one over all held-out calibration
        windows) and degrades to the per-source serial path on any failure —
        slow, never different: both paths share the same normalisation,
        clipping, calibration windows, interval fitting and assembly.
        """
        if self._batch_inference:
            try:
                return self._predict_single_batched(input_data)
            except Exception as exc:  # noqa: BLE001 - degrade to slow, never to different
                logger.warning(
                    "Batched source inference unavailable (%s); scoring per source", exc
                )
        return self._predict_single_serial(input_data)


    def _predict_single_serial(self, input_data: pd.DataFrame) -> PredictionResult:
        """Predict for single entity (per-source serial scoring).

        The reference implementation: every source is prepared, scored and
        calibrated in its own loop. :meth:`_predict_single_batched` must
        reproduce this result; ``test_batched_inference_equivalence.py`` pins
        the equality, and :meth:`_predict_single` falls back to this path
        whenever the batched path raises.
        """

        # Group by source

        # Pass 1: score every source and collect the regime inputs. The
        # per-source regime nowcast used to run inside this loop, paying a
        # Python-looped (T, K=2) EM fit per source; the fits are independent,
        # so they are collected here and run as one batch per window length in
        # pass 2 (docs/LANGUAGE_STRATEGY.md names this the one order-of-
        # magnitude lever left on the prediction path).
        scored_rows = []
        regime_items = []

        for source_code in input_data['source_code'].unique():
            source_data = input_data[input_data['source_code'] == source_code]
            source_data = source_data.sort_values('Date')

            # Get source ID
            source_id = self._map_source_id(source_code)

            # Prepare the sequence from the column that actually holds this
            # source's values. Gaps are preserved rather than forward-filled:
            # carrying a stale observation into the future feeds the model
            # values that were not published at that timestamp, which is
            # look-ahead. A source with no usable value column is skipped,
            # never standardised to a degenerate all-zero input.
            value_column = select_value_column(source_data)
            if value_column is None:
                logger.warning(
                    "Prediction: source %s has no usable value column (Close/Value); skipped",
                    source_code,
                )
                continue
            values = pd.to_numeric(
                source_data[value_column], errors='coerce'
            ).to_numpy(dtype=float)
            sequence, stats = self._prepare_sequence(values, source_code)

            normalized_prediction = self._score_sequence(sequence, source_id)
            denorm_prediction = self._denormalize_prediction(normalized_prediction, stats)

            lower, upper, interval_method = self._conformal_interval(
                values, stats, source_id, normalized_prediction
            )
            if lower is not None:
                conf = (
                    self._denormalize_prediction(lower, stats),
                    self._denormalize_prediction(upper, stats),
                )
            else:
                conf = (None, None)

            # Aleatoric/epistemic decomposition on the same held-out evidence
            # the conformal interval uses. A single-checkpoint engine gets a
            # not-measurable status; an ensemble whose members disagree more
            # on this window than they ever did on the calibration slice gets
            # a refusal, applied in pass 3.
            uncertainty = self._uncertainty_for_source(sequence, values, stats, source_id)

            scored_rows.append(
                (source_code, denorm_prediction, normalized_prediction, interval_method, conf, uncertainty)
            )
            regime_items.append((source_code, values, stats))

        # Pass 2: batched regime nowcast — same labels _regime_label produces,
        # with per-source fallback on any failure (degrades to slow, never to
        # different).
        regime_labels = self._regime_labels_batch(regime_items)

        # Pass 3: assemble (shared with the batched inference path).
        return self._assemble_prediction_result(scored_rows, regime_items, regime_labels)

    def _predict_single_batched(self, input_data: pd.DataFrame) -> PredictionResult:
        """Predict for single entity, scoring across sources in batched passes.

        Same contract as :meth:`_predict_single_serial`, with the per-source
        torch calls collected into two batched passes:

        * every source's final window in one pass (per-row source id, so the
          per-source embedding each serial forward used is the row's own);
        * every source's held-out calibration windows in one pass, rows
          grouped per source in source order, so each source's residual array
          is byte-identical to the serial one and the per-source conformal
          fit sees exactly the serial evidence.

        Per-source preparation (value-column selection, the degenerate
        standardisation guard, gap handling, clipping), the interval fitting
        and the uncertainty decomposition run unchanged; a source that cannot
        support a calibration window keeps the serial
        ``insufficient_history_for_calibration`` method. Any failure anywhere
        raises and :meth:`_predict_single` falls back to the serial path —
        never to a different number.
        """
        scored_rows = []
        regime_items = []

        # Pass 1a: per-source preparation (identical rules to the serial loop).
        prepared = []
        for source_code in input_data['source_code'].unique():
            source_data = input_data[input_data['source_code'] == source_code]
            source_data = source_data.sort_values('Date')

            source_id = self._map_source_id(source_code)

            value_column = select_value_column(source_data)
            if value_column is None:
                logger.warning(
                    "Prediction: source %s has no usable value column (Close/Value); skipped",
                    source_code,
                )
                continue
            values = pd.to_numeric(
                source_data[value_column], errors='coerce'
            ).to_numpy(dtype=float)
            sequence, stats = self._prepare_sequence(values, source_code)
            prepared.append({
                'source_code': source_code,
                'values': values,
                'sequence': sequence,
                'stats': stats,
                'source_id': source_id,
                'calibration': self._calibration_windows(values, stats),
            })

        # Pass 1b: one batched forward over every source's final window.
        if prepared:
            final_windows = np.stack([p['sequence'].numpy() for p in prepared])
            source_ids = np.array([p['source_id'] for p in prepared], dtype=np.int64)
            point_scores = self._score_windows_multi(final_windows, source_ids, 512)
        else:
            point_scores = np.empty(0, dtype=float)

        # Pass 1c: one batched forward over every source's held-out
        # calibration windows; rows stay grouped per source, in source order.
        window_blocks = []
        block_meta = []
        for p, final_score in zip(prepared, point_scores):
            p['final_score'] = float(final_score)
            calibration = p['calibration']
            if calibration is None:
                p['interval'] = (None, None, "insufficient_history_for_calibration")
                continue
            cal_windows, residual_targets = calibration
            window_blocks.append(cal_windows)
            block_meta.append((cal_windows.shape[0], residual_targets, p))

        if window_blocks:
            stacked = np.concatenate(window_blocks, axis=0)
            stacked_ids = np.concatenate([
                np.full(count, p['source_id'], dtype=np.int64)
                for count, _, p in block_meta
            ])
            window_scores = self._score_windows_multi(stacked, stacked_ids, 512)
            offset = 0
            for count, residual_targets, p in block_meta:
                scores = window_scores[offset:offset + count]
                offset += count
                lower, upper, method = self._conformal_fit_from_scores(
                    residual_targets, scores, p['final_score']
                )
                p['interval'] = (lower, upper, method)
        for p in prepared:
            p.setdefault('interval', (None, None, "insufficient_history_for_calibration"))

        # Pass 1d: per-source denormalisation, interval bounds and the
        # uncertainty decomposition (unchanged from the serial path).
        for p in prepared:
            normalized_prediction = p['final_score']
            denorm_prediction = self._denormalize_prediction(normalized_prediction, p['stats'])
            lower, upper, interval_method = p['interval']
            if lower is not None:
                conf = (
                    self._denormalize_prediction(lower, p['stats']),
                    self._denormalize_prediction(upper, p['stats']),
                )
            else:
                conf = (None, None)
            uncertainty = self._uncertainty_for_source(
                p['sequence'], p['values'], p['stats'], p['source_id']
            )
            scored_rows.append(
                (p['source_code'], denorm_prediction, normalized_prediction,
                 interval_method, conf, uncertainty)
            )
            regime_items.append((p['source_code'], p['values'], p['stats']))

        # Pass 2: batched regime nowcast (same as the serial path).
        regime_labels = self._regime_labels_batch(regime_items)

        # Pass 3: assemble (shared with the serial path).
        return self._assemble_prediction_result(scored_rows, regime_items, regime_labels)

    def _assemble_prediction_result(
        self, scored_rows: list, regime_items: list, regime_labels: Dict[str, tuple]
    ) -> PredictionResult:
        """Assemble the PredictionResult from scored rows and regime labels.

        Shared by the serial and batched inference paths: the assembly, the
        uncertainty summary, the executive summary and the metrics are one
        computation on both sides, so the two paths cannot drift apart.
        """
        # Pass 3: assemble.
        predictions_list: List[Dict[str, Any]] = []
        confidence_intervals: Dict[str, tuple] = {}
        uncertainty_records: Dict[str, Dict[str, Any]] = {}
        for (
            source_code,
            denorm_prediction,
            normalized_prediction,
            interval_method,
            conf,
            uncertainty,
        ) in scored_rows:
            regime, regime_method = regime_labels[source_code]
            uncertainty_records[source_code] = uncertainty
            if uncertainty.get('status') == 'refused':
                # An unreliable prediction is absence, not a number: the score,
                # the point prediction and the interval are all withheld, and
                # the row says why. Downstream consumers (risk-score
                # persistence, summary statistics) skip null scores by design.
                denorm_prediction = float('nan')
                normalized_prediction = float('nan')
                conf = (None, None)
                interval_method = 'refused_uncertainty_assessment'
            predictions_list.append({
                'source': source_code,
                'prediction': denorm_prediction,
                'risk_score': normalized_prediction,
                # Split-conformal interval over held-out rolling residuals of
                # this source, in the model's standardized space, denormalized
                # with the same statistics as the point score. None when the
                # payload cannot support a calibration window -- reported as
                # absent, never as a zero-width or invented interval.
                'confidence_lower': conf[0],
                'confidence_upper': conf[1],
                'confidence_method': interval_method,
                'regime': regime,
                'regime_method': regime_method,
                # Uncertainty decomposition (modules/engine/uncertainty.py):
                # measured only when independently trained ensemble members
                # exist beside the checkpoint; otherwise the status says the
                # split is not measurable and the variance fields are absent.
                'uncertainty_status': uncertainty.get('status'),
                'uncertainty_reasons': (
                    "; ".join(uncertainty.get('reasons') or []) or None
                ),
                'aleatoric_var': uncertainty.get('aleatoric'),
                'epistemic_var': uncertainty.get('epistemic'),
                'epistemic_share': uncertainty.get('epistemic_share'),
            })
            confidence_intervals[source_code] = conf

        predictions_df = pd.DataFrame(predictions_list)

        # Generate executive summary
        if not predictions_df.empty:
            avg_risk = float(predictions_df['risk_score'].mean())
            max_risk = float(predictions_df['risk_score'].max())
            min_risk = float(predictions_df['risk_score'].min())
        else:
            avg_risk = max_risk = min_risk = 0.0

        # A refused source carries no score (NaN), and pandas skips NaN in
        # these reductions -- so the averages describe the assessed sources.
        # When every source was refused there is no average to print, and
        # printing 0.000 would be a number the run did not produce.
        def _fmt_score(value: float) -> str:
            return f"{value:+.3f}" if np.isfinite(value) else "n/a (no source carried a score)"

        n_refused = sum(
            1 for record in uncertainty_records.values() if record.get('status') == 'refused'
        )
        refused_sources = sorted(
            source for source, record in uncertainty_records.items()
            if record.get('status') == 'refused'
        )
        statuses: Dict[str, int] = {}
        for record in uncertainty_records.values():
            key = str(record.get('status'))
            statuses[key] = statuses.get(key, 0) + 1
        uncertainty_summary = {
            'mode': 'deep_ensemble' if self.ensemble_members else 'single_model',
            'n_members': len(self.ensemble_members) + 1,
            'statuses': statuses,
            'refused_sources': refused_sources,
        }
        if self.ensemble_members:
            uncertainty_line = (
                f"deep ensemble, {len(self.ensemble_members) + 1} members: "
                f"{statuses.get('assessed', 0)} source(s) assessed reliable, "
                f"{n_refused} refused. A refusal means the members disagreed on "
                "this window more than they ever did on the calibration slice "
                "(epistemic spike -- the model is extrapolating), or model "
                "ignorance dominates the variance; the withheld score is "
                "absence, not a number. Per-source variances are in the "
                "prediction rows."
            )
        else:
            uncertainty_line = (
                "not measurable with the single frozen checkpoint this engine "
                "loaded: the aleatoric/epistemic split needs independently "
                "trained members (train with ensemble_size >= 2). No "
                "decomposition is approximated in its place."
            )

        # What the summary says about intervals must match what the rows
        # carry: count the per-source confidence methods actually recorded
        # rather than asserting a blanket state.
        if not predictions_df.empty and 'confidence_method' in predictions_df.columns:
            methods = predictions_df['confidence_method'].astype(str)
            n_with_intervals = int(methods.str.startswith('split_conformal').sum())
            method_counts = {m: int(c) for m, c in methods.value_counts().items()}
        else:
            n_with_intervals = 0
            method_counts = {}

        executive_summary = f"""
LIQUIDITY STRESS FORECAST SUMMARY

Overall model score: {_fmt_score(avg_risk)} (standardized units, uncalibrated)
Maximum model score: {_fmt_score(max_risk)} (standardized units, uncalibrated)
Data Sources Analyzed: {len(predictions_df)}
Sources refused by uncertainty assessment: {n_refused}{f" ({', '.join(refused_sources)})" if refused_sources else ""}

The model score is a one-step-ahead prediction of each indicator's
standardized next value. It is not a probability, it is not bounded to
0-100, and its direction of stress depends on the indicator; no calibrated
mapping to a risk level exists yet (README.md, Scoring and validation).

KEY FINDINGS:
{self._generate_key_findings(predictions_df)}

INTERVALS AND ATTRIBUTION:
Prediction intervals are split-conformal, fitted per source on this
payload's own held-out rolling residuals: {n_with_intervals} of {len(predictions_df)} source(s) carry
one (confidence methods: {method_counts}). Sources whose history cannot
support a calibration window report null bounds and name the reason in
confidence_method; no interval is invented or zero-width.
Local feature attribution is not reported: SubgraphX requires a liability
network and a game value this payload does not carry, and nothing is
approximated in its place.

UNCERTAINTY DECOMPOSITION:
{uncertainty_line}
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
            executive_summary=executive_summary,
            uncertainty_summary=uncertainty_summary
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
        if (
            not stats
            and self.source_stats
            and str(getattr(self, 'stats_grain', 'feed')) == 'series'
            and not getattr(self, '_stats_grain_mismatch_warned', False)
        ):
            self._stats_grain_mismatch_warned = True
            logger.warning(
                "Checkpoint standardizes at series-grain but this payload is "
                "scored per feed ('%s'): no series' statistics describe a whole "
                "feed, so the window is normalized from its own observed values. "
                "Score panel feeds per series to use the checkpoint's statistics.",
                source_code,
            )

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
            normalized = np.where(observed, normalized, 0.0)
            # Same clipping law as the training dataset builder: a tiny-but-real
            # std would otherwise feed a z of 1e4-1e10 into a model whose input
            # space was bounded to +-STANDARDIZED_VALUE_CLIP at train time.
            normalized = np.clip(normalized, -STANDARDIZED_VALUE_CLIP, STANDARDIZED_VALUE_CLIP)
            normalized = normalized.astype(np.float32)
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

    def _regime_label(
        self, values: np.ndarray, stats: Dict[str, float]
    ) -> tuple:
        """Nowcast the volatility regime of one source with the Student-t HMM.

        The regime label is what ``mixture_of_experts`` was missing and what
        the census queued: a live, per-source state from a fitted model rather
        than a declared one. The stress state is identified as the
        higher-variance state -- a naming convention over fitted parameters,
        not a supervised label. Too little history returns None: an unnamed
        regime, never a guessed one.
        """
        finite = values[np.isfinite(values)]
        if finite.size < 40:
            return None, "insufficient_history_for_regime"
        mean = float(stats.get('mean', finite.mean()))
        std = float(stats.get('std', finite.std())) or 1.0
        standardized = ((values - mean) / std)[np.isfinite(values)].reshape(-1, 1)
        try:
            from backend.modules.engine.hidden_markov import StudentTHMM

            hmm = StudentTHMM(n_states=2, seed=0)
            hmm.fit(standardized)
            states = hmm.viterbi(standardized)
            variances = np.array(
                [standardized[states == k, 0].var() if (states == k).any() else 0.0
                 for k in range(2)]
            )
            stress_state = int(np.argmax(variances))
            label = "stress" if int(states[-1]) == stress_state else "calm"
            return label, "student_t_hmm_higher_variance_state"
        except Exception as exc:  # noqa: BLE001 - regime is advisory, absence is honest
            logger.warning("Regime labelling unavailable: %s", exc)
            return None, f"regime_unavailable:{type(exc).__name__}"

    def _regime_labels_batch(
        self, items: List[tuple]
    ) -> Dict[str, tuple]:
        """Nowcast every source's regime with one batched fit per window length.

        Contract: for each ``(source_code, values, stats)`` item this returns
        exactly what :meth:`_regime_label` returns for the same input — the
        same standardisation, the same 40-observation floor, the same
        higher-variance-state naming, the same honest ``None`` on absence.
        The only difference is who pays the per-timestep Python overhead:
        ``fit_viterbi_student_t_batch`` runs one ``(n, T, K)`` recursion per
        length group instead of ``n`` separate ``(T, K)`` ones.

        Degradation paths, all to the per-source method, never to a guess:
        sequences the batch declines (degenerate seeding) fall back
        individually; a length group that raises falls back wholesale.
        """
        results: Dict[str, tuple] = {}
        # (source_code, values, stats, standardized-or-None) per item
        windows: List[tuple] = []
        groups: Dict[int, List[int]] = {}

        for source_code, values, stats in items:
            finite = values[np.isfinite(values)]
            if finite.size < 40:
                results[source_code] = (None, "insufficient_history_for_regime")
                windows.append((source_code, values, stats, None))
                continue
            mean = float(stats.get('mean', finite.mean()))
            std = float(stats.get('std', finite.std())) or 1.0
            standardized = ((values - mean) / std)[np.isfinite(values)].reshape(-1, 1)
            groups.setdefault(int(len(standardized)), []).append(len(windows))
            windows.append((source_code, values, stats, standardized))

        from backend.modules.engine.hidden_markov import fit_viterbi_student_t_batch

        for member_indexes in groups.values():
            try:
                stacked = np.stack(
                    [windows[index][3] for index in member_indexes]
                )
                fit = fit_viterbi_student_t_batch(stacked)
                fallback = set(fit.fallback_indices)
                for position, window_index in enumerate(member_indexes):
                    source_code, values, stats, standardized = windows[window_index]
                    if position in fallback:
                        results[source_code] = self._regime_label(values, stats)
                        continue
                    states = fit.states[position]
                    variances = np.array(
                        [
                            standardized[states == k, 0].var()
                            if (states == k).any()
                            else 0.0
                            for k in range(2)
                        ]
                    )
                    stress_state = int(np.argmax(variances))
                    label = "stress" if int(states[-1]) == stress_state else "calm"
                    results[source_code] = (
                        label,
                        "student_t_hmm_higher_variance_state",
                    )
            except Exception as exc:  # noqa: BLE001 - regime is advisory, absence is honest
                logger.warning(
                    "Batched regime labelling unavailable (%s); fitting per source", exc
                )
                for window_index in member_indexes:
                    source_code, values, stats, _ = windows[window_index]
                    results[source_code] = self._regime_label(values, stats)

        return results

    def _calibration_windows(
        self,
        values: np.ndarray,
        stats: Dict[str, float],
        calibration_window: int = 120,
        minimum_window: int = 30,
    ) -> Optional[tuple]:
        """Held-out rolling windows and their next-value targets, standardised.

        The shared evidence slice for both per-source calibrations: the
        split-conformal interval fits its residual quantile on it, and the
        ensemble decomposition (when members exist) calibrates its aleatoric
        term and builds its epistemic reference on exactly the same windows.
        Returns ``(cal_windows, residual_targets)`` or ``None`` when the
        payload cannot support a calibration window -- absence, never a
        substitute slice.
        """
        finite = values[np.isfinite(values)]
        mean = float(stats.get('mean', finite.mean() if finite.size else 0.0))
        std = float(stats.get('std', finite.std() if finite.size else 1.0)) or 1.0
        normalized = (values - mean) / std
        normalized = np.where(np.isfinite(normalized), normalized, 0.0)
        # Same clipping law as training: these windows are model inputs and the
        # residual targets are the calibrated quantities, so both must live in
        # the clipped standardized space.
        normalized = np.clip(normalized, -STANDARDIZED_VALUE_CLIP, STANDARDIZED_VALUE_CLIP)

        sequence_length = int(self.sequence_length)
        n_windows = normalized.size - sequence_length
        if n_windows < minimum_window + 1:
            return None

        holdout = min(calibration_window, n_windows - 1)
        windows = np.lib.stride_tricks.sliding_window_view(normalized, sequence_length)
        first = n_windows - holdout
        cal_windows = windows[first:n_windows]
        # target for window i (ending at i+L-1) is normalized[i+L]
        residual_targets = normalized[first + sequence_length: first + sequence_length + cal_windows.shape[0]]
        if residual_targets.size < minimum_window:
            return None
        return cal_windows, residual_targets

    def _conformal_interval(
        self,
        values: np.ndarray,
        stats: Dict[str, float],
        source_id: int,
        final_score: float,
        calibration_window: int = 120,
        minimum_window: int = 30,
        alpha: float = 0.1,
    ) -> tuple:
        """Split-conformal interval for the point score, per source.

        Residuals come from rolling the frozen model over a held-out tail of
        this source's own standardized series and comparing each window's
        score with the observed next value -- the calibration set is disjoint
        from the window the point score uses. Returns bounds in standardized
        space and the method string, or (None, None, reason) when the payload
        cannot support a calibration window.
        """
        calibration = self._calibration_windows(
            values, stats, calibration_window=calibration_window, minimum_window=minimum_window
        )
        if calibration is None:
            return None, None, "insufficient_history_for_calibration"
        cal_windows, residual_targets = calibration

        scores = self._score_windows(cal_windows, source_id, 256)

        from backend.modules.engine.conformal import SplitConformalCalibrator

        calibrator = SplitConformalCalibrator(alpha=alpha)
        calibrator.fit(residual_targets, scores[: residual_targets.size])
        interval = calibrator.interval(float(final_score))
        return interval.lower, interval.upper, f"split_conformal_alpha_{alpha}"

    def _uncertainty_for_source(
        self,
        sequence: Any,
        values: np.ndarray,
        stats: Dict[str, float],
        source_id: int,
    ) -> Dict[str, Any]:
        """Aleatoric/epistemic decomposition for one source's point score.

        Computable only with two or more independently trained members
        (``ensemble_member_*.pt`` beside the checkpoint, written by
        :func:`backend.modules.engine.trainer.train_ensemble`). A single
        frozen model's epistemic term is identically zero by construction,
        and a reliability flag built on that zero would understate model
        ignorance -- the wrong direction to be wrong in (see
        :mod:`backend.modules.engine.uncertainty`). So a single checkpoint
        reports the decomposition *not measurable* rather than approximated.

        When members exist, the decomposition is calibrated on exactly the
        held-out windows the split-conformal interval uses
        (:meth:`_calibration_windows`): aleatoric variance from the members'
        residuals on that slice, the epistemic reference from the members'
        disagreement across it. The final window is then decomposed and
        assessed; ``assess_uncertainty`` decides reliability (epistemic spike
        over the calibrated ceiling, optional epistemic-share bound, and --
        because a gate that cannot measure should not certify -- a missing
        reference counts as a failure). A refused source's prediction is
        treated downstream as absence, never as a number.

        The point score itself stays the primary frozen model's: the
        decomposition describes the ensemble's spread around that score and
        drives the reliability verdict, but it does not silently replace the
        contracted prediction with an ensemble mean.
        """
        if not self.ensemble_members:
            return {
                "status": "not_measurable_single_model",
                "n_members": 1,
                "reason": (
                    "one frozen checkpoint: the epistemic term of the law of "
                    "total variance is identically zero by construction, so no "
                    "reliability verdict is derived from it. Train with "
                    "ensemble_size >= 2 (trainer.train_ensemble) to enable the "
                    "decomposition."
                ),
            }

        calibration = self._calibration_windows(values, stats)
        if calibration is None:
            return {
                "status": "insufficient_history_for_decomposition",
                "n_members": len(self.ensemble_members) + 1,
            }
        cal_windows, cal_targets = calibration

        from backend.modules.engine.uncertainty import (
            DeepEnsemble,
            EpistemicReference,
            assess_uncertainty,
        )

        members = [
            _EnsembleMemberAdapter(self, model, source_id)
            for model in (self.model, *self.ensemble_members)
        ]
        ensemble = DeepEnsemble(members)
        ensemble.calibrate_residual_variance(cal_windows, cal_targets)
        reference = EpistemicReference(
            [d.epistemic for d in ensemble.decompose(cal_windows)],
            level=float(self.config.get('epistemic_reference_level', 0.99)),
        )
        final_window = np.asarray(
            sequence.detach().cpu().numpy() if hasattr(sequence, "detach") else sequence,
            dtype=float,
        ).reshape(-1)
        decomposition = ensemble.decompose_one(final_window)
        assessment = assess_uncertainty(
            decomposition,
            reference,
            require_epistemic_reference=True,
            max_epistemic_share=self.config.get('max_epistemic_share'),
        )

        record = decomposition.to_dict()
        record.update({
            "status": "assessed" if assessment.reliable else "refused",
            "reliable": bool(assessment.reliable),
            "epistemic_spiked": bool(assessment.epistemic_spiked),
            "reasons": [str(reason) for reason in assessment.reasons],
            "n_calibration_windows": int(cal_windows.shape[0]),
            "epistemic_reference_threshold": float(reference.threshold),
        })
        return record

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
            scores = predictions_df['risk_score'].dropna()
            findings.append(
                f"- Highest model score: {peak['source']} "
                f"({float(peak['risk_score']):+.3f} standardized units)"
            )
            findings.append(
                f"- Mean model score across {len(valid)} source(s): "
                f"{scores.mean():+.3f} (standardized units; indicators carry "
                f"mixed stress directions, so treat the mean as indicative only)"
            )
        else:
            findings.append("- No valid risk predictions available")

        findings.append(
            "- Per-feature attribution is not reported; prediction intervals "
            "are split-conformal per source where the payload supports a "
            "calibration window (see each row's confidence_method)"
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
