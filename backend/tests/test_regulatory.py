"""Tests for the Basel III regulatory ratio module.

The central tests are **hand-computed worked examples**: every headline number the
implementation returns is stated in a comment and asserted against arithmetic done
by hand, not against the implementation itself. A module that agreed only with
itself would pass none of them.

The stress tests reuse the real clearing engine
(:func:`backend.modules.risk.clearing.sequential_clearing`) rather than a
hand-built ``ClearingResult``, so the coupling between clearing and the
regulatory ratios is exercised end to end, and the pre-stress ratios are asserted
to sit *above* their thresholds so that a reported breach cannot be an artefact of
a mis-specified baseline.
"""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pytest

from backend.exceptions import DataQualityError
from backend.modules.risk.clearing import sequential_clearing
from backend.modules.risk.regulatory import (
    ASF_FACTORS,
    ASF_STABLE_RETAIL_DEPOSITS,
    ASF_TIER1_CAPITAL,
    ASF_WHOLESALE_LONG_TERM,
    CCF_DIRECT_CREDIT_SUBSTITUTES,
    CCF_UNCONDITIONALLY_CANCELLABLE,
    HQLA_LEVEL2A_HAIRCUT,
    HQLA_LEVEL2B_HAIRCUT,
    INFLOW_RATES,
    INFLOW_RETAIL_LOANS,
    INFLOW_WHOLESALE_NON_OPERATIONAL,
    INFLOW_CAP,
    LEVEL2_HQLA_CAP,
    MIN_LEVERAGE_RATIO,
    MIN_LCR,
    MIN_NSFR,
    OUTFLOW_RATES,
    OUTFLOW_LESS_STABLE_RETAIL_DEPOSITS,
    OUTFLOW_STABLE_RETAIL_DEPOSITS,
    RSF_HQLA_LEVEL1,
    RSF_LOANS_CORPORATE_LONG,
    RSF_LOANS_RETAIL_LONG,
    RSF_OTHER_ASSETS,
    InstitutionState,
    LeveragePosition,
    LiquidityPosition,
    StableFundingPosition,
    compute_lcr,
    compute_leverage_ratio,
    compute_nsfr,
    translate_systemic_stress,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def worked_liquidity_position() -> LiquidityPosition:
    """The fully hand-computed LCR example (see ``test_worked_example``)."""
    return LiquidityPosition(
        level1_assets=200.0,
        level2a_assets=40.0,
        level2b_assets=32.0,
        outflows_by_category={
            OUTFLOW_STABLE_RETAIL_DEPOSITS: 800.0,
            OUTFLOW_LESS_STABLE_RETAIL_DEPOSITS: 400.0,
        },
        inflows_by_category={INFLOW_RETAIL_LOANS: 60.0},
    )


def worked_funding_position() -> StableFundingPosition:
    """The fully hand-computed NSFR example (see ``test_worked_example``)."""
    return StableFundingPosition(
        asf_by_category={
            ASF_TIER1_CAPITAL: 100.0,
            ASF_STABLE_RETAIL_DEPOSITS: 400.0,
            ASF_WHOLESALE_LONG_TERM: 420.0,
        },
        rsf_by_category={
            RSF_HQLA_LEVEL1: 100.0,
            RSF_LOANS_CORPORATE_LONG: 400.0,
            RSF_LOANS_RETAIL_LONG: 300.0,
            RSF_OTHER_ASSETS: 120.0,
        },
    )


def worked_leverage_position() -> LeveragePosition:
    """The fully hand-computed leverage example (see ``test_worked_example``)."""
    return LeveragePosition(
        tier1_capital=100.0,
        on_balance_sheet_assets=1_900.0,
        derivative_exposure=50.0,
        off_balance_sheet_items={
            CCF_UNCONDITIONALLY_CANCELLABLE: 200.0,
            CCF_DIRECT_CREDIT_SUBSTITUTES: 30.0,
        },
    )


def clearing_shortfall_result():
    """BankB owes BankA 100 and has no endowment, so BankA loses 100."""
    liabilities = np.array([[0.0, 0.0], [100.0, 0.0]])
    return sequential_clearing(
        liabilities, [0.0, 0.0], node_ids=["BankA", "BankB"]
    )


def stress_institution(
    institution_id: str,
    *,
    level1: float,
    retail_outflow: float,
    tier1: float,
    on_balance_sheet: float,
    retail_deposit: float,
    corporate_asset: float,
    price_sensitive_assets: float = 0.0,
) -> InstitutionState:
    """A minimally consistent institution for the stress tests."""
    return InstitutionState(
        institution_id=institution_id,
        liquidity=LiquidityPosition(
            level1_assets=level1,
            outflows_by_category={OUTFLOW_STABLE_RETAIL_DEPOSITS: retail_outflow},
        ),
        funding=StableFundingPosition(
            asf_by_category={ASF_TIER1_CAPITAL: tier1, ASF_STABLE_RETAIL_DEPOSITS: retail_deposit},
            rsf_by_category={
                RSF_HQLA_LEVEL1: level1,
                RSF_LOANS_CORPORATE_LONG: corporate_asset,
            },
        ),
        leverage=LeveragePosition(
            tier1_capital=tier1,
            on_balance_sheet_assets=on_balance_sheet,
        ),
        price_sensitive_assets=price_sensitive_assets,
    )


# ---------------------------------------------------------------------------
# Candidate BankA / BankB used by the stress tests
# ---------------------------------------------------------------------------


def bank_a() -> InstitutionState:
    """Pre-stress LCR 1.5, leverage 10%, NSFR ~1.38; all above threshold."""
    return stress_institution(
        "BankA",
        level1=150.0,
        # 2000 * 5% = 100 of weighted outflows -> LCR before = 150 / 100 = 1.50.
        retail_outflow=2_000.0,
        tier1=100.0,
        on_balance_sheet=1_000.0,
        retail_deposit=400.0,
        corporate_asset=400.0,
        price_sensitive_assets=100.0,
    )


def bank_b() -> InstitutionState:
    """The defaulting counterparty; no clearing loss falls on it."""
    return stress_institution(
        "BankB",
        level1=50.0,
        # 1000 * 5% = 50 outflows -> LCR before = 50 / 50 = 1.0.
        retail_outflow=1_000.0,
        tier1=20.0,
        on_balance_sheet=200.0,
        retail_deposit=100.0,
        corporate_asset=50.0,
    )


# ---------------------------------------------------------------------------
# LCR
# ---------------------------------------------------------------------------


class TestLiquidityCoverageRatio:
    def test_worked_example(self):
        """Fully hand-computed LCR.

        HQLA:       L1 200 * 100% = 200
                    L2A 40 * 85%  =  34
                    L2B 32 * 50%  =  16
                    ----------------------
                    total            250
        Level 2 cap: 2/3 * 200 = 133.33; uncapped Level 2 = 50, so not binding.
        Outflows:   800 * 5%       = 40
                    400 * 10%      = 40
                    ----------------------
                    total            80
        Inflows:    60 * 50%       = 30; cap = 0.75 * 80 = 60, so not binding.
        Net:        80 - 30        = 50
        LCR:        250 / 50       = 5.0
        """
        result = compute_lcr(worked_liquidity_position())

        assert result.hqla == pytest.approx(250.0)
        assert result.hqla_level1 == pytest.approx(200.0)
        assert result.hqla_level2a == pytest.approx(34.0)
        assert result.hqla_level2b == pytest.approx(16.0)
        assert result.level2_uncapped == pytest.approx(50.0)
        assert result.level2_cap_binding is False
        assert result.outflows == pytest.approx(80.0)
        assert result.inflows == pytest.approx(30.0)
        assert result.effective_inflows == pytest.approx(30.0)
        assert result.inflows_capped is False
        assert result.net_cash_outflows == pytest.approx(50.0)
        assert result.lcr == pytest.approx(5.0)
        assert result.compliant is True

    def test_the_factor_tables_are_source_values(self):
        """A guard against a factor being silently edited in the code."""
        assert OUTFLOW_RATES[OUTFLOW_STABLE_RETAIL_DEPOSITS] == pytest.approx(0.05)
        assert OUTFLOW_RATES[OUTFLOW_LESS_STABLE_RETAIL_DEPOSITS] == pytest.approx(0.10)
        assert INFLOW_RATES[INFLOW_RETAIL_LOANS] == pytest.approx(0.50)
        assert HQLA_LEVEL2A_HAIRCUT == pytest.approx(0.15)
        assert HQLA_LEVEL2B_HAIRCUT == pytest.approx(0.50)
        assert LEVEL2_HQLA_CAP == pytest.approx(0.40)
        assert INFLOW_CAP == pytest.approx(0.75)
        assert MIN_LCR == pytest.approx(1.0)

    def test_level_2_cap_binds(self):
        """The 40% cap, hand-computed.

        L1  60 * 100% = 60
        L2A 40 * 85%  = 34
        L2B 40 * 50%  = 20  -> uncapped Level 2 = 54
        Allowance at the cap: L2 = 0.4 * (60 + L2) -> L2 = (2/3) * 60 = 40.
        So 14 of the 54 is excluded, taken from Level 2B first:
            L2B included = 20 - 14 = 6
            L2A included = 34
        HQLA = 60 + 34 + 6 = 100.
        Outflows 2000 * 5% = 100; inflows 0; net = 100; LCR = 100 / 100 = 1.0.
        """
        position = LiquidityPosition(
            level1_assets=60.0,
            level2a_assets=40.0,
            level2b_assets=40.0,
            outflows_by_category={OUTFLOW_STABLE_RETAIL_DEPOSITS: 2_000.0},
        )
        result = compute_lcr(position)

        assert result.level2_uncapped == pytest.approx(54.0)
        assert result.level2_cap_binding is True
        assert result.level2_excluded == pytest.approx(14.0)
        assert result.hqla == pytest.approx(100.0)
        assert result.hqla_level1 == pytest.approx(60.0)
        assert result.hqla_level2a == pytest.approx(34.0)
        assert result.hqla_level2b == pytest.approx(6.0)
        # Exactly at the minimum: compliant, because the rule is lcr >= 1.0.
        assert result.lcr == pytest.approx(1.0)
        assert result.compliant is True

    def test_level_2_cap_at_the_boundary_is_not_reported_as_binding(self):
        """Equality is not a binding cap: nothing was excluded."""
        # L2A 40 * 0.85 = 34; L2B 52 * 0.50 = 26; uncapped = 60 = (2/3) * 90.
        position = LiquidityPosition(
            level1_assets=90.0,
            level2a_assets=40.0,
            level2b_assets=52.0,
            outflows_by_category={OUTFLOW_STABLE_RETAIL_DEPOSITS: 1_000.0},
        )
        result = compute_lcr(position)

        assert result.hqla == pytest.approx(150.0)
        assert result.level2_excluded == pytest.approx(0.0)
        assert result.level2_cap_binding is False

    def test_a_level_2_only_book_is_capped_to_zero(self):
        """With no Level 1, the cap makes Level 2 ineligible entirely."""
        position = LiquidityPosition(
            level2a_assets=100.0,
            outflows_by_category={OUTFLOW_STABLE_RETAIL_DEPOSITS: 1_000.0},
        )
        result = compute_lcr(position)
        assert result.hqla == pytest.approx(0.0)
        assert result.level2_cap_binding is True
        assert result.compliant is False

    def test_inflow_cap_binds(self):
        """The 75%-of-outflows inflow cap, hand-computed.

        Outflows: 2000 * 5% = 100.
        Inflows:  200 * 100% = 200, but allowed only up to 0.75 * 100 = 75.
        Net:      100 - 75 = 25.
        HQLA:     Level 1 100 only.
        LCR:      100 / 25 = 4.0.
        """
        position = LiquidityPosition(
            level1_assets=100.0,
            outflows_by_category={OUTFLOW_STABLE_RETAIL_DEPOSITS: 2_000.0},
            inflows_by_category={INFLOW_WHOLESALE_NON_OPERATIONAL: 200.0},
        )
        result = compute_lcr(position)

        assert result.outflows == pytest.approx(100.0)
        assert result.inflows == pytest.approx(200.0)
        assert result.effective_inflows == pytest.approx(75.0)
        assert result.inflows_capped is True
        assert result.net_cash_outflows == pytest.approx(25.0)
        assert result.lcr == pytest.approx(4.0)

    def test_inflows_at_the_cap_are_not_reported_as_capped(self):
        """Exactly 75% is admitted in full, so the cap did not bind."""
        position = LiquidityPosition(
            level1_assets=100.0,
            outflows_by_category={OUTFLOW_STABLE_RETAIL_DEPOSITS: 2_000.0},
            inflows_by_category={INFLOW_WHOLESALE_NON_OPERATIONAL: 75.0},
        )
        result = compute_lcr(position)
        assert result.inflows_capped is False
        assert result.net_cash_outflows == pytest.approx(25.0)

    def test_a_below_minimum_lcr_is_reported_as_non_compliant(self):
        position = LiquidityPosition(
            level1_assets=50.0,
            outflows_by_category={OUTFLOW_STABLE_RETAIL_DEPOSITS: 2_000.0},
        )
        result = compute_lcr(position)
        assert result.lcr == pytest.approx(0.5)
        assert result.compliant is False


# ---------------------------------------------------------------------------
# NSFR
# ---------------------------------------------------------------------------


class TestNetStableFundingRatio:
    def test_worked_example(self):
        """Fully hand-computed NSFR.

        ASF: Tier 1 100 * 100%          = 100
             stable retail 400 * 95%    = 380
             wholesale >= 1y 420 * 100% = 420
             -------------------------------
             available                  = 900
        RSF: HQLA L1 100 * 5%           =   5
             corporate loan >= 1y 400 * 85% = 340
             retail loan >= 1y 300 * 85%    = 255
             other assets 120 * 100%        = 120
             -------------------------------
             required                       = 720
        NSFR = 900 / 720 = 1.25
        """
        result = compute_nsfr(worked_funding_position())

        assert result.available_stable_funding == pytest.approx(900.0)
        assert result.required_stable_funding == pytest.approx(720.0)
        assert result.nsfr == pytest.approx(1.25)
        assert result.compliant is True
        assert len(result.asf_contributions) == 3
        assert len(result.rsf_contributions) == 4

    def test_every_contribution_reconstructs_the_totals(self):
        """The aggregate is the sum of its published parts, not an opaque field."""
        result = compute_nsfr(worked_funding_position())
        assert sum(row.contribution for row in result.asf_contributions) == pytest.approx(
            result.available_stable_funding
        )
        assert sum(row.contribution for row in result.rsf_contributions) == pytest.approx(
            result.required_stable_funding
        )
        for row in result.asf_contributions + result.rsf_contributions:
            assert row.contribution == pytest.approx(row.amount * row.factor)

    def test_the_factor_tables_are_source_values(self):
        assert ASF_FACTORS[ASF_TIER1_CAPITAL] == pytest.approx(1.00)
        assert ASF_FACTORS[ASF_STABLE_RETAIL_DEPOSITS] == pytest.approx(0.95)
        assert MIN_NSFR == pytest.approx(1.0)

    def test_a_below_minimum_nsfr_is_reported_as_non_compliant(self):
        # Available 700 (tier 1 700), required 800 (other assets 800) -> 0.875.
        position = StableFundingPosition(
            asf_by_category={ASF_TIER1_CAPITAL: 700.0},
            rsf_by_category={RSF_OTHER_ASSETS: 800.0},
        )
        result = compute_nsfr(position)
        assert result.nsfr == pytest.approx(0.875)
        assert result.compliant is False


# ---------------------------------------------------------------------------
# Leverage ratio
# ---------------------------------------------------------------------------


class TestLeverageRatio:
    def test_worked_example_with_an_off_balance_sheet_ccf(self):
        """Fully hand-computed leverage ratio.

        On-balance-sheet                 = 1,900
        Derivative exposure              =    50
        Unconditionally cancellable 200 * 10% = 20
        Direct credit substitutes   30 * 100% = 30
        ------------------------------------------
        Total exposure measure           = 2,000
        Leverage = 100 / 2000 = 0.05 (5%), above the 3% minimum.
        """
        result = compute_leverage_ratio(worked_leverage_position())

        assert result.off_balance_sheet_exposure == pytest.approx(50.0)
        assert result.total_exposure_measure == pytest.approx(2_000.0)
        assert result.leverage_ratio == pytest.approx(0.05)
        assert result.compliant is True

    def test_the_ccf_table_is_the_leverage_definition(self):
        result = compute_leverage_ratio(worked_leverage_position())
        by_category = {row.category: row for row in result.obs_contributions}
        assert by_category[CCF_UNCONDITIONALLY_CANCELLABLE].contribution == pytest.approx(20.0)
        assert by_category[CCF_DIRECT_CREDIT_SUBSTITUTES].contribution == pytest.approx(30.0)

    def test_below_the_minimum_is_reported_as_non_compliant(self):
        # 50 / 2000 = 2.5% < 3%.
        position = LeveragePosition(tier1_capital=50.0, on_balance_sheet_assets=2_000.0)
        result = compute_leverage_ratio(position)
        assert result.leverage_ratio == pytest.approx(0.025)
        assert result.compliant is False
        assert MIN_LEVERAGE_RATIO == pytest.approx(0.03)

    def test_exactly_at_the_minimum_is_compliant(self):
        # 60 / 2000 = 3.0% exactly.
        position = LeveragePosition(tier1_capital=60.0, on_balance_sheet_assets=2_000.0)
        assert compute_leverage_ratio(position).compliant is True


# ---------------------------------------------------------------------------
# Stress translation
# ---------------------------------------------------------------------------


class TestStressTranslation:
    def test_no_stress_reports_the_pre_stress_table_and_says_so(self):
        states = [bank_a(), bank_b()]
        result = translate_systemic_stress(states)

        assert result.stress_applied is False
        assert result.price_decline is None
        assert result.clearing_total_shortfall is None
        for row in result.rows:
            assert row.total_loss == pytest.approx(0.0)
            assert row.lcr_after == pytest.approx(row.lcr_before)
            assert row.nsfr_after == pytest.approx(row.nsfr_before)
            assert row.leverage_after == pytest.approx(row.leverage_before)
            assert row.newly_breached == ()
            assert row.thresholds_breached_after == row.thresholds_breached_before

    def test_a_clearing_shortfall_breaches_lcr_and_leverage(self):
        """BankA loses the full 100 shortfall from BankB.

        Before: LCR = HQLA 150 / outflows 100 = 1.50 (> 1)
                leverage = 100 / 1000 = 10% (> 3%)
                NSFR = 480 / 347.5 = 1.381 (> 1)
        Stress: clearing loss 100, no price shock.
                Tier 1 100 - 100 = 0 -> leverage 0 / 900 = 0 (< 3%)
                HQLA 150 - 100 = 50 -> LCR 50 / 100 = 0.50 (< 1)
                ASF 480 - 100 = 380; RSF 347.5 - 100 * 5% = 342.5
                    -> NSFR = 380 / 342.5 = 1.109 (> 1, no new breach)
        """
        clearing = clearing_shortfall_result()
        result = translate_systemic_stress([bank_a(), bank_b()], clearing=clearing)

        assert result.stress_applied is True
        assert result.clearing_total_shortfall == pytest.approx(100.0)
        assert result.institutions_absent_from_clearing == ()

        bank_a_row = result.row_for("BankA")
        assert bank_a_row.clearing_loss == pytest.approx(100.0)
        assert bank_a_row.lcr_before == pytest.approx(1.5)
        assert bank_a_row.lcr_before > MIN_LCR
        assert bank_a_row.lcr_after == pytest.approx(0.5)
        assert bank_a_row.lcr_after < MIN_LCR
        assert bank_a_row.leverage_before == pytest.approx(0.10)
        assert bank_a_row.leverage_after == pytest.approx(0.0)
        assert bank_a_row.tier1_capital_after == pytest.approx(0.0)
        assert bank_a_row.capital_exhausted is True

        assert bank_a_row.thresholds_breached_before == ()
        assert set(bank_a_row.thresholds_breached_after) == {"lcr", "leverage"}
        assert set(bank_a_row.newly_breached) == {"lcr", "leverage"}
        assert "nsfr" not in bank_a_row.thresholds_breached_after

        # BankB is the defaulter, not a creditor, so it bears no clearing loss.
        bank_b_row = result.row_for("BankB")
        assert bank_b_row.clearing_loss == pytest.approx(0.0)
        assert bank_b_row.newly_breached == ()

    def test_a_price_decline_pushes_lcr_below_threshold(self):
        """A price shock with no clearing shortfall, hand-computed.

        BankA: price_sensitive_assets = 100, price_decline = 0.60 -> loss 60.
        LCR before 1.50; HQLA 150 - 60 = 90 -> LCR 90 / 100 = 0.90 (< 1).
        Leverage before 10%; Tier 1 100 - 60 = 40; exposure 1000 - 60 = 940
            -> 4.26% (still > 3%).
        """
        result = translate_systemic_stress([bank_a()], price_decline=0.60)

        assert result.stress_applied is True
        assert result.price_decline == pytest.approx(0.60)
        assert result.clearing_total_shortfall is None

        row = result.row_for("BankA")
        assert row.price_loss == pytest.approx(60.0)
        assert row.clearing_loss == pytest.approx(0.0)
        assert row.lcr_before == pytest.approx(1.5)
        assert row.lcr_after == pytest.approx(0.9)
        assert row.leverage_before == pytest.approx(0.10)
        assert row.leverage_after == pytest.approx(40.0 / 940.0)
        assert row.newly_breached == ("lcr",)

    def test_clearing_and_price_stress_add_up(self):
        """Both explicit shocks are additive, and no magnitude is invented."""
        clearing = clearing_shortfall_result()
        combined = translate_systemic_stress(
            [bank_a()], clearing=clearing, price_decline=0.10
        )
        row = combined.row_for("BankA")
        # loss = clearing 100 + 0.10 * 100 = 110.
        assert row.clearing_loss == pytest.approx(100.0)
        assert row.price_loss == pytest.approx(10.0)
        assert row.total_loss == pytest.approx(110.0)
        # HQLA 150 - 110 = 40, so the LCR is 40 / 100 = 0.4.
        assert row.hqla_before == pytest.approx(150.0)
        assert row.hqla_after == pytest.approx(40.0)
        assert row.lcr_after == pytest.approx(0.4)

    def test_a_zero_price_decline_is_not_a_stress(self):
        result = translate_systemic_stress([bank_a()], price_decline=0.0)
        assert result.stress_applied is False
        assert result.price_decline == pytest.approx(0.0)
        row = result.row_for("BankA")
        assert row.lcr_after == pytest.approx(row.lcr_before)

    def test_institutions_absent_from_the_clearing_network_are_named(self):
        clearing = clearing_shortfall_result()
        outsider = stress_institution(
            "BankC",
            level1=100.0,
            retail_outflow=1_000.0,
            tier1=50.0,
            on_balance_sheet=500.0,
            retail_deposit=100.0,
            corporate_asset=100.0,
        )
        result = translate_systemic_stress([bank_a(), bank_b(), outsider], clearing=clearing)
        assert result.institutions_absent_from_clearing == ("BankC",)
        assert result.row_for("BankC").clearing_loss == pytest.approx(0.0)

    def test_hqla_depletion_is_flagged_when_the_loss_exceeds_hqla(self):
        clearing = clearing_shortfall_result()
        result = translate_systemic_stress([bank_a()], clearing=clearing)
        bank_a_row = result.row_for("BankA")
        # Loss 100 <= HQLA 150, so no depletion.
        assert bank_a_row.hqla_depleted is False

        # A price shock of 100 % on a 100 book is a loss of 100, which exceeds
        # the 60 of HQLA declared here.
        thin = stress_institution(
            "ThinBank",
            level1=60.0,
            retail_outflow=1_000.0,
            tier1=40.0,
            on_balance_sheet=400.0,
            retail_deposit=100.0,
            corporate_asset=100.0,
            price_sensitive_assets=100.0,
        )
        thin_result = translate_systemic_stress([thin], price_decline=1.0)
        assert thin_result.row_for("ThinBank").hqla_depleted is True


# ---------------------------------------------------------------------------
# Fail-closed behaviour
# ---------------------------------------------------------------------------


class TestFailClosed:
    def test_negative_hqla_raises(self):
        with pytest.raises(DataQualityError, match="level1_assets"):
            LiquidityPosition(level1_assets=-1.0)
        with pytest.raises(DataQualityError, match="level2a_assets"):
            LiquidityPosition(level2a_assets=-0.01)

    def test_nan_inputs_raise(self):
        with pytest.raises(DataQualityError, match="level1_assets"):
            LiquidityPosition(level1_assets=float("nan"))
        with pytest.raises(DataQualityError, match="outflows_by_category"):
            LiquidityPosition(
                level1_assets=10.0,
                outflows_by_category={OUTFLOW_STABLE_RETAIL_DEPOSITS: float("nan")},
            )
        with pytest.raises(DataQualityError, match="tier1_capital"):
            LeveragePosition(tier1_capital=float("nan"))

    def test_non_finite_hqla_raises(self):
        with pytest.raises(DataQualityError, match="level2b_assets"):
            LiquidityPosition(level2b_assets=float("inf"))

    def test_capital_exceeding_total_assets_raises(self):
        with pytest.raises(DataQualityError, match="impossible"):
            LeveragePosition(tier1_capital=100.0, on_balance_sheet_assets=50.0)

    def test_price_sensitive_assets_exceeding_the_balance_sheet_raises(self):
        with pytest.raises(DataQualityError, match="price_sensitive_assets"):
            InstitutionState(
                institution_id="BankX",
                liquidity=LiquidityPosition(
                    level1_assets=100.0,
                    outflows_by_category={OUTFLOW_STABLE_RETAIL_DEPOSITS: 1_000.0},
                ),
                funding=StableFundingPosition(
                    asf_by_category={ASF_TIER1_CAPITAL: 10.0},
                    rsf_by_category={RSF_OTHER_ASSETS: 100.0},
                ),
                leverage=LeveragePosition(tier1_capital=10.0, on_balance_sheet_assets=100.0),
                price_sensitive_assets=101.0,
            )

    def test_empty_institution_set_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            translate_systemic_stress([])

    def test_duplicate_institution_ids_raise(self):
        with pytest.raises(ValueError, match="unique"):
            translate_systemic_stress([bank_a(), bank_a()])

    def test_unknown_category_names_raise(self):
        with pytest.raises(ValueError, match="unknown category"):
            LiquidityPosition(
                level1_assets=10.0,
                outflows_by_category={"not_a_basel_category": 1.0},
            )
        with pytest.raises(ValueError, match="unknown category"):
            StableFundingPosition(asf_by_category={"not_a_basel_category": 1.0})

    def test_missing_denominators_raise_rather_than_return_a_ratio(self):
        with pytest.raises(ValueError, match="outflows are zero"):
            compute_lcr(LiquidityPosition(level1_assets=100.0))
        with pytest.raises(ValueError, match="required stable funding is zero"):
            compute_nsfr(StableFundingPosition(asf_by_category={ASF_TIER1_CAPITAL: 100.0}))
        with pytest.raises(ValueError, match="total exposure measure is zero"):
            compute_leverage_ratio(LeveragePosition(tier1_capital=0.0))

    def test_price_decline_outside_zero_one_raises(self):
        with pytest.raises(ValueError, match="price_decline"):
            translate_systemic_stress([bank_a()], price_decline=1.5)
        with pytest.raises(ValueError, match="price_decline"):
            translate_systemic_stress([bank_a()], price_decline=-0.1)
        with pytest.raises(DataQualityError, match="price_decline"):
            translate_systemic_stress([bank_a()], price_decline=float("nan"))

    def test_a_non_converged_clearing_result_is_refused(self):
        non_converged = replace(clearing_shortfall_result(), converged=False)
        with pytest.raises(DataQualityError, match="did not converge"):
            translate_systemic_stress([bank_a()], clearing=non_converged)

    def test_an_inconsistent_clearing_result_is_refused(self):
        broken = replace(
            clearing_shortfall_result(), node_ids=["BankA", "BankB", "BankC"]
        )
        with pytest.raises(DataQualityError, match="internally inconsistent"):
            translate_systemic_stress([bank_a()], clearing=broken)

    def test_non_finite_clearing_losses_are_refused(self):
        broken = replace(
            clearing_shortfall_result(),
            losses_by_creditor=np.array([float("nan"), 0.0]),
        )
        with pytest.raises(DataQualityError, match="finite and non-negative"):
            translate_systemic_stress([bank_a()], clearing=broken)

    def test_blank_institution_id_raises(self):
        with pytest.raises(ValueError, match="institution_id"):
            replace(bank_a(), institution_id="")


# ---------------------------------------------------------------------------
# Determinism, immutability and serialisation
# ---------------------------------------------------------------------------


class TestDeterminismAndImmutability:
    def test_repeated_computations_are_equal(self):
        position = worked_liquidity_position()
        assert compute_lcr(position) == compute_lcr(position)
        assert compute_lcr(position).to_dict() == compute_lcr(position).to_dict()

        funding = worked_funding_position()
        assert compute_nsfr(funding).to_dict() == compute_nsfr(funding).to_dict()

        leverage = worked_leverage_position()
        assert compute_leverage_ratio(leverage).to_dict() == compute_leverage_ratio(
            leverage
        ).to_dict()

    def test_repeated_stress_runs_are_equal(self):
        clearing = clearing_shortfall_result()
        first = translate_systemic_stress(
            [bank_a(), bank_b()], clearing=clearing, price_decline=0.25
        )
        second = translate_systemic_stress(
            [bank_a(), bank_b()], clearing=clearing, price_decline=0.25
        )
        assert first == second
        assert first.to_dict() == second.to_dict()

    def test_the_position_copies_its_input_mapping(self):
        """Mutating the caller's dict after construction cannot move the result."""
        outflows = {OUTFLOW_STABLE_RETAIL_DEPOSITS: 2_000.0}
        position = LiquidityPosition(level1_assets=100.0, outflows_by_category=outflows)
        before = compute_lcr(position).lcr
        outflows[OUTFLOW_STABLE_RETAIL_DEPOSITS] = 10.0
        assert compute_lcr(position).lcr == pytest.approx(before)

    def test_results_are_json_serialisable_without_nan(self):
        clearing = clearing_shortfall_result()
        stress = translate_systemic_stress(
            [bank_a(), bank_b()], clearing=clearing, price_decline=0.10
        )
        json.dumps(compute_lcr(worked_liquidity_position()).to_dict(), allow_nan=False)
        json.dumps(compute_nsfr(worked_funding_position()).to_dict(), allow_nan=False)
        json.dumps(compute_leverage_ratio(worked_leverage_position()).to_dict(), allow_nan=False)
        json.dumps(stress.to_dict(), allow_nan=False)

    def test_a_stressed_ratio_is_carried_in_the_payload(self):
        clearing = clearing_shortfall_result()
        payload = translate_systemic_stress(
            [bank_a(), bank_b()], clearing=clearing
        ).to_dict()
        by_id = {row["institution_id"]: row for row in payload["rows"]}
        assert by_id["BankA"]["lcr_after"] == pytest.approx(0.5)
        assert by_id["BankA"]["capital_exhausted"] is True
        assert set(by_id["BankA"]["newly_breached"]) == {"lcr", "leverage"}
