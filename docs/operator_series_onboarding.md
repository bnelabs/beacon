# Onboarding operator-reported series

**Who this is for:** an institution running its own BEACON deployment that
wants its *internal* risk series — liquidity buffers, funding ratios, its own
equity index, basis and premium feeds — inside the platform's governance,
backtesting and scenario machinery.

**Why it matters:** the three pre-registered early-warning runs
([v1](prereg/runs/early_warning_v1/report.md),
[v2](prereg/runs/early_warning_v2/report.md),
[v3](prereg/runs/early_warning_v3/report.md) — all tagged, all published
unchanged) established that families of *public* daily stress series are thin:
of the 13 codes in the semantics registry, six are operator-reported and were
excluded from those evaluations by declared rules ("no public source in the
evaluation environment"). Those six codes are the platform's differentiator —
no public feed will ever fill them — and this document is the path that fills
them. What operator data feeds is the platform as it honestly describes
itself: data governance, per-source predictive-validity measurement,
contagion/clearing scenarios. It does **not** resurrect an early-warning
claim; that line is parked by v3's terminal clause (see "Boundaries" below).

## 1. The six codes and their declared directions

`backend/modules/data/semantics.py` already declares the stress direction for
every code — an undeclared orientation is a refusal, not a guess, so nothing
here needs a code change:

| Code | Direction | Meaning |
|---|---|---|
| `HQLA_LEVEL` | `-1` | falling high-quality liquid assets = deterioration |
| `LCR_RATIO` | `-1` | falling liquidity coverage = deterioration |
| `NSFR_RATIO` | `-1` | falling net stable funding = deterioration |
| `BANK_EQUITY_INDEX` | `-1` | falling equity = market-judged stress |
| `FX_SWAP_BASIS` | `+1` | widening basis = funding squeeze |
| `CDS_PREMIUM` | `+1` | rising premium = credit stress |

Use these codes as the series identifiers (the `Indicator`/`indicator_id`
values below) and the event labelling, backtest scoring and refusal logic all
speak the same language. Units are the operator's responsibility — the
platform stores exactly what you declare; record the unit in the source's
`description` field (`LCR %`, `USD millions`, `bp`, …) so every downstream
surface carries it.

## 2. Route A — CSV drop (`csv` plugin)

The simplest contract in the platform. A file with:

```csv
Date,Indicator,Value
2026-09-01,LCR_RATIO,138.4
2026-09-02,LCR_RATIO,137.9
2026-09-01,NSFR_RATIO,121.0
2026-09-02,NSFR_RATIO,120.6
```

- Columns: `Date` (parseable), `Value` (numeric). The `Indicator` column is
  optional — without it the file is a single-series feed and the code is
  whatever the pipeline requests; with it, one file can carry all six.
- Rows need not be sorted; the plugin sorts by date and filters to the
  requested window. A window with no rows returns *no data* — a logged
  absence, never a fabricated zero.
- The file must be readable by the backend process — in a Compose deployment
  that means mounting it (e.g. a `./data/inputs:/data/inputs:ro` volume).

Register the source (UI: **Data Sources** page — the plugin list comes from
the live registry; or API):

```bash
curl -X POST http://<host>/api/v1/data-sources \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "internal-liquidity-csv",
    "plugin_type": "csv",
    "config": {"file_path": "/data/inputs/liquidity.csv"},
    "description": "Daily LCR/NSFR/HQLA, % and USD mm, treasury feed"
  }'
```

Refresh cadence: replace the file's contents in place and either trigger
`POST /api/v1/data-sources/{id}/sync` or set the schedule in the UI
(`sync_interval_minutes`). There is no private cache in the plugin, so a
sync always re-reads the file — nothing can serve stale bytes silently.

## 3. Route B — institutional API (`custom_api` plugin)

For a treasury/risk system that can serve HTTP. The plugin calls:

```
GET {base_url}{indicator_endpoint}/{indicator_id}?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
```

and accepts either `{"data": [{"date": …, "value": …}, …]}` or a bare JSON
array of those objects (`date`/`value` are case-normalised). Missing
`Date`/`Value` after normalisation is a logged failure, not a partial ingest.

Config keys: `base_url` (required), `indicator_endpoint` (default
`/indicators`), `asset_endpoint` (default `/assets`, for OHLCV-style pulls),
and auth — `auth_type` of `none` (default), `api_key` (`api_key`,
`api_key_header`, default header `X-API-Key`) or `bearer` (`bearer_token`).

**SSRF guardrails are part of this plugin's contract** (round-seven finding
B2) and apply to operator-supplied URLs without exception: `https` only by
default (on-prem `http` is an explicit opt-in via
`BEACON_CUSTOM_API_ALLOW_HTTP=1`); loopback, private, link-local and reserved
addresses — literal or via DNS resolution — are refused;
`BEACON_CUSTOM_API_HOST_ALLOWLIST` (comma-separated exact hosts) restricts
fetching entirely when set. Point the plugin at your intranet endpoint
through those knobs, not around them.

```bash
curl -X POST http://<host>/api/v1/data-sources \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "treasury-risk-api",
    "plugin_type": "custom_api",
    "config": {
      "base_url": "https://risk.intranet.example.com",
      "indicator_endpoint": "/beacon/series",
      "auth_type": "api_key",
      "api_key": "<from your secret store>",
      "api_key_header": "X-API-Key"
    },
    "description": "Daily internal liquidity and basis series"
  }'
```

## 4. What the platform does with the series afterwards

Everything every other source gets — no operator series is second-class, and
none is trusted more:

- **Quality gate** on every collected window (gaps, staleness, anomalies);
  results on the Data Quality page with provenance per series.
- **Event labelling in backtests** uses the declared direction above;
  per-source **predictive-validity** statistics (ROC AUC, average precision,
  median lead) render on the Results page — a measurement, never a claim of
  early warning.
- **Volatility track**: GARCH(1,1) priced against unconditional variance per
  source on every backtest (needs ≥120 observations of history on the
  source's own contiguous span; younger sources get a declared skip).
- **Predictions with uncertainty**: the deep-ensemble assessment can *refuse*
  a source whose variance is ignorance-dominant — a refused prediction renders
  as absence ("Refused", with the reason), never as a number.
- **Contagion/clearing scenarios** consume declared exposures, not these
  series directly; onboarding them does not change the network inputs.

Daily observations are recommended: the backtest and event paths operate on
whatever cadence you supply, but daily is what the volatility floor (≥120
returns) and the walk-forward defaults are sized for.

## 5. Boundaries, stated plainly

1. **The early-warning line is parked.** v3's terminal clause (declared
   before its run, honoured after) parks the "demonstrated early-warning
   system" claim on a three-run published record. Operator data enriches
   backtests, validity measurement and scenarios; it does not reopen the
   claim. A resumption is a new protocol — the recorded v4 axes are rolling
   refits and weekly/monthly tracks admitting the credit-gap family —
   owner-initiated and frozen before its run, like all three predecessors.
2. **The pre-registered evaluations stay exactly as published.** v1–v3
   excluded these six codes by their declared data-availability rules; this
   document changes no historical record and re-grades nothing.
3. **Your data stays in your deployment.** CSV files are read locally; the
   custom-API plugin only ever fetches the URLs you declare, through the
   SSRF contract above. Nothing about onboarding sends data outward.
4. **History depth is honest capital.** A series with three months of rows
   will be scored on three months of rows; skips and refusals downstream are
   declared states, not failures to hide.
