# Bank of England Endpoint Probe

> **Status: planned, not executed.** This document is the probe methodology
> and decision criteria. No probe has been run yet, so it records no
> findings — every response code and outcome below is *expected*, not
> *observed*. When the probe runs, its results get appended here with the
> date and the raw responses, or this stays a plan and says so.

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
*Phase 5 deliverable — the methodology; the evidence comes when the probe runs*
