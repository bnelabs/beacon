"""Tests for the neural SDE memory.

The SDE is checked against closed forms wherever one exists, because a
stochastic integrator that merely *runs* proves nothing. Three independent
anchors are used and each one is stated before it is asserted:

* a **known law** -- constant drift and constant diffusion give the terminal law
  ``N(z0 + mu*T, sigma^2*T)`` exactly under Euler-Maruyama, so the empirical
  moments differ from the closed form only by Monte Carlo error;
* a **known path** -- geometric Brownian motion has an exact solution, so the
  strong (pathwise) error of each scheme can be measured and its refinement rate
  compared with the theoretical order;
* an **exact reduction** -- with ``g == 0`` the noise is multiplied by exactly
  zero, so the SDE must collapse onto the deterministic ODE bit-for-bit, which is
  checked against the temporal graph's own RK4 integrator rather than against a
  second implementation of the same idea.

Monte Carlo tolerances are stated as a multiple of the standard error of the
statistic being tested, not as numbers chosen to pass. Where the measured rate is
reported, the noise in it is reported too.
"""

from __future__ import annotations

import json
import math
from typing import Dict, List, Sequence

import pytest
import torch
import torch.nn as nn

from backend.modules.engine.neural_sde import (
    INTEGRATORS,
    ConstantDiffusion,
    DiagonalDiffusion,
    DriftField,
    NeuralSDEMemory,
    SDEPath,
    ZeroDiffusion,
    diagonal_derivative,
    euler_maruyama_step,
    milstein_step,
    simulate_paths,
)
from backend.modules.engine.temporal_graph import (
    MemoryState,
    NeuralODEField,
    TemporalGraphMemory,
    rk4_integrate,
)

DTYPE = torch.float64


# ---------------------------------------------------------------------------
# Reference processes
# ---------------------------------------------------------------------------

def constant_drift(mu: float):
    def drift(state: torch.Tensor, time: torch.Tensor) -> torch.Tensor:
        return torch.full_like(state, mu)

    return drift


def linear_drift(rate: float):
    def drift(state: torch.Tensor, time: torch.Tensor) -> torch.Tensor:
        return -rate * state

    return drift


class GeometricBrownianDiffusion(nn.Module):
    """``g(z, t) = sigma * z`` for geometric Brownian motion.

    Its diagonal derivative is closed form, ``dg/dz = sigma``, so the Milstein
    correction is checked against a hand-computed coefficient rather than against
    an autodiff result that could hide a sign error.
    """

    def __init__(self, sigma: float) -> None:
        super().__init__()
        self.sigma = float(sigma)

    def forward(self, state: torch.Tensor, time: torch.Tensor) -> torch.Tensor:
        return self.sigma * state

    def derivative(self, state: torch.Tensor, time: torch.Tensor) -> torch.Tensor:
        return torch.full_like(state, self.sigma)


def gbm_drift(mu: float):
    def drift(state: torch.Tensor, time: torch.Tensor) -> torch.Tensor:
        return mu * state

    return drift


def zero_drift(state: torch.Tensor, time: torch.Tensor) -> torch.Tensor:
    return torch.zeros_like(state)


# ---------------------------------------------------------------------------
# Diffusion parameterisation
# ---------------------------------------------------------------------------

class TestDiagonalDiffusion:
    def test_the_diffusion_coefficient_is_strictly_positive(self):
        """The property the SDE needs: ``g`` is a variance rate, so ``g > 0``.

        The inputs deliberately include very large negative states, where a
        naive linear parameterisation would go negative.
        """
        diffusion = DiagonalDiffusion(4)
        states = torch.tensor(
            [
                [-1e6, -1e3, -1.0, 0.0],
                [1.0, 1e3, 1e6, -0.5],
                [-50.0, 50.0, -1e8, 1e8],
            ]
        )
        for row in states:
            g = diffusion(row.reshape(1, -1), torch.tensor([0.0]))
            assert bool((g > 0.0).all()), row

    def test_the_floor_is_a_lower_bound_even_for_an_extreme_network(self):
        """A saturating network cannot drive the diffusion to zero.

        The output bias is set to a large negative number so ``softplus``
        underflows; the coefficient must still sit at the floor, not at zero.
        Driving it to zero would silently turn the SDE back into the ODE and
        destroy exactly the heteroskedasticity this module exists for.
        """
        floor = 1e-2
        diffusion = DiagonalDiffusion(3, floor=floor)
        with torch.no_grad():
            # Only the output bias is driven down; the hidden activations stay
            # bounded, so the pre-activation is enormously negative and softplus
            # underflows to zero. (Driving the output weight down too would make
            # the two large terms cancel and defeat the test.)
            diffusion.net[-1].bias.fill_(-1e9)
        g = diffusion(torch.tensor([[0.0, -5.0, 5.0]]), torch.tensor([0.0]))
        assert bool((g > 0.0).all())
        assert torch.allclose(g, torch.full_like(g, floor), rtol=1e-5, atol=0.0)

    def test_a_randomly_initialised_network_is_also_positive(self):
        torch.manual_seed(0)
        diffusion = DiagonalDiffusion(6, hidden_dim=16)
        states = torch.randn(64, 6) * 100.0
        g = diffusion(states, torch.zeros(64))
        assert bool((g > 0.0).all())

    def test_the_diffusion_varies_with_the_state(self):
        """Positivity must not come at the cost of being constant."""
        torch.manual_seed(1)
        diffusion = DiagonalDiffusion(2, hidden_dim=16)
        g = diffusion(torch.tensor([[-3.0, 0.0], [3.0, 3.0]]), torch.tensor([0.0, 1.0]))
        assert not torch.allclose(g[0], g[1])

    def test_derivative_is_the_diagonal_dg_dz(self):
        """Check the Milstein coefficient against a hand-computed value.

        With one hidden unit, an identity second layer and only the state input
        wired, the composition is ``g = floor + softplus(tanh(a*z))``, whose
        exact derivative is
        ``sigmoid(tanh(a*z)) * a * (1 - tanh(a*z)^2)``. Deriving the value by
        hand is the point: an autodiff-only check would accept a wrong formula,
        and the Milstein correction's sign and scale both depend on it.
        """
        diffusion = DiagonalDiffusion(1, hidden_dim=1, floor=0.5)
        with torch.no_grad():
            # Layer 0: [state, cos(t), sin(t)] -> one hidden unit.
            diffusion.net[0].weight.zero_()
            diffusion.net[0].weight[0, 0] = 2.0
            diffusion.net[0].bias.zero_()
            # Layer 2: hidden -> 1, weight 1, bias 0.
            diffusion.net[2].weight.fill_(1.0)
            diffusion.net[2].bias.zero_()

        state = torch.tensor([[0.75]])
        time = torch.tensor([0.0])
        inner = math.tanh(2.0 * 0.75)
        expected = torch.sigmoid(torch.tensor(inner)) * 2.0 * (1.0 - inner ** 2)
        got = diffusion.derivative(state, time)
        assert float(got[0, 0]) == pytest.approx(float(expected), rel=1e-5)

    def test_validation(self):
        with pytest.raises(ValueError, match="state_dim"):
            DiagonalDiffusion(0)
        with pytest.raises(ValueError, match="hidden_dim"):
            DiagonalDiffusion(2, hidden_dim=0)
        with pytest.raises(ValueError, match="strictly positive"):
            DiagonalDiffusion(2, floor=0.0)
        with pytest.raises(ValueError, match="strictly positive"):
            DiagonalDiffusion(2, floor=-1.0)
        with pytest.raises(ValueError, match="finite"):
            DiagonalDiffusion(2, floor=float("inf"))


