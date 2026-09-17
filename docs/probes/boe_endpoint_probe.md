# Bank of England Endpoint Probe

> **Status: EXECUTED 2026-09-17 — findings recorded below.** The
> methodology and decision criteria follow, as written before the run; the
> "Expected Outcomes" sections are left untouched so the pre-registered
> criteria can be read against what was actually observed. Classification:
> **YELLOW (requires work)** — see Findings.

## Probe Findings (executed 2026-09-17, ~9 requests, all observed)

Raw results, recorded as returned:

| # | Request | Observed |
|---|---|---|
| 1 | `HEAD https://www.bankofengland.co.uk/-/media/boe/files/statistics/uk-banks-balance-sheet-data.xlsx` | **404**, redirected to `/error/404.html`. The file path this methodology guessed does not exist. |
| 2 | `GET https://api.bankofengland.co.uk/` | **DNS NXDOMAIN** — no REST API host exists at that name. |
| 3 | `GET https://www.bankofengland.co.uk/boeapps/database/` | **200** (25 kB). The Interactive Database is live; the page's data forms post to `FromShowColumns.asp`; category indices (COUNTRY / INSTRUMENTS / SECTOR / A–Z) are linked from it. |
| 4 | `GET …/boeapps/database/fromshowcolumns.asp?csv.x=yes&Datefrom=02/Jan/2024&Dateto=05/Jan/2024&SeriesCodes=IUDBEDR&CSVF=CNF&UsingCodes=Y&VPD=Y&VFD=N` | **200**, 40 kB **HTML** (not CSV, despite `csv.x=yes`), containing a clean data table: *Official Bank Rate* (`IUDBEDR`) = **5.25** on 02/03/04/05 Jan 2024 — real values, matching the published history for that week. **No authentication, no API key, no registration.** |
| 5 | `GET https://www.bankofengland.co.uk/statistics` | **200** — statistics hub reachable. |

A first attempt at #4 with ISO dates (`Datefrom=2024-01-02`) redirected to
`ErrorPage.asp`; the `DD/Mon/YYYY` form is what the interface accepts. The
date format is the only parameter sensitivity found.

### Assessment against the named preconditions

1. **Machine-readable access** — *partial*. Real series data is served
   without auth, but as HTML tables at the probed URL; the `csv.x=yes`
   switch did not produce `text/csv`. Either a CSV variant exists behind
   parameters/headers not probed here, or ingestion needs an HTML-table
   parser with strict schema validation (the table structure is regular:
   date/value cell pairs under a labelled series header).
2. **Bank-level exposure data or aggregate systemic indicators** —
   *aggregate: yes* (the database covers UK monetary and financial
   statistics — Bank Rate, rates and FX series, with sector/instrument
   category indices). *Bank-level: not found* — the guessed balance-sheet
   file 404'd, and bank-level prudential data would live with the PRA, not
   probed here.
3. **Regular update cadence** — *yes* for the rates family (daily
   observations returned for a 4-day window).
4. **Rate limits** — not hit at ~9 polite requests; no published automated-
   collection terms were found in this probe. A production plugin must
   cache aggressively and identify itself (User-Agent was set for this
   probe).

### Classification: YELLOW (requires work)

Endpoint exists, serves real data, no registration — but no formal
machine-readable contract at the probed URL. Per this document's own
decision paths, the actions are:

1. Discovery follow-up (bounded): probe the site's own XHR/JSON endpoints
   behind `FromShowColumns.asp` and CSV parameter variants before writing
   any parser.
2. If no CSV/JSON contract surfaces: implement `boe_database_plugin.py`
   with an HTML-table parser, strict schema validation, typed
   `SchemaValidationError`/`DataSourceUnavailableError` on any drift, and
   the platform's usual no-synthetic-fallback rules. Series to register
   first: Official Bank Rate (`IUDBEDR`); candidates for the semantics
   registry: SONIA-family rates (direction: rising = tightening = stress,
   consistent with `FRED_SOFR`).
3. Bank-level UK exposures: separate probe against the PRA, out of this
   document's scope.
4. Licensing/attribution: confirm terms for redistribution in derived
   reports before shipping (BoE statistical data is normally free to use
   with attribution; the exact licence was not captured by this probe).

### Discovery follow-up (executed 2026-09-17, ~5 further requests)

Action 1 of the YELLOW path is complete. Observed:

- The Interactive Database is a classic server-rendered ASP application:
  the landing page's forms post to `FromShowColumns.asp`; no REST/JSON
  service is referenced anywhere in the landing or results pages.
- `csv.x=yes` does **not** switch the content type on a stateless GET
  (HTML returned, `Content-Type: text/html`); the results page contains no
  CSV/XLS/download links — the only "csv" in the response is the echoed
  query parameter.
