# G-SIB Grade Build — Response to the Comprehensive Review

This document records what was actually done in response to the external
quantitative review of BEACON: which of its claims were already true of the
codebase, which were stale, which were correct, and what was built because of
them. It is written to be checkable rather than persuasive — every claim below
names the file or test that supports it.

---

## 1. Audit: the review is directionally right, and about half its "immediate fixes" were already done

Before writing any code, each concrete claim in the review was checked against
the tree. Several were already satisfied, and the review's own premise ("the
module was designed around MOMENT") had been superseded before it was written.

| Review claim | Verdict | Evidence |
|---|---|---|
| Static conformal → **add Adaptive Conformal Inference** | Already done | `AdaptiveConformalInference` in `backend/modules/engine/conformal.py`, Gibbs–Candès update rule, drift tests in `test_conformal.py` |
| **Rewrite the encoder for Toto 2.0** (hidden states, drop MOMENT) | Already done | `TotoEncoder` hooks the `transformer` trunk, pools patch positions, flattens variates (`foundation_encoders.py`); provenance is `kind='forecast'`; loads from a local folder only |
| **Strip ghost MOMENT / TimesFM paths** | Already gone | No import and no load path. The surviving mentions are prose in `foundation_encoders.py` recording why each was rejected (TimesFM on licence grounds) |
| **Strip ghost `model_type="HGT"` / `MultiScaleGNN`** | Already gone | No live branch accepts either. The surviving occurrences are comments in `models.py`, `orchestrator.py` and `job_tasks.py` explaining the removal |
| **Gaussian HMM tails → Student-t / generalized hyperbolic** | Correct, and now fixed | See §2.1 |
| **Couple clearing × fire-sale** | Correct — and worse than stated | See §2.6 |
| Neural SDE for stochastic volatility | Correct, and now added | See §2.7 |
| NOTEARS / causal discovery for TNCM-VAE | Correct, and now added | See §2.4, §2.5 |
| Persistence images / landscapes | Correct, and now added | See §2.3 |
| "Any remaining `ffill` outside PIT" | Half right | No `ffill` in the model path, but two real `fillna(0)` fabrications existed. See §2.8 |
| numpy / scipy version hazard from `momentfm` | Moot | The repository is already on `numpy==2.5.3` / `scipy==1.18.1` and `momentfm` is gone |

### Two findings the review missed

1. **The fire-sale module was orphaned, not merely decoupled.** `LiquiditySpiralModel`
   was referenced only from its own module and from tests. Its docstring claimed
   it "composes with the clearing engine", but nothing in `backend/modules/`
   imported it. BEACON was not computing a liquidity spiral in production at all.
   The review credited it as an active channel.

2. **`TNCM-VAE` was orphaned too.** The same check showed the counterfactual
   module referenced only by its own tests. The review described it as a shipped
   capability.

3. **Two places invented a number where none was observed** — the exact failure
   the point-in-time store exists to prevent. Neither is `ffill`, so a grep for
   `ffill` would not have found them. See §2.8.

---

## 2. What was built

### 2.1 Student-t HMM emissions (`backend/modules/engine/hidden_markov.py`)

`GaussianHMM` under-assigns probability to extreme observations, so the state that
should light up in a crisis does not. The failure is directional — always an
*under*-reaction — so it cannot be excused as conservative.

`StudentTHMM` is a sibling class, as the Gaussian class's own docstring required:
the name records the emission law, so nothing downstream can mistake a Gaussian
fit for a heavy-tailed one. It reuses the entire log-space forward/backward
machinery, the Viterbi recursion, the restarts and the state labelling, and
overrides only the two emission-specific steps. The shared transition and initial
updates were extracted into `_update_transition` / `_update_initial` rather than
duplicated, so there is one definition of each.

The Student-t is a Gaussian scale mixture, so the E-step stays closed-form: the
latent scale enters as a per-observation weight `u_tj = (nu_j + d) / (nu_j + delta_tj)`.
Degrees of freedom are **fitted** per state by EM, not assumed — fixing `nu` would
turn the model's central claim into an assumption rather than a result.

**A real bug was found and fixed during implementation.** The first version used
`log(E[u])` in the degrees-of-freedom update. The posterior of the latent scale is
Gamma, so `E[log u] != log(E[u])`; substituting the latter inflates the implied tail
weight and drove `nu` to the Gaussian bound on data that were genuinely
heavy-tailed. The independent check that caught it — a one-state fit compared
against `scipy.stats.t.fit`, which is a completely separate optimiser for the same
maximum-likelihood problem — is now a permanent test.

