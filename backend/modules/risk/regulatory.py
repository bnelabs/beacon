"""Basel III regulatory ratios as the unit of account for systemic stress.

Why this module exists
----------------------

Clearing (:mod:`backend.modules.risk.clearing`) answers *who fails and in what
order*; the liquidity spiral
(:mod:`backend.modules.risk.liquidity_spiral`) answers *how far prices have to
fall* for deleveraging to be feasible. Neither answers the question a supervisor
actually asks: does this institution still meet the Basel III minimum after the
scenario? A shortfall in dollars is not self-interpreting -- a 500m loss is
survivable for one balance sheet and fatal for another. This module translates
the outputs of the systemic models into the three ratios that regulators enforce:

* **Liquidity Coverage Ratio** (LCR): ``HQLA / net cash outflows`` over a
  30-day stress horizon, minimum 100%.
* **Net Stable Funding Ratio** (NSFR): ``available stable funding / required
  stable funding``, minimum 100%.
* **Leverage ratio**: ``Tier 1 capital / total exposure measure``, minimum 3%.

What IS implemented
-------------------

* The **LCR** with the standard HQLA haircuts (Level 1 100%, Level 2A 85%,
  Level 2B 50%), the 40%-of-HQLA Level 2 aggregate cap *after* haircuts, and the
  75%-of-outflows inflow cap. Both caps are reported explicitly as flags rather
  than applied silently.
* The **NSFR** with table-driven ASF and RSF factors over a documented subset of
  the Basel categories.
* The **leverage ratio** with on-balance-sheet assets, a caller-supplied
  derivative exposure, and off-balance-sheet items at their credit conversion
  factors (CCFs).
* **Stress translation**: :func:`translate_systemic_stress` consumes a
  :class:`~backend.modules.risk.clearing.ClearingResult` and an explicit
  price-decline fraction and returns a per-institution before/after table of LCR,
  NSFR and leverage, the thresholds breached, and post-stress Tier 1 capital.

Every rate and factor is a module-level named constant in an explicit table
(:data:`OUTFLOW_RATES`, :data:`INFLOW_RATES`, :data:`ASF_FACTORS`,
:data:`RSF_FACTORS`, :data:`CREDIT_CONVERSION_FACTORS`) so that no Basel
threshold is buried in an expression. Unknown category names are rejected rather
than ignored: silently dropping a category would understate outflows and
overstate capital.

What is NOT implemented (stated plainly so the numbers are not over-trusted)
----------------------------------------------------------------------------

* **No LCR by significant currency.** The Basel standard requires an LCR in each
  currency that is significant to the bank; only one aggregate is computed, and
  all amounts are assumed to be in a single unit of account. A bank with a
  mismatched currency book can pass this aggregate while failing a currency LCR.
* **No Basel IV output floor**, no G-SIB buffer, no TLAC/MREL, no
  countercyclical or conservation buffer, and no Pillar 2 add-on. ``compliant``
  compares against the bare Pillar 1 minimum only.
* **No granular residual-maturity ladder for the NSFR.** Maturities are bucketed
  only into ``< 1 year`` and ``>= 1 year``. The Basel RSF table's finer buckets
  (for example the six-month and one-year distinctions) are collapsed.
* **ASF/RSF categories are a documented subset**, not the full Basel table.
  Deposits from credit unions, central-bank funding, and several secured-funding
  lines are absent; a caller must map them onto the modelled categories or not
  report an NSFR for that institution.
* **No Level 2B 15% sub-cap.** Only the 40% aggregate Level 2 cap is applied, so
  a portfolio that is almost entirely Level 2B can pass here and fail Basel.
* **No treatment of central bank reserves beyond Level 1**, and no committed
  central-bank facilities, no intraday liquidity, and none of the LCR monitoring
  tools (maturity mismatch, concentration of funding, available unencumbered
  assets, LCR by counterparty).
* **The leverage ratio takes the derivative exposure as an input.** No SA-CCR
  replacement-cost / potential-future-exposure calculation is performed, and no
  collateral netting is applied.
* **No FX translation or hedging.** Amounts are consumed as given.

The stress accounting is a stated simplification
------------------------------------------------

:func:`translate_systemic_stress` applies a single loss to both the capital and
the liquidity view of each institution:

1. ``clearing_loss`` is the institution's ``losses_by_creditor`` entry from the
   supplied :class:`ClearingResult <backend.modules.risk.clearing.ClearingResult>`.
   ``price_loss`` is ``price_decline`` times the caller-supplied
   ``price_sensitive_assets``. Both magnitudes come from the caller; this module
   never invents, calibrates or defaults a shock.
2. Post-stress Tier 1 capital is ``tier1_before - (clearing_loss + price_loss)``,
   floored at zero (reported via ``capital_exhausted``). The total exposure
   measure falls by the same loss, floored at zero.
3. HQLA is assumed to absorb the loss in cash, drawing down Level 1 first, then
   Level 2A, then Level 2B, each floored at zero. Funding, deposit and
   committed-facility *categories are held unchanged*: the scenario does not
   re-run-off the funding book. That is deliberately conservative on the outflow
   side only if the caller separately supplies stressed categories; on its own it
   does not invent a deposit run.
4. Post-stress ASF removes the loss from the Tier 1 capital category (at its
   100% factor), and post-stress RSF removes the loss from the declared HQLA
   asset categories with the same Level 1 -> 2A -> 2B waterfall, then from other
   assets.

This is **one defensible treatment, not the only one**. A credit write-down need
not be funded out of HQLA, and applying the same loss to capital, to the
exposure measure and to HQLA is conservative by construction. Alternatives
(separate cash-loss and mark-down channels, behavioural deposit run-off,
collateral haircut widening, funding-mix migration) are deliberately left to the
caller because each requires assumptions this module refuses to make silently.
"""

from __future__ import annotations

import math
from collections.abc import Mapping as AbcMapping
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from backend.exceptions import DataQualityError
from backend.modules.risk.clearing import ClearingResult