- The statistics hub landing page links no `.xlsx`/`.csv`/`.zip` data files
  (media refs are PDFs/images); bulk statistical files, where they exist,
  sit behind per-dataset pages that each need their own discovery pass.

**Consequence — the parser path is confirmed, not avoided.** The reliable
series-level contract is the HTML table returned by `FromShowColumns.asp`
(`SeriesCodes=<code>`, `Datefrom`/`Dateto` in `DD/Mon/YYYY`, `UsingCodes=Y`),
whose structure was observed to be regular: labelled series header, then
date/value cell pairs. A `boe_database_plugin.py` should therefore:

1. request the HTML table with an identifying User-Agent and cache
   aggressively (daily series change at most daily);
2. parse with a strict table parser and validate the schema (header names,
   date parseability, numeric values) — any drift raises the platform's
   typed `SchemaValidationError`/`DataSourceUnavailableError`, never a
   silent default;
3. register first series: Official Bank Rate (`IUDBEDR`), then SONIA-family
   candidates for the semantics registry (direction per `FRED_SOFR`
   convention);
4. confirm BoE reuse/attribution terms before shipping (still open — this
   probe captured no licence statement).

*Probe discipline: every status code, redirect and value above was
observed on 2026-09-17; nothing is inferred from documentation alone.*

---

## Purpose
Phase 5 evidence-first external: probe the Bank of England (BoE) API endpoint to assess feasibility as a data source for UK banking sector exposures and systemic risk indicators.

## Named Precondition
The BoE endpoint must provide:
1. **Machine-readable access** (REST/JSON or CSV over HTTP)
2. **Bank-level exposure data** or aggregate systemic indicators
3. **Regular update cadence** (daily/weekly/monthly)
4. **No prohibitive rate limits** for automated collection

## Probe Methodology

### Step 1: Endpoint Discovery
Target endpoints to probe:
- `https://www.bankofengland.co.uk/-/media/boe/files/` (data repository)
- `https://api.bankofengland.co.uk/` (if REST API exists)
- Specific datasets:
  - UK banks' balance sheet data
  - Interbank lending rates (SONIA, LIBOR transition)
  - Prudential Regulatory Authority (PRA) returns

### Step 2: Connectivity Test
```bash
curl -I "https://www.bankofengland.co.uk/-/media/boe/files/statistics/uk-banks-balance-sheet-data.xlsx"
```

Expected responses:
- `200 OK`: Direct file access available
- `301/302 Redirect`: Follow redirect, check final destination
- `403 Forbidden`: May require registration/API key
- `404 Not Found`: Endpoint doesn't exist at this path

### Step 3: Data Quality Assessment
If accessible, evaluate:
- **Schema**: Column names, data types, units
- **Coverage**: Time range, bank coverage, frequency
- **Freshness**: Last update date vs current date
- **Completeness**: Missing values, structural breaks

### Step 4: Integration Feasibility
Based on findings, determine:
1. **Plugin implementation effort** (hours/days)
2. **Registration requirements** (API key, terms acceptance)
3. **Rate limit constraints** (calls/day, bandwidth)
4. **Data licensing** (commercial use, attribution)

## Expected Outcomes

### Green Path (Integration Ready)
- ✅ Endpoint responds with valid data
- ✅ No authentication required OR simple API key
- ✅ Data schema matches BEACON's exposure model
- ✅ Update frequency aligns with monitoring needs
- **Action**: Implement `boe_plugin.py` following pattern of `ecb_banking_plugin.py`

### Yellow Path (Requires Work)
- ⚠️ Endpoint exists but requires registration
- ⚠️ Data format needs transformation (PDF → structured)
- ⚠️ Rate limits require caching strategy
- **Action**: Create feasibility ticket with registration steps and estimated integration effort

### Red Path (Not Feasible)
- ❌ No machine-readable endpoint
- ❌ Data behind paywall or restrictive license
- ❌ Format is PDF-only without bulk download
- **Action**: Document limitation, consider alternative UK data sources (FCA, ONS)

## Documentation Updates
Upon completion:
1. Record findings in this file (there is no `docs/data-sources.md` today; create one only if the findings justify it)
2. Update the plugin registry (`backend/plugins/`) if integration proceeds
3. Note any API keys in deployment documentation

## Timeline
- Probe execution: 1-2 hours
- Decision memo: Same day
- Plugin implementation (if green): 1-2 days

---
*Phase 5 deliverable — methodology first, evidence second: the run happened
2026-09-17 and its findings are recorded at the top, against these
pre-registered criteria.*
