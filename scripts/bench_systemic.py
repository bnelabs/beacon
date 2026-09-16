#!/usr/bin/env python3
"""Hot-path benchmarks for the language-strategy decision rule.

Measures the loops that would justify a systems language if they ever became
bottlenecks:

  1. multiplex clearing (Eisenberg-Noe fixed point), per solve and as the
     n-solve loop the systemic-importance ranking runs;
  2. the coupled fire-sale fixed point (clearing inside a price-feedback loop);
  3. batched sequence-model inference over rolling windows (the risk series);
  4. the Student-t regime nowcast the prediction path runs once per source.

Prints one JSON object per benchmark. The numbers are embedded in
docs/LANGUAGE_STRATEGY.md; re-run after touching those loops and update the
doc in the same change. Nothing here imports the API or the database.

Usage:  PYTHONPATH=. python scripts/bench_systemic.py [--reps N]
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np


def _bench(fn, reps: int) -> dict:
    fn()  # warm-up (allocations, JIT-free but cache-warm)
    start = time.perf_counter()
    for _ in range(reps):
        fn()
    elapsed = (time.perf_counter() - start) / reps
    return {"seconds_per_call": round(elapsed, 6)}


def bench_clearing(reps: int) -> None:
    from backend.modules.risk.clearing import NetworkLayer, clear_multiplex

    for n in (50, 200, 500):
        rng = np.random.default_rng(n)
        layers = []
        for _ in range(3):
            liab = np.abs(rng.normal(0, 1e8, size=(n, n)))
            np.fill_diagonal(liab, 0.0)
            layers.append(NetworkLayer(name=f"l{_}", liabilities=liab, seniority=_))
        endow = np.abs(rng.normal(0, 5e8, size=n))

        def solve(layers=layers, endow=endow, n=n):
            clear_multiplex(layers, endow, node_ids=[str(i) for i in range(n)])

        result = _bench(solve, reps)
        result.update(benchmark="multiplex_clearing", n=n, layers=3)
        print(json.dumps(result))

        if n == 200:
            def ranking(layers=layers, endow=endow, n=n):
                # the systemic-importance loop: one clear per institution
                for i in range(min(n, 50)):
                    shocked = endow.copy()
                    shocked[i] = 0.0
                    clear_multiplex(layers, shocked, node_ids=[str(j) for j in range(n)])

            result = _bench(ranking, max(1, reps // 10))
            result.update(benchmark="importance_ranking_50_clears", n=n)
            print(json.dumps(result))


def bench_fire_sale(reps: int) -> None:
    from backend.modules.risk.fire_sale import FireSaleScenario, FireSaleSolver

    rng = np.random.default_rng(11)
    n, assets = 200, 20
    holdings = rng.uniform(0, 2e5, size=(n, assets))  # units; every position marginable at rest
    capital = rng.uniform(5e8, 9e8, size=n)  # floored so every position is financeable at rest
    liab = np.abs(rng.normal(0, 1e8, size=(n, n)))
    np.fill_diagonal(liab, 0.0)
    endow = np.abs(rng.normal(0, 4e8, size=n))
    prices = np.full(assets, 100.0)
    impact = np.full(assets, 1e-6)
    margins = np.full(n, 0.1)
    ids = [str(i) for i in range(n)]

    scenario = FireSaleScenario(
        institution_ids=ids,
        asset_ids=[f"a{i}" for i in range(assets)],
        holdings=holdings,
        prices=prices,
        capital=capital,
        liabilities=liab,
        endowments=endow,
        margins=margins,
        price_impacts=impact,
        price_shock=np.full(assets, -5.0),
        margin_sensitivity=np.full(n, 0.5),
        reference_volatility=0.2,
    )

    def solve():
        FireSaleSolver(scenario).solve()

    result = _bench(solve, reps)
    result.update(benchmark="coupled_fire_sale", n=n, assets=assets)
    print(json.dumps(result))


def bench_inference(reps: int) -> None:
    import torch

    from backend.modules.engine.multi_scale_trainer import (
        MultiScaleTemporalAttentionModel,
    )

    torch.manual_seed(3)
    model = MultiScaleTemporalAttentionModel(
        num_sources=8, sequence_length=30, d_model=64, nhead=4, num_layers=2, dropout=0.0
    )
    model.eval()
    windows = torch.randn(5000, 30)
    sources = torch.randint(0, 8, (5000, 1))

    def forward():
        with torch.no_grad():
            for start in range(0, 5000, 256):
                model(windows[start:start + 256], sources[start:start + 256])

    result = _bench(forward, reps)
    result.update(benchmark="risk_series_inference", windows=5000, batch=256)
    print(json.dumps(result))


def bench_regime_nowcast(reps: int) -> None:
    """The Student-t regime nowcast the prediction path runs once per source.

    ``RealPredictionEngine._regime_label`` fits a two-state Student-t HMM on the
    standardized history of every source and reads the regime off the Viterbi
    path. It is the only loop on the prediction path whose cost is seconds
    rather than milliseconds, and it is paid once per source per job, so it is
    the one that decides whether a monitoring cycle over the full catalogue
    meets the decision rule in docs/LANGUAGE_STRATEGY.md.

    Measured here at the production shape: ``n_states=2, seed=0``, default
    ``max_iterations=100``, on a T=1000 standardized random walk.
    """
    from backend.modules.engine.hidden_markov import StudentTHMM

    rng = np.random.default_rng(11)
    for n_observations in (250, 1000):
        values = np.cumsum(rng.standard_normal(n_observations))
        standardized = ((values - values.mean()) / values.std()).reshape(-1, 1)

        def nowcast(data=standardized):
            model = StudentTHMM(n_states=2, seed=0)
            model.fit(data)
            model.viterbi(data)

        result = _bench(nowcast, reps)
        result.update(
            benchmark="regime_nowcast_student_t_k2",
            n_observations=n_observations,
        )
        print(json.dumps(result))


def bench_regime_nowcast_batched(reps: int, n_sources: int = 20) -> None:
    """The same nowcast, batched across sources -- the lever LANGUAGE_STRATEGY
    named and deferred: the per-source fits are independent, and the
    forward/backward recursions are Python loops over T doing (K, K) numpy
    work with K=2, a shape dominated by per-timestep numpy overhead rather
    than arithmetic. ``fit_viterbi_student_t_batch`` runs one (n, T, K)
    recursion per length group instead of n separate ones, so the loop cost
    is paid once for the whole job.

    Measured at the monitoring-cycle shape: n=20 sources, T=250 and T=1000,
    ``n_states=2, seed=0``, default ``max_iterations=100`` -- and against the
    sequential per-source loop production paid before, on identical windows.
    Label equality between the two paths is not a benchmark question; it is
    pinned exactly by backend/tests/test_regime_batch_equivalence.py.
    """
    from backend.modules.engine.hidden_markov import (
        StudentTHMM,
        fit_viterbi_student_t_batch,
    )

    for n_observations in (250, 1000):
        windows = []
        for index in range(n_sources):
            rng = np.random.default_rng(11 + index)
            values = np.cumsum(rng.standard_normal(n_observations))
            standardized = ((values - values.mean()) / values.std()).reshape(-1, 1)
            windows.append(standardized)
        stacked = np.stack(windows)

        def sequential(data=windows):
            for window in data:
                model = StudentTHMM(n_states=2, seed=0)
                model.fit(window)
                model.viterbi(window)

        def batched(data=stacked):
            fit_viterbi_student_t_batch(data)

        seq_result = _bench(sequential, max(1, reps // 2))
        seq_result.update(
            benchmark="regime_nowcast_student_t_k2_sequential",
            n_sources=n_sources,
            n_observations=n_observations,
        )
        print(json.dumps(seq_result))

        batch_result = _bench(batched, reps)
        batch_result.update(
            benchmark="regime_nowcast_student_t_k2_batched",
            n_sources=n_sources,
            n_observations=n_observations,
        )
        print(json.dumps(batch_result))

        speedup = seq_result["seconds_per_call"] / max(batch_result["seconds_per_call"], 1e-9)
        print(json.dumps({
            "benchmark": "regime_nowcast_batched_speedup",
            "n_sources": n_sources,
            "n_observations": n_observations,
            "speedup": round(speedup, 2),
        }))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=10)
    args = parser.parse_args()

    bench_clearing(args.reps)
    bench_fire_sale(max(1, args.reps // 2))
    bench_inference(max(1, args.reps // 5))
    # The nowcast is seconds per call, so it gets the fewest repetitions.
    bench_regime_nowcast(max(1, args.reps // 10))
    # The batched nowcast pays the loop once for n sources; the sequential
    # comparison inside it is the expensive leg, hence the smaller budget.
    bench_regime_nowcast_batched(max(2, args.reps // 5))


if __name__ == "__main__":
    main()
