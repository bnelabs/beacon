"""Tests for the SEC Form N-MFP connector.

The suite is built around the connector's two hard promises. First, the parser
must read the *real* EDGAR schema: every fixture below is a trimmed verbatim
excerpt of a filing actually downloaded from EDGAR on 2026-09-11, so a change to
a tag name cannot pass. Second, the two clocks must stay separate: the filing
date is the vintage and the reporting month is the period, and the tests pin
both, including one that makes reading the wall clock an error.

Everything is offline. ``fetch`` is exercised through a fake HTTP client that
serves recorded bytes, so the orchestration (submissions index -> archive
document) is tested without touching SEC.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from backend.exceptions import EmptyDatasetError, SchemaValidationError
from backend.modules.data.connectors.base import (
    FetchRequest,
    validate_observation_frame,
)
from backend.modules.data.connectors.sec_n_mfp import (
    SERIES_DAILY_LIQUID_ASSETS,
    SERIES_DAILY_LIQUID_ASSETS_PCT,
    SERIES_TOTAL_NET_ASSETS,
    SERIES_WAL_DAYS,
    SERIES_WAM_DAYS,
    SERIES_WEEKLY_LIQUID_ASSETS,
    SERIES_WEEKLY_LIQUID_ASSETS_PCT,
    SecNMfpConnector,
)
from backend.modules.data.pit import OBSERVATION_COLUMNS, PITStore

# --------------------------------------------------------------------------
# Real fixtures.
#
# N-MFP2: AB Fixed Income Shares Inc (CIK 0000862021), series S000011990, period
# ending 2023-12-31, filed 2024-01-08, accession 0001145549-24-001106. Trimmed
# to the header, general info, series-level block and signature; the eight
# <classLevelInfo> blocks and 102 <scheduleOfPortfolioSecuritiesInfo> rows were
# dropped because this connector reads none of them. Every value is verbatim.
# December 2023 has five Fridays, so the "(if applicable)" fridayDay5 slot is
# real here: 14190110031.93 matches percentageDailyLiquidAssets fridayDay5
# (0.6410) against total assets, which is how the slot order was confirmed.
# --------------------------------------------------------------------------
N_MFP2_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xsi:schemaLocation="http://www.sec.gov/edgar/nmfp2 eis_NMFP2_Filer.xsd" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:ns1="http://www.sec.gov/edgar/common" xmlns:ns2="http://www.sec.gov/edgar/statecodes" xmlns:ns3="http://www.sec.gov/edgar/nmfp2common" xmlns="http://www.sec.gov/edgar/nmfp2">
  <headerData>
    <submissionType>N-MFP2</submissionType>
    <filerInfo>
      <filer>
        <filerCredentials>
          <cik>0000862021</cik>
          <ccc>XXXXXXXX</ccc>
        </filerCredentials>
      </filer>
      <notifications/>
    </filerInfo>
  </headerData>
  <formData>
    <generalInfo>
      <reportDate>2023-12-31</reportDate>
      <cik>0000862021</cik>
      <seriesId>S000011990</seriesId>
      <totalShareClassesInSeries>8</totalShareClassesInSeries>
      <finalFilingFlag>N</finalFilingFlag>
    </generalInfo>
    <seriesLevelInfo>
      <moneyMarketFundCategory>Exempt Government</moneyMarketFundCategory>
      <moneyMarketFundCategory>Government/Agency</moneyMarketFundCategory>
      <averagePortfolioMaturity>31</averagePortfolioMaturity>
      <averageLifeMaturity>100</averageLifeMaturity>
      <totalValueDailyLiquidAssets>
        <ns3:fridayDay1>13249590750.68</ns3:fridayDay1>
        <ns3:fridayDay2>13033447300.49</ns3:fridayDay2>
        <ns3:fridayDay3>14504701176.69</ns3:fridayDay3>
        <ns3:fridayDay4>14419380176.72</ns3:fridayDay4>
        <ns3:fridayDay5>14190110031.93</ns3:fridayDay5>
      </totalValueDailyLiquidAssets>
      <totalValueWeeklyLiquidAssets>
        <ns3:fridayWeek1>13732338062.76</ns3:fridayWeek1>
        <ns3:fridayWeek2>13461764956.98</ns3:fridayWeek2>
        <ns3:fridayWeek3>14933128413.75</ns3:fridayWeek3>
        <ns3:fridayWeek4>15221188045.62</ns3:fridayWeek4>
        <ns3:fridayWeek5>15290249466.43</ns3:fridayWeek5>
      </totalValueWeeklyLiquidAssets>
      <percentageDailyLiquidAssets>
        <ns3:fridayDay1>0.6127</ns3:fridayDay1>
        <ns3:fridayDay2>0.6131</ns3:fridayDay2>
        <ns3:fridayDay3>0.6407</ns3:fridayDay3>
        <ns3:fridayDay4>0.6313</ns3:fridayDay4>
        <ns3:fridayDay5>0.6410</ns3:fridayDay5>
      </percentageDailyLiquidAssets>
      <percentageWeeklyLiquidAssets>
        <ns3:fridayWeek1>0.6350</ns3:fridayWeek1>
        <ns3:fridayWeek2>0.6333</ns3:fridayWeek2>
        <ns3:fridayWeek3>0.6596</ns3:fridayWeek3>
        <ns3:fridayWeek4>0.6665</ns3:fridayWeek4>
        <ns3:fridayWeek5>0.6907</ns3:fridayWeek5>
      </percentageWeeklyLiquidAssets>
      <cash>915403.22</cash>
      <totalValuePortfolioSecurities>22062486868.01</totalValuePortfolioSecurities>
      <amortizedCostPortfolioSecurities>22059924454.50</amortizedCostPortfolioSecurities>
      <totalValueOtherAssets>74550823.97</totalValueOtherAssets>
      <totalValueLiabilities>15043159.98</totalValueLiabilities>
      <netAssetOfSeries>22120347521.71</netAssetOfSeries>
      <numberOfSharesOutstanding>22122560839.2700</numberOfSharesOutstanding>
      <stablePricePerShare>1.0000</stablePricePerShare>
    </seriesLevelInfo>
    <signature>
      <registrant>AllianceBernstein Fixed Income Shares</registrant>
      <signatureDate>2024-01-08</signatureDate>
    </signature>
  </formData>
</edgarSubmission>
"""

