"""Tests for crowded-trade portfolio overlap.

Every closed form here is computed by hand in a comment next to the assertion.
The pairwise matrices are checked for the structural properties they must have
(symmetry, unit diagonal, zero at disjointness) and, on small matrices, against
the exact arithmetic. The short/long convention and the missing-data policy are
pinned so that a future change to either cannot pass unnoticed.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from backend.exceptions import DataQualityError
from backend.modules.engine.portfolio_overlap import (
    CorrelatedUnwindExposure,
    CrowdingScore,
    InstrumentCrowding,
    MissingDataPolicy,
    PortfolioOverlapDataError,
    analyse_portfolio_overlap,
    correlated_unwind_exposure,
    instrument_crowding,
    jaccard_directional_overlap,
    jaccard_name_overlap,
    signed_cosine_overlap,
    system_crowding_score,
)


# A 3x3 book used by several hand-computed tests.
#
#          X   Y   Z
#   A      1   0   0      ||A|| = 1
#   B      1   1   0      ||B|| = sqrt(2)
#   C      0   0   2      ||C|| = 2
THREE_BY_THREE = [[1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 0.0, 2.0]]
THREE_IDS = ["A", "B", "C"]
THREE_INSTRUMENTS = ["X", "Y", "Z"]


class TestHandComputedOverlap:
    """Exact arithmetic on a matrix small enough to do on paper."""

    def test_cosine_matches_the_hand_computation(self):
        result = analyse_portfolio_overlap(
            THREE_BY_THREE, THREE_IDS, THREE_INSTRUMENTS
        )
        cosine = result.cosine_overlap
        # A.B = 1*1 = 1; ||A|| ||B|| = 1 * sqrt(2), so cos = 1/sqrt(2).
        assert cosine[0, 1] == pytest.approx(1.0 / math.sqrt(2.0), rel=1e-12)
        # A and C share no nonzero name, so the dot product is exactly 0.
        assert cosine[0, 2] == pytest.approx(0.0)
        assert cosine[1, 2] == pytest.approx(0.0)
        # A.A = 1 by definition.
        assert cosine[0, 0] == 1.0

    def test_jaccard_name_matches_the_hand_computation(self):
        result = analyse_portfolio_overlap(
            THREE_BY_THREE, THREE_IDS, THREE_INSTRUMENTS
        )
        jaccard = result.jaccard_name_overlap
        # A = {X}, B = {X, Y}: intersection 1, union 2.
        assert jaccard[0, 1] == pytest.approx(0.5, rel=1e-12)
        # A = {X}, C = {Z}: intersection 0, union 2.
        assert jaccard[0, 2] == pytest.approx(0.0)
        assert jaccard[1, 2] == pytest.approx(0.0)
        assert jaccard[0, 0] == 1.0

    def test_per_instrument_hhi_matches_the_hand_computation(self):
        result = analyse_portfolio_overlap(
            THREE_BY_THREE, THREE_IDS, THREE_INSTRUMENTS
        )
        by_name = {c.instrument: c for c in result.instrument_crowding}

        # X is held 1 each by A and B: shares 0.5, 0.5 -> HHI = 0.5.
        assert by_name["X"].hhi == pytest.approx(0.5, rel=1e-12)
        assert by_name["X"].n_holders == 2
        assert by_name["X"].effective_holders == pytest.approx(2.0, rel=1e-12)
        # Y is held only by B: HHI = 1.
        assert by_name["Y"].hhi == pytest.approx(1.0, rel=1e-12)
        # Z is held only by C: HHI = 1.
        assert by_name["Z"].hhi == pytest.approx(1.0, rel=1e-12)

    def test_system_score_matches_the_hand_computation(self):
        result = analyse_portfolio_overlap(
            THREE_BY_THREE, THREE_IDS, THREE_INSTRUMENTS
        )
        score = result.system_crowding
        # Gross: X = 2, Y = 1, Z = 2, total = 5. Weights: 0.4, 0.2, 0.4.
        # raw = 0.4*(2/3) + 0.2*(1/3) + 0.4*(1/3) = 7/15.
        assert score.raw == pytest.approx(7.0 / 15.0, rel=1e-12)
        # normalized = (7/15 - 1/3) / (2/3) = 1/5.
        assert score.normalized == pytest.approx(0.2, rel=1e-12)
        # weighted mean HHI = 0.4*0.5 + 0.2*1 + 0.4*1 = 0.8.
        assert score.weighted_mean_hhi == pytest.approx(0.8, rel=1e-12)
        assert score.total_gross_exposure == pytest.approx(5.0)


class TestMatrixProperties:
    def test_all_pairwise_matrices_are_symmetric_with_unit_diagonal(self):
        result = analyse_portfolio_overlap(
            THREE_BY_THREE, THREE_IDS, THREE_INSTRUMENTS
        )
        for matrix in (
            result.cosine_overlap,
            result.jaccard_name_overlap,
            result.jaccard_directional_overlap,
        ):
            assert np.allclose(matrix, matrix.T)
            assert np.allclose(np.diag(matrix), 1.0)
            # The cosine is a cosine and cannot leave [-1, 1].
            if matrix is result.cosine_overlap:
                assert matrix.min() >= -1.0
                assert matrix.max() <= 1.0

    def test_disjoint_books_sit_at_the_documented_minimum(self):
        positions = [[1.0, 0.0], [0.0, 2.0]]
        result = analyse_portfolio_overlap(positions, ["A", "B"], ["X", "Y"])
        assert result.cosine_overlap[0, 1] == pytest.approx(0.0)
        assert result.jaccard_name_overlap[0, 1] == pytest.approx(0.0)
        assert result.jaccard_directional_overlap[0, 1] == pytest.approx(0.0)

    def test_identical_books_overlap_completely(self):
        positions = [[1.0, 2.0], [1.0, 2.0]]
        result = analyse_portfolio_overlap(positions, ["A", "B"], ["X", "Y"])
        assert result.cosine_overlap[0, 1] == pytest.approx(1.0)
        assert result.jaccard_name_overlap[0, 1] == pytest.approx(1.0)
        assert result.jaccard_directional_overlap[0, 1] == pytest.approx(1.0)

    def test_an_all_zero_book_still_has_unit_self_overlap(self):
        result = analyse_portfolio_overlap(
            [[0.0, 0.0], [0.0, 0.0]], ["A", "B"], ["X", "Y"]
        )
        # Self-overlap is an identity, so it holds even where the cosine is
        # otherwise undefined; off-diagonal stays at zero.
        assert np.allclose(result.cosine_overlap, [[1.0, 0.0], [0.0, 1.0]])
        assert result.system_crowding.normalized == 0.0


class TestHhiBounds:
    def test_perfect_equality_is_one_over_n(self):
        # Three equal holders, one name: shares 1/3, HHI = 3*(1/9) = 1/3.
        crowding = instrument_crowding([[2.0], [2.0], [2.0]], ["X"])
        assert crowding[0].hhi == pytest.approx(1.0 / 3.0, rel=1e-12)
        assert crowding[0].effective_holders == pytest.approx(3.0, rel=1e-12)

    def test_a_single_holder_is_one(self):
        crowding = instrument_crowding([[5.0], [0.0], [0.0]], ["X"])
        assert crowding[0].hhi == pytest.approx(1.0)
        assert crowding[0].effective_holders == pytest.approx(1.0)
        assert crowding[0].n_holders == 1

    def test_unequal_holders_land_between_the_bounds(self):
        # 3 and 1 of a gross 4: shares 0.75 and 0.25 -> 0.5625 + 0.0625 = 0.625.
        crowding = instrument_crowding([[3.0], [1.0], [0.0]], ["X"])
        assert crowding[0].hhi == pytest.approx(0.625, rel=1e-12)
        assert crowding[0].effective_holders == pytest.approx(1.6, rel=1e-12)

    def test_an_unheld_instrument_has_zero_crowding_and_zero_weight(self):
        crowding = instrument_crowding([[1.0, 0.0]], ["X", "Y"])
        by_name = {c.instrument: c for c in crowding}
        assert by_name["Y"].n_holders == 0
        assert by_name["Y"].hhi == 0.0
        assert by_name["Y"].weight == 0.0


class TestSignConvention:
    """Shorts are negative; opposite sides are not the same crowded trade."""

    def test_long_versus_short_is_negative_cosine_and_no_directional_overlap(self):
        positions = [[5.0], [-5.0], [5.0], [-5.0]]
        result = analyse_portfolio_overlap(positions, ["A", "B", "C", "D"], ["X"])
        # A long 5 against B short 5: dot = -25, norms 5 each -> -1.
        assert result.cosine_overlap[0, 1] == pytest.approx(-1.0)
        # Two longs of the same size: dot = 25 -> +1.
        assert result.cosine_overlap[0, 2] == pytest.approx(1.0)
        # Two shorts of the same size also move together: +1, not -1.
        assert result.cosine_overlap[1, 3] == pytest.approx(1.0)
        # A and B touch the same name (sign-agnostic) ...
        assert result.jaccard_name_overlap[0, 1] == pytest.approx(1.0)
        # ... but they do not share it directionally.
        assert result.jaccard_directional_overlap[0, 1] == pytest.approx(0.0)
        assert result.jaccard_directional_overlap[0, 2] == pytest.approx(1.0)
        assert result.jaccard_directional_overlap[1, 3] == pytest.approx(1.0)

    def test_gross_crowding_reports_the_long_short_split(self):
        positions = [[5.0], [-5.0], [5.0]]
        result = analyse_portfolio_overlap(positions, ["A", "B", "C"], ["X"])
        entry = result.instrument_crowding[0]
        # Gross 15, three equal holders -> HHI = 1/3; longs 10, shorts 5.
        assert entry.gross_exposure == pytest.approx(15.0)
        assert entry.long_exposure == pytest.approx(10.0)
        assert entry.short_exposure == pytest.approx(5.0)
        assert entry.net_exposure == pytest.approx(5.0)
        assert entry.hhi == pytest.approx(1.0 / 3.0, rel=1e-12)

    def test_directional_jaccard_separates_mixed_books(self):
        positions = [
            [5.0, 3.0, 0.0],   # A: long X, long Y
            [5.0, -3.0, 1.0],  # B: long X, short Y, long Z
            [0.0, -3.0, 1.0],  # C: short Y, long Z
        ]
        result = analyse_portfolio_overlap(
            positions, ["A", "B", "C"], ["X", "Y", "Z"]
        )
        directional = result.jaccard_directional_overlap
        # A={X,Y}, B={X,Y,Z}: same side only on X -> 1/3.
        assert directional[0, 1] == pytest.approx(1.0 / 3.0, rel=1e-12)
        # A long Y, C short Y and no other shared side -> 0.
        assert directional[0, 2] == pytest.approx(0.0)
        # B={X,Y,Z}, C={Y,Z}: same side on Y and Z -> 2/3.
        assert directional[1, 2] == pytest.approx(2.0 / 3.0, rel=1e-12)
        # Names only: A and B share X and Y of a union of three -> 2/3.
        assert result.jaccard_name_overlap[0, 1] == pytest.approx(
            2.0 / 3.0, rel=1e-12
        )
        # Signed cosine A.B = 25 - 9 = 16 over sqrt(34)*sqrt(35).
        assert result.cosine_overlap[0, 1] == pytest.approx(
            16.0 / math.sqrt(34.0 * 35.0), rel=1e-12
        )


class TestSystemScoreRises:
    def test_more_institutions_piling_into_one_name_raises_the_score(self):
        # Both books have identical total gross exposure of 30.
        spread = [[10.0, 0.0], [10.0, 0.0], [0.0, 5.0], [0.0, 5.0]]
        piled = [[5.0, 0.0], [5.0, 0.0], [5.0, 0.0], [5.0, 10.0]]
        ids = ["A", "B", "C", "D"]
        instruments = ["X", "Y"]

        a = analyse_portfolio_overlap(spread, ids, instruments)
        b = analyse_portfolio_overlap(piled, ids, instruments)

        assert a.system_crowding.total_gross_exposure == pytest.approx(30.0)
        assert b.system_crowding.total_gross_exposure == pytest.approx(30.0)
        # raw: spread 0.5 -> normalized 1/3; piled 0.75 -> normalized 2/3.
        assert a.system_crowding.normalized == pytest.approx(1.0 / 3.0, rel=1e-12)
        assert b.system_crowding.normalized == pytest.approx(2.0 / 3.0, rel=1e-12)
        assert b.system_crowding.normalized > a.system_crowding.normalized

    def test_perfect_equality_across_all_names_is_the_maximum(self):
        positions = [[1.0, 1.0], [1.0, 1.0], [1.0, 1.0]]
        result = analyse_portfolio_overlap(positions, ["A", "B", "C"], ["X", "Y"])
        assert result.system_crowding.normalized == pytest.approx(1.0, rel=1e-12)

    def test_one_holder_per_name_is_the_minimum(self):
        positions = [[1.0, 0.0], [0.0, 1.0]]
        result = analyse_portfolio_overlap(positions, ["A", "B"], ["X", "Y"])
        assert result.system_crowding.normalized == pytest.approx(0.0, rel=1e-12)


class TestCorrelatedUnwind:
    """The threshold is explicit input and the response is monotone in it."""

    def test_threshold_selects_the_concentrated_institutions(self):
        result = analyse_portfolio_overlap(
            THREE_BY_THREE, THREE_IDS, THREE_INSTRUMENTS
        )
        # Row gross: A = 1, B = 2, C = 2. X holdings 1, 1, 0.
        # Concentration in X: A = 1.0, B = 0.5, C = 0.
        at_half = result.unwind_exposure("X", 0.5)
        # 0.5 is inclusive: A and B qualify -> exposure 1 + 1 = 2 (all of X).
        assert at_half.exposure == pytest.approx(2.0)
        assert at_half.n_liquidating == 2
        assert at_half.liquidating_institutions == ("A", "B")
        assert at_half.fraction_of_instrument == pytest.approx(1.0)
        # System gross is 5, so 2/5 of the system unwinds.
        assert at_half.fraction_of_system == pytest.approx(0.4)

        at_three_quarters = result.unwind_exposure("X", 0.75)
        # Only A (1.0) clears 0.75.
        assert at_three_quarters.exposure == pytest.approx(1.0)
        assert at_three_quarters.n_liquidating == 1
        assert at_three_quarters.liquidating_institutions == ("A",)

    def test_exposure_is_non_increasing_in_the_threshold(self):
        result = analyse_portfolio_overlap(
            THREE_BY_THREE, THREE_IDS, THREE_INSTRUMENTS
        )
        exposures = [
            result.unwind_exposure("X", threshold).exposure
            for threshold in (0.0, 0.3, 0.5, 0.75, 1.0)
        ]
        assert exposures == sorted(exposures, reverse=True)
        assert exposures[0] == pytest.approx(2.0)
        assert exposures[-1] == pytest.approx(1.0)

    def test_a_name_with_no_holder_above_the_threshold_exposes_nothing(self):
        result = analyse_portfolio_overlap(
            THREE_BY_THREE, THREE_IDS, THREE_INSTRUMENTS
        )
        # Y is held only by B, at concentration 1/2 of B's book.
        assert result.unwind_exposure("Y", 0.5).exposure == pytest.approx(1.0)
        assert result.unwind_exposure("Y", 0.6).exposure == pytest.approx(0.0)
        assert result.unwind_exposure("Y", 0.6).n_liquidating == 0

    def test_threshold_zero_still_requires_a_position(self):
        result = analyse_portfolio_overlap(
            THREE_BY_THREE, THREE_IDS, THREE_INSTRUMENTS
        )
        # Non-holders must not be dragged in by threshold 0.
        assert result.unwind_exposure("Z", 0.0).liquidating_institutions == ("C",)
        assert result.unwind_exposure("Z", 0.0).exposure == pytest.approx(2.0)

    def test_module_function_agrees_with_the_result_method(self):
        standalone = correlated_unwind_exposure(
            THREE_BY_THREE,
            THREE_IDS,
            THREE_INSTRUMENTS,
            instrument="X",
            concentration_threshold=0.5,
        )
        result = analyse_portfolio_overlap(
            THREE_BY_THREE, THREE_IDS, THREE_INSTRUMENTS
        )
        assert standalone == result.unwind_exposure("X", 0.5)
        assert standalone.exposure == pytest.approx(2.0)

    def test_threshold_can_be_precomputed_for_every_instrument(self):
        result = analyse_portfolio_overlap(
            THREE_BY_THREE,
            THREE_IDS,
            THREE_INSTRUMENTS,
            concentration_threshold=0.5,
        )
        assert set(result.unwind_exposures) == {"X", "Y", "Z"}
        assert result.unwind_exposures["X"].exposure == pytest.approx(2.0)

    def test_no_threshold_means_no_unwind_exposures(self):
        result = analyse_portfolio_overlap(
            THREE_BY_THREE, THREE_IDS, THREE_INSTRUMENTS
        )
        assert result.unwind_exposures == {}

    def test_a_short_holder_still_counts_as_unwinding_gross(self):
        positions = [[5.0], [-5.0]]
        result = analyse_portfolio_overlap(positions, ["A", "B"], ["X"])
        exposure = result.unwind_exposure("X", 0.5)
        # Both books are fully concentrated, so both are exposed; gross 10.
        assert exposure.exposure == pytest.approx(10.0)
        assert exposure.long_exposure == pytest.approx(5.0)
        assert exposure.short_exposure == pytest.approx(5.0)


class TestMissingDataPolicy:
    def test_fail_closed_is_the_default_and_raises_on_nan(self):
        positions = [[np.nan, 1.0], [1.0, 1.0]]
        with pytest.raises(PortfolioOverlapDataError) as excinfo:
            analyse_portfolio_overlap(positions, ["A", "B"], ["X", "Y"])
        assert excinfo.value.code == "PORTFOLIO_OVERLAP_DATA_INVALID"
        assert excinfo.value.context["missing_policy"] == "fail_closed"
        assert excinfo.value.context["n_missing"] == 1
        assert excinfo.value.context["institutions_with_missing"] == ["A"]

    def test_missing_is_never_silently_treated_as_a_zero_position(self):
        # A genuine zero is a fact and is accepted and retained.
        with_zero = analyse_portfolio_overlap(
            [[0.0, 1.0], [1.0, 1.0]], ["A", "B"], ["X", "Y"]
        )
        assert with_zero.positions[0, 0] == 0.0
        assert with_zero.instrument_crowding[0].n_holders == 1

        # The same shape with a missing entry is refused, not zero-filled: the
        # two inputs cannot silently collapse to the same analysis.
        with_missing = [[np.nan, 1.0], [1.0, 1.0]]
        with pytest.raises(PortfolioOverlapDataError):
            analyse_portfolio_overlap(with_missing, ["A", "B"], ["X", "Y"])

    def test_low_level_helpers_refuse_missing_values(self):
        with pytest.raises(ValueError, match="missing"):
            signed_cosine_overlap([[np.nan, 1.0]])
        with pytest.raises(ValueError, match="missing"):
            jaccard_name_overlap([[np.nan, 1.0]])
        with pytest.raises(ValueError, match="missing"):
            jaccard_directional_overlap([[np.nan, 1.0]])

    def test_exclude_institutions_drops_and_reports_the_row(self):
        positions = [[np.nan, 1.0], [1.0, 1.0], [1.0, 0.0]]
        result = analyse_portfolio_overlap(
            positions,
            ["A", "B", "C"],
            ["X", "Y"],
            missing_policy=MissingDataPolicy.EXCLUDE_INSTITUTIONS,
        )
        assert result.institution_ids == ["B", "C"]
        assert result.excluded_institutions == ["A"]
        assert result.excluded_instruments == []
        # C's genuine zero in Y survives the row exclusion.
        assert result.positions[1, 1] == 0.0
        # X is now held 1 each by B and C -> HHI = 0.5.
        by_name = {c.instrument: c for c in result.instrument_crowding}
        assert by_name["X"].hhi == pytest.approx(0.5, rel=1e-12)

    def test_exclude_instruments_drops_and_reports_the_column(self):
        positions = [[np.nan, 1.0], [1.0, 1.0]]
        result = analyse_portfolio_overlap(
            positions,
            ["A", "B"],
            ["X", "Y"],
            missing_policy=MissingDataPolicy.EXCLUDE_INSTRUMENTS,
        )
        assert result.instrument_ids == ["Y"]
        assert result.excluded_instruments == ["X"]
        assert result.excluded_institutions == []
        assert np.array_equal(result.positions, np.array([[1.0], [1.0]]))

    def test_exclude_both_drops_incomplete_rows_and_columns(self):
        # Row A is incomplete (NaN in Y) and column Y is incomplete (NaN in A);
        # each mask is judged on the original matrix, so both are dropped.
        positions = [[1.0, np.nan], [1.0, 2.0]]
        result = analyse_portfolio_overlap(
            positions,
            ["A", "B"],
            ["X", "Y"],
            missing_policy=MissingDataPolicy.EXCLUDE_BOTH,
        )
        assert result.institution_ids == ["B"]
        assert result.instrument_ids == ["X"]
        assert result.excluded_institutions == ["A"]
        assert result.excluded_instruments == ["Y"]

    def test_exclude_both_is_the_union_of_the_two_axes(self):
        positions = [
            [np.nan, 1.0, 2.0],
            [1.0, 1.0, 1.0],
            [1.0, 1.0, np.nan],
        ]
        result = analyse_portfolio_overlap(
            positions,
            ["A", "B", "C"],
            ["X", "Y", "Z"],
            missing_policy=MissingDataPolicy.EXCLUDE_BOTH,
        )
        # Rows A and C carry NaNs; columns X and Z carry NaNs.
        assert result.institution_ids == ["B"]
        assert result.instrument_ids == ["Y"]
        assert result.excluded_institutions == ["A", "C"]
        assert result.excluded_instruments == ["X", "Z"]

    def test_result_records_the_policy_it_was_computed_under(self):
        default = analyse_portfolio_overlap(
            THREE_BY_THREE, THREE_IDS, THREE_INSTRUMENTS
        )
        assert default.missing_policy is MissingDataPolicy.FAIL_CLOSED
        explicit = analyse_portfolio_overlap(
            THREE_BY_THREE,
            THREE_IDS,
            THREE_INSTRUMENTS,
            missing_policy=MissingDataPolicy.EXCLUDE_BOTH,
        )
        assert explicit.missing_policy is MissingDataPolicy.EXCLUDE_BOTH

    def test_an_unknown_policy_is_rejected(self):
        with pytest.raises(ValueError, match="missing_policy"):
            analyse_portfolio_overlap(
                THREE_BY_THREE,
                THREE_IDS,
                THREE_INSTRUMENTS,
                missing_policy="guess",
            )


class TestFailClosedInputValidation:
    def test_empty_institution_set_raises(self):
        with pytest.raises(DataQualityError):
            analyse_portfolio_overlap(np.zeros((0, 3)), [], ["X", "Y", "Z"])

    def test_empty_instrument_set_raises(self):
        with pytest.raises(DataQualityError):
            analyse_portfolio_overlap(np.zeros((2, 0)), ["A", "B"], [])

    def test_infinite_positions_raise(self):
        with pytest.raises(ValueError, match="non-finite"):
            analyse_portfolio_overlap(
                [[np.inf, 1.0]], ["A"], ["X", "Y"]
            )

    def test_ragged_labels_raise(self):
        with pytest.raises(ValueError, match="instrument_ids"):
            analyse_portfolio_overlap([[1.0, 2.0]], ["A"], ["X"])
        with pytest.raises(ValueError, match="institution_ids"):
            analyse_portfolio_overlap([[1.0, 2.0]], ["A", "B"], ["X", "Y"])

    def test_duplicate_labels_raise(self):
        with pytest.raises(ValueError, match="duplicate"):
            analyse_portfolio_overlap([[1.0, 2.0]], ["A"], ["X", "X"])
        with pytest.raises(ValueError, match="duplicate"):
            analyse_portfolio_overlap(
                [[1.0, 2.0], [3.0, 4.0]], ["A", "A"], ["X", "Y"]
            )

    def test_non_2d_positions_raise(self):
        with pytest.raises(ValueError, match="2-D"):
            analyse_portfolio_overlap([1.0, 2.0], ["A"], ["X"])

    def test_ragged_positions_raise(self):
        with pytest.raises(ValueError):
            analyse_portfolio_overlap([[1.0, 2.0], [3.0]], ["A", "B"], ["X", "Y"])

    def test_invalid_threshold_raises(self):
        result = analyse_portfolio_overlap(
            THREE_BY_THREE, THREE_IDS, THREE_INSTRUMENTS
        )
        with pytest.raises(ValueError, match="concentration_threshold"):
            result.unwind_exposure("X", 1.5)
        with pytest.raises(ValueError, match="concentration_threshold"):
            result.unwind_exposure("X", -0.1)
        with pytest.raises(ValueError, match="concentration_threshold"):
            result.unwind_exposure("X", float("nan"))
        with pytest.raises(ValueError, match="concentration_threshold"):
            analyse_portfolio_overlap(
                THREE_BY_THREE,
                THREE_IDS,
                THREE_INSTRUMENTS,
                concentration_threshold=1.01,
            )

    def test_unknown_instrument_raises(self):
        result = analyse_portfolio_overlap(
            THREE_BY_THREE, THREE_IDS, THREE_INSTRUMENTS
        )
        with pytest.raises(ValueError, match="unknown instrument"):
            result.unwind_exposure("W", 0.5)


class TestResultRecord:
    def test_names_are_carried_through(self):
        result = analyse_portfolio_overlap(
            THREE_BY_THREE, THREE_IDS, THREE_INSTRUMENTS
        )
        assert result.institution_ids == ["A", "B", "C"]
        assert result.instrument_ids == ["X", "Y", "Z"]
        assert [c.instrument for c in result.instrument_crowding] == [
            "X",
            "Y",
            "Z",
        ]

    def test_to_dict_is_json_safe_and_name_keyed(self):
        result = analyse_portfolio_overlap(
            THREE_BY_THREE,
            THREE_IDS,
            THREE_INSTRUMENTS,
            concentration_threshold=0.5,
        )
        payload = result.to_dict()
        json.dumps(payload, allow_nan=False)
        assert payload["missing_policy"] == "fail_closed"
        assert payload["institutions"] == ["A", "B", "C"]
        assert payload["instruments"] == ["X", "Y", "Z"]
        assert payload["cosine_overlap"]["A"]["B"] == pytest.approx(
            1.0 / math.sqrt(2.0), rel=1e-12
        )
        assert payload["positions"]["C"]["Z"] == pytest.approx(2.0)
        assert payload["system_crowding"]["normalized"] == pytest.approx(0.2)
        assert payload["unwind_exposures"]["X"]["exposure"] == pytest.approx(2.0)

    def test_repeated_identical_calls_are_exactly_equal(self):
        kwargs = dict(concentration_threshold=0.5)
        first = analyse_portfolio_overlap(
            THREE_BY_THREE, THREE_IDS, THREE_INSTRUMENTS, **kwargs
        )
        second = analyse_portfolio_overlap(
            THREE_BY_THREE, THREE_IDS, THREE_INSTRUMENTS, **kwargs
        )
        assert first.to_dict() == second.to_dict()
        assert np.array_equal(first.positions, second.positions)
        assert np.array_equal(first.cosine_overlap, second.cosine_overlap)
        assert np.array_equal(
            first.jaccard_directional_overlap,
            second.jaccard_directional_overlap,
        )


class TestPublicHelpers:
    def test_helper_matrices_match_the_result(self):
        result = analyse_portfolio_overlap(
            THREE_BY_THREE, THREE_IDS, THREE_INSTRUMENTS
        )
        assert np.allclose(
            signed_cosine_overlap(THREE_BY_THREE), result.cosine_overlap
        )
        assert np.allclose(
            jaccard_name_overlap(THREE_BY_THREE), result.jaccard_name_overlap
        )
        assert np.allclose(
            jaccard_directional_overlap(THREE_BY_THREE),
            result.jaccard_directional_overlap,
        )

    def test_system_score_helper_agrees_with_the_result(self):
        crowding = instrument_crowding(THREE_BY_THREE, THREE_INSTRUMENTS)
        score = system_crowding_score(crowding, 3)
        result = analyse_portfolio_overlap(
            THREE_BY_THREE, THREE_IDS, THREE_INSTRUMENTS
        )
        assert isinstance(score, CrowdingScore)
        assert score == result.system_crowding

    def test_default_instrument_labels_are_positional(self):
        crowding = instrument_crowding([[1.0, 2.0]])
        assert [c.instrument for c in crowding] == [
            "instrument_0",
            "instrument_1",
        ]

    def test_system_score_rejects_an_empty_institution_count(self):
        with pytest.raises(ValueError, match="n_institutions"):
            system_crowding_score([], 0)

    def test_dataclasses_are_exposed(self):
        assert InstrumentCrowding.__dataclass_fields__
        assert CorrelatedUnwindExposure.__dataclass_fields__
        assert CrowdingScore.__dataclass_fields__
