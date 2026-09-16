# Language strategy: what stays in Python, what would earn Rust, what moves to TypeScript

An assessment with measurements, not aesthetics. Benchmarks come from
`scripts/bench_systemic.py` (re-run after touching those loops; update this
doc in the same change). Numbers below: single-threaded CPU container,
re-run 2026-09-15 after the EM change recorded in
[§ The one hot path that was real](#the-one-hot-path-that-was-real-and-what-actually-fixed-it),
`--reps 6`. Earlier figures from the 2026-09-14 run are kept in that section
where they are the comparison being made.

> **This file was deleted on 2026-09-15** by a commit titled *"Document
> language strategy and migration plans"* (`0ecd76f`) whose entire diff was
> 85 deletions of this document. `docs/README.md` still indexed it, and
> `scripts/bench_systemic.py` — added by `8dff9e2` specifically so the numbers
> below could be re-measured rather than trusted — was left in the tree with
> nothing pointing at it. It is restored here from `8dff9e2` and extended. The
> deletion is recorded rather than quietly undone because an unwritten strategy
> is how a language change gets proposed against a codebase nobody measured.

## Measured hot paths

| Loop | Shape | Seconds per call |
|---|---|---|
| Multiplex clearing (Eisenberg–Noe, 3 seniority layers) | n=50 | 0.017 |
| Multiplex clearing | n=200 | 0.097 |
| Multiplex clearing | n=500 | 0.688 |
| Systemic-importance ranking (50 counterfactual clears) | n=200 | 4.88 |
| Coupled fire-sale fixed point (clearing inside price feedback) | n=200 × 20 assets | 0.657 |
| Risk-series inference (batched transformer forwards) | 5 000 windows | 0.669 |
| **Regime nowcast (Student-t HMM, k=2, fit + Viterbi)** | **T=250** | **0.842** |
| **Regime nowcast — the prediction path runs this once per source** | **T=1 000** | **3.349** |
| Regime nowcast, 20 sources sequentially (batching baseline, 2026-09-16 host) | n=20 × T=250 | 29.04 |
| **Regime nowcast, batched over sources (2026-09-16)** | **n=20 × T=250** | **2.82 (10.3×)** |
| Regime nowcast, 20 sources sequentially (batching baseline, 2026-09-16 host) | n=20 × T=1 000 | 111.53 |
| **Regime nowcast, batched over sources (2026-09-16)** | **n=20 × T=1 000** | **10.27 (10.9×)** |

The last row is the newest entry and the only one on the *prediction* path
rather than the scenario path; the previous six are unchanged in character and
differ from the 2026-09-14 run only by host load. It is discussed next, because
it is the one case where the "nothing moves to Rust" verdict was actually tested
by a measured bottleneck — and the verdict held.

## The one hot path that was real, and what actually fixed it

`RealPredictionEngine._regime_label` (`backend/modules/engine/prediction_engine.py`)
fits a two-state Student-t HMM on each source's standardized history and reads
the regime off the Viterbi path. It is called once per source per prediction job,
it is the only loop on that path costing seconds rather than milliseconds, and at
the default `max_iterations=100` it measured **5.264 s at T=1 000**. A 20-source
job therefore paid ~105 s in regime labels, which is inside an order of magnitude
of the decision rule's 10 s monitoring-cycle threshold on its own — so the Rust
question was not hypothetical here. It was asked, and the answer was still no:

| | 2026-09-14 | after | change |
|---|---|---|---|
| Regime nowcast, T=1 000 | 5.264 s | **3.349 s** | **1.57×** |
| Regime nowcast, T=250 | 1.401 s | **0.842 s** | **1.67×** |
| Final log-likelihood, T=1 000 | −3 618.940508 | −3 618.940508 | **bit-identical** |
| `test_hidden_markov.py` + `test_student_t_hmm.py` + `test_property_based.py` | 76.3 s | 44.3 s | 1.72× |

What the cost actually was, in descending order of what it bought:

1. **A redundant forward pass in the innermost loop (fixed, 1.57×).** `_fit_once`
   re-scored the parameters after every M-step so that `history[-1]` would equal
   `log_likelihood` of the returned parameters. But `_forward` returns the
   per-step normalisers and their sum *is* `log p(X)` under the parameters that
   produced them — the identity is already in `_forward`'s docstring. The
   iteration's likelihood was therefore already in hand, and the loop was paying
   two forward passes and one backward pass where one and one suffice. The score
   is now taken once, after the loop, which is the only place the invariant needs
   it. The returned parameters are bit-identical; `history[:-1]` now records the
   likelihoods *entering* each M-step, a one-iteration lag that leaves
   `np.diff(history)` the same sequence of EM improvements. Pinned by
   `test_one_forward_pass_per_iteration_plus_one_final_score`, which counts
   `_forward` invocations and **fails on the pre-fix code** (12 passes for 5
   E-steps, expected 6).
2. **A convergence threshold with the wrong dimensions (fixed, latent).** The
   break tested `improvement < tolerance` with `tolerance=1e-6` *absolute*,
   against an objective that is a log-likelihood summed over `T` observations
   and therefore grows with both series length and the units the data is
   expressed in. At T=1 000 that is a relative tolerance of ~1e-9. It is now
   scaled by the objective. **Honest scope: this is not where the speedup came
   from.** On every dataset tried — Gaussian and Student-t, T=250 to T=20 000,
   random walks and well-separated mixtures — the absolute test also converged,
   and the measured per-iteration tail on the production nowcast (4.5e−2 at
   iteration 50, 1.3e−2 at iteration 99) stays above the scaled threshold too,
   so the production fit still runs its full 100 iterations. The fix removes a
   scale-dependence that would bite on a longer series or a change of units; it
   is recorded as a latent defect closed, not as a win claimed.
3. **The iteration budget is NOT available as a lever (measured, declined).**
   Capping `max_iterations` is the obvious 4× and it was tested rather than
   assumed: across 12 series × 4 caps, reducing 100 → 15/25/40 **flipped the
   returned regime label in 3 of 48 cases** (T=1 060, "stress" vs "calm" at the
   100-iteration fit). A regime label is the input to `NetworkQualityGate`,
   which fails closed on an unseen label, so a cap that moves labels would change
   which predictions are blocked. Declined on evidence, in the same register as
   the Stooq and connector decisions.

The lever that remained was **algorithmic and structural, not linguistic**: the
per-source fits are independent, and the forward/backward recursions are Python
loops over `T` doing `(K, K)` numpy work with K=2 — a shape dominated by
per-timestep numpy overhead, not by arithmetic. Batching the sources into one
`(n_sources, T, K)` recursion amortises that overhead across every source in the
job and was the only change on this path with an order of magnitude in it.

**It has now landed (2026-09-16), as its own change with its own
label-equality test** — exactly what this section required before it could be
built:

* `hidden_markov.fit_viterbi_student_t_batch` runs the *same* recursion with a
  leading source axis: the seeded stream is broadcast (every solo fit restarts
  it, so all sources see identical draws), the EM bookkeeping stays per-source
  (history, scale-relative convergence, freeze after the converging M-step),
  the `nu` solve is the identical scalar `brentq` per (sequence, state), and a
  sequence whose degenerate k-means++ seeding would consume a different stream
  is handed back for solo fitting rather than fitted on a stream its solo fit
  would not have seen.
* `_predict_single` collects the windows during its scoring pass and nowcasts
  them in one batch per window length. `_regime_label` is unchanged and
  remains the per-source fallback, so a batch failure degrades to slow, never
  to different.
* `backend/tests/test_regime_batch_equivalence.py` pins the contract at the
  bar this document set: **exact** Viterbi state-sequence equality against
  solo fits — hence label equality, and a label is the input to
  `NetworkQualityGate`, which fails closed on an unseen label — over a
  deterministic corpus including the production T=1 000 shape, plus
  likelihood-history equality at 1e-8 and the degenerate-seeding fallback.
* Measured with `scripts/bench_systemic.py`'s new
  `bench_regime_nowcast_batched`, sequential and batched legs on the same
  host in the same session (not quoted across hosts): **n=20 × T=250:
  29.04 s → 2.82 s (10.3×)**; **n=20 × T=1 000: 111.53 s → 10.27 s (10.9×)**.
  The absolute seconds are this host's — a 2-CPU sandbox whose solo
  per-source cost at T=1 000 is 5.58 s against the 3.349 s recorded above on
  a quieter one; the ratio is the claim, and it grows with source count
  because the Python loop over `T` is paid once per job instead of once per
  source. The 20-source monitoring cycle that paid ~105 s in regime labels
  when this section was first written now pays one batched pass.

This is the decision rule working as intended rather than being cited at it: a
measured product path crossed into seconds, the migration unit was examined, and
the fix that paid was the one that kept the existing equivalence harness
meaningful. A Rust port of the pre-fix loop would have been a fast
implementation of a redundant forward pass.

## Why nothing moves to Rust today

1. **The hot loops are already vectorized fixed-point iterations.** Clearing
   is a monotone map iterated on `(n, n)` matrices; the fire-sale solver wraps
   it in an outer price loop. The cost is BLAS-level matrix arithmetic, where
   a Rust reimplementation competes with decades-old tuned kernels, not with
   Python overhead. A PyO3 port would move the *iteration bookkeeping* — the
   cheap part.
2. **The workload is scenario-sized, not stream-sized.** A supervisor runs
   hundreds of institutions through a declared scenario interactively; at
   n=500 the whole solve is under a second, and the importance ranking — the
   only quadratic-in-clears loop — is seconds. Latency budgets are human.
3. **The real scaling levers are algorithmic.** If n grows, the first wins are
   warm-starting the fixed point from the previous scenario, tolerance
   scheduling, and pruning negligible liabilities — each worth more than a
   language change, and each testable in place.
4. **Toolchain cost is real.** A Rust extension adds maturin builds, wheel
   matrix, CI runners and a second language review culture to a codebase
   whose auditability is its selling point. That tax must be earned.

## The decision rule (binding)

Re-open the Rust question **only when a measured product requirement** crosses
one of these thresholds, re-benchmarked with `scripts/bench_systemic.py`:

- a single clearing solve > **5 s** at the production institution count, or
- a scenario batch (Monte-Carlo over shocks/margins) > **10 000 solves per
  interactive request**, or
- inference > **10 s** for a 24 h monitoring cycle over the full catalogue.

If crossed, the migration unit is the **clearing kernel plus the fire-sale
outer loop** (they share the liability algebra), exposed via PyO3 with numpy
zero-copy buffers, keeping the Python API and its tests unchanged — the
existing test suite (`test_clearing.py`, `test_fire_sale.py`, hand-computed
fixed points) becomes the cross-language equivalence harness. Until then this
document is the record that the question was asked and measured.

## An external four-language migration proposal, and why it was declined

A 40-week plan was proposed (Go API gateway + Rust gRPC engine + Python ML +
Julia simulation, protobuf contracts, NATS JetStream, ~5.75 FTE, static
multi-arch binaries) in the same week this file was deleted. Its *methodology*
is sound and is not what was declined: parity gates before cutover, shadow
running, per-module feature flags, the strangler-fig pattern, a per-phase exit
ramp, and the split between deterministic-exact and numerical-tolerance outputs
are all correct, and §Test strategy in that proposal is better than nothing. It
was declined because every repo-specific claim in it was checked against this
tree and did not survive:

| Proposal claims | This tree |
|---|---|
| Migrate `/institutions`, `/exposures/latest`, `/risk/scores`, `/regimes/current`, `/scenarios`, `/stream/regimes`, `/stream/risk`, `/predict`, `/version`, `/metrics` | **None of these routes exist.** 115 route decorations across 22 modules, all under `/api/v1/{pipeline,jobs,network,results,reports,catalogue,…}` and `/api/v2/*`; the inventory is *generated* (`scripts/generate_api_docs.py --check` in CI) precisely because a hand-written `api_v2.md` once documented 7 endpoints that did not exist. |
| `/metrics` migrates in week 16; add Prometheus + OpenTelemetry in Phase 2 | Observability was **removed on purpose** on 2026-09-11: *"every Prometheus/Grafana reference is gone from the repository… The only surviving statement is that this API exposes no metrics endpoint."* |
| `canonical_hash` must be bit-exact across the language change; `CanonicalHash` RPC | **No `canonical_hash` exists.** What exists is `canonical_json` / `sha256_bytes` / `hash_frame`, and `snapshots.py` states its content hash uses `pandas.util.hash_pandas_object` and is *"deliberately not claimed to be stable across major pandas upgrades"* — the durability guarantee is the persisted byte-for-byte copy, so "bit-exact across a reimplementation" is not a property this codebase has to preserve. |
| Phase 4 ports Monte-Carlo contagion, NSS projections and NGFS scenarios to Julia | **No Monte-Carlo contagion, NSS, NGFS or climate module exists** anywhere in `backend/`. |
| Python ML service keeps the Toto 2.0 foundation encoder | **Deleted** in the 2026-09 hygiene round with its dependency train; see the `REMOVED` register in `test_reachability.py`. |
| Add Stooq, Bank of England, OpenFIGI, EBA risk dashboard, Yahoo Finance, BIS, IMF, World Bank, FDIC, SEC, FRED, Alpha Vantage | Nine of those are **already plugins**. Stooq was **rejected on evidence this same week** (anti-bot challenge page, HTTP 200 carrying HTML). BoE, OpenFIGI and the EBA dashboard are **already deferred with named preconditions** in `docs/README.md`. |
| Add `docker-compose.simple.yml` | **Already proposed and declined** in `docs/README.md`: a third compose variant multiplies what CI must keep valid without a deployment scenario the two existing files do not cover. |
| Replace Celery + Redis with NATS JetStream | Redis is also the **WebSocket relay** between worker and API process (`docs/frontend.md`), so this is a two-subsystem change, not a broker swap. |
| LOC estimates: `causal_discovery` ~500 Rust, `hidden_markov` ~700, `fractional` ~400, `cpcv` ~200, "contagion engine" ~600 | Actual Python: **2 263**, **1 353**, **863**, **335**, and the contagion stack (`risk/{clearing,fire_sale,liquidity_spiral,bank_analyzer,regulatory,network_estimation}` + `engine/multiplex`) is **~6 100**. `fractional.py` and `quality_gate.py` are in `modules/data/`, not `modules/engine/`. |
| Phase 1 ports KPSS, fractional differencing and CPCV as the highest-ROI kernels | Measured: **KPSS 0.07 ms**, ADF 1.52 ms, `frac_diff_ffd` 4.69 ms, CPCV enumeration **0.88 ms** at n=1 000 — and all of it runs inside Celery tasks, not the HTTP request path, so no API latency target can move. The proposed `Kpss` RPC would serialise 5 000 doubles to do 0.07 ms of work. |
| p95 API latency −40 % / −60 %, cold start −70 %, image size ~3 GB → ~1 GB | No baseline for any of these exists (the proposal's own table says "Measure"), and the endpoints that would carry them are DB reads. Deployment is **one node** — `docs/deployment.md` §1 rejects orchestration on that evidence — reached over Wi-Fi, with a bearer-token gate and multi-user explicitly out of scope. |

Two further reasons are structural rather than factual. The proposal would port
modules without checking whether anything calls them, which is the exact defect
`test_reachability.py` exists to prevent and has caught three times. And it
never mentions the fourth-round quant review, which reproduced five P0
defects in the live ML path the day before and concludes that the binding
constraint is a **missing target definition** — *"risk of what, measured how, over what horizon,
labelled from which observable?"* Making an undefined target fast is not
progress.

If a version of this proposal returns, the parts worth keeping are its test
strategy and its exit ramps. The parts that need re-deriving are its endpoint
list, its module list, its LOC estimates and its success metrics, all of which
should come from `docs/api-endpoints.md`, `test_reachability.py` and
`scripts/bench_systemic.py` rather than from recollection.

## What does move: TypeScript, in phases

The frontend's failure modes were type-shaped (payload-envelope drift,
`undefined%` rendering, wrong field names surviving four review rounds). The
migration was phased and ratcheted — new code is `.ts`, existing modules convert
when touched. It is complete: **zero `.js`/`.jsx` modules remain under
`frontend/src`.**

1. **Phase 1 (done, 2026-09):** `src/utils/apiClient.ts` — the single HTTP
   client with typed generics and the envelope normaliser; `tsconfig.json`
   with `strict: true`; `npm run typecheck` in CI. Zero `.js` modules may add
   new fetch logic.
2. **Phase 2 (done, 2026-09):** every hook (`useApi`, `useJobsWebSocket`,
   `useDataQuality`, `useAnalytics`, `useCountries`, `useNotifications`) is
   `.ts` and returns typed responses. The response types were not generated
   from `/openapi.json` as originally sketched; they are hand-derived in
   `src/types/api.ts` from the generated endpoint inventory
   (`docs/api-endpoints.md`) and from every field the UI actually reads, so
   envelope and field-name drift is a compile error rather than an e2e
   surprise. The hand-derivation is itself machine-checked:
   `backend/tests/test_frontend_contract.py` parses every typed
   `fetchApi<T>`/`fetchJson<T>` call and asserts the bound interface's
   fields all exist on the response schema in the app's own `app.openapi()`
   (the schema `docs/api-endpoints.md` is generated from), recursing into
   nested interfaces, with a two-entry allowlist for the WebSocket payload's
   alternate spellings. A backend field rename now fails the nightly suite
   naming the type and field, instead of surfacing as `undefined` in a
   browser. If a generator is added later, `src/types/api.ts` is the file it
   must replace — and the contract test is what it must keep passing.
3. **Phase 3 (done, 2026-09):** every page, component and entry point is
   `.tsx` — not one route per PR but one migration to close the ratchet,
   because the incremental batches (PR #64 and its predecessors) had already
   converted the UI kit, layout and stores, and leaving eleven pages in
   untyped JS kept the exact failure modes the migration exists to kill.
   `tsconfig.json` no longer carries `allowJs`, so a new `.js` module in
   `src/` is not merely unchecked, it is invisible to the compiler.

JavaScript stays where it is honest: config files (`vite.config.js`,
`tailwind.config.js`, `playwright.config.js`) and the Playwright spec — tooling
and tests, not the shipped app.

## What is not on the table

- Rewriting the data pipeline in another language: it is I/O- and
  governance-bound (attestations, typed failures, PIT vintages), and Python
  expresses that contract with the least ceremony.
- Moving storage logic out of TimescaleDB: hypertables, continuous aggregates
  and point-in-time vintages are the right tool and already carry the load.
- Any language change without the equivalence harness above: the repo's rule
  that a claim needs an independent check applies to performance claims too.