# N-MFP3: same registrant and series, period ending 2026-08-31, filed 2026-09-08,
# accession 0001410368-26-090983. N-MFP3 replaced the positional Friday
# containers with a dated per-business-day <liquidAssetsDetails> panel; the three
# blocks below are verbatim, but their order was permuted so the test pins
# selection *by date* rather than by document position.
N_MFP3_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xsi:schemaLocation="http://www.sec.gov/edgar/nmfp3 eis_NMFP3_Filer.xsd" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:ns1="http://www.sec.gov/edgar/common" xmlns:ns2="http://www.sec.gov/edgar/statecodes" xmlns:ns3="http://www.sec.gov/edgar/nmfp3common" xmlns="http://www.sec.gov/edgar/nmfp3">
  <headerData>
    <submissionType>N-MFP3</submissionType>
    <filerInfo>
      <filer>
        <filerCredentials>
          <cik>0000862021</cik>
          <ccc>XXXXXXXX</ccc>
        </filerCredentials>
      </filer>
    </filerInfo>
  </headerData>
  <formData>
    <generalInfo>
      <reportDate>2026-08-31</reportDate>
      <cik>0000862021</cik>
      <seriesId>S000011990</seriesId>
      <totalShareClassesInSeries>7</totalShareClassesInSeries>
      <finalFilingFlag>N</finalFilingFlag>
    </generalInfo>
    <seriesLevelInfo>
      <averagePortfolioMaturity>45</averagePortfolioMaturity>
      <averageLifeMaturity>77</averageLifeMaturity>
      <liquidAssetsDetails>
        <totalValueDailyLiquidAssets>17271648618.52</totalValueDailyLiquidAssets>
        <totalValueWeeklyLiquidAssets>17870648266.93</totalValueWeeklyLiquidAssets>
        <percentageDailyLiquidAssets>0.7082</percentageDailyLiquidAssets>
        <percentageWeeklyLiquidAssets>0.7328</percentageWeeklyLiquidAssets>
        <totalLiquidAssetsNearPercentDate>2026-08-04</totalLiquidAssetsNearPercentDate>
      </liquidAssetsDetails>
      <liquidAssetsDetails>
        <totalValueDailyLiquidAssets>16323469051.26</totalValueDailyLiquidAssets>
        <totalValueWeeklyLiquidAssets>17472467430.21</totalValueWeeklyLiquidAssets>
        <percentageDailyLiquidAssets>0.6908</percentageDailyLiquidAssets>
        <percentageWeeklyLiquidAssets>0.7394</percentageWeeklyLiquidAssets>
        <totalLiquidAssetsNearPercentDate>2026-08-31</totalLiquidAssetsNearPercentDate>
      </liquidAssetsDetails>
      <liquidAssetsDetails>
        <totalValueDailyLiquidAssets>17324829487.46</totalValueDailyLiquidAssets>
        <totalValueWeeklyLiquidAssets>17923827159.36</totalValueWeeklyLiquidAssets>
        <percentageDailyLiquidAssets>0.7089</percentageDailyLiquidAssets>
        <percentageWeeklyLiquidAssets>0.7334</percentageWeeklyLiquidAssets>
        <totalLiquidAssetsNearPercentDate>2026-08-03</totalLiquidAssetsNearPercentDate>
      </liquidAssetsDetails>
      <netAssetOfSeries>23619721574.07</netAssetOfSeries>
    </seriesLevelInfo>
    <signature>
      <signatureDate>2026-09-08</signatureDate>
    </signature>
  </formData>