__all__ = [
    # Thresholds
    "MIN_LCR",
    "MIN_NSFR",
    "MIN_LEVERAGE_RATIO",
    "LEVEL2_HQLA_CAP",
    "INFLOW_CAP",
    # HQLA haircuts
    "HQLA_LEVEL1_HAIRCUT",
    "HQLA_LEVEL2A_HAIRCUT",
    "HQLA_LEVEL2B_HAIRCUT",
    # LCR outflow categories and rates
    "OUTFLOW_STABLE_RETAIL_DEPOSITS",
    "OUTFLOW_LESS_STABLE_RETAIL_DEPOSITS",
    "OUTFLOW_WHOLESALE_OPERATIONAL",
    "OUTFLOW_WHOLESALE_NON_OPERATIONAL_CORPORATE",
    "OUTFLOW_WHOLESALE_NON_OPERATIONAL_FINANCIAL",
    "OUTFLOW_SECURED_FUNDING_LEVEL1",
    "OUTFLOW_SECURED_FUNDING_LEVEL2A",
    "OUTFLOW_SECURED_FUNDING_LEVEL2B",
    "OUTFLOW_COMMITTED_FACILITIES_RETAIL",
    "OUTFLOW_COMMITTED_FACILITIES_CORPORATE",
    "OUTFLOW_COMMITTED_FACILITIES_FINANCIAL_CREDIT",
    "OUTFLOW_COMMITTED_FACILITIES_FINANCIAL_LIQUIDITY",
    "OUTFLOW_OTHER",
    "OUTFLOW_RATES",
    # LCR inflow categories and rates
    "INFLOW_RETAIL_LOANS",
    "INFLOW_SECURED_LENDING_LEVEL1",
    "INFLOW_SECURED_LENDING_LEVEL2A",
    "INFLOW_SECURED_LENDING_LEVEL2B",
    "INFLOW_WHOLESALE_OPERATIONAL",
    "INFLOW_WHOLESALE_NON_OPERATIONAL",
    "INFLOW_OTHER",
    "INFLOW_RATES",
    # NSFR ASF categories and factors
    "ASF_TIER1_CAPITAL",
    "ASF_TIER2_CAPITAL",
    "ASF_STABLE_RETAIL_DEPOSITS",
    "ASF_LESS_STABLE_RETAIL_DEPOSITS",
    "ASF_WHOLESALE_SHORT_TERM",
    "ASF_WHOLESALE_LONG_TERM",
    "ASF_OTHER_LIABILITIES",
    "ASF_FACTORS",
    # NSFR RSF categories and factors
    "RSF_HQLA_LEVEL1",
    "RSF_HQLA_LEVEL2A",
    "RSF_HQLA_LEVEL2B",
    "RSF_LOANS_FINANCIAL_SHORT",
    "RSF_LOANS_FINANCIAL_LONG",
    "RSF_LOANS_CORPORATE_SHORT",
    "RSF_LOANS_CORPORATE_LONG",
    "RSF_LOANS_RETAIL_SHORT",
    "RSF_LOANS_RETAIL_LONG",
    "RSF_UNDRAWN_COMMITTED_FACILITIES",
    "RSF_OTHER_ASSETS",
    "RSF_FACTORS",
    # Leverage CCF categories and factors
    "CCF_UNCONDITIONALLY_CANCELLABLE",
    "CCF_SHORT_TERM_COMMITMENTS",
    "CCF_LONG_TERM_COMMITMENTS",
    "CCF_DIRECT_CREDIT_SUBSTITUTES",
    "CCF_TRANSACTION_RELATED_CONTINGENCIES",
    "CREDIT_CONVERSION_FACTORS",
    # Dataclasses
    "LiquidityPosition",
    "LiquidityCoverageResult",
    "StableFundingPosition",
    "FactorContribution",
    "NetStableFundingResult",
    "LeveragePosition",
    "LeverageRatioResult",
    "InstitutionState",
    "InstitutionStressResult",
    "StressTranslationResult",
    # Functions
    "compute_lcr",
    "compute_nsfr",
    "compute_leverage_ratio",
    "translate_systemic_stress",
]

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

MIN_LCR = 1.0
"""Basel III minimum LCR: HQLA must cover 100% of net cash outflows."""

MIN_NSFR = 1.0
"""Basel III minimum NSFR: available stable funding must cover 100% of required."""

MIN_LEVERAGE_RATIO = 0.03
"""Basel III minimum leverage ratio: Tier 1 / exposure measure >= 3%."""

LEVEL2_HQLA_CAP = 0.40
"""Level 2A + Level 2B may be at most 40% of HQLA *after* haircuts.

When the cap binds at equality, the included Level 2 solves
``L2 = LEVEL2_HQLA_CAP * (L1 + L2)``, so ``L2 = L1 * 0.4 / 0.6 = (2/3) L1``.
"""

INFLOW_CAP = 0.75
"""Inflows count towards net cash outflows only up to 75% of outflows."""

HQLA_LEVEL1_HAIRCUT = 0.00
HQLA_LEVEL2A_HAIRCUT = 0.15
HQLA_LEVEL2B_HAIRCUT = 0.50
"""Basel III HQLA haircuts: Level 1 counts at 100%, 2A at 85%, 2B at 50%."""

# ---------------------------------------------------------------------------
# LCR: outflow categories and run-off rates
# ---------------------------------------------------------------------------

OUTFLOW_STABLE_RETAIL_DEPOSITS = "stable_retail_deposits"
OUTFLOW_LESS_STABLE_RETAIL_DEPOSITS = "less_stable_retail_deposits"
OUTFLOW_WHOLESALE_OPERATIONAL = "unsecured_wholesale_operational"
OUTFLOW_WHOLESALE_NON_OPERATIONAL_CORPORATE = (
    "unsecured_wholesale_non_operational_corporate"
)
OUTFLOW_WHOLESALE_NON_OPERATIONAL_FINANCIAL = (
    "unsecured_wholesale_non_operational_financial"
)
OUTFLOW_SECURED_FUNDING_LEVEL1 = "secured_funding_level1"
OUTFLOW_SECURED_FUNDING_LEVEL2A = "secured_funding_level2a"
OUTFLOW_SECURED_FUNDING_LEVEL2B = "secured_funding_level2b"
OUTFLOW_COMMITTED_FACILITIES_RETAIL = "committed_facilities_retail"
OUTFLOW_COMMITTED_FACILITIES_CORPORATE = "committed_facilities_corporate"
OUTFLOW_COMMITTED_FACILITIES_FINANCIAL_CREDIT = (
    "committed_facilities_financial_credit"
)
OUTFLOW_COMMITTED_FACILITIES_FINANCIAL_LIQUIDITY = (
    "committed_facilities_financial_liquidity"
)
OUTFLOW_OTHER = "other_outflows"

