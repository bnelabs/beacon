"""Tests for the coupled Eisenberg-Noe / fire-sale fixed point.

The central claims are checked against routes that do not run through this
module's own loop:

* a **hand-computed worked example** whose prices, shortfalls and capital are
  derived in the comments from the stated rules alone;
* the **spiral module's own ``cascade``**, which must reach the identical fixed
  point when the same single-holder scenario is run through this solver's margin
  channel;
* the **exact decomposition identities** (feedback = total - baseline), checked
  against a baseline run built independently in the test.

A solver that merely agreed with itself would pass none of these.
"""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pytest

from backend.modules.risk.clearing import NetworkLayer, clear_multiplex
from backend.modules.risk.fire_sale import (
    FireSaleScenario,
    FireSaleSolver,
    solve_fire_sale,
)
from backend.modules.risk.liquidity_spiral import (
    LiquiditySpiralModel,
    SpiralParameters,
    stability_impact_limit,
)


def worked_scenario(price_impact: float = 0.5) -> FireSaleScenario:
    """A's solvency shortfall drives the sale; B is a passive creditor.

    ``A`` holds 10 units at 10 (V = 100) and owes ``B`` 150 with no endowment,
    so the clearing leaves A 50 short. ``m = 1`` means no leverage, which
    isolates the shortfall channel from the margin channel.
    """
    return FireSaleScenario(
        institution_ids=["A", "B"],
        asset_ids=["X"],
        holdings=np.array([[10.0], [0.0]]),
        prices=np.array([10.0]),
        capital=np.array([1000.0, 0.0]),
        endowments=np.array([0.0, 0.0]),
        liabilities=np.array([[0.0, 150.0], [0.0, 0.0]]),
        margins=np.array([1.0, 1.0]),
        price_impacts=np.array([price_impact]),
        price_shock=np.array([0.0]),
    )


def feedback_scenario(price_impact: float = 0.2) -> FireSaleScenario:
    """A's fire sale marks B down enough to push B into default.

    ``A`` holds 10 units at 10 and owes B 150. ``B`` holds 10 units and owes
    ``C`` 190. At lambda = 0 the price never moves, B's marked assets stay at
    100 + A's 100 receipt = 200 and B pays in full; with lambda > 0 the price
    fall erodes B's capacity below 190 and B defaults. C is a passive creditor
    with no holdings.
    """
    return FireSaleScenario(
        institution_ids=["A", "B", "C"],
        asset_ids=["X"],
        holdings=np.array([[10.0], [10.0], [0.0]]),
        prices=np.array([10.0]),
        capital=np.array([1000.0, 1000.0, 0.0]),
        endowments=np.array([0.0, 0.0, 0.0]),
        liabilities=np.array(
            [[0.0, 150.0, 0.0], [0.0, 0.0, 190.0], [0.0, 0.0, 0.0]]
        ),
        margins=np.array([1.0, 1.0, 1.0]),
        price_impacts=np.array([price_impact]),
        price_shock=np.array([0.0]),
    )


def levered_scenario(
    price_impact: float,
    margin_sensitivity: float = 0.0,
    price_shock: float = -1.0,
) -> FireSaleScenario:
    """One levered holder with no liabilities: the margin channel alone."""
    return FireSaleScenario(
        institution_ids=["H"],
        asset_ids=["X"],
        holdings=np.array([[100.0]]),
        prices=np.array([100.0]),
        capital=np.array([1500.0]),
        endowments=np.array([0.0]),
        liabilities=np.zeros((1, 1)),
        margins=np.array([0.15]),
        price_impacts=np.array([price_impact]),
        price_shock=np.array([price_shock]),
        margin_sensitivity=np.array([margin_sensitivity]),
    )