</edgarSubmission>
"""

# N-MFP1: AB Bond Fund Inc (CIK 0000003794), series S000040013, period ending
# 2016-08-31, filed 2016-09-08, accession 0001145549-16-017346. August 2016 has
# only four Fridays, and the weekly container carries a literal 0.00 filler in
# fridayWeek5 -- the case that makes "take the last child" wrong. N-MFP1 also
# names the *daily* children fridayWeekN rather than N-MFP2's fridayDayN.
N_MFP1_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xsi:schemaLocation="http://www.sec.gov/edgar/nmfp1 eis_NMFP1_Filer.xsd" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:ns1="http://www.sec.gov/edgar/common" xmlns:ns2="http://www.sec.gov/edgar/statecodes" xmlns:ns3="http://www.sec.gov/edgar/nmfp1common" xmlns="http://www.sec.gov/edgar/nmfp1">
  <headerData>
    <submissionType>N-MFP1</submissionType>
    <filerInfo>
      <filer>
        <filerCredentials>
          <cik>0000003794</cik>
          <ccc>XXXXXXXX</ccc>
        </filerCredentials>
      </filer>
    </filerInfo>
  </headerData>
  <formData>
    <generalInfo>
      <reportDate>2016-08-31</reportDate>
      <cik>0000003794</cik>
      <seriesId>S000040013</seriesId>
      <totalShareClassesInSeries>1</totalShareClassesInSeries>
    </generalInfo>
    <seriesLevelInfo>
      <moneyMarketFundCategory>Government/Agency</moneyMarketFundCategory>
      <averagePortfolioMaturity>32</averagePortfolioMaturity>
      <averageLifeMaturity>91</averageLifeMaturity>
      <totalValueDailyLiquidAssets>
        <ns3:fridayWeek1>115647462.01</ns3:fridayWeek1>
        <ns3:fridayWeek2>133134594.73</ns3:fridayWeek2>
        <ns3:fridayWeek3>127782395.09</ns3:fridayWeek3>
        <ns3:fridayWeek4>144209944.14</ns3:fridayWeek4>
      </totalValueDailyLiquidAssets>
      <totalValueWeeklyLiquidAssets>
        <ns3:fridayWeek1>193921854.47</ns3:fridayWeek1>
        <ns3:fridayWeek2>227885404.81</ns3:fridayWeek2>
        <ns3:fridayWeek3>250331109.92</ns3:fridayWeek3>
        <ns3:fridayWeek4>197695313.29</ns3:fridayWeek4>
        <ns3:fridayWeek5>0.00</ns3:fridayWeek5>
      </totalValueWeeklyLiquidAssets>
      <percentageDailyLiquidAssets>
        <ns3:fridayWeek1>0.2040</ns3:fridayWeek1>
        <ns3:fridayWeek2>0.2240</ns3:fridayWeek2>
        <ns3:fridayWeek3>0.2192</ns3:fridayWeek3>
        <ns3:fridayWeek4>0.2479</ns3:fridayWeek4>
      </percentageDailyLiquidAssets>
      <percentageWeeklyLiquidAssets>
        <ns3:fridayWeek1>0.3421</ns3:fridayWeek1>
        <ns3:fridayWeek2>0.3834</ns3:fridayWeek2>
        <ns3:fridayWeek3>0.4295</ns3:fridayWeek3>
        <ns3:fridayWeek4>0.3398</ns3:fridayWeek4>
        <ns3:fridayWeek5>0.0000</ns3:fridayWeek5>
      </percentageWeeklyLiquidAssets>
      <netAssetOfSeries>567886603.64</netAssetOfSeries>
    </seriesLevelInfo>
    <signature>
      <signatureDate>2016-09-08</signatureDate>
    </signature>
  </formData>
</edgarSubmission>
"""

# Original Form N-MFP: AB Bond Fund Inc (CIK 0000003794), series S000040013,
# period ending 2015-12-31, filed 2016-01-08, accession 0001145549-16-009699.
# This schema has no daily/weekly liquid-asset elements at all and no
# signatureDate, so only three series exist and observed_at must be supplied.
LEGACY_N_MFP_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nmfp" xmlns:com="http://www.sec.gov/edgar/common" xmlns:invest="http://www.sec.gov/edgar/invest" xmlns:part1="http://www.sec.gov/edgar/nmfpfund" xmlns:part2="http://www.sec.gov/edgar/nmfpsecurities" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.sec.gov/edgar/nmfp eis_NMFP_Submission.xsd">
  <submissionType>N-MFP</submissionType>
  <liveTestFlag>LIVE</liveTestFlag>
  <DocumentPeriodEndDate>2015-12-31</DocumentPeriodEndDate>
  <EntityCentralIndexKey>0000003794</EntityCentralIndexKey>
  <seriesId>S000040013</seriesId>
  <totalClassesInSeries>1</totalClassesInSeries>
  <seriesLevelInformation>
    <part1:dollarWeightedAveragePortfolioMaturity>42</part1:dollarWeightedAveragePortfolioMaturity>
    <part1:dollarWeightedAverageLifeMaturity>72</part1:dollarWeightedAverageLifeMaturity>
    <part1:OtherAssets>435638.38</part1:OtherAssets>
    <part1:Liabilities>188015.68</part1:Liabilities>
    <part1:AssetsNet>552342815.89</part1:AssetsNet>
  </seriesLevelInformation>
