# NBFI / CCP data connectors

Five feeds the pipeline previously lacked. Four retrieve from public APIs; the
fifth (`sec_form_pf`) is confidential by law and deliberately refuses.

```
backend/modules/data/connectors/
├── base.py           DataConnector, ConnectorSpec, FetchRequest, HttpClient
├── __init__.py       lazy registry: build_connector / available_connectors
├── sec_n_mfp.py      SEC Form N-MFP      -> money-market fund portfolios
├── bis_credit.py     BIS total credit    -> private non-financial sector credit
├── ecb_ccp.py        ECB CCP statistics  -> CPMI-IOSCO public quantitative disclosures
├── payments.py       Fedwire + TARGET2   -> large-value payment throughput
└── sec_form_pf.py    SEC Form PF         -> refuses; see below
```

## The contract every connector honours

1. **One schema.** `fetch()` returns an *observation frame* — exactly
   `OBSERVATION_COLUMNS` from `backend.modules.data.pit` — so output drops
   straight into a `PITStore` with no per-source adapter.
2. **Two clocks, never conflated.** `valid_time` is the period a number
   *describes*; `observed_at` is when the source *published* it. Collapsing them
   is what makes a backtest silently clairvoyant, so it is enforced centrally.
3. **Fails closed.** Unreachable source, unexpected schema, or an empty result
   raises a typed `BeaconError` with a stable `code`. No connector ever invents,
   interpolates, forward-fills or back-fills a value.
4. **Declares itself.** Each carries a `ConnectorSpec` naming its licence and
   terms; the three publishers attach different conditions to redistribution.
5. **I/O is separate from parsing.** `parse()` performs no network I/O, so every
   parser is tested against recorded payloads and the suite stays offline.
6. **Identifies itself.** Every request sends a descriptive `User-Agent`. SEC
   returns 403 without one.

## Usage

```python
from backend.modules.data.connectors import build_connector, available_connectors
from backend.modules.data.connectors.base import FetchRequest
from backend.modules.data.pit import PITStore

store = PITStore()
connector = build_connector("ecb_ccp")
report = connector.load(store, FetchRequest(start="2020-01-01", end="2025-12-31"))
print(report.to_dict())

# Loads are idempotent: PITStore de-duplicates identical re-appends.
assert connector.load(store, FetchRequest(start="2020-01-01", end="2025-12-31")).added == 0
```

## The feeds

### `sec_n_mfp` — money-market fund portfolios *(monthly)*

Discovery is `https://data.sec.gov/submissions/CIK##########.json`; the document
is fetched as `<accession-dir>/primary_doc.xml`. Four filing schemas exist and
are all handled: legacy `nmfp` (≤2016-04), `nmfp1`, `nmfp2`, and `nmfp3`
(current since 2024-07).

| Series | Unit |
|---|---|
| `N-MFP:TOTAL_NET_ASSETS` | USD |
| `N-MFP:WAM_DAYS`, `N-MFP:WAL_DAYS` | days |
| `N-MFP:DAILY_LIQUID_ASSETS`, `N-MFP:WEEKLY_LIQUID_ASSETS` | USD |
| `N-MFP:DAILY_LIQUID_ASSETS_PCT`, `N-MFP:WEEKLY_LIQUID_ASSETS_PCT` | fraction as filed |

* `entity_id` is the filing **series id**, not the CIK: one registrant files
  several series on the same day and collapsing on CIK would collide.
* `observed_at` is the EDGAR **filing date** (fallback: the filing's
  `signatureDate`); if neither exists the parse **raises**. The current time is
  never used.
* `/A` amendments of the same month are renumbered to `revision >= 1`.

> **The EDGAR full-text search endpoint is useless for this form.** It returns
> 200 but **zero** N-MFP hits across every window tried, while a control query
> returns results. It is therefore not used. Watch for the other trap:
> `filings.recent.primaryDocument` is the *rendered* path
> (`xslN-MFP2_X01/primary_doc.xml`) and serves XHTML; the connector keeps the
> basename and fetches the machine XML.

Discovery reads `filings.recent` only; older `filings.files` chunks are not
fetched. Security-level holdings and repo collateral are not extracted.

### `bis_credit` — private credit *(quarterly)*

`https://stats.bis.org/api/v1/data/WS_TC/all?format=csv`. Default slice:
`TC_BORROWERS ∈ {P,N,H}` (private non-financial sector and its components),
`TC_LENDERS ∈ {A,B}`, `TC_ADJUST="A"`, `FREQ="Q"`.

`series_id` = `BIS:TC:borrowers=P:lenders=A:val=M:unit=770`; `entity_id` is the
borrower country or aggregate. `valid_time` is the **quarter end**, because credit
is an end-of-period stock.

`observed_at` uses real release dates when supplied via
`parse_release_calendar()` (from the `BIS_REL_CAL` dataflow — note `WS_REL_CAL`
does **not** exist); otherwise `valid_time + 171` days, the maximum of 14 real
releases, chosen so a PIT query can never see a value too early.

`UNIT_MULT` is the SDMX exponent (verified: `770/799 → 0` = per cent,
`USD/XDC → 9` = **billions**). Values are stored exactly as published, unscaled.

### `ecb_ccp` — CPMI-IOSCO public quantitative disclosures *(annual)*

`https://data-api.ecb.europa.eu/service/data/CCP/all?format=csvdata`.
19 CCPs, 2006–present.