class TestHandComputedWorkedExample:
    """Every expected number below is derived by hand in the comments.

    Worked scenario: A holds 10 units at p = 10 (V = 100), owes B 150, no
    endowment, margin m = 1 (unlevered), lambda = 0.5, no exogenous shock.

    Round 1 (p = 10): e_A = 100, so A pays 100 and is 50 short. The margin need
    is 0 because 100 <= capital 1000. A sells 50 / 100 = 50% of the portfolio:
    5 units, worth 50, and Q = 5 moves the price to 10 - 0.5 * 5 = 7.5.

    Round 2 (p = 7.5): e_A = cash 50 + 5 * 7.5 = 87.5, so A pays 87.5 and is
    62.5 short. Demand 62.5 exceeds V = 37.5, so A sells all 5 remaining units.
    Q = 10 and the price is 10 - 0.5 * 10 = 5.

    Round 3 (p = 5): e_A = 87.5, shortfall 62.5, nothing left to sell. Q stays
    10 and the price stays 5, so the change is exactly zero and the loop stops.

    Final capital: C_A = 1000 + 10 * (5 - 10) = 950, marked on the position
    carried into the shock.
    """

    def test_the_price_path_is_exactly_the_hand_computation(self):
        result = FireSaleSolver(worked_scenario(), tolerance=1e-12).solve()

        assert result.converged
        assert result.diverged is False
        assert result.rounds == 3
        assert result.final_prices == pytest.approx([5.0])
        assert [round_record.prices[0] for round_record in result.path] == pytest.approx(
            [10.0, 7.5, 5.0]
        )
        assert [
            round_record.next_prices[0] for round_record in result.path
        ] == pytest.approx([7.5, 5.0, 5.0])

    def test_the_shortfall_path_is_exactly_the_hand_computation(self):
        result = FireSaleSolver(worked_scenario(), tolerance=1e-12).solve()

        assert [round_record.shortfall[0] for round_record in result.path] == pytest.approx(
            [50.0, 62.5, 62.5]
        )
        assert [
            round_record.sold_value[0] for round_record in result.path
        ] == pytest.approx([50.0, 37.5, 0.0])
        assert result.final_shortfall[0] == pytest.approx(62.5)

    def test_the_clearing_path_is_exactly_the_hand_computation(self):
        result = FireSaleSolver(worked_scenario(), tolerance=1e-12).solve()

        # A pays its whole marked capacity each round: 100, 87.5, 87.5.
        assert [round_record.clearing.payments[0] for round_record in result.path] == (
            pytest.approx([100.0, 87.5, 87.5])
        )
        assert result.final_clearing.payments[0] == pytest.approx(87.5)
        assert result.final_defaults == ["A"]

    def test_final_capital_and_cash_are_the_hand_computation(self):
        result = FireSaleSolver(worked_scenario(), tolerance=1e-12).solve()

        assert result.final_capital[0] == pytest.approx(950.0)
        assert result.final_cash[0] == pytest.approx(87.5)
        assert result.cumulative_sold_units[0, 0] == pytest.approx(10.0)

    def test_the_amplification_numbers_are_the_hand_computation(self):
        result = FireSaleSolver(worked_scenario(), tolerance=1e-12).solve()
        amplification = result.amplification

        # At lambda = 0 the price never moves, so A still pays 100 and the
        # shortfall is 50 with no mark-to-market loss at all.
        assert amplification.baseline_total_shortfall == pytest.approx(50.0)
        assert amplification.baseline_mark_to_market_loss == pytest.approx(0.0)
        # With lambda = 0.5 the shortfall is 62.5 and A has lost 50 of capital.
        assert amplification.total_shortfall == pytest.approx(62.5)
        assert amplification.total_mark_to_market_loss == pytest.approx(50.0)
        # The part attributable to the feedback: 12.5 of shortfall, 50 of loss.
        assert amplification.feedback_shortfall == pytest.approx(12.5)
        assert amplification.feedback_mark_to_market_loss == pytest.approx(50.0)