</edgarSubmission>
"""

# A well-formed N-MFP2 that carries no numeric series at all.
N_MFP2_BARE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nmfp2" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.sec.gov/edgar/nmfp2 eis_NMFP2_Filer.xsd">
  <headerData><submissionType>N-MFP2</submissionType></headerData>
  <formData>
    <generalInfo>
      <reportDate>2023-12-31</reportDate>
      <cik>0000862021</cik>
      <seriesId>S000011990</seriesId>
    </generalInfo>
    <seriesLevelInfo/>
    <signature><signatureDate>2024-01-08</signatureDate></signature>
  </formData>
</edgarSubmission>
"""

CIK = "0000862021"
INDEX_URL = "https://data.sec.gov/submissions/CIK0000862021.json"
DOCUMENT_URL = (
    "https://www.sec.gov/Archives/edgar/data/862021/000114554924001106/primary_doc.xml"
)


def _connector() -> SecNMfpConnector:
    return SecNMfpConnector()


def _values(frame: pd.DataFrame) -> dict:
    """``series_id -> value`` for a single-fund frame."""
    return dict(zip(frame["series_id"], frame["value"].astype(float)))


def _submissions(rows: list) -> bytes:
    """An EDGAR submissions index with the parallel arrays the parser reads."""
    keys = (
        "accessionNumber",
        "form",
        "filingDate",
        "reportDate",
        "primaryDocument",
    )
    recent = {key: [row[key] for row in rows] for key in keys}
    return json.dumps(
        {"cik": CIK, "name": "AB FIXED INCOME SHARES INC", "filings": {"recent": recent}}
    ).encode("utf-8")


class _FakeClient:
    """Serves recorded bytes and records every URL, so URLs are asserted too."""

    def __init__(self, responses: dict) -> None:
        self._responses = responses
        self.calls: list = []

    def get(self, url, *, params=None, accept=None, connector="connector"):
        self.calls.append(url)
        if url not in self._responses:
            raise AssertionError(f"unexpected URL fetched: {url}")
        return self._responses[url]


# --------------------------------------------------------------------------
# Parsing the real payloads.
# --------------------------------------------------------------------------


class TestRealNfp2Payload:
    def test_frame_carries_the_observation_contract(self):
        frame = _connector().parse(N_MFP2_XML, FetchRequest())

        assert list(frame.columns) == list(OBSERVATION_COLUMNS)
        assert len(frame) == 7

    def test_every_extracted_value_matches_the_filing(self):
        values = _values(_connector().parse(N_MFP2_XML, FetchRequest()))

        assert values == {
            SERIES_TOTAL_NET_ASSETS: 22120347521.71,
            SERIES_WAM_DAYS: 31.0,
            SERIES_WAL_DAYS: 100.0,
            SERIES_DAILY_LIQUID_ASSETS: 14190110031.93,
            SERIES_WEEKLY_LIQUID_ASSETS: 15290249466.43,
            SERIES_DAILY_LIQUID_ASSETS_PCT: 0.6410,
            SERIES_WEEKLY_LIQUID_ASSETS_PCT: 0.6907,
        }

    def test_entity_id_is_the_series_not_the_reader(self):
        frame = _connector().parse(N_MFP2_XML, FetchRequest())

        assert set(frame["entity_id"]) == {"S000011990"}

    def test_liquidity_uses_the_last_friday_of_a_five_friday_month(self):
        # December 2023 has five Fridays; the fifth slot is real, and its
        # percentage (0.6410) is the period-end ratio, not an average.
        frame = _connector().parse(N_MFP2_XML, FetchRequest())
        value = _values(frame)[SERIES_DAILY_LIQUID_ASSETS]

        assert value == 14190110031.93
        assert value != 13249590750.68  # fridayDay1
        assert value != sum(
            [13249590750.68, 13033447300.49, 14504701176.69, 14419380176.72]
        ) / 4

    def test_observed_at_defaults_to_the_signature_date(self):
        frame = _connector().parse(N_MFP2_XML, FetchRequest())

        assert set(frame["observed_at"]) == {pd.Timestamp("2024-01-08")}
        assert set(frame["valid_time"]) == {pd.Timestamp("2023-12-31")}

    def test_explicit_filing_date_wins_over_the_signature_date(self):
        frame = _connector().parse(
            N_MFP2_XML, FetchRequest(), observed_at="2024-01-09"
        )

        assert set(frame["observed_at"]) == {pd.Timestamp("2024-01-09")}


