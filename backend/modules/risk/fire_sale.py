"""Greenwood-Landier-Thesmar fire-sale spiral coupled to Eisenberg-Noe clearing.

Why this module exists
----------------------

Two modules in this package each answer one half of the same crisis and never
speak to each other:

* :mod:`backend.modules.risk.clearing` (Eisenberg-Noe) answers *who fails given
  a set of balance sheets*, and reports the shortfall each defaulter leaves
  unpaid.
* :mod:`backend.modules.risk.liquidity_spiral` (Brunnermeier-Pedersen) answers
  *how far a price has to fall before a levered holder's deleveraging becomes
  feasible*, and where the stability boundary ``lambda*`` lies.

In a real fire sale the two are one feedback loop. Institutions fail the
clearing and are left with an unpaid shortfall; they sell illiquid assets to
raise the cash; selling moves prices by ``lambda`` per unit, so the liquidation
is worth less than the mark it was counted at; the price fall marks every other
holder down and shrinks their capital; thinner capital breaches the margin
constraint, forcing further sales; and the loop returns to the clearing with a
worse balance sheet. This module solves that coupled fixed point. It is the
Greenwood-Landier-Thesmar (2015) spiral, closed through an actual clearing
engine rather than asserted.

What IS implemented
-------------------

* A **round-based fixed-point solver**. Each round: (1) mark capital to the
  current prices, (2) clear the interbank network with the current marked
  balance sheets, (3) derive a required liquidation from the clearing shortfall
  and the margin constraint, (4) execute it, (5) move prices by the aggregate
  sale, (6) test convergence. The loop stops when the dimensionless
  round-over-round change is at or below ``tolerance``, or reports divergence if
  the round cap is reached or a price would cease to be positive.

* **Reuse, not reimplementation.** The clearing step is
  :class:`~backend.modules.risk.clearing.MultiplexClearingEngine`; the margin in
  force is :meth:`~backend.modules.risk.liquidity_spiral.SpiralParameters.margin_for`;
  the per-round stability boundary is
  :func:`~backend.modules.risk.liquidity_spiral.stability_impact_limit`. No
  second Eisenberg-Noe solver and no second margin formula exist here.

* **Explicit state.** Holdings of one or more illiquid assets, initial prices,
  capital, endowments, the interbank liability matrix, margin requirements,
  price impacts and an exogenous price shock are all caller inputs. Nothing is
  invented, interpolated or defaulted for a missing quantity.

* **Feedback isolation.** The same scenario is solved with every ``lambda`` set
  to zero. The difference between the two runs is the part of the loss
  attributable to the fire-sale feedback, as opposed to the direct effect of the
  initial shock. The set of institutions that survive at ``lambda = 0`` but
  default at ``lambda > 0`` is reported as a first-class output: that is the
  systemic-risk number.

* **Path record.** Per round: prices, margins in force, per-institution capital,
  shortfalls, defaults, liquidation demand and the units actually sold, the
  convergence deltas, and whether the round's ``lambda`` exceeded ``lambda*``.

The model, stated exactly
-------------------------

Let ``p_a(0)`` be the initial price of asset ``a`` and ``s_a`` an exogenous
price shock applied before round 1. Institution ``i`` holds ``X_i,a(0)`` units.
Write ``V_i(0) = sum_a X_i,a(0) p_a(0)``.

**Capital (loss spiral).** Marked on the position carried *into* the shock,
exactly as :mod:`liquidity_spiral` marks it (``C = C0 + X0 * price_change``)::

    C_i(r) = capital_i + sum_a X_i,a(0) * (p_a(r) - p_a(0))

Sales do **not** reduce the mark. The loss is realised at the sale price, so
marking the full original position at the current price is the conservative
reading, and it is the same convention the spiral solver uses.

**Margin in force (margin spiral).** Via ``SpiralParameters.margin_for`` with the
portfolio's mark-to-market return as the realised volatility::

    m_i(r) = clip( margin_i
                   + kappa_i * (|C_i(r) - capital_i| / V_i(0) - sigma_i),
                   min_margin, max_margin )

Direction: a larger price fall raises ``|C_i(r) - capital_i|``, which raises
``m_i(r)``, which *lowers* the financeable position below.

**Clearing capacity.** Each round is a re-solve of the *same* balance sheet at
new prices, not a time step. The endowment handed to the clearing engine is the
institution's marked external assets::

    e_i(r) = endowments_i + cash_i(r) + sum_a X_i,a(r) * p_a(r)

where ``cash_i(r)`` is the cumulative cash actually raised by earlier sales. The
cash term matters: selling converts holdings into cash at the price realised, so
the conversion is value-neutral at the price it is executed at, and the only
thing that destroys capacity is the price impact. Every term is non-negative, so
the endowment passed to the engine is never negative.

**Liquidation rule.** Given the clearing shortfall
``S_i(r) = max(0, liabilities_i - payments_i)`` and the margin need
``max(0, V_i(r) - max(0, C_i(r)) / m_i(r))``, the required sale value is::

    D_i(r) = max( V_i(r) - max(0, C_i(r)) / m_i(r) ,  S_i(r) )

The two needs are combined with a maximum, not a sum: one sale of value
``D_i(r)`` both raises the cash the shortfall requires and shrinks the position
to the financeable size, so it satisfies both at once. The institution then
sells the fraction ``phi_i(r) = min(1, D_i(r) / V_i(r))`` of its portfolio
(``phi_i = 0`` when ``V_i(r) = 0``). By default the sale is **pro rata across
every asset**; if the caller declares an order in
:attr:`FireSaleScenario.liquidation_order`, assets are sold in that declared
order until ``D_i(r)`` is covered. A demand larger than the whole portfolio is
not fabricated into a sale: the institution sells all it has and the residual
unmet demand is reported in the round record.

**Price impact.** Linear, permanent, constant depth, aggregated across every
seller::

    Q_a(r) = sum_{k <= r} sum_i sold_i,a(k)
    p_a(r) = p_a(0) + s_a - lambda_a * Q_a(r)

This is the same linear impact law the spiral declares (``dp = lambda * dX``),
applied once at the market level rather than once per holder. Applying a
single-holder :meth:`LiquiditySpiralModel.cascade` to each institution
separately would attribute the whole market move to each of them in turn and
double-count it; the spiral's own public surface is used where it is defined for
the aggregate problem (``margin_for``, ``stability_impact_limit``).

**Convergence.** The per-round change is a dimensionless sup-norm::

    price_delta(r)       = max_a |p_a(r) - p_a(r-1)| / max_a |p_a(0)|
    liquidation_delta(r) = max_i (value actually sold by i in round r)
                           / max(1, max_j (endowments_j + V_j(0) + liabilities_j))
    delta(r)             = max(price_delta(r), liquidation_delta(r))

The liquidation term is included deliberately. With ``lambda = 0`` prices never
move, and a price-only test would stop after one round while the institution is
still draining its portfolio. The loop converges when ``delta(r) <= tolerance``
and the run is re-evaluated once at the final prices so the reported clearing is
the one belonging to the reported fixed point.

**Divergence.** Reaching the round cap without ``delta <= tolerance``, or a
round in which any asset's price would fall to zero or below, sets
``converged = False, diverged = True`` with a machine-readable reason. No final
price, capital or shortfall is then returned; ``final_prices`` and the other
``final_*`` fields are ``None`` and the partial path is still reported. A spiral
that runs away *is* the crisis, and reporting a capped or clamped number as if
it were an equilibrium would be worse than reporting nothing.

What is NOT implemented, and the limitations you must read
----------------------------------------------------------

* **The fixed point may be non-unique.** The map is not a contraction; the
  no-sale and partial-liquidation equilibria can coexist, and the path taken can
  land on different ones. This solver reports only the fixed point it reaches
  from the given initial condition and path. It is not evidence that no other
  equilibrium exists, and a different round ordering or rule could settle
  elsewhere. This is the single most important caveat in the module.
* **No strategic or anticipatory behaviour.** Every agent follows the mechanical
  rule above. No institution pre-empts a peer's sale, hoards liquidity, or
  chooses a sale size to minimise its own loss.
* **No new lending and no central-bank intervention.** No discount window, no
  recapitalisation, no asset purchase, no lending-of-last-resort. Endowments are
  fixed; cash raised is never re-lent.
* **No bankruptcy or resolution costs.** A default is an unpaid claim, nothing
  more. There are no legal costs, no stay, no fire-sale of the estate, no
  depositor preference.
* **Price impact is linear with constant depth.** There are no depth dynamics,
  no liquidity recovery, no concave market depth, and no distinction between
  temporary and permanent impact.
* **No cross-asset substitution and no externality pricing.** A seller does not
  switch to a substitute asset, and nobody internalises the price impact it
  imposes on others.
* **No intraday sequencing or settlement timing.** Rounds are re-solves, not
  clock time. There is no queue, no netting cycle, no settlement lag.
* **Holdings are marked at the same price for every holder.** No position size
  effects, no lot-level discounts, no differing execution prices.
* **No optimisation over liquidation order.** The pro-rata rule (or the
  caller's declared order) is mechanical; it is not chosen to minimise losses.
* Capital is marked on the **initial** position and is not reduced by sales;
  the clearing endowment includes holdings at the **pre-impact** price of the
  round; and interbank losses do not feed the margin constraint, only the
  shortfall channel. Each of these is a modelling choice, not an accounting
  identity.
* The ``lambda = 0`` run is an **isolation counterfactual**, not a "no-crisis"
  counterfactual: the initial price shock and the initial clearing are still
  applied. Only the feedback channel is switched off.
* Inputs are caller-supplied balance sheets, so a malformed one is a
  :class:`ValueError` (a structural/programmer error). No exception from
  :mod:`backend.exceptions` applies: none of them describes a bad argument to a
  pure solver, and fabricating an ingestion error would misreport the cause.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from .clearing import DEFAULT_TOLERANCE as CLEARING_DEFAULT_TOLERANCE
from .clearing import ClearingResult, MultiplexClearingEngine, NetworkLayer
from .liquidity_spiral import SpiralParameters, stability_impact_limit

__all__ = [
    "FireSaleScenario",
    "FireSaleRound",
    "FireSaleAmplification",
    "FireSaleResult",
    "FireSaleSolver",
    "solve_fire_sale",
    "DEFAULT_TOLERANCE",
    "DEFAULT_MAX_ROUNDS",
]

DEFAULT_TOLERANCE = 1e-10
DEFAULT_MAX_ROUNDS = 1_000


# ---------------------------------------------------------------------------
# Validation helpers. Every failure is a precise ValueError: the inputs are
# caller-supplied balance sheets, so a malformed one is a programming error.
# ---------------------------------------------------------------------------


def _as_id_tuple(ids: Sequence[str], name: str) -> Tuple[str, ...]:
    if ids is None:
        raise ValueError(f"{name} is required")
    values = tuple(str(item) for item in ids)
    if not values:
        raise ValueError(f"{name} must not be empty")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} contains duplicate entries: {values}")
    return values


def _as_float_vector(
    values: Sequence[float], length: int, name: str
) -> np.ndarray:
    array = np.asarray(values, dtype=float).reshape(-1)
    if array.shape[0] != length:
        raise ValueError(
            f"{name} has length {array.shape[0]} but {length} was expected"
        )
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} contains non-finite values")
    return array


def _as_float_matrix(
    values: Sequence[Sequence[float]], shape: Tuple[int, int], name: str
) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.shape != shape:
        raise ValueError(
            f"{name} must have shape {shape}, got {array.shape}"
        )
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} contains non-finite values")
    return array


def _freeze(array: np.ndarray) -> np.ndarray:
    array.setflags(write=False)
    return array


# ---------------------------------------------------------------------------
# Scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FireSaleScenario:
    """The balance sheets, prices and liquidation frictions of a fire sale.

    Every field is a caller declaration. Nothing is derived from a default, and
    a missing or nonsensical quantity raises rather than being guessed.

    Attributes:
        institution_ids: Unique labels, length ``n``. Index order defines the
            rows of ``holdings``, ``capital`` and the liability matrix.
        asset_ids: Unique labels, length ``A``. Index order defines the columns
            of ``holdings`` and the entries of the price vectors.
        holdings: ``(n, A)`` non-negative units of each illiquid asset held.
        prices: ``(A,)`` strictly positive initial prices.
        capital: ``(n,)`` non-negative equity backing the illiquid book at
            ``t = 0``; the numerator of the margin constraint. The initial
            position must be financeable: ``margins_i * V_i(0) <= capital_i``.
        endowments: ``(n,)`` non-negative external assets available to the
            clearing engine at ``t = 0``, excluding the illiquid book.
        liabilities: ``(n, n)`` non-negative matrix where ``liabilities[i, j]``
            is what ``i`` owes ``j``. Consumed by the clearing engine.
        margins: ``(n,)`` initial margin requirement ``m_i`` in ``(0, 1]``.
        price_impacts: ``(A,)`` non-negative ``lambda_a``, the price change per
            unit of asset ``a`` sold.
        price_shock: ``(A,)`` finite exogenous price change applied once before
            round 1. This is the initial shock, not feedback.
        margin_sensitivity: ``(n,)`` non-negative ``kappa_i``, the rise in the
            margin per unit of realised portfolio volatility. ``None`` means
            no margin spiral (all zeros), an explicit model choice.
        reference_volatility: ``sigma``, the volatility at which ``margins`` is
            the requirement. Scalar, applied to every institution.
        min_margin, max_margin: Bounds on the margin in force, in ``(0, 1]``.
        liquidation_order: Optional mapping from institution id to an ordered
            permutation of ``asset_ids``. Institutions listed sell in that
            order instead of pro rata; unlisted institutions sell pro rata.
    """

    institution_ids: Sequence[str]
    asset_ids: Sequence[str]
    holdings: np.ndarray
    prices: np.ndarray
    capital: np.ndarray
    endowments: np.ndarray
    liabilities: np.ndarray
    margins: np.ndarray
    price_impacts: np.ndarray
    price_shock: np.ndarray
    margin_sensitivity: Optional[np.ndarray] = None
    reference_volatility: float = 0.0
    min_margin: float = 0.01
    max_margin: float = 1.0
    liquidation_order: Optional[Mapping[str, Sequence[str]]] = None

    def __post_init__(self) -> None:
        institutions = _as_id_tuple(self.institution_ids, "institution_ids")
        assets = _as_id_tuple(self.asset_ids, "asset_ids")
        n = len(institutions)
        a_count = len(assets)
        object.__setattr__(self, "institution_ids", institutions)
        object.__setattr__(self, "asset_ids", assets)

        holdings = _as_float_matrix(self.holdings, (n, a_count), "holdings")
        if np.any(holdings < 0.0):
            raise ValueError("holdings cannot be negative")
        holdings = _freeze(holdings)
        object.__setattr__(self, "holdings", holdings)

        prices = _as_float_vector(self.prices, a_count, "prices")
        if np.any(prices <= 0.0):
            raise ValueError("prices must be strictly positive")
        prices = _freeze(prices)
        object.__setattr__(self, "prices", prices)

        capital = _as_float_vector(self.capital, n, "capital")
        if np.any(capital < 0.0):
            raise ValueError("capital cannot be negative")
        object.__setattr__(self, "capital", _freeze(capital))

        endowments = _as_float_vector(self.endowments, n, "endowments")
        if np.any(endowments < 0.0):
            raise ValueError("endowments cannot be negative")
        object.__setattr__(self, "endowments", _freeze(endowments))

        liabilities = _as_float_matrix(
            self.liabilities, (n, n), "liabilities"
        )
        if np.any(liabilities < 0.0):
            raise ValueError("liabilities cannot be negative")
        object.__setattr__(self, "liabilities", _freeze(liabilities))

        margins = _as_float_vector(self.margins, n, "margins")
        if np.any(margins <= 0.0) or np.any(margins > 1.0):
            raise ValueError(f"margins must all lie in (0, 1], got {margins.tolist()}")
        object.__setattr__(self, "margins", _freeze(margins))

        price_impacts = _as_float_vector(
            self.price_impacts, a_count, "price_impacts"
        )
        if np.any(price_impacts < 0.0):
            raise ValueError("price_impacts cannot be negative")
        object.__setattr__(self, "price_impacts", _freeze(price_impacts))

        price_shock = _as_float_vector(self.price_shock, a_count, "price_shock")
        post_shock = prices + price_shock
        if np.any(post_shock <= 0.0):
            raise ValueError(
                "prices + price_shock must remain strictly positive; asset "
                f"{assets[int(np.argmin(post_shock))]!r} would be "
                f"{float(np.min(post_shock)):.6g}"
            )
        object.__setattr__(self, "price_shock", _freeze(price_shock))

        if self.margin_sensitivity is None:
            sensitivity = np.zeros(n, dtype=float)
        else:
            sensitivity = _as_float_vector(
                self.margin_sensitivity, n, "margin_sensitivity"
            )
            if np.any(sensitivity < 0.0):
                raise ValueError("margin_sensitivity cannot be negative")
        object.__setattr__(self, "margin_sensitivity", _freeze(sensitivity))

        if not math.isfinite(self.reference_volatility) or self.reference_volatility < 0.0:
            raise ValueError(
                f"reference_volatility must be finite and non-negative, got "
                f"{self.reference_volatility}"
            )
        if not (0.0 < self.min_margin <= self.max_margin <= 1.0):
            raise ValueError(
                "need 0 < min_margin <= max_margin <= 1, got "
                f"{self.min_margin}, {self.max_margin}"
            )

        ordered: Dict[str, Tuple[str, ...]] = {}
        if self.liquidation_order is not None:
            known_institutions = set(institutions)
            known_assets = set(assets)
            for institution, order in self.liquidation_order.items():
                key = str(institution)
                if key not in known_institutions:
                    raise ValueError(
                        f"liquidation_order references unknown institution id {key!r}"
                    )
                sequence = tuple(str(item) for item in order)
                unknown = [item for item in sequence if item not in known_assets]
                if unknown:
                    raise ValueError(
                        f"liquidation_order for {key!r} references unknown asset "
                        f"ids {unknown}"
                    )
                if sorted(sequence) != sorted(assets):
                    raise ValueError(
                        f"liquidation_order for {key!r} must be a permutation of "
                        f"asset_ids {list(assets)}, got {list(sequence)}"
                    )
                ordered[key] = sequence
        object.__setattr__(self, "liquidation_order", ordered)

        # Fail closed on an already-breached position: the spiral module refuses
        # an un-financeable holder, and this solver must not silently start from
        # a state the machinery it reuses would reject.
        for i in range(n):
            exposure = float(np.dot(holdings[i], prices)) * float(margins[i])
            if exposure > float(capital[i]) + 1e-9:
                raise ValueError(
                    f"position of {institutions[i]!r} is not financeable at rest: "
                    f"margin * price * position = {exposure:.6g} exceeds capital "
                    f"{float(capital[i]):.6g}"
                )

    @property
    def n_institutions(self) -> int:
        return len(self.institution_ids)

    @property
    def n_assets(self) -> int:
        return len(self.asset_ids)

    @property
    def initial_portfolio_values(self) -> np.ndarray:
        """``V_i(0)``: marked value of each institution's portfolio at ``t = 0``."""
        return self.holdings @ self.prices

    @property
    def nominal_liabilities(self) -> np.ndarray:
        """``l_i``: total interbank liabilities of each institution."""
        return self.liabilities.sum(axis=1)