class TestFeedbackAmplification:
    def test_price_impact_makes_losses_and_defaults_strictly_worse(self):
        result = FireSaleSolver(feedback_scenario(), tolerance=1e-12).solve()

        baseline_scenario = replace(
            feedback_scenario(), price_impacts=np.zeros(1)
        )
        baseline = FireSaleSolver(
            baseline_scenario, tolerance=1e-12, decompose_feedback=False
        ).solve()

        assert result.converged and baseline.converged
        assert result.final_total_shortfall > baseline.final_total_shortfall
        assert len(result.final_defaults) > len(baseline.final_defaults)
        assert (
            result.amplification.total_mark_to_market_loss
            > result.amplification.baseline_mark_to_market_loss
        )

    def test_the_feedback_component_is_exactly_the_difference(self):
        result = FireSaleSolver(feedback_scenario(), tolerance=1e-12).solve()
        baseline_scenario = replace(
            feedback_scenario(), price_impacts=np.zeros(1)
        )
        baseline = FireSaleSolver(
            baseline_scenario, tolerance=1e-12, decompose_feedback=False
        ).solve()

        amplification = result.amplification
        assert amplification.baseline_total_shortfall == pytest.approx(
            baseline.final_total_shortfall
        )
        assert amplification.total_shortfall == pytest.approx(
            result.final_total_shortfall
        )
        assert amplification.feedback_shortfall == pytest.approx(
            amplification.total_shortfall - amplification.baseline_total_shortfall,
            rel=1e-12,
        )
        # The same identity for the mark-to-market loss.
        assert amplification.feedback_mark_to_market_loss == pytest.approx(
            amplification.total_mark_to_market_loss
            - amplification.baseline_mark_to_market_loss,
            rel=1e-12,
        )

    def test_zero_price_impact_is_its_own_baseline(self):
        scenario = replace(feedback_scenario(), price_impacts=np.zeros(1))
        result = FireSaleSolver(scenario, tolerance=1e-12).solve()
        assert result.amplification.feedback_shortfall == pytest.approx(0.0)
        assert result.amplification.feedback_mark_to_market_loss == pytest.approx(0.0)
        assert result.amplification.feedback_caused_defaults == []


class TestFeedbackCausedDefault:
    def test_b_survives_without_feedback_and_defaults_with_it(self):
        result = FireSaleSolver(feedback_scenario(), tolerance=1e-12).solve()
        baseline_scenario = replace(
            feedback_scenario(), price_impacts=np.zeros(1)
        )
        baseline = FireSaleSolver(
            baseline_scenario, tolerance=1e-12, decompose_feedback=False
        ).solve()

        assert baseline.final_defaults == ["A"]
        assert result.final_defaults == ["A", "B"]
        assert result.feedback_caused_defaults == ["B"]
        assert result.amplification.feedback_caused_defaults == ["B"]

    def test_the_feedback_caused_set_is_empty_without_price_impact(self):
        scenario = replace(feedback_scenario(), price_impacts=np.zeros(1))
        result = FireSaleSolver(scenario, tolerance=1e-12).solve()
        assert result.feedback_caused_defaults == []