class TestConstantAndZeroDiffusion:
    def test_constant_diffusion_is_constant_with_zero_derivative(self):
        diffusion = ConstantDiffusion(0.7)
        state = torch.tensor([[1.0, -2.0]])
        g = diffusion(state, torch.tensor([0.0]))
        assert torch.allclose(g, torch.full_like(state, 0.7))
        assert torch.allclose(diffusion.derivative(state, torch.tensor([0.0])), torch.zeros_like(state))

    def test_zero_diffusion_is_exactly_zero(self):
        diffusion = ZeroDiffusion()
        state = torch.tensor([[1.0, -2.0]])
        assert torch.equal(diffusion(state, torch.tensor([0.0])), torch.zeros_like(state))
        assert torch.equal(diffusion.derivative(state, torch.tensor([0.0])), torch.zeros_like(state))

    def test_validation(self):
        with pytest.raises(ValueError, match="non-negative"):
            ConstantDiffusion(-0.1)
        with pytest.raises(ValueError, match="finite"):
            ConstantDiffusion(float("nan"))

    def test_the_autograd_fallback_recovers_a_known_derivative(self):
        """A plain callable without a ``derivative`` method must still work.

        ``g(z) = sigma * z`` has ``dg/dz = sigma``, so the fallback is checked
        against a hand-computed number.
        """
        sigma = 0.35
        state = torch.tensor([[1.0, 2.0, 3.0]])
        got = diagonal_derivative(
            lambda z, t: sigma * z, state, torch.tensor([0.0])
        )
        assert torch.allclose(got, torch.full_like(state, sigma))

    def test_the_autograd_fallback_rejects_a_non_callable(self):
        with pytest.raises(ValueError, match="callable"):
            diagonal_derivative(object(), torch.zeros(1), torch.zeros(1))


class TestDriftField:
    def test_a_zero_network_reduces_the_field_to_decay(self):
        field = DriftField(4, rate=0.25)
        with torch.no_grad():
            for parameter in field.net.parameters():
                parameter.zero_()
        state = torch.tensor([[1.0, 2.0, 3.0, 4.0]])
        derivative = field(state, torch.tensor([0.0]))
        assert torch.allclose(derivative, -0.25 * state, atol=1e-6)

    def test_the_field_matches_the_temporal_graph_convention(self):
        """Same call signature and same output as ``NeuralODEField``.

        Aliasing the weights is what makes the claim checkable rather than
        stylistic: if the two modules agree on weights, they must agree on
        outputs.
        """
        seed = 11
        torch.manual_seed(seed)
        reference = NeuralODEField(3, hidden_dim=8, rate=0.2)
        candidate = DriftField(3, hidden_dim=8, rate=0.2)
        candidate.load_state_dict(reference.state_dict())
        state = torch.tensor([[0.3, -0.4, 0.5]])
        time = torch.tensor([1.25])
        assert torch.allclose(candidate(state, time), reference(state, time), atol=1e-6)

    def test_validation(self):
        with pytest.raises(ValueError, match="state_dim"):
            DriftField(0)
        with pytest.raises(ValueError, match="hidden_dim"):
            DriftField(2, hidden_dim=0)
        with pytest.raises(ValueError, match="rate"):
            DriftField(2, rate=0.0)


# ---------------------------------------------------------------------------
# Integrator steps
# ---------------------------------------------------------------------------