class TestRealNfp3Payload:
    def test_dated_panel_takes_the_freshest_block(self):
        frame = _connector().parse(N_MFP3_XML, FetchRequest())
        values = _values(frame)

        # The 2026-08-31 block, not the 2026-08-03 or 2026-08-04 block and not
        # the first block in document order.
        assert values[SERIES_DAILY_LIQUID_ASSETS] == 16323469051.26
        assert values[SERIES_WEEKLY_LIQUID_ASSETS] == 17472467430.21
        assert values[SERIES_DAILY_LIQUID_ASSETS_PCT] == 0.6908
        assert values[SERIES_WEEKLY_LIQUID_ASSETS_PCT] == 0.7394

    def test_series_level_values(self):
        values = _values(_connector().parse(N_MFP3_XML, FetchRequest()))

        assert values[SERIES_TOTAL_NET_ASSETS] == 23619721574.07
        assert values[SERIES_WAM_DAYS] == 45.0
        assert values[SERIES_WAL_DAYS] == 77.0
        assert set(_connector().parse(N_MFP3_XML, FetchRequest())["valid_time"]) == {
            pd.Timestamp("2026-08-31")
        }


class TestRealNfp1Payload:
    def test_four_friday_month_ignores_the_zero_filler(self):
        # August 2016 has four Fridays. fridayWeek5 is a literal 0.00 filler on
        # both liquidity containers; taking it would report a fund with zero
        # weekly liquidity.
        values = _values(_connector().parse(N_MFP1_XML, FetchRequest()))

        assert values[SERIES_DAILY_LIQUID_ASSETS] == 144209944.14
        assert values[SERIES_WEEKLY_LIQUID_ASSETS] == 197695313.29
        assert values[SERIES_DAILY_LIQUID_ASSETS_PCT] == 0.2479
        assert values[SERIES_WEEKLY_LIQUID_ASSETS_PCT] == 0.3398

    def test_daily_children_named_friday_week_are_still_read(self):
        # N-MFP1 reuses fridayWeekN inside the *daily* container.
        values = _values(_connector().parse(N_MFP1_XML, FetchRequest()))

        assert values[SERIES_DAILY_LIQUID_ASSETS] == 144209944.14
        assert values[SERIES_TOTAL_NET_ASSETS] == 567886603.64


class TestLegacyPayload:
    def test_only_the_three_available_series_are_emitted(self):
        frame = _connector().parse(
            LEGACY_N_MFP_XML, FetchRequest(), observed_at="2016-01-08"
        )
        values = _values(frame)

        assert set(values) == {
            SERIES_TOTAL_NET_ASSETS,
            SERIES_WAM_DAYS,
            SERIES_WAL_DAYS,
        }
        assert values[SERIES_TOTAL_NET_ASSETS] == 552342815.89
        assert values[SERIES_WAM_DAYS] == 42.0
        assert values[SERIES_WAL_DAYS] == 72.0
        assert set(frame["entity_id"]) == {"S000040013"}
        assert set(frame["valid_time"]) == {pd.Timestamp("2015-12-31")}

    def test_without_signature_date_the_filing_date_must_be_supplied(self):
        with pytest.raises(SchemaValidationError, match="publication date"):
            _connector().parse(LEGACY_N_MFP_XML, FetchRequest())


# --------------------------------------------------------------------------
# The two clocks.
# --------------------------------------------------------------------------


class TestClocks:
    def test_valid_time_is_the_reported_period_not_the_filing_date(self):
        frame = _connector().parse(N_MFP2_XML, FetchRequest())

        assert frame["valid_time"].iloc[0] == pd.Timestamp("2023-12-31")
        assert frame["observed_at"].iloc[0] == pd.Timestamp("2024-01-08")

    def test_a_filing_dated_before_its_period_is_rejected(self):
        with pytest.raises(SchemaValidationError, match="before the period"):
            _connector().parse(N_MFP2_XML, FetchRequest(), observed_at="2023-12-30")

    def test_observed_at_may_equal_valid_time(self):
        frame = _connector().parse(
            N_MFP2_XML, FetchRequest(), observed_at="2023-12-31"
        )

        assert frame["observed_at"].iloc[0] == frame["valid_time"].iloc[0]

    def test_module_never_reads_the_wall_clock(self, monkeypatch):
        def _forbidden(*args, **kwargs):
            raise AssertionError("connector read the wall clock")

        monkeypatch.setattr(pd.Timestamp, "now", staticmethod(_forbidden))
        monkeypatch.setattr(pd.Timestamp, "today", staticmethod(_forbidden))
        monkeypatch.setattr(
            pd.Timestamp, "utcnow", staticmethod(_forbidden), raising=False
        )

        # Neither the explicit filing date nor the signature-date fallback may
        # touch the clock.
        explicit = _connector().parse(
            N_MFP2_XML, FetchRequest(), observed_at="2024-01-08"
        )
        fallback = _connector().parse(N_MFP2_XML, FetchRequest())

        for frame in (explicit, fallback):
            assert set(frame["observed_at"]) == {pd.Timestamp("2024-01-08")}

    def test_revisions_start_at_zero_within_one_filing(self):
        frame = _connector().parse(N_MFP2_XML, FetchRequest())

        assert set(frame["revision"]) == {0}


