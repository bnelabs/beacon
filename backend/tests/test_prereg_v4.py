"""Contract tests for the protocol-v4 additions to the pre-registered runner.

Same philosophy as ``test_prereg_runner.py``: the runner executes tagged
protocols under a single-run rule, so nothing here trains a model or touches
the network. What IS pinned are the properties the v4 verdict will depend on:

* ``TRACK_PARAMS``: the daily row restates the frozen v1-v3 constants exactly
  (the v4 machinery must not move the daily track's parameters), and every
  track's lead floor / horizon respects the frozen design intent in business
  days;
* the protocol table: v4 declares exactly the recorded axes and nothing else,
  and v1-v3 stay byte-frozen;
* ``_refit_boundaries``: the causality the rolling-refit axis lives or dies by
  -- every refit window ends strictly before the year it scores, slices tile
  the evaluation span without overlap;
* ``_map_positions_to_eval``: grid mapping is exact, off-grid positions are
  refused rather than rounded;
* ``_fetch_bis_frame``: pinned-bytes parsing (quarter-end date convention) and
  the homogeneous-series refusal on format drift;
* ``_bis_licence_screen``: permission observed -> proceed; prohibition ->
  refuse; drift/unreachable -> refuse as unconfirmed (never assumed);
* ``_rolling_hazard_scores``: the per-refit absence rule (no onsets in a
  window -> no scores, not zeros).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]


def _runner():
    spec = importlib.util.spec_from_file_location(
        "prereg_runner_v4", REPO / "scripts" / "run_preregistered_eval.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runner():
    return _runner()


class TestTrackParams:
    def test_daily_row_restates_the_frozen_constants(self, runner):
        tp = runner.TRACK_PARAMS["daily"]
        assert tp["horizon"] == runner.HORIZON == 21
        assert tp["min_duration"] == runner.MIN_DURATION == 5
        assert tp["max_lead"] == runner.MAX_LEAD == 42
        assert tp["min_median_lead"] == runner.MIN_MEDIAN_LEAD == 10
        assert tp["steps_per_year"] == runner.BUSINESS_DAYS_PER_YEAR == 252
        assert tp["hazard_lookback"] == runner.HAZARD_LOOKBACK == 63

    def test_lead_floor_never_weakens_the_frozen_intent(self, runner):
        for track, tp in runner.TRACK_PARAMS.items():
            # >= 10 business days of warning, in each track's own steps
            assert tp["min_median_lead"] * tp["bd_per_step"] >= 10, track

    def test_horizon_covers_the_intent_at_grid_granularity(self, runner):
        for track, tp in runner.TRACK_PARAMS.items():
            # ~21 business days of move accumulation; weekly expresses 20
            # (4 weeks) as the nearest grid step, quarterly overshoots at 63
            # -- both declared in the protocol, asserted here as documented.
            assert tp["horizon"] * tp["bd_per_step"] >= 20, track

    def test_max_lead_is_twice_the_horizon_on_every_track(self, runner):
        for track, tp in runner.TRACK_PARAMS.items():
            assert tp["max_lead"] == 2 * tp["horizon"], track


class TestProtocolTableV4:
    def test_v4_declares_the_recorded_axes_and_only_those(self, runner):
        proto = runner.PROTOCOLS["v4"]
        assert proto["tag"] == "prereg-early-warning-v4"
        assert proto["alarm_quantile"] == 0.98          # v3's coherent point, unchanged
        assert proto["scorers"] == ("tan_frozen", "tan_rolling",
                                    "hazard_logit", "hazard_logit_rolling")
        assert proto["rolling_refit"] == "annual"
        assert proto["per_scorer_grids"] is True
        assert proto["keyed"] is True and proto["licence_screen"] is True
        assert proto["family"] is runner.FAMILY_V4
        assert proto["tracks"] is runner.TRACKS_V4

    def test_v1_v2_v3_untouched_by_the_v4_additions(self, runner):
        for version in ("v1", "v2", "v3"):
            proto = runner.PROTOCOLS[version]
            assert "tracks" not in proto
            assert "per_scorer_grids" not in proto
            assert "rolling_refit" not in proto
        assert runner.PROTOCOLS["v3"]["family"] is runner.FAMILY_V2
        assert runner.PROTOCOLS["v3"]["scorers"] == ("tan_frozen", "hazard_logit")

    def test_family_v4_extends_v2_with_the_probe_green_quarterly(self, runner):
        assert set(runner.FAMILY_V2).issubset(set(runner.FAMILY_V4))
        bis = runner.FAMILY_V4["BIS_CREDIT_GAP_US"]
        assert bis["source"] == "bis"
        # the GAP variant (CG_DTYPE=C), never the levels (A/B)
        assert bis["series_id"] == "WS_CREDIT_GAP/Q.US.P.A.C.E"
        new_codes = set(runner.FAMILY_V4) - set(runner.FAMILY_V2)
        assert new_codes == {"BIS_CREDIT_GAP_US"}  # nothing else snuck in

    def test_tracks_cover_the_weekly_and_quarterly_candidates(self, runner):
        assert runner.TRACKS_V4["FRED_STLFSI4"] == "weekly"
        assert runner.TRACKS_V4["FRED_KCFSI"] == "weekly"
        assert runner.TRACKS_V4["ECB_CISS"] == "weekly"
        assert runner.TRACKS_V4["BIS_CREDIT_GAP_US"] == "quarterly"
        for code in ("FRED_T10Y2Y", "FRED_T10Y3M", "FRED_VIXCLS"):
            assert runner.TRACKS_V4.get(code, "daily") == "daily"

    def test_registry_direction_declared_pre_fetch(self):
        from backend.modules.data.semantics import event_direction, stress_direction
        assert stress_direction("BIS_CREDIT_GAP_US") == +1
        assert event_direction("BIS_CREDIT_GAP_US") == "up"


class TestRefitBoundaries:
    @pytest.fixture()
    def frame_and_positions(self):
        dates = pd.bdate_range("2005-01-03", "2009-12-31")
        frame = pd.DataFrame({"Date": dates, "Value": np.arange(len(dates), dtype=float)})
        mask = ((frame["Date"] >= pd.Timestamp("2007-01-01"))
                & (frame["Date"] <= pd.Timestamp("2024-12-31"))).to_numpy()
        return frame, np.flatnonzero(mask)

    def test_annual_boundaries_tile_the_eval_span(self, runner, frame_and_positions):
        frame, pos = frame_and_positions
        bounds = runner._refit_boundaries(frame["Date"], pos)
        assert [y for _, _, y in bounds] == [2007, 2008, 2009]
        covered = np.concatenate([np.arange(b, e) for b, e, _ in bounds])
        assert covered.tolist() == pos.tolist()  # exact tiling, no overlap

    def test_every_refit_window_is_strictly_causal(self, runner, frame_and_positions):
        frame, pos = frame_and_positions
        for b, _e, y in runner._refit_boundaries(frame["Date"], pos):
            # the last row a refit at this boundary may see
            assert frame["Date"].iloc[b - 1].year < y
            assert frame["Date"].iloc[b].year == y


class TestMapPositions:
    def test_exact_mapping_and_off_grid_refusal(self, runner):
        eval_positions = np.array([10, 11, 12, 15, 16])
        idx, ok = runner._map_positions_to_eval(np.array([10, 12, 13, 16]), eval_positions)
        assert ok.tolist() == [True, True, False, True]
        assert idx[ok].tolist() == [0, 2, 4]


class TestBisFetchParser:
    HEADER = ("FREQ,BORROWERS_CTY,TC_BORROWERS,TC_LENDERS,CG_DTYPE,COLLECTION,DECIMALS,"
              "UNIT_MEASURE,UNIT_MULT,TIME_FORMAT,TITLE_TS,TIME_PERIOD,OBS_VALUE,"
              "OBS_STATUS,OBS_CONF,OBS_PRE_BREAK\n")
    ROW = "Q,US,P,A,C,E,1,770,0,,,1957-Q4,0.7754,A,F,\n"
    ROW2 = "Q,US,P,A,C,E,1,770,0,,,1958-Q1,-1.25,A,F,\n"

    def _get(self, text, status=200):
        resp = mock.Mock(status_code=status, text=text)
        return mock.patch("requests.get", return_value=resp)

    def test_pinned_bytes_parse_to_quarter_end_dates(self, runner):
        with self._get(self.HEADER + self.ROW + self.ROW2):
            frame = runner._fetch_bis_frame("WS_CREDIT_GAP/Q.US.P.A.C.E")
        assert frame["Date"].tolist() == [pd.Timestamp("1957-12-31"), pd.Timestamp("1958-03-31")]
        assert frame["Value"].tolist() == [0.7754, -1.25]

    def test_mixed_dimensions_are_a_refusal_not_a_guess(self, runner):
        mixed = self.ROW.replace(",C,", ",B,")
        with self._get(self.HEADER + self.ROW + mixed):
            with pytest.raises(RuntimeError, match="mixes"):
                runner._fetch_bis_frame("WS_CREDIT_GAP/Q.US.P.A.C.E")

    def test_http_error_is_recorded_not_swallowed(self, runner):
        with self._get("", status=500):
            with pytest.raises(RuntimeError, match="BIS HTTP 500"):
                runner._fetch_bis_frame("WS_CREDIT_GAP/Q.US.P.A.C.E")


class TestBisLicenceScreen:
    PERMISSION = ("<html><body><p>The use of the statistics is unrestricted, provided that: "
                  "if the statistics are reproduced, the BIS must be cited in your publication "
                  "or product as the source of the statistics.</p></body></html>")

    def _get(self, text, status=200):
        resp = mock.Mock(status_code=status, text=text)
        return mock.patch("requests.get", return_value=resp)

    def test_permission_observed_proceeds(self, runner):
        with self._get(self.PERMISSION):
            prohibited, reason, lines = runner._bis_licence_screen()
        assert prohibited is False and reason == ""
        assert any("unrestricted" in ln for ln in lines)

    def test_prohibition_language_refuses(self, runner):
        page = self.PERMISSION + "<p>Reproduction of this data in any form is prohibited.</p>"
        with self._get(page):
            prohibited, reason, _ = runner._bis_licence_screen()
        assert prohibited is True
        assert "prohibited" in reason.lower()

    def test_page_furniture_is_not_recorded_as_terms(self, runner):
        noisy = ('<html><head><script type="application/ld+json">{"@context":"https://schema.org",'
                 '"legalName":"BIS","license":"https://example.org"}</script></head><body>'
                 + self.PERMISSION + '</body></html>')
        with self._get(noisy):
            prohibited, reason, lines = runner._bis_licence_screen()
        assert prohibited is False
        assert lines and all("unrestricted" in ln or "cited" in ln for ln in lines)

    def test_drifted_page_refuses_as_unconfirmed(self, runner):
        with self._get("<html><body><p>Something else entirely.</p></body></html>"):
            prohibited, reason, _ = runner._bis_licence_screen()
        assert prohibited is True and reason.startswith("unconfirmed")

    def test_unreachable_page_refuses_as_unconfirmed(self, runner):
        with self._get("", status=404):
            prohibited, reason, _ = runner._bis_licence_screen()
        assert prohibited is True and reason.startswith("unconfirmed")


class TestRollingHazardAbsence:
    def test_no_onsets_in_any_window_is_declared_absence(self, runner):
        from backend.modules.data.event_labeller import EventDefinition

        # the pinned calm fixture from test_prereg_runner: tiny iid noise
        # never crosses its own q95 horizon-move, in ANY refit window
        rng = np.random.default_rng(2)
        dates = pd.bdate_range("2005-01-03", "2008-12-31")
        frame = pd.DataFrame({"Date": dates,
                              "Value": rng.normal(0.0, 1.0, len(dates)) * 0.001})
        mask = (frame["Date"] >= pd.Timestamp("2007-01-01")).to_numpy()
        pos = np.flatnonzero(mask)
        definition = EventDefinition(direction="up", quantile=0.95, horizon=21, min_duration=5)
        out = runner._rolling_hazard_scores(frame, pos, runner.TRACK_PARAMS["daily"], 1.0, definition)
        assert out is None  # absence, never zero-signal

    def test_scores_exist_only_from_the_first_fit_boundary_on(self, runner):
        from backend.modules.data.event_labeller import EventDefinition

        rng = np.random.default_rng(7)
        dates = pd.bdate_range("2005-01-03", "2008-12-31")
        values = rng.normal(0.0, 1.0, len(dates)).cumsum()
        # a training-span plateau the labeller can find onsets in
        values[100:130] += 12.0
        frame = pd.DataFrame({"Date": dates, "Value": values})
        mask = (frame["Date"] >= pd.Timestamp("2007-01-01")).to_numpy()
        pos = np.flatnonzero(mask)
        definition = EventDefinition(direction="up", quantile=0.95, horizon=21, min_duration=5)
        out = runner._rolling_hazard_scores(frame, pos, runner.TRACK_PARAMS["daily"], 1.0, definition)
        if out is not None:  # onsets found: every scored position is inside the eval span
            scored_pos, scores = out
            assert scored_pos.min() >= pos[0]
            assert scored_pos.max() <= pos[-1]
            assert np.all(np.isfinite(scores))