OUTFLOW_RATES: Mapping[str, float] = {
    # Insured / guaranteed retail deposits are the most stable funding.
    OUTFLOW_STABLE_RETAIL_DEPOSITS: 0.05,
    # Uninsured retail deposits: a higher run-off assumption.
    OUTFLOW_LESS_STABLE_RETAIL_DEPOSITS: 0.10,
    # Unsecured wholesale funding from operational relationships.
    OUTFLOW_WHOLESALE_OPERATIONAL: 0.25,
    # Non-operational wholesale from non-financial corporates, sovereigns,
    # PSEs and MDBs.
    OUTFLOW_WHOLESALE_NON_OPERATIONAL_CORPORATE: 0.40,
    # Non-operational wholesale from other entities, including financials.
    OUTFLOW_WHOLESALE_NON_OPERATIONAL_FINANCIAL: 1.00,
    # Secured funding is charged by the quality of the encumbered collateral.
    OUTFLOW_SECURED_FUNDING_LEVEL1: 0.00,
    OUTFLOW_SECURED_FUNDING_LEVEL2A: 0.15,
    OUTFLOW_SECURED_FUNDING_LEVEL2B: 0.50,
    # Undrawn committed facilities by counterparty type.
    OUTFLOW_COMMITTED_FACILITIES_RETAIL: 0.05,
    OUTFLOW_COMMITTED_FACILITIES_CORPORATE: 0.10,
    OUTFLOW_COMMITTED_FACILITIES_FINANCIAL_CREDIT: 0.40,
    OUTFLOW_COMMITTED_FACILITIES_FINANCIAL_LIQUIDITY: 1.00,
    # Residual "anything else" bucket, charged at 100% so that omitting a
    # category in the caller's favour is never the default.
    OUTFLOW_OTHER: 1.00,
}
"""Basel III 30-day run-off factors. Amounts are contractual balances."""

# ---------------------------------------------------------------------------
# LCR: inflow categories and rates
# ---------------------------------------------------------------------------

INFLOW_RETAIL_LOANS = "retail_loans"
INFLOW_SECURED_LENDING_LEVEL1 = "secured_lending_level1"
INFLOW_SECURED_LENDING_LEVEL2A = "secured_lending_level2a"
INFLOW_SECURED_LENDING_LEVEL2B = "secured_lending_level2b"
INFLOW_WHOLESALE_OPERATIONAL = "wholesale_operational_inflows"
INFLOW_WHOLESALE_NON_OPERATIONAL = "wholesale_non_operational_inflows"
INFLOW_OTHER = "other_inflows"

INFLOW_RATES: Mapping[str, float] = {
    # The 50% retail cap is embedded in the rate: a 50% factor means only half
    # the contractual inflow is recognised.
    INFLOW_RETAIL_LOANS: 0.50,
    # Secured lending inflows are charged by the quality of the collateral
    # received, mirroring the secured-funding outflow table.
    INFLOW_SECURED_LENDING_LEVEL1: 0.00,
    INFLOW_SECURED_LENDING_LEVEL2A: 0.15,
    INFLOW_SECURED_LENDING_LEVEL2B: 0.50,
    INFLOW_WHOLESALE_OPERATIONAL: 0.50,
    INFLOW_WHOLESALE_NON_OPERATIONAL: 1.00,
    INFLOW_OTHER: 1.00,
}
"""Basel III inflow factors. The 75% aggregate cap is applied separately."""

# ---------------------------------------------------------------------------
# NSFR: Available Stable Funding factors
# ---------------------------------------------------------------------------

ASF_TIER1_CAPITAL = "tier1_capital"
ASF_TIER2_CAPITAL = "tier2_capital"
ASF_STABLE_RETAIL_DEPOSITS = "stable_retail_deposits"
ASF_LESS_STABLE_RETAIL_DEPOSITS = "less_stable_retail_deposits"
ASF_WHOLESALE_SHORT_TERM = "wholesale_funding_under_1y"
ASF_WHOLESALE_LONG_TERM = "wholesale_funding_over_1y"
ASF_OTHER_LIABILITIES = "other_liabilities"

ASF_FACTORS: Mapping[str, float] = {
    ASF_TIER1_CAPITAL: 1.00,
    ASF_TIER2_CAPITAL: 1.00,
    ASF_STABLE_RETAIL_DEPOSITS: 0.95,
    ASF_LESS_STABLE_RETAIL_DEPOSITS: 0.90,
    # Wholesale funding is split only into < 1 year and >= 1 year.
    ASF_WHOLESALE_SHORT_TERM: 0.50,
    ASF_WHOLESALE_LONG_TERM: 1.00,
    ASF_OTHER_LIABILITIES: 0.00,
}
"""Basel III ASF factors. Amounts are liabilities and capital balances."""

# ---------------------------------------------------------------------------
# NSFR: Required Stable Funding factors
# ---------------------------------------------------------------------------

RSF_HQLA_LEVEL1 = "hqla_level1"
RSF_HQLA_LEVEL2A = "hqla_level2a"
RSF_HQLA_LEVEL2B = "hqla_level2b"
RSF_LOANS_FINANCIAL_SHORT = "loans_financial_under_1y"
RSF_LOANS_FINANCIAL_LONG = "loans_financial_over_1y"
RSF_LOANS_CORPORATE_SHORT = "loans_corporate_under_1y"
RSF_LOANS_CORPORATE_LONG = "loans_corporate_over_1y"
RSF_LOANS_RETAIL_SHORT = "loans_retail_under_1y"
RSF_LOANS_RETAIL_LONG = "loans_retail_over_1y"
RSF_UNDRAWN_COMMITTED_FACILITIES = "undrawn_committed_facilities"
RSF_OTHER_ASSETS = "other_assets"

RSF_FACTORS: Mapping[str, float] = {
    RSF_HQLA_LEVEL1: 0.05,
    RSF_HQLA_LEVEL2A: 0.15,
    RSF_HQLA_LEVEL2B: 0.50,
    # Short-dated claims on financial institutions are the most runnable.
    RSF_LOANS_FINANCIAL_SHORT: 0.15,
    RSF_LOANS_FINANCIAL_LONG: 1.00,
    RSF_LOANS_CORPORATE_SHORT: 0.50,
    RSF_LOANS_CORPORATE_LONG: 0.85,
    RSF_LOANS_RETAIL_SHORT: 0.50,
    RSF_LOANS_RETAIL_LONG: 0.85,
    # Undrawn committed facilities are charged on the undrawn amount.
    RSF_UNDRAWN_COMMITTED_FACILITIES: 0.05,
    # Residual bucket at 100%, again so omission is never favourable.
    RSF_OTHER_ASSETS: 1.00,
}
"""Basel III RSF factors. Amounts are asset carrying values."""

# ---------------------------------------------------------------------------
# Leverage ratio: off-balance-sheet credit conversion factors
# ---------------------------------------------------------------------------

CCF_UNCONDITIONALLY_CANCELLABLE = "unconditionally_cancellable_commitments"
CCF_SHORT_TERM_COMMITMENTS = "commitments_under_1y"
CCF_LONG_TERM_COMMITMENTS = "commitments_over_1y"
CCF_DIRECT_CREDIT_SUBSTITUTES = "direct_credit_substitutes"
CCF_TRANSACTION_RELATED_CONTINGENCIES = "transaction_related_contingencies"