# --------------------------------------------------------------------------
# Failing closed.
# --------------------------------------------------------------------------


class TestFailClosed:
    def test_malformed_xml_raises(self):
        with pytest.raises(SchemaValidationError, match="well-formed XML"):
            _connector().parse(b"<edgarSubmission><unclosed>", FetchRequest())

    def test_non_bytes_payload_raises(self):
        with pytest.raises(SchemaValidationError, match="must be bytes"):
            _connector().parse(12345, FetchRequest())

    def test_rendered_xhtml_payload_raises(self):
        # The submissions index points at xslN-MFP2_X01/primary_doc.xml, which is
        # XHTML; fetching that instead of the raw XML must not parse as data.
        xhtml = b'<!DOCTYPE html><html><body><p>N-MFP2</p></body></html>'

        with pytest.raises(SchemaValidationError, match="not an N-MFP filing"):
            _connector().parse(xhtml, FetchRequest())

    def test_unknown_submission_type_raises(self):
        payload = N_MFP2_XML.replace(
            b"<submissionType>N-MFP2</submissionType>",
            b"<submissionType>8-K</submissionType>",
        )

        with pytest.raises(SchemaValidationError, match="not a form N-MFP"):
            _connector().parse(payload, FetchRequest())

    def test_missing_period_end_raises(self):
        payload = N_MFP2_XML.replace(b"<reportDate>2023-12-31</reportDate>", b"")

        with pytest.raises(SchemaValidationError, match="reporting-period end date"):
            _connector().parse(payload, FetchRequest())

    def test_non_numeric_net_assets_placeholder_raises(self):
        payload = N_MFP2_XML.replace(
            b"<netAssetOfSeries>22120347521.71</netAssetOfSeries>",
            b"<netAssetOfSeries>..</netAssetOfSeries>",
        )

        with pytest.raises(SchemaValidationError, match="placeholder"):
            _connector().parse(payload, FetchRequest())

    def test_non_numeric_wam_placeholder_raises(self):
        payload = N_MFP2_XML.replace(
            b"<averagePortfolioMaturity>31</averagePortfolioMaturity>",
            b"<averagePortfolioMaturity>c</averagePortfolioMaturity>",
        )

        with pytest.raises(SchemaValidationError, match="placeholder"):
            _connector().parse(payload, FetchRequest())

    def test_placeholder_in_the_applicable_friday_slot_raises(self):
        payload = N_MFP2_XML.replace(
            b"<ns3:fridayDay5>14190110031.93</ns3:fridayDay5>",
            b"<ns3:fridayDay5>-</ns3:fridayDay5>",
        )

        with pytest.raises(SchemaValidationError, match="placeholder"):
            _connector().parse(payload, FetchRequest())

    def test_a_filing_with_no_numeric_series_raises(self):
        with pytest.raises(SchemaValidationError, match="no usable numeric series"):
            _connector().parse(N_MFP2_BARE_XML, FetchRequest())

    def test_a_valid_filing_outside_the_requested_entities_is_empty(self):
        # "Not mine" is not "malformed": the frame is empty and the schema check
        # turns it into EmptyDatasetError, which callers can tell apart.
        frame = _connector().parse(
            N_MFP2_XML, FetchRequest(entity_ids=("0000000001",))
        )

        assert frame.empty
        assert list(frame.columns) == list(OBSERVATION_COLUMNS)
        with pytest.raises(EmptyDatasetError):
            validate_observation_frame(frame, connector="sec_n_mfp")


# --------------------------------------------------------------------------
# Scoping and URLs.
# --------------------------------------------------------------------------


class TestScoping:
    def test_matching_entity_is_not_filtered_out(self):
        frame = _connector().parse(N_MFP2_XML, FetchRequest(entity_ids=("862021",)))

        assert len(frame) == 7

    def test_requested_series_are_the_only_ones_returned(self):
        frame = _connector().parse(
            N_MFP2_XML, FetchRequest(series_ids=(SERIES_WAM_DAYS,))
        )

        assert set(frame["series_id"]) == {SERIES_WAM_DAYS}


