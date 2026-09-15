"""Property-based tests for the three numerically load-bearing modules.

Why this file exists
--------------------

The example-based suites (``test_fractional.py``, ``test_clearing.py``,
``test_hidden_markov.py``) pin known answers: hand-computed fixed points,
reference implementations, documented critical values. What they cannot do is
sweep an input *domain*. The modules under test here make claims of exactly
that shape, and a claim that is only checked on three hand-picked inputs is a
claim about those inputs:

* ``fractional.py`` claims its filter is strictly causal and its weights are
  the binomial coefficients of ``(1 - B)**d``. Causality is the property that
  distinguishes it from the forward-filling it replaced, so it is checked here
  as the exact prefix identity from the module docstring -- for generated
  series, orders and truncation thresholds, not one example of each.
* ``clearing.py`` computes the Eisenberg-Noe greatest fixed point. That fixed
  point is monotone in endowments, homogeneous of degree one in
  (liabilities, endowments), and bounded by the nominal obligations. A
  violation of any of these on a generated network is an implementation bug,
  not a numerical quirk -- they are theorems about the map the code iterates.
* ``hidden_markov.py`` runs the forward-backward recursion in log space and
  claims the scaled version agrees with the textbook linear-space
  probabilities. The claim is checked against brute-force enumeration of
  *every* hidden state path -- feasible because generation keeps T small
  while varying means, variances, transitions and observations. The brute
  force recomputes Gaussian densities from the closed form rather than
  calling into the module, so it is an independent implementation, not a
  mirror of the one under test.

Determinism
-----------

The rest of this suite is deterministic by seeding ``numpy.random.default_rng``
with fixed integers; property tests match that contract by running with
``derandomize=True``, which fixes hypothesis' own RNG per test. The example
database (``.hypothesis/``) is gitignored. ``max_examples`` is kept modest
because the EM-fit properties are the expensive ones and the invariants they
check do not get more true at example 500.
"""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays
from scipy.special import binom

from backend.modules.data.fractional import (
    frac_diff,
    frac_diff_ffd,
    frac_diff_weights,
)
from backend.modules.engine.hidden_markov import GaussianHMM, StudentTHMM
from backend.modules.risk.clearing import sequential_clearing

# Every property test runs with the same discipline: a fixed example count, no
# wall-clock deadline (CI machines vary), and derandomised generation so a
# failure here reproduces on every machine and every run.
PROPERTIES = settings(
    max_examples=50,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)
