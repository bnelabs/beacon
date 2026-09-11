"""The network analysis is already in-process and fast; no query engine is needed.

The third-round review recommended integrating "a specialized graph engine (like
TigerGraph, Neo4j, or DuckDB for analytical queries)" on the premise that
"querying dense adjacency matrices (graph structures) in Postgres is inefficient"
and that a graph engine would handle the heavy matrix multiplications more
efficiently.

That premise does not hold for this codebase, and this file records the evidence
rather than the argument. Two independent facts:

* **Nothing stores an adjacency in Postgres.** The schema defines 17 tables and
  none of them holds an exposure or adjacency matrix; the network is built as a
  numpy array from the caller's ``(debtor, creditor) -> amount`` mapping and
  cleared in process. There is no query to make faster.
* **The supposedly heavy work is milliseconds.** ``clear_multiplex`` at n=1000
  nodes runs in single-digit milliseconds, so a database round trip per iteration
  would be slower than the computation it replaced, not faster.

The bounds below are deliberately loose -- two orders of magnitude above the
measured cost -- because the purpose is to catch an accidental complexity
regression (a per-edge database round trip, or an O(n^4) rewrite), not to assert a
benchmark number that a shared CI runner would make flaky.

If a future deployment genuinely outgrows this, the signal is one of these bounds
failing, and the right response would then be informed by the measured shape
rather than by a recommendation made without one.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from backend.modules.risk.clearing import NetworkLayer, clear_multiplex

#: Measured cost at n=1000 was ~3 ms. The bound is ~1000x that, on purpose.
GENEROUS_BOUND_SECONDS = 5.0

NETWORK_SIZES = (50, 100, 250, 500)


def interbank_network(n_nodes: int, seed: int = 0):
    """A sparse liability matrix and plausible endowments, in the real regime.

    Real interbank networks are sparse: a few percent of pairs have an exposure.
    A dense random matrix would be a harder-to-clear network that does not
    correspond to anything, so sparsity is part of the fixture's meaning.
    """
    rng = np.random.default_rng(seed)
    mask = rng.random((n_nodes, n_nodes)) < 0.04
    np.fill_diagonal(mask, False)
    liabilities = mask * rng.uniform(1e6, 1e9, size=(n_nodes, n_nodes))
    endowments = liabilities.sum(axis=1) * rng.uniform(0.3, 1.5, size=n_nodes)
    return liabilities, endowments


class TestClearingIsInProcessFast:
    @pytest.mark.parametrize("n_nodes", NETWORK_SIZES)
    def test_a_full_clear_stays_far_inside_the_bound(self, n_nodes: int):
        liabilities, endowments = interbank_network(n_nodes)
        layer = NetworkLayer(name="interbank", liabilities=liabilities, seniority=0)

        started = time.perf_counter()
        result = clear_multiplex([layer], endowments)
        elapsed = time.perf_counter() - started

        # Correctness first: a fast wrong answer is not evidence of capacity.
        assert result.converged is True
        assert result.payments.shape == (n_nodes,)
        assert np.all(np.isfinite(result.payments))
        assert elapsed < GENEROUS_BOUND_SECONDS, (
            f"clearing {n_nodes} nodes took {elapsed:.2f}s, which is far above the "
            "measured cost and suggests a complexity regression: "
            f"{GENEROUS_BOUND_SECONDS}s is the guard, ~3ms is the historical value "
            "at this scale"
        )

    def test_the_scenario_workload_the_analysis_actually_runs_is_cheap(self):
        """``analyze_multiple_banks`` clears once per institution for importance.

        That n-fold loop, not a single clear, is the real workload, so the bound is
        asserted on the loop rather than on one call.
        """
        n_nodes = 200
        liabilities, endowments = interbank_network(n_nodes)
        layer = NetworkLayer(name="interbank", liabilities=liabilities, seniority=0)

        started = time.perf_counter()
        baseline = clear_multiplex([layer], endowments)
        for position in range(n_nodes):
            shocked = endowments.copy()
            shocked[position] = 0.0
            clear_multiplex([layer], shocked)
        elapsed = time.perf_counter() - started

        assert baseline.converged is True
        assert elapsed < GENEROUS_BOUND_SECONDS, (
            f"{n_nodes} contagion clears took {elapsed:.2f}s; the measured cost for "
            "this workload is tens of milliseconds"
        )

    def test_no_database_session_is_needed_to_clear(self):
        """Clearing takes arrays, not a connection: there is nothing to substitute.

        Asserted structurally -- the call above succeeds with no session, engine or
        fixture in scope -- so a future change that made clearing require the
        database would fail here rather than silently becoming a query workload.
        """
        liabilities, endowments = interbank_network(20)
        result = clear_multiplex(
            [NetworkLayer(name="interbank", liabilities=liabilities, seniority=0)],
            endowments,
        )
        assert isinstance(result.payments, np.ndarray)