class TestBuildUrl:
    def test_submissions_url_shape(self):
        url = _connector().build_url(FetchRequest(entity_ids=("0000862021",)))

        assert url == INDEX_URL

    def test_short_cik_is_zero_padded(self):
        assert _connector().build_url(FetchRequest(entity_ids=("862021",))) == INDEX_URL

    def test_cik_prefix_is_accepted(self):
        assert (
            _connector().build_url(FetchRequest(entity_ids=("CIK0000862021",)))
            == INDEX_URL
        )

    def test_zero_entities_is_rejected(self):
        with pytest.raises(SchemaValidationError, match="exactly one"):
            _connector().build_url(FetchRequest())

    def test_two_entities_are_rejected_rather_than_truncated(self):
        with pytest.raises(SchemaValidationError, match="exactly one"):
            _connector().build_url(FetchRequest(entity_ids=("0000862021", "0000003794")))

    def test_a_non_cik_is_rejected(self):
        with pytest.raises(SchemaValidationError, match="not a CIK"):
            _connector().build_url(FetchRequest(entity_ids=("not-a-cik",)))

    def test_document_url_drops_the_rendered_path_and_dashes(self):
        url = SecNMfpConnector.build_document_url(
            "0000862021", "0001145549-24-001106", "xslN-MFP2_X01/primary_doc.xml"
        )

        assert url == DOCUMENT_URL
        assert "xslN-MFP2_X01" not in url

    def test_document_url_needs_an_accession(self):
        with pytest.raises(SchemaValidationError, match="accession"):
            SecNMfpConnector.build_document_url(CIK, "", "primary_doc.xml")


# --------------------------------------------------------------------------
# The submissions index.
# --------------------------------------------------------------------------


def _index_rows() -> list:
    return [
        {
            "accessionNumber": "0001145549-24-001106",
            "form": "N-MFP2",
            "filingDate": "2024-01-08",
            "reportDate": "2023-12-31",
            "primaryDocument": "xslN-MFP2_X01/primary_doc.xml",
        },
        {
            "accessionNumber": "0001145549-24-000001",
            "form": "485BPOS",
            "filingDate": "2024-01-09",
            "reportDate": "2023-12-31",
            "primaryDocument": "prospectus.htm",
        },
        {
            "accessionNumber": "0001145549-24-000002",
            "form": "N-MFP2",
            "filingDate": "2021-01-08",
            "reportDate": "2020-12-31",
            "primaryDocument": "xslN-MFP2_X01/primary_doc.xml",
        },
    ]


class TestSubmissionsIndex:
    def test_only_n_mfp_filings_are_returned(self):
        refs = _connector().parse_submissions(_submissions(_index_rows()))

        assert [ref.form for ref in refs] == ["N-MFP2", "N-MFP2"]

    def test_the_period_window_filters_filings(self):
        request = FetchRequest(
            start="2023-01-01", end="2023-12-31", entity_ids=(CIK,)
        )
        refs = _connector().parse_submissions(_submissions(_index_rows()), request)

        assert [ref.accession for ref in refs] == ["0001145549-24-001106"]

    def test_dates_are_parsed_into_timestamps(self):
        ref = _connector().parse_submissions(_submissions(_index_rows()))[0]

        assert ref.filing_date == pd.Timestamp("2024-01-08")
        assert ref.report_date == pd.Timestamp("2023-12-31")
        assert ref.cik == CIK

    def test_empty_recent_arrays_yield_no_references(self):
        payload = json.dumps({"cik": CIK, "filings": {"recent": {
            "accessionNumber": [],
            "form": [],
            "filingDate": [],
            "reportDate": [],
            "primaryDocument": [],
        }}}).encode()

        assert _connector().parse_submissions(payload) == []

    def test_invalid_json_raises(self):
        with pytest.raises(SchemaValidationError, match="not valid JSON"):
            _connector().parse_submissions(b"<html>not json</html>")

    def test_missing_recent_block_raises(self):
        with pytest.raises(SchemaValidationError, match="filings.recent"):
            _connector().parse_submissions(json.dumps({"cik": CIK}).encode())

    def test_mismatched_parallel_arrays_raise(self):
        payload = json.dumps(
            {"cik": CIK, "filings": {"recent": {"form": ["N-MFP2"]}}}
        ).encode()

        with pytest.raises(SchemaValidationError, match="missing required arrays"):
            _connector().parse_submissions(payload)


# --------------------------------------------------------------------------
# Orchestration and loading.
# --------------------------------------------------------------------------