EXPENSIVE = settings(
    max_examples=20,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Orders away from both ends: d=0 is the identity (tested separately) and d>=1
# turns the filter into integer differencing, which is not what this module is
# for. Thresholds span the range the production callers use.
DIFF_ORDERS = st.floats(
    min_value=0.05, max_value=0.95, allow_nan=False, allow_infinity=False
)
THRESHOLDS = st.floats(
    min_value=1e-4, max_value=1e-2, allow_nan=False, allow_infinity=False
)
OBSERVATIONS = st.floats(
    min_value=-1e3, max_value=1e3, allow_nan=False, allow_infinity=False
)


def _series(min_length: int = 1, max_length: int = 64):
    """A finite 1-D float series of generated length."""
    return st.integers(min_value=min_length, max_value=max_length).flatmap(
        lambda n: arrays(float, n, elements=OBSERVATIONS)
    )


@st.composite
def _clearing_network(draw, max_nodes: int = 6):
    """A single-layer interbank network: non-negative, zero-diagonal, plus
    non-negative endowments. Sizes are kept small because the engine iterates
    to a 1e-10 fixed point and the property, not the scale, is under test."""
    n = draw(st.integers(min_value=2, max_value=max_nodes))
    liabilities = draw(
        arrays(
            float,
            (n, n),
            elements=st.floats(
                min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False
            ),
        )
    )
    liabilities[np.diag_indices(n)] = 0.0
    endowments = draw(
        arrays(
            float,
            n,
            elements=st.floats(
                min_value=0.0, max_value=200.0, allow_nan=False, allow_infinity=False
            ),
        )
    )
    return liabilities, endowments


def _fit_hmm_parameters(draw, n_states: int):
    """Draw a valid (means, variances, transition, initial) parameter set.

    Transition rows and the initial vector are drawn strictly positive and
    normalised, so every state path has nonzero probability and the brute-force
    enumeration below cannot divide by zero.
    """
    positive = st.floats(
        min_value=0.05, max_value=1.0, allow_nan=False, allow_infinity=False
    )
    means = draw(
        arrays(
            float,
            (n_states, 1),
            elements=st.floats(
                min_value=-3.0, max_value=3.0, allow_nan=False, allow_infinity=False
            ),
        )
    )
    variances = draw(
        arrays(
            float,
            (n_states, 1),
            elements=st.floats(
                min_value=0.5, max_value=3.0, allow_nan=False, allow_infinity=False
            ),
        )
    )
    transition = draw(arrays(float, (n_states, n_states), elements=positive))
    transition = transition / transition.sum(axis=1, keepdims=True)
    initial = draw(arrays(float, n_states, elements=positive))
    initial = initial / initial.sum()
    return means, variances, transition, initial


def _manual_hmm(n_states: int, parameters) -> GaussianHMM:
    """A GaussianHMM with hand-set parameters -- no fit, no randomness."""
    means, variances, transition, initial = parameters
    model = GaussianHMM(n_states=n_states, n_features=1)
    model.means = means
    model.variances = variances
    model.transition = transition
    model.initial = initial
    return model


def _brute_force_path_probabilities(model: GaussianHMM, X: np.ndarray):
    """Exact linear-space likelihood and smoothed posteriors by enumeration.

    Sums the joint p(X, z_{1:T}) over every one of the ``n_states**T`` hidden
    paths. The Gaussian density is recomputed from its closed form here on
    purpose: an independent implementation is the point of the cross-check.
    """
    n_observations = X.shape[0]
    n_states = model.n_states

    def density(x: float, state: int) -> float:
        mean = float(model.means[state, 0])
        variance = float(model.variances[state, 0])
        return math.exp(-0.5 * (x - mean) ** 2 / variance) / math.sqrt(
            2.0 * math.pi * variance
        )

    total = 0.0
    marginal = np.zeros((n_observations, n_states), dtype=float)
    for path in itertools.product(range(n_states), repeat=n_observations):
        joint = float(model.initial[path[0]]) * density(float(X[0, 0]), path[0])
        for step in range(1, n_observations):
            joint *= float(model.transition[path[step - 1], path[step]]) * density(
                float(X[step, 0]), path[step]
            )
        total += joint
        for step, state in enumerate(path):
            marginal[step, state] += joint
    return total, marginal / total


# ---------------------------------------------------------------------------
# fractional.py -- causality, binomial weights, constant annihilation, linearity
# ---------------------------------------------------------------------------


class TestFractionalDifferencingProperties:
    """Invariants of ``(1 - B)**d`` that must hold across the whole domain."""

    @PROPERTIES
    @given(d=DIFF_ORDERS, threshold=THRESHOLDS)
    def test_weights_are_analytic_binomial_coefficients(self, d, threshold):
        """w_0 = 1, w_k = -w_{k-1}(d-k+1)/k = (-1)^k binom(d, k), and for
        d in (0, 1) every weight after the first is negative with strictly
        decaying magnitude.

        The sign structure matters: the filter is "the level minus a weighted
        memory of the past", and the infinite weights sum to exactly zero
        ((1-1)**d), so the memory cancels the level only in the limit. How
        much level survives a *truncated* window is the next test's subject.
        """
        weights = frac_diff_weights(d, threshold)

        assert weights[0] == 1.0
        # Every retained coefficient is at or above the cutoff; the first one
        # below it is what stopped the accumulation.
        assert np.all(np.abs(weights) >= threshold)
        # Closed form: w_k = (-1)^k * binom(d, k) -- for d in (0,1) that is
        # +1 at k=0 and strictly negative afterwards.
        expected = ((-1.0) ** np.arange(len(weights))) * binom(
            d, np.arange(len(weights))
        )
        np.testing.assert_allclose(weights, expected, rtol=1e-10, atol=1e-15)
        assert np.all(weights[1:] < 0.0)
        # |w_k| strictly decreases -- the decay that makes truncation finite
        # at all (|w_k|/|w_{k-1}| = (k-1-d)/k < 1 for every k >= 1).
        magnitudes = np.abs(weights)
        assert np.all(np.diff(magnitudes) < 0.0)

    @PROPERTIES
    @given(series=_series())
    def test_zero_order_is_the_exact_identity(self, series):
        """d = 0 must return the series unchanged -- bit for bit, no warm-up.

        This is the anchor of the dial: fractional differencing at order zero
        is *not* an approximation of the input, it is the input.
        """
        weights = frac_diff_weights(0.0)
        assert weights.shape == (1,)
        assert weights[0] == 1.0
        np.testing.assert_array_equal(frac_diff(series, 0.0), series)
        np.testing.assert_array_equal(frac_diff_ffd(series, 0.0), series)

    @PROPERTIES
    @given(series=_series(min_length=2), d=DIFF_ORDERS, threshold=THRESHOLDS, data=st.data())
    def test_both_forms_are_strictly_causal(self, series, d, threshold, data):
        """``frac_diff(series)[:k] == frac_diff(series[:k])`` -- exactly.

        This is the docstring's own no-look-ahead contract, and the property
        forward-filling violated: a value at ``i`` may depend only on
        ``series[0..i]``, so truncating the input may not change any output
        that was already computable. Checked for both the expanding form and
        the fixed-width form (whose warm-up mask must also agree).
        """
        n = len(series)
        k = data.draw(st.integers(min_value=1, max_value=n))

        full = frac_diff(series, d, threshold)
        prefix = frac_diff(series[:k], d, threshold)
        np.testing.assert_array_equal(full[:k], prefix)

        ffd_full = frac_diff_ffd(series, d, threshold)
        ffd_prefix = frac_diff_ffd(series[:k], d, threshold)
        np.testing.assert_array_equal(np.isnan(ffd_full[:k]), np.isnan(ffd_prefix))
        finite = ~np.isnan(ffd_prefix)
        if finite.any():
            np.testing.assert_array_equal(ffd_full[:k][finite], ffd_prefix[finite])

    @PROPERTIES
    @given(d=DIFF_ORDERS, threshold=THRESHOLDS, data=st.data())
    def test_fixed_width_matches_expanding_after_warmup(self, d, threshold, data):
        """Once the fixed window fits, FFD and the expanding form agree.

        After warm-up the expanding form uses every retained coefficient, so
        both compute the same dot product -- in a different summation order,
        hence ``allclose`` scaled to the data rather than exact equality.
        """
        width = len(frac_diff_weights(d, threshold))
        n = data.draw(st.integers(min_value=width, max_value=width + 40))
        series = data.draw(arrays(float, n, elements=OBSERVATIONS))

        expanding = frac_diff(series, d, threshold)
        fixed = frac_diff_ffd(series, d, threshold)

        scale = 1.0 + float(np.abs(series).max()) if n else 1.0
        np.testing.assert_allclose(
            fixed[width - 1 :],
            expanding[width - 1 :],
            rtol=1e-10,
            atol=1e-9 * scale,
        )

    @PROPERTIES
    @given(
        constant=st.floats(
            min_value=-1e3, max_value=1e3, allow_nan=False, allow_infinity=False
        ),
        d=DIFF_ORDERS,
        threshold=THRESHOLDS,
        data=st.data(),
    )
    def test_level_residual_is_the_weight_sum_and_shrinks_with_threshold(
        self, constant, d, threshold, data
    ):
        """On a constant series the truncated filter outputs exactly
        ``c * sum(weights)`` -- flat, with no fabricated structure -- and that
        residual level shrinks monotonically as the threshold falls.

        The infinite weights sum to zero, so the filter kills levels only in
        the limit; every retained term after the first is negative, hence the
        partial sums decrease toward zero and a tighter threshold (a longer
        window) can never leave *more* of the level behind. This is the honest
        form of "the threshold is a dial": it prices the level leakage
        instead of pretending it is zero.
        """
        weights = frac_diff_weights(d, threshold)
        width = len(weights)
        series = np.full(width + 5, constant, dtype=float)
        out = frac_diff_ffd(series, d, threshold)

        computed = out[np.isfinite(out)]
        assert computed.shape[0] == 6
        # Flat output equal to c * sum-of-weights, to accumulation round-off.
        np.testing.assert_allclose(
            computed,
            constant * float(weights.sum()),
            rtol=0.0,
            atol=1e-8 * (1.0 + abs(constant)),
        )

        # A strictly tighter threshold keeps more terms and leaves less level.
        tighter = threshold * data.draw(
            st.floats(min_value=0.01, max_value=0.9, allow_nan=False, allow_infinity=False)
        )
        more_weights = frac_diff_weights(d, tighter)
        assert len(more_weights) >= width
        assert abs(float(more_weights.sum())) <= abs(float(weights.sum())) + 1e-15

    @PROPERTIES
    @given(d=DIFF_ORDERS, threshold=THRESHOLDS, data=st.data())
    def test_fixed_width_form_is_linear(self, d, threshold, data):
        """``ffd(a*x + b*y) == a*ffd(x) + b*ffd(y)`` wherever both are defined.

        The filter is a convolution; linearity is what lets callers difference
        a portfolio by differing its parts, and what a hand-rolled
        "normalise-then-difference" shortcut silently breaks.
        """
        n = data.draw(st.integers(min_value=1, max_value=48))
        x = data.draw(arrays(float, n, elements=OBSERVATIONS))
        y = data.draw(arrays(float, n, elements=OBSERVATIONS))
        a = data.draw(st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False))
        b = data.draw(st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False))

        left = frac_diff_ffd(a * x + b * y, d, threshold)
        right = a * frac_diff_ffd(x, d, threshold) + b * frac_diff_ffd(y, d, threshold)

        np.testing.assert_array_equal(np.isnan(left), np.isnan(right))
        finite = ~np.isnan(left)
        if finite.any():
            scale = 1.0 + float(np.abs(left[finite]).max())
            np.testing.assert_allclose(
                left[finite], right[finite], rtol=1e-9, atol=1e-9 * scale
            )


