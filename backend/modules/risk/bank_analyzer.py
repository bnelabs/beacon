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
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

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
from ..engine.persistence_vectors import (
    SUMMARY_FEATURES,
    PersistenceVectorParameters,
    persistence_vector,
)
from ..engine.portfolio_overlap import (
    PortfolioOverlapResult,
    analyse_portfolio_overlap,
)
from .regulatory import (
    InstitutionState,
    StressTranslationResult,
    translate_systemic_stress,
)
from .fire_sale import FireSaleResult, FireSaleScenario, solve_fire_sale
from .liquidity_spiral import (
    LiquiditySpiralModel,
    SpiralParameters,
    SpiralResult,
    shock_from_shortfall,
)
from ..engine.latent_dynamics import (
    LatentDynamicsResult,
    LatentDynamicsScenario,
    simulate_latent_stress,
)
from ..engine.counterfactual import (
    CounterfactualOutcome,
    CounterfactualScenario,
    run_counterfactual,
)

logger = logging.getLogger(__name__)

__all__ = [
    "BankRiskProfile",
    "MultiBankAnalysis",
    "TopologicalFeatures",
    "BankRiskAnalyzer",
    "generate_executive_summary",
    "eigenvector_centrality",
]

# Milestone at which calibrated intervals replace the current placeholder.
CONFIDENCE_METHOD_PENDING = "unavailable:pending-conformal-calibration"


