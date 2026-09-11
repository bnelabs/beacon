"""Per-institution systemic risk analysis.

This module was rebuilt on real network mathematics. The previous
implementation scored contagion as ``risk_i * exposure * vulnerability_j`` with
``vulnerability = min(total_exposure / 1e9, 1.0)``, simulated cascades as
``new_risk = current_risk + min(impact / 1e9, 0.5)``, and ranked systemically
important institutions by ``0.4 * risk + 0.4 * min(outgoing / 1e10, 1) + 0.2 *
min(connections / 20, 1)``.

Every constant in those expressions is arbitrary: ``1e9``, ``1e10``, ``20``, the
``0.4/0.4/0.2`` split. They convert dollars and counts into a unitless "risk"
that is then compared against a threshold. Because the scale constants are
chosen rather than derived, the thresholds they feed are not falsifiable -- move
the unit of account from dollars to millions and every institution's score
changes while nothing about the world changed.

What replaces them:

* **Systemic importance** comes from the interbank liability network. When
  endowments (external assets) are supplied, importance is a *contagion index*:
  the increase in total system clearing shortfall caused by wiping out that
  institution's external assets, divided by system-wide liabilities. It is
  measured, not asserted. Without endowments, importance falls back to
  eigenvector centrality of the liability matrix -- still a property of the
  network rather than of a hand-picked scale factor.
* **Contagion paths** come from the Eisenberg-Noe clearing engine in
  :mod:`backend.modules.risk.clearing`, which derives default from the balance
  sheet and conserves payments.
* **A bank's own risk score** is the model's output. It is a latent state and is
  deliberately *not* decomposed into "market", "funding" and "operational"
  components. The previous code produced those three channels as
  ``overall * 0.7 + vol * 0.2 + trend * 0.1`` and ``overall * 0.8 +
  instability * 0.2`` -- re-weighted copies of one number, which conveyed the
  appearance of a decomposition without performing one. Real decomposition
  requires the funding and market layers of the multiplex network, which arrive
  with the data layer.

Balance-sheet inputs
--------------------

Clearing needs two things per institution: a liability matrix (who owes whom)
and an endowment (external assets available to meet obligations). BEACON's model
produces neither -- it scores latent liquidity stress from time series. So
network analysis is performed only when the caller supplies exposures, and
clearing only when it additionally supplies endowments. When they are absent the
analysis says so instead of manufacturing endowments from risk scores, which
would make the clearing output a restatement of the model's own prediction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import torch

from .clearing import (
    ClearingResult,
    NetworkLayer,
    clear_multiplex,
)
from .constants import (
    CRITICAL_RISK_THRESHOLD,
    HIGH_RISK_THRESHOLD,
    RISK_THRESHOLD_HIGH,
    RISK_THRESHOLD_LOW,
    RISK_THRESHOLD_MODERATE,
)
from .fire_sale import FireSaleResult, FireSaleScenario, solve_fire_sale

logger = logging.getLogger(__name__)

__all__ = [
    "BankRiskProfile",
    "MultiBankAnalysis",
    "BankRiskAnalyzer",
    "generate_executive_summary",
    "eigenvector_centrality",
]

# Milestone at which calibrated intervals replace the current placeholder.
CONFIDENCE_METHOD_PENDING = "unavailable:pending-conformal-calibration"


def eigenvector_centrality(
    matrix: np.ndarray,
    tolerance: float = 1e-12,
    max_iterations: int = 1_000,
) -> np.ndarray:
    """Eigenvector centrality of a non-negative influence matrix.

    Used on the liability matrix ``L``, where ``L[i, j]`` is what ``i`` owes
    ``j``. Entry ``i`` of the result measures how much damage ``i`` can pass on,
    weighted recursively by how much damage each of its creditors can pass on.

    Implemented with power iteration rather than pulled from a graph library so
    the convergence behaviour is explicit and testable.

    Args:
        matrix: Square non-negative matrix.
        tolerance: Convergence threshold on the sup-norm change.
        max_iterations: Iteration cap.

    Returns:
        Non-negative vector of unit Euclidean norm. All zeros when the matrix
        carries no weight (an empty network has no central node).
    """
    arr = np.asarray(matrix, dtype=float)
    if arr.ndim != 2 or arr.shape[0] != arr.shape[1]:
        raise ValueError(f"matrix must be square, got shape {arr.shape}")
    n = arr.shape[0]
    if n == 0:
        return np.zeros(0, dtype=float)

    non_negative = np.maximum(arr, 0.0)
    if non_negative.sum() <= 0:
        return np.zeros(n, dtype=float)

    vector = np.full(n, 1.0 / np.sqrt(n))
    for _ in range(max_iterations):
        updated = non_negative @ vector
        norm = float(np.linalg.norm(updated))
        if norm <= tolerance:
            return np.zeros(n, dtype=float)
        updated = updated / norm
        if float(np.max(np.abs(updated - vector))) <= tolerance:
            return updated
        vector = updated

    logger.warning("eigenvector centrality did not converge in %d iterations", max_iterations)
    return vector


def _exposures_to_matrix(
    bank_ids: Sequence[str],
    exposures: Dict[Tuple[str, str], float],
) -> np.ndarray:
    """Build the ``(n, n)`` liability matrix from ``(debtor, creditor) -> amount``."""
    index = {bank_id: position for position, bank_id in enumerate(bank_ids)}
    matrix = np.zeros((len(bank_ids), len(bank_ids)), dtype=float)
    for (debtor, creditor), amount in exposures.items():
        if debtor == creditor:
            continue
        if debtor not in index or creditor not in index:
            raise KeyError(
                f"exposure ({debtor!r}, {creditor!r}) references an institution "
                f"outside the analysed set"
            )
        matrix[index[debtor], index[creditor]] += float(amount)
    return matrix


@dataclass
class BankRiskProfile:
    """Risk profile for a single institution."""

    bank_id: str
    bank_name: str

    risk_score: float
    """Model output. A latent stress state in ``[0, 1]``, not a price."""

    risk_level: str

    systemic_importance: float
    """Contagion index when endowments are known, else eigenvector centrality."""

    systemic_importance_method: str

    network_position: str

    gross_liabilities: float
    gross_claims: float

    confidence_lower: Optional[float]
    confidence_upper: Optional[float]
    confidence_method: str

    top_vulnerabilities: List[str] = field(default_factory=list)
    top_strengths: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "bank_id": self.bank_id,
            "bank_name": self.bank_name,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "systemic_importance": self.systemic_importance,
            "systemic_importance_method": self.systemic_importance_method,
            "network_position": self.network_position,
            "gross_liabilities": self.gross_liabilities,
            "gross_claims": self.gross_claims,
            "confidence_lower": self.confidence_lower,
            "confidence_upper": self.confidence_upper,
            "confidence_method": self.confidence_method,
            "top_vulnerabilities": list(self.top_vulnerabilities),
            "top_strengths": list(self.top_strengths),
            "recommendations": list(self.recommendations),
        }


@dataclass
class MultiBankAnalysis:
    """Analysis across a set of institutions."""

    analysis_date: str
    num_banks: int
    bank_profiles: Dict[str, BankRiskProfile]

    avg_risk: float
    max_risk: float
    num_high_risk: int
    num_critical_risk: int

    network_available: bool
    network_density: float
    liability_matrix: Optional[np.ndarray]

    clearing: Optional[ClearingResult] = None
    """Populated only when endowments were supplied."""

    shock_scenarios: Dict[str, ClearingResult] = field(default_factory=dict)
    """Per-institution clearing result under a total-loss shock to that node."""

    systemic_risk_score: Optional[float] = None
    """Fraction of system liabilities left unpaid at the clearing equilibrium.

    ``None`` when the balance sheet is unknown -- the honest answer, since
    without liabilities and endowments there is no systemic risk number to
    compute.
    """

    fire_sale: Optional[FireSaleResult] = None
    """The coupled fire-sale fixed point, when a scenario was supplied.

    `clearing` above is a single-step answer at *fixed* prices. This is the fixed
    point once forced liquidation is allowed to move them, which is a different and
    generally worse number. `None` means the holdings, prices and capital the
    coupled solver needs were not supplied -- that is missing information, not
    evidence that the feedback is absent, and the two must not be confused.
    """

    def to_dict(self) -> Dict[str, object]:
        return {
            "analysis_date": self.analysis_date,
            "num_banks": self.num_banks,
            "avg_risk": self.avg_risk,
            "max_risk": self.max_risk,
            "num_high_risk": self.num_high_risk,
            "num_critical_risk": self.num_critical_risk,
            "network_available": self.network_available,
            "network_density": self.network_density,
            "systemic_risk_score": self.systemic_risk_score,
            "clearing": self.clearing.to_dict() if self.clearing else None,
            "fire_sale": self.fire_sale.to_dict() if self.fire_sale else None,
            "shock_scenarios": {
                bank_id: result.to_dict()
                for bank_id, result in self.shock_scenarios.items()
            },
            "bank_profiles": {
                bank_id: profile.to_dict()
                for bank_id, profile in self.bank_profiles.items()
            },
        }


class BankRiskAnalyzer:
    """Scores institutions and, when the balance sheet is known, clears them."""

    def __init__(
        self,
        model: torch.nn.Module,
        device: torch.device,
        sequence_length: int,
        source_stats: Dict[str, Dict[str, float]],
        source_to_id: Dict[str, int],
    ) -> None:
        self.model = model
        self.device = device
        self.sequence_length = int(sequence_length)
        self.source_stats = source_stats or {}
        self.source_to_id = source_to_id or {}

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def analyze_multiple_banks(
        self,
        bank_data: Dict[str, pd.DataFrame],
        bank_exposures: Optional[Dict[Tuple[str, str], float]] = None,
        feature_names: Optional[List[str]] = None,
        bank_endowments: Optional[Dict[str, float]] = None,
        fire_sale_scenario: Optional[FireSaleScenario] = None,
    ) -> MultiBankAnalysis:
        """Score every institution, then analyse the network if possible.

        Args:
            bank_data: ``bank_id ->`` time series DataFrame.
            bank_exposures: ``(debtor, creditor) ->`` nominal exposure.
            feature_names: Unused; retained for call-site compatibility.
            bank_endowments: ``bank_id ->`` external assets available to meet
                obligations. Required for clearing.
            fire_sale_scenario: Optional coupled fire-sale scenario. When
                supplied, the clearing above is iterated against the liquidation
                feedback until a fixed point or divergence. Every quantity comes
                from the caller; nothing is defaulted, and the scenario must cover
                exactly the institutions being analysed.

        Returns:
            A :class:`MultiBankAnalysis`. ``systemic_risk_score`` is ``None``
            unless both exposures and endowments are supplied.
        """
        logger.info("Analysing %d institutions", len(bank_data))

        bank_ids = list(bank_data.keys())
        scores: Dict[str, float] = {}
        for bank_id, frame in bank_data.items():
            scores[bank_id] = self._score_bank(bank_id, frame)

        liabilities = None
        network_available = bool(bank_exposures)
        network_density = 0.0
        if network_available:
            liabilities = _exposures_to_matrix(bank_ids, bank_exposures)
            possible = len(bank_ids) * (len(bank_ids) - 1)
            network_density = (
                float(np.count_nonzero(liabilities)) / possible if possible else 0.0
            )

        centrality = (
            eigenvector_centrality(liabilities)
            if liabilities is not None
            else np.zeros(len(bank_ids))
        )

        clearing: Optional[ClearingResult] = None
        shock_scenarios: Dict[str, ClearingResult] = {}
        importance: Dict[str, float] = {}
        importance_method = "eigenvector_centrality"
        systemic_risk_score: Optional[float] = None

        balance_sheet_known = (
            liabilities is not None
            and bank_endowments is not None
            and len(bank_endowments) > 0
        )

        if balance_sheet_known:
            endowments = np.array(
                [float(bank_endowments.get(bank_id, 0.0)) for bank_id in bank_ids],
                dtype=float,
            )
            layer = NetworkLayer(name="interbank", liabilities=liabilities, seniority=0)
            clearing = clear_multiplex([layer], endowments, node_ids=bank_ids)
            importance_method = "contagion_index"

            baseline_shortfall = clearing.total_shortfall
            system_liabilities = float(clearing.nominal_liabilities.sum())
            scale = system_liabilities if system_liabilities > 0 else 1.0

            for position, bank_id in enumerate(bank_ids):
                shocked = endowments.copy()
                shocked[position] = 0.0
                outcome = clear_multiplex([layer], shocked, node_ids=bank_ids)
                shock_scenarios[bank_id] = outcome
                importance[bank_id] = max(
                    0.0, (outcome.total_shortfall - baseline_shortfall) / scale
                )

            systemic_risk_score = (
                float(clearing.total_shortfall / scale) if scale > 0 else 0.0
            )
        elif network_available:
            # Topology is known but the balance sheet is not. Centrality is a
            # legitimate network property; a clearing result would not be.
            importance = {
                bank_id: float(max(centrality[position], 0.0))
                for position, bank_id in enumerate(bank_ids)
            }

        profiles: Dict[str, BankRiskProfile] = {}
        for position, bank_id in enumerate(bank_ids):
            risk_score = scores[bank_id]
            profiles[bank_id] = BankRiskProfile(
                bank_id=bank_id,
                bank_name=f"Bank {bank_id}",
                risk_score=risk_score,
                risk_level=self._risk_level(risk_score),
                systemic_importance=importance.get(bank_id, 0.0),
                systemic_importance_method=importance_method,
                network_position=self._network_position(
                    centrality, position, network_available
                ),
                gross_liabilities=(
                    float(liabilities[position].sum()) if liabilities is not None else 0.0
                ),
                gross_claims=(
                    float(liabilities[:, position].sum()) if liabilities is not None else 0.0
                ),
                confidence_lower=None,
                confidence_upper=None,
                confidence_method=CONFIDENCE_METHOD_PENDING,
                top_vulnerabilities=self._vulnerabilities(
                    risk_score=risk_score,
                    position=position,
                    centrality=centrality,
                    network_available=network_available,
                ),
                top_strengths=[],
                recommendations=self._recommendations(risk_score, importance.get(bank_id, 0.0)),
            )

        risks = list(scores.values())
        avg_risk = float(np.mean(risks)) if risks else 0.0
        max_risk = float(np.max(risks)) if risks else 0.0

        fire_sale_result: Optional[FireSaleResult] = None
        if fire_sale_scenario is not None:
            scenario_ids = set(fire_sale_scenario.institution_ids)
            analysed_ids = set(bank_ids)
            if scenario_ids != analysed_ids:
                raise ValueError(
                    "fire_sale_scenario covers a different institution set than the "
                    "analysis: only in the scenario "
                    f"{sorted(scenario_ids - analysed_ids)}, only in the analysis "
                    f"{sorted(analysed_ids - scenario_ids)}"
                )
            fire_sale_result = solve_fire_sale(fire_sale_scenario)

        return MultiBankAnalysis(
            analysis_date=pd.Timestamp.now().isoformat(),
            num_banks=len(bank_ids),
            bank_profiles=profiles,
            avg_risk=avg_risk,
            max_risk=max_risk,
            num_high_risk=sum(1 for r in risks if r > HIGH_RISK_THRESHOLD),
            num_critical_risk=sum(1 for r in risks if r > CRITICAL_RISK_THRESHOLD),
            network_available=network_available,
            network_density=network_density,
            liability_matrix=liabilities,
            clearing=clearing,
            shock_scenarios=shock_scenarios,
            systemic_risk_score=systemic_risk_score,
            fire_sale=fire_sale_result,
        )

    def _score_bank(self, bank_id: str, df: pd.DataFrame) -> float:
        """Score one institution with a single forward pass.

        Missing observations are **not** forward-filled. Forward-filling copies
        a stale value into the future, which means a model consuming the series
        sees data that had not been published at that timestamp -- the series is
        silently extended with information from before the gap. Instead the gap
        is preserved and the observation mask is passed through, so the encoder
        can distinguish "value was zero" from "value was not reported".
        """
        if len(df) == 0:
            raise ValueError(f"No data provided for bank {bank_id}")

        source_code: Optional[str] = None
        if "source_code" in df.columns and df["source_code"].notna().any():
            source_code = str(df["source_code"].dropna().iloc[0])
            df = df[df["source_code"] == source_code]

        value_column = "Close" if "Close" in df.columns else "Value"
        if value_column not in df.columns:
            raise ValueError(
                f"Bank {bank_id} has neither a 'Close' nor a 'Value' column; "
                f"columns are {sorted(df.columns)}"
            )

        series = pd.to_numeric(df[value_column], errors="coerce")
        observed = series.notna().to_numpy()
        values = series.to_numpy(dtype=float)

        if len(values) < self.sequence_length:
            logger.warning(
                "Bank %s has only %d observations for a sequence length of %d",
                bank_id, len(values), self.sequence_length,
            )

        sequence, _stats = self._prepare_sequence(values, observed, source_code)
        source_id = self._map_source_id(source_code)

        inputs = sequence.unsqueeze(0).to(self.device)
        source_ids = torch.tensor(
            [[int(source_id)]], dtype=torch.long, device=self.device
        )
        self.model.eval()
        with torch.no_grad():
            output = self.model(inputs, source_ids)

        return float(output.detach().cpu().reshape(-1)[0])

    def _map_source_id(self, source_code: Optional[str]) -> int:
        if source_code and source_code in self.source_to_id:
            return int(self.source_to_id[source_code])
        if self.source_to_id:
            logger.warning(
                "Source %r was not seen during training - defaulting to 0", source_code
            )
        return 0

    def _prepare_sequence(
        self,
        values: np.ndarray,
        observed: np.ndarray,
        source_code: Optional[str],
    ) -> Tuple[torch.Tensor, Dict[str, float]]:
        """Normalise the tail of the series, preserving gaps as ``nan``.

        Substitutes the training-time mean for missing entries rather than
        carrying the previous observation forward, and returns the observation
        mask so callers can tell a real value from an imputed one.
        """
        values = np.asarray(values, dtype=np.float32)
        stats = self.source_stats.get(source_code, {}) if source_code else {}

        finite = values[np.isfinite(values)]
        default_mean = float(np.mean(finite)) if finite.size else 0.0
        default_std = float(np.std(finite)) if finite.size else 1.0
        mean = float(stats.get("mean", default_mean))
        std = float(stats.get("std", default_std))
        if not np.isfinite(std) or std == 0.0:
            std = 1.0

        normalized = (values - mean) / std
        # Impute with the standardised mean (i.e. 0) and keep the mask separate.
        mask = np.isfinite(normalized).astype(np.float32)
        normalized = np.where(np.isfinite(normalized), normalized, 0.0)

        length = self.sequence_length
        if len(normalized) >= length:
            normalized = normalized[-length:]
            mask = mask[-length:]
        else:
            pad = length - len(normalized)
            normalized = np.pad(normalized, (pad, 0), mode="constant", constant_values=0.0)
            mask = np.pad(mask, (pad, 0), mode="constant", constant_values=0.0)

        sequence = torch.FloatTensor(normalized)
        return sequence, {"mean": mean, "std": std, "observed_fraction": float(mask.mean())}

    # ------------------------------------------------------------------
    # Interpretation
    # ------------------------------------------------------------------

    @staticmethod
    def _risk_level(risk_score: float) -> str:
        if risk_score < RISK_THRESHOLD_LOW:
            return "low"
        if risk_score < RISK_THRESHOLD_MODERATE:
            return "medium"
        if risk_score < RISK_THRESHOLD_HIGH:
            return "high"
        return "critical"

    @staticmethod
    def _network_position(
        centrality: np.ndarray,
        position: int,
        network_available: bool,
    ) -> str:
        if not network_available or centrality.size == 0:
            return "unknown"
        finite = centrality[np.isfinite(centrality)]
        if finite.size == 0 or float(finite.max()) <= 0.0:
            return "peripheral"
        value = float(centrality[position])
        if value >= 0.66 * float(finite.max()):
            return "hub"
        if value <= 0.33 * float(finite.max()):
            return "peripheral"
        return "intermediate"

    @staticmethod
    def _vulnerabilities(
        risk_score: float,
        position: int,
        centrality: np.ndarray,
        network_available: bool,
    ) -> List[str]:
        """Describe the measured conditions, without inventing causes.

        The previous implementation listed "High contagion centrality" from a
        centrality-like score that was in fact a weighted sum of risk, exposure
        and a connection count. These strings are now tied to quantities that
        exist: the model score and the node's position in the liability network.
        """
        findings: List[str] = []
        if risk_score >= RISK_THRESHOLD_HIGH:
            findings.append("Model risk score is at or above the high threshold")
        elif risk_score >= RISK_THRESHOLD_MODERATE:
            findings.append("Model risk score is in the elevated band")

        if network_available and centrality.size:
            finite = centrality[np.isfinite(centrality)]
            peak = float(finite.max()) if finite.size else 0.0
            if peak > 0 and float(centrality[position]) >= 0.66 * peak:
                findings.append("Top-third eigenvector centrality in the liability network")
        return findings

    @staticmethod
    def _recommendations(risk_score: float, systemic_importance: float) -> List[str]:
        recommendations: List[str] = []
        if risk_score >= RISK_THRESHOLD_HIGH:
            recommendations.append(
                "Increase high-quality liquid assets and reduce short-term wholesale reliance"
            )
            recommendations.append(
                "Stress-test the contingency funding plan against the modelled stress path"
            )
        elif risk_score >= RISK_THRESHOLD_MODERATE:
            recommendations.append("Monitor intraday liquidity positions more frequently")
            recommendations.append("Review funding-source diversification")

        if systemic_importance >= 0.1:
            recommendations.append(
                "Institution is systemically material: publish exposure detail for the "
                "clearing members that would absorb its shortfall"
            )
        return recommendations[:5]


def generate_executive_summary(analysis: MultiBankAnalysis) -> str:
    """Render a non-technical summary of a multi-institution analysis."""
    summary = f"""