CREDIT_CONVERSION_FACTORS: Mapping[str, float] = {
    CCF_UNCONDITIONALLY_CANCELLABLE: 0.10,
    CCF_SHORT_TERM_COMMITMENTS: 0.20,
    CCF_LONG_TERM_COMMITMENTS: 0.50,
    CCF_DIRECT_CREDIT_SUBSTITUTES: 1.00,
    CCF_TRANSACTION_RELATED_CONTINGENCIES: 0.50,
}
"""Basel III leverage-ratio CCFs. Amounts are the nominal off-balance-sheet
exposures before conversion."""

_TOLERANCE = 1e-12
"""Relative slack for "did this cap bind" tests, to keep exact arithmetic from
being reported as binding because of floating-point representation."""


# ---------------------------------------------------------------------------
# Validation helpers -- fail closed, never an interpolated or defaulted number
# ---------------------------------------------------------------------------


def _finite(value: Any, name: str) -> float:
    """Return ``value`` as a float, rejecting anything non-finite.

    A NaN or infinity propagating through a ratio produces a number that looks
    like an answer and is not one, so it is refused at the boundary.
    """
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DataQualityError(
            f"{name} must be a real number, got {value!r}",
            context={"field": name, "value": repr(value)},
            cause=exc,
        ) from exc
    if not math.isfinite(number):
        raise DataQualityError(
            f"{name} must be finite, got {number!r}",
            context={"field": name, "value": repr(value)},
        )
    return number


def _non_negative(value: Any, name: str) -> float:
    """Return ``value`` as a finite, non-negative float."""
    number = _finite(value, name)
    if number < 0.0:
        raise DataQualityError(
            f"{name} must be non-negative, got {number!r}",
            context={"field": name, "value": number},
        )
    return number


def _category_table(
    mapping: Mapping[str, Any], table: Mapping[str, float], name: str
) -> Dict[str, float]:
    """Validate a category -> amount mapping against a named-factor table.

    Unknown categories raise: ignoring one would silently drop an outflow or an
    asset, which is exactly the failure mode that turns a wrong number into a
    plausible one.
    """
    if not isinstance(mapping, AbcMapping):
        raise ValueError(
            f"{name} must be a mapping of category to amount, got "
            f"{type(mapping).__name__}"
        )
    validated: Dict[str, float] = {}
    for key, value in mapping.items():
        if key not in table:
            raise ValueError(
                f"{name} contains unknown category {key!r}; known categories are "
                f"{sorted(table)}"
            )
        validated[str(key)] = _non_negative(value, f"{name}[{key!r}]")
    return validated


def _capped_at(after: float, before: float) -> bool:
    """Whether ``after`` is strictly below ``before`` beyond rounding slack."""
    return after < before - _TOLERANCE * max(1.0, abs(before))


# ---------------------------------------------------------------------------
# Input containers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LiquidityPosition:
    """One institution's 30-day LCR balance sheet.

    Attributes:
        level1_assets: Level 1 HQLA carrying value (central bank reserves,
            sovereigns, etc.). Counts at 100% after its (zero) haircut.
        level2a_assets: Level 2A carrying value. Counts at 85%.
        level2b_assets: Level 2B carrying value. Counts at 50%.
        outflows_by_category: Contractual 30-day outflow balances keyed by the
            constants in :data:`OUTFLOW_RATES`. Unlisted categories are rejected.
        inflows_by_category: Contractual 30-day inflow balances keyed by the
            constants in :data:`INFLOW_RATES`.
    """

    level1_assets: float = 0.0
    level2a_assets: float = 0.0
    level2b_assets: float = 0.0
    outflows_by_category: Mapping[str, float] = field(default_factory=dict)
    inflows_by_category: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "level1_assets", _non_negative(self.level1_assets, "level1_assets")
        )
        object.__setattr__(
            self, "level2a_assets", _non_negative(self.level2a_assets, "level2a_assets")
        )
        object.__setattr__(
            self, "level2b_assets", _non_negative(self.level2b_assets, "level2b_assets")
        )
        object.__setattr__(
            self,
            "outflows_by_category",
            _category_table(
                self.outflows_by_category, OUTFLOW_RATES, "outflows_by_category"
            ),
        )
        object.__setattr__(
            self,
            "inflows_by_category",
            _category_table(
                self.inflows_by_category, INFLOW_RATES, "inflows_by_category"
            ),
        )

    @property
    def gross_hqla(self) -> float:
        """Sum of HQLA carrying values before haircuts and before the cap."""
        return self.level1_assets + self.level2a_assets + self.level2b_assets


@dataclass(frozen=True)
class FactorContribution:
    """One row of a factor table: ``amount * factor``.

    Kept so a reader can reconstruct every aggregate from its parts rather than
    trusting a single total.
    """

    category: str
    amount: float
    factor: float
    contribution: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "amount": float(self.amount),
            "factor": float(self.factor),
            "contribution": float(self.contribution),
        }


@dataclass(frozen=True)
class LiquidityCoverageResult:
    """Outcome of an LCR computation.

    Attributes:
        hqla: Total eligible HQLA after haircuts and after the Level 2 cap.
        hqla_level1: The Level 1 contribution included in ``hqla``.
        hqla_level2a: The Level 2A contribution included in ``hqla`` after
            haircut and after any cap allocation.
        hqla_level2b: The Level 2B contribution included in ``hqla`` after
            haircut and after any cap allocation.
        level2_uncapped: Level 2A + Level 2B after haircut but before the cap.
        level2_excluded: The Level 2 value removed by the 40% cap.
        level2_cap_binding: Whether the 40%-of-HQLA Level 2 cap removed value.
        outflows: Weighted outflows before any inflow netting.
        inflows: Weighted inflows before the 75% cap.
        effective_inflows: Inflows actually admitted, ``min(inflows, 75% x
            outflows)``.
        inflows_capped: Whether the 75%-of-outflows inflow cap bound.
        net_cash_outflows: ``outflows - effective_inflows``.
        lcr: ``hqla / net_cash_outflows``.
    """

    hqla: float
    hqla_level1: float
    hqla_level2a: float
    hqla_level2b: float
    level2_uncapped: float
    level2_excluded: float
    level2_cap_binding: bool
    outflows: float
    inflows: float
    effective_inflows: float
    inflows_capped: bool
    net_cash_outflows: float
    lcr: float

    @property
    def compliant(self) -> bool:
        """Whether the LCR meets the 100% minimum."""
        return self.lcr >= MIN_LCR

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hqla": float(self.hqla),
            "hqla_level1": float(self.hqla_level1),
            "hqla_level2a": float(self.hqla_level2a),
            "hqla_level2b": float(self.hqla_level2b),
            "level2_uncapped": float(self.level2_uncapped),
            "level2_excluded": float(self.level2_excluded),
            "level2_cap_binding": bool(self.level2_cap_binding),
            "outflows": float(self.outflows),
            "inflows": float(self.inflows),
            "effective_inflows": float(self.effective_inflows),
            "inflows_capped": bool(self.inflows_capped),
            "net_cash_outflows": float(self.net_cash_outflows),
            "lcr": float(self.lcr),
            "compliant": self.compliant,
        }