class TestIntegratorSteps:
    def test_milstein_reduces_to_euler_for_a_constant_diffusion(self):
        """The Milstein correction is ``0.5 * g * (dg/dz) * (dW^2 - dt)``.

        With ``dg/dz == 0`` exactly the correction is exactly zero, so the two
        schemes must agree bit-for-bit -- not merely approximately.
        """
        state = torch.tensor([[1.0, 2.0]], dtype=DTYPE)
        time = torch.tensor([0.0], dtype=DTYPE)
        dW = torch.tensor([[0.3, -0.2]], dtype=DTYPE)
        mu = constant_drift(0.4)
        g = ConstantDiffusion(0.9)
        euler = euler_maruyama_step(mu, g, state, time, 0.01, dW)
        milstein = milstein_step(mu, g, state, time, 0.01, dW)
        assert torch.equal(euler, milstein)

    def test_steps_validate_dt(self):
        state = torch.ones(2, 1, dtype=DTYPE)
        time = torch.zeros(1, dtype=DTYPE)
        dW = torch.zeros(2, 1, dtype=DTYPE)
        for bad in (0.0, -1.0, float("nan"), float("inf")):
            with pytest.raises(ValueError, match="dt"):
                euler_maruyama_step(zero_drift, ZeroDiffusion(), state, time, bad, dW)
            with pytest.raises(ValueError, match="dt"):
                milstein_step(zero_drift, ZeroDiffusion(), state, time, bad, dW)

    def test_steps_validate_the_noise_shape(self):
        state = torch.ones(2, 3, dtype=DTYPE)
        time = torch.zeros(2, dtype=DTYPE)
        with pytest.raises(ValueError, match="dW"):
            euler_maruyama_step(zero_drift, ZeroDiffusion(), state, time, 0.1, torch.zeros(2, 4, dtype=DTYPE))

    def test_steps_validate_the_state(self):
        with pytest.raises(ValueError, match="floating"):
            euler_maruyama_step(zero_drift, ZeroDiffusion(), torch.ones(2, dtype=torch.int64), torch.zeros(2), 0.1, torch.zeros(2))
        with pytest.raises(ValueError, match="non-finite"):
            euler_maruyama_step(zero_drift, ZeroDiffusion(), torch.tensor([1.0, float("nan")], dtype=DTYPE), torch.zeros(2), 0.1, torch.zeros(2))

    def test_steps_validate_drift_and_diffusion_shapes(self):
        state = torch.ones(2, 1, dtype=DTYPE)
        time = torch.zeros(2, dtype=DTYPE)
        dW = torch.zeros(2, 1, dtype=DTYPE)
        with pytest.raises(ValueError, match="drift"):
            euler_maruyama_step(lambda z, t: z.sum(), ZeroDiffusion(), state, time, 0.1, dW)

        class BadDiffusion(nn.Module):
            def forward(self, z, t):
                return z.sum()

            def derivative(self, z, t):
                return torch.zeros(1)

        with pytest.raises(ValueError, match="diffusion"):
            euler_maruyama_step(zero_drift, BadDiffusion(), state, time, 0.1, dW)

        class BadDerivative(nn.Module):
            def forward(self, z, t):
                return torch.zeros_like(z)

            def derivative(self, z, t):
                return torch.zeros(1)

        with pytest.raises(ValueError, match="diffusion derivative"):
            milstein_step(zero_drift, BadDerivative(), state, time, 0.1, dW)


# ---------------------------------------------------------------------------
# Known law
# ---------------------------------------------------------------------------

class TestKnownLaw:
    """Euler-Maruyama is exact in law for constant coefficients.

    With ``f = mu`` and ``g = sigma`` the scheme gives
    ``z_T = z0 + mu*T + sigma * sum_k dW_k`` and ``sum_k dW_k ~ N(0, T)``
    exactly, so the terminal law is ``N(z0 + mu*T, sigma^2*T)`` with no
    discretisation error. Any deviation of the empirical moments is Monte Carlo
    error, and the tolerance below is stated as a multiple of it.
    """

    MU = 0.25
    SIGMA = 0.6
    Z0 = 1.0
    T = 1.0
    N_PATHS = 20000
    STEPS = 32
    SEED = 12345
    #: Standard error of the empirical mean: sigma * sqrt(T) / sqrt(N).
    SE_MEAN = SIGMA * math.sqrt(T) / math.sqrt(N_PATHS)
    #: Standard error of the unbiased variance estimator for Gaussian draws.
    SE_VAR = SIGMA ** 2 * T * math.sqrt(2.0 / (N_PATHS - 1))

    def _path(self) -> SDEPath:
        return simulate_paths(
            constant_drift(self.MU),
            ConstantDiffusion(self.SIGMA),
            torch.tensor([self.Z0], dtype=DTYPE),
            t0=0.0,
            t1=self.T,
            steps=self.STEPS,
            n_paths=self.N_PATHS,
            seed=self.SEED,
        )

    def test_the_empirical_mean_matches_the_closed_form(self):
        terminal = self._path().terminal().reshape(-1)
        empirical = float(terminal.mean())
        closed = self.Z0 + self.MU * self.T
        deviation = abs(empirical - closed) / self.SE_MEAN
        assert deviation < 4.0, (
            f"mean {empirical} vs closed form {closed}; deviation {deviation:.2f} "
            f"standard errors (SE = {self.SE_MEAN:.6f})"
        )

    def test_the_empirical_variance_matches_the_closed_form(self):
        terminal = self._path().terminal().reshape(-1)
        empirical = float(terminal.var(unbiased=True))
        closed = self.SIGMA ** 2 * self.T
        deviation = abs(empirical - closed) / self.SE_VAR
        assert deviation < 4.0, (
            f"variance {empirical} vs closed form {closed}; deviation "
            f"{deviation:.2f} standard errors (SE = {self.SE_VAR:.6f})"
        )

    def test_the_integrated_diffusion_is_exactly_sigma_squared_T(self):
        """A deterministic quantity: ``sum_k sigma^2 * dt = sigma^2 * T``."""
        path = self._path()
        expected = self.SIGMA ** 2 * self.T
        assert torch.allclose(
            path.integrated_diffusion,
            torch.full_like(path.integrated_diffusion, expected),
            rtol=0.0,
            atol=1e-12,
        )

    def test_the_time_grid_spans_the_horizon(self):
        path = self._path()
        assert path.times.shape == (self.STEPS + 1,)
        assert float(path.times[0]) == pytest.approx(0.0)
        assert float(path.times[-1]) == pytest.approx(self.T)
        assert path.states.shape == (self.N_PATHS, self.STEPS + 1, 1)
        assert path.drift.shape == (self.N_PATHS, self.STEPS, 1)
        assert path.diffusion.shape == (self.N_PATHS, self.STEPS, 1)

    def test_a_vector_valued_process_is_handled_coordinatewise(self):
        """Independent coordinates must reproduce each coordinate's own law."""
        mu, sigma, z0 = 0.1, 0.4, torch.tensor([1.0, 2.0, 3.0], dtype=DTYPE)
        path = simulate_paths(
            constant_drift(mu),
            ConstantDiffusion(sigma),
            z0,
            t0=0.0,
            t1=0.5,
            steps=16,
            n_paths=8000,
            seed=77,
        )
        terminal = path.terminal()
        assert terminal.shape == (8000, 3)
        se = sigma * math.sqrt(0.5) / math.sqrt(8000)
        for coordinate in range(3):
            empirical = float(terminal[:, coordinate].mean())
            closed = float(z0[coordinate]) + mu * 0.5
            assert abs(empirical - closed) < 4.0 * se