Verification routes, none of which compares the implementation against itself:
the univariate density against `scipy.stats.t.logpdf`; the multivariate density
against numerical integration of its own scale-mixture definition (the only
available check on the normalising constant when there is more than one feature);
the Gaussian limit, which the Student-t must reproduce; the one-state fit against
`scipy.stats.t.fit`; and the headline claim itself — on fat-tailed simulated data
the Student-t model achieves a strictly higher observed likelihood than the
Gaussian model on the same data.

**Limitations, stated in the module:** symmetric tails only (no skew-t, no
generalized hyperbolic); diagonal scale only; `nu` floored above 2 so the
infinite-variance regime is excluded and `variances` always means variance; the
`nu` step maximises the expected complete-data likelihood, not the observed one.

### 2.2 Basel III regulatory simulators (`backend/modules/risk/regulatory.py`)

LCR, NSFR and leverage ratio, plus `translate_systemic_stress`, which consumes the
existing `ClearingResult` and an explicit price decline and produces per-institution
before/after ratios. Every rate, factor and threshold is a named module-level
constant; no magic number is buried in code.

The stress accounting is a **stated simplification**, not the only defensible
treatment: losses reduce Tier 1 and the exposure measure one-for-one and are met in
cash from HQLA through a Level 1 → 2A → 2B waterfall. Funding categories are held
unchanged, because inventing a behavioural re-run-off would be fabrication.
Post-stress NSFR and leverage return `None` when their denominator hits zero, and
`None` counts as a breach — an undefined ratio is not evidence of compliance.

**Limitations:** no LCR by significant currency; no Basel IV output floor, buffers
or TLAC; the ASF/RSF category set is a documented subset with only a below/above
one-year maturity split; no Level 2B 15% sub-cap; central bank reserves treated only
as Level 1; no intraday liquidity; derivative exposure is caller-supplied rather
than computed by SA-CCR.

### 2.3 Persistence vectors (`backend/modules/engine/persistence_vectors.py`)

`persistent_homology.py` computed only summary statistics. This adds the full
topological signature as a **fixed-width** feature vector — the shape a model can
consume — combining persistence landscapes, persistence images and the existing
summary block.

The filtration is the edge-threshold filtration on the **1-skeleton**, deliberately
not the Vietoris–Rips flag complex: a flag complex fills a triangle the instant it
closes, giving zero persistence, whereas the point is that a closed triangle is one
H1 cycle. `persistent_homology.py` was left untouched; the new module imports its
`merge_levels` and `UnionFind` helpers and `_edges` so there is exactly one
definition of the filtration in the codebase.

The property that motivates the module is asserted directly: adding a short-lived
(near-diagonal) feature moves the vector by a small amount, adding a long-lived one
moves it substantially, and the movement is monotone in lifetime.

**Limitations:** H0 and H1 only, so no higher-dimensional voids; not a flag complex;
grid, resolution, sigma and weighting are conventional choices with no data-driven
selector, so the vector is genuinely parameter-sensitive; persistence images are not
injective; no statistical significance test for any coordinate.

### 2.4 Causal discovery (`backend/modules/engine/causal_discovery.py`)

NOTEARS (Zheng et al. 2018) — least-squares loss with an L1 penalty under the
acyclicity constraint `h(W) = tr(exp(W ∘ W)) - d = 0`, solved by augmented
Lagrangian around L-BFGS-B, with the analytic constraint gradient verified against
central finite differences. Plus a constraint-based baseline, explicitly named
`PartialCorrelationSkeleton` and documented as **not** the PC algorithm (no Meek
rules), so the NOTEARS result has an independent route to compare against.

The deliverable is `compare_dag`, which reports `declared_only`, `learned_only` and
`orientation_conflicts` and distinguishes the two severities: a `learned_only` edge
means the declared DAG may be **under**-specified, leaving an open confounding path
that silently invalidates counterfactuals; a `declared_only` edge means it is
**over**-specified. Both are model risk, but they are not the same model risk.

Implementation findings worth recording: z-scoring the columns **breaks** recovery
(it rescales each column's residual and violates the equal-noise-variance
assumption, inverting recovered colliders), so `standardize=False` is the default
and that is a correctness fix rather than a tuning preference. Separately, the L1
penalty — not the optimiser — can be why a true DAG is not recovered: at a large
enough penalty a wrong sparse graph has a genuinely lower penalised objective, so
no solver could return the truth.

