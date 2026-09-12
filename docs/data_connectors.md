# The NBFI / CCP connector layer: deleted, and why

**Status: deleted.** `backend/modules/data/connectors/` is gone, along with its
five test files. This file is the decision record: what the layer was, what the
migration spike found, and why removal was the honest answer rather than a
wiring task deferred again.

The code is recoverable from git history; the reasoning is here so it does not
have to be reconstructed.

## What was removed

| Module | Source | Lines |
|---|---|---|
| `sec_n_mfp.py` | SEC Form N-MFP money-market fund portfolios | 933 |
| `payments.py` | Fedwire + TARGET2 payment-system throughput | 1315 |
| `bis_credit.py` | BIS credit to the private non-financial sector | 857 |
| `ecb_ccp.py` | ECB / CPMI-IOSCO CCP disclosures | 623 |
| `sec_form_pf.py` | SEC Form PF — refuses by design (confidential) | 224 |
| `base.py` | `DataConnector`, `ConnectorSpec`, `HttpClient`, observation validation | 507 |
| `__init__.py` | lazy registry: `build_connector`, `available_connectors` | 99 |

Plus roughly 3,100 lines of tests. `backend/modules/data/pit.py` was **kept** and
given a real home — see below.

## Why it was deleted

The layer was implemented and well tested, but `build_connector` had no
production caller: ingestion runs on the separate `backend/plugins/` layer. Two
overlapping ingestion abstractions existed and only one was live. The census
recorded that as an open decision between "migrate" and "bridge"; a spike on
`ecb_ccp` closed both options with evidence.

### Finding 1 — no consumer at the required granularity

`ecb_ccp` looked like the producer for
`build_ccp_exposure_layer` in `backend/modules/engine/multiplex.py`. It is not.
That consumer wants `member_exposures` with columns `member` and `exposure`:
per-clearing-member obligations to the CCP.

The ECB `CCP` dataflow has **no clearing-member dimension at all**. Its
dimensions are `CCP_SYSTEM`, `SSS_INFO_TYPE`, `SSS_INSTRUMENT`, `COUNT_AREA`,
`SSS_SYSTEM`, `CURRENCY_TRANS`, `SERIES_DENOM`, `UNIT`, `UNIT_MULT` and `FREQ`;
its `entity_id` is the CCP system, and its values are annual aggregates — counts
of participants by *type* (central bank / credit institution / other) and
securities transfer volumes. Participants are grouped, never identified
(`ST1`/`ST2` name transfer directions, not counterparties).

The two are not the same object at different resolution; they are different
objects. Wiring them would have produced exactly the defect this census exists to
find: a green import with nothing flowing. The other four feeds are the same
shape — market-context series, none a producer for a network layer the engine
builds.

### Finding 2 — the plugin contract cannot carry the two clocks

Bridging into `backend/plugins/` was the cheap option, and it is impossible
without loss. `DataSourcePlugin.fetch_indicator_data` returns a frame of
`Date, Value` — **one clock**. A grep for `observed_at` or `revision` across
`backend/plugins/`, `collector.py` and `data_source_service.py` returns nothing:
the production ingestion path has no concept of a publication vintage.

That was the connector layer's entire reason to exist. Its own contract said
collapsing `valid_time` and `observed_at` "is what makes a backtest silently
clairvoyant." A bridged connector would have handed the pipeline precisely the
clairvoyance it was written to prevent.

So "migrate or bridge" was the wrong question. Bridging is refuted, and migration
is not a registry entry — it means giving the ingestion contract vintages, which
is a platform decision with no consumer asking for it.

## What was kept, and where it went

`backend/modules/data/pit.py` (509 lines) is the reusable asset: the
`Observation` two-clock schema, `PITStore` with as-of retrieval, and `as_of_join`.
Deleting the five parsers does not delete the point-in-time design; it was always
`pit.py` that encoded it.

It now has a production home. The bilateral exposure store's manifest already
carried both clocks — `as_of` is the vintage a matrix *describes*, `uploaded_at`
is when it *became known* — and `BilateralExposureStore.load_as_of()` resolves a
matrix through `PITStore`:

* `GET /api/v1/network/graph?as_of=<ISO 8601>` returns the matrix as it was known
  at that instant;
* a cut-off before the stored matrix was uploaded returns `unavailable` with a
  reason naming the cut-off — **the current matrix is never substituted for a
  vintage that did not exist yet.**

That is the anti-clairvoyance guarantee the connectors were built to provide,
applied to the one exposure path the engine actually consumes.

## What would justify rebuilding this

A concrete consumer for one of the five feeds, at a granularity the engine can
use. If that arrives, the ingestion contract gains a vintage field first and the
parser is written against the then-current API — the responses these were written
against were verified on 2026-09-11 and will have moved.
