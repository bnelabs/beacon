# Language strategy: what stays in Python, what would earn Rust, what moves to TypeScript

An assessment with measurements, not aesthetics. Benchmarks come from
`scripts/bench_systemic.py` (re-run after touching those loops; update this
doc in the same change). Numbers below: single-threaded CPU container,
2026-09-14, `--reps 6`.

## Measured hot paths

| Loop | Shape | Seconds per call |
|---|---|---|
| Multiplex clearing (Eisenberg–Noe, 3 seniority layers) | n=50 | 0.018 |
| Multiplex clearing | n=200 | 0.130 |
| Multiplex clearing | n=500 | 0.838 |
| Systemic-importance ranking (50 counterfactual clears) | n=200 | 6.64 |
| Coupled fire-sale fixed point (clearing inside price feedback) | n=200 × 20 assets | 1.05 |
| Risk-series inference (batched transformer forwards) | 5 000 windows | 1.49 |

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

## What does move: TypeScript, in phases

The frontend's failure modes were type-shaped (payload-envelope drift,
`undefined%` rendering, wrong field names surviving four review rounds). The
migration is phased and ratcheted — new code is `.ts`, existing modules convert
when touched:

1. **Phase 1 (done, 2026-09):** `src/utils/apiClient.ts` — the single HTTP
   client with typed generics and the envelope normaliser; `tsconfig.json`
   with `strict: true`; `npm run typecheck` in CI. Zero `.js` modules may add
   new fetch logic.
2. **Phase 2:** hooks (`useApi`, `useDataQuality`, `useAnalytics`,
   `useCountries`, `useNotifications`) converted alongside response types
   generated from the backend OpenAPI schema (`/openapi.json`), so envelope
   and field-name drift becomes a compile error rather than an e2e surprise.
3. **Phase 3:** page components, one route per PR, starting with the
   data-quality and analytics dashboards (the pages whose payloads crashed
   under wrong shapes in testing).

JavaScript stays where it is honest: config files, the Playwright spec, and
unconverted legacy modules during the ratchet.

## What is not on the table

- Rewriting the data pipeline in another language: it is I/O- and
  governance-bound (attestations, typed failures, PIT vintages), and Python
  expresses that contract with the least ceremony.
- Moving storage logic out of TimescaleDB: hypertables, continuous aggregates
  and point-in-time vintages are the right tool and already carry the load.
- Any language change without the equivalence harness above: the repo's rule
  that a claim needs an independent check applies to performance claims too.