def _two_filing_index() -> bytes:
    """One period, filed once and then amended: two vintages of the same month."""
    return _submissions(
        [
            {
                "accessionNumber": "0001145549-24-001106",
                "form": "N-MFP2",
                "filingDate": "2024-01-08",
                "reportDate": "2023-12-31",
                "primaryDocument": "xslN-MFP2_X01/primary_doc.xml",
            },
            {
                "accessionNumber": "0001145549-24-099999",
                "form": "N-MFP2/A",
                "filingDate": "2024-03-01",
                "reportDate": "2023-12-31",
                "primaryDocument": "xslN-MFP2_X01/primary_doc.xml",
            },
        ]
    )


AMENDMENT_URL = (
    "https://www.sec.gov/Archives/edgar/data/862021/000114554924099999/primary_doc.xml"
)


def _amendment_xml() -> bytes:
    return (
        N_MFP2_XML.replace(
            b"<netAssetOfSeries>22120347521.71</netAssetOfSeries>",
            b"<netAssetOfSeries>22000000000.00</netAssetOfSeries>",
        ).replace(b"<signatureDate>2024-01-08</signatureDate>", b"<signatureDate>2024-03-01</signatureDate>")
    )


def _fake_client() -> _FakeClient:
    return _FakeClient(
        {
            INDEX_URL: _two_filing_index(),
            DOCUMENT_URL: N_MFP2_XML,
            AMENDMENT_URL: _amendment_xml(),
        }
    )


class TestFetchOrchestration:
    def test_index_then_documents_are_fetched_in_order(self):
        client = _fake_client()
        connector = SecNMfpConnector(client=client)

        connector.fetch(FetchRequest(entity_ids=(CIK,)))

        assert client.calls == [INDEX_URL, DOCUMENT_URL, AMENDMENT_URL]

    def test_observed_at_is_the_filing_date_from_the_index(self):
        connector = SecNMfpConnector(client=_fake_client())
        frame = connector.fetch(FetchRequest(entity_ids=(CIK,)))

        base = frame.loc[frame["observed_at"] == pd.Timestamp("2024-01-08")]
        amendment = frame.loc[frame["observed_at"] == pd.Timestamp("2024-03-01")]
        assert len(base) == 7
        assert len(amendment) == 7

    def test_an_amendment_is_a_higher_revision_of_the_same_period(self):
        connector = SecNMfpConnector(client=_fake_client())
        frame = connector.fetch(FetchRequest(entity_ids=(CIK,)))
        net_assets = frame.loc[frame["series_id"] == SERIES_TOTAL_NET_ASSETS]

        by_revision = dict(zip(net_assets["revision"], net_assets["value"]))
        assert by_revision == {0: 22120347521.71, 1: 22000000000.00}
        assert set(net_assets["valid_time"]) == {pd.Timestamp("2023-12-31")}

    def test_fetch_without_a_period_filters_everything_out(self):
        connector = SecNMfpConnector(client=_fake_client())
        request = FetchRequest(
            start="2024-06-01", end="2024-12-31", entity_ids=(CIK,)
        )

        with pytest.raises(EmptyDatasetError):
            connector.fetch(request)

    def test_fetch_requires_a_registrant(self):
        with pytest.raises(SchemaValidationError, match="at least one"):
            _connector().fetch(FetchRequest())

    def test_load_into_a_pit_store_is_idempotent(self):
        connector = SecNMfpConnector(client=_fake_client())
        request = FetchRequest(entity_ids=(CIK,))
        store = PITStore()

        first = connector.load(store, request)
        second = connector.load(store, request)

        assert first.added == 14
        assert first.fetched == 14
        assert second.added == 0
        assert second.fetched == 14
        assert len(store) == 14

    def test_pit_query_does_not_see_the_amendment_before_it_was_filed(self):
        connector = SecNMfpConnector(client=_fake_client())
        store = PITStore()
        connector.load(store, FetchRequest(entity_ids=(CIK,)))

        before = store.query(
            "S000011990", SERIES_TOTAL_NET_ASSETS, as_of="2024-02-01"
        )
        after = store.query(
            "S000011990", SERIES_TOTAL_NET_ASSETS, as_of="2024-03-01"
        )

        assert before["value"].tolist() == [22120347521.71]
        assert after["value"].tolist() == [22000000000.00]


# --------------------------------------------------------------------------
# Declared metadata.
# --------------------------------------------------------------------------


class TestSpec:
    def test_spec_names_the_source_and_its_terms(self):
        spec = _connector().spec

        assert spec.name == "sec_n_mfp"
        assert spec.kind == "sec"
        assert spec.cadence == "monthly"
        assert spec.requires_credentials is False
        assert spec.source_url.startswith("https://www.sec.gov/")
        assert spec.endpoint == "https://data.sec.gov/submissions/CIK{cik}.json"
        assert "17 U.S.C. 105" in spec.licence
        assert spec.description

    def test_spec_serialises(self):
        payload = _connector().spec.to_dict()

        assert payload["name"] == "sec_n_mfp"
        assert set(payload) >= {"name", "kind", "endpoint", "licence", "cadence"}
