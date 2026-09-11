"""Stochastic latent dynamics for the continuous-time graph memory.

Why this module exists
----------------------

:mod:`backend.modules.engine.temporal_graph` advances each node's memory with a
deterministic flow, ``dz/dt = f_theta(z, t)``. A deterministic flow tracks one
trajectory and therefore one conditional mean: it carries *no* uncertainty about
the state, so it cannot represent a regime in which the state's own variance is
moving. That matters here because the defining signature of systemic risk is not
a change in the level of funding stress but a change in its *dispersion* -- calm
markets and pre-crisis markets can share a mean and differ entirely in how
volatile they are, and a deterministic latent state cannot express the
difference. Clustered and expanding volatility is the pre-crisis signal.

Raising the dynamics to a stochastic differential equation

    dz = f_theta(z, t) dt + g_theta(z, t) dW

gives the latent state its own heteroskedasticity: the diffusion ``g`` is a
learned function, so the model can widen the state distribution exactly when the
data says uncertainty is expanding. This pairs with the model's quantile layer --
the base model supplies marginal uncertainty per node and the SDE propagates it
through the network over time. Nothing in this module calibrates that coupling;
it supplies the propagator.

What is implemented
-------------------

* ``DriftField`` -- a learned ``f_theta(z, t)`` with the same ``(state, time)``
  convention as ``NeuralODEField`` in the temporal graph, so either can be passed
  wherever a drift is expected.
* ``DiagonalDiffusion`` -- a learned ``g_theta`` that is diagonal by
  construction: coordinate ``i`` of the diffusion depends only on coordinate
  ``i`` of the state (and time). Positivity is guaranteed by a softplus with a
  strictly positive floor, ``g_i = floor + softplus(raw_i)``. Softplus was chosen
  over ``exp`` because it is strictly positive but grows only linearly for large
  positive arguments, so a badly scaled network cannot make the noise overflow;
  the floor keeps ``g_i`` bounded away from zero, so the diffusion cannot silently
  collapse and turn the SDE back into the deterministic ODE this module exists to
  move beyond. ``exp`` would also be positive but explodes, and its reciprocal
  vanishes; the floor gives an explicit, inspectable lower bound instead.
* ``ConstantDiffusion`` and ``ZeroDiffusion`` -- fixed non-learned diffusions,
  which is what makes the analytic tests possible.
* ``euler_maruyama_step`` / ``milstein_step`` -- fixed-step strong integrators.
* ``simulate_paths`` -- a vectorised fixed-step sampler that returns an
  ``SDEPath`` carrying the drift, the diffusion, the integrated diffusion
  ``sum g^2 dt`` and the realised quadratic variation ``sum (dz)^2`` along the
  path, so a caller can check the discretisation against theory rather than trust
  it.
* ``NeuralSDEMemory`` -- the per-node memory with the *same interface* as
  ``TemporalGraphMemory`` (``read``/``write``/``evolve_to``/``stale_nodes``/
  ``reset``, returning the same ``MemoryState``). The deterministic RK4 path
  remains the default and is bit-for-bit the temporal graph's integrator; the SDE
  is opt-in through ``mode``.

Milstein's condition
--------------------

The Milstein scheme is only implemented for **diagonal, commutative noise**: the
diffusion ``g`` must satisfy ``g_i = g_i(z_i, t)``, so the diffusion matrix is
diagonal and the off-diagonal Levy areas vanish. Under that condition the
correction reduces to ``0.5 * g_i * dg_i/dz_i * (dW_i^2 - dt)``, which is what
``milstein_step`` adds. For a general (non-diagonal or non-commutative) diffusion
the Milstein correction requires iterated Ito integrals of the Wiener process
(Levy areas) that are *not* simulated here, and applying this formula would be
silently wrong. ``DiagonalDiffusion`` satisfies the condition by construction;
a caller who supplies an arbitrary callable is responsible for it, and this
module does not verify it. The ``derivative`` method is defined to return only
the diagonal ``dg_i/dz_i``; it is not a general Jacobian.

What is NOT implemented, and the limitations
--------------------------------------------

* The orders quoted are **strong** (pathwise) orders, not weak orders. Euler-
  Maruyama is strong order 0.5 and Milstein strong order 1.0 for the diffusion
  assumptions above. A weak-order claim would need a different test.
* **A diffusion is continuous, so it cannot produce jumps.** This is the most
  important caveat. A diffusion can widen the state distribution and cluster its
  variance, but the increments are Gaussian and the tails are therefore only
  partly served: the fat tails a genuine crisis exhibits (a discrete funding
  freeze, a margin call cascade arriving as one impulse) require a jump term,
  i.e. a true jump-diffusion ``dz = f dt + g dW + h dN``, which is not
  implemented here. Modelling a crisis with this module alone will understate
  tail risk.
* There is no adaptive step-size control. The step is fixed by the caller, and a
  fixed step can be badly wrong in stiff regions of the learned field, where the
  true solution changes far faster than the step resolves. The error is not
  bounded or reported at run time.
* There is no existence or uniqueness verification beyond a Lipschitz-style
  regularisation: the learned fields use bounded (``tanh``) hidden activations,
  but the linear output layers are unbounded and no Lipschitz constant is
  measured or enforced. A pathological network can produce a field for which the
  SDE has no unique solution over the requested horizon.
* The diffusion parameterisation bounds the noise it can express. ``g_i`` is
  elementwise in ``(z_i, t)``, so it cannot represent correlated noise between
  coordinates, and the softplus floor sets a strictly positive minimum variance
  rate even in a regime where the model should be deterministic.
* Long-horizon paths may drift -- there is no mean-reversion constraint or
  stationary-distribution guarantee -- and the discretisation bias grows with the
  horizon because the step count is fixed while the interval is not.
* No calibration of the SDE to data is provided here. Nothing in this module fits
  ``f`` or ``g``; it provides the parameterisation, the integrators, the memory
  wiring and the diagnostics only.
* Gradients do flow through the forward Euler-Maruyama path, but the Milstein
  correction is differentiated with ``create_graph=False``: the ``dg/dz`` factor
  is a number, not a differentiable function of the parameters, so training the
  diffusion through Milstein needs a module that implements ``derivative``
  analytically. This file does not claim otherwise.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

from backend.modules.engine.temporal_graph import (
    MemoryState,
    NeuralODEField,
    TimeEncoder,
    rk4_integrate,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DriftFn",
    "DiffusionFn",
    "DriftField",
    "DiagonalDiffusion",
    "ConstantDiffusion",
    "ZeroDiffusion",
    "diagonal_derivative",
    "euler_maruyama_step",
    "milstein_step",
    "simulate_paths",
    "SDEPath",
    "NeuralSDEMemory",
    "INTEGRATORS",
]

#: Signature of a drift ``(state, time) -> d(state)/dt``.
DriftFn = Callable[[torch.Tensor, torch.Tensor], torch.Tensor]
#: Signature of a diagonal diffusion ``(state, time) -> g(state, time)``.
DiffusionFn = Callable[[torch.Tensor, torch.Tensor], torch.Tensor]

_MAX_SEED = 2 ** 63 - 1


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def _check_state(state: torch.Tensor) -> torch.Tensor:
    """Fail closed on anything that cannot be a latent state."""
    tensor = torch.as_tensor(state)
    if not tensor.is_floating_point():
        raise ValueError(
            f"state must be a floating-point tensor, got dtype {tensor.dtype}"
        )
    if tensor.numel() == 0:
        raise ValueError("state must have at least one element")
    if not bool(torch.isfinite(tensor).all()):
        raise ValueError("state contains a non-finite value")
    return tensor


def _check_dt(dt: float) -> float:
    value = float(dt)
    if not math.isfinite(value):
        raise ValueError(f"dt must be finite, got {dt!r}")
    if value <= 0.0:
        raise ValueError(f"dt must be positive, got {value}")
    return value


def _check_time(time: object, state: torch.Tensor) -> torch.Tensor:
    return torch.as_tensor(time, dtype=state.dtype, device=state.device)


def _check_noise(dW: torch.Tensor, state: torch.Tensor) -> torch.Tensor:
    noise = torch.as_tensor(dW, dtype=state.dtype, device=state.device)
    if noise.shape != state.shape:
        raise ValueError(
            f"dW has shape {tuple(noise.shape)} but the state has shape "
            f"{tuple(state.shape)}; they must match exactly"
        )
    return noise


def _check_output(output: torch.Tensor, state: torch.Tensor, name: str) -> torch.Tensor:
    if output.shape != state.shape:
        raise ValueError(
            f"the {name} returned shape {tuple(output.shape)} for a state of shape "
            f"{tuple(state.shape)}"
        )
    if not bool(torch.isfinite(output).all()):
        raise ValueError(f"the {name} returned a non-finite value")
    return output


# ---------------------------------------------------------------------------
# Drift
# ---------------------------------------------------------------------------

class DriftField(nn.Module):
    """A learned drift ``f_theta(z, t)`` for the SDE.

    Structurally the same object as ``NeuralODEField`` in the temporal graph --
    a Fourier-encoded time interval concatenated to the state, a small ``tanh``
    network, and a linear decay floor -- and deliberately callable in the same
    way, so a trained ``NeuralODEField`` can be dropped in as the SDE drift
    without conversion. The decay term is kept for the same reason it exists
    there: without a floor the field can learn zero, and a memory that does not
    move is exactly the staleness the continuous-time model removes.
    """

    def __init__(
        self,
        state_dim: int,
        hidden_dim: int = 64,
        time_dim: int = 8,
        rate: float = 0.1,
    ) -> None:
        super().__init__()
        if state_dim < 1:
            raise ValueError(f"state_dim must be positive, got {state_dim}")
        if hidden_dim < 1:
            raise ValueError(f"hidden_dim must be positive, got {hidden_dim}")
        if rate <= 0:
            raise ValueError(f"rate must be positive, got {rate}")
        self.state_dim = int(state_dim)
        self.time_encoder = TimeEncoder(dim=time_dim)
        self.net = nn.Sequential(
            nn.Linear(self.state_dim + self.time_encoder.output_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, self.state_dim),
        )
        self.rate = float(rate)

    def forward(self, state: torch.Tensor, t: object) -> torch.Tensor:
        encoded = self.time_encoder(torch.as_tensor(t).reshape(-1))
        if encoded.shape[0] != state.shape[0]:
            expanded = encoded.mean(dim=0, keepdim=True).expand(state.shape[0], -1)
        else:
            expanded = encoded
        return self.net(torch.cat([state, expanded], dim=-1)) - self.rate * state


# ---------------------------------------------------------------------------
# Diffusion
# ---------------------------------------------------------------------------

class DiagonalDiffusion(nn.Module):
    """A positive, diagonal diffusion ``g_theta(z, t)``.

    Parameterisation: ``g_i = floor + softplus(raw_i(z_i, t))`` with
    ``floor > 0``. This is strictly positive for every finite input, which is the
    property the SDE needs -- a negative or zero diffusion coefficient is not a
    valid variance rate. Softplus is chosen over ``exp`` because it saturates to
    ``floor`` for very negative arguments (so the diffusion cannot collapse) and
    grows only linearly for very positive arguments (so it cannot overflow),
    whereas ``exp`` diverges rapidly and can produce ``inf`` from a modest weight
    update. The floor is a deliberate, inspectable lower bound rather than an
    implicit one, and it is the reason the module can never silently degenerate
    into the deterministic ODE.

    The map is elementwise in the state: ``raw_i`` is computed from ``(z_i, t)``
    alone, with parameters shared across coordinates. That makes the diffusion
    matrix diagonal by construction, which is exactly the condition under which
    the Milstein correction in this module is valid (see the module docstring).
    It also means the module cannot express cross-coordinate correlation in the
    noise -- a stated limitation, not an accident.
    """

    def __init__(
        self,
        state_dim: int,
        hidden_dim: int = 32,
        time_dim: int = 8,
        floor: float = 1e-3,
    ) -> None:
        super().__init__()
        if state_dim < 1:
            raise ValueError(f"state_dim must be positive, got {state_dim}")
        if hidden_dim < 1:
            raise ValueError(f"hidden_dim must be positive, got {hidden_dim}")
        if not math.isfinite(float(floor)):
            raise ValueError(f"floor must be finite, got {floor!r}")
        if float(floor) <= 0.0:
            raise ValueError(
                f"floor must be strictly positive, got {floor}; a zero floor lets "
                "the diffusion collapse and the SDE degenerate to the ODE"
            )
        self.state_dim = int(state_dim)
        self.hidden_dim = int(hidden_dim)
        self.floor = float(floor)
        self.time_encoder = TimeEncoder(dim=time_dim)
        self.net = nn.Sequential(
            nn.Linear(1 + self.time_encoder.output_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, 1),
        )

    def _positive(self, state: torch.Tensor, t: object) -> torch.Tensor:
        encoded = self.time_encoder(torch.as_tensor(t).reshape(-1))
        if encoded.shape[0] != state.shape[0]:
            encoded = encoded.mean(dim=0, keepdim=True).expand(state.shape[0], -1)
        expanded = encoded.unsqueeze(-2).expand(*state.shape, encoded.shape[-1])
        features = torch.cat([state.unsqueeze(-1), expanded], dim=-1)
        raw = self.net(features).squeeze(-1)
        return self.floor + F.softplus(raw)

    def forward(self, state: torch.Tensor, t: object) -> torch.Tensor:
        state = torch.as_tensor(state)
        return self._positive(state, t)

    def derivative(self, state: torch.Tensor, t: object) -> torch.Tensor:
        """Diagonal of the diffusion Jacobian, ``dg_i/dz_i``.

        Because the parameterisation is elementwise, the gradient of
        ``sum_i g_i`` with respect to the state is exactly the diagonal
        ``dg_i/dz_i``: every off-diagonal partial is zero by construction. The
        graph is detached first, so this is a numerical coefficient and not a
        differentiable path through the state (documented in the module
        docstring). It is the term the Milstein correction needs, and it is not
        a general Jacobian.
        """
        state = torch.as_tensor(state)
        with torch.enable_grad():
            z = state.detach().requires_grad_(True)
            g = self._positive(z, t)
            (grad,) = torch.autograd.grad(g.sum(), z, create_graph=False)
        return grad.detach()


class ConstantDiffusion(nn.Module):
    """A non-learned constant diffusion ``g(z, t) = sigma``.

    Present so the analytic tests have a diffusion whose law is known exactly:
    with a constant drift it makes Euler-Maruyama exact in law, and it gives the
    quadratic-variation diagnostic an integrated diffusion of exactly
    ``sigma^2 * T``. ``sigma`` may be zero, which is how the SDE is checked to
    reduce to the deterministic ODE.
    """

    def __init__(self, sigma: float) -> None:
        super().__init__()
        if not math.isfinite(float(sigma)):
            raise ValueError(f"sigma must be finite, got {sigma!r}")
        if float(sigma) < 0.0:
            raise ValueError(f"sigma must be non-negative, got {sigma}")
        self.sigma = float(sigma)

    def forward(self, state: torch.Tensor, t: object) -> torch.Tensor:
        return torch.full_like(torch.as_tensor(state), self.sigma)

    def derivative(self, state: torch.Tensor, t: object) -> torch.Tensor:
        return torch.zeros_like(torch.as_tensor(state))


class ZeroDiffusion(ConstantDiffusion):
    """``g == 0`` exactly: the SDE reduces to the drift ODE."""

    def __init__(self) -> None:
        super().__init__(0.0)


def diagonal_derivative(
    diffusion: object, state: torch.Tensor, time: object
) -> torch.Tensor:
    """Return the diagonal ``dg_i/dz_i`` for a diffusion.

    A diffusion may expose an exact ``derivative`` method; otherwise this falls
    back to reverse-mode autodiff of ``sum(g)``, which is the diagonal of the
    Jacobian only when ``g`` is elementwise (or when the off-diagonal terms
    genuinely vanish). For a general dense diffusion the fallback would return a
    row-summed quantity, not the diagonal, so a caller supplying one must provide
    an explicit ``derivative``.
    """
    method = getattr(diffusion, "derivative", None)
    if method is not None:
        result = method(state, time)
        if not isinstance(result, torch.Tensor):
            raise ValueError("the diffusion derivative must return a tensor")
        return _check_output(result, state, "diffusion derivative")
    if not callable(diffusion):
        raise ValueError(
            "diffusion must be callable or expose a derivative(state, time) method"
        )
    with torch.enable_grad():
        z = state.detach().requires_grad_(True)
        g = diffusion(z, time)
        _check_output(g, state, "diffusion")
        (grad,) = torch.autograd.grad(g.sum(), z, create_graph=False)
    return grad.detach()


# ---------------------------------------------------------------------------
# Integrators
# ---------------------------------------------------------------------------

def euler_maruyama_step(
    drift: DriftFn,
    diffusion: DiffusionFn,
    state: torch.Tensor,
    time: object,
    dt: float,
    dW: torch.Tensor,
) -> torch.Tensor:
    """One Euler-Maruyama step: ``z + f*dt + g*dW``.

    Strong order 0.5 for a general diffusion. Both the drift and the diffusion
    are evaluated at the left point of the step, which is what makes the scheme
    explicit and the order claim the standard one.
    """
    state = _check_state(state)
    step = _check_dt(dt)
    noise = _check_noise(dW, state)
    moment = _check_time(time, state)
    f = _check_output(drift(state, moment), state, "drift")
    g = _check_output(diffusion(state, moment), state, "diffusion")
    return state + f * step + g * noise


def milstein_step(
    drift: DriftFn,
    diffusion: DiffusionFn,
    state: torch.Tensor,
    time: object,
    dt: float,
    dW: torch.Tensor,
) -> torch.Tensor:
    """One Milstein step for diagonal, commutative noise.

    Condition, stated explicitly: the diffusion must be diagonal, ``g_i``
    depending only on ``z_i`` and ``t``. Under that condition the Milstein
    correction is

        ``0.5 * g_i * (dg_i/dz_i) * (dW_i^2 - dt)``

    per coordinate. For a non-diagonal or non-commutative diffusion the correct
    Milstein scheme needs iterated Ito integrals (Levy areas) that are not
    simulated here, and this formula would be wrong; the module does not attempt
    to detect that case. ``DiagonalDiffusion`` is diagonal by construction.
    Strong order 1.0 under the diagonal/commutative condition.
    """
    state = _check_state(state)
    step = _check_dt(dt)
    noise = _check_noise(dW, state)
    moment = _check_time(time, state)
    f = _check_output(drift(state, moment), state, "drift")
    g = _check_output(diffusion(state, moment), state, "diffusion")
    dg = diagonal_derivative(diffusion, state, moment)
    return state + f * step + g * noise + 0.5 * g * dg * (noise * noise - step)


#: Integrator name -> fixed-step scheme. Both have the same call signature.
INTEGRATORS: Dict[str, Callable[..., torch.Tensor]] = {
    "euler_maruyama": euler_maruyama_step,
    "milstein": milstein_step,
}


# ---------------------------------------------------------------------------
# Path sampling
# ---------------------------------------------------------------------------

@dataclass
class SDEPath:
    """A batch of sampled paths together with the diagnostics to check them.

    Attributes:
        times: ``(steps + 1,)`` step boundaries from ``t0`` to ``t1``.
        states: ``(n_paths, steps + 1, *state_shape)`` sampled states.
        drift: ``(n_paths, steps, *state_shape)`` drift at each left point.
        diffusion: ``(n_paths, steps, *state_shape)`` diffusion at each left point.
        integrated_diffusion: ``(n_paths, *state_shape)``, ``sum_k g_k^2 * dt`` --
            the model's own integrated variance along the path.
        quadratic_variation: ``(n_paths, *state_shape)``, ``sum_k (dz_k)^2`` -- the
            path's realised quadratic variation. With a non-zero drift this
            carries an ``O(dt)`` drift contamination, so it equals
            ``integrated_diffusion`` in expectation only up to that term; with
            zero drift the equality is exact in expectation.
        dt: The fixed step size.
        integrator: Name of the scheme used.
        antithetic: Whether the paths were drawn in +/- pairs.
        seed: The seed supplied, if any.
    """

    times: torch.Tensor
    states: torch.Tensor
    drift: torch.Tensor
    diffusion: torch.Tensor
    integrated_diffusion: torch.Tensor
    quadratic_variation: torch.Tensor
    dt: float
    integrator: str
    antithetic: bool
    seed: Optional[int]

    def terminal(self) -> torch.Tensor:
        """Terminal state of every path, shape ``(n_paths, *state_shape)``."""
        return self.states[:, -1]

    def to_dict(self) -> Dict[str, object]:
        """Serialisable summary; deliberately excludes the full path tensors."""
        return {
            "n_paths": int(self.states.shape[0]),
            "steps": int(self.states.shape[1] - 1),
            "dt": float(self.dt),
            "integrator": self.integrator,
            "antithetic": bool(self.antithetic),
            "seed": None if self.seed is None else int(self.seed),
            "t0": float(self.times[0].item()),
            "t1": float(self.times[-1].item()),
        }


def _resolve_generator(
    seed: Optional[int],
    generator: Optional[torch.Generator],
    device: torch.device,
) -> Tuple[torch.Generator, Optional[int]]:
    if seed is not None and generator is not None:
        raise ValueError("pass either seed or generator, not both")
    if seed is None and generator is None:
        raise ValueError(
            "a seed or an explicit torch.Generator is required: the sampler is "
            "stochastic and must be reproducible"
        )
    if generator is not None:
        return generator, None
    resolved = torch.Generator(device=device)
    resolved.manual_seed(int(seed) % _MAX_SEED)
    return resolved, int(seed)


def simulate_paths(
    drift: DriftFn,
    diffusion: DiffusionFn,
    z0: torch.Tensor,
    t0: float = 0.0,
    t1: float = 1.0,
    steps: int = 1,
    n_paths: int = 1,
    integrator: str = "euler_maruyama",
    seed: Optional[int] = None,
    generator: Optional[torch.Generator] = None,
    antithetic: bool = False,
) -> SDEPath:
    """Sample ``n_paths`` fixed-step solutions of ``dz = f dt + g dW``.

    The increments are standard normal scaled by ``sqrt(dt)`` and drawn from a
    caller-supplied generator, so the same seed reproduces the whole batch
    bit-for-bit. With ``antithetic=True`` the batch is drawn as ``+/-`` pairs,
    interleaved so that path ``2j`` and path ``2j + 1`` are partners; the pairing
    cancels the leading linear part of the noise and reduces the variance of any
    Monte Carlo estimate taken over the batch.

    Args:
        drift: ``f(state, time)``; must accept a leading batch dimension.
        diffusion: ``g(state, time)``; diagonal, see :func:`milstein_step`.
        z0: Initial state, shape ``(*state_shape)``; expanded over paths.
        t0, t1: Integration bounds; ``t1`` must be strictly greater than ``t0``.
        steps: Number of fixed steps.
        n_paths: Number of paths. Must be even when ``antithetic`` is set.
        integrator: One of :data:`INTEGRATORS`.
        seed: Seed for the generator. Exactly one of ``seed``/``generator``.
        generator: An explicit ``torch.Generator`` for reproducibility.
        antithetic: Draw paths in ``+/-`` pairs.

    Returns:
        An :class:`SDEPath`.

    Raises:
        ValueError: For a non-positive or non-integer step count, a non-finite or
            non-positive step size, a horizon that is not strictly positive, an
            unknown integrator, an odd path count under antithetic sampling,
            conflicting or missing randomness sources, or a drift/diffusion whose
            output shape does not match the state.
    """
    if not isinstance(steps, (int,)) or isinstance(steps, bool):
        raise ValueError(f"steps must be an integer, got {steps!r}")
    if steps < 1:
        raise ValueError(f"steps must be positive, got {steps}")
    if not isinstance(n_paths, (int,)) or isinstance(n_paths, bool):
        raise ValueError(f"n_paths must be an integer, got {n_paths!r}")
    if n_paths < 1:
        raise ValueError(f"n_paths must be positive, got {n_paths}")
    if antithetic and n_paths % 2 != 0:
        raise ValueError(
            f"antithetic sampling needs an even n_paths, got {n_paths}"
        )
    if integrator not in INTEGRATORS:
        raise ValueError(
            f"unknown integrator {integrator!r}; expected one of "
            f"{sorted(INTEGRATORS)}"
        )

    start = float(t0)
    end = float(t1)
    if not math.isfinite(start) or not math.isfinite(end):
        raise ValueError(f"integration bounds must be finite, got t0={t0!r}, t1={t1!r}")
    if end <= start:
        raise ValueError(
            f"the horizon must be strictly positive, got t0={start}, t1={end}"
        )

    initial = _check_state(z0)
    state_shape = tuple(initial.shape)
    dtype = initial.dtype
    device = initial.device

    step = (end - start) / float(steps)
    if not math.isfinite(step) or step <= 0.0:
        raise ValueError(
            f"the step size (t1 - t0) / steps = {step!r} is not a positive finite number"
        )

    resolved_generator, reported_seed = _resolve_generator(seed, generator, device)

    noise = torch.randn(
        (n_paths, steps) + state_shape,
        generator=resolved_generator,
        dtype=dtype,
        device=device,
    ) * math.sqrt(step)
    if antithetic:
        noise[1::2] = -noise[0::2]

    step_fn = INTEGRATORS[integrator]

    state = initial.unsqueeze(0).expand(n_paths, *state_shape).clone()
    states: List[torch.Tensor] = [state]
    drift_trace: List[torch.Tensor] = []
    diffusion_trace: List[torch.Tensor] = []
    integrated = torch.zeros((n_paths,) + state_shape, dtype=dtype, device=device)
    variation = torch.zeros((n_paths,) + state_shape, dtype=dtype, device=device)

    for index in range(steps):
        moment = torch.full(
            (n_paths,), start + index * step, dtype=dtype, device=device
        )
        noise_step = noise[:, index]
        f = _check_output(drift(state, moment), state, "drift")
        g = _check_output(diffusion(state, moment), state, "diffusion")
        nxt = step_fn(drift, diffusion, state, moment, step, noise_step)
        drift_trace.append(f)
        diffusion_trace.append(g)
        integrated = integrated + g * g * step
        variation = variation + (nxt - state) * (nxt - state)
        states.append(nxt)
        state = nxt

    times = torch.linspace(start, end, steps + 1, dtype=dtype, device=device)
    return SDEPath(
        times=times,
        states=torch.stack(states, dim=1),
        drift=torch.stack(drift_trace, dim=1),
        diffusion=torch.stack(diffusion_trace, dim=1),
        integrated_diffusion=integrated,
        quadratic_variation=variation,
        dt=float(step),
        integrator=integrator,
        antithetic=bool(antithetic),
        seed=reported_seed,
    )


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

class NeuralSDEMemory(nn.Module):
    """Per-node memory whose evolution may be stochastic.

    The interface is exactly ``TemporalGraphMemory``: the same constructor
    arguments in the same order, the same buffers (``memory``, ``last_time``,
    ``initialised``), and ``read``/``write``/``evolve_to``/``stale_nodes``/
    ``reset`` returning the same ``MemoryState``. The default ``mode`` is
    ``"deterministic"``, in which case the stored state is advanced with the
    temporal graph's RK4 integrator over the drift and the stochastic machinery
    is never touched -- the existing deterministic ODE is available and is the
    default, not a fallback bolted on beside it.

    In the stochastic modes the drift is ``field`` (a ``NeuralODEField`` by
    default) and the diffusion is ``diffusion`` (a ``DiagonalDiffusion`` by
    default). Because the memory is then a random variable, the module refuses to
    run without an explicit ``seed``; the same node, interval and seed always
    produce the same sample, so an SDE memory is as reproducible as the ODE one.
    A read returns *one* sample path, not a mean: use
    :meth:`read_distribution` to get the spread that the uncertainty layer
    consumes.

    Args:
        n_nodes: Size of the node universe.
        memory_dim: Width of each node's memory vector.
        field: Drift field. Defaults to a :class:`NeuralODEField` of the right
            width, matching the temporal graph.
        integration_steps: Steps per evolution of one node.
        mode: ``"deterministic"``, ``"euler_maruyama"`` or ``"milstein"``.
        diffusion: Diffusion module; defaults to a :class:`DiagonalDiffusion`.
        seed: Required for stochastic modes; ignored in deterministic mode.
        antithetic: Draw the samples of :meth:`read_distribution` in +/- pairs.
    """

    MODES = ("deterministic", "euler_maruyama", "milstein")

    def __init__(
        self,
        n_nodes: int,
        memory_dim: int = 32,
        field: Optional[nn.Module] = None,
        integration_steps: int = 8,
        mode: str = "deterministic",
        diffusion: Optional[nn.Module] = None,
        seed: Optional[int] = None,
        antithetic: bool = False,
    ) -> None:
        super().__init__()
        if n_nodes < 1:
            raise ValueError(f"n_nodes must be positive, got {n_nodes}")
        if memory_dim < 1:
            raise ValueError(f"memory_dim must be positive, got {memory_dim}")
        if integration_steps < 1:
            raise ValueError(
                f"integration_steps must be positive, got {integration_steps}"
            )
        if mode not in self.MODES:
            raise ValueError(
                f"mode must be one of {self.MODES}, got {mode!r}"
            )
        if mode != "deterministic" and seed is None:
            raise ValueError(
                "a seed is required in stochastic mode: a random memory that "
                "cannot be reproduced is not acceptable for risk monitoring"
            )

        self.n_nodes = int(n_nodes)
        self.memory_dim = int(memory_dim)
        self.integration_steps = int(integration_steps)
        self.mode = str(mode)
        self.seed = None if seed is None else int(seed)
        self.antithetic = bool(antithetic)
        self.field = field if field is not None else NeuralODEField(self.memory_dim)
        if mode == "deterministic":
            self.diffusion = ConstantDiffusion(0.0)
        else:
            self.diffusion = (
                diffusion if diffusion is not None else DiagonalDiffusion(self.memory_dim)
            )

        self.register_buffer("memory", torch.zeros(self.n_nodes, self.memory_dim))
        self.register_buffer("last_time", torch.zeros(self.n_nodes, dtype=torch.float64))
        self.register_buffer(
            "initialised", torch.zeros(self.n_nodes, dtype=torch.bool)
        )

    # -- interface shared with TemporalGraphMemory --------------------------

    def evolve_to(self, time: float) -> torch.Tensor:
        """Advance every node's memory to ``time`` and return the whole memory.

        Nodes whose last observation is at or after ``time`` are left alone, and
        an unobserved node is not moved: composing an interval from a state that
        was never written would be integrating noise from nothing.
        """
        target = float(time)
        for node in range(self.n_nodes):
            interval = target - float(self.last_time[node].item())
            if interval <= 0 or not bool(self.initialised[node].item()):
                continue
            with torch.no_grad():
                evolved = self._advance(node, self.memory[node], interval)
                self.memory[node] = evolved.detach()
            self.last_time[node] = target
        return self.memory

    def write(self, node: int, memory: torch.Tensor, time: float) -> None:
        """Overwrite a node's memory at a given time (an event has been applied)."""
        if not 0 <= node < self.n_nodes:
            raise ValueError(f"node {node} is outside a {self.n_nodes}-node universe")
        if memory.shape != (self.memory_dim,):
            raise ValueError(
                f"memory for node {node} has shape {tuple(memory.shape)}, expected "
                f"({self.memory_dim},)"
            )
        with torch.no_grad():
            self.memory[node] = memory
        self.last_time[node] = float(time)
        self.initialised[node] = True

    def read(self, node: int, time: float) -> MemoryState:
        """Memory for one node evolved to ``time``, without mutating the store.

        In a stochastic mode the returned memory is a single sample from the
        state distribution at ``time``, reproducible from the module seed, the
        node and the interval. In deterministic mode it is the RK4 path, which is
        differentiable with respect to the drift field exactly as in the temporal
        graph.
        """
        if not 0 <= node < self.n_nodes:
            raise ValueError(f"node {node} is outside a {self.n_nodes}-node universe")

        last = float(self.last_time[node].item())
        if not bool(self.initialised[node].item()):
            return MemoryState(
                node=node,
                time=float(time),
                last_update_time=last,
                evolved_interval=0.0,
                memory=self.memory[node].detach().clone(),
            )

        interval = float(time) - last
        if interval <= 0:
            return MemoryState(
                node=node,
                time=float(time),
                last_update_time=last,
                evolved_interval=max(interval, 0.0),
                memory=self.memory[node].detach().clone(),
            )

        evolved = self._advance(node, self.memory[node], interval)
        return MemoryState(
            node=node,
            time=float(time),
            last_update_time=last,
            evolved_interval=interval,
            memory=evolved,
        )

    def read_distribution(self, node: int, time: float, n_paths: int) -> torch.Tensor:
        """``n_paths`` samples of a node's memory at ``time``, shape ``(n_paths, dim)``.

        This is the object the uncertainty layer consumes: a sample of the latent
        state, not a point. In deterministic mode every sample is identical, which
        is stated rather than hidden -- with ``g == 0`` the SDE *is* the ODE. The
        store is not mutated.
        """
        if not 0 <= node < self.n_nodes:
            raise ValueError(f"node {node} is outside a {self.n_nodes}-node universe")
        if n_paths < 1:
            raise ValueError(f"n_paths must be positive, got {n_paths}")

        last = float(self.last_time[node].item())
        if not bool(self.initialised[node].item()) or float(time) - last <= 0:
            return self.memory[node].detach().unsqueeze(0).expand(n_paths, -1).clone()

        interval = float(time) - last
        if self.mode == "deterministic":
            evolved = self._advance(node, self.memory[node], interval)
            return evolved.detach().unsqueeze(0).expand(n_paths, -1).clone()

        return self._simulate(node, self.memory[node], interval, n_paths)

    def stale_nodes(self, time: float) -> List[int]:
        """Initialised nodes whose last update is later than ``time``."""
        target = float(time)
        return [
            node
            for node in range(self.n_nodes)
            if bool(self.initialised[node].item())
            and float(self.last_time[node].item()) > target
        ]

    def reset(self) -> None:
        with torch.no_grad():
            self.memory.zero_()
            self.last_time.zero_()
            self.initialised.zero_()

    # -- internals ----------------------------------------------------------

    @property
    def is_stochastic(self) -> bool:
        return self.mode != "deterministic"

    def _field_for(self, node: int) -> DriftFn:
        """The drift for a single node, as a batch-of-one callable."""

        def field(state: torch.Tensor, time: torch.Tensor) -> torch.Tensor:
            return self.field(state.reshape(1, -1), time)[0]

        return field

    def _derived_seed(self, node: int, interval: float) -> int:
        """A pure, deterministic function of (seed, node, interval)."""
        quantised = int(round(float(interval) * 1_000_000.0))
        mixed = (int(self.seed) * 1_000_003 + node * 7919 + quantised) % _MAX_SEED
        return int(mixed)

    def _advance(
        self, node: int, current: torch.Tensor, interval: float
    ) -> torch.Tensor:
        if self.mode == "deterministic":
            # Exactly the temporal graph's integrator, so deterministic mode is
            # bit-for-bit the existing ODE and not a reimplementation of it.
            return rk4_integrate(
                self._field_for(node), current, 0.0, interval, self.integration_steps
            )
        return self._simulate(node, current, interval, n_paths=1)[0]

    def _simulate(
        self, node: int, current: torch.Tensor, interval: float, n_paths: int
    ) -> torch.Tensor:
        if self.antithetic and n_paths % 2 != 0:
            # An odd request cannot be paired; pad up and drop the extra, so the
            # antithetic option is honoured rather than silently ignored.
            padded = n_paths + 1
        else:
            padded = n_paths
        generator = torch.Generator(device=current.device)
        generator.manual_seed(self._derived_seed(node, interval))

        def drift(state: torch.Tensor, time: torch.Tensor) -> torch.Tensor:
            return self.field(state, time)

        paths = simulate_paths(
            drift=drift,
            diffusion=self.diffusion,
            z0=current,
            t0=0.0,
            t1=float(interval),
            steps=self.integration_steps,
            n_paths=padded,
            integrator=self.mode,
            generator=generator,
            antithetic=self.antithetic,
        )
        return paths.terminal()[:n_paths].detach()

    def to_dict(self) -> Dict[str, object]:
        return {
            "n_nodes": self.n_nodes,
            "memory_dim": self.memory_dim,
            "integration_steps": self.integration_steps,
            "mode": self.mode,
            "stochastic": self.is_stochastic,
            "seed": self.seed,
            "antithetic": self.antithetic,
        }