@dataclass(frozen=True)
class StableFundingPosition:
    """One institution's NSFR balance sheet.

    Attributes:
        asf_by_category: Liability and capital balances keyed by the constants in
            :data:`ASF_FACTORS`.
        rsf_by_category: Asset carrying values keyed by the constants in
            :data:`RSF_FACTORS`.
    """

    asf_by_category: Mapping[str, float] = field(default_factory=dict)
    rsf_by_category: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "asf_by_category",
            _category_table(self.asf_by_category, ASF_FACTORS, "asf_by_category"),
        )
        object.__setattr__(
            self,
            "rsf_by_category",
            _category_table(self.rsf_by_category, RSF_FACTORS, "rsf_by_category"),
        )


@dataclass(frozen=True)
class NetStableFundingResult:
    """Outcome of an NSFR computation.

    ``compliant`` is defined iff ``required_stable_funding`` is positive; a zero
    denominator is refused rather than reported as infinite.
    """

    available_stable_funding: float
    required_stable_funding: float
    nsfr: float
    asf_contributions: Tuple[FactorContribution, ...]
    rsf_contributions: Tuple[FactorContribution, ...]

    @property
    def compliant(self) -> bool:
        """Whether the NSFR meets the 100% minimum."""
        return self.nsfr >= MIN_NSFR

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available_stable_funding": float(self.available_stable_funding),
            "required_stable_funding": float(self.required_stable_funding),
            "nsfr": float(self.nsfr),
            "compliant": self.compliant,
            "asf_contributions": [row.to_dict() for row in self.asf_contributions],
            "rsf_contributions": [row.to_dict() for row in self.rsf_contributions],
        }


@dataclass(frozen=True)
class LeveragePosition:
    """One institution's leverage-ratio exposure.

    Attributes:
        tier1_capital: Tier 1 capital. Cannot exceed on-balance-sheet assets,
            since equity is a residual claim on those assets.
        on_balance_sheet_assets: On-balance-sheet asset carrying values.
        derivative_exposure: Caller-supplied derivative exposure. This module
            does not compute SA-CCR replacement cost or potential future
            exposure.
        off_balance_sheet_items: Nominal off-balance-sheet amounts keyed by the
            constants in :data:`CREDIT_CONVERSION_FACTORS`.
    """

    tier1_capital: float = 0.0
    on_balance_sheet_assets: float = 0.0
    derivative_exposure: float = 0.0
    off_balance_sheet_items: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "tier1_capital", _non_negative(self.tier1_capital, "tier1_capital")
        )
        object.__setattr__(
            self,
            "on_balance_sheet_assets",
            _non_negative(self.on_balance_sheet_assets, "on_balance_sheet_assets"),
        )
        object.__setattr__(
            self,
            "derivative_exposure",
            _non_negative(self.derivative_exposure, "derivative_exposure"),
        )
        object.__setattr__(
            self,
            "off_balance_sheet_items",
            _category_table(
                self.off_balance_sheet_items,
                CREDIT_CONVERSION_FACTORS,
                "off_balance_sheet_items",
            ),
        )
        if self.tier1_capital > self.on_balance_sheet_assets:
            raise DataQualityError(
                "Tier 1 capital exceeds on-balance-sheet assets, which is "
                "impossible: equity cannot exceed the assets it is a claim on",
                context={
                    "tier1_capital": self.tier1_capital,
                    "on_balance_sheet_assets": self.on_balance_sheet_assets,
                },
            )

    def off_balance_sheet_exposure(self) -> float:
        """Off-balance-sheet items after applying their credit conversion factors."""
        return float(
            sum(
                amount * CREDIT_CONVERSION_FACTORS[category]
                for category, amount in self.off_balance_sheet_items.items()
            )
        )

    def total_exposure(self) -> float:
        """On-balance-sheet assets + derivative exposure + converted off-balance-sheet."""
        return (
            self.on_balance_sheet_assets
            + self.derivative_exposure
            + self.off_balance_sheet_exposure()
        )


@dataclass(frozen=True)
class LeverageRatioResult:
    """Outcome of a leverage-ratio computation."""

    tier1_capital: float
    on_balance_sheet_assets: float
    derivative_exposure: float
    off_balance_sheet_exposure: float
    total_exposure_measure: float
    leverage_ratio: float
    obs_contributions: Tuple[FactorContribution, ...]

    @property
    def compliant(self) -> bool:
        """Whether the leverage ratio meets the 3% minimum."""
        return self.leverage_ratio >= MIN_LEVERAGE_RATIO

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier1_capital": float(self.tier1_capital),
            "on_balance_sheet_assets": float(self.on_balance_sheet_assets),
            "derivative_exposure": float(self.derivative_exposure),
            "off_balance_sheet_exposure": float(self.off_balance_sheet_exposure),
            "total_exposure_measure": float(self.total_exposure_measure),
            "leverage_ratio": float(self.leverage_ratio),
            "compliant": self.compliant,
            "obs_contributions": [row.to_dict() for row in self.obs_contributions],
        }


# ---------------------------------------------------------------------------
# Ratio computations
# ---------------------------------------------------------------------------