# ---------------------------------------------------------------------------
# Strong order
# ---------------------------------------------------------------------------

def gbm_strong_errors(
    mu: float,
    sigma: float,
    s0: float,
    n_paths: int,
    finest_steps: int,
    resolutions: Sequence[int],
    seed: int,
) -> Dict[str, List[float]]:
    """Strong error ``E|z_T - S_T|`` for each scheme at each resolution.

    One Brownian path per sample is generated at the finest resolution and the
    coarser increments are obtained by summing the finer ones, so the sample is
    *nested* across resolutions. Without nesting the coarse and fine paths would
    be independent draws and the refinement ratio would be swamped by Monte Carlo
    noise; with it, the only remaining noise is in the mean of ``|error|``.
    """
    generator = torch.Generator().manual_seed(seed)
    fine = torch.randn(
        n_paths, finest_steps, generator=generator, dtype=DTYPE
    ) * math.sqrt(1.0 / finest_steps)

    errors: Dict[str, List[float]] = {name: [] for name in INTEGRATORS}
    for steps in resolutions:
        factor = finest_steps // steps
        dW = fine.reshape(n_paths, steps, factor).sum(dim=-1)
        brownian = dW.cumsum(dim=1)
        exact = s0 * torch.exp(
            (mu - 0.5 * sigma ** 2) * 1.0 + sigma * brownian[:, -1]
        )
        for name, step_fn in INTEGRATORS.items():
            state = torch.full((n_paths, 1), s0, dtype=DTYPE)
            dt = 1.0 / steps
            for index in range(steps):
                time = torch.full((n_paths,), index * dt, dtype=DTYPE)
                state = step_fn(
                    gbm_drift(mu),
                    GeometricBrownianDiffusion(sigma),
                    state,
                    time,
                    dt,
                    dW[:, index:index + 1],
                )
            errors[name].append(float((state[:, 0] - exact).abs().mean()))
    return errors


class TestStrongOrder:
    """Geometry Brownian motion has an exact solution, so strong error is measurable.

    ``dS = mu*S dt + sigma*S dW`` with ``S_T = S_0 exp((mu - sigma^2/2)T + sigma W_T)``.
    The theoretical strong orders are 0.5 (Euler-Maruyama) and 1.0 (Milstein).
    """

    MU = 0.1
    SIGMA = 0.5
    S0 = 1.0
    N_PATHS = 4096
    FINEST_STEPS = 256
    RESOLUTIONS = (16, 32, 64, 128)
    SEED = 2024

    def _errors(self) -> Dict[str, List[float]]:
        return gbm_strong_errors(
            self.MU,
            self.SIGMA,
            self.S0,
            self.N_PATHS,
            self.FINEST_STEPS,
            self.RESOLUTIONS,
            self.SEED,
        )

    def test_milstein_is_more_accurate_than_euler_at_every_step_size(self):
        errors = self._errors()
        for index, steps in enumerate(self.RESOLUTIONS):
            assert errors["milstein"][index] < errors["euler_maruyama"][index], (
                f"at {steps} steps, milstein {errors['milstein'][index]:.4e} "
                f"vs euler {errors['euler_maruyama'][index]:.4e}"
            )
        # Measured at the finest grid the margin is roughly 28x; require 5x so the
        # claim survives a different seed without being an accident of this one.
        ratio = errors["euler_maruyama"][-1] / errors["milstein"][-1]
        assert ratio > 5.0, f"only {ratio:.1f}x improvement at the finest grid"

    def test_the_observed_strong_rates_match_the_theoretical_orders(self):
        """Refinement rates, with the Monte Carlo noise they carry.

        Each error is a mean over 4096 nested paths, so its relative standard
        error is a little over 1%; a rate is a log2 ratio of two such means, so
        a single rate is uncertain by roughly +/- 0.05. The measured per-pair
        rates for this seed are Euler 0.49/0.49/0.50 and Milstein 0.94/0.95/0.98
        -- close to, and slightly below, the asymptotic 0.5 and 1.0, which is the
        expected finite-step behaviour. The bands below are wide enough to absorb
        the noise but far too tight for the wrong order to pass.
        """
        errors = self._errors()
        for name, lower, upper in (
            ("euler_maruyama", 0.40, 0.60),
            ("milstein", 0.85, 1.10),
        ):
            series = errors[name]
            rates = [
                math.log2(previous / current)
                for previous, current in zip(series, series[1:])
            ]
            for rate in rates:
                assert lower < rate < upper, (
                    f"{name} rates {rates} outside ({lower}, {upper})"
                )

    def test_milstein_rate_exceeds_euler_rate(self):
        errors = self._errors()
        euler_rates = [
            math.log2(a / b)
            for a, b in zip(errors["euler_maruyama"], errors["euler_maruyama"][1:])
        ]
        milstein_rates = [
            math.log2(a / b)
            for a, b in zip(errors["milstein"], errors["milstein"][1:])
        ]
        assert sum(milstein_rates) > sum(euler_rates) + 1.0