`series_id` carries the **full** coded dimension set —
`ECB:CCP:ccp=AT1:info=D03:instr=Z:area=X0:sss=ZZZ:cur=Z0Z:denom=Q:unit=PURE_NUMB:mult=1:freq=A`.
This matters: 9,791 of 16,832 `(CCP, info, instrument, freq, year)` groups hold
more than one row, usually a `SERIES_DENOM` `Q`/`E` pair with different values,
so a shorter key fails closed on the real feed.

`OBS_STATUS` is exactly correlated with emptiness over all 88,160 rows: `A`
(normal) ⟺ a value (43,880); `L` (not collected, 17,082) and `M` (cannot exist,
27,198) ⟺ empty. Empty rows are skipped and counted, never zeroed.

`UNIT_MULT` is **not** applied: the code `1` would imply ×10 for participant
counts, but the published totals are plainly raw counts. The raw value is emitted
verbatim and the multiplier rides in `series_id`. This apparent ECB metadata
inconsistency is flagged rather than guessed at.

### `payments` — Fedwire and TARGET2 *(annual)*

Two sources behind one facade. `PaymentsConnector` fetches both and returns a
combined frame; series prefixes cannot collide.

| Rail | Source | Key |
|---|---|---|
| Fedwire | BIS CPMI `WS_CPMI_SYSTEMS` | `REP_CTY=US`, `SYSTEM=US2P` |
| TARGET2 | ECB `PSS` | `PSS_SYSTEM=P101` |

Both were confirmed from the publishers' own codelists rather than by guessing,
then sanity-checked on magnitude (Fedwire 2024: 209.9m transfers, $1.133
quadrillion). `P1T1`/`P1T2` exist in the ECB codebook but return 404 for every
period, so they are deliberately unused.

`entity_id` is the **payment system** (`FEDWIRE` / `TARGET2`). Values are scaled
out of millions once, at parse time.

**The facade fails the whole call if either source fails.** A frame missing one
rail is indistinguishable downstream from "that rail settled nothing", and the
schema has nowhere to record the difference.

Two findings worth keeping:
* ECB answers **HTTP 200 with a 0-byte body** for a window it has no data for
  (e.g. TARGET2 past 2021), which is correctly an `EmptyDatasetError` — not a
  schema change. An out-of-catalogue key behaves differently (404 →
  `DataSourceUnavailableError`).
* Adding `includeHistory=true` exposes the ECB's per-observation `VALID_FROM`,
  so TARGET2's `observed_at` is a **real publication timestamp** rather than an
  assumption.

### `sec_form_pf` — refuses, by design

Form PF is the confidential systemic-risk filing that private fund advisers
submit. Individual filings are not public, and that is the design of the regime,
not a missing key. Verified 2026-09-11:

* `data-research/statistics-data-visualizations/private-fund-statistics` → **200**
  (the public substitute: *aggregated* Form PF data).
* `foia/docs/form-pf-data.htm` → **404** (there is no public data page).
* `efts.sec.gov/...?forms=PF` → 200 but serves the search index, not filings.

Every retrieval method raises `RestrictedSourceError`
(`code="DATA_SOURCE_RESTRICTED"`, HTTP **451**). It is not silent and not
retried: retrying never helps, and an empty frame would be indistinguishable from
"no funds to report".

An institution that lawfully holds the data can still load it:

```python
connector.load_authorised_export(store, frame, source_reference="PFRD receipt 12345")
```

`source_reference` is mandatory — an explicit attestation of the authority under
which the data was obtained — so restricted data can never enter the store
anonymously.

## Publication clocks: what is real and what is assumed

| Feed | `valid_time` | `observed_at` | Basis |
|---|---|---|---|
| `sec_n_mfp` | report month end | EDGAR filing date | **real** |
| `payments` (TARGET2) | year end | ECB `VALID_FROM` | **real** |
| `payments` (Fedwire) | year end | `BIS_REL_CAL` release date | **real** (2022–2024); 1y6m fallback |
| `bis_credit` | quarter end | `BIS_REL_CAL` if supplied | **real when supplied**; 171-day fallback |
| `ecb_ccp` | year end | `valid_time + 212 days` | **assumed** (late bound of ECB's stated 6–7 months) |

Every lag is an overridable constant, is chosen conservatively so a PIT query
cannot see a value early, and never reads the wall clock.

## Known limitations

* **Revision history is mostly absent.** `bis_credit` and `ecb_ccp` expose only
  the latest vintage, so `revision` is always 0 and a restatement is stamped with
  its first release date. Only `sec_n_mfp` distinguishes revisions, via `/A`
  filings.
* **`ecb_ccp` `UNIT_MULT`** is unapplied and the ECB metadata appears internally
  inconsistent (see above).
* **`COUNT_SECTOR`** in ECB `PSS` (TARGET interbank legs) was not verified
  against a codelist, so only the all-counterparty total is captured.
* **`bis_credit` `TC_ADJUST`** is not part of `series_id`, so configuring both
  adjusted and unadjusted slices collides; conflicting values raise.
* **BIS terms** at `bis.org/terms_statistics.htm` return 403 to this client;
  terms are quoted from the BIS Data Portal mirror instead.
* Suppression is rare in these feeds — BIS CPMI has no blank `OBS_VALUE` at all —
  so the "blank is skipped" tests for two connectors blank a real cell and label
  the fixture as synthetic. The ECB tombstone used for the same test is real.