def compute_lcr(position: LiquidityPosition) -> LiquidityCoverageResult:
    """Compute the Liquidity Coverage Ratio for one position.

    The Level 2 cap is applied to the combined post-haircut Level 2A + Level 2B
    value. When it binds, the excluded value is taken from Level 2B first and
    only then from Level 2A, because Level 2B is the lower-quality tranche and is
    the one Basel's own sub-cap treats as marginal. The *total* capped HQLA is
    independent of that allocation choice.

    Raises:
        ValueError: If the position has no outflows at all, in which case the
            ratio has no denominator and cannot be reported.
    """
    if not isinstance(position, LiquidityPosition):
        raise ValueError(
            f"position must be a LiquidityPosition, got {type(position).__name__}"
        )

    included_level1 = position.level1_assets * (1.0 - HQLA_LEVEL1_HAIRCUT)
    included_level2a = position.level2a_assets * (1.0 - HQLA_LEVEL2A_HAIRCUT)
    included_level2b = position.level2b_assets * (1.0 - HQLA_LEVEL2B_HAIRCUT)

    level2_uncapped = included_level2a + included_level2b
    # Binding cap: included L2 satisfies L2 = LEVEL2_HQLA_CAP * (L1 + L2).
    level2_allowance = (
        LEVEL2_HQLA_CAP / (1.0 - LEVEL2_HQLA_CAP) * included_level1
    )
    level2_included = min(level2_uncapped, level2_allowance)
    level2_cap_binding = _capped_at(level2_included, level2_uncapped)

    excluded = level2_uncapped - level2_included
    excluded_from_2b = min(excluded, included_level2b)
    excluded_from_2a = excluded - excluded_from_2b
    hqla_level2a = included_level2a - excluded_from_2a
    hqla_level2b = included_level2b - excluded_from_2b
    hqla = included_level1 + hqla_level2a + hqla_level2b

    outflows = float(
        sum(amount * OUTFLOW_RATES[category] for category, amount in position.outflows_by_category.items())
    )
    if outflows <= 0.0:
        raise ValueError(
            "outflows are zero, so the LCR has no denominator and is undefined; "
            "an institution with no 30-day outflows cannot be given an LCR"
        )
    inflows = float(
        sum(amount * INFLOW_RATES[category] for category, amount in position.inflows_by_category.items())
    )

    inflow_allowance = INFLOW_CAP * outflows
    effective_inflows = min(inflows, inflow_allowance)
    inflows_capped = _capped_at(effective_inflows, inflows)
    net_cash_outflows = outflows - effective_inflows

    return LiquidityCoverageResult(
        hqla=float(hqla),
        hqla_level1=float(included_level1),
        hqla_level2a=float(hqla_level2a),
        hqla_level2b=float(hqla_level2b),
        level2_uncapped=float(level2_uncapped),
        level2_excluded=float(excluded),
        level2_cap_binding=bool(level2_cap_binding),
        outflows=float(outflows),
        inflows=float(inflows),
        effective_inflows=float(effective_inflows),
        inflows_capped=bool(inflows_capped),
        net_cash_outflows=float(net_cash_outflows),
        lcr=float(hqla / net_cash_outflows),
    )


def compute_nsfr(position: StableFundingPosition) -> NetStableFundingResult:
    """Compute the Net Stable Funding Ratio for one position.

    Raises:
        ValueError: If required stable funding is zero, in which case the ratio
            has no denominator and cannot be reported.
    """
    if not isinstance(position, StableFundingPosition):
        raise ValueError(
            f"position must be a StableFundingPosition, got {type(position).__name__}"
        )

    asf_rows = tuple(
        FactorContribution(
            category=category,
            amount=float(amount),
            factor=float(ASF_FACTORS[category]),
            contribution=float(amount * ASF_FACTORS[category]),
        )
        for category, amount in position.asf_by_category.items()
    )
    rsf_rows = tuple(
        FactorContribution(
            category=category,
            amount=float(amount),
            factor=float(RSF_FACTORS[category]),
            contribution=float(amount * RSF_FACTORS[category]),
        )
        for category, amount in position.rsf_by_category.items()
    )

    available = float(sum(row.contribution for row in asf_rows))
    required = float(sum(row.contribution for row in rsf_rows))
    if required <= 0.0:
        raise ValueError(
            "required stable funding is zero, so the NSFR has no denominator and "
            "is undefined"
        )

    return NetStableFundingResult(
        available_stable_funding=available,
        required_stable_funding=required,
        nsfr=float(available / required),
        asf_contributions=asf_rows,
        rsf_contributions=rsf_rows,
    )


def compute_leverage_ratio(position: LeveragePosition) -> LeverageRatioResult:
    """Compute the Basel III leverage ratio for one position.

    Raises:
        ValueError: If the total exposure measure is zero, in which case the
            ratio has no denominator and cannot be reported.
    """
    if not isinstance(position, LeveragePosition):
        raise ValueError(
            f"position must be a LeveragePosition, got {type(position).__name__}"
        )

    obs_rows = tuple(
        FactorContribution(
            category=category,
            amount=float(amount),
            factor=float(CREDIT_CONVERSION_FACTORS[category]),
            contribution=float(amount * CREDIT_CONVERSION_FACTORS[category]),
        )
        for category, amount in position.off_balance_sheet_items.items()
    )
    obs_exposure = float(sum(row.contribution for row in obs_rows))
    exposure = position.on_balance_sheet_assets + position.derivative_exposure + obs_exposure
    if exposure <= 0.0:
        raise ValueError(
            "total exposure measure is zero, so the leverage ratio has no "
            "denominator and is undefined"
        )

    return LeverageRatioResult(
        tier1_capital=float(position.tier1_capital),
        on_balance_sheet_assets=float(position.on_balance_sheet_assets),
        derivative_exposure=float(position.derivative_exposure),
        off_balance_sheet_exposure=obs_exposure,
        total_exposure_measure=float(exposure),
        leverage_ratio=float(position.tier1_capital / exposure),
        obs_contributions=obs_rows,
    )


# ---------------------------------------------------------------------------
# Stress translation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InstitutionState:
    """One institution's pre-stress regulatory position plus its shock base.

    Attributes:
        institution_id: Label. Matched against ``ClearingResult.node_ids`` to
            pick up the institution's clearing loss.
        liquidity: Pre-stress LCR position.
        funding: Pre-stress NSFR position.
        leverage: Pre-stress leverage position.
        price_sensitive_assets: Carrying value of non-HQLA assets whose value
            falls with the scenario's ``price_decline``. The caller declares this
            base; the module never infers it.
    """

    institution_id: str
    liquidity: LiquidityPosition
    funding: StableFundingPosition
    leverage: LeveragePosition
    price_sensitive_assets: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.institution_id, str) or not self.institution_id:
            raise ValueError(
                f"institution_id must be a non-empty string, got {self.institution_id!r}"
            )
        object.__setattr__(
            self,
            "price_sensitive_assets",
            _non_negative(self.price_sensitive_assets, "price_sensitive_assets"),
        )
        if not isinstance(self.liquidity, LiquidityPosition):
            raise ValueError("liquidity must be a LiquidityPosition")
        if not isinstance(self.funding, StableFundingPosition):
            raise ValueError("funding must be a StableFundingPosition")
        if not isinstance(self.leverage, LeveragePosition):
            raise ValueError("leverage must be a LeveragePosition")
        if self.price_sensitive_assets > self.leverage.on_balance_sheet_assets:
            raise DataQualityError(
                "price_sensitive_assets exceeds on-balance-sheet assets, which is "
                "impossible: the price-sensitive book is a subset of the balance "
                "sheet",
                context={
                    "institution_id": self.institution_id,
                    "price_sensitive_assets": self.price_sensitive_assets,
                    "on_balance_sheet_assets": self.leverage.on_balance_sheet_assets,
                },
            )


