# Execution log — early_warning_v2 (protocol §5-equivalent: the single-run record)

**Tag:** `prereg-early-warning-v2` → commit `40f02b0` (protocol, config,
runner, registry additions, licence-screened hashed data manifest — all
frozen before the run).

| Attempt | When (UTC) | Outcome |
|---|---|---|
| 1 | 2026-09-17 14:05:35 → 14:07:39 | **evaluated — the run of record** (all three testable indicators, zero retries, zero infrastructure defects) |

No protocol constant, criterion, family disposition or data byte changed
between the tag and the run. The evaluation used the tagged runner against
the tagged manifest (`data/prereg/v2/manifest.json`, SHA-256 per series);
`FRED_API_KEY` was read from the environment and appears in no committed
file (grep-verified pre-merge).

**Verdict (published unchanged):** 0 of 3 indicators passed the frozen
criteria; family claim **NO**. Per-indicator facts and the three recorded
findings (byte-identical reproduction of v1's T10Y2Y numbers; T10Y3M
validating the literature-backed selection and passing the lift criterion;
the false-alarm criterion binding systematically at q95 alarms) are in
`report.md` / `report.json` and the README's claim gate, which did not move.