# ---------------------------------------------------------------------------
# Zero diffusion reduces to the deterministic ODE
# ---------------------------------------------------------------------------

class TestZeroDiffusion:
    RATE = 0.5
    T = 1.0
    STEPS = 1024

    def _path(self, seed: int) -> SDEPath:
        return simulate_paths(
            linear_drift(self.RATE),
            ZeroDiffusion(),
            torch.tensor([1.0], dtype=DTYPE),
            t0=0.0,
            t1=self.T,
            steps=self.STEPS,
            n_paths=1,
            seed=seed,
        )

    def test_the_noise_has_exactly_no_effect(self):
        """``g == 0`` multiplies the increment by exactly zero.

        Two seeds must therefore give *bit-identical* paths. Approximate
        agreement would not be enough: the claim is that the stochastic term
        vanishes, not that it is small.
        """
        first = self._path(seed=1)
        second = self._path(seed=2)
        assert torch.equal(first.states, second.states)

    def test_it_matches_the_temporal_graph_rk4_integration(self):
        """Compare against the existing deterministic solver, not a reimplementation.

        Euler-Maruyama with zero diffusion is forward Euler, so it differs from
        the fourth-order RK4 reference by the first-order truncation error; at
        1024 steps over a unit interval that is about ``rate^2 * T * h / 2``
        relative, i.e. ~1.2e-4, and the tolerance is set with margin above it.
        """
        path = self._path(seed=3)
        reference = rk4_integrate(
            linear_drift(self.RATE),
            torch.tensor([1.0], dtype=DTYPE),
            0.0,
            self.T,
            steps=self.STEPS,
        )
        assert float(path.terminal()[0, 0]) == pytest.approx(
            float(reference[0]), rel=5e-3
        )

    def test_it_matches_the_closed_form_solution(self):
        path = self._path(seed=4)
        closed = math.exp(-self.RATE * self.T)
        assert float(path.terminal()[0, 0]) == pytest.approx(closed, rel=5e-3)

    def test_the_diffusion_part_of_the_variation_is_exactly_zero(self):
        """``g == 0`` means the integrated diffusion is identically zero.

        The *realised* variation is not zero, because it is ``sum (dz)^2`` and
        the drift still moves the state: with ``dz = f dt`` exactly, every
        increment is ``f*dt``, so the realised variation is the hand-computable
        ``sum_k (f_k * dt)^2``. Asserting that exact identity is both the honest
        statement and a check that the diagnostic is wired to the real increments
        rather than to the diffusion tensor.
        """
        path = self._path(seed=5)
        assert torch.equal(
            path.integrated_diffusion, torch.zeros_like(path.integrated_diffusion)
        )
        expected = (path.drift * path.dt).pow(2).sum(dim=1)
        assert torch.allclose(path.quadratic_variation, expected, rtol=1e-12, atol=1e-15)
        # The drift's contribution is O(dt): sum_k (f_k dt)^2 ~ rate^2 * dt *
        # integral_0^T exp(-2*rate*t) dt. For rate=0.5, T=1, dt=1/1024 that is
        # 1.543e-4, and the realised value sits within a percent of it.
        analytic = (
            self.RATE ** 2
            * path.dt
            * (1.0 - math.exp(-2.0 * self.RATE * self.T)) / (2.0 * self.RATE)
        )
        assert float(path.quadratic_variation.max()) == pytest.approx(analytic, rel=1e-2)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    def _arguments(self, **overrides):
        arguments = dict(
            drift=constant_drift(0.2),
            diffusion=ConstantDiffusion(0.5),
            z0=torch.tensor([1.0, -1.0], dtype=DTYPE),
            t0=0.0,
            t1=1.0,
            steps=16,
            n_paths=8,
        )
        arguments.update(overrides)
        return arguments

    def test_the_same_seed_is_bit_identical(self):
        first = simulate_paths(**self._arguments(seed=1234))
        second = simulate_paths(**self._arguments(seed=1234))
        assert torch.equal(first.states, second.states)
        assert torch.equal(first.quadratic_variation, second.quadratic_variation)

    def test_different_seeds_differ(self):
        first = simulate_paths(**self._arguments(seed=1))
        second = simulate_paths(**self._arguments(seed=2))
        assert not torch.equal(first.states, second.states)

    def test_an_explicit_generator_matches_the_equivalent_seed(self):
        from_seed = simulate_paths(**self._arguments(seed=7))
        from_generator = simulate_paths(
            **self._arguments(generator=torch.Generator().manual_seed(7))
        )
        assert torch.equal(from_seed.states, from_generator.states)

    def test_advancing_a_generator_changes_the_path(self):
        generator = torch.Generator().manual_seed(7)
        _ = simulate_paths(**self._arguments(generator=generator))
        second = simulate_paths(**self._arguments(generator=generator))
        fresh = simulate_paths(**self._arguments(seed=7))
        assert not torch.equal(second.states, fresh.states)

    def test_both_sources_together_are_rejected(self):
        with pytest.raises(ValueError, match="not both"):
            simulate_paths(
                **self._arguments(seed=1, generator=torch.Generator().manual_seed(1))
            )

    def test_a_missing_randomness_source_is_rejected(self):
        with pytest.raises(ValueError, match="seed"):
            simulate_paths(**self._arguments())


# ---------------------------------------------------------------------------
# Antithetic sampling
# ---------------------------------------------------------------------------

