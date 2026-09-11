"""Tests for the Brunnermeier-Pedersen liquidity spiral.

The iterative solver and the closed-form quadratic are independent routes to the
same fixed point, so the central test compares them. The linearised amplification
is a third route, valid in the small-shock limit, and is compared there too. A
solver that merely agreed with itself would pass none of these.
"""

from __future__ import annotations

import json
import math

import pytest

from backend.modules.risk.liquidity_spiral import (
    LiquiditySpiralModel,
    SpiralParameters,
    linear_amplification,
    solve_quadratic_price_change,
    stability_impact_limit,
)


def base_parameters(**overrides) -> SpiralParameters:
    """A binding, levered position: m*p*X = 0.15 * 100 * 100 = 1500 = capital."""
    defaults = dict(
        price=100.0,
        position=100.0,
        capital=1_500.0,
        margin=0.15,
        price_impact=0.01,
        margin_sensitivity=0.0,
    )
    defaults.update(overrides)
    return SpiralParameters(**defaults)


class TestThirdRouteAgreement:
    """Three independent computations of the same quantity."""

    def test_iteration_matches_the_closed_form_quadratic(self):
        """The fixed-point iteration against an algebraic solution.

        Eliminating the sale size between the two fixed-point conditions gives a
        quadratic whose root is the equilibrium. Agreeing to machine precision
        over a range of shocks is strong evidence the iteration converges to the
        right thing rather than merely to something stable.
        """
        parameters = base_parameters()
        model = LiquiditySpiralModel(parameters)

        for shock in (-5.0, -1.0, -0.1, -0.01, -0.001):
            result = model.cascade(shock)
            closed_form = solve_quadratic_price_change(parameters, shock)
            assert result.converged
            assert result.total_price_change == pytest.approx(closed_form, rel=1e-9, abs=1e-12), shock

    def test_iteration_matches_the_linearised_amplification_for_small_shocks(self):
        parameters = base_parameters()
        model = LiquiditySpiralModel(parameters)
        expected = linear_amplification(100.0, 100.0, 0.15, 0.01)

        result = model.cascade(-1e-6)
        assert result.amplification == pytest.approx(expected, rel=1e-5)

    def test_all_three_agree_at_a_steeper_impact(self):
        parameters = base_parameters(price_impact=0.05, capital=1_500.0)
        model = LiquiditySpiralModel(parameters)

        linear = linear_amplification(100.0, 100.0, 0.15, 0.05)
        quadratic = solve_quadratic_price_change(parameters, -0.001) / -0.001
        iterative = model.cascade(-0.001).amplification

        assert iterative == pytest.approx(quadratic, rel=1e-9)
        assert iterative == pytest.approx(linear, rel=1e-3)


class TestDegenerateLimits:
    def test_no_price_impact_means_no_spiral(self):
        result = LiquiditySpiralModel(base_parameters(price_impact=0.0)).cascade(-10.0)
        assert result.amplification == pytest.approx(1.0)
        assert result.total_price_change == pytest.approx(-10.0)

    def test_no_leverage_means_no_spiral(self):
        # m = 1 leaves no debt, so nothing can force a sale.
        parameters = base_parameters(margin=1.0, capital=10_000.0, position=100.0)
        result = LiquiditySpiralModel(parameters).cascade(-10.0)
        assert result.amplification == pytest.approx(1.0)
        assert result.deleveraging == pytest.approx(0.0)

    def test_no_position_means_no_spiral(self):
        parameters = base_parameters(position=0.0, capital=0.0)
        result = LiquiditySpiralModel(parameters).cascade(-10.0)
        assert result.amplification == pytest.approx(1.0)

    def test_a_favourable_shock_does_not_force_selling(self):
        result = LiquiditySpiralModel(base_parameters()).cascade(+5.0)
        assert result.deleveraging == pytest.approx(0.0)
        assert result.amplification == pytest.approx(1.0)

    def test_a_slack_constraint_does_not_force_selling(self):
        # Capital well above the requirement: the holder is not constrained, so
        # nothing is sold and the position is not levered back up either.
        parameters = base_parameters(capital=3_000.0)
        result = LiquiditySpiralModel(parameters).cascade(-5.0)
        assert result.deleveraging == pytest.approx(0.0)
        assert result.final_position == pytest.approx(parameters.position)