# ---------------------------------------------------------------------------
# Round record
# ---------------------------------------------------------------------------


def _clearing_summary(
    clearing: ClearingResult, institution_ids: Sequence[str]
) -> Dict[str, Any]:
    return {
        "payments": {
            institution_ids[i]: float(clearing.payments[i])
            for i in range(len(institution_ids))
        },
        "equity": {
            institution_ids[i]: float(clearing.equity[i])
            for i in range(len(institution_ids))
        },
        "total_shortfall": float(clearing.total_shortfall),
        "defaulted": [
            institution_ids[i]
            for i in range(len(institution_ids))
            if bool(clearing.defaulted[i])
        ],
        "causes": {
            institution_ids[i]: clearing.causes[i] for i in sorted(clearing.causes)
        },
    }


@dataclass(frozen=True)
class FireSaleRound:
    """One solved round of the coupled loop.

    ``prices`` are the prices the round's decisions were taken at; ``next_prices``
    are the prices after the round's sales. At a fixed point they coincide.
    """

    round: int
    prices: np.ndarray
    next_prices: np.ndarray
    capital: np.ndarray
    margins_in_force: np.ndarray
    portfolio_values: np.ndarray
    clearing: ClearingResult
    shortfall: np.ndarray
    liquidation_demand: np.ndarray
    sold_units: np.ndarray
    sold_value: np.ndarray
    holdings: np.ndarray
    cash: np.ndarray
    price_delta: float
    liquidation_delta: float
    delta: float
    stability_margin: float
    over_stability_limit: bool
    converged: bool

    def to_dict(self, institution_ids: Sequence[str], asset_ids: Sequence[str]) -> Dict[str, Any]:
        return {
            "round": int(self.round),
            "prices": {
                asset_ids[a]: float(self.prices[a]) for a in range(len(asset_ids))
            },
            "next_prices": {
                asset_ids[a]: float(self.next_prices[a])
                for a in range(len(asset_ids))
            },
            "capital": {
                institution_ids[i]: float(self.capital[i])
                for i in range(len(institution_ids))
            },
            "margins_in_force": {
                institution_ids[i]: float(self.margins_in_force[i])
                for i in range(len(institution_ids))
            },
            "portfolio_values": {
                institution_ids[i]: float(self.portfolio_values[i])
                for i in range(len(institution_ids))
            },
            "shortfall": {
                institution_ids[i]: float(self.shortfall[i])
                for i in range(len(institution_ids))
            },
            "aggregate_shortfall": float(self.clearing.total_shortfall),
            "defaults": [
                institution_ids[i]
                for i in range(len(institution_ids))
                if bool(self.clearing.defaulted[i])
            ],
            "liquidation_demand": {
                institution_ids[i]: float(self.liquidation_demand[i])
                for i in range(len(institution_ids))
            },
            "sold_value": {
                institution_ids[i]: float(self.sold_value[i])
                for i in range(len(institution_ids))
            },
            "sold_units": {
                institution_ids[i]: {
                    asset_ids[a]: float(self.sold_units[i, a])
                    for a in range(len(asset_ids))
                }
                for i in range(len(institution_ids))
            },
            "holdings": {
                institution_ids[i]: {
                    asset_ids[a]: float(self.holdings[i, a])
                    for a in range(len(asset_ids))
                }
                for i in range(len(institution_ids))
            },
            "cash": {
                institution_ids[i]: float(self.cash[i])
                for i in range(len(institution_ids))
            },
            "price_delta": float(self.price_delta),
            "liquidation_delta": float(self.liquidation_delta),
            "delta": float(self.delta),
            "stability_margin": float(self.stability_margin),
            "over_stability_limit": bool(self.over_stability_limit),
            "converged": bool(self.converged),
            "clearing": _clearing_summary(self.clearing, institution_ids),
        }