**Limitations:** linear structural equations with equal-variance additive noise;
orientation identified only up to the Markov equivalence class; no latent
confounders (this is not FCI); no principled selector for the sparsity penalty;
local optima only.

### 2.5 Declared-structure validation (`backend/modules/engine/causal_validation.py`)

This is the seam that makes §2.4 and `tncm_vae.py` useful together.
`StructuralCausalModel` states in its own docstring that nothing validates its
declared structure, so a counterfactual from a wrong DAG is wrong in a way that
reads exactly like being right.

`counterfactual_with_validation` compares the declared structure against the one
the data support and, when they materially disagree, **refuses to report a
counterfactual** rather than reporting one with a caveat — a number that reaches a
decision-maker tends to be used regardless of the footnote attached to it. A caller
who has read the discrepancy can proceed with `accept_structure_risk=True`, and
that fact is carried in the returned object so an accepted risk and an unexamined
one cannot look alike downstream.

Agreement is explicitly **not** reported as validation; the result object carries an
`agreement_is_not_proof` flag so "not contradicted at this sparsity" cannot be
inflated into "validated". The declared variable order is enforced by reindexing, so
a frame whose columns happen to be in another order cannot silently produce a
counterfactual over permuted variables.

### 2.6 Coupled fire-sale equilibrium (`backend/modules/risk/fire_sale.py`)

The review's second "immediate fix", and it closes a real hole: `clearing.py` answered
*who* fails at fixed prices, `liquidity_spiral.py` answered *how far prices must fall*
for one holder's deleveraging, and the two never spoke. The mechanism that turns a
solvency problem into a systemic one lives in the gap between them.

The solver iterates one round at a time: mark capital to current prices; clear through
the existing `MultiplexClearingEngine`; derive a liquidation demand from the clearing
shortfall and the margin constraint; execute it; move prices by aggregate cumulative
sales; test a dimensionless convergence delta. Divergence is reported **as divergence** —
a price driven through zero, or a round cap reached, returns `diverged=True` with a
machine-readable reason and `final_prices=None`, never a silently clamped answer.

Reuse was a requirement and is honoured where it matters: clearing is the real engine,
margin is the real `SpiralParameters.margin_for`, and the per-round stability diagnostic
is the real `stability_impact_limit` (lambda*). The one deliberate exception is
documented rather than hidden: `LiquiditySpiralModel.cascade` is *not* called inside the
loop, because it solves a single-holder problem with that holder's own price impact and
applying it per holder would attribute the whole market move to every seller. Instead a
test proves the margin channel reaches the **identical** fixed point as `cascade`
(relative 1e-9), so the two cannot drift apart unnoticed.

The number a regulator actually wants is in the amplification block: re-solving the same
scenario at price impact zero isolates the shortfall attributable to the feedback, and
`feedback_caused_defaults` names the institutions that survive at zero impact and fail
only because of the spiral.

Verification includes a fully hand-computed example (a holder of 10 units at price 10
owing 150 converges in exactly three rounds; prices 10 → 7.5 → 5, shortfall 50 → 62.5,
asserted as exact numbers), a fixed-point recheck that re-running one clearing step at
the final prices reproduces the same payments, and a divergence case at lambda = 1.2
against lambda* = 0.1765.

**Limitations, stated in the module:** the fixed point may be **non-unique** and the
solver reports only the one it finds from the given initial condition — flagged in the
module as the single most important caveat; no strategic or anticipatory behaviour; no
new lending and no central-bank intervention; no bankruptcy or resolution costs; linear
constant-depth price impact with no depth dynamics or recovery; no cross-asset
substitution or externality pricing; no intraday sequencing; and the price-impact-zero
run is an *isolation* counterfactual (the initial shock is still applied), not a
no-crisis counterfactual.

**Wired into the engine, not left as a library.** `BankRiskAnalyzer.analyze_multiple_banks`
accepts an optional `fire_sale_scenario`; when supplied it is solved and attached to
`MultiBankAnalysis.fire_sale`, and `prediction_engine`'s multi-institution report renders
the outcome — including DIVERGED and the feedback-caused default set — falling back to an
explicit "UNAVAILABLE — holdings, prices and capital were not supplied" rather than
implying the feedback is absent. A scenario covering a different institution set than the
analysis raises instead of being silently aligned.

### 2.7 Neural SDE latent dynamics (`backend/modules/engine/neural_sde.py`)

`dz = f(z, t) dt + g(z, t) dW`, with Euler–Maruyama and Milstein integrators, a
diagonal diffusion parameterisation that guarantees a positive coefficient,
antithetic sampling, and a memory class matching the interface the temporal graph
consumes. The deterministic Neural ODE remains available; this is an alternative,
not a replacement.

