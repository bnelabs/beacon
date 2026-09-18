# early_warning_v5 — execution log

**Protocol:** `docs/prereg/early_warning_v5.md` + `configs/event_eval_v5.yaml`
**Tag:** `prereg-early-warning-v5` (commit `4318584`, frozen and pushed BEFORE
any v5 measurement)
**Sequence executed:** tag → fetch → evaluate (the v3/v4 sequence). Single-run
rule: one evaluation run; the attempt below is the run of record.

## Attempt log (full transparency)

| Attempt | When (UTC) | Outcome |
|---|---|---|
| 1 | 2026-09-18 10:04:54 → 11:55:19 | **Completed — this is the run of record.** Ran detached (`setsid`, applying the v4 attempt-1 lesson: the execution environment SIGKILLs a launching shell's process group at its call timeout; detaching survives it — two operator-side polling interruptions occurred during the run with zero effect on it). 11 of 11 testable indicators evaluated; report written 11:55:19. Zero retries. No pre-metric defect, no restart. |

No earlier attempts exist: the fetch phase (10:02:26 → 10:04:16) ran once,
clean, and its manifest is the manifest of record.

## Fetch facts (manifest of record: `data/prereg/v5/manifest.json`)

- **11 testable** — daily: `FRED_T10Y2Y` (12,143 rows, 1976–), `FRED_T10Y3M`
  (10,752, 1982–), `FRED_VIXCLS` (8,834, 1990–), `FRED_DCOILWTICO` (9,078,
  1986–); weekly: `FRED_STLFSI4` (1,618, 1993–), `FRED_MORTGAGE30US` (2,805,
  1971–), `FRED_NFCI` (2,817, 1971–); monthly: `FRED_KCFSI` (419, 1990–),
  `FRED_FEDFUNDS` (660, 1970–), `FRED_UMCSENT` (596, 1970–); quarterly:
  `BIS_CREDIT_GAP_US` (274, 1957-Q4–2026-Q1, keyless SDMX, licence GREEN with
  attribution recorded). The runner's fetch window starts 1970-01-01 for
  every version (unchanged convention), so FEDFUNDS/UMCSENT carry their
  post-1970 rows although the series themselves reach 1954/1952 — 36 years of
  pre-2007 training data either way, far above any floor.
- **3 skipped, all by declared rule, before any metric:** `FRED_SOFR`
  (coverage 0.36 < 0.60 — starts 2018); `FRED_BAMLH0A0HYM2` (licence screen
  refused it **pre-download**: "Reproduction of this data in any form is
  prohibited"); `ECB_CISS` (declared keyless attempt; licence screen could not
  read series metadata: HTTP 400 — recorded, not substituted).
- **7 excluded:** the six operator-reported codes (no public source; the PRA
  probe confirmed bank-level data is supervisory-confidential) and
  `FRED_RRPONTSYD` (owner exclusion, standing since v1).
- Transport: keyed FRED API (`FRED_API_KEY` environment-only; every recorded
  endpoint carries `api_key=<redacted>`; post-run grep of every committed file:
  key absent) + keyless BIS SDMX CSV (quarter-end convention; homogeneous-series
  check passed). Licence lines recorded per series, including the Freddie Mac
  copyright line (MORTGAGE30US) and the University of Michigan citation
  requirement (UMCSENT).
- Fresh fetch: every SHA-256 differs from v4's manifest (new downloads); see
  the reproducibility result below for what did NOT differ.

## Run environment

2 CPUs (`OMP_NUM_THREADS=2`), Python 3.12.14, torch 2.14.0+cpu, ~500 MB RAM
available held throughout, disk stable (~5.5 GB free). Total wall time 1 h
50 m 25 s; per-indicator: STLFSI4 3m13s · KCFSI 50s · T10Y2Y 27m06s ·
T10Y3M 26m29s · VIXCLS 17m33s · BIS 41s · DCOILWTICO 18m46s ·
MORTGAGE30US 6m31s · NFCI 6m26s · FEDFUNDS 1m32s · UMCSENT 1m18s.

## Reproducibility (checked programmatically against v4's published report)

All five indicators shared with v4 (T10Y2Y, T10Y3M, VIXCLS, STLFSI4,
BIS_CREDIT_GAP_US) reproduce **20 of 20 scorer pairs byte-identically** —
frozen AND rolling — on fresh fetches with new SHA-256s: same AUC, AP,
false-alarm rates, leads, criteria outcomes. That includes
`FRED_STLFSI4 × hazard_logit`'s full pass (AUC 0.9223, AP 0.3836, p=0.0010,
FA 0.483) and `FRED_T10Y3M × tan_frozen`'s 4.202 FA/quiet-yr — the 0.2-miss,
identical for the third consecutive run. Byte-identical reproducibility now
holds across five runs.

## Deviations

As declared in the protocol (report.json `deviations`): in-process execution
rather than the Celery job queue; chronological holdout (train ≤2006,
evaluate 2007–2024) rather than CPCV. No others. No criterion, constant,
family entry, alarm rule or scorer spec changed after the tag:
`git diff prereg-early-warning-v5 HEAD` at the run touched no runner or
config path.

## Verdict (published unchanged)

**Family: 2 of 11 passed** (`FRED_STLFSI4`, `FRED_DCOILWTICO`) against a
rule requiring at least half (≥6) — **system-level claim NOT warranted; the
line remains parked with a five-run record; there is no planned v6** (the
outcome handling frozen before the run). The two passes are published as
facts with their numbers (see `report.md`), not upgraded into a system claim.