@dataclass(frozen=True)
class FireSaleAmplification:
    """The part of the outcome attributable to the fire-sale feedback.

    Every ``*_shortfall`` and ``*_loss`` field is ``None`` when the run it comes
    from did not reach a fixed point. A divergent run has no final balance sheet
    to compare, and a number derived from a partial path would be a fiction.
    """

    baseline_total_shortfall: Optional[float]
    total_shortfall: Optional[float]
    feedback_shortfall: Optional[float]
    baseline_mark_to_market_loss: Optional[float]
    total_mark_to_market_loss: Optional[float]
    feedback_mark_to_market_loss: Optional[float]
    baseline_defaults: List[str]
    total_defaults: List[str]
    feedback_caused_defaults: List[str]
    baseline_converged: bool
    baseline_diverged: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "baseline_total_shortfall": self.baseline_total_shortfall,
            "total_shortfall": self.total_shortfall,
            "feedback_shortfall": self.feedback_shortfall,
            "baseline_mark_to_market_loss": self.baseline_mark_to_market_loss,
            "total_mark_to_market_loss": self.total_mark_to_market_loss,
            "feedback_mark_to_market_loss": self.feedback_mark_to_market_loss,
            "baseline_defaults": list(self.baseline_defaults),
            "total_defaults": list(self.total_defaults),
            "feedback_caused_defaults": list(self.feedback_caused_defaults),
            "baseline_converged": bool(self.baseline_converged),
            "baseline_diverged": bool(self.baseline_diverged),
        }


