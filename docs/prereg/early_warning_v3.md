# Pre-registered early-warning evaluation — protocol v3

**Status: FROZEN, pending run.** Machine-readable half:
[`configs/event_eval_v3.yaml`](../../configs/event_eval_v3.yaml). Owner
sign-off: given in chat on 2026-09-17 ("do all of them", approving the
decisive-v3 design as presented: coherent alarm arithmetic + hazard scorer,
every grading criterion frozen). Committed and git-tagged
`prereg-early-warning-v3` **before** the run; after the tag, changes require
protocol v4 plus a CHANGELOG entry.

**Terminal clause (declared now, honoured either way):** v3 is the last
planned iteration of this line. Pass → the README claim gate moves, carrying
these numbers. Fail → the early-warning line is parked with a three-run
documented record (v1: under-powered NO; v2: better-powered NO with
diagnosis; v3: coherent-operating-point NO), and the platform's claims rest
on what it demonstrably is: a governance and scenario laboratory with
unusually honest reporting. Both outcomes are publishable; neither gets
argued with after the fact.

## 1. What v3 changes — and the published arithmetic that motivates it

v2 graded three indicators and passed none. The cross-indicator pattern was
the finding: the **false-alarm criterion bound every indicator** (~9–10 per
quiet year against a ceiling of 4) because the frozen alarm rule (top 5% of
scores) fires ~12.6 times per year while measured precision at that
operating point was 23–29% — even for the 0.93-AUC indicator. From
published numbers only:

```
FA/year = alarms/year × (1 − precision)
q95:    ≈ 12.6 × (1 − 0.23…0.29) ≈ 9.0…9.7   vs ceiling 4  → unreachable
q98:    ≈  5.0 × (1 − p) ≤ 4  requires p ≥ ~20%             → demanding but possible
```

So the q95 alarm point made criterion 2 mathematically unreachable for any
indicator; that is a **protocol design incoherence**, now measured twice.
v3 declares the coherent operating point **before** running: alarm quantile
**0.98**. This is design iteration on published results — the discipline
that separates it from goalpost-moving is that **no grading criterion
changes**: the ≤4 FA/quiet-year ceiling, ≥10-day median lead, both-baseline
lift, AP>base-rate with Holm-adjusted significance are exactly v1's, frozen
since before any run existed.

Declared risk, accepted pre-run: rarer alarms can shorten median lead (VIX
measured 11.5 days at q95 against a 10-day floor). If lead now binds, that
is the result.

## 2. What v3 adds — the literature-standard scorer

One-step *level* forecasting is a weak EWS architecture; the crisis-
prediction literature estimates **episode-onset hazard**. v3 declares a
second scorer, frozen in the runner and in `test_prereg_runner.py`:

- **`hazard_logit`**: logistic regression of P(onset within 21 business
  days) on two declared features — the direction-signed standardized level
  and its 63-day (≈ one quarter) change, clamped at series start, past
  information only. Fit labels come from `label_events` on the **training
  span** (labels never cross into evaluation; features never see labels).
  Estimator: `sklearn LogisticRegression` at library defaults (L2, C=1.0,
  lbfgs, no class weighting), fitted once on ≤2006 — the same frozen-small-
  model discipline as the TAN. No knob is exposed, so none can be turned
  after seeing results. Score = `decision_function` (criteria are rank-based;
  no calibrated-probability claim is made). No training-span onsets ⇒
  declared absence, never zero-signal.
- **`tan_frozen`**: the v1/v2 scorer, byte-identical config and seed,
  retained so v3 answers "does the architecture matter?" on the same grid.

Both scorers face the identical labels, grid, alarm rule, baselines and
criteria. **Multiplicity is accounted honestly:** Holm–Bonferroni pools
*every* scorer–indicator pair (two scorers double the hypotheses), and an
indicator passes only via a scorer whose AP survives that pool.

## 3. What v3 does NOT change

Windows (train ≤2006; evaluate 2007–2024), labelling (q95 horizon-move,
h=21, persistence 5, historical threshold span), sign adjustment,
`row_offset` alignment, baselines (persistence, AR(1)), model config and
seeds, permutation test (1000 shuffles, seed 20260917), Holm α=0.05,
minimum testable family 3, family rule (≥ half pass), single-run rule,
negative-results-published rule, transport (keyed FRED, env-only key,
redacted endpoints), licence screen. The runner enforces the shared parts
structurally: one constant block, one evaluation path, per-protocol alarm
quantile and scorer list. The frozen constants are pinned by
`test_prereg_runner.py::TestProtocolTableIntegrity` so a silent edit fails
CI.

## 4. Family

Identical dispositions to v2 (same candidates including the pre-fetch
rationales for `T10Y3M`/`VIXCLS`, same exclusions). All skips are
re-derived by the declared rules on a **fresh fetch** into
`data/prereg/v3/` with its own hashed manifest — nothing is skipped from
memory, and the licence screen runs before any download.

## 5. Provenance and credentials

As v2: `FRED_API_KEY` read from the environment at run time, never written
to any file; recorded endpoints carry `api_key=<redacted>`; committed
provenance is CSV bytes + SHA-256. (The key used for this cycle has been
exposed in chat and is to be rotated by the owner afterwards; rotation does
not affect the committed data or hashes.)
