"""The risk-threshold scales must not disagree with each other.

``constants.py`` carried two copies of the same three cut-offs: a 0-1 scale
(``RISK_THRESHOLD_*``) and a 0-100 scale (``RISK_THRESHOLD_*_PERCENT``). They had
drifted at the top band -- ``RISK_THRESHOLD_HIGH`` was ``0.85`` while
``RISK_THRESHOLD_HIGH_PERCENT`` still read ``80`` -- so a score of 0.82 banded as
"high" on one scale and "critical" on the other, depending on which constant a
caller happened to reach for.

The percentage scale is now derived from the 0-1 scale, which makes that class of
disagreement unrepresentable. These tests lock the derivation and check that the
two functions which band a score agree with the constants rather than with their
own private copies of the numbers.
"""

from __future__ import annotations

import pytest

from backend.modules.risk import constants as C
from backend.modules.risk.bank_analyzer import BankRiskAnalyzer, _risk_to_text


class TestScaleConsistency:
    @pytest.mark.parametrize(
        "decimal, percent",
        [
            (C.RISK_THRESHOLD_LOW, C.RISK_THRESHOLD_LOW_PERCENT),
            (C.RISK_THRESHOLD_MODERATE, C.RISK_THRESHOLD_MODERATE_PERCENT),
            (C.RISK_THRESHOLD_HIGH, C.RISK_THRESHOLD_HIGH_PERCENT),
        ],
    )
    def test_the_percentage_scale_is_the_decimal_scale_times_one_hundred(
        self, decimal: float, percent: int
    ):
        assert percent == round(decimal * 100)

    def test_ordering_is_preserved_on_both_scales(self):
        assert (
            C.RISK_THRESHOLD_LOW
            < C.RISK_THRESHOLD_MODERATE
            < C.RISK_THRESHOLD_HIGH
        )
        assert (
            C.RISK_THRESHOLD_LOW_PERCENT
            < C.RISK_THRESHOLD_MODERATE_PERCENT
            < C.RISK_THRESHOLD_HIGH_PERCENT
        )


class TestBandingAgreesWithTheConstants:
    """``_risk_level`` and ``_risk_to_text`` band the same score identically."""

    _BAND_FOR_LEVEL = {
        "low": "LOW RISK",
        "medium": "MODERATE RISK",
        "high": "HIGH RISK",
        "critical": "CRITICAL RISK",
    }

    @pytest.mark.parametrize(
        "score",
        [0.0, 0.29, 0.3, 0.45, 0.59, 0.6, 0.7, 0.84, 0.85, 0.95, 1.0],
    )
    def test_the_two_renderings_describe_the_same_band(self, score: float):
        level = BankRiskAnalyzer._risk_level(score)
        assert _risk_to_text(score) == self._BAND_FOR_LEVEL[level]

    @pytest.mark.parametrize(
        "score, expected",
        [
            (C.RISK_THRESHOLD_LOW - 0.001, "LOW RISK"),
            (C.RISK_THRESHOLD_LOW, "MODERATE RISK"),
            (C.RISK_THRESHOLD_MODERATE - 0.001, "MODERATE RISK"),
            (C.RISK_THRESHOLD_MODERATE, "HIGH RISK"),
            (C.RISK_THRESHOLD_HIGH - 0.001, "HIGH RISK"),
            (C.RISK_THRESHOLD_HIGH, "CRITICAL RISK"),
        ],
    )
    def test_band_edges_are_the_named_constants(self, score: float, expected: str):
        assert _risk_to_text(score) == expected
