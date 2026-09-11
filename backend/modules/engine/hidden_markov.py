"""Hidden Markov regime model for the network attestation gate.

Why this module exists
----------------------

``NetworkQualityGate`` (``backend/modules/data/network_gate.py``) blocks a
prediction when the live market regime is not one the model was trained on. It
already accepts a ``known_regimes`` tuple and fails closed on an unseen label --
but until now that tuple was written by hand and nothing produced the label it
compares against. A gate whose input is hand-typed is an assertion about the
person typing it, not about the market. This module is the estimator that
populates it.

The regime is not observed. What is observed is a return, a spread, a funding
ratio: continuous quantities whose *distribution* changes with the regime. An
HMM is the right tool because regime membership is a latent state that persists
(the market does not flip regime every tick) and emits observables through a
state-dependent law. That is precisely the structure the plan calls a Hidden
Markov Graphical Model.

What is implemented, and what is not
------------------------------------

The plan specifies **generalized hyperbolic** state-dependent emissions. Those
are **NOT implemented here.** Generalized hyperbolic distributions require
Bessel-function density evaluation and a much harder M-step, and there is no
library available in this repository to validate such an implementation against.
What is implemented is the tractable and fully verifiable specialisation:

    diagonal-covariance **Gaussian** emissions.

The class is named ``GaussianHMM`` rather than ``HiddenMarkovGraphicalModel``
precisely so the name does not claim a capability the code does not have. The
generalized hyperbolic extension is the intended next step; when it arrives it
belongs in a sibling class with its own tests, not behind this name. The
marginal Gaussian emission is wrong in the tails -- financial returns are
leptokurtic, so a Gaussian state will systematically understate the probability
of an extreme observation and can therefore under-detect the stressed states
this gate cares about most. That limitation is recorded here rather than
discovered later.

Numerical stability
-------------------

The reason this module is longer than a textbook HMM is that the textbook
forward pass underflows. The unscaled forward variable
``alpha_t(j) = P(x_1..t, s_t = j)`` is a product of ``t`` probabilities and
decays geometrically: by ``t = 100`` it is below the smallest representable
double, so ``alpha`` becomes all zeros and the log-likelihood becomes ``-inf``.
A model that returns ``-inf`` for a realistic series length is not a conservative
model, it is a broken one -- and the failure is silent, because ``-inf`` is a
plausible-looking number.

Every recursion here therefore runs in log space with a log-sum-exp and a
per-step normaliser, which is the scaling trick in disguise:

    log alpha_t(j) = logsumexp_i(log alpha_{t-1}(i) + log A[i, j]) + log b_t(j)
    log alpha_t    -= logsumexp_j(log alpha_t)          (the scale of step t)

The normalisers are exactly the per-step likelihood contributions, so
``log p(X) = sum_t log c_t`` is accumulated without ever multiplying
probabilities. ``T = 5000`` is finite, and a test asserts it.

A second failure mode is a state collapsing onto a single observation, which
sends its variance to zero and the likelihood to ``+inf``. The M-step therefore
floors every variance at ``variance_floor``; a test constructs the degenerate
case on purpose.

Honest limits
-------------

* Gaussian emissions only (above). No generalized hyperbolic, no skew, no
  fat tails.
* Diagonal covariance only. Cross-feature correlation within a state is
  ignored; features that only co-move *within* a regime are treated as
  independent given the state.
* The number of states is chosen by the caller. There is no BIC/AIC selection
  here, and a fitted HMM is a local optimum of a non-concave likelihood: that
  is why ``fit`` supports ``n_restarts`` and why the reported log-likelihood is
  the best restart's, not the first one's.
* Labels are assigned by variance rank, not by a probabilistic statement that
  "calm" is the correct economic name for the quietest state. The rank is
  deterministic; the naming is a convention the caller supplies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "DEFAULT_REGIME_LABELS",
    "GaussianHMM",
    "order_states_by_volatility",
    "label_states",
]

DEFAULT_REGIME_LABELS: Tuple[str, ...] = ("calm", "elevated", "stressed", "crisis")

_LOG_2PI = float(np.log(2.0 * np.pi))

# Below this the responsibility of a state is treated as numerically absent and
# its parameters are carried over from the previous iteration rather than being
# recomputed from a division by a near-zero denominator.
_ACTIVE_RESPONSIBILITY = 1e-12


def _logsumexp(values: np.ndarray, axis: int) -> np.ndarray:
    """``log(sum(exp(values)))`` without overflowing or underflowing.

    Subtracting the row maximum before exponentiating keeps the largest term at
    ``exp(0) = 1``, so the sum is in ``[1, K]`` and its logarithm is a normal
    number. Rows that are entirely ``-inf`` (a state that cannot emit the
    observation at all) correctly return ``-inf`` instead of ``nan``.
    """
    peak = np.max(values, axis=axis, keepdims=True)
    # An all -inf row has peak -inf; replace it with 0 so the subtraction is
    # finite and the exp term is 0, giving log(0) = -inf, which is correct.
    peak = np.where(np.isfinite(peak), peak, 0.0)
    shifted = values - peak
    total = np.sum(np.exp(shifted), axis=axis, keepdims=True)
    result = np.log(total) + peak
    return np.squeeze(result, axis=axis)


def _log_probabilities(probabilities: np.ndarray) -> np.ndarray:
    """Elementwise ``log`` with ``log(0) = -inf`` and no warning."""
    out = np.full(np.shape(probabilities), -np.inf, dtype=float)
    np.log(probabilities, out=out, where=np.asarray(probabilities) > 0.0)
    return out


def _validate_matrix_pair(
    means: np.ndarray, variances: np.ndarray
) -> Tuple[np.ndarray, np.ndarray]:
    """Shape-check the ``(n_states, n_features)`` parameter pair."""
    mean_array = np.asarray(means, dtype=float)
    variance_array = np.asarray(variances, dtype=float)

    if mean_array.ndim != 2 or variance_array.ndim != 2:
        raise ValueError(
            "means and variances must both be 2-D (n_states, n_features), got "
            f"shapes {mean_array.shape} and {variance_array.shape}"
        )
    if mean_array.shape != variance_array.shape:
        raise ValueError(
            "means and variances must have the same shape, got "
            f"{mean_array.shape} and {variance_array.shape}"
        )
    if mean_array.shape[0] < 1:
        raise ValueError("means and variances must describe at least one state")
    if not np.all(np.isfinite(mean_array)):
        raise ValueError("means contains non-finite values")
    if not np.all(np.isfinite(variance_array)):
        raise ValueError("variances contains non-finite values")
    if np.any(variance_array < 0):
        raise ValueError("variances must be non-negative")
    return mean_array, variance_array


def order_states_by_volatility(means: np.ndarray, variances: np.ndarray) -> np.ndarray:
    """State indices sorted from lowest to highest average variance.

    EM has a label-switching symmetry: swapping two states' parameters leaves
    the likelihood unchanged, so the integer a state receives depends on where
    the initialisation happened to start. An integer is therefore *not* a
    regime. Ranking by average emission variance turns those arbitrary integers
    into a stable ordering, which is the thing the downstream gate can compare
    across refits.

    Average variance across features is used rather than the first feature's, so
    the ordering is well defined for the multivariate case. Ties are broken by
    the original index (``kind="stable"``) so the ordering is a deterministic
    function of the parameters.

    Args:
        means: ``(n_states, n_features)`` state means.
        variances: ``(n_states, n_features)`` state variances.

    Returns:
        ``(n_states,)`` integer state indices, quietest first.

    Raises:
        ValueError: If the parameter arrays are not a valid matching pair.
    """
    _, variance_array = _validate_matrix_pair(means, variances)
    average_variance = variance_array.mean(axis=1)
    return np.argsort(average_variance, kind="stable").astype(int)


def label_states(
    means: np.ndarray,
    variances: np.ndarray,
    labels: Sequence[str] = DEFAULT_REGIME_LABELS,
) -> Dict[int, str]:
    """Map each state index to a regime label by volatility rank.

    The quietest state gets ``labels[0]`` (``"calm"``) and the noisiest gets
    ``labels[-1]`` (``"crisis"``). When the model has fewer states than the
    caller supplied labels, labels are sampled at even intervals across the
    ordered scale so the extremes are always preserved: two states over the
    default four labels become ``calm`` and ``crisis``, never ``calm`` and
    ``elevated``. Truncating the tuple instead would silently reserve the word
    "crisis" for a state that does not exist and label the most volatile state
    something milder than it is -- and a gate that blocks on "crisis" would then
    never fire.

    Args:
        means: ``(n_states, n_features)`` state means.
        variances: ``(n_states, n_features)`` state variances.
        labels: Ordered regime names, calmest to most stressed.

    Returns:
        ``{state_index: label}`` in the model's own integer indices.

    Raises:
        ValueError: If the parameter arrays are invalid, ``labels`` is empty, or
            fewer labels were supplied than there are states.
    """
    order = order_states_by_volatility(means, variances)
    n_states = int(order.size)

    names = [str(name) for name in labels]
    if not names:
        raise ValueError("labels must contain at least one regime name")
    if len(names) < n_states:
        raise ValueError(
            f"labels has {len(names)} entries but the model has {n_states} states; "
            "supply a label for every state"
        )

    if n_states == 1:
        chosen = [names[0]]
    else:
        positions = np.round(np.linspace(0, len(names) - 1, n_states)).astype(int)
        chosen = [names[int(position)] for position in positions]

    return {int(state): chosen[rank] for rank, state in enumerate(order)}


@dataclass(eq=False)
class GaussianHMM:
    """Baum-Welch (EM) fit of a hidden Markov model with Gaussian emissions.

    Each state ``j`` emits ``x_t`` from ``N(means[j], diag(variances[j]))`` and
    the hidden state follows a first-order Markov chain with row-stochastic
    ``transition`` and ``initial`` distribution. See the module docstring for
    what is and is not implemented -- in particular, these are diagonal-covariance
    Gaussian emissions, not the generalized hyperbolic emissions the plan
    ultimately wants.

    Args:
        n_states: Number of hidden states. At least 1.
        n_features: Number of observation columns. At least 1.
        variance_floor: Lower bound applied to every state variance. Keeps a
            state from collapsing onto a point, which would drive the
            likelihood to infinity.
        seed: Seed for the restart initialisation. ``None`` draws fresh entropy
            on every fit; a fixed seed makes a fit exactly reproducible.

    Attributes:
        means: ``(n_states, n_features)`` fitted state means, after ``fit``.
        variances: ``(n_states, n_features)`` fitted state variances.
        transition: ``(n_states, n_states)`` row-stochastic transition matrix.
        initial: ``(n_states,)`` initial state distribution, summing to 1.
        log_likelihood_history: Per-iteration total log-likelihood of the best
            restart, one entry per EM iteration actually run.
        restart_log_likelihoods: Final log-likelihood of every restart, in the
            order the restarts were run. The history kept is the arg-max.
    """

    n_states: int
    n_features: int = 1
    variance_floor: float = field(default=1e-6, kw_only=True)
    seed: Optional[int] = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if self.n_states < 1:
            raise ValueError(f"n_states must be at least 1, got {self.n_states}")
        if self.n_features < 1:
            raise ValueError(f"n_features must be at least 1, got {self.n_features}")
        if not np.isfinite(self.variance_floor) or self.variance_floor <= 0.0:
            raise ValueError(
                f"variance_floor must be a positive finite number, got "
                f"{self.variance_floor}"
            )

        self.n_states = int(self.n_states)
        self.n_features = int(self.n_features)
        self.variance_floor = float(self.variance_floor)
        self.seed = None if self.seed is None else int(self.seed)

        self.means: Optional[np.ndarray] = None
        self.variances: Optional[np.ndarray] = None
        self.transition: Optional[np.ndarray] = None
        self.initial: Optional[np.ndarray] = None
        self.log_likelihood_history: List[float] = []
        self.restart_log_likelihoods: List[float] = []

    # -- introspection -----------------------------------------------------

    @property
    def is_fitted(self) -> bool:
        """Whether ``fit`` has produced parameters."""
        return (
            self.means is not None
            and self.variances is not None
            and self.transition is not None
            and self.initial is not None
        )

    def _require_fitted(self, method: str) -> None:
        if not self.is_fitted:
            raise ValueError(
                f"GaussianHMM is not fitted; call fit() before {method}()"
            )

    def state_means(self) -> np.ndarray:
        """A copy of the fitted ``(n_states, n_features)`` means."""
        self._require_fitted("state_means")
        assert self.means is not None
        return self.means.copy()

    def state_variances(self) -> np.ndarray:
        """A copy of the fitted ``(n_states, n_features)`` variances."""
        self._require_fitted("state_variances")
        assert self.variances is not None
        return self.variances.copy()

    # -- input handling ----------------------------------------------------

    def _as_observations(self, X: np.ndarray) -> np.ndarray:
        """Coerce ``X`` to a finite ``(T, n_features)`` array or raise."""
        array = np.asarray(X, dtype=float)
        if array.ndim == 1:
            array = array.reshape(-1, 1)
        if array.ndim != 2:
            raise ValueError(
                f"X must be 1-D or 2-D, got {array.ndim} dimension(s)"
            )
        if array.shape[0] == 0:
            raise ValueError("X is empty; at least one observation is required")
        if array.shape[1] != self.n_features:
            raise ValueError(
                f"X must have {self.n_features} feature column(s), got shape "
                f"{array.shape}"
            )
        if not np.all(np.isfinite(array)):
            raise ValueError("X contains non-finite values (NaN or inf)")
        return array

    # -- emission ----------------------------------------------------------

    def _log_emission(
        self,
        data: np.ndarray,
        means: np.ndarray,
        variances: np.ndarray,
    ) -> np.ndarray:
        """``(T, n_states)`` log Gaussian density of each observation per state."""
        difference = data[:, None, :] - means[None, :, :]
        quadratic = np.einsum(
            "tkd,tkd->tk", difference, difference / variances[None, :, :]
        )
        log_normaliser = np.sum(np.log(2.0 * np.pi * variances), axis=1)
        return -0.5 * (quadratic + log_normaliser[None, :])

    # -- scaled forward/backward ------------------------------------------

    def _forward(
        self,
        log_emission: np.ndarray,
        initial: np.ndarray,
        transition: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Scaled forward pass in log space.

        Returns ``(log_alpha, log_c)`` where ``log_alpha`` rows are normalised
        (``exp`` of each row sums to 1) and ``log_c[t]`` is the log of the
        per-step normaliser. The total log-likelihood is ``sum(log_c)``.
        """
        n_observations, n_states = log_emission.shape
        log_transition = _log_probabilities(transition)

        log_alpha = np.empty((n_observations, n_states), dtype=float)
        log_scale = np.empty(n_observations, dtype=float)

        current = _log_probabilities(initial) + log_emission[0]
        log_scale[0] = _logsumexp(current, axis=0)
        log_alpha[0] = current - log_scale[0]

        for step in range(1, n_observations):
            current = (
                _logsumexp(log_alpha[step - 1][:, None] + log_transition, axis=0)
                + log_emission[step]
            )
            log_scale[step] = _logsumexp(current, axis=0)
            log_alpha[step] = current - log_scale[step]

        return log_alpha, log_scale

    def _backward(
        self,
        log_emission: np.ndarray,
        log_scale: np.ndarray,
        transition: np.ndarray,
    ) -> np.ndarray:
        """Scaled backward pass in log space, matching ``_forward``."""
        n_observations, n_states = log_emission.shape
        log_transition = _log_probabilities(transition)
        log_beta = np.zeros((n_observations, n_states), dtype=float)

        for step in range(n_observations - 2, -1, -1):
            contribution = log_emission[step + 1] + log_beta[step + 1]
            log_beta[step] = (
                _logsumexp(
                    log_transition + contribution[None, :], axis=1
                )
                - log_scale[step + 1]
            )

        return log_beta

    def _expectations(
        self,
        log_alpha: np.ndarray,
        log_beta: np.ndarray,
        log_emission: np.ndarray,
        transition: np.ndarray,
        log_scale: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Smoothed state posteriors ``gamma`` and summed pairwise ``xi``."""
        log_transition = _log_probabilities(transition)
        n_observations = log_emission.shape[0]

        log_gamma = log_alpha + log_beta
        gamma = np.exp(log_gamma)
        row_totals = gamma.sum(axis=1, keepdims=True)
        # Rows should already sum to one; renormalising removes the round-off
        # that would otherwise make the M-step denominators inconsistent.
        gamma = np.divide(
            gamma,
            row_totals,
            out=np.full_like(gamma, 1.0 / self.n_states),
            where=row_totals > 0.0,
        )

        if n_observations > 1:
            log_xi = (
                log_alpha[:-1, :, None]
                + log_transition[None, :, :]
                + (log_emission[1:] + log_beta[1:])[:, None, :]
                - log_scale[1:, None, None]
            )
            xi_sum = np.sum(np.exp(log_xi), axis=0)
        else:
            xi_sum = np.zeros((self.n_states, self.n_states), dtype=float)

        return gamma, xi_sum

    # -- EM ----------------------------------------------------------------

    def _random_initialisation(
        self, rng: np.random.Generator, data: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """One random parameter draw for a restart.

        Means are seeded k-means++ style -- far-apart observations are preferred
        -- because a purely uniform draw frequently places two initial means
        inside the same true state, and EM then needs many iterations (or
        restarts) to separate them. The spread is still random, so restarts
        explore different basins; the seeding only avoids the obviously bad
        ones.
        """
        n_observations = data.shape[0]
        n_states = self.n_states
        global_variance = np.maximum(
            data.var(axis=0), self.variance_floor
        )

        if n_states == 1:
            means = data.mean(axis=0, keepdims=True)
            variances = np.maximum(
                data.var(axis=0, keepdims=True), self.variance_floor
            )
            transition = np.ones((1, 1), dtype=float)
            initial = np.ones(1, dtype=float)
            return means, variances, transition, initial

        first = int(rng.integers(n_observations))
        chosen = [first]
        for _ in range(1, n_states):
            picked = data[chosen]
            distances = np.min(
                np.sum((data[:, None, :] - picked[None, :, :]) ** 2, axis=2),
                axis=1,
            )
            total = float(distances.sum())
            if not np.isfinite(total) or total <= 0.0:
                chosen.append(int(rng.integers(n_observations)))
            else:
                chosen.append(int(rng.choice(n_observations, p=distances / total)))

        scale = np.sqrt(global_variance)
        scale = np.where(scale > 0.0, scale, 1.0)
        means = data[chosen].copy()
        # A nudge so duplicate observations cannot produce two identical states.
        means = means + rng.normal(scale=1e-3, size=means.shape) * scale[None, :]

        variances = np.tile(global_variance[None, :], (n_states, 1))
        variances = variances * rng.uniform(0.5, 1.5, size=variances.shape)
        variances = np.maximum(variances, self.variance_floor)

        persistence = rng.uniform(0.6, 0.95, size=n_states)
        transition = np.empty((n_states, n_states), dtype=float)
        for state in range(n_states):
            transition[state] = (1.0 - persistence[state]) / (n_states - 1)
            transition[state, state] = persistence[state]

        initial = rng.dirichlet(np.ones(n_states))
        return means, variances, transition, initial

    def _maximise(
        self,
        data: np.ndarray,
        gamma: np.ndarray,
        xi_sum: np.ndarray,
        means: np.ndarray,
        variances: np.ndarray,
        transition: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Closed-form Gaussian M-step given the expectations.

        A state that received (numerically) no responsibility is left at its
        previous parameters rather than divided by a near-zero denominator,
        which would produce ``nan``. Variances are floored so no state can
        collapse onto a point.
        """
        n_observations = data.shape[0]
        responsibility = gamma.sum(axis=0)
        active = responsibility > _ACTIVE_RESPONSIBILITY
        safe = np.where(active, responsibility, 1.0)

        new_means = (gamma.T @ data) / safe[:, None]
        difference = data[:, None, :] - new_means[None, :, :]
        new_variances = (
            np.einsum("tk,tkd->kd", gamma, difference**2) / safe[:, None]
        )

        new_means = np.where(active[:, None], new_means, means)
        new_variances = np.where(active[:, None], new_variances, variances)
        new_variances = np.maximum(new_variances, self.variance_floor)

        if n_observations > 1:
            row_mass = gamma[:-1].sum(axis=0)
            active_rows = row_mass > _ACTIVE_RESPONSIBILITY
            safe_rows = np.where(active_rows, row_mass, 1.0)
            new_transition = xi_sum / safe_rows[:, None]
            new_transition = np.where(
                active_rows[:, None], new_transition, transition
            )
            new_transition = np.maximum(new_transition, 0.0)
            row_sums = new_transition.sum(axis=1, keepdims=True)
            new_transition = np.divide(
                new_transition,
                row_sums,
                out=np.full_like(new_transition, 1.0 / self.n_states),
                where=row_sums > 0.0,
            )
        else:
            new_transition = transition

        new_initial = np.maximum(gamma[0], 0.0)
        total = new_initial.sum()
        if total > 0.0:
            new_initial = new_initial / total
        else:
            new_initial = np.full(self.n_states, 1.0 / self.n_states)

        return new_means, new_variances, new_transition, new_initial

    def _fit_once(
        self,
        data: np.ndarray,
        parameters: Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
        max_iterations: int,
        tolerance: float,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, List[float]]:
        """Baum-Welch from one initialisation.

        Each iteration performs an E-step under the current parameters, then the
        M-step, then **re-scores the updated parameters**. Re-scoring costs one
        extra forward pass and buys two things: the history is the likelihood of
        the parameter sets EM actually produced, so the monotonicity property is
        asserted about the fit and not about a shifted sequence, and
        ``history[-1]`` equals ``log_likelihood`` of the returned parameters.
        """
        means, variances, transition, initial = parameters
        means = means.copy()
        variances = variances.copy()
        transition = transition.copy()
        initial = initial.copy()

        history: List[float] = []
        for iteration in range(max_iterations):
            log_emission = self._log_emission(data, means, variances)
            log_alpha, log_scale = self._forward(log_emission, initial, transition)
            log_beta = self._backward(log_emission, log_scale, transition)
            gamma, xi_sum = self._expectations(
                log_alpha, log_beta, log_emission, transition, log_scale
            )
            means, variances, transition, initial = self._maximise(
                data, gamma, xi_sum, means, variances, transition
            )

            scored_emission = self._log_emission(data, means, variances)
            _, scored_scale = self._forward(
                scored_emission, initial, transition
            )
            likelihood = float(np.sum(scored_scale))
            history.append(likelihood)

            if iteration > 0 and (likelihood - history[-2]) < tolerance:
                break

        return means, variances, transition, initial, history

    def fit(
        self,
        X: np.ndarray,
        *,
        max_iterations: int = 100,
        tolerance: float = 1e-6,
        n_restarts: int = 1,
    ) -> List[float]:
        """Fit by Baum-Welch EM and return the per-iteration log-likelihood.

        ``n_restarts`` independent random initialisations are run and the one
        with the highest final log-likelihood is kept. The likelihood surface of
        an HMM has many local maxima, so a single run is a draw, not an answer;
        reporting the best of several and the spread between them is the honest
        form of the result.

        Args:
            X: ``(T, n_features)`` observations.
            max_iterations: Cap on EM iterations per restart.
            tolerance: Stop when an iteration improves the log-likelihood by
                less than this.
            n_restarts: Number of random initialisations. At least 1.

        Returns:
            The retained restart's log-likelihood per iteration.

        Raises:
            ValueError: If ``X`` is malformed, or the controls are out of range.
        """
        data = self._as_observations(X)
        if max_iterations < 1:
            raise ValueError(
                f"max_iterations must be at least 1, got {max_iterations}"
            )
        if not np.isfinite(tolerance) or tolerance <= 0.0:
            raise ValueError(
                f"tolerance must be a positive finite number, got {tolerance}"
            )
        if n_restarts < 1:
            raise ValueError(f"n_restarts must be at least 1, got {n_restarts}")

        rng = np.random.default_rng(self.seed)
        best_likelihood = -np.inf
        best_parameters: Optional[
            Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]
        ] = None
        best_history: List[float] = []
        restart_likelihoods: List[float] = []

        for _ in range(n_restarts):
            parameters = self._random_initialisation(rng, data)
            means, variances, transition, initial, history = self._fit_once(
                data, parameters, max_iterations, tolerance
            )
            final_likelihood = history[-1] if history else -np.inf
            restart_likelihoods.append(float(final_likelihood))
            if final_likelihood > best_likelihood:
                best_likelihood = float(final_likelihood)
                best_parameters = (means, variances, transition, initial)
                best_history = history

        assert best_parameters is not None
        self.means, self.variances, self.transition, self.initial = best_parameters
        self.log_likelihood_history = list(best_history)
        self.restart_log_likelihoods = restart_likelihoods
        return list(self.log_likelihood_history)

    # -- inference ---------------------------------------------------------

    def log_likelihood(self, X: np.ndarray) -> float:
        """Total ``log p(X)`` under the fitted parameters.

        Raises:
            ValueError: If the model is not fitted or ``X`` is malformed.
        """
        self._require_fitted("log_likelihood")
        data = self._as_observations(X)
        assert self.means is not None
        assert self.variances is not None
        assert self.transition is not None
        assert self.initial is not None

        log_emission = self._log_emission(data, self.means, self.variances)
        _, log_scale = self._forward(log_emission, self.initial, self.transition)
        return float(np.sum(log_scale))

    def posteriors(self, X: np.ndarray) -> np.ndarray:
        """Smoothed state posteriors ``(T, n_states)``, each row summing to 1.

        Raises:
            ValueError: If the model is not fitted or ``X`` is malformed.
        """
        self._require_fitted("posteriors")
        data = self._as_observations(X)
        assert self.means is not None
        assert self.variances is not None
        assert self.transition is not None
        assert self.initial is not None

        log_emission = self._log_emission(data, self.means, self.variances)
        log_alpha, log_scale = self._forward(
            log_emission, self.initial, self.transition
        )
        log_beta = self._backward(log_emission, log_scale, self.transition)
        gamma, _ = self._expectations(
            log_alpha, log_beta, log_emission, self.transition, log_scale
        )
        return np.clip(gamma, 0.0, 1.0)

    def viterbi(self, X: np.ndarray) -> np.ndarray:
        """Most likely hidden state sequence ``(T,)`` of integer indices.

        Runs the max-product recursion in log space, so the same underflow
        argument as the forward pass applies.

        Raises:
            ValueError: If the model is not fitted or ``X`` is malformed.
        """
        self._require_fitted("viterbi")
        data = self._as_observations(X)
        assert self.means is not None
        assert self.variances is not None
        assert self.transition is not None
        assert self.initial is not None

        log_emission = self._log_emission(data, self.means, self.variances)
        log_transition = _log_probabilities(self.transition)
        n_observations, n_states = log_emission.shape

        log_delta = np.empty((n_observations, n_states), dtype=float)
        backtrack = np.zeros((n_observations, n_states), dtype=int)

        log_delta[0] = _log_probabilities(self.initial) + log_emission[0]
        for step in range(1, n_observations):
            scores = log_delta[step - 1][:, None] + log_transition
            backtrack[step] = np.argmax(scores, axis=0)
            log_delta[step] = (
                scores[backtrack[step], np.arange(n_states)] + log_emission[step]
            )

        path = np.empty(n_observations, dtype=int)
        path[-1] = int(np.argmax(log_delta[-1]))
        for step in range(n_observations - 2, -1, -1):
            path[step] = backtrack[step + 1, path[step + 1]]
        return path

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Alias for :meth:`viterbi`, for callers using the ``predict`` convention."""
        return self.viterbi(X)

    def label_series(
        self,
        X: np.ndarray,
        labels: Sequence[str] = DEFAULT_REGIME_LABELS,
    ) -> np.ndarray:
        """Viterbi path translated into regime labels via :func:`label_states`.

        This is the end-to-end product the attestation gate consumes: a label
        per observation drawn only from ``labels``, with the mapping fixed by
        variance rank so it cannot drift with the arbitrary integer EM assigned.

        Raises:
            ValueError: If the model is not fitted, ``X`` is malformed, or there
                are fewer labels than states.
        """
        path = self.viterbi(X)
        assert self.means is not None
        assert self.variances is not None
        mapping = label_states(self.means, self.variances, labels)
        return np.array([mapping[int(state)] for state in path], dtype=str)

    # -- serialisation -----------------------------------------------------

    def to_dict(self) -> Dict[str, object]:
        """JSON-serialisable snapshot of the fitted model.

        Every value is a Python ``float``/``int``/``list`` -- numpy scalars do
        not survive ``json.dumps`` and, worse, a bare ``numpy.float64`` is not
        caught by ``allow_nan=False`` checks the way a Python float is.

        Raises:
            ValueError: If the model is not fitted.
        """
        self._require_fitted("to_dict")
        assert self.means is not None
        assert self.variances is not None
        assert self.transition is not None
        assert self.initial is not None

        return {
            "n_states": int(self.n_states),
            "n_features": int(self.n_features),
            "variance_floor": float(self.variance_floor),
            "seed": None if self.seed is None else int(self.seed),
            "fitted": True,
            "means": [[float(value) for value in row] for row in self.means],
            "variances": [
                [float(value) for value in row] for row in self.variances
            ],
            "transition": [
                [float(value) for value in row] for row in self.transition
            ],
            "initial": [float(value) for value in self.initial],
            "state_order": [
                int(state)
                for state in order_states_by_volatility(
                    self.means, self.variances
                )
            ],
            "log_likelihood_history": [
                float(value) for value in self.log_likelihood_history
            ],
            "restart_log_likelihoods": [
                float(value) for value in self.restart_log_likelihoods
            ],
            "log_likelihood": (
                float(self.log_likelihood_history[-1])
                if self.log_likelihood_history
                else None
            ),
        }