# ---------------------------------------------------------------------------
# clearing.py -- Eisenberg-Noe fixed-point invariants
# ---------------------------------------------------------------------------


class TestClearingProperties:
    """Theorems of the Eisenberg-Noe map, asserted on generated networks.

    Monotonicity and homogeneity are not stylistic preferences: the whole
    product claim ("more capital never causes more defaults") rests on the
    first, and scenario rescaling on the second.
    """

    @PROPERTIES
    @given(network=_clearing_network())
    def test_payments_are_bounded_and_the_result_is_internally_consistent(self, network):
        liabilities, endowments = network
        result = sequential_clearing(liabilities, endowments)
        nominal = result.nominal_liabilities

        # Nobody pays negative, nobody pays more than they owe.
        assert np.all(result.payments >= 0.0)
        assert np.all(result.payments <= nominal + result.tolerance)
        # The aggregate is the sum of the layers; shortfall is the gap.
        layer_sum = sum(result.layer_payments.values())
        np.testing.assert_allclose(result.payments, layer_sum, rtol=0, atol=1e-12)
        assert result.total_shortfall == pytest.approx(
            float((nominal - result.payments).sum()), abs=1e-9
        )
        # Balance-sheet identity and non-negative receipts.
        np.testing.assert_allclose(
            result.equity, result.resources - nominal, rtol=0, atol=1e-9
        )
        assert np.all(result.resources >= result.endowments - 1e-12)
        # A node is flagged exactly when its final payment falls short, and
        # every flagged node has a recorded cause.
        short = (nominal - result.payments) > result.tolerance
        assert np.array_equal(result.defaulted, short)
        assert set(result.causes) == set(np.nonzero(result.defaulted)[0].tolist())
        assert result.converged

    @PROPERTIES
    @given(network=_clearing_network(), data=st.data())
    def test_more_endowment_never_reduces_any_payment(self, network, data):
        """Monotonicity of the greatest fixed point in the endowments.

        The clearing map is monotone and the iteration starts from the same
        full-payment vector for both runs, so the sequences are ordered at
        every step and their limits inherit the order. If this ever fails, the
        dashboard can show a bank becoming *more* distressed after receiving
        capital -- the one artefact the platform must never produce.
        """
        liabilities, endowments = network
        n = len(endowments)
        extra = data.draw(
            arrays(
                float,
                n,
                elements=st.floats(
                    min_value=0.0, max_value=200.0, allow_nan=False, allow_infinity=False
                ),
            )
        )
        base = sequential_clearing(liabilities, endowments)
        enriched = sequential_clearing(liabilities, endowments + extra)

        assert np.all(enriched.payments >= base.payments - 1e-6)
        assert enriched.total_shortfall <= base.total_shortfall + 1e-6
        assert enriched.n_defaults <= base.n_defaults

    @PROPERTIES
    @given(network=_clearing_network(), data=st.data())
    def test_endowments_covering_nominal_liabilities_pay_in_full(self, network, data):
        """Solvency plus self-sufficiency: no node needs its receipts, so the
        full-payment vector is already the fixed point and nobody defaults."""
        liabilities, _ = network
        nominal = liabilities.sum(axis=1)
        cushion = data.draw(
            arrays(
                float,
                len(nominal),
                elements=st.floats(
                    min_value=0.0, max_value=200.0, allow_nan=False, allow_infinity=False
                ),
            )
        )
        result = sequential_clearing(liabilities, nominal + cushion)

        np.testing.assert_allclose(result.payments, nominal, rtol=0, atol=1e-8)
        assert result.n_defaults == 0
        assert result.total_shortfall <= 1e-8
        assert np.all(result.equity >= -1e-8)

    @PROPERTIES
    @given(
        network=_clearing_network(),
        factor=st.floats(
            min_value=0.25, max_value=4.0, allow_nan=False, allow_infinity=False
        ),
    )
    def test_clearing_is_homogeneous_of_degree_one(self, network, factor):
        """Scaling every balance sheet by c scales the clearing vector by c.

        Recovery ratios are scale-invariant and the seniority allocation is
        piecewise linear, so the whole computation commutes with rescaling.
        This is what makes currency/unit changes and scenario multipliers
        safe to apply to inputs rather than outputs.
        """
        liabilities, endowments = network
        base = sequential_clearing(liabilities, endowments)
        scaled = sequential_clearing(factor * liabilities, factor * endowments)

        np.testing.assert_allclose(
            scaled.payments,
            factor * base.payments,
            rtol=1e-8,
            atol=1e-8 * (1.0 + factor * float(np.abs(base.payments).max())),
        )
        assert scaled.n_defaults == base.n_defaults

    @PROPERTIES
    @given(
        endowments=arrays(
            float,
            st.integers(min_value=2, max_value=6),
            elements=st.floats(
                min_value=0.0, max_value=200.0, allow_nan=False, allow_infinity=False
            ),
        )
    )
    def test_network_without_interbank_debt_is_trivial(self, endowments):
        """No liabilities: no payments, no contagion, resources are endowments."""
        n = len(endowments)
        result = sequential_clearing(np.zeros((n, n)), endowments)

        np.testing.assert_array_equal(result.payments, np.zeros(n))
        np.testing.assert_allclose(result.resources, endowments, rtol=0, atol=1e-12)
        np.testing.assert_allclose(result.equity, endowments, rtol=0, atol=1e-12)
        assert result.n_defaults == 0
        assert result.contagion_edges == []