@dataclass(frozen=True)
class TopologicalFeatures:
    """The topological signature of the exposure network, as a fixed-width vector.

    `summary` names the interpretable half -- Betti numbers, fragmentation and
    redundancy, the same statistics `persistent_homology.TopologicalSignature`
    reports. `vector` is the full signature a model consumes, whose layout is
    documented by
    :class:`~backend.modules.engine.persistence_vectors.PersistenceVectorParameters`.

    It is computed only when the caller supplies `topology_parameters` *and* the
    exposure network exists. A topological signature of a network that was never
    built would be a number without a subject, so that combination raises.
    """

    summary: Mapping[str, float]
    vector: Tuple[float, ...]
    reference: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "summary": {name: float(value) for name, value in self.summary.items()},
            "vector": [float(value) for value in self.vector],
            "reference": self.reference,
            "width": len(self.vector),
        }


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
    regulatory_stress: Optional[StressTranslationResult] = None
    """Per-institution Basel III ratios before and after the systemic stress.

    `None` when the caller supplied no `regulatory_states`. The stress table is a
    different question from `clearing`: clearing says who fails to pay, this says
    what that does to the liquidity and leverage ratios a supervisor measures.
    """

    crowding: Optional[PortfolioOverlapResult] = None
    """Crowded-trade overlap across the supplied holdings.

    `None` when no holdings matrix was supplied. A distinct volatility channel:
    two institutions can hold identical positions and owe each other nothing, so
    this is invisible in any exposure layer.
    """

    topology: Optional[TopologicalFeatures] = None
    """Structural fragility of the exposure network, when it was requested.

    `None` when no `topology_parameters` were supplied. Summary statistics such
    as average degree can be unchanged while the routes between members quietly
    collapse; this measures whether they did.
    """

    liquidity_spiral: Dict[str, SpiralResult] = field(default_factory=dict)
    """Per-institution Brunnermeier-Pedersen spiral, keyed by institution id.

    Populated only for institutions that both failed to pay in the clearing
    equilibrium *and* had a :class:`SpiralParameters` supplied. Empty otherwise:
    a spiral needs a shock, and the shock comes from a real clearing shortfall --
    without liabilities and endowments there is none, and inventing one from a
    model risk score would make the spiral a restatement of the model rather than
    a consequence of the balance sheet.
    """

    latent_dynamics: Optional[LatentDynamicsResult] = None
    """Terminal dispersion of the caller-declared latent SDE, when one was given.

    ``None`` unless a :class:`LatentDynamicsScenario` was supplied. It is a
    **simulated scenario dispersion under a declared SDE**, not a calibrated
    prediction interval: the drift and diffusion are caller inputs, not
    estimates, and this field must never be read as ``confidence_lower`` /
    ``confidence_upper``. The result carries its own
    :data:`~backend.modules.engine.latent_dynamics.DISPERSION_LABEL` and a
    ``calibrated`` flag that is always ``False``.
    """

    counterfactual: Optional[CounterfactualOutcome] = None
    """The counterfactual answer to a caller-declared ``do`` query, when one was given.

    ``None`` unless a :class:`CounterfactualScenario` was supplied. It is
    **conditional on the scenario's declared structural model**: an answer to "what
    follows from this intervention given this model", not a forecast of the world.
    A misspecified coefficient yields a precise wrong answer, and nothing here
    bounds that error -- the outcome carries
    :data:`~backend.modules.engine.counterfactual.CONDITIONALITY_NOTE` and an
    ``is_forecast`` flag that is always ``False``.
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
            "regulatory_stress": (
                self.regulatory_stress.to_dict() if self.regulatory_stress else None
            ),
            "crowding": self.crowding.to_dict() if self.crowding else None,
            "topology": self.topology.to_dict() if self.topology else None,
            "liquidity_spiral": {
                bank_id: result.to_dict()
                for bank_id, result in self.liquidity_spiral.items()
            },
            "latent_dynamics": (
                self.latent_dynamics.to_dict() if self.latent_dynamics else None
            ),
            "counterfactual": (
                self.counterfactual.to_dict() if self.counterfactual else None
            ),
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
        regulatory_states: Optional[Sequence[InstitutionState]] = None,
        price_decline: Optional[float] = None,
        holdings: Optional[pd.DataFrame] = None,
        concentration_threshold: Optional[float] = None,
        topology_parameters: Optional[PersistenceVectorParameters] = None,
        spiral_parameters: Optional[Mapping[str, SpiralParameters]] = None,
        latent_dynamics_scenario: Optional[LatentDynamicsScenario] = None,
        counterfactual_scenario: Optional[CounterfactualScenario] = None,
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
            regulatory_states: Optional per-institution Basel III positions. Must
                cover *every* analysed institution, because a partial stress table
                silently omits the others and reads as though they were unaffected.
            price_decline: Optional fractional price fall applied to each
                institution's declared price-sensitive assets.
            holdings: Optional institutions x instruments positions frame for
                crowded-trade analysis. A subset of the analysed institutions is
                allowed; an institution outside the analysis is not.
            concentration_threshold: Optional per-institution concentration above
                which a holding counts toward the correlated-unwind measure.
            topology_parameters: Optional persistence-vector parameters. When
                supplied, the exposure network's topological signature is computed;
                this requires the network to exist.
            spiral_parameters: Optional per-institution Brunnermeier-Pedersen
                parameters. When supplied, each institution that failed to pay in
                the clearing equilibrium has its shortfall translated into the
                adverse price move its forced sale implies
                (:func:`~backend.modules.risk.liquidity_spiral.shock_from_shortfall`),
                and the coupled market/funding spiral is solved from there. This
                requires the clearing equilibrium to exist -- the shock *is* the
                shortfall -- and must cover every defaulting institution, since a
                partial table would omit institutions silently.
            latent_dynamics_scenario: Optional caller-declared latent SDE. When
                supplied, every analysed institution's initial latent stress state
                is advanced stochastically and the terminal dispersion is attached
                as :attr:`MultiBankAnalysis.latent_dynamics`. The scenario must
                cover *every* analysed institution: a partial scenario would
                attach a dispersion table that reads as though the omitted
                institutions had none. The output is a **simulated scenario
                dispersion under a declared SDE, not a calibrated prediction
                interval** -- the drift and diffusion are caller inputs and are
                neither fitted nor validated here -- so it is deliberately not
                placed in ``confidence_lower``/``confidence_upper``.
            counterfactual_scenario: Optional caller-declared ``do`` query over a
                structural model. When supplied, abduction/intervention/propagation
                is run and the answer is attached as
                :attr:`MultiBankAnalysis.counterfactual`. The variables of the
                structural model are factors, not analysed institutions, so unlike
                the other scenarios this one is *not* required to cover the analysed
                set -- it is a different question attached to the same report. The
                answer is conditional on the declared model and is not a forecast.

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

        regulatory_stress_result: Optional[StressTranslationResult] = None
        if regulatory_states is not None:
            states = list(regulatory_states)
            given = [state.institution_id for state in states]
            repeated = sorted({name for name in given if given.count(name) > 1})
            if repeated:
                raise ValueError(f"regulatory_states repeats institution(s): {repeated}")
            unknown = sorted(set(given) - set(bank_ids))
            if unknown:
                raise KeyError(
                    "regulatory_states names institutions outside the analysis: "
                    f"{unknown}"
                )
            absent = sorted(set(bank_ids) - set(given))
            if absent:
                raise ValueError(
                    "regulatory_states must cover every analysed institution; missing "
                    f"{absent}. A partial stress table would omit institutions "
                    "silently, which reads as though they were unaffected."
                )
            regulatory_stress_result = translate_systemic_stress(
                states, clearing=clearing, price_decline=price_decline
            )

        crowding_result: Optional[PortfolioOverlapResult] = None
        if holdings is not None:
            if not isinstance(holdings, pd.DataFrame):
                raise TypeError(
                    "holdings must be a DataFrame of institutions x instruments, got "
                    f"{type(holdings).__name__}"
                )
            institution_ids = [str(name) for name in holdings.index]
            instrument_ids = [str(name) for name in holdings.columns]
            unknown = sorted(set(institution_ids) - set(bank_ids))
            if unknown:
                raise KeyError(
                    f"holdings names institutions outside the analysis: {unknown}"
                )
            crowding_result = analyse_portfolio_overlap(
                holdings.to_numpy(dtype=float),
                institution_ids,
                instrument_ids,
                concentration_threshold=concentration_threshold,
            )

        topology_result: Optional[TopologicalFeatures] = None
        if topology_parameters is not None:
            if liabilities is None:
                raise ValueError(
                    "topology_parameters were supplied but the exposure network is "
                    "unavailable; supply interbank exposures and endowments. A "
                    "topological signature of a network that was never built would be "
                    "a number without a subject."
                )
            vector = persistence_vector(liabilities, topology_parameters)
            block = topology_parameters.layout()["summary"]
            topology_result = TopologicalFeatures(
                summary=dict(
                    zip(SUMMARY_FEATURES, (float(value) for value in vector[block]))
                ),
                vector=tuple(float(value) for value in vector),
                reference=str(topology_parameters.reference),
            )

        spiral_results: Dict[str, SpiralResult] = {}
        if spiral_parameters is not None:
            if clearing is None:
                raise ValueError(
                    "spiral_parameters were supplied but there is no clearing "
                    "equilibrium: the spiral's initial shock is the clearing "
                    "shortfall, so supply interbank exposures and endowments. Without "
                    "them a shock would have to be invented from the model score, "
                    "which would make the spiral a restatement of the model."
                )

            unknown_spiral = sorted(set(spiral_parameters) - set(bank_ids))
            if unknown_spiral:
                raise KeyError(
                    "spiral_parameters names institutions outside the analysis: "
                    f"{unknown_spiral}"
                )
            for institution, parameters in spiral_parameters.items():
                if not isinstance(parameters, SpiralParameters):
                    raise TypeError(
                        f"spiral_parameters[{institution!r}] must be a SpiralParameters, "
                        f"got {type(parameters).__name__}"
                    )

            # The shock is the institution's own unpaid obligation. `node_ids`
            # defines the clearing vector's index order, so resolve positions
            # through it rather than assuming it matches `bank_ids`.
            position_of = {
                bank_id: index for index, bank_id in enumerate(clearing.node_ids)
            }
            shortfalls: Dict[str, float] = {
                bank_id: float(
                    clearing.nominal_liabilities[position_of[bank_id]]
                    - clearing.payments[position_of[bank_id]]
                )
                for bank_id in bank_ids
            }
            defaulting = {
                bank_id for bank_id, shortfall in shortfalls.items() if shortfall > 0.0
            }
            missing = sorted(defaulting - set(spiral_parameters))
            if missing:
                # Same reasoning as the regulatory table: a partial spiral table
                # omits institutions, which reads as though they were unaffected.
                raise ValueError(
                    "spiral_parameters must cover every institution that failed to pay "
                    f"in the clearing equilibrium; missing {missing}"
                )

            for bank_id, parameters in spiral_parameters.items():
                shock = shock_from_shortfall(
                    shortfalls[bank_id],
                    price=parameters.price,
                    price_impact=parameters.price_impact,
                )
                spiral_results[bank_id] = LiquiditySpiralModel(parameters).cascade(shock)

        latent_result: Optional[LatentDynamicsResult] = None
        if latent_dynamics_scenario is not None:
            if not isinstance(latent_dynamics_scenario, LatentDynamicsScenario):
                raise TypeError(
                    "latent_dynamics_scenario must be a LatentDynamicsScenario, got "
                    f"{type(latent_dynamics_scenario).__name__}"
                )
            named = set(latent_dynamics_scenario.institution_ids)
            analysed = {str(bank_id) for bank_id in bank_ids}
            unknown_latent = sorted(named - analysed)
            if unknown_latent:
                raise KeyError(
                    "latent_dynamics_scenario names institutions outside the analysis: "
                    f"{unknown_latent}"
                )
            absent_latent = sorted(analysed - named)
            if absent_latent:
                # Same reasoning as the regulatory and spiral tables: omitting an
                # institution would attach a dispersion table that reads as though
                # the omitted institutions had no simulated dispersion.
                raise ValueError(
                    "latent_dynamics_scenario must cover every analysed institution; "
                    f"missing {absent_latent}"
                )
            # Nothing here is derived from the model score. The initial latent
            # states are the caller's declaration; manufacturing them from a risk
            # score would make the simulated dispersion a restatement of the
            # model rather than a property of the declared process.
            latent_result = simulate_latent_stress(latent_dynamics_scenario)

        counterfactual_result: Optional[CounterfactualOutcome] = None
        if counterfactual_scenario is not None:
            if not isinstance(counterfactual_scenario, CounterfactualScenario):
                raise TypeError(
                    "counterfactual_scenario must be a CounterfactualScenario, got "
                    f"{type(counterfactual_scenario).__name__}"
                )
            # Deliberately no coverage requirement here, unlike the regulatory,
            # spiral and latent tables: the structural model's variables are
            # factors, not the analysed institutions, so demanding that they match
            # bank ids would force a caller to mislabel one as the other. The
            # scenario validates its own shape -- observation columns against model
            # variables, interventions against declared variables -- in its
            # constructor, so a mismatch still fails closed.
            counterfactual_result = run_counterfactual(counterfactual_scenario)

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
            regulatory_stress=regulatory_stress_result,
            crowding=crowding_result,
            topology=topology_result,
            liquidity_spiral=spiral_results,
            latent_dynamics=latent_result,
            counterfactual=counterfactual_result,
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
    """Convert a risk score to human-readable text.

    Reads the same named thresholds as :meth:`BankRiskAnalyzer._risk_level`
    instead of repeating the literals. The two functions previously hard-coded the
    same three numbers independently, so a change to ``constants.py`` would have
    left the narrative summary disagreeing with the per-institution risk level it
    summarises -- with nothing to detect the drift.
    """
    if risk < RISK_THRESHOLD_LOW:
        return "LOW RISK"
    if risk < RISK_THRESHOLD_MODERATE:
        return "MODERATE RISK"
    if risk < RISK_THRESHOLD_HIGH:
        return "HIGH RISK"
    return "CRITICAL RISK"