@dataclass
class FireSaleResult:
    """Outcome of a coupled clearing / fire-sale fixed-point solve.

    When ``converged`` is false every ``final_*`` field is ``None``: the run has
    no fixed point to report and must not be read as one. ``path`` still carries
    every round that was solved, which is where the divergence is visible.
    """

    institution_ids: List[str]
    asset_ids: List[str]
    path: List[FireSaleRound]
    converged: bool
    diverged: bool
    divergence_reason: Optional[str]
    rounds: int
    tolerance: float
    final_prices: Optional[np.ndarray]
    final_holdings: Optional[np.ndarray]
    final_cash: Optional[np.ndarray]
    final_capital: Optional[np.ndarray]
    final_shortfall: Optional[np.ndarray]
    final_clearing: Optional[ClearingResult]
    final_defaults: List[str]
    cumulative_sold_units: Optional[np.ndarray]
    amplification: Optional[FireSaleAmplification] = None
    feedback_caused_defaults: List[str] = field(default_factory=list)

    @property
    def stability_limit_exceeded(self) -> bool:
        """Whether any solved round implied a ``lambda`` above its ``lambda*``."""
        return any(round_record.over_stability_limit for round_record in self.path)

    @property
    def final_total_shortfall(self) -> Optional[float]:
        if self.final_clearing is None:
            return None
        return float(self.final_clearing.total_shortfall)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "institution_ids": list(self.institution_ids),
            "asset_ids": list(self.asset_ids),
            "converged": bool(self.converged),
            "diverged": bool(self.diverged),
            "divergence_reason": self.divergence_reason,
            "rounds": int(self.rounds),
            "tolerance": float(self.tolerance),
            "final_prices": (
                None
                if self.final_prices is None
                else {
                    self.asset_ids[a]: float(self.final_prices[a])
                    for a in range(len(self.asset_ids))
                }
            ),
            "final_capital": (
                None
                if self.final_capital is None
                else {
                    self.institution_ids[i]: float(self.final_capital[i])
                    for i in range(len(self.institution_ids))
                }
            ),
            "final_holdings": (
                None
                if self.final_holdings is None
                else {
                    self.institution_ids[i]: {
                        self.asset_ids[a]: float(self.final_holdings[i, a])
                        for a in range(len(self.asset_ids))
                    }
                    for i in range(len(self.institution_ids))
                }
            ),
            "final_cash": (
                None
                if self.final_cash is None
                else {
                    self.institution_ids[i]: float(self.final_cash[i])
                    for i in range(len(self.institution_ids))
                }
            ),
            "final_shortfall": (
                None
                if self.final_shortfall is None
                else {
                    self.institution_ids[i]: float(self.final_shortfall[i])
                    for i in range(len(self.institution_ids))
                }
            ),
            "final_defaults": list(self.final_defaults),
            "final_total_shortfall": self.final_total_shortfall,
            "feedback_caused_defaults": list(self.feedback_caused_defaults),
            "stability_limit_exceeded": self.stability_limit_exceeded,
            "cumulative_sold_units": (
                None
                if self.cumulative_sold_units is None
                else {
                    self.institution_ids[i]: {
                        self.asset_ids[a]: float(self.cumulative_sold_units[i, a])
                        for a in range(len(self.asset_ids))
                    }
                    for i in range(len(self.institution_ids))
                }
            ),
            "amplification": (
                None if self.amplification is None else self.amplification.to_dict()
            ),
            "path": [
                round_record.to_dict(self.institution_ids, self.asset_ids)
                for round_record in self.path
            ],
        }


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------


