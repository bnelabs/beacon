"""Tests for the cross-currency (FX swap) multiplex layers.

The central test in this file is not about arithmetic. It is that the two things
built here stay on the correct side of the module's most important boundary: an
FX swap is an obligation and may be cleared, while a cross-currency basis is a
price and may not. Running a clearing algorithm on a price is the exact category
error this codebase was rebuilt to remove, so ``require_exposure`` refusing the
basis layer is asserted directly rather than left implicit.

The arithmetic tests are hand-computed in the comments so they check the
implementation rather than restate it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.modules.engine.multiplex import (
    MultiplexSnapshot,
    RelationKind,
    build_fx_basis_layer,
    build_fx_swap_exposure_layer,
    cross_currency_funding_exposure,
    require_exposure,
)

T0 = pd.Timestamp("2025-12-01")
CUTOFF = pd.Timestamp("2026-01-01")
FUTURE = pd.Timestamp("2026-02-01")

UNIVERSE = ("A", "B", "C")


def funding_mix() -> pd.DataFrame:
    """A: all EUR. B: half EUR, half JPY. C: all USD."""
    return pd.DataFrame(
        [
            {"institution": "A", "currency": "EUR", "share": 1.0},
            {"institution": "B", "currency": "EUR", "share": 0.5},
            {"institution": "B", "currency": "JPY", "share": 0.5},
            {"institution": "C", "currency": "USD", "share": 1.0},
        ]
    )


# EUR -25bp, JPY -5bp, USD 0bp. A negative basis is the dollar-squeeze direction.
SQUEEZE_BASIS = {"EUR": -25.0, "JPY": -5.0, "USD": 0.0}


class TestCrossCurrencyFundingExposure:
    def test_hand_computed_exposure(self):
        # A = 1.00 * 25 = 25bp
        # B = 0.50 * 25 + 0.50 * 5 = 15bp
        # C = 1.00 * max(0, -0) = 0bp
        exposure = cross_currency_funding_exposure(funding_mix(), SQUEEZE_BASIS)
        assert exposure == {"A": 25.0, "B": 15.0, "C": 0.0}

    def test_a_positive_basis_contributes_nothing_in_stress_only_mode(self):
        # JPY at +10bp is the opposite direction, so it is not a dollar squeeze.
        # B = 0.50 * 25 + 0.50 * max(0, -10) = 12.5bp
        exposure = cross_currency_funding_exposure(
            funding_mix(), {"EUR": -25.0, "JPY": 10.0, "USD": 0.0}
        )
        assert exposure["B"] == pytest.approx(12.5)

    def test_absolute_mode_counts_both_directions(self):
        # B = 0.50 * 25 + 0.50 * 10 = 17.5bp
        exposure = cross_currency_funding_exposure(
            funding_mix(),
            {"EUR": -25.0, "JPY": 10.0, "USD": 0.0},
            stress_only=False,
        )
        assert exposure["B"] == pytest.approx(17.5)

    def test_a_missing_basis_for_a_funded_currency_raises(self):
        """A missing price is not a zero price."""
        with pytest.raises(KeyError, match="no basis observation"):
            cross_currency_funding_exposure(funding_mix(), {"EUR": -25.0, "USD": 0.0})

    def test_a_zero_share_currency_needs_no_basis_observation(self):
        mix = pd.DataFrame(
            [
                {"institution": "A", "currency": "EUR", "share": 1.0},
                {"institution": "A", "currency": "JPY", "share": 0.0},
            ]
        )
        exposure = cross_currency_funding_exposure(mix, {"EUR": -25.0})
        assert exposure == {"A": 25.0}

    def test_shares_must_sum_to_one(self):
        mix = pd.DataFrame(
            [
                {"institution": "A", "currency": "EUR", "share": 0.4},
                {"institution": "A", "currency": "USD", "share": 0.4},
            ]
        )
        with pytest.raises(ValueError, match="sum to 0.800000, not 1"):
            cross_currency_funding_exposure(mix, {"EUR": -25.0, "USD": 0.0})

    def test_a_negative_share_raises(self):
        mix = pd.DataFrame(
            [{"institution": "A", "currency": "EUR", "share": -0.5}]
        )
        with pytest.raises(ValueError, match="invalid"):
            cross_currency_funding_exposure(mix, {"EUR": -25.0})

    def test_conflicting_basis_observations_for_one_currency_raise(self):
        basis = pd.DataFrame(
            [
                {"currency": "EUR", "basis": -25.0},
                {"currency": "EUR", "basis": -30.0},
            ]
        )
        with pytest.raises(ValueError, match="conflicting basis"):
            cross_currency_funding_exposure(funding_mix(), basis)


class TestFxBasisLayer:
    def test_hand_computed_adjacency(self):
        # Stresses are A=25, B=15, C=0, so the only non-zero edge is A-B:
        # 25 * 15 = 375.
        layer = build_fx_basis_layer(
            funding_mix(), SQUEEZE_BASIS, UNIVERSE, as_of=CUTOFF
        )
        expected = np.array(
            [
                [0.0, 375.0, 0.0],
                [375.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],
            ]
        )
        assert np.array_equal(layer.adjacency, expected)

    def test_it_is_a_co_movement_layer_and_require_exposure_refuses_it(self):
        """The boundary that matters: a price is not an obligation."""
        layer = build_fx_basis_layer(
            funding_mix(), SQUEEZE_BASIS, UNIVERSE, as_of=CUTOFF
        )
        assert layer.kind is RelationKind.CO_MOVEMENT
        assert layer.is_clearing_eligible is False
        assert layer.metadata["clearing_eligible"] is False
        # The guard raises TypeError: passing the wrong *kind* of relation is a
        # type error about the relation, not a bad value in a correct one.
        with pytest.raises(TypeError, match="Only EXPOSURE layers may be cleared"):
            require_exposure(layer)

    def test_an_absent_institution_is_not_silently_treated_as_unexposed(self):
        """Absence of funding data is not evidence of domestic-only funding."""
        mix = funding_mix().loc[lambda df: df["institution"] != "C"]
        with pytest.raises(KeyError, match="no funding mix supplied for \\['C'\\]"):
            build_fx_basis_layer(mix, SQUEEZE_BASIS, UNIVERSE, as_of=CUTOFF)

    def test_absent_means_zero_is_an_explicit_recorded_declaration(self):
        mix = funding_mix().loc[lambda df: df["institution"] != "C"]
        layer = build_fx_basis_layer(
            mix, SQUEEZE_BASIS, UNIVERSE, as_of=CUTOFF, absent_means_zero=True
        )
        assert layer.metadata["nodes_assumed_base_currency_funded"] == ["C"]
        # C carries zero stress, so the only edge is still A-B.
        assert np.array_equal(
            layer.adjacency,
            np.array([[0.0, 375.0, 0.0], [375.0, 0.0, 0.0], [0.0, 0.0, 0.0]]),
        )

    def test_an_institution_outside_the_universe_raises(self):
        mix = pd.concat(
            [
                funding_mix(),
                pd.DataFrame(
                    [{"institution": "Z", "currency": "EUR", "share": 1.0}]
                ),
            ],
            ignore_index=True,
        )
        with pytest.raises(KeyError, match="outside the node universe"):
            build_fx_basis_layer(mix, SQUEEZE_BASIS, UNIVERSE, as_of=CUTOFF)

    def test_repeated_calls_are_identical(self):
        first = build_fx_basis_layer(
            funding_mix(), SQUEEZE_BASIS, UNIVERSE, as_of=CUTOFF
        )
        second = build_fx_basis_layer(
            funding_mix(), SQUEEZE_BASIS, UNIVERSE, as_of=CUTOFF
        )
        assert np.array_equal(first.adjacency, second.adjacency)
        assert first.metadata == second.metadata

    def test_the_layer_records_which_direction_it_counted(self):
        squeezed = build_fx_basis_layer(
            funding_mix(), SQUEEZE_BASIS, UNIVERSE, as_of=CUTOFF
        )
        absolute = build_fx_basis_layer(
            funding_mix(), SQUEEZE_BASIS, UNIVERSE, as_of=CUTOFF, stress_only=False
        )
        assert "negative basis is the stress" in squeezed.metadata["basis_convention"]
        assert "both directions" in absolute.metadata["basis_convention"]


class TestFxSwapExposureLayer:
    def swaps(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "debtor": "A",
                    "creditor": "B",
                    "notional": 100.0,
                    "currency_pair": "EURUSD",
                    "as_of": T0,
                },
                {
                    "debtor": "B",
                    "creditor": "C",
                    "notional": 50.0,
                    "currency_pair": "JPYUSD",
                    "as_of": T0,
                },
                {
                    "debtor": "A",
                    "creditor": "B",
                    "notional": 25.0,
                    "currency_pair": "GBPUSD",
                    "as_of": FUTURE,
                },
            ]
        )

    def test_hand_computed_obligations_and_orientation(self):
        layer = build_fx_swap_exposure_layer(self.swaps(), UNIVERSE, as_of=CUTOFF)
        # A owes B 100; B owes C 50. The future GBPUSD row is withheld.
        assert np.array_equal(
            layer.adjacency,
            np.array([[0.0, 100.0, 0.0], [0.0, 0.0, 50.0], [0.0, 0.0, 0.0]]),
        )
        assert layer.metadata["gross_notional"] == 150.0
        assert layer.metadata["rows_withheld_as_future"] == 1

    def test_it_is_clearing_eligible_and_require_exposure_accepts_it(self):
        layer = build_fx_swap_exposure_layer(self.swaps(), UNIVERSE, as_of=CUTOFF)
        assert layer.kind is RelationKind.EXPOSURE
        assert layer.is_clearing_eligible is True
        network = require_exposure(layer)
        assert network is not None

    def test_a_withheld_future_row_contributes_no_currency_pair(self):
        layer = build_fx_swap_exposure_layer(self.swaps(), UNIVERSE, as_of=CUTOFF)
        assert layer.metadata["currency_pairs"] == ["EURUSD", "JPYUSD"]
        assert "GBPUSD" not in layer.metadata["currency_pairs"]

    def test_an_unknown_counterparty_raises(self):
        frame = self.swaps().copy()
        frame.loc[0, "creditor"] = "Z"
        with pytest.raises(KeyError, match="outside the node universe"):
            build_fx_swap_exposure_layer(frame, UNIVERSE, as_of=CUTOFF)

    def test_a_negative_notional_raises(self):
        frame = pd.DataFrame(
            [{"debtor": "A", "creditor": "B", "notional": -5.0, "as_of": T0}]
        )
        with pytest.raises(ValueError, match="invalid notional"):
            build_fx_swap_exposure_layer(frame, UNIVERSE, as_of=CUTOFF)

    def test_a_non_finite_notional_raises(self):
        frame = pd.DataFrame(
            [{"debtor": "A", "creditor": "B", "notional": float("nan"), "as_of": T0}]
        )
        with pytest.raises(ValueError, match="invalid notional"):
            build_fx_swap_exposure_layer(frame, UNIVERSE, as_of=CUTOFF)

    def test_a_missing_column_raises(self):
        frame = pd.DataFrame([{"debtor": "A", "creditor": "B"}])
        with pytest.raises(ValueError, match="missing required column"):
            build_fx_swap_exposure_layer(frame, UNIVERSE, as_of=CUTOFF)

    def test_a_snapshot_keeps_obligation_separate_from_context(self):
        snapshot = MultiplexSnapshot(as_of=CUTOFF, node_ids=UNIVERSE)
        snapshot.add_layer(
            build_fx_swap_exposure_layer(self.swaps(), UNIVERSE, as_of=CUTOFF)
        )
        snapshot.add_layer(
            build_fx_basis_layer(
                funding_mix(), SQUEEZE_BASIS, UNIVERSE, as_of=CUTOFF
            )
        )

        clearing = snapshot.clearing_layers
        context = snapshot.without_clearing_layers()
        assert len(clearing) == 1
        assert list(context) == ["fx_swap_basis"]
        assert context["fx_swap_basis"].kind is RelationKind.CO_MOVEMENT