class TestDivergenceIsReported:
    def test_a_runaway_spiral_is_reported_and_no_answer_is_returned(self):
        # lambda* = m p / (X (1 - m)) = 0.15 * 10 / (10 * 0.85) = 0.17647...
        # lambda = 1.2 is nearly seven times the stability limit, so the
        # cumulative impact drives the price through zero.
        limit = stability_impact_limit(10.0, 10.0, 0.15)
        assert limit == pytest.approx(0.15 * 10.0 / (10.0 * 0.85))
        assert 1.2 > limit

        scenario = FireSaleScenario(
            institution_ids=["A", "B"],
            asset_ids=["X"],
            holdings=np.array([[10.0], [0.0]]),
            prices=np.array([10.0]),
            capital=np.array([15.0, 0.0]),
            endowments=np.array([0.0, 0.0]),
            liabilities=np.array([[0.0, 150.0], [0.0, 0.0]]),
            margins=np.array([0.15, 1.0]),
            price_impacts=np.array([1.2]),
            price_shock=np.array([0.0]),
        )
        result = FireSaleSolver(scenario, tolerance=1e-12, max_rounds=50).solve()

        assert result.diverged is True
        assert result.converged is False
        assert result.divergence_reason is not None
        assert "price_floor" in result.divergence_reason
        # A divergent run must not hand back a finite answer.
        assert result.final_prices is None
        assert result.final_capital is None
        assert result.final_shortfall is None
        assert result.final_clearing is None
        assert result.final_defaults == []
        # But the path that diverged is still reported.
        assert len(result.path) >= 1
        assert result.stability_limit_exceeded is True

    def test_reaching_the_round_cap_is_divergence(self):
        result = FireSaleSolver(worked_scenario(), tolerance=1e-12, max_rounds=1).solve()
        assert result.diverged is True
        assert result.converged is False
        assert result.divergence_reason is not None
        assert "round_cap_reached" in result.divergence_reason
        assert result.final_prices is None

    def test_a_round_flags_when_lambda_exceeds_the_stability_limit(self):
        limit = stability_impact_limit(10.0, 10.0, 0.15)
        # 0.05 is below the limit: the round must not be flagged.
        calm = FireSaleScenario(
            institution_ids=["A"],
            asset_ids=["X"],
            holdings=np.array([[10.0]]),
            prices=np.array([10.0]),
            capital=np.array([15.0]),
            endowments=np.array([0.0]),
            liabilities=np.zeros((1, 1)),
            margins=np.array([0.15]),
            price_impacts=np.array([limit * 0.5]),
            price_shock=np.array([-0.1]),
        )
        calm_result = FireSaleSolver(calm, tolerance=1e-12).solve()
        assert calm_result.path[0].over_stability_limit is False
        assert calm_result.stability_limit_exceeded is False
        assert calm_result.path[0].stability_margin > 0.0

    def test_a_caller_supplied_stability_limit_replaces_the_derived_one(self):
        limit = stability_impact_limit(10.0, 10.0, 0.15)
        scenario = FireSaleScenario(
            institution_ids=["A"],
            asset_ids=["X"],
            holdings=np.array([[10.0]]),
            prices=np.array([10.0]),
            capital=np.array([15.0]),
            endowments=np.array([0.0]),
            liabilities=np.zeros((1, 1)),
            margins=np.array([0.15]),
            price_impacts=np.array([limit * 0.5]),
            price_shock=np.array([-0.1]),
        )
        # The derived limit is well above lambda, so nothing is flagged by
        # default; an explicit tighter policy threshold must be honoured.
        default = FireSaleSolver(scenario, tolerance=1e-12).solve()
        tightened = FireSaleSolver(
            scenario, tolerance=1e-12, stability_limit=limit * 0.1
        ).solve()
        assert default.path[0].over_stability_limit is False
        assert tightened.path[0].over_stability_limit is True
        assert tightened.path[0].stability_margin < 0.0


class TestConvergenceAndFixedPoint:
    def test_the_round_over_round_change_falls_below_the_tolerance(self):
        tolerance = 1e-9
        result = FireSaleSolver(worked_scenario(), tolerance=tolerance).solve()

        assert result.converged
        assert result.path[-1].delta <= tolerance
        assert result.path[-1].converged is True
        # No executable liquidation remains at the reported fixed point.
        assert result.path[-1].sold_value == pytest.approx([0.0, 0.0])

    def test_rerunning_one_clearing_step_at_the_final_prices_does_not_move_it(self):
        scenario = worked_scenario()
        solver = FireSaleSolver(scenario, tolerance=1e-12)
        result = solver.solve()

        endowments = solver.endowments_for(
            result.final_holdings, result.final_cash, result.final_prices
        )
        layer = NetworkLayer(
            name="interbank", liabilities=scenario.liabilities, seniority=0
        )
        recheck = clear_multiplex(
            [layer], endowments, node_ids=list(scenario.institution_ids)
        )

        assert recheck.payments == pytest.approx(result.final_clearing.payments)
        assert recheck.defaulted.tolist() == result.final_clearing.defaulted.tolist()

    def test_the_price_stops_moving_at_the_fixed_point(self):
        result = FireSaleSolver(worked_scenario(), tolerance=1e-12).solve()
        assert result.path[-1].prices == pytest.approx(result.path[-1].next_prices)
        assert result.final_prices == pytest.approx(result.path[-1].prices)

    def test_a_scenario_with_no_pressure_converges_in_one_round(self):
        scenario = FireSaleScenario(
            institution_ids=["A"],
            asset_ids=["X"],
            holdings=np.array([[10.0]]),
            prices=np.array([10.0]),
            capital=np.array([1000.0]),
            endowments=np.array([500.0]),
            liabilities=np.zeros((1, 1)),
            margins=np.array([1.0]),
            price_impacts=np.array([0.5]),
            price_shock=np.array([0.0]),
        )
        result = FireSaleSolver(scenario, tolerance=1e-12).solve()
        assert result.converged
        assert result.rounds == 1
        assert result.path[0].sold_value == pytest.approx([0.0])
        assert result.final_prices == pytest.approx([10.0])