class FireSaleSolver:
    """Iterates clearing and liquidation to a coupled fixed point.

    Args:
        scenario: The balance sheets, prices and frictions.
        tolerance: Convergence threshold on the dimensionless round-over-round
            change. Must be strictly positive.
        max_rounds: Round cap. Reaching it without convergence is reported as
            divergence, never as a large answer.
        stability_limit: Optional caller-supplied ``lambda*`` used in place of
            the derived per-position
            :func:`~backend.modules.risk.liquidity_spiral.stability_impact_limit`.
            When supplied it must be finite and strictly positive.
        clearing_tolerance: Passed through to the clearing engine.
        decompose_feedback: When true (the default), ``solve`` also runs the
            scenario with every ``lambda`` set to zero and reports the
            difference.
    """

    def __init__(
        self,
        scenario: FireSaleScenario,
        *,
        tolerance: float = DEFAULT_TOLERANCE,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        stability_limit: Optional[float] = None,
        clearing_tolerance: float = CLEARING_DEFAULT_TOLERANCE,
        decompose_feedback: bool = True,
    ) -> None:
        if not math.isfinite(tolerance) or tolerance <= 0.0:
            raise ValueError(f"tolerance must be strictly positive, got {tolerance}")
        if max_rounds < 1:
            raise ValueError(f"max_rounds must be at least 1, got {max_rounds}")
        if stability_limit is not None:
            if not math.isfinite(stability_limit) or stability_limit <= 0.0:
                raise ValueError(
                    f"stability_limit must be finite and strictly positive, got "
                    f"{stability_limit}"
                )
        if not math.isfinite(clearing_tolerance) or clearing_tolerance <= 0.0:
            raise ValueError(
                f"clearing_tolerance must be strictly positive, got "
                f"{clearing_tolerance}"
            )

        self.scenario = scenario
        self.tolerance = float(tolerance)
        self.max_rounds = int(max_rounds)
        self.stability_limit = stability_limit
        self.clearing_tolerance = float(clearing_tolerance)
        self.decompose_feedback = bool(decompose_feedback)

        self._layer = NetworkLayer(
            name="interbank", liabilities=scenario.liabilities, seniority=0
        )
        self._engine = MultiplexClearingEngine(
            [self._layer],
            node_ids=list(scenario.institution_ids),
            tolerance=self.clearing_tolerance,
        )
        self._asset_index = {
            asset_id: position
            for position, asset_id in enumerate(scenario.asset_ids)
        }
        self._order_indices: Dict[int, Tuple[int, ...]] = {
            position: tuple(
                self._asset_index[asset_id]
                for asset_id in scenario.liquidation_order.get(
                    scenario.institution_ids[position], ()
                )
            )
            for position in range(scenario.n_institutions)
        }

        # The margin in force is computed by the spiral's own margin function.
        # Its holder-state fields are dummies because `margin_for` depends only
        # on the realised volatility, the base margin, the sensitivity and the
        # bounds; `position = capital = 0` is a valid, financeable resting state.
        # `price` carries the portfolio's t=0 value so that the mark-to-market
        # change passed to `margin_for` is read as a portfolio return.
        self._spiral: List[SpiralParameters] = []
        initial_values = scenario.initial_portfolio_values
        for i in range(scenario.n_institutions):
            scale = float(initial_values[i])
            self._spiral.append(
                SpiralParameters(
                    price=scale if scale > 0.0 else 1.0,
                    position=0.0,
                    capital=0.0,
                    margin=float(scenario.margins[i]),
                    price_impact=0.0,
                    margin_sensitivity=float(scenario.margin_sensitivity[i]),
                    reference_volatility=float(scenario.reference_volatility),
                    min_margin=float(scenario.min_margin),
                    max_margin=float(scenario.max_margin),
                )
            )

    # -- public helpers ----------------------------------------------------

    def endowments_for(
        self,
        holdings: np.ndarray,
        cash: np.ndarray,
        prices: np.ndarray,
    ) -> np.ndarray:
        """Marked external assets handed to the clearing engine.

        ``e_i = endowments_i + cash_i + sum_a holdings[i, a] * prices[a]``. Every
        term is non-negative by construction, so no clamp is applied and a
        negative result would (correctly) be rejected by the clearing engine.
        """
        h = np.asarray(holdings, dtype=float)
        expected_shape = (self.scenario.n_institutions, self.scenario.n_assets)
        if h.shape != expected_shape:
            raise ValueError(
                f"holdings must have shape {expected_shape}, got {h.shape}"
            )
        k = np.asarray(cash, dtype=float).reshape(-1)
        if k.shape[0] != self.scenario.n_institutions:
            raise ValueError(
                f"cash has length {k.shape[0]} but "
                f"{self.scenario.n_institutions} was expected"
            )
        p = np.asarray(prices, dtype=float).reshape(-1)
        if p.shape[0] != self.scenario.n_assets:
            raise ValueError(
                f"prices has length {p.shape[0]} but {self.scenario.n_assets} "
                "was expected"
            )
        if not (np.all(np.isfinite(h)) and np.all(np.isfinite(k)) and np.all(np.isfinite(p))):
            raise ValueError("holdings, cash and prices must all be finite")
        return self.scenario.endowments + k + h @ p

    def solve(self) -> FireSaleResult:
        """Run the coupled loop, then the ``lambda = 0`` isolation counterfactual."""
        result = self._run()
        if self.decompose_feedback:
            baseline_scenario = replace(
                self.scenario,
                price_impacts=np.zeros_like(self.scenario.price_impacts),
            )
            baseline_solver = FireSaleSolver(
                baseline_scenario,
                tolerance=self.tolerance,
                max_rounds=self.max_rounds,
                stability_limit=self.stability_limit,
                clearing_tolerance=self.clearing_tolerance,
                decompose_feedback=False,
            )
            baseline = baseline_solver._run()
            result.amplification = _build_amplification(
                self.scenario, result, baseline
            )
            result.feedback_caused_defaults = list(
                result.amplification.feedback_caused_defaults
            )
        return result

    # -- internals ---------------------------------------------------------

    def _margin_in_force(self, position: int, mark_change: float) -> float:
        return float(self._spiral[position].margin_for(mark_change))

    def _stability_diagnostics(
        self, prices: np.ndarray, holdings: np.ndarray, margins: np.ndarray
    ) -> Tuple[float, bool]:
        """Minimum headroom to ``lambda*`` and whether any position exceeds it.

        Headroom is ``1 - lambda / lambda*``, reported as ``1.0`` when there is no
        constrained position at all (and when ``lambda*`` is unbounded): no
        position means no spiral, which is full headroom rather than an
        undefined one.
        """
        headroom = 1.0
        over = False
        impacts = self.scenario.price_impacts
        for i in range(self.scenario.n_institutions):
            for a in range(self.scenario.n_assets):
                position = float(holdings[i, a])
                if position <= 0.0:
                    continue
                if self.stability_limit is not None:
                    limit = float(self.stability_limit)
                else:
                    limit = stability_impact_limit(
                        float(prices[a]), position, float(margins[i])
                    )
                impact = float(impacts[a])
                if math.isinf(limit):
                    headroom = min(headroom, 1.0)
                else:
                    headroom = min(headroom, 1.0 - impact / limit)
                if impact > limit:
                    over = True
        return float(headroom), over

    def _run(self) -> FireSaleResult:
        scenario = self.scenario
        n = scenario.n_institutions
        a_count = scenario.n_assets
        base_prices = scenario.prices
        shock = scenario.price_shock
        initial_holdings = scenario.holdings

        prices = base_prices + shock
        holdings = scenario.holdings.copy()
        cash = np.zeros(n, dtype=float)
        cumulative_sold = np.zeros((n, a_count), dtype=float)
        cumulative_units = np.zeros(a_count, dtype=float)
        path: List[FireSaleRound] = []

        price_scale = max(float(np.max(np.abs(base_prices))), 1e-12)
        asset_scale = max(
            1.0,
            float(
                np.max(
                    scenario.endowments
                    + (initial_holdings @ base_prices)
                    + scenario.nominal_liabilities
                )
            ),
        )

        converged = False
        diverged = False
        reason: Optional[str] = None
        rounds = 0

        for round_index in range(1, self.max_rounds + 1):
            rounds = round_index

            mark_change = initial_holdings @ (prices - base_prices)
            capital = scenario.capital + mark_change
            margins = np.array(
                [
                    self._margin_in_force(i, float(mark_change[i]))
                    for i in range(n)
                ],
                dtype=float,
            )
            headroom, over = self._stability_diagnostics(prices, holdings, margins)

            endowments = self.endowments_for(holdings, cash, prices)
            clearing = self._engine.clear(endowments, record_edges=False)
            shortfall = np.maximum(
                clearing.nominal_liabilities - clearing.payments, 0.0
            )

            portfolio_value = holdings @ prices
            financeable = (
                np.where(capital > 0.0, capital, 0.0) / margins
            )
            margin_need = np.maximum(portfolio_value - financeable, 0.0)
            demand = np.maximum(margin_need, shortfall)

            sold = np.zeros((n, a_count), dtype=float)
            for i in range(n):
                if demand[i] <= 0.0 or portfolio_value[i] <= 0.0:
                    continue
                order = self._order_indices.get(i, ())
                if not order:
                    fraction = min(
                        1.0, float(demand[i]) / float(portfolio_value[i])
                    )
                    sold[i] = fraction * holdings[i]
                    continue
                remaining = float(demand[i])
                for asset_index in order:
                    if remaining <= 0.0:
                        break
                    available = float(holdings[i, asset_index]) * float(
                        prices[asset_index]
                    )
                    if available <= 0.0:
                        continue
                    taken = min(available, remaining)
                    sold[i, asset_index] = taken / float(prices[asset_index])
                    remaining -= taken

            sold_value = sold @ prices
            holdings = holdings - sold
            cumulative_sold += sold
            cumulative_units += sold.sum(axis=0)
            cash = cash + sold_value

            next_prices = (
                base_prices + shock - scenario.price_impacts * cumulative_units
            )
            if np.any(next_prices <= 0.0):
                diverged = True
                offender = int(np.argmin(next_prices))
                reason = (
                    f"price_floor: asset {scenario.asset_ids[offender]!r} would "
                    f"price at {float(next_prices[offender]):.6g} after round "
                    f"{round_index}; no positive-price equilibrium exists"
                )
                break

            price_delta = float(np.max(np.abs(next_prices - prices))) / price_scale
            liquidation_delta = float(np.max(sold_value)) / asset_scale
            delta = max(price_delta, liquidation_delta)

            path.append(
                FireSaleRound(
                    round=round_index,
                    prices=prices.copy(),
                    next_prices=next_prices.copy(),
                    capital=capital.copy(),
                    margins_in_force=margins.copy(),
                    portfolio_values=portfolio_value.copy(),
                    clearing=clearing,
                    shortfall=shortfall.copy(),
                    liquidation_demand=demand.copy(),
                    sold_units=sold.copy(),
                    sold_value=sold_value.copy(),
                    holdings=holdings.copy(),
                    cash=cash.copy(),
                    price_delta=price_delta,
                    liquidation_delta=liquidation_delta,
                    delta=delta,
                    stability_margin=headroom,
                    over_stability_limit=over,
                    converged=delta <= self.tolerance,
                )
            )
            prices = next_prices

            if delta <= self.tolerance:
                converged = True
                break

        if not converged and not diverged:
            diverged = True
            reason = (
                f"round_cap_reached: no fixed point within {self.max_rounds} rounds"
            )

        result = FireSaleResult(
            institution_ids=list(scenario.institution_ids),
            asset_ids=list(scenario.asset_ids),
            path=path,
            converged=converged,
            diverged=diverged,
            divergence_reason=reason,
            rounds=rounds,
            tolerance=self.tolerance,
            final_prices=None,
            final_holdings=None,
            final_cash=None,
            final_capital=None,
            final_shortfall=None,
            final_clearing=None,
            final_defaults=[],
            cumulative_sold_units=None,
        )

        if not converged:
            return result

        # Re-evaluate once at the reported fixed-point prices so the final
        # clearing, capital and shortfall all belong to the same price vector.
        final_mark_change = initial_holdings @ (prices - base_prices)
        final_capital = scenario.capital + final_mark_change
        final_endowments = self.endowments_for(holdings, cash, prices)
        final_clearing = self._engine.clear(final_endowments, record_edges=False)
        final_shortfall = np.maximum(
            final_clearing.nominal_liabilities - final_clearing.payments, 0.0
        )

        result.final_prices = prices.copy()
        result.final_holdings = holdings.copy()
        result.final_cash = cash.copy()
        result.final_capital = final_capital.copy()
        result.final_shortfall = final_shortfall.copy()
        result.final_clearing = final_clearing
        result.final_defaults = [
            scenario.institution_ids[i]
            for i in range(n)
            if bool(final_clearing.defaulted[i])
        ]
        result.cumulative_sold_units = cumulative_sold.copy()
        return result