# ---------------------------------------------------------------------------
# hidden_markov.py -- log-space forward-backward against brute force
# ---------------------------------------------------------------------------


class TestHiddenMarkovProperties:
    """The log-space machinery checked against enumeration and against itself
    under relabelling -- the two ways scaled recursions go wrong."""

    @PROPERTIES
    @given(data=st.data())
    def test_forward_backward_matches_brute_force_enumeration(self, data):
        """log p(X) and every smoothed posterior, verified by summing all
        2**T hidden paths in linear space with an independent density formula.

        This is the ground truth the scaled log-space recursion exists to
        approximate without underflow; on small T the two must agree to
        floating-point noise, or the scaling factors are wrong.
        """
        n_observations = data.draw(st.integers(min_value=3, max_value=7))
        parameters = _fit_hmm_parameters(data.draw, n_states=2)
        model = _manual_hmm(2, parameters)
        X = data.draw(
            arrays(
                float,
                (n_observations, 1),
                elements=st.floats(
                    min_value=-6.0, max_value=6.0, allow_nan=False, allow_infinity=False
                ),
            )
        )

        total, posteriors = _brute_force_path_probabilities(model, X)
        assert total > 0.0

        assert model.log_likelihood(X) == pytest.approx(math.log(total), rel=1e-9, abs=1e-12)
        np.testing.assert_allclose(model.posteriors(X), posteriors, rtol=1e-8, atol=1e-10)
        row_sums = model.posteriors(X).sum(axis=1)
        np.testing.assert_allclose(row_sums, np.ones(n_observations), rtol=0, atol=1e-12)

    @PROPERTIES
    @given(data=st.data())
    def test_inference_is_invariant_under_state_relabelling(self, data):
        """State indices are arbitrary; permuting every parameter consistently
        must permute the posteriors and leave the likelihood untouched.

        A scaled forward-backward that leaks index-dependent behaviour (a
        normalisation applied to the wrong axis, an argmax tie resolved by
        position) fails exactly here.
        """
        n_observations = data.draw(st.integers(min_value=5, max_value=20))
        permutation = np.array(data.draw(st.permutations([0, 1, 2])))
        parameters = _fit_hmm_parameters(data.draw, n_states=3)
        means, variances, transition, initial = parameters
        model = _manual_hmm(3, parameters)
        permuted = _manual_hmm(
            3,
            (
                means[permutation],
                variances[permutation],
                transition[np.ix_(permutation, permutation)],
                initial[permutation],
            ),
        )
        X = data.draw(
            arrays(
                float,
                (n_observations, 1),
                elements=st.floats(
                    min_value=-6.0, max_value=6.0, allow_nan=False, allow_infinity=False
                ),
            )
        )

        assert permuted.log_likelihood(X) == pytest.approx(
            model.log_likelihood(X), rel=1e-10, abs=1e-12
        )
        np.testing.assert_allclose(
            permuted.posteriors(X), model.posteriors(X)[:, permutation], rtol=1e-8, atol=1e-10
        )

    @EXPENSIVE
    @given(data=st.data())
    def test_em_likelihood_history_never_decreases(self, data):
        """Baum-Welch is an EM algorithm; its observed-data likelihood is
        non-decreasing by construction. A dip means the M-step and the
        E-step disagree about the model -- the classic silent HMM bug.

        Also checks the fitted model's recomputed likelihood matches the last
        history entry, i.e. the history the caller sees describes the
        parameters the caller gets.
        """
        n_observations = data.draw(st.integers(min_value=24, max_value=64))
        X = data.draw(
            arrays(
                float,
                (n_observations, 1),
                elements=st.floats(
                    min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False
                ),
            )
        )
        model = GaussianHMM(n_states=2, n_features=1, seed=20260915)
        history = model.fit(X, max_iterations=40, tolerance=1e-7, n_restarts=1)

        assert len(history) >= 1
        assert np.all(np.isfinite(history))
        scale = max(1.0, abs(history[0]))
        assert np.all(np.diff(np.asarray(history)) >= -1e-9 * scale)
        assert model.log_likelihood(X) == pytest.approx(
            history[-1], rel=1e-8, abs=1e-6 * scale
        )
        posteriors = model.posteriors(X)
        np.testing.assert_allclose(
            posteriors.sum(axis=1), np.ones(n_observations), rtol=0, atol=1e-9
        )
        assert np.all(posteriors >= 0.0) and np.all(posteriors <= 1.0)

    @EXPENSIVE
    @given(data=st.data())
    def test_student_t_fit_stays_finite_and_normalised(self, data):
        """The heavy-tailed sibling inherits the log-space machinery; its fit
        must stay finite, keep posteriors a distribution, and keep the fitted
        degrees of freedom inside the declared identification bounds (nu > 2
        is what keeps ``variances`` meaning variance)."""
        n_observations = data.draw(st.integers(min_value=24, max_value=64))
        X = data.draw(
            arrays(
                float,
                (n_observations, 1),
                elements=st.floats(
                    min_value=-8.0, max_value=8.0, allow_nan=False, allow_infinity=False
                ),
            )
        )
        model = StudentTHMM(n_states=2, n_features=1, seed=7)
        history = model.fit(X, max_iterations=25, tolerance=1e-6, n_restarts=1)

        assert np.all(np.isfinite(history))
        posteriors = model.posteriors(X)
        np.testing.assert_allclose(
            posteriors.sum(axis=1), np.ones(n_observations), rtol=0, atol=1e-9
        )
        fitted_df = model.degrees_of_freedom_per_state
        assert np.all(np.isfinite(fitted_df))
        assert np.all(fitted_df >= model.min_degrees_of_freedom - 1e-9)
        assert np.all(fitted_df <= model.max_degrees_of_freedom + 1e-9)