Measured evidence, not a claim: on geometric Brownian motion, which has a known
exact solution, Euler–Maruyama's strong error falls at the expected order-0.5 rate
(0.490, 0.494, 0.498 across step refinements) while Milstein's falls at order ~1
(0.940, 0.949, 0.975), and Milstein is more accurate at every step size — about
28x more accurate at the finest grid. The Milstein rate sits slightly below the
asymptotic 1.0, and the test says so rather than asserting the textbook number.

**The most important limitation, stated plainly in the module:** a diffusion is
continuous, so it **cannot produce jumps**. The review's framing — that stochastic
volatility is the missing channel — is served, but the fat tails a crisis needs are
only partly served, and a true jump-diffusion would be required for genuine jumps.
Also stated: strong rather than weak convergence orders; fixed step size with no
adaptive control, which can be badly wrong in stiff regions; the diagonal diffusion
cannot express cross-coordinate correlated noise; and no calibration of the SDE to
data is provided.

### 2.8 Removed fabrications

Two places wrote a number where none had been observed:

- `backend/modules/data/formatter.py` — a seven-day rolling standard deviation was
  `fillna(0)`, writing "volatility is exactly zero" for the first row of every
  series. It now stays genuinely missing.
- `backend/modules/results/generator.py` — un-readable `market_liquidity` entries
  became `0.0`, which on a liquidity chart reads as a total seizure, the most
  alarming possible reading, invented from a parsing failure. Un-readable entries are
  now dropped, and timestamps and values are filtered by the same mask so they cannot
  drift out of alignment.

### 2.9 Cross-currency FX swap layer (`backend/modules/engine/multiplex.py`)

Two distinct constructs, kept deliberately apart:

- `build_fx_swap_exposure_layer` builds an **EXPOSURE** layer, because a currency
  swap is a contractual obligation. It is clearing-eligible.
- `build_fx_basis_layer` builds a **CO_MOVEMENT** layer, because a basis is a
  *price*, not a promise. Two institutions funded in the same at-risk currency are
  exposed to the same squeeze; neither owes the other anything.

`require_exposure` refuses the basis layer, and that refusal is asserted directly in
the tests. Running a clearing algorithm on a price is the exact category error this
codebase was rebuilt to remove.

The exposure is `sum_c share_ic * f(basis_c)` with the basis indexed by **funding
currency**, and in the default mode only the dollar-squeeze direction counts — a
negative basis is the stress sign, and a basis in the other direction is not
evidence of a squeeze and is not counted as one. A missing basis for a non-zero
### 2.10 Feeding the systemic modules (`backend/modules/risk/bank_analyzer.py`)

The three modules above began as engine-level capabilities with no route into the
analysis pipeline. Wiring them in meant either extending the caller's input contract
or inventing the inputs — and inventing them would have produced an infinite LCR for
every institution and a crowding score of exactly zero, plausible-looking numbers
manufactured from absence. So the contract was extended instead, and every input
fails closed.

`BankRiskAnalyzer.analyze_multiple_banks` now accepts five optional arguments:

| Argument | Feeds | When absent | When invalid |
|---|---|---|---|
| `regulatory_states` | `regulatory.py` | `regulatory_stress` stays `None` | must cover *every* analysed institution; a partial table raises, because omitting one reads as though it were unaffected |
| `price_decline` | `regulatory.py` | pre-stress ratios only, and the report says so | propagates into the translation |
| `holdings` | `portfolio_overlap.py` | `crowding` stays `None` | a NaN raises under the fail-closed policy rather than becoming a zero position; an institution outside the analysis raises |
| `concentration_threshold` | `portfolio_overlap.py` | the correlated-unwind measure is not computed | — |
| `topology_parameters` | `persistence_vectors.py` | `topology` stays `None` | requesting topology with no exposure network raises, since a signature of a network that was never built is a number without a subject |

The multi-institution report renders each of them and names plainly which are
unavailable and why, rather than leaving a blank a reader could take for zero.

**This work also caught a bug in itself, which is worth recording because the suite
did not.** During development the fire-sale call was accidentally placed inside the
topology branch, so a supplied scenario was validated and then silently ignored
unless topology was requested too — and every existing test still passed. The
regression test that now guards it asserts that a supplied input *produces a
result*, not merely that the call does not raise.

---

## 3. Verification

Run from the repository root:

```bash
PYTHONPATH=. /home/komedi/Denemeler/beacon-venv/bin/python -m pytest backend/tests -o addopts='' -q
/home/komedi/Denemeler/beacon-venv/bin/python -m ruff check backend --select E9,F63,F7,F82
```

Last recorded result: **1655 passed, 8 skipped**, ruff clean.

New test files added by this work, and what each is anchored to:

| Test file | Tests | Anchored to |
|---|---|---|
| `test_causal_discovery.py` | 101 | Known-DAG recovery over 8 shapes x 10 seeds; the closed forms `h([[0,1],[1,0]]) = 2cosh(1) - 2` and `h([[w]]) = e^{w^2} - 1`; the constraint gradient against central finite differences |
| `test_neural_sde.py` | 69 | Closed-form terminal law and quadratic variation within stated Monte Carlo standard errors; measured strong-order rates on geometric Brownian motion; bit-identical determinism |
| `test_portfolio_overlap.py` | 52 | Hand-computed cosine `1/sqrt(2)`, Jaccard `1/2`, HHI `1/3` and `1`, system score `7/15 -> 1/5` |
| `test_persistence_vectors.py` | 47 | Hand-computed triangle birth-death pairs; the short-lived-versus-long-lived stability property the module exists for |
| `test_regulatory.py` | 42 | Hand-computed LCR `5.0`, capped HQLA with the 40% Level 2 cap binding, the inflow cap at 75%, NSFR `1.25`, leverage `0.05` |
| `test_fx_swap_layer.py` | 23 | Hand-computed basis exposures and the `25 x 15 = 375` coupling; the refusal of a price layer by `require_exposure` |
| `test_student_t_hmm.py` | 21 | `scipy.stats.t.logpdf`; numerical integration of the scale-mixture definition; `scipy.stats.t.fit` as an independent optimiser |
| `test_causal_validation.py` | 18 | Generated data from a known DAG; the refusal path; and that the counterfactual is passed through unaltered |
| `test_fire_sale.py` | 49 | A hand-computed three-round fixed point; a divergence case past lambda*; and the feedback-caused default set |
| `test_systemic_module_inputs.py` | 21 | That each optional input is used or refused; that a NaN holding raises rather than becoming zero; and the regression guard for the misplaced fire-sale call |

The Student-t suite is the clearest example of the standard applied throughout:
none of its five independent checks compares the implementation against itself,
which is what allowed it to catch a genuine bug in the degrees-of-freedom update
(see §2.1).

---

## 4. What is still not done

Stated explicitly, because a build report that only lists achievements is not
useful to a reviewer.

- **Generalized hyperbolic and skewed emissions** remain unimplemented. The
  Student-t captures symmetric fat tails; it cannot represent the asymmetry of a
  crash versus a rally.
- **Hidden semi-Markov (HSMM) duration modelling** is not implemented. Regime
  persistence is still geometric by construction.
- **A diffusion cannot jump.** The Neural SDE covers stochastic volatility, not
  discontinuous jumps.
- **No Basel IV output floor, TLAC, or currency-level LCR.**
- **No full PC / FCI orientation**, so latent confounding is not handled and
  orientation is identified only up to the Markov equivalence class.
- **No principled selector** for the causal-discovery sparsity penalty or the
  persistence-vector parameters.
- ~~The new risk modules are engine-level capabilities with explicit input
  contracts, not yet wired into the live report pipeline.~~ **Closed in §2.10.**
  `regulatory.py`, `portfolio_overlap.py` and `persistence_vectors.py` are now
  fed from `analyze_multiple_banks` through optional, fail-closed arguments, and
  rendered in the multi-institution report.
- **The claim that followed that closure was wrong and is corrected here.** This
  document previously said "every one of the nine review items is therefore both
  implemented and reachable from the engine". A transitive import-graph scan of
  the whole backend (see `EXECUTIVE_REVIEW_REMEDIATION.md`, third round) found
  that this was false: `conformal.py`, `federated.py`, `hidden_markov.py`,
  `subgraphx.py`, `uncertainty.py`, `event_metrics.py`, `causal_validation.py`,
  `causal_discovery.py`, `tncm_vae.py`, `mixture_of_experts.py`,
  `network_gate.py`, `streaming.py`, `timeseries_store.py` and the whole
  `modules/data/connectors/` package are implemented and tested but reachable
  from nothing that runs. The sentence is left visible above rather than deleted,
  because "the note said it was done" is how the gap survived two review rounds.
  Reachability is now asserted by `backend/tests/test_reachability.py`, which
  fails when the census and the code disagree in either direction.