class TestAntitheticSampling:
    def test_paths_are_drawn_in_exact_negating_pairs(self):
        """For zero drift and constant diffusion the pair means are exact.

        Under Euler-Maruyama ``z_k = z0 + sigma * sum dW``, so a path driven by
        ``-dW`` lands symmetrically around ``z0`` and the two terminals sum to
        ``2*z0``. That is a closed form, so the pairing is checked exactly rather
        than by a variance argument.
        """
        path = simulate_paths(
            zero_drift,
            ConstantDiffusion(0.8),
            torch.tensor([0.0], dtype=DTYPE),
            t0=0.0,
            t1=1.0,
            steps=32,
            n_paths=16,
            seed=9,
            antithetic=True,
        )
        terminal = path.terminal().reshape(-1)
        paired_sums = terminal[0::2] + terminal[1::2]
        assert torch.allclose(paired_sums, torch.zeros_like(paired_sums), atol=1e-10)

    def test_the_estimator_variance_is_lower_than_independent_sampling(self):
        """Variance of the batch-mean estimator, antithetic vs independent.

        Each estimator uses the same number of paths (512, in 64 batches of 8),
        so the comparison is fair. The batch means are independent within a run
        and their sample variance estimates the estimator variance. Geometric
        Brownian motion is used because the payoff ``S_T`` is nonlinear in the
        noise, which is where antithetic sampling has to earn its reduction; the
        effect is large here (roughly 5-12x) so the assertion is robust to the
        seed rather than tuned to it.
        """
        def batch_means(antithetic: bool, seed: int) -> torch.Tensor:
            path = simulate_paths(
                gbm_drift(0.1),
                GeometricBrownianDiffusion(0.4),
                torch.tensor([1.0], dtype=DTYPE),
                t0=0.0,
                t1=1.0,
                steps=32,
                n_paths=512,
                seed=seed,
                antithetic=antithetic,
            )
            return path.terminal().reshape(512).reshape(64, 8).mean(dim=1)

        ratios = []
        for seed in (1, 2, 3):
            antithetic = batch_means(True, seed)
            independent = batch_means(False, seed)
            ratios.append(float(antithetic.var(unbiased=True)) /
                          float(independent.var(unbiased=True)))
        assert all(ratio < 0.6 for ratio in ratios), ratios
        pooled = sum(ratios) / len(ratios)
        assert pooled < 0.4, f"pooled variance ratio {pooled:.3f}"

    def test_an_odd_path_count_is_rejected(self):
        with pytest.raises(ValueError, match="even"):
            simulate_paths(
                zero_drift,
                ConstantDiffusion(0.5),
                torch.tensor([0.0], dtype=DTYPE),
                steps=4,
                n_paths=5,
                seed=1,
                antithetic=True,
            )


# ---------------------------------------------------------------------------
# Quadratic variation diagnostics
# ---------------------------------------------------------------------------

class TestQuadraticVariation:
    SIGMA = 0.5
    T = 1.0
    STEPS = 256
    N_PATHS = 4096
    SEED = 99

    def _zero_drift_path(self) -> SDEPath:
        return simulate_paths(
            zero_drift,
            ConstantDiffusion(self.SIGMA),
            torch.tensor([0.0], dtype=DTYPE),
            t0=0.0,
            t1=self.T,
            steps=self.STEPS,
            n_paths=self.N_PATHS,
            seed=self.SEED,
        )

    def test_the_realised_quadratic_variation_matches_the_integrated_diffusion(self):
        """For ``dz = sigma dW`` the realised QV is ``sigma^2 * sum dW^2``.

        ``sum_k dW_k^2 = dt * chi^2(n)``, so the mean over paths has standard
        error ``sigma^2 * sqrt(2*T*dt) / sqrt(N)``. The variance of the realised
        QV itself is ``2 * sigma^4 * T * dt``, and the sample variance has
        standard error ``that * sqrt(2/(N-1))``. Both tolerances below are four
        of those standard errors.
        """
        path = self._zero_drift_path()
        variation = path.quadratic_variation.reshape(-1)
        expected = self.SIGMA ** 2 * self.T

        se_mean = self.SIGMA ** 2 * math.sqrt(2.0 * self.T * path.dt) / math.sqrt(
            self.N_PATHS
        )
        mean = float(variation.mean())
        assert abs(mean - expected) < 4.0 * se_mean, (
            f"mean QV {mean} vs {expected}; {abs(mean - expected) / se_mean:.2f} SE "
            f"(SE = {se_mean:.3e})"
        )

        expected_variance = 2.0 * self.SIGMA ** 4 * self.T * path.dt
        se_variance = expected_variance * math.sqrt(2.0 / (self.N_PATHS - 1))
        variance = float(variation.var(unbiased=True))
        assert abs(variance - expected_variance) < 4.0 * se_variance, (
            f"QV variance {variance:.3e} vs {expected_variance:.3e}; "
            f"{abs(variance - expected_variance) / se_variance:.2f} SE"
        )

    def test_the_integrated_diffusion_is_the_deterministic_integral(self):
        path = self._zero_drift_path()
        expected = self.SIGMA ** 2 * self.T
        assert torch.allclose(
            path.integrated_diffusion,
            torch.full_like(path.integrated_diffusion, expected),
            rtol=0.0,
            atol=1e-12,
        )

    def test_a_nonzero_drift_contaminates_the_realised_variation_by_o_dt(self):
        """The diagnostic is honest about what it measures.

        With ``dz = mu dt + sigma dW`` the realised variation is
        ``sum (mu dt + sigma dW)^2``, whose expectation is
        ``sigma^2 T + mu^2 T dt`` (the cross term has mean zero). So the naive
        comparison with ``sigma^2 T`` is *wrong* at fixed ``dt``, and this test
        asserts the measurable size of that error as well as its sign. The
        measured bias agrees with the prediction to about one standard error.
        """
        mu, sigma, steps, n_paths = 0.7, 0.4, 128, 8192
        path = simulate_paths(
            constant_drift(mu),
            ConstantDiffusion(sigma),
            torch.tensor([0.0], dtype=DTYPE),
            t0=0.0,
            t1=1.0,
            steps=steps,
            n_paths=n_paths,
            seed=5,
        )
        variation = path.quadratic_variation.reshape(-1)
        mean = float(variation.mean())
        se = sigma ** 2 * math.sqrt(2.0 * 1.0 * path.dt) / math.sqrt(n_paths)

        predicted = sigma ** 2 * 1.0 + mu ** 2 * 1.0 * path.dt
        assert abs(mean - predicted) < 4.0 * se, (
            f"mean QV {mean} vs prediction {predicted}; "
            f"{abs(mean - predicted) / se:.2f} SE (SE = {se:.3e})"
        )
        # And the uncorrected closed form must be rejected by a wide margin.
        naive = sigma ** 2 * 1.0
        assert abs(mean - naive) > 4.0 * se, "the O(dt) drift bias was not detected"