class TestStabilityBoundary:
    def test_the_limit_matches_the_derived_expression(self):
        # lambda* = m p / (X (1 - m)) = 0.15 * 100 / (100 * 0.85)
        assert stability_impact_limit(100.0, 100.0, 0.15) == pytest.approx(
            0.15 * 100.0 / (100.0 * 0.85)
        )

    def test_the_limit_is_unbounded_without_leverage_or_position(self):
        assert math.isinf(stability_impact_limit(100.0, 100.0, 1.0))
        assert math.isinf(stability_impact_limit(100.0, 0.0, 0.15))

    def test_amplification_diverges_at_the_limit(self):
        limit = stability_impact_limit(100.0, 100.0, 0.15)
        assert linear_amplification(100.0, 100.0, 0.15, limit) == float("inf")
        assert linear_amplification(100.0, 100.0, 0.15, limit * 1.5) == float("inf")

    def test_amplification_increases_towards_the_limit(self):
        limit = stability_impact_limit(100.0, 100.0, 0.15)
        values = [
            linear_amplification(100.0, 100.0, 0.15, limit * fraction)
            for fraction in (0.1, 0.4, 0.7, 0.95)
        ]
        assert values == sorted(values)
        assert values[-1] > values[0]

    def test_the_iteration_tracks_the_linearisation_up_to_the_limit(self):
        """The exact iteration against the first-order approximation.

        The tolerance widens as the boundary approaches, and deliberately so. The
        linear amplification drops the second-order term, whose relative
        contribution grows with the amplification itself: at 0.5 of the limit the
        two agree to a fraction of a percent, while at 0.99 they differ by about
        1% (the iteration gives 101.01 against the linear form's 100.00). The
        iteration is the exact one within the model; the gap measures the
        linearisation's error, not the solver's.
        """
        limit = stability_impact_limit(100.0, 100.0, 0.15)
        tolerances = {0.5: 1e-3, 0.9: 1e-2, 0.99: 2e-2}
        for fraction, tolerance in tolerances.items():
            impact = limit * fraction
            parameters = base_parameters(price_impact=impact)
            result = LiquiditySpiralModel(parameters).cascade(-1e-4)
            expected = linear_amplification(100.0, 100.0, 0.15, impact)
            assert result.converged
            assert result.amplification == pytest.approx(expected, rel=tolerance), fraction

    def test_headroom_is_reported_and_shrinks_as_impact_rises(self):
        limit = stability_impact_limit(100.0, 100.0, 0.15)
        tight = LiquiditySpiralModel(base_parameters(price_impact=limit * 0.9)).stability_margin
        loose = LiquiditySpiralModel(base_parameters(price_impact=limit * 0.1)).stability_margin
        assert loose > tight
        assert tight == pytest.approx(0.1, abs=1e-9)

    def test_a_finite_shock_collapses_below_the_linearised_limit(self):
        """A property of the model, not a solver defect.

        The boundary is a first-order result. The solved system is nonlinear, and
        a large enough shock drives the holder to full liquidation even where the
        linearisation predicts a finite multiplier.
        """
        impact = stability_impact_limit(100.0, 100.0, 0.15) * 0.9
        parameters = base_parameters(price_impact=impact)
        model = LiquiditySpiralModel(parameters)

        small = model.cascade(-0.01)
        large = model.cascade(-1.0)

        assert small.collapsed is False
        assert small.amplification < 20.0
        assert large.collapsed is True