@dataclass(frozen=True)
class InstitutionStressResult:
    """One institution's before/after regulatory ratios under a scenario."""

    institution_id: str
    clearing_loss: float
    price_loss: float
    total_loss: float
    tier1_capital_before: float
    tier1_capital_after: float
    hqla_before: float
    hqla_after: float
    lcr_before: float
    lcr_after: float
    nsfr_before: float
    nsfr_after: Optional[float]
    leverage_before: float
    leverage_after: Optional[float]
    thresholds_breached_before: Tuple[str, ...]
    thresholds_breached_after: Tuple[str, ...]
    newly_breached: Tuple[str, ...]
    capital_exhausted: bool
    hqla_depleted: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "institution_id": self.institution_id,
            "clearing_loss": float(self.clearing_loss),
            "price_loss": float(self.price_loss),
            "total_loss": float(self.total_loss),
            "tier1_capital_before": float(self.tier1_capital_before),
            "tier1_capital_after": float(self.tier1_capital_after),
            "hqla_before": float(self.hqla_before),
            "hqla_after": float(self.hqla_after),
            "lcr_before": float(self.lcr_before),
            "lcr_after": float(self.lcr_after),
            "nsfr_before": float(self.nsfr_before),
            "nsfr_after": None if self.nsfr_after is None else float(self.nsfr_after),
            "leverage_before": float(self.leverage_before),
            "leverage_after": (
                None if self.leverage_after is None else float(self.leverage_after)
            ),
            "thresholds_breached_before": list(self.thresholds_breached_before),
            "thresholds_breached_after": list(self.thresholds_breached_after),
            "newly_breached": list(self.newly_breached),
            "capital_exhausted": bool(self.capital_exhausted),
            "hqla_depleted": bool(self.hqla_depleted),
        }


@dataclass(frozen=True)
class StressTranslationResult:
    """The per-institution post-stress regulatory table.

    Attributes:
        rows: One :class:`InstitutionStressResult` per institution, in input order.
        stress_applied: Whether any stress magnitude was supplied. When false the
            "after" columns equal the "before" columns and this is the pre-stress
            table only.
        price_decline: The supplied price-decline fraction, or ``None``.
        clearing_total_shortfall: The supplied clearing vector's total shortfall,
            or ``None``.
        institutions_absent_from_clearing: Institutions with no matching node in
            the clearing network. They were given a clearing loss of zero; the
            list makes that assumption visible instead of silent.
    """

    rows: Tuple[InstitutionStressResult, ...]
    stress_applied: bool
    price_decline: Optional[float]
    clearing_total_shortfall: Optional[float]
    institutions_absent_from_clearing: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stress_applied": bool(self.stress_applied),
            "price_decline": (
                None if self.price_decline is None else float(self.price_decline)
            ),
            "clearing_total_shortfall": (
                None
                if self.clearing_total_shortfall is None
                else float(self.clearing_total_shortfall)
            ),
            "institutions_absent_from_clearing": list(
                self.institutions_absent_from_clearing
            ),
            "rows": [row.to_dict() for row in self.rows],
        }

    def row_for(self, institution_id: str) -> InstitutionStressResult:
        """Return the row for an institution id, or raise if it is absent."""
        for row in self.rows:
            if row.institution_id == institution_id:
                return row
        raise KeyError(f"no stress row for institution {institution_id!r}")


def _threshold_breaches(
    lcr: Optional[float], nsfr: Optional[float], leverage: Optional[float]
) -> Tuple[str, ...]:
    """Named thresholds below their Basel minimum, in a fixed order.

    An undefined post-stress ratio (``None``) counts as breached: an undefined
    ratio is not evidence of compliance, and this module fails closed rather than
    reporting it as passing.
    """
    breached: List[str] = []
    if lcr is None or lcr < MIN_LCR:
        breached.append("lcr")
    if nsfr is None or nsfr < MIN_NSFR:
        breached.append("nsfr")
    if leverage is None or leverage < MIN_LEVERAGE_RATIO:
        breached.append("leverage")
    return tuple(breached)


def _clearing_losses(clearing: ClearingResult) -> Dict[str, float]:
    """Map node id -> loss borne as a creditor, validating the clearing result."""
    if not clearing.converged:
        raise DataQualityError(
            "the clearing result did not converge, so its losses are not a fixed "
            "point and cannot be used as a stress input",
            context={"iterations": int(clearing.iterations)},
        )
    node_ids = list(clearing.node_ids)
    losses = [float(x) for x in clearing.losses_by_creditor]
    if len(node_ids) != len(losses):
        raise DataQualityError(
            "clearing result is internally inconsistent: node_ids and "
            "losses_by_creditor have different lengths",
            context={"node_ids": len(node_ids), "losses": len(losses)},
        )
    mapping: Dict[str, float] = {}
    for node_id, loss in zip(node_ids, losses):
        if not math.isfinite(loss) or loss < 0.0:
            raise DataQualityError(
                f"clearing loss for {node_id!r} must be finite and non-negative, "
                f"got {loss!r}",
                context={"node_id": node_id, "loss": loss},
            )
        mapping[node_id] = loss
    return mapping


def _drawdown_waterfall(
    loss: float, level1: float, level2a: float, level2b: float
) -> Tuple[float, float, float, float]:
    """Split a cash loss across HQLA tranches, Level 1 first.

    Returns ``(from_level1, from_level2a, from_level2b, unmet)``. The unmet
    residual is the part of the loss not covered by HQLA at all.
    """
    from_level1 = min(loss, level1)
    remaining = loss - from_level1
    from_level2a = min(remaining, level2a)
    remaining -= from_level2a
    from_level2b = min(remaining, level2b)
    remaining -= from_level2b
    return from_level1, from_level2a, from_level2b, remaining


