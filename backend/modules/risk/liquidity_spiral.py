"""Brunnermeier-Pedersen liquidity spirals: market and funding liquidity coupled.

The mechanism
-------------

A leveraged holder of a risky asset is constrained by its margin:

    m * p * X <= C

where ``X`` is the position, ``p`` the price, ``C`` the holder's capital and ``m``
the margin requirement. When an adverse shock lands, three things happen at once,
and each makes the next worse:

1. **Mark-to-market loss.** A price fall of ``dp`` reduces capital by ``X * dp``.
   The constraint that was binding now binds harder, so the position must shrink.
2. **Loss spiral.** The forced sale is itself a price impact: selling ``dX`` moves
   the price by ``lambda * dX``, which produces a further loss, which forces
   further selling. Brunnermeier and Pedersen (2009) call this the loss spiral.
3. **Margin spiral.** The same price move raises realised volatility, and margin
   requirements rise with volatility. A higher ``m`` shrinks the position the same
   capital can support, so the sale is larger still. That is the margin spiral.

The liquidation only stops when the position the holder can finance equals the
position it chooses to hold, which is a fixed point::

    dX  = C'(dp) / (m'(dp) * (p + dp)) - X
    dp  = shock + lambda * dX

Solved by iterating from ``dX = 0``.

The stability boundary is sharp and is the economically interesting object. For
constant margin the linearised amplification is

    A = 1 + lambda * X * (1 - m) / (m * p - lambda * X * (1 - m))

so the denominator vanishes at ``lambda* = m * p / (X * (1 - m))``. Below it the
spiral is damped; at it, a single sale is self-financing and amplification
diverges. Above it there is no finite equilibrium -- the position cannot be
liquidated into a price that survives, which is the fire-sale collapse the model
exists to describe.

``lambda*`` is a **linearised, small-shock** boundary and must be read as one. The
amplification above is first order; the iteration solved here is exact within the
one-period model, and its nonlinearity means a *finite* shock can drive the holder
to full liquidation well below ``lambda*``. The tests check the linearised
prediction in the small-shock limit, where the two agree to within a fraction of a
percent, and separately check that a large shock collapses even below the
boundary -- a property of the model rather than a defect in the solver.

Two features follow from the algebra and are worth stating because they are what
make this a *model* rather than a story: amplification is exactly 1 when either
``lambda = 0`` (no price impact) or ``m = 1`` (no leverage), since with no
leverage there is nothing to force a sale with.

Why this replaces nothing in particular
---------------------------------------

The additive contagion rule deleted in Phase 1 increased a risk score by
``shock / 1e9``, which cannot represent any of this: it has no position, no
capital, no margin and no price, so it cannot express feedback at all, let alone a
divergence. This module composes with the clearing engine instead. Clearing
answers *who* fails and in what order given a set of balance sheets; the spiral
answers *how far prices have to fall* for the deleveraging to be feasible. They
are separate questions and are kept in separate modules.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace
from typing import Any, Dict

logger = logging.getLogger(__name__)

__all__ = [
    "SpiralParameters",
    "SpiralResult",
    "LiquiditySpiralModel",
    "linear_amplification",
    "stability_impact_limit",
    "solve_quadratic_price_change",
]

DEFAULT_TOLERANCE = 1e-12
DEFAULT_MAX_ITERATIONS = 10_000


@dataclass(frozen=True)
class SpiralParameters:
    """State of a leveraged holder before any shock.

    All quantities are in consistent units; only ratios matter.

    Attributes:
        price: Price of the risky asset before the shock.
        position: Units held before the shock.
        capital: The holder's equity. Must satisfy ``m * price * position <=
            capital`` for the constraint to be satisfiable at rest, though a
            slack constraint is allowed and simply means the shock must be larger
            before deleveraging begins.
        margin: Margin requirement ``m``, the fraction of position value that
            must be equity. ``1`` means unleveraged.
        price_impact: ``lambda``, the price move caused by selling one unit. Zero
            means perfectly liquid, and removes the spiral entirely.
        margin_sensitivity: ``kappa``, the increase in ``m`` per unit of realised
            volatility ``|dp| / price``. Zero isolates the loss spiral.
        reference_volatility: Volatility at which ``margin`` is the requirement;
            the margin in force is ``margin + kappa * (|dp|/price -
            reference_volatility)``, floored and capped so it stays a valid
            fraction.
        min_margin, max_margin: Bounds on the margin in force, in ``(0, 1]``.
    """

    price: float = 100.0
    position: float = 100.0
    capital: float = 1_500.0
    margin: float = 0.15
    price_impact: float = 0.01
    margin_sensitivity: float = 0.0
    reference_volatility: float = 0.0
    min_margin: float = 0.01
    max_margin: float = 1.0

    def __post_init__(self) -> None:
        for name in ("price", "position", "capital"):
            value = getattr(self, name)
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite, got {value}")
        if self.price <= 0:
            raise ValueError(f"price must be positive, got {self.price}")
        if self.position < 0:
            raise ValueError(f"position must be non-negative, got {self.position}")
        if self.capital < 0:
            raise ValueError(f"capital must be non-negative, got {self.capital}")
        if not 0.0 < self.margin <= 1.0:
            raise ValueError(f"margin must be in (0, 1], got {self.margin}")
        if self.price_impact < 0:
            raise ValueError(f"price_impact must be non-negative, got {self.price_impact}")
        if self.margin_sensitivity < 0:
            raise ValueError(
                f"margin_sensitivity must be non-negative, got {self.margin_sensitivity}"
            )
        if self.reference_volatility < 0:
            raise ValueError(
                f"reference_volatility must be non-negative, got {self.reference_volatility}"
            )
        if not 0.0 < self.min_margin <= self.max_margin <= 1.0:
            raise ValueError(
                f"need 0 < min_margin <= max_margin <= 1, got "
                f"{self.min_margin}, {self.max_margin}"
            )
        if self.position > 0 and self.margin * self.price * self.position > self.capital + 1e-9:
            raise ValueError(
                "the initial position is not financeable: margin * price * position "
                f"= {self.margin * self.price * self.position:.6g} exceeds capital "
                f"{self.capital:.6g}"
            )

    def margin_for(self, price_change: float) -> float:
        """Margin in force given the realised price change.

        Rises with volatility and is bounded, because a margin above 1 is not a
        requirement that can be met and a margin below zero would permit infinite
        leverage.
        """
        realized = abs(price_change) / self.price
        raw = self.margin + self.margin_sensitivity * (
            realized - self.reference_volatility
        )
        return float(min(max(raw, self.min_margin), self.max_margin))


@dataclass(frozen=True)
class SpiralResult:
    """Outcome of a single shock."""

    shock: float
    initial_price_change: float
    total_price_change: float
    amplification: float
    final_price: float
    initial_position: float
    final_position: float
    deleveraging: float
    initial_capital: float
    final_capital: float
    margin_before: float
    margin_after: float
    converged: bool
    iterations: int
    fully_liquidated: bool
    stability_margin: float

    @property
    def price_impact_component(self) -> float:
        """How much of the total move came from forced selling rather than news."""
        return float(self.total_price_change - self.initial_price_change)

    @property
    def is_unstable(self) -> bool:
        """Whether the spiral failed to reach a finite equilibrium."""
        return not self.converged

    @property
    def collapsed(self) -> bool:
        """Whether the spiral ran away, by either route.

        Two distinct terminal states look similar from outside and are both
        failures of the equilibrium: the iteration failed to settle at all, or it
        settled after the holder lost its entire capital. Reading ``amplification``
        alone cannot distinguish a genuine multiplier from a terminal liquidation,
        so this flag is what a caller should branch on.
        """
        return bool(self.fully_liquidated or not self.converged)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shock": float(self.shock),
            "initial_price_change": float(self.initial_price_change),
            "total_price_change": float(self.total_price_change),
            "amplification": float(self.amplification),
            "price_impact_component": self.price_impact_component,
            "final_price": float(self.final_price),
            "initial_position": float(self.initial_position),
            "final_position": float(self.final_position),
            "deleveraging": float(self.deleveraging),
            "initial_capital": float(self.initial_capital),
            "final_capital": float(self.final_capital),
            "margin_before": float(self.margin_before),
            "margin_after": float(self.margin_after),
            "converged": bool(self.converged),
            "iterations": int(self.iterations),
            "fully_liquidated": bool(self.fully_liquidated),
            "is_unstable": self.is_unstable,
            "stability_margin": float(self.stability_margin),
        }


def stability_impact_limit(
    price: float, position: float, margin: float
) -> float:
    """``lambda*`` above which no finite equilibrium exists.

    Derived from the linearised amplification denominator
    ``m * p - lambda * X * (1 - m)``: it vanishes at ``m * p / (X * (1 - m))``.
    Returns ``inf`` when ``m = 1`` or ``X = 0``, since with no leverage or no
    position there is nothing to force a sale and the spiral cannot run.
    """
    if not 0.0 < margin <= 1.0:
        raise ValueError(f"margin must be in (0, 1], got {margin}")
    if price <= 0:
        raise ValueError(f"price must be positive, got {price}")
    if position < 0:
        raise ValueError(f"position must be non-negative, got {position}")

    denominator = position * (1.0 - margin)
    if denominator <= 0:
        return float("inf")
    return float(margin * price / denominator)


def linear_amplification(
    price: float,
    position: float,
    margin: float,
    price_impact: float,
) -> float:
    """Small-shock amplification ``A`` for constant margin.

    ``A = 1 + lambda X (1 - m) / (m p - lambda X (1 - m))``.

    Exactly 1 when ``lambda = 0`` or ``m = 1``: no price impact, or no leverage,
    means no spiral. Returns ``inf`` at or beyond the stability limit, because the
    linearisation has no finite solution there and reporting a large finite number
    would understate the breakdown.
    """
    if price_impact < 0:
        raise ValueError(f"price_impact must be non-negative, got {price_impact}")

    denominator = margin * price - price_impact * position * (1.0 - margin)
    numerator = price_impact * position * (1.0 - margin)
    if denominator <= 0:
        return float("inf")
    return float(1.0 + numerator / denominator)


def solve_quadratic_price_change(
    parameters: SpiralParameters, shock: float
) -> float:
    """Total price change from the exact quadratic, for constant margin.

    Eliminating ``dX`` between the fixed-point conditions gives a quadratic in the
    sale size ``u``::

        m*lambda*u^2 + u*(m*p + m*shock - X*lambda*(1-m)) - X*(1-m)*shock = 0

    The root tending to zero as the shock vanishes is the economically relevant
    one. This is exact within the model (constant margin) and is used to check the
    iterative solver, which is otherwise only self-consistent.
    """
    m = parameters.margin
    p = parameters.price
    X = parameters.position
    lam = parameters.price_impact

    if lam == 0.0:
        return float(shock)
    if m == 1.0:
        # No leverage: capital absorbs the loss with no forced sale, so the
        # quadratic degenerates and the price move is the shock itself.
        return float(shock)

    a = m * lam
    b = m * p + m * shock - X * lam * (1.0 - m)
    c = -X * (1.0 - m) * shock

    discriminant = b * b - 4.0 * a * c
    if discriminant < 0:
        return float("nan")

    root = (-b + math.sqrt(discriminant)) / (2.0 * a)
    return float(shock + lam * root)


class LiquiditySpiralModel:
    """Iterates the coupled market/funding liquidity feedback to a fixed point.

    Args:
        parameters: The pre-shock state.
        tolerance: Convergence tolerance on the price change.
        max_iterations: Iteration cap. Exceeding it is reported as
            non-convergence, not as a large answer -- a spiral that does not
            settle has no equilibrium to report.
    """

    def __init__(
        self,
        parameters: SpiralParameters,
        tolerance: float = DEFAULT_TOLERANCE,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
    ) -> None:
        if tolerance <= 0:
            raise ValueError(f"tolerance must be positive, got {tolerance}")
        if max_iterations < 1:
            raise ValueError(f"max_iterations must be positive, got {max_iterations}")
        self.parameters = parameters
        self.tolerance = float(tolerance)
        self.max_iterations = int(max_iterations)

    @property
    def stability_margin(self) -> float:
        """Headroom to the stability limit, as ``1 - lambda / lambda*``.

        Positive means the spiral is damped; zero means a single sale is
        self-financing; negative means there is no finite equilibrium. ``inf``
        when the limit is unbounded.
        """
        limit = stability_impact_limit(
            self.parameters.price, self.parameters.position, self.parameters.margin
        )
        if math.isinf(limit):
            return float("inf")
        if limit <= 0:
            return float("-inf")
        return float(1.0 - self.parameters.price_impact / limit)

    def cascade(self, shock: float, *, margin_feedback: bool = True) -> SpiralResult:
        """Iterate the spiral to a fixed point for a given shock.

        Args:
            shock: The exogenous price change. Negative is adverse.
            margin_feedback: When false, the margin is held at its initial value,
                which isolates the loss spiral from the margin spiral and is what
                the decomposition of amplification uses.
        """
        if not math.isfinite(shock):
            raise ValueError(f"shock must be finite, got {shock}")

        p = self.parameters.price
        X0 = self.parameters.position
        C0 = self.parameters.capital
        lam = self.parameters.price_impact

        kappa = self.parameters.margin_sensitivity if margin_feedback else 0.0

        # The fixed point is on the *position*, so the loop must be allowed to
        # complete a full update before testing for convergence. Seeding the
        # price change with the shock and breaking on an unchanged value would
        # stop on the first pass -- when the sale is still zero by construction --
        # and report an amplification of exactly 1 for every shock, which is the
        # no-spiral answer regardless of the parameters.
        position = float(X0)
        price_change = float(shock)
        previous_price_change = None
        capital = C0
        margin = self.parameters.margin
        iterations = 0
        converged = False
        fully_liquidated = False

        for iteration in range(1, self.max_iterations + 1):
            iterations = iteration

            # 1. Price reflects the shock plus the impact of the sale the holder
            #    was last able to sustain.
            sale = position - X0
            price_change = shock + lam * sale

            # 2. Capital is marked to market on the position carried into the move.
            capital = C0 + X0 * price_change

            # 3. Volatility rises, and margin with it.
            if margin_feedback:
                realized = abs(price_change) / p
                margin = min(
                    max(
                        self.parameters.margin
                        + kappa * (realized - self.parameters.reference_volatility),
                        self.parameters.min_margin,
                    ),
                    self.parameters.max_margin,
                )

            # 4. The position the margin constraint permits. A holder that was
            #    already financed below its constraint does not lever back up
            #    after a loss, so the position is capped at the original.
            current_price = p + price_change
            if capital <= 0.0 or current_price <= 0.0:
                # Capital wiped out or the price has gone non-positive: the
                # position cannot be financed at all.
                new_position = 0.0
                fully_liquidated = True
            else:
                financeable = capital / (margin * current_price)
                new_position = float(min(X0, max(financeable, 0.0)))

            position = new_position

            if previous_price_change is not None:
                delta = abs(price_change - previous_price_change)
                if delta <= self.tolerance * max(1.0, abs(price_change)):
                    converged = True
                    break

            previous_price_change = price_change

        amplification = (
            price_change / shock if shock != 0 else 1.0
        )

        return SpiralResult(
            shock=float(shock),
            initial_price_change=float(shock),
            total_price_change=float(price_change),
            amplification=float(amplification),
            final_price=float(p + price_change),
            initial_position=float(X0),
            final_position=float(position),
            deleveraging=float(position - X0),
            initial_capital=float(C0),
            final_capital=float(capital),
            margin_before=float(self.parameters.margin),
            margin_after=float(margin),
            converged=bool(converged),
            iterations=int(iterations),
            fully_liquidated=bool(fully_liquidated),
            stability_margin=self.stability_margin,
        )

    def amplitude_decomposition(self, shock: float) -> Dict[str, float]:
        """Split the amplification into its loss and margin spiral parts.

        Running with no price impact gives amplification 1 by construction, so the
        distance from 1 under the loss spiral alone is attributable to price
        impact, and the further increase once margin responds is attributable to
        the margin spiral. The two add up to the full amplification exactly.
        """
        loss_only_parameters = replace(self.parameters, margin_sensitivity=0.0)
        loss_only = LiquiditySpiralModel(
            loss_only_parameters, self.tolerance, self.max_iterations
        ).cascade(shock)

        full = self.cascade(shock)

        loss_component = loss_only.amplification - 1.0
        margin_component = full.amplification - loss_only.amplification
        return {
            "total_amplification": float(full.amplification),
            "loss_spiral": float(loss_component),
            "margin_spiral": float(margin_component),
            "baseline": 1.0,
        }