class TestSpiralMechanics:
    def test_capital_is_marked_to_market_on_the_original_position(self):
        parameters = base_parameters()
        result = LiquiditySpiralModel(parameters).cascade(-1.0)
        expected = parameters.capital + parameters.position * result.total_price_change
        assert result.final_capital == pytest.approx(expected)

    def test_the_financing_identity_holds_at_the_solution(self):
        """The constraint is tight at the fixed point: m p X = C."""
        parameters = base_parameters()
        result = LiquiditySpiralModel(parameters).cascade(-1.0)

        assert not result.collapsed
        implied = result.margin_after * result.final_price * result.final_position
        assert implied == pytest.approx(result.final_capital, rel=1e-6)

    def test_deleveraging_is_a_sale(self):
        result = LiquiditySpiralModel(base_parameters()).cascade(-1.0)
        assert result.deleveraging < 0
        assert result.final_position < result.initial_position

    def test_a_bigger_shock_sells_more(self):
        model = LiquiditySpiralModel(base_parameters())
        small = model.cascade(-0.1)
        large = model.cascade(-1.0)
        assert large.deleveraging < small.deleveraging

    def test_the_price_impact_component_is_the_sale_not_the_news(self):
        result = LiquiditySpiralModel(base_parameters()).cascade(-1.0)
        assert result.price_impact_component == pytest.approx(
            result.total_price_change - result.initial_price_change
        )
        assert result.price_impact_component < 0

    def test_full_liquidation_carries_the_impact_of_the_whole_position(self):
        """The terminal sale must be priced, not assumed free.

        An earlier version broke out of the loop as soon as capital went negative,
        which reported an amplification of exactly 1.0 for a shock that had in fact
        wiped the holder out. The impact of liquidating the entire position is
        ``lambda * X``, the largest the model admits.
        """
        parameters = base_parameters()
        result = LiquiditySpiralModel(parameters).cascade(-20.0)

        assert result.fully_liquidated is True
        assert result.final_position == pytest.approx(0.0)
        assert result.total_price_change == pytest.approx(
            -20.0 - parameters.price_impact * parameters.position
        )
        assert result.collapsed is True


class TestMarginSpiral:
    def test_margin_rises_with_the_price_move(self):
        parameters = base_parameters(margin_sensitivity=0.5)
        result = LiquiditySpiralModel(parameters).cascade(-1.0)
        assert result.margin_after > result.margin_before

    def test_margin_is_unchanged_without_sensitivity(self):
        result = LiquiditySpiralModel(base_parameters()).cascade(-1.0)
        assert result.margin_after == pytest.approx(result.margin_before)

    def test_the_margin_spiral_increases_amplification(self):
        """The second feedback loop, isolated by turning it off."""
        without = LiquiditySpiralModel(base_parameters(margin_sensitivity=0.0)).cascade(-1.0)
        with_margin = LiquiditySpiralModel(base_parameters(margin_sensitivity=1.0)).cascade(-1.0)

        assert not without.collapsed
        assert with_margin.amplification > without.amplification

    def test_margin_is_bounded(self):
        parameters = base_parameters(margin_sensitivity=1_000.0, max_margin=0.9)
        result = LiquiditySpiralModel(parameters).cascade(-50.0)
        assert result.margin_after <= 0.9

    def test_amplitude_decomposition_adds_up(self):
        model = LiquiditySpiralModel(base_parameters(margin_sensitivity=0.5))
        parts = model.amplitude_decomposition(-0.5)
        assert parts["baseline"] + parts["loss_spiral"] + parts["margin_spiral"] == pytest.approx(
            parts["total_amplification"], rel=1e-9
        )

    def test_the_loss_spiral_alone_is_positive_when_impact_is_positive(self):
        model = LiquiditySpiralModel(base_parameters(margin_sensitivity=0.5))
        parts = model.amplitude_decomposition(-0.5)
        assert parts["loss_spiral"] > 0
        assert parts["margin_spiral"] > 0


