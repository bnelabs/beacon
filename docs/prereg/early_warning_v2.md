# Pre-registered early-warning evaluation — protocol v2

**Status: FROZEN, pending run.** This document plus
[`configs/event_eval_v2.yaml`](../../configs/event_eval_v2.yaml) is the v2
pre-registration. Owner sign-off: given in chat on 2026-09-17 (the owner
supplied the FRED API key that unlocks the v2 transport, approving the v2
plan as presented: same criteria, better-powered family). Both files are
committed and git-tagged `prereg-early-warning-v2` **before** the
evaluation runs; after the tag, any change requires protocol v3 plus a
CHANGELOG entry saying what changed and why.

## 1. Why v2 exists — and what v2 is NOT

v1 ran, and its published verdict was **NO** — with the diagnosis written
into the report: only one indicator survived the declared data-availability
rules, below the minimum testable family of 3, and that indicator
(10y–2y spread) is not among the variables the crisis-prediction literature
documents as strong. The test was under-powered **by construction**.

v2 fixes the diagnosed flaw and **nothing else**. It is explicitly not a
retry with softer rules:

- **Changed:** the family (two literature-backed daily series added), a
  licence-screening skip rule, keyed FRED transport with credential
  redaction.
- **Unchanged, frozen since before v1's run:** all four pass criteria, the
  labelling parameters (q95, horizon 21, persistence 5), the alarm rule
  (q95 of scores), the model (same tiny TAN, same seed 11), the windows
  (train ≤ 2006, evaluate 2007–2024), the baselines (persistence, AR(1)),
  the permutation test (1000 shuffles, seed 20260917), Holm–Bonferroni at
  0.05, the minimum family of 3, the single-run rule, negative results
  published unchanged.

The runner enforces the "unchanged" list by construction: one shared set of
constants and one shared evaluation path serve every protocol version.
Adjusting a criterion *after seeing v1's numbers* would be moving
goalposts; v2 does not, and the code makes it structurally hard to do
silently.

## 2. Family v2 (frozen before any v2 fetch)

Candidates (the fetch rules re-derive every skip; nothing is pre-skipped
from memory): the six v1 public candidates **plus**

| Code | Series | Declared rationale (predates any v2 fetch) |
|---|---|---|
| `FRED_T10Y3M` | 10y − 3m Treasury spread | the short-end curve spread the recession literature documents (Harvey et al.; Engstrom); public domain; full history from 1982 |
| `FRED_VIXCLS` | CBOE VIX close | the standard equity-stress gauge; served by FRED "reprinted with permission", no reproduction prohibition (notes checked 2026-09-17); full history from 1990 |

Both were added to the semantics registry with directions (`T10Y3M`: −1,
falling/inverting = stress, same convention as `T10Y2Y`; `VIXCLS`: +1)
before any data was examined.

Exclusions carried from v1 (owner decision + operator-reported codes with
no public source) are unchanged; `FRED_RRPONTSYD` remains owner-excluded.

**Licence screening (new rule, applied before download):** each candidate's
own FRED series notes are read; any terms prohibiting reproduction or
redistribution skip the series (`licence_prohibits_reproduction`). The
repository commits fetched series as provenance, so committing prohibited
data would make the provenance store itself the violation. This is not
hypothetical: the ICE BofA terms for `BAMLH0A0HYM2` say exactly that, and
v1's keyless capture of its 3-year window was removed when the fact was
established (`data/prereg/REMOVAL_NOTE.md`). Recorded manifest fields
include the series' licence lines, so every screening decision is
auditable.

## 3. Transport and credentials

v2 fetches through the platform's own `fred_plugin` with `FRED_API_KEY`
read from the **environment at run time**. The key is never written to any
file: recorded endpoints carry `api_key=<redacted>`; the committed
provenance is the CSV bytes plus their SHA-256 hashes, which do not depend
on the credential. (The key supplied for this run has been exposed in chat
and should be rotated by the owner afterwards; rotation changes nothing
about the committed data or hashes.)

## 4. Everything else

Windows, labelling, scoring, model, baselines, criteria, family verdict
rules, run rules and the declared episode family are **identical to v1** —
see [`early_warning_v1.md`](early_warning_v1.md) sections 3–5 and
`configs/event_eval_v1.yaml`. v2 does not restate them so that there is
exactly one frozen definition of each; the runner reads one shared
constant block for both versions.

## 5. What v2 can and cannot conclude

- A pass by ≥ half of a testable family of ≥ 3 daily indicators would move
  the README claim gate **for those indicators, at these settings** — the
  claim wording would carry the run's numbers and provenance.
- A fail is published unchanged, and would be a substantially better-powered
  NO than v1's: three literature-relevant daily series across 18 years,
  graded against frozen criteria. At that point the honest readings are
  about the model class and labelling design (frozen tiny model; endogenous
  quantile labels), which are declared v3 axes — never about the rules.
- Either way, the low-frequency tracks (weekly/monthly indicators like
  STLFSI4, KCFSI, and the BIS credit-gap family the literature favours)
  remain unbuilt: they need a declared resampling/step design, which is v3
  work and is not improvised here.