class TestLiquidationRule:
    def test_the_margin_demand_matches_the_hand_computation(self):
        """D = V - C / m with C marked on the original position.

        H holds 100 units at 100 (V0 = 10000), capital 1500, m = 0.15, and a
        shock of -5. Then p = 95, C = 1500 - 500 = 1000, the financeable value
        is 1000 / 0.15 = 6666.67, and D = 9500 - 6666.67 = 2833.33.
        """
        scenario = levered_scenario(price_impact=0.01, price_shock=-5.0)
        result = FireSaleSolver(scenario, tolerance=1e-12, max_rounds=100_000).solve()

        first = result.path[0]
        assert first.prices[0] == pytest.approx(95.0)
        assert first.capital[0] == pytest.approx(1000.0)
        assert first.portfolio_values[0] == pytest.approx(9500.0)
        assert first.liquidation_demand[0] == pytest.approx(
            9500.0 - 1000.0 / 0.15
        )
        assert first.sold_value[0] == pytest.approx(first.liquidation_demand[0])
        assert first.sold_units[0, 0] == pytest.approx(
            first.liquidation_demand[0] / 95.0
        )

    def test_the_default_sale_is_pro_rata_across_assets(self):
        scenario = FireSaleScenario(
            institution_ids=["A", "B"],
            asset_ids=["X", "Y"],
            holdings=np.array([[10.0, 20.0], [5.0, 0.0]]),
            prices=np.array([10.0, 5.0]),
            capital=np.array([200.0, 60.0]),
            endowments=np.array([0.0, 0.0]),
            liabilities=np.array([[0.0, 250.0], [0.0, 0.0]]),
            margins=np.array([1.0, 1.0]),
            price_impacts=np.array([0.2, 0.1]),
            price_shock=np.array([0.0, 0.0]),
        )
        result = FireSaleSolver(scenario, tolerance=1e-12, max_rounds=100).solve()

        # V = 10 * 10 + 20 * 5 = 200 and the shortfall is 50, so exactly 25% of
        # every position is sold: 2.5 units of X and 5 units of Y.
        first = result.path[0]
        assert result.converged
        assert first.liquidation_demand[0] == pytest.approx(50.0)
        assert first.sold_units[0].tolist() == pytest.approx([2.5, 5.0])

    def test_a_declared_liquidation_order_is_followed(self):
        scenario = FireSaleScenario(
            institution_ids=["A", "B"],
            asset_ids=["X", "Y"],
            holdings=np.array([[10.0, 20.0], [5.0, 0.0]]),
            prices=np.array([10.0, 5.0]),
            capital=np.array([200.0, 60.0]),
            endowments=np.array([0.0, 0.0]),
            liabilities=np.array([[0.0, 250.0], [0.0, 0.0]]),
            margins=np.array([1.0, 1.0]),
            price_impacts=np.array([0.2, 0.1]),
            price_shock=np.array([0.0, 0.0]),
            liquidation_order={"A": ["Y", "X"]},
        )
        result = FireSaleSolver(scenario, tolerance=1e-12, max_rounds=100).solve()

        # Y is sold first and holds 20 * 5 = 100 of value, more than the 50
        # needed, so nothing is taken from X in the first round.
        first = result.path[0]
        assert first.sold_units[0].tolist() == pytest.approx([0.0, 10.0])
        assert first.sold_value[0] == pytest.approx(50.0)