# ---------------------------------------------------------------------------
# Fail-closed behaviour
# ---------------------------------------------------------------------------

class TestFailClosed:
    def _arguments(self, **overrides):
        arguments = dict(
            drift=zero_drift,
            diffusion=ConstantDiffusion(0.5),
            z0=torch.tensor([0.0], dtype=DTYPE),
            t0=0.0,
            t1=1.0,
            steps=4,
            n_paths=2,
            seed=1,
        )
        arguments.update(overrides)
        return arguments

    def test_bad_step_counts_are_rejected(self):
        for bad in (0, -3):
            with pytest.raises(ValueError, match="steps"):
                simulate_paths(**self._arguments(steps=bad))
        with pytest.raises(ValueError, match="integer"):
            simulate_paths(**self._arguments(steps=2.5))

    def test_bad_horizons_and_step_sizes_are_rejected(self):
        with pytest.raises(ValueError, match="horizon"):
            simulate_paths(**self._arguments(t1=0.0))
        with pytest.raises(ValueError, match="horizon"):
            simulate_paths(**self._arguments(t1=-1.0))
        with pytest.raises(ValueError, match="finite"):
            simulate_paths(**self._arguments(t1=float("inf")))
        with pytest.raises(ValueError, match="finite"):
            simulate_paths(**self._arguments(t0=float("nan")))

    def test_bad_path_counts_are_rejected(self):
        with pytest.raises(ValueError, match="n_paths"):
            simulate_paths(**self._arguments(n_paths=0))

    def test_an_unknown_integrator_is_rejected(self):
        with pytest.raises(ValueError, match="integrator"):
            simulate_paths(**self._arguments(integrator="trapezoid"))

    def test_a_non_floating_or_non_finite_initial_state_is_rejected(self):
        with pytest.raises(ValueError, match="floating"):
            simulate_paths(**self._arguments(z0=torch.tensor([1, 2])))
        with pytest.raises(ValueError, match="non-finite"):
            simulate_paths(**self._arguments(z0=torch.tensor([1.0, float("inf")], dtype=DTYPE)))

    def test_a_mismatched_drift_shape_is_rejected(self):
        with pytest.raises(ValueError, match="drift"):
            simulate_paths(
                **self._arguments(drift=lambda z, t: torch.zeros(1, dtype=DTYPE))
            )

    def test_a_mismatched_diffusion_shape_is_rejected(self):
        class BadDiffusion(nn.Module):
            def forward(self, z, t):
                return torch.zeros(1, dtype=DTYPE)

        with pytest.raises(ValueError, match="diffusion"):
            simulate_paths(**self._arguments(diffusion=BadDiffusion()))


# ---------------------------------------------------------------------------
# Memory interface
# ---------------------------------------------------------------------------

def decay_only_field(memory_dim: int, rate: float) -> NeuralODEField:
    """A field reduced to ``-rate * z``, exactly as the temporal graph tests do."""
    field = NeuralODEField(memory_dim, rate=rate)
    with torch.no_grad():
        for parameter in field.net.parameters():
            parameter.zero_()
    return field


