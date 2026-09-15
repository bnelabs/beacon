"""Per-indicator stress semantics: which direction is bad, and why.

Round-eight adoption. The fifth-round review named the missing semantic
bridge; the event labeller made stress labelable; what remained undefined was
the *orientation*: a rising HQLA level is good, a rising FX-swap basis is
bad, and an aggregate that mixes the two without a sign convention measures
nothing. This module is the registry that supplies the convention.

Contract
--------

* ``stress_direction(code)`` returns ``+1`` when rising values mean stress,
  ``-1`` when falling values mean stress, and ``None`` when the orientation
  is undeclared. ``None`` is a refusal, not a default: consumers that need an
  orientation must skip the series rather than guess.
* ``event_direction(code)`` maps the orientation onto the event labeller's
  vocabulary (``"up"``/``"down"``).
* Entries are curated alongside the catalogue (see
  ``scripts/populate_catalogue.py``); adding a monitored series without an
  orientation is allowed but leaves it out of cross-source aggregation and
  out of default event labelling.
"""

from __future__ import annotations

from typing import Literal, Optional

__all__ = ["stress_direction", "event_direction", "STRESS_DIRECTION"]

#: code -> +1 (rising = stress) / -1 (falling = stress)
STRESS_DIRECTION = {
    # Stress indices: positive is stressed by construction.
    "FRED_STLFSI4": +1,
    "FRED_KCFSI": +1,
    "ECB_CISS": +1,
    # Funding costs and spreads: rising = tightening = stress.
    "FRED_SOFR": +1,
    "FRED_BAMLH0A0HYM2": +1,
    # Safe-asset demand: rising ON-RRP balances signal cash abundance and
    # intermediation strain; treated as rising = stress in the funding sense.
    "FRED_RRPONTSYD": +1,
    # Term structure: inversion (falling spread) precedes funding pressure.
    "FRED_T10Y2Y": -1,
    # Liquidity levels and coverage: falling = deterioration.
    "HQLA_LEVEL": -1,
    "LCR_RATIO": -1,
    "NSFR_RATIO": -1,
    # Market levels used as health proxies: falling = stress.
    "BANK_EQUITY_INDEX": -1,
    # Bases and premiums: rising = squeeze.
    "FX_SWAP_BASIS": +1,
    "CDS_PREMIUM": +1,
}


def stress_direction(code: str) -> Optional[Literal[+1, -1]]:
    """``+1`` when rising values mean stress, ``-1`` when falling does, else ``None``."""
    return STRESS_DIRECTION.get(str(code))


def event_direction(code: str) -> Optional[str]:
    """The event-labeller vocabulary for ``code``: ``'up'``, ``'down'`` or ``None``."""
    direction = stress_direction(code)
    if direction is None:
        return None
    return "up" if direction > 0 else "down"