class TestMarginFeedback:
    def test_the_margin_in_force_matches_the_spiral_formula(self):
        """m = margin + kappa * (|dC| / V0 - sigma), clipped.

        A -5 shock on V0 = 10000 is a 5% return, so with kappa = 0.5 and
        sigma = 0 the margin is 0.15 + 0.5 * 0.05 = 0.175.
        """
        scenario = levered_scenario(
            price_impact=0.01, margin_sensitivity=0.5, price_shock=-5.0
        )
        result = FireSaleSolver(scenario, tolerance=1e-12, max_rounds=100_000).solve()
        assert result.path[0].margins_in_force[0] == pytest.approx(0.175)

    def test_margin_is_unchanged_without_sensitivity(self):
        result = FireSaleSolver(
            levered_scenario(price_impact=0.01), tolerance=1e-12, max_rounds=100_000
        ).solve()
        assert result.path[0].margins_in_force[0] == pytest.approx(0.15)

    def test_the_margin_spiral_raises_the_margin_and_the_loss(self):
        without = FireSaleSolver(
            levered_scenario(price_impact=0.01), tolerance=1e-12, max_rounds=100_000
        ).solve()
        with_margin = FireSaleSolver(
            levered_scenario(price_impact=0.01, margin_sensitivity=2.0),
            tolerance=1e-12,
            max_rounds=100_000,
        ).solve()

        assert with_margin.path[0].margins_in_force[0] > without.path[0].margins_in_force[0]
        assert with_margin.final_holdings[0, 0] < without.final_holdings[0, 0]
        assert with_margin.final_prices[0] < without.final_prices[0]

    def test_the_margin_is_bounded(self):
        scenario = FireSaleScenario(
            institution_ids=["H"],
            asset_ids=["X"],
            holdings=np.array([[100.0]]),
            prices=np.array([100.0]),
            capital=np.array([1500.0]),
            endowments=np.array([0.0]),
            liabilities=np.zeros((1, 1)),
            margins=np.array([0.15]),
            price_impacts=np.array([0.01]),
            price_shock=np.array([-50.0]),
            margin_sensitivity=np.array([1_000.0]),
            max_margin=0.9,
        )
        result = FireSaleSolver(scenario, tolerance=1e-12, max_rounds=100_000).solve()
        assert result.path[0].margins_in_force[0] <= 0.9


class TestReusesExistingMachinery:
    def test_the_margin_channel_reaches_the_spirals_own_fixed_point(self):
        """A single levered holder with no liabilities: the margin channel alone.

        With nothing owed there is no clearing shortfall, so the only sale is
        the margin channel. At the fixed point this solver reports the same
        price and position as ``LiquiditySpiralModel.cascade``, which solves the
        same two equations by its own nested iteration. Agreement to tight
        tolerance is evidence the shared machinery is the same function and has
        not drifted into a second definition.
        """
        for shock in (-1.0, -5.0):
            for price_impact in (0.01, 0.05):
                scenario = FireSaleScenario(
                    institution_ids=["H"],
                    asset_ids=["X"],
                    holdings=np.array([[100.0]]),
                    prices=np.array([100.0]),
                    capital=np.array([1500.0]),
                    endowments=np.array([0.0]),
                    liabilities=np.zeros((1, 1)),
                    margins=np.array([0.15]),
                    price_impacts=np.array([price_impact]),
                    price_shock=np.array([shock]),
                )
                mine = FireSaleSolver(
                    scenario, tolerance=1e-13, max_rounds=1_000_000
                ).solve()
                spiral = LiquiditySpiralModel(
                    SpiralParameters(
                        price=100.0,
                        position=100.0,
                        capital=1500.0,
                        margin=0.15,
                        price_impact=price_impact,
                    )
                ).cascade(shock)

                assert mine.converged
                assert mine.final_prices[0] == pytest.approx(
                    spiral.final_price, rel=1e-9, abs=1e-9
                )
                assert mine.final_holdings[0, 0] == pytest.approx(
                    spiral.final_position, rel=1e-9, abs=1e-9
                )

    def test_the_price_impact_law_is_the_spirals_linear_law(self):
        """``p = p0 + shock - lambda * Q``, with Q the cumulative units sold.

        This is the spiral's ``dp = shock + lambda * dX`` aggregated across
        sellers, and it is checked directly against the reported quantities.
        """
        scenario = worked_scenario(price_impact=0.5)
        result = FireSaleSolver(scenario, tolerance=1e-12).solve()

        cumulative = np.zeros(scenario.n_assets)
        for round_record in result.path:
            cumulative = cumulative + round_record.sold_units.sum(axis=0)
            expected = (
                scenario.prices
                + scenario.price_shock
                - scenario.price_impacts * cumulative
            )
            assert round_record.next_prices == pytest.approx(expected)