class TestMemoryInterface:
    def test_deterministic_mode_reproduces_the_temporal_graph_memory(self):
        """The new memory is a superset: the ODE path must be unchanged.

        Both objects are given the *same* field instance, so equality is
        bit-for-bit and not merely close -- if the RK4 wiring had been subtly
        reimplemented, this would not hold.
        """
        field = decay_only_field(4, rate=0.4)
        reference = TemporalGraphMemory(2, memory_dim=4, field=field, integration_steps=16)
        candidate = NeuralSDEMemory(2, memory_dim=4, field=field, integration_steps=16)

        for memory in (reference, candidate):
            memory.write(0, torch.tensor([1.0, 2.0, 3.0, 4.0]), time=0.0)
            memory.write(1, torch.full((4,), 0.5), time=1.0)

        for time in (0.5, 2.5, 6.0):
            assert torch.equal(
                reference.read(0, time).memory, candidate.read(0, time).memory
            )
        assert torch.equal(reference.evolve_to(3.0), candidate.evolve_to(3.0))
        assert reference.stale_nodes(0.5) == candidate.stale_nodes(0.5)

    def test_deterministic_mode_matches_the_analytic_decay(self):
        rate = 0.4
        memory = NeuralSDEMemory(
            1, memory_dim=3, field=decay_only_field(3, rate), integration_steps=64
        )
        memory.write(0, torch.tensor([1.0, 2.0, 3.0]), time=0.0)
        expected = torch.tensor([1.0, 2.0, 3.0]) * math.exp(-rate * 0.5)
        assert torch.allclose(memory.read(0, 0.5).memory, expected, rtol=1e-6)

    def test_the_deterministic_mode_is_the_default(self):
        memory = NeuralSDEMemory(2, memory_dim=4)
        assert memory.mode == "deterministic"
        assert not memory.is_stochastic

    def test_a_stochastic_mode_without_a_seed_is_rejected(self):
        with pytest.raises(ValueError, match="seed"):
            NeuralSDEMemory(2, memory_dim=4, mode="milstein")

    def test_an_unknown_mode_is_rejected(self):
        with pytest.raises(ValueError, match="mode"):
            NeuralSDEMemory(2, memory_dim=4, mode="heun", seed=1)

    def _stochastic(
        self, seed: int, diffusion: nn.Module | None = None
    ) -> NeuralSDEMemory:
        return NeuralSDEMemory(
            2,
            memory_dim=4,
            field=decay_only_field(4, rate=0.3),
            integration_steps=16,
            mode="milstein",
            diffusion=diffusion if diffusion is not None else DiagonalDiffusion(4),
            seed=seed,
        )

    def test_stochastic_reads_are_reproducible_and_seed_sensitive(self):
        # One shared diffusion module, so the *only* source of variation between
        # the two memories is the sampling seed. Identity of reads then tests the
        # generator, not the module initialisation.
        diffusion = DiagonalDiffusion(4)
        first = self._stochastic(seed=7, diffusion=diffusion)
        second = self._stochastic(seed=7, diffusion=diffusion)
        other = self._stochastic(seed=8, diffusion=diffusion)
        for memory in (first, second, other):
            memory.write(0, torch.ones(4), time=0.0)
        assert torch.equal(first.read(0, 1.0).memory, second.read(0, 1.0).memory)
        assert not torch.equal(first.read(0, 1.0).memory, other.read(0, 1.0).memory)

    def test_evolving_the_store_matches_reading_in_a_stochastic_mode(self):
        memory = self._stochastic(seed=11)
        memory.write(0, torch.ones(4), time=0.0)
        read_value = memory.read(0, 1.0).memory
        memory.evolve_to(1.0)
        assert torch.equal(memory.memory[0], read_value)

    def test_reading_does_not_mutate_the_store(self):
        memory = self._stochastic(seed=3)
        memory.write(0, torch.ones(4), time=0.0)
        before = memory.memory[0].clone()
        last_before = float(memory.last_time[0].item())
        _ = memory.read(0, 5.0)
        assert torch.equal(memory.memory[0], before)
        assert float(memory.last_time[0].item()) == last_before

    def test_read_distribution_returns_distinct_samples(self):
        memory = self._stochastic(seed=5)
        memory.write(0, torch.ones(4), time=0.0)
        samples = memory.read_distribution(0, 1.0, 32)
        assert samples.shape == (32, 4)
        assert not torch.equal(samples[0], samples[1])
        assert torch.isfinite(samples).all()

    def test_read_distribution_is_degenerate_in_deterministic_mode(self):
        """With ``g == 0`` every sample is the same point, and that is stated."""
        memory = NeuralSDEMemory(
            1, memory_dim=3, field=decay_only_field(3, 0.5), integration_steps=16
        )
        memory.write(0, torch.ones(3), time=0.0)
        samples = memory.read_distribution(0, 1.0, 8)
        assert torch.allclose(samples, samples[0].expand(8, -1))

    def test_unobserved_node_reads_as_zero(self):
        memory = self._stochastic(seed=1)
        state = memory.read(0, 10.0)
        assert torch.equal(state.memory, torch.zeros(4))
        assert state.evolved_interval == pytest.approx(0.0)

    def test_asking_for_an_earlier_time_does_not_integrate_backwards(self):
        memory = self._stochastic(seed=1)
        memory.write(0, torch.ones(4), time=5.0)
        state = memory.read(0, 2.0)
        assert state.evolved_interval == pytest.approx(0.0)
        assert torch.equal(state.memory, torch.ones(4))

    def test_write_stale_and_reset_follow_the_temporal_graph_conventions(self):
        memory = self._stochastic(seed=1)
        memory.write(0, torch.ones(4), time=1.0)
        memory.write(1, torch.ones(4), time=9.0)
        assert memory.stale_nodes(5.0) == [1]
        memory.reset()
        assert torch.equal(memory.memory, torch.zeros(2, 4))
        assert memory.stale_nodes(100.0) == []

    def test_write_validation(self):
        memory = self._stochastic(seed=1)
        with pytest.raises(ValueError, match="outside"):
            memory.write(5, torch.ones(4), time=0.0)
        with pytest.raises(ValueError, match="outside"):
            memory.read(5, 0.0)
        with pytest.raises(ValueError, match="shape"):
            memory.write(0, torch.ones(7), time=0.0)

    def test_constructor_validation(self):
        with pytest.raises(ValueError, match="n_nodes"):
            NeuralSDEMemory(0)
        with pytest.raises(ValueError, match="memory_dim"):
            NeuralSDEMemory(2, memory_dim=0)
        with pytest.raises(ValueError, match="integration_steps"):
            NeuralSDEMemory(2, memory_dim=4, integration_steps=0)

    def test_read_returns_the_temporal_graph_memory_state(self):
        memory = self._stochastic(seed=1)
        memory.write(0, torch.ones(4), time=1.0)
        state = memory.read(0, 4.0)
        assert isinstance(state, MemoryState)
        assert state.node == 0
        assert state.time == pytest.approx(4.0)
        assert state.last_update_time == pytest.approx(1.0)
        assert state.evolved_interval == pytest.approx(3.0)
        assert state.memory.shape == (4,)

    def test_the_public_interface_matches_the_temporal_graph(self):
        reference = TemporalGraphMemory(2, memory_dim=4)
        candidate = NeuralSDEMemory(2, memory_dim=4)
        for name in ("read", "write", "evolve_to", "stale_nodes", "reset"):
            assert callable(getattr(candidate, name))
            assert hasattr(reference, name)

    def test_configuration_serialises(self):
        memory = self._stochastic(seed=1)
        memory.write(0, torch.ones(4), time=0.0)
        payload = memory.to_dict()
        json.dumps(payload, allow_nan=False)
        assert payload["mode"] == "milstein"
        assert payload["seed"] == 1
        assert payload["stochastic"] is True

    def test_path_summary_serialises(self):
        path = simulate_paths(
            zero_drift,
            ConstantDiffusion(0.5),
            torch.tensor([0.0], dtype=DTYPE),
            steps=4,
            n_paths=4,
            seed=1,
        )
        json.dumps(path.to_dict(), allow_nan=False)
