# Execution log — early_warning_v1 (protocol §5: re-runs must be logged with their diff)

**Tag:** `prereg-early-warning-v1` → commit `a10d1e5` (protocol, config,
runner, hashed data manifest — all frozen before attempt 1).

| Attempt | When (UTC) | Outcome | Metrics computed before failure? | Defect & diff |
|---|---|---|---|---|
| 1 | 2026-09-17 ~12:15 | `failed` at import | **none** | `scripts/run_preregistered_eval.py` imported `QualityGate`; the real class is `DataQualityGate`. Diff: import + instantiation renamed. |
| 2 | 2026-09-17 ~12:19 | `failed` at engine load | **none** | Runner trained with `ModelTrainer` (single-scale architecture); `RealPredictionEngine._load_model` rebuilds `MultiScaleTemporalAttentionModel`, so the checkpoint could not load (state_dict key mismatch). Diff: train via `MultiScaleTrainer` — the production pairing whose checkpoints carry `config`/`source_stats`/`sources`; manual checkpoint augmentation removed. |
| 3 | 2026-09-17 12:23:51 → 12:24:43 | **evaluated** | all | — (the run of record) |

Both defects were infrastructure failures *before any metric existed* —
neither could have been informed by results — so the re-runs fall squarely
inside the protocol's single-run rule ("re-runs only for documented
infrastructure defects, each logged with its diff"). No protocol constant,
criterion, family disposition or data byte changed between the tag and the
run of record; the frozen runner differed from the tagged runner only in
the two defect diffs above.

**Run of record:** `report.json` / `report.md` in this directory, produced
by attempt 3 on the tagged data (manifest hashes in
`data/prereg/manifest.json`). Verdict: `FRED_T10Y2Y` fails 2 of 4 frozen
criteria (false alarms 9.6/quiet-year vs ≤4; does not beat the persistence
baseline on AUC or AP); testable family = 1 < minimum 3 ⇒ **no system-level
claim**. Published unchanged, per the protocol's negative-results rule.
The README claim gate did not move.