class TestDeterminismAndRecord:
    def test_identical_inputs_give_an_identical_result(self):
        first = FireSaleSolver(feedback_scenario(), tolerance=1e-12).solve()
        second = FireSaleSolver(feedback_scenario(), tolerance=1e-12).solve()
        assert first.to_dict() == second.to_dict()

    def test_repeated_solves_on_one_solver_are_identical(self):
        solver = FireSaleSolver(feedback_scenario(), tolerance=1e-12)
        assert solver.solve().to_dict() == solver.solve().to_dict()

    def test_the_payload_is_json_serialisable(self):
        result = FireSaleSolver(feedback_scenario(), tolerance=1e-12).solve()
        payload = result.to_dict()
        encoded = json.dumps(payload, allow_nan=False)
        assert "feedback_caused_defaults" in encoded

    def test_the_path_carries_the_evidence(self):
        result = FireSaleSolver(worked_scenario(), tolerance=1e-12).solve()
        payload = result.to_dict()
        assert payload["converged"] is True
        assert payload["diverged"] is False
        assert payload["final_prices"] == {"X": 5.0}
        assert payload["final_defaults"] == ["A"]
        assert len(payload["path"]) == result.rounds
        first = payload["path"][0]
        assert first["prices"] == {"X": 10.0}
        assert first["shortfall"]["A"] == 50.0
        assert first["sold_units"]["A"]["X"] == 5.0
        assert first["clearing"]["total_shortfall"] == 50.0

    def test_the_convenience_wrapper_matches_the_solver(self):
        direct = FireSaleSolver(worked_scenario(), tolerance=1e-9).solve()
        wrapped = solve_fire_sale(worked_scenario(), tolerance=1e-9)
        assert direct.to_dict() == wrapped.to_dict()


