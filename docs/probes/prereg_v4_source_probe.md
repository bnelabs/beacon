# Source probe — v4 early-warning candidates (BIS credit gap, BIS DSR, ECB CISS)

**Executed:** 2026-09-18 · **Discipline:** criteria below were written before
any request; findings are recorded verbatim against them. Polite probing:
single-operator requests, default timeouts, no retries beyond one per URL,
user-agent identifies the probe.

Protocol context: the v3 record parks the early-warning line with two
**recorded v4 axes** — rolling refits, and weekly/monthly tracks admitting the
credit-gap family. This probe answers one question before any protocol is
drafted: *are the credit-gap family (BIS) and the weekly stress indices (ECB
CISS) fetchable keyless, with histories long enough to train pre-2007 and
evaluate 2007–2024, under licences that permit committing them as provenance?*

## Pre-written criteria (frozen before probing)

**P1 — BIS credit-to-GDP gap (US, quarterly).**
GREEN: keyless SDMX/REST fetch succeeds; US series; quarterly; first
observation ≤ 1995 (≥ 12 years of pre-2007 training span); data runs to
≥ 2024. YELLOW: fetchable but shorter training span or stale end. RED: no
keyless structured endpoint, or terms prohibit reproduction.

**P2 — BIS debt service ratio (US, quarterly).** Same thresholds as P1.

**P3 — Licence (BIS).** The copyright/terms page is read in full and quoted.
GREEN: reproduction permitted with attribution. RED: prohibition patterns
matching the runner's `LICENCE_PROHIBITION_RE` class (reproduction prohibited
/ internal use only / prior written permission required).

**P4 — ECB CISS (euro area, weekly).** GREEN: keyless data-API fetch of the
headline CISS level series; weekly; first observation ≤ 2000 (≥ 7 years of
pre-2007 training span); runs to ≥ 2024; licence permits reproduction with
attribution. RED: key required, no structured endpoint, or licence prohibits.

**Disposition rule (declared now):** only GREEN sources may enter the v4
family. A YELLOW source may enter only if the protocol document explicitly
declares the shortfall and its consequence before the freeze. A RED source is
recorded as a licence/availability skip — no substitute is improvised (the v1
CISS-on-FRED precedent).

## Findings

*(recorded after execution, verbatim; ~14 requests total, 2026-09-18, UA
`BEACON-source-probe/4.0`)*

**P1 — BIS credit-to-GDP gap: GREEN.** `GET
https://stats.bis.org/api/v1/data/WS_CREDIT_GAP/Q.US?format=csv` → HTTP 200,
40,637 bytes, no authentication. Three `CG_DTYPE` variants for the US:
`A` (47.06 → 139.68) and `B` (68.75 → 151.00) are credit-to-GDP *levels*;
**`C` is the gap** (0.7754 in 1957-Q4 → −11.3204 in 2026-Q1), 274 quarterly
observations, 1957-Q4 → 2026-Q1. Training span pre-2007: ~197 quarters
(≥ 12 years ✓). Full SDMX key: `Q.US.P.A.C.E` (FREQ, BORROWERS_CTY,
TC_BORROWERS=private non-financial, TC_LENDERS=all, CG_DTYPE=gap,
COLLECTION). The dataflow listing (`/api/v1/dataflow`, 200) confirms flows
`WS_CREDIT_GAP`, `BIS_CREDIT_GAP`, `WS_DSR`, `BIS_DSR`.

**P2 — BIS debt service ratio: YELLOW.** `GET
https://stats.bis.org/api/v1/data/WS_DSR/Q.US?format=csv` → HTTP 200,
24,834 bytes, keyless; variants `H` (9.5), `N` (43.0), `P` (16.3, the
private-sector DSR the literature uses). **First observation 1999-Q1** —
fails the frozen ≤1995 criterion: only ~32 quarters of pre-2007 training
span, below any honest fit for the frozen model class (the TAN's
`sequence_length` alone is 30 steps). Per the declared disposition rule,
YELLOW may enter only with the shortfall declared pre-freeze; a 32-row
training span cannot train the declared architecture, so **DSR is excluded
from the v4 family and the exclusion is recorded here and in the protocol**
— an availability skip, not a licence skip. (`BIS_DSR/Q.US` → 404; the WS_
flow is the live one.)

**P3 — BIS licence: GREEN.** `GET https://data.bis.org/help/legal` → 200.
Verbatim: *"The use of the statistics is unrestricted, provided that: if the
statistics are reproduced, the BIS must be cited in your publication or
product as the source of the statistics; … your use of the statistics must
not be potentially misleading, for example by implying endorsement or
affiliation with the BIS …"* No pattern of the runner's
`LICENCE_PROHIBITION_RE` class appears. Attribution line to carry in the
manifest: "Source: BIS Data Portal — Bank for International Settlements".
(`bis.org/about/copyright.htm` and `data.bis.org/content/terms-use` are 404s;
`data.bis.org/help/legal` is the live page.)

**P4 — ECB CISS: RED.** `GET
https://data-api.ecb.europa.eu/service/data/CISS?detail=serieskeysonly` →
200 but **mis-resolves**: the payload's `structureRef` is `ECB_FMD2` and all
60 returned series are daily/monthly equity-index keys
(`PROVIDER_FM=4F, INSTRUMENT_FM=EC, DATA_TYPE_FM=IDX`); the string "CISS"
appears zero times in the response. `ECB_CISS1` → 404. The legacy host
`sdw-wsrest.ecb.europa.eu` does not connect. ECB copyright pages probed
(`/legal/copyright/…`, `/copyright/…`, portal `/content/copyright`) all 404.
Per the disposition rule and the v1 CISS-on-FRED precedent: **recorded as a
fetch failure; no substitute improvised.** The weekly track proceeds on the
two FRED-served weekly indices whose directions are already declared in the
registry (STLFSI4, KCFSI); CISS stays in the registry, unfetchable, and its
skip is recorded in the v4 manifest like every other.

**Disposition summary:** credit gap (quarterly track) GREEN → enters the v4
family as `BIS_CREDIT_GAP_US` with direction declared pre-fetch. DSR YELLOW →
excluded, reason recorded. CISS RED → fetch-attempted, skip recorded. Weekly
track = STLFSI4 + KCFSI (keyed FRED, licence-screened at fetch as in v2/v3).

