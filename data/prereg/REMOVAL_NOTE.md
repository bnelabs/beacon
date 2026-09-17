# Removal note — FRED_BAMLH0A0HYM2.csv (removed 2026-09-17)

This directory held a 339-row capture of the ICE BofA US High Yield OAS
series, fetched keyless during the early_warning_v1 protocol's fetch phase
and committed as provenance. The series was **skipped before any metric
existed** (insufficient coverage: a 2023-09-start window), so no v1 result
ever consumed these bytes.

When the v2 protocol added a licence screen, the series' own FRED notes were
read in full: ICE Data Indices terms state *"Reproduction of this data in
any form is prohibited except with the prior written permission of ICE Data
Indices"* and *"provided for your internal use only and you are not
authorized or permitted to publish, distribute or otherwise furnish"* the
data. FRED also now serves only a rolling 3-year window (series
`observation_start` = 2023-09-18; per the notes, from April 2026 the series
carries just 3 years of observations).

Committing the capture as "provenance" was therefore itself the violation
the licence prohibits. The file is removed from the working tree as of this
commit. It remains reachable in git history at tag
`prereg-early-warning-v1` — published history is not rewritten, and the
record of why the file existed and why it was removed is this note plus the
CHANGELOG. The v1 `manifest.json` is left byte-identical (it is a frozen
record; its `csv` field for this entry now points at a removed file, which
is accurate: the data was fetched, never used, and withdrawn).

v2 excludes the series via the licence screen **before** downloading it, and
the screen's prohibition patterns are declared in
`scripts/run_preregistered_eval.py` and `configs/event_eval_v2.yaml`.