class TestUnstableCollapse:
    def test_a_runaway_spiral_is_reported_as_collapsed(self):
        impact = stability_impact_limit(100.0, 100.0, 0.15) * 1.5
        parameters = base_parameters(price_impact=impact)
        result = LiquiditySpiralModel(parameters).cascade(-1.0)
        assert result.collapsed is True

    def test_a_runaway_spiral_wipes_the_position_out(self):
        impact = stability_impact_limit(100.0, 100.0, 0.15) * 1.5
        result = LiquiditySpiralModel(base_parameters(price_impact=impact)).cascade(-1.0)
        assert result.final_position == pytest.approx(0.0)
        assert result.fully_liquidated is True

    def test_headroom_goes_negative_past_the_limit(self):
        impact = stability_impact_limit(100.0, 100.0, 0.15) * 1.5
        model = LiquiditySpiralModel(base_parameters(price_impact=impact))
        assert model.stability_margin < 0


class TestResultRecord:
    def test_serialises_to_json(self):
        result = LiquiditySpiralModel(base_parameters()).cascade(-1.0)
        json.dumps(result.to_dict(), allow_nan=False)

    def test_payload_carries_the_evidence(self):
        result = LiquiditySpiralModel(base_parameters()).cascade(-1.0)
        payload = result.to_dict()
        assert payload["initial_price_change"] == pytest.approx(-1.0)
        assert payload["amplification"] > 1.0
        assert payload["deleveraging"] < 0
        # `collapsed` is a computed property and is not serialised, so the payload
        # must carry the two fields it is derived from.
        assert payload["fully_liquidated"] is False
        assert payload["is_unstable"] is False
        assert payload["converged"] is True

    def test_repeated_runs_are_identical(self):
        model = LiquiditySpiralModel(base_parameters())
        assert model.cascade(-1.0).to_dict() == model.cascade(-1.0).to_dict()


class TestValidation:
    def test_impossible_initial_position_is_rejected(self):
        # m p X = 0.15 * 100 * 1000 = 15000 > 1500 capital.
        with pytest.raises(ValueError, match="not financeable"):
            SpiralParameters(price=100.0, position=1_000.0, capital=1_500.0, margin=0.15)

    def test_non_positive_price_is_rejected(self):
        with pytest.raises(ValueError, match="price"):
            SpiralParameters(price=0.0)

    def test_negative_position_is_rejected(self):
        with pytest.raises(ValueError, match="position"):
            SpiralParameters(position=-1.0, capital=0.0)

    def test_negative_capital_is_rejected(self):
        with pytest.raises(ValueError, match="capital"):
            SpiralParameters(capital=-1.0)

    def test_out_of_range_margin_is_rejected(self):
        with pytest.raises(ValueError, match="margin must be in"):
            SpiralParameters(margin=0.0)
        with pytest.raises(ValueError, match="margin must be in"):
            SpiralParameters(margin=1.5)

    def test_negative_impact_is_rejected(self):
        with pytest.raises(ValueError, match="price_impact"):
            SpiralParameters(price_impact=-0.1)

    def test_negative_sensitivity_is_rejected(self):
        with pytest.raises(ValueError, match="margin_sensitivity"):
            SpiralParameters(margin_sensitivity=-0.1)

    def test_inverted_margin_bounds_are_rejected(self):
        with pytest.raises(ValueError, match="min_margin"):
            SpiralParameters(min_margin=0.9, max_margin=0.1)

    def test_non_finite_shock_is_rejected(self):
        model = LiquiditySpiralModel(base_parameters())
        with pytest.raises(ValueError, match="shock"):
            model.cascade(float("nan"))

    def test_invalid_solver_settings_are_rejected(self):
        with pytest.raises(ValueError, match="tolerance"):
            LiquiditySpiralModel(base_parameters(), tolerance=0.0)
        with pytest.raises(ValueError, match="max_iterations"):
            LiquiditySpiralModel(base_parameters(), max_iterations=0)

    def test_helper_validation(self):
        with pytest.raises(ValueError, match="margin"):
            stability_impact_limit(100.0, 100.0, 0.0)
        with pytest.raises(ValueError, match="price_impact"):
            linear_amplification(100.0, 100.0, 0.15, -1.0)