def _build_amplification(
    scenario: FireSaleScenario,
    result: FireSaleResult,
    baseline: FireSaleResult,
) -> FireSaleAmplification:
    """Difference between the full run and the ``lambda = 0`` counterfactual."""
    baseline_converged = bool(baseline.converged)
    total_converged = bool(result.converged)

    baseline_shortfall: Optional[float] = None
    baseline_loss: Optional[float] = None
    baseline_defaults: List[str] = list(baseline.final_defaults)
    if baseline_converged and baseline.final_clearing is not None:
        baseline_shortfall = float(baseline.final_clearing.total_shortfall)
        baseline_loss = float(
            np.sum(scenario.capital - baseline.final_capital)
        )

    total_shortfall: Optional[float] = None
    total_loss: Optional[float] = None
    total_defaults: List[str] = list(result.final_defaults)
    if total_converged and result.final_clearing is not None:
        total_shortfall = float(result.final_clearing.total_shortfall)
        total_loss = float(np.sum(scenario.capital - result.final_capital))

    if total_shortfall is None or baseline_shortfall is None:
        feedback_shortfall: Optional[float] = None
        feedback_loss: Optional[float] = None
        feedback_defaults: List[str] = []
    else:
        feedback_shortfall = total_shortfall - baseline_shortfall
        feedback_loss = (
            None if total_loss is None or baseline_loss is None
            else total_loss - baseline_loss
        )
        feedback_defaults = [
            institution_id
            for institution_id in total_defaults
            if institution_id not in set(baseline_defaults)
        ]

    return FireSaleAmplification(
        baseline_total_shortfall=baseline_shortfall,
        total_shortfall=total_shortfall,
        feedback_shortfall=feedback_shortfall,
        baseline_mark_to_market_loss=baseline_loss,
        total_mark_to_market_loss=total_loss,
        feedback_mark_to_market_loss=feedback_loss,
        baseline_defaults=baseline_defaults,
        total_defaults=total_defaults,
        feedback_caused_defaults=feedback_defaults,
        baseline_converged=baseline_converged,
        baseline_diverged=bool(baseline.diverged),
    )


def solve_fire_sale(
    scenario: FireSaleScenario,
    *,
    tolerance: float = DEFAULT_TOLERANCE,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    stability_limit: Optional[float] = None,
    clearing_tolerance: float = CLEARING_DEFAULT_TOLERANCE,
) -> FireSaleResult:
    """Convenience wrapper: solve a scenario in one call."""
    return FireSaleSolver(
        scenario,
        tolerance=tolerance,
        max_rounds=max_rounds,
        stability_limit=stability_limit,
        clearing_tolerance=clearing_tolerance,
    ).solve()