def _stress_one(
    state: InstitutionState, clearing_loss: float, price_decline: float
) -> InstitutionStressResult:
    """Apply one institution's loss and recompute all three ratios."""
    liquidity = state.liquidity
    funding = state.funding
    leverage_position = state.leverage

    lcr_before = compute_lcr(liquidity)
    nsfr_before = compute_nsfr(funding)
    leverage_before = compute_leverage_ratio(leverage_position)

    price_loss = price_decline * state.price_sensitive_assets
    total_loss = clearing_loss + price_loss

    tier1_before = leverage_position.tier1_capital
    tier1_after = max(0.0, tier1_before - total_loss)
    capital_exhausted = total_loss > 0.0 and total_loss >= tier1_before

    # Liquidity: the loss is met in cash from HQLA, best tranche first.
    d1, d2, d3, unmet = _drawdown_waterfall(
        total_loss,
        liquidity.level1_assets,
        liquidity.level2a_assets,
        liquidity.level2b_assets,
    )
    hqla_depleted = unmet > 0.0
    stressed_position = LiquidityPosition(
        level1_assets=liquidity.level1_assets - d1,
        level2a_assets=liquidity.level2a_assets - d2,
        level2b_assets=liquidity.level2b_assets - d3,
        outflows_by_category=dict(liquidity.outflows_by_category),
        inflows_by_category=dict(liquidity.inflows_by_category),
    )
    lcr_after = compute_lcr(stressed_position)

    # NSFR: the loss removes capital from ASF and writes assets down from RSF.
    asf_tier1_amount = funding.asf_by_category.get(ASF_TIER1_CAPITAL, 0.0)
    capital_borne_loss = min(total_loss, tier1_before)
    asf_reduction = min(capital_borne_loss, asf_tier1_amount) * ASF_FACTORS[
        ASF_TIER1_CAPITAL
    ]
    asf_after = nsfr_before.available_stable_funding - asf_reduction

    rsf_l1 = funding.rsf_by_category.get(RSF_HQLA_LEVEL1, 0.0)
    rsf_l2a = funding.rsf_by_category.get(RSF_HQLA_LEVEL2A, 0.0)
    rsf_l2b = funding.rsf_by_category.get(RSF_HQLA_LEVEL2B, 0.0)
    e1, e2, e3, rsf_unmet = _drawdown_waterfall(total_loss, rsf_l1, rsf_l2a, rsf_l2b)
    rsf_reduction = (
        e1 * RSF_FACTORS[RSF_HQLA_LEVEL1]
        + e2 * RSF_FACTORS[RSF_HQLA_LEVEL2A]
        + e3 * RSF_FACTORS[RSF_HQLA_LEVEL2B]
        + rsf_unmet * RSF_FACTORS[RSF_OTHER_ASSETS]
    )
    rsf_after = nsfr_before.required_stable_funding - rsf_reduction
    nsfr_after: Optional[float] = (
        float(asf_after / rsf_after) if rsf_after > 0.0 else None
    )

    # Leverage: the same asset write-down shrinks the exposure measure.
    exposure_before = leverage_position.total_exposure()
    exposure_after = max(0.0, exposure_before - total_loss)
    leverage_after: Optional[float] = (
        float(tier1_after / exposure_after) if exposure_after > 0.0 else None
    )

    breached_before = _threshold_breaches(
        lcr_before.lcr, nsfr_before.nsfr, leverage_before.leverage_ratio
    )
    breached_after = _threshold_breaches(lcr_after.lcr, nsfr_after, leverage_after)
    newly_breached = tuple(
        name for name in breached_after if name not in breached_before
    )

    return InstitutionStressResult(
        institution_id=state.institution_id,
        clearing_loss=float(clearing_loss),
        price_loss=float(price_loss),
        total_loss=float(total_loss),
        tier1_capital_before=float(tier1_before),
        tier1_capital_after=float(tier1_after),
        hqla_before=float(lcr_before.hqla),
        hqla_after=float(lcr_after.hqla),
        lcr_before=float(lcr_before.lcr),
        lcr_after=float(lcr_after.lcr),
        nsfr_before=float(nsfr_before.nsfr),
        nsfr_after=nsfr_after,
        leverage_before=float(leverage_before.leverage_ratio),
        leverage_after=leverage_after,
        thresholds_breached_before=breached_before,
        thresholds_breached_after=breached_after,
        newly_breached=newly_breached,
        capital_exhausted=bool(capital_exhausted),
        hqla_depleted=bool(hqla_depleted),
    )


def translate_systemic_stress(
    institutions: Sequence[InstitutionState],
    *,
    clearing: Optional[ClearingResult] = None,
    price_decline: Optional[float] = None,
) -> StressTranslationResult:
    """Translate systemic stress into post-stress Basel III ratios.

    The stress magnitudes are **explicit caller inputs**. If neither a clearing
    result nor a price decline is supplied, every "after" column equals its
    "before" column and ``stress_applied`` is ``False``: the function reports the
    pre-stress table and says so rather than inventing a scenario.

    Args:
        institutions: The institutions to translate. Must be non-empty.
        clearing: An optional converged
            :class:`~backend.modules.risk.clearing.ClearingResult`. Each
            institution's loss is its ``losses_by_creditor`` entry, matched by
            id. A non-converged result is refused.
        price_decline: Optional fractional decline in the price of each
            institution's ``price_sensitive_assets``, in ``[0, 1]``. Must be
            supplied explicitly; there is no default shock.

    Raises:
        ValueError: If ``institutions`` is empty, or ``price_decline`` is
            outside ``[0, 1]``.
        DataQualityError: If the clearing result did not converge or is
            internally inconsistent.
    """
    states = list(institutions)
    if not states:
        raise ValueError(
            "institutions must be non-empty: there is no table to produce for an "
            "empty institution set"
        )

    ids = [state.institution_id for state in states]
    if len(set(ids)) != len(ids):
        duplicates = sorted({name for name in ids if ids.count(name) > 1})
        raise ValueError(
            f"institution ids must be unique; duplicated: {duplicates}"
        )

    decline = 0.0
    if price_decline is not None:
        decline = _finite(price_decline, "price_decline")
        if not 0.0 <= decline <= 1.0:
            raise ValueError(
                f"price_decline must be a fraction in [0, 1], got {decline!r}"
            )

    clearing_losses: Dict[str, float] = {}
    total_shortfall: Optional[float] = None
    absent: Tuple[str, ...] = ()
    if clearing is not None:
        clearing_losses = _clearing_losses(clearing)
        total_shortfall = float(clearing.total_shortfall)
        absent = tuple(
            institution_id
            for institution_id in ids
            if institution_id not in clearing_losses
        )

    stress_applied = (total_shortfall is not None and total_shortfall > 0.0) or (
        decline > 0.0
    )

    rows = tuple(
        _stress_one(state, clearing_losses.get(state.institution_id, 0.0), decline)
        for state in states
    )

    return StressTranslationResult(
        rows=rows,
        stress_applied=bool(stress_applied),
        price_decline=None if price_decline is None else float(decline),
        clearing_total_shortfall=total_shortfall,
        institutions_absent_from_clearing=absent,
    )