class TestFailClosed:
    def base(self, **overrides):
        values = dict(
            institution_ids=["A", "B"],
            asset_ids=["X"],
            holdings=np.array([[10.0], [0.0]]),
            prices=np.array([10.0]),
            capital=np.array([1000.0, 0.0]),
            endowments=np.array([0.0, 0.0]),
            liabilities=np.array([[0.0, 150.0], [0.0, 0.0]]),
            margins=np.array([1.0, 1.0]),
            price_impacts=np.array([0.5]),
            price_shock=np.array([0.0]),
        )
        values.update(overrides)
        return values

    def test_unknown_institution_id_in_the_liquidation_order_is_rejected(self):
        with pytest.raises(ValueError, match="unknown institution id"):
            FireSaleScenario(**self.base(liquidation_order={"ghost": ["X"]}))

    def test_unknown_asset_id_in_the_liquidation_order_is_rejected(self):
        with pytest.raises(ValueError, match="unknown asset"):
            FireSaleScenario(**self.base(liquidation_order={"A": ["Z"]}))

    def test_duplicate_institution_ids_are_rejected(self):
        with pytest.raises(ValueError, match="duplicate"):
            FireSaleScenario(**self.base(institution_ids=["A", "A"]))

    def test_negative_or_non_finite_prices_are_rejected(self):
        with pytest.raises(ValueError, match="strictly positive"):
            FireSaleScenario(**self.base(prices=np.array([0.0])))
        with pytest.raises(ValueError, match="non-finite"):
            FireSaleScenario(**self.base(prices=np.array([np.nan])))

    def test_negative_or_non_finite_holdings_are_rejected(self):
        with pytest.raises(ValueError, match="holdings cannot be negative"):
            FireSaleScenario(**self.base(holdings=np.array([[-1.0], [0.0]])))
        with pytest.raises(ValueError, match="non-finite"):
            FireSaleScenario(**self.base(holdings=np.array([[np.inf], [0.0]])))

    def test_negative_or_non_finite_capital_is_rejected(self):
        with pytest.raises(ValueError, match="capital cannot be negative"):
            FireSaleScenario(**self.base(capital=np.array([-1.0, 0.0])))
        with pytest.raises(ValueError, match="non-finite"):
            FireSaleScenario(**self.base(capital=np.array([np.nan, 0.0])))

    def test_negative_endowments_are_rejected(self):
        with pytest.raises(ValueError, match="endowments cannot be negative"):
            FireSaleScenario(**self.base(endowments=np.array([-1.0, 0.0])))

    def test_liabilities_the_clearing_engine_cannot_consume_are_rejected(self):
        with pytest.raises(ValueError, match="liabilities must have shape"):
            FireSaleScenario(**self.base(liabilities=np.zeros((2, 3))))
        with pytest.raises(ValueError, match="liabilities cannot be negative"):
            FireSaleScenario(
                **self.base(
                    liabilities=np.array([[0.0, -1.0], [0.0, 0.0]])
                )
            )
        with pytest.raises(ValueError, match="liabilities contains non-finite"):
            FireSaleScenario(
                **self.base(
                    liabilities=np.array([[0.0, np.inf], [0.0, 0.0]])
                )
            )

    def test_out_of_range_margins_are_rejected(self):
        with pytest.raises(ValueError, match="margins"):
            FireSaleScenario(**self.base(margins=np.array([0.0, 1.0])))
        with pytest.raises(ValueError, match="margins"):
            FireSaleScenario(**self.base(margins=np.array([1.5, 1.0])))

    def test_negative_price_impact_is_rejected(self):
        with pytest.raises(ValueError, match="price_impacts cannot be negative"):
            FireSaleScenario(**self.base(price_impacts=np.array([-0.1])))

    def test_a_shock_that_removes_the_price_is_rejected(self):
        with pytest.raises(ValueError, match="strictly positive"):
            FireSaleScenario(**self.base(price_shock=np.array([-10.0])))

    def test_an_unfinanceable_initial_position_is_rejected(self):
        with pytest.raises(ValueError, match="not financeable"):
            FireSaleScenario(**self.base(capital=np.array([5.0, 0.0])))

    def test_a_zero_tolerance_is_rejected(self):
        with pytest.raises(ValueError, match="tolerance must be strictly positive"):
            FireSaleSolver(worked_scenario(), tolerance=0.0)

    def test_a_negative_round_cap_is_rejected(self):
        with pytest.raises(ValueError, match="max_rounds"):
            FireSaleSolver(worked_scenario(), max_rounds=-1)
        with pytest.raises(ValueError, match="max_rounds"):
            FireSaleSolver(worked_scenario(), max_rounds=0)

    def test_a_zero_or_negative_stability_limit_is_rejected(self):
        with pytest.raises(ValueError, match="stability_limit"):
            FireSaleSolver(worked_scenario(), stability_limit=0.0)
        with pytest.raises(ValueError, match="stability_limit"):
            FireSaleSolver(worked_scenario(), stability_limit=-1.0)

    def test_a_zero_clearing_tolerance_is_rejected(self):
        with pytest.raises(ValueError, match="clearing_tolerance"):
            FireSaleSolver(worked_scenario(), clearing_tolerance=0.0)

    def test_endowments_for_rejects_mis_shaped_state(self):
        solver = FireSaleSolver(worked_scenario())
        with pytest.raises(ValueError, match="holdings must have shape"):
            solver.endowments_for(
                np.zeros((3, 1)), np.zeros(2), np.array([10.0])
            )
        with pytest.raises(ValueError, match="cash has length"):
            solver.endowments_for(
                np.zeros((2, 1)), np.zeros(3), np.array([10.0])
            )
