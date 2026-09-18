"""Contract tests for the protocol-v5 additions to the pre-registered runner.

Same philosophy as ``test_prereg_v4.py``: nothing here trains a model or
touches the network. What IS pinned are the properties the v5 verdict will
depend on:

* ``TRACK_PARAMS["monthly"]`` — the v5 track translates the frozen design
  intent (~21-bd horizon, >=10-bd lead floor, ~quarter hazard lookback) at
  the monthly grid's coarsest granularity, and its gap band matches the
  runner's measured-frequency classifier;
* the daily/weekly/quarterly rows are UNCHANGED from v4 (v5 adds a track,
  it does not move one);
* the protocol table: v5 declares the wider family, the same four scorers,
  the same alarm point, the same shared constants — and v1-v4 stay frozen;
* ``FAMILY_V5`` / ``TRACKS_V5``: exactly the probe-GREEN additions entered,
  KCFSI's weekly->monthly reassignment is the only track change, and every
  entering code has a stress direction declared in the registry (an
  undeclared direction is a refusal, not a default).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _runner():
    spec = importlib.util.spec_from_file_location(
        "prereg_runner_v5", REPO / "scripts" / "run_preregistered_eval.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runner():
    return _runner()


class TestMonthlyTrack:
    def test_monthly_row_translates_the_frozen_intent(self, runner):
        tp = runner.TRACK_PARAMS["monthly"]
        daily = runner.TRACK_PARAMS["daily"]
        # horizon: 1 step x 21 bd = the daily 21-bd intent exactly
        assert tp["horizon"] == 1
        assert tp["horizon"] * tp["bd_per_step"] == daily["horizon"] * daily["bd_per_step"] == 21
        # max_lead: 2 steps x 21 bd = the daily 42-bd ceiling
        assert tp["max_lead"] == 2
        assert tp["max_lead"] * tp["bd_per_step"] == daily["max_lead"] * daily["bd_per_step"] == 42
        # lead floor: 1 step ~ 21 bd >= the 10-bd intent (STRICTER — declared)
        assert tp["min_median_lead"] == 1
        assert tp["min_median_lead"] * tp["bd_per_step"] >= daily["min_median_lead"]
        # hazard lookback: 3 steps ~ one quarter, matching weekly's 13 weeks
        assert tp["hazard_lookback"] == 3
        assert tp["hazard_lookback"] * tp["bd_per_step"] == 63 == daily["hazard_lookback"]
        # coarsest expressible persistence
        assert tp["min_duration"] == 1
        assert tp["steps_per_year"] == 12

    def test_monthly_gap_band_matches_the_frequency_classifier(self, runner):
        tp = runner.TRACK_PARAMS["monthly"]
        weekly = runner.TRACK_PARAMS["weekly"]
        # classifier: monthly iff 8 < median_gap <= 35 (runner line: gap<=35)
        assert tp["gap_min"] == weekly["gap_max"] == 8.0
        assert tp["gap_max"] == 35.0
        # a ~31-day cadence (KCFSI/FEDFUNDS/UMCSENT) lands inside the band
        assert tp["gap_min"] <= 31.0 <= tp["gap_max"]

    def test_v4_tracks_unchanged_by_v5(self, runner):
        tp = runner.TRACK_PARAMS
        # daily re-states the frozen v1-v3 constants (as pinned since v4)
        assert tp["daily"] == {
            "horizon": 21, "min_duration": 5, "max_lead": 42, "min_median_lead": 10,
            "steps_per_year": 252, "hazard_lookback": 63, "bd_per_step": 1.0,
            "gap_min": 0.0, "gap_max": 1.5,
        }
        assert tp["weekly"] == {
            "horizon": 4, "min_duration": 1, "max_lead": 8, "min_median_lead": 2,
            "steps_per_year": 52, "hazard_lookback": 13, "bd_per_step": 5.0,
            "gap_min": 1.5, "gap_max": 8.0,
        }
        assert tp["quarterly"] == {
            "horizon": 1, "min_duration": 1, "max_lead": 2, "min_median_lead": 1,
            "steps_per_year": 4, "hazard_lookback": 1, "bd_per_step": 63.0,
            "gap_min": 35.0, "gap_max": 125.0,
        }


class TestProtocolTableV5:
    def test_v5_declares_the_family_axis_and_only_that(self, runner):
        proto = runner.PROTOCOLS["v5"]
        assert proto["tag"] == "prereg-early-warning-v5"
        assert proto["alarm_quantile"] == 0.98          # v3's coherent point, unchanged
        assert proto["scorers"] == ("tan_frozen", "tan_rolling",
                                    "hazard_logit", "hazard_logit_rolling")
        assert proto["rolling_refit"] == "annual"
        assert proto["per_scorer_grids"] is True
        assert proto["keyed"] is True and proto["licence_screen"] is True
        assert proto["family"] is runner.FAMILY_V5
        assert proto["tracks"] is runner.TRACKS_V5

    def test_v1_through_v4_untouched_by_the_v5_additions(self, runner):
        for version in ("v1", "v2", "v3"):
            proto = runner.PROTOCOLS[version]
            assert "tracks" not in proto
            assert "per_scorer_grids" not in proto
            assert "rolling_refit" not in proto
        v4 = runner.PROTOCOLS["v4"]
        assert v4["family"] is runner.FAMILY_V4
        assert v4["tracks"] is runner.TRACKS_V4
        assert v4["alarm_quantile"] == 0.98
        assert runner.PROTOCOLS["v3"]["family"] is runner.FAMILY_V2

    def test_shared_constants_stay_frozen(self, runner):
        assert runner.QUANTILE == 0.95
        assert runner.HORIZON == 21
        assert runner.MIN_DURATION == 5
        assert runner.MIN_MEDIAN_LEAD == 10
        assert runner.MAX_LEAD == 42
        assert runner.MAX_FALSE_ALARMS_PER_QUIET_YEAR == 4.0
        assert runner.PERM_SEED == 20260917
        assert runner.PERM_ITERATIONS == 1000
        assert runner.HOLM_ALPHA == 0.05
        assert runner.MIN_TESTABLE_FAMILY == 3
        assert runner.MODEL_CONFIG["sequence_length"] == 30
        assert runner.MODEL_CONFIG["d_model"] == 16


class TestFamilyV5:
    def test_exactly_the_probe_green_additions_entered(self, runner):
        assert set(runner.FAMILY_V4).issubset(set(runner.FAMILY_V5))
        new_codes = set(runner.FAMILY_V5) - set(runner.FAMILY_V4)
        assert new_codes == {
            "FRED_DCOILWTICO", "FRED_MORTGAGE30US", "FRED_NFCI",
            "FRED_FEDFUNDS", "FRED_UMCSENT",
        }  # nothing else snuck in; probe-RED candidates are NOT family members

    def test_probe_red_candidates_are_not_in_the_family(self, runner):
        for red in ("FRED_DTWEXBGS", "NYFED_RECESSION_PROB", "NYFED_RP_PROB",
                    "BIS_DEBT_SERVICE_RATIO", "BIS_DSR_US"):
            assert red not in runner.FAMILY_V5

    def test_tracks_v5_reassigns_only_kcfsi_and_declares_the_new_codes(self, runner):
        t4, t5 = runner.TRACKS_V4, runner.TRACKS_V5
        assert t5["FRED_KCFSI"] == "monthly"           # the declared reassignment
        for code in t4:
            if code != "FRED_KCFSI":
                assert t5[code] == t4[code]            # every other v4 track stands
        assert t5["FRED_MORTGAGE30US"] == "weekly"
        assert t5["FRED_NFCI"] == "weekly"
        assert t5["FRED_FEDFUNDS"] == "monthly"
        assert t5["FRED_UMCSENT"] == "monthly"
        # the new daily code needs no track entry (absence = daily), but if
        # present it must say daily
        assert t5.get("FRED_DCOILWTICO", "daily") == "daily"

    def test_every_entering_code_has_a_declared_direction(self, runner):
        from backend.modules.data.semantics import stress_direction

        for code, spec in runner.FAMILY_V5.items():
            if "excluded" in spec:
                continue
            direction = stress_direction(code)
            assert direction in (+1, -1), f"{code} enters the family with no declared direction"

    def test_new_directions_match_the_declared_rationale(self, runner):
        from backend.modules.data.semantics import stress_direction

        assert stress_direction("FRED_DCOILWTICO") == +1    # oil spike = stress
        assert stress_direction("FRED_MORTGAGE30US") == +1  # rate shock = stress
        assert stress_direction("FRED_NFCI") == +1          # tighter by construction
        assert stress_direction("FRED_FEDFUNDS") == +1      # tightening channel
        assert stress_direction("FRED_UMCSENT") == -1       # falling sentiment = stress
        # and the carried ones did not move
        assert stress_direction("FRED_STLFSI4") == +1
        assert stress_direction("FRED_KCFSI") == +1
        assert stress_direction("FRED_T10Y2Y") == -1
        assert stress_direction("FRED_T10Y3M") == -1
        assert stress_direction("FRED_VIXCLS") == +1
        assert stress_direction("BIS_CREDIT_GAP_US") == +1
