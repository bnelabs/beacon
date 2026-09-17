# Execution log — early_warning_v3 (single-run record)

**Tag:** `prereg-early-warning-v3` → commit `994dd65` (protocol, config,
runner with both scorers, helper tests — frozen before the run).

**Sequence (declared):** tag → fetch → evaluate. Unlike v1/v2 (whose
fetch preceded the tag), v3's fresh keyed fetch ran after the protocol tag
and before any metric; the manifest with per-series SHA-256 hashes, fetch
timestamps, licence lines and redacted endpoints is committed with this
report, so the data the run consumed is exactly auditable. The invariant
that matters — rules frozen before data and metrics — held in all three
versions.

| Attempt | When (UTC) | Outcome |
|---|---|---|
| 1 | 2026-09-17 16:24:37 → 16:26:43 | **evaluated — the run of record** (3 indicators × 2 declared scorers, zero retries, zero infrastructure defects) |

`FRED_API_KEY` was read from the environment; grep of every committed path
in `data/prereg/v3/` confirms the key appears in zero files. Licence screen
ran before every download; `FRED_BAMLH0A0HYM2` was refused pre-download on
its prohibition language (no prohibited bytes exist in this directory).

**Verdict (published unchanged):** 0 of 3 indicators passed; family claim
**NO**. Under the terminal clause declared in the protocol before the run,
the early-warning line is **parked** with this three-run record:

- **v1** (`prereg-early-warning-v1`): under-powered — one testable
  indicator, below the minimum family; that indicator failed FA and lift.
- **v2** (`prereg-early-warning-v2`): better-powered NO — 0/3; the
  diagnosis was the q95 alarm point making the FA criterion arithmetically
  unreachable (~9–10 FA/quiet-year vs ceiling 4 for every indicator).
- **v3** (`prereg-early-warning-v3`): coherent operating point, terminal
  run — 0/3. Findings recorded in the report and README:
  1. The q98 alarm point fixed what v2 diagnosed (FA/quiet-year fell to
     2.7–4.7; two of three indicators now clear that criterion) — and
     consumed lead time exactly as declared pre-run (medians 42→10,
     18.5→10, 11.5→8; VIX fell through the frozen ≥10-day floor). The
     lead/FA trade-off at these criteria defines a narrow operating region
     that none of the three scorers reached on all four criteria.
  2. `FRED_T10Y3M` · `tan_frozen` failed on the FA criterion alone, by
     0.2 alarms per quiet year (4.2 vs 4.0) — the closest any candidate
     came across three runs. It is published as a fail; loosening the
     ceiling after seeing 4.2 would be exactly the goalpost-move the
     protocol exists to forbid.
  3. The frozen hazard logit failed out-of-sample on both spread series
     (AUC 0.39/0.44 — worse than chance): an 18-year extrapolation of a
     pre-2006 hazard fit does not survive the QE-era regime change. The
     literature's architecture pairs hazard models with rolling refits;
     our frozen-model discipline forbade one. Recorded as the finding it
     is: frozen-forever scoring and hazard architectures are a poor
     pairing; any future line starts from rolling refits.
  4. Reproducibility held a third time: alarm-independent metrics (AUC,
     AP) are identical across v2 and v3 for every indicator-scorer pair;
     only the alarm-dependent statistics moved, exactly as the rule change
     implies.

No protocol constant changed between tag and run. This directory
(`report.json`, `report.md`, this log) is the complete published record;
the README claim gate did not move and now carries the parked status.