EXECUTIVE SUMMARY - Banking System Liquidity Risk Analysis
Date: {analysis.analysis_date}
Institutions Analysed: {analysis.num_banks}

OVERALL SYSTEM HEALTH:
- Average Risk Score: {analysis.avg_risk * 100:.1f}% ({_risk_to_text(analysis.avg_risk)})
- Highest Risk Score: {analysis.max_risk * 100:.1f}%
- Institutions Requiring Immediate Attention: {analysis.num_critical_risk}
- Institutions Under Elevated Stress: {analysis.num_high_risk}
"""

    if analysis.systemic_risk_score is not None:
        summary += f"- Unpaid fraction of system liabilities: {analysis.systemic_risk_score * 100:.2f}%\n"
    else:
        summary += (
            "- Systemic clearing: UNAVAILABLE - interbank liabilities and institution\n"
            "  endowments were not supplied, so no clearing equilibrium exists to report.\n"
            "  The risk scores below are model outputs on individual time series and do\n"
            "  not by themselves imply contagion.\n"
        )

    critical = [
        (bank_id, profile)
        for bank_id, profile in analysis.bank_profiles.items()
        if profile.risk_level == "critical"
    ]
    if critical:
        summary += f"\n{len(critical)} INSTITUTION(S) AT CRITICAL RISK LEVELS:\n"
        for _bank_id, profile in critical[:5]:
            summary += (
                f"- {profile.bank_name}: {profile.risk_score * 100:.1f}% model risk\n"
            )

    if analysis.network_available:
        ranked = sorted(
            analysis.bank_profiles.values(),
            key=lambda profile: profile.systemic_importance,
            reverse=True,
        )[:3]
        if ranked:
            summary += "\nMOST SYSTEMICALLY IMPORTANT INSTITUTIONS:\n"
            for profile in ranked:
                summary += (
                    f"- {profile.bank_id}: importance {profile.systemic_importance * 100:.1f}% "
                    f"({profile.systemic_importance_method})\n"
                )

    if analysis.shock_scenarios:
        summary += "\nCONTAGION SCENARIOS (total loss of external assets):\n"
        for bank_id, result in list(analysis.shock_scenarios.items())[:2]:
            sequence = result.default_sequence()
            summary += (
                f"- If {bank_id} loses all external assets: "
                f"{result.n_defaults} institution(s) fail"
            )
            if sequence:
                summary += f", in order: {' -> '.join(sequence)}"
            summary += "\n"

    all_recommendations: List[str] = []
    for profile in analysis.bank_profiles.values():
        if profile.risk_level in ("critical", "high"):
            all_recommendations.extend(profile.recommendations)
    unique_recommendations = list(dict.fromkeys(all_recommendations))[:5]
    if unique_recommendations:
        summary += "\nRECOMMENDED ACTIONS:\n"
        for index, recommendation in enumerate(unique_recommendations, 1):
            summary += f"{index}. {recommendation}\n"

    return summary


def _risk_to_text(risk: float) -> str:
    """Convert a risk score to human-readable text."""
    if risk < 0.3:
        return "LOW RISK"
    if risk < 0.6:
        return "MODERATE RISK"
    if risk < 0.85:
        return "HIGH RISK"
    return "CRITICAL RISK"
