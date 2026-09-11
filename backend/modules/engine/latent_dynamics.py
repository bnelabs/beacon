"""Latent stress propagation as a caller-declared stochastic differential equation.

Why this module exists
----------------------

:mod:`backend.modules.engine.neural_sde` implemented a Stochastic Differential
Equation for the continuous-time graph memory -- a learned drift, a positive
diagonal diffusion, strong integrators, a path sampler and an
``NeuralSDEMemory`` that mirrors ``TemporalGraphMemory`` -- and was thoroughly
tested. Nothing in production imported it. It was an orphan, and the project
documentation described it as a shipped capability, which made the documentation
overstate the system.

This module is the production face of that SDE. It answers one question the
deterministic model cannot: *given a declared SDE and a per-institution initial
latent stress state, how much does the terminal state disperse?* That is the
signature systemic risk is about -- pre-crisis markets can share a mean with calm
markets and differ in how volatile they are -- and a deterministic flow cannot
express it. The simulation is built on ``NeuralSDEMemory`` so the object being
driven is the same memory interface the temporal graph uses, not a parallel
reimplementation of it.

What the numbers are, and what they are NOT
-------------------------------------------

**The reported dispersion is a simulated scenario dispersion under a
caller-declared SDE. It is not a calibrated prediction interval, and it must not
be reported as one.** The reason is the one that already governs the rest of this
package: :mod:`backend.modules.engine.prediction_engine` refuses to report
MC-dropout "confidence intervals" because they describe a different network from
the one that produced the prediction and carry no coverage guarantee, and
``bank_analyzer.CONFIDENCE_METHOD_PENDING`` records that calibrated intervals do
not exist yet. Smuggling an SDE dispersion into ``confidence_lower`` /
``confidence_upper`` would be the same defect wearing a new name.

Concretely, this code does **not**:

* fit or calibrate the drift or the diffusion -- both are declared by the caller,
  and the default declaration is a constant-coefficient Ornstein-Uhlenbeck form
  whose parameters are inputs, not estimates;
* verify that the declared process matches realised data, so no coverage
  statement, no "x% interval", and no probability of a threshold breach follows
  from the dispersion;
* produce a forecast of the level of stress. It propagates the *uncertainty*
  around a declared drift, and the terminal mean of that propagation is a
  property of the declared drift, not a prediction.

Every result carries :data:`DISPERSION_LABEL`, a ``calibrated`` flag that is
always ``False`` and :data:`CALIBRATION_NOTE`; the engine report renders the same
caveat in words. A reviewer reading either the payload or the report is told what
the number is.

The declared process
--------------------

With the default declaration the latent state ``z`` follows

    dz = -drift_rate * z dt + diffusion_scale dW

a mean-reverting diffusion: stress decays toward zero at ``drift_rate`` and is
buffeted by Gaussian noise of scale ``diffusion_scale``. The drift is the same
form the temporal graph's ``NeuralODEField`` reduces to when its learned part is
held at zero -- ``-rate * z`` -- so the deterministic limit is the ODE the SDE
replaces, and ``diffusion_scale = 0`` collapses the SDE onto it exactly (the
noise is multiplied by exactly zero). The closed-form terminal standard deviation
of this process is ``diffusion_scale * sqrt((1 - exp(-2*drift_rate*T)) /
(2*drift_rate))`` per coordinate, which is what the tests check the simulation
against; the coordinates are independent because the diffusion is diagonal.

A caller with a *trained* field and diffusion can supply the ``drift`` and
``diffusion`` modules directly instead of the two scalar parameters; the
simulation then propagates those, and this module still neither fits nor
validates them.

What is NOT implemented
-----------------------

* **No calibration, in any sense.** See above.
* **No jumps.** The increments are Gaussian and the process is continuous, so the
  fat tails of a genuine crisis -- a discrete funding freeze, a margin call
  arriving as one impulse -- are understated. A jump-diffusion
  (``dz = f dt + g dW + h dN``) is not implemented here or in the SDE module.
* **No cross-coordinate correlation.** The diffusion is diagonal by
  construction, so two coordinates of one institution's latent state cannot be
  driven by correlated noise, and neither can two institutions.
* **No cross-institution coupling.** Each node's memory evolves independently:
  the SDE propagates uncertainty *within* an institution's latent state, not
  contagion *between* institutions. Contagion between institutions is the
  clearing engine's job (:mod:`backend.modules.risk.clearing`).
* **No adaptive step size.** ``dt`` is fixed by the caller and
  ``horizon / dt`` must be a whole number of steps, because the declared step
  cannot otherwise be honoured exactly; an indivisible pair raises rather than
  being silently rounded.
* **The dispersion describes the sampled paths only.** It is the population
  standard deviation over the drawn paths, so with ``n_paths = 1`` it is
  identically zero and carries no information. ``n_paths`` is reported alongside
  it so that degenerate case is visible.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field as dataclass_field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import torch
import torch.nn as nn

from backend.modules.engine.neural_sde import (
    ConstantDiffusion,
    DriftField,
    NeuralSDEMemory,
)

__all__ = [
    "CALIBRATION_NOTE",
    "DISPERSION_LABEL",
    "STOCHASTIC_MODES",
    "LatentDynamicsResult",
    "LatentDynamicsScenario",
    "simulate_latent_stress",
]

#: Machine-readable label carried by every result. It states the epistemic status
#: of the number: a scenario dispersion, not an interval.
DISPERSION_LABEL = "simulated_terminal_dispersion_under_declared_sde"

#: Integrators the simulation may use. ``deterministic`` is deliberately excluded:
#: this capability exists to sample, and a deterministic run would report a
#: dispersion of exactly zero while looking like a simulation.
STOCHASTIC_MODES = ("euler_maruyama", "milstein")

#: The caveat attached to every result, in words, so a consumer that never reads
#: the module docstring still cannot mistake the dispersion for a calibrated
#: interval.
CALIBRATION_NOTE = (
    "Simulated scenario dispersion under a caller-declared SDE. NOT a calibrated "
    "prediction interval. The drift and diffusion are supplied by the caller and "
    "are not fitted to data, validated against realised outcomes, or accompanied "
    "by any coverage guarantee; the dispersion says only what the declared "
    "process implies about the spread of its own terminal state."
)


def _finite_number(value: object, name: str) -> float:
    """Coerce to ``float`` and fail closed on anything not finite."""
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a real number, got {value!r}") from error
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return number


def _positive_number(value: object, name: str, *, allow_zero: bool = False) -> float:
    number = _finite_number(value, name)
    if allow_zero:
        if number < 0.0:
            raise ValueError(f"{name} must be non-negative, got {value!r}")
    elif number <= 0.0:
        raise ValueError(f"{name} must be strictly positive, got {value!r}")
    return number


def _normalise_states(
    initial_states: Mapping[str, Sequence[float]],
) -> Tuple[Tuple[str, Tuple[float, ...]], ...]:
    """Validate and freeze per-institution initial latent states.

    Returns an ordered tuple of ``(institution_id, state_vector)`` so the node
    order that the memory is written in is fixed and inspectable, and so the
    scenario is hashable despite starting life as a mapping.

    Raises:
        TypeError: ``initial_states`` is not a mapping.
        ValueError: it is empty, an id is blank, a state is not a sequence of
            finite numbers, or the widths disagree. A mismatched width cannot be
            simulated: ``NeuralSDEMemory`` has one ``memory_dim``, so honouring
            two widths at once is impossible and must not be silently truncated
            or zero-padded.
    """
    if not isinstance(initial_states, Mapping):
        raise TypeError(
            "initial_states must be a mapping of institution id to latent state, "
            f"got {type(initial_states).__name__}"
        )
    if not initial_states:
        raise ValueError("initial_states must name at least one institution")

    normalised: list[Tuple[str, Tuple[float, ...]]] = []
    width: Optional[int] = None
    for raw_name, raw_state in initial_states.items():
        name = str(raw_name)
        if not name.strip():
            raise ValueError("institution ids must be non-empty strings")
        if raw_state is None or isinstance(raw_state, (str, bytes)):
            raise ValueError(
                f"initial state for {name!r} must be a sequence of numbers, got "
                f"{raw_state!r}"
            )
        try:
            vector = tuple(
                _finite_number(value, f"initial state for {name!r}") for value in raw_state
            )
        except TypeError as error:
            raise ValueError(
                f"initial state for {name!r} must be an iterable sequence of numbers"
            ) from error
        if not vector:
            raise ValueError(f"initial state for {name!r} must have at least one element")
        if width is None:
            width = len(vector)
        elif len(vector) != width:
            raise ValueError(
                f"initial state for {name!r} has width {len(vector)} but the first "
                f"institution declared width {width}; the SDE memory has a single "
                "width, so a mismatched state cannot be simulated"
            )
        normalised.append((name, vector))

    ids = [name for name, _ in normalised]
    duplicates = sorted({name for name in ids if ids.count(name) > 1})
    if duplicates:
        raise ValueError(
            f"initial_states repeats institution id(s) after string coercion: {duplicates}"
        )
    return tuple(normalised)


@dataclass(frozen=True)
class LatentDynamicsScenario:
    """A caller-declared SDE run over per-institution initial latent states.

    The scenario is *frozen* because a scenario that changed between the
    validation of its inputs and the simulation of them could be simulated with
    parameters it was never checked against. It states the epistemic contract
    explicitly: the drift and the diffusion are inputs, not estimates.

    Args:
        initial_states: ``institution_id ->`` initial latent stress vector. All
            vectors must share one width, because the SDE memory has one
            ``memory_dim``. Normalised at construction to an ordered tuple of
            ``(id, vector)`` pairs.
        horizon: Length of the simulated interval ``T``, in the time units the
            caller's drift and diffusion are expressed in. Strictly positive and
            finite. It is a *declared* horizon, not a calendar date: this module
            has no clock.
        dt: Fixed integration step. Strictly positive and finite, and ``horizon``
            must be an integer multiple of it (see ``steps``).
        n_paths: Number of sampled paths. At least 1. With 1 the reported
            dispersion is identically zero and carries no information.
        seed: Seed for the sampled Wiener increments. Required: every result in
            this package must be reproducible, and an unseeded stochastic run is
            not.
        drift_rate: Decay rate of the declared ``-drift_rate * z`` drift. Exactly
            one of ``drift_rate`` / ``drift`` must be supplied.
        diffusion_scale: Scale of the declared constant diagonal diffusion.
            Exactly one of ``diffusion_scale`` / ``diffusion`` must be supplied.
            Zero is allowed and is the exact reduction to the deterministic ODE.
        drift: Optional caller-supplied drift module ``(state, time) -> d(state)/dt``.
            Replaces the declared linear drift; mutually exclusive with
            ``drift_rate``.
        diffusion: Optional caller-supplied diagonal diffusion module
            ``(state, time) -> g(state, time)``. Replaces the declared constant
            diffusion; mutually exclusive with ``diffusion_scale``.
        integrator: One of :data:`STOCHASTIC_MODES`.
        antithetic: Draw the sampled paths in ``+/-`` pairs, which cancels the
            leading linear part of the noise. With an odd ``n_paths`` the memory
            pads by one and discards the extra, so the option is honoured rather
            than silently ignored.
    """

    initial_states: Mapping[str, Sequence[float]]
    horizon: float
    dt: float
    n_paths: int
    seed: int
    drift_rate: Optional[float] = None
    diffusion_scale: Optional[float] = None
    drift: Optional[Any] = dataclass_field(default=None, repr=False, compare=False)
    diffusion: Optional[Any] = dataclass_field(default=None, repr=False, compare=False)
    integrator: str = "euler_maruyama"
    antithetic: bool = False

    def __post_init__(self) -> None:
        horizon = _positive_number(self.horizon, "horizon")
        dt = _positive_number(self.dt, "dt")

        if isinstance(self.n_paths, bool) or not isinstance(self.n_paths, int):
            raise ValueError(f"n_paths must be an integer, got {self.n_paths!r}")
        if self.n_paths < 1:
            raise ValueError(f"n_paths must be at least 1, got {self.n_paths}")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError(f"seed must be an integer, got {self.seed!r}")
        if self.integrator not in STOCHASTIC_MODES:
            raise ValueError(
                f"integrator must be one of {STOCHASTIC_MODES}, got {self.integrator!r}; "
                "the deterministic mode is excluded because it would report a "
                "dispersion of exactly zero while looking like a simulation"
            )

        ratio = horizon / dt
        steps = int(round(ratio))
        if steps < 1 or not math.isclose(ratio, steps, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError(
                "horizon must be a whole number of steps of the declared dt so the "
                f"declared step can be honoured exactly; got horizon={horizon!r}, "
                f"dt={dt!r} (ratio {ratio!r})"
            )

        if (self.drift_rate is None) == (self.drift is None):
            raise ValueError(
                "declare exactly one of drift_rate (the linear mean-reversion rate) "
                "or a caller-supplied drift module"
            )
        drift_rate: Optional[float] = None
        if self.drift_rate is not None:
            drift_rate = _positive_number(self.drift_rate, "drift_rate")
        elif not callable(self.drift):
            raise ValueError(
                "the supplied drift must be callable as drift(state, time) and "
                f"return d(state)/dt, got {type(self.drift).__name__}"
            )

        if (self.diffusion_scale is None) == (self.diffusion is None):
            raise ValueError(
                "declare exactly one of diffusion_scale (the constant diagonal "
                "scale) or a caller-supplied diffusion module"
            )
        diffusion_scale: Optional[float] = None
        if self.diffusion_scale is not None:
            diffusion_scale = _positive_number(
                self.diffusion_scale, "diffusion_scale", allow_zero=True
            )
        elif not callable(self.diffusion):
            raise ValueError(
                "the supplied diffusion must be callable as diffusion(state, time) "
                f"and return g(state, time), got {type(self.diffusion).__name__}"
            )

        states = _normalise_states(self.initial_states)

        object.__setattr__(self, "horizon", horizon)
        object.__setattr__(self, "dt", dt)
        object.__setattr__(self, "drift_rate", drift_rate)
        object.__setattr__(self, "diffusion_scale", diffusion_scale)
        object.__setattr__(self, "initial_states", states)

    # -- derived, immutable views ------------------------------------------

    @property
    def institution_ids(self) -> Tuple[str, ...]:
        """Ids in the order the memory nodes are written."""
        return tuple(name for name, _ in self.initial_states)

    @property
    def state_width(self) -> int:
        """Common latent width of every initial state."""
        return len(self.initial_states[0][1])

    @property
    def steps(self) -> int:
        """Whole number of integration steps; ``horizon / dt`` is validated integral."""
        return int(round(self.horizon / self.dt))


@dataclass(frozen=True)
class LatentDynamicsResult:
    """Terminal dispersion of the simulated latent stress paths.

    Every field describes the *sample* that was drawn, not a calibrated
    distribution. See :data:`CALIBRATION_NOTE`; ``calibrated`` is always
    ``False`` and ``label`` is always :data:`DISPERSION_LABEL`. There is no
    ``confidence_*`` field on purpose.

    Attributes:
        terminal_mean: Per-institution terminal mean of the sampled paths, per
            coordinate. A property of the declared drift, not a forecast.
        terminal_std: Per-institution terminal population standard deviation
            (``unbiased=False``) of the sampled paths, per coordinate. With
            ``n_paths = 1`` this is identically zero.
        terminal_dispersion: Per-institution scalar summary --
            ``||terminal_std||_2`` over coordinates. This is the object the
            capability exists to report.
        drift_only_terminal: Per-institution terminal state of the deterministic
            drift ODE, integrated with the temporal graph's RK4 scheme over the
            same horizon and step count. It is the path the SDE collapses onto
            when the diffusion vanishes, and it is reported so a reader can see
            what the sampled spread sits around rather than having to trust the
            mean alone.
        mean_dispersion, max_dispersion: Cross-institution summaries of
            ``terminal_dispersion``.
    """

    institution_ids: Tuple[str, ...]
    state_width: int
    horizon: float
    dt: float
    steps: int
    n_paths: int
    seed: int
    integrator: str
    antithetic: bool
    drift_description: str
    diffusion_description: str
    terminal_mean: Mapping[str, Tuple[float, ...]]
    terminal_std: Mapping[str, Tuple[float, ...]]
    terminal_dispersion: Mapping[str, float]
    drift_only_terminal: Mapping[str, Tuple[float, ...]]
    mean_dispersion: float
    max_dispersion: float

    #: Always :data:`DISPERSION_LABEL`; carried as a field so it survives
    #: serialisation without the producer having to remember it.
    label: str = DISPERSION_LABEL
    #: Always ``False``. There is no code path that sets it true, and there must
    #: not be until real conformal calibration exists.
    calibrated: bool = False
    calibration_note: str = CALIBRATION_NOTE

    @property
    def is_calibrated(self) -> bool:
        """Whether this is a calibrated prediction interval. Always ``False``."""
        return False

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready payload.

        The label, the calibration note and ``not_a_prediction_interval`` are
        inlined at the top level so that a consumer reading only the serialised
        form still sees what the numbers are. Full path tensors are not included:
        only the terminal summaries are, which keeps the payload small and makes
        the reported uncertainty the only stochastic object that escapes.
        """
        return {
            "label": self.label,
            "calibrated": bool(self.calibrated),
            "calibration_note": self.calibration_note,
            "not_a_prediction_interval": True,
            "institution_ids": list(self.institution_ids),
            "state_width": int(self.state_width),
            "horizon": float(self.horizon),
            "dt": float(self.dt),
            "steps": int(self.steps),
            "n_paths": int(self.n_paths),
            "seed": int(self.seed),
            "integrator": self.integrator,
            "antithetic": bool(self.antithetic),
            "drift": self.drift_description,
            "diffusion": self.diffusion_description,
            "terminal_mean": {
                name: [float(value) for value in values]
                for name, values in self.terminal_mean.items()
            },
            "terminal_std": {
                name: [float(value) for value in values]
                for name, values in self.terminal_std.items()
            },
            "terminal_dispersion": {
                name: float(value) for name, value in self.terminal_dispersion.items()
            },
            "drift_only_terminal": {
                name: [float(value) for value in values]
                for name, values in self.drift_only_terminal.items()
            },
            "mean_dispersion": float(self.mean_dispersion),
            "max_dispersion": float(self.max_dispersion),
        }


def _resolve_dtype(scenario: LatentDynamicsScenario) -> torch.dtype:
    """Match the simulation dtype to a caller-supplied module when there is one.

    The declared configuration runs in ``float32``. A supplied module may hold
    ``float64`` parameters, and PyTorch refuses to mix parameter and input
    dtypes, so the state is built in the first supplied module's dtype rather
    than the caller being surprised by a ``RuntimeError`` deep in a forward pass.
    """
    for module in (scenario.drift, scenario.diffusion):
        if isinstance(module, nn.Module):
            for parameter in module.parameters():
                return parameter.dtype
    return torch.float32


def _build_declared_drift(scenario: LatentDynamicsScenario, dtype: torch.dtype) -> nn.Module:
    """``-drift_rate * z`` as a ``DriftField`` with its learned part held at zero.

    Using ``DriftField`` rather than a bespoke lambda is deliberate: it is the
    same field type the SDE module uses, so the deterministic limit is the
    temporal graph's own ``-rate * z`` form and the reduction to the ODE is a
    property of two implementations of the same equation agreeing, not of a
    special-cased shortcut.
    """
    field = DriftField(scenario.state_width, rate=float(scenario.drift_rate))
    with torch.no_grad():
        for parameter in field.net.parameters():
            parameter.zero_()
    return field.to(dtype)


def simulate_latent_stress(scenario: LatentDynamicsScenario) -> LatentDynamicsResult:
    """Sample the declared SDE and report the terminal dispersion.

    This is the production entry point. It writes each institution's initial
    latent state into an :class:`~backend.modules.engine.neural_sde.NeuralSDEMemory`
    as node ``i``, advances every node to ``scenario.horizon`` with the declared
    integrator and the declared diffusion, and summarises the terminal sample.
    The deterministic drift-only terminal is computed from a second memory in the
    SDE module's deterministic mode, so the comparison uses the temporal graph's
    RK4 integrator rather than a re-derivation of it.

    The store is never left mutated in a way a caller can observe: both memories
    are local to this call.

    Args:
        scenario: The declared SDE and its initial states.

    Returns:
        A :class:`LatentDynamicsResult`. It is a scenario dispersion and says so.

    Raises:
        TypeError: ``scenario`` is not a :class:`LatentDynamicsScenario`.
        ValueError: the sampled terminal state is non-finite. That is a
            divergence of the declared process, not a number to report, so it
            fails closed rather than emitting ``nan`` dispersion.
    """
    if not isinstance(scenario, LatentDynamicsScenario):
        raise TypeError(
            "scenario must be a LatentDynamicsScenario, got "
            f"{type(scenario).__name__}"
        )

    items = scenario.initial_states
    ids = scenario.institution_ids
    width = scenario.state_width
    steps = scenario.steps
    dtype = _resolve_dtype(scenario)

    if scenario.drift is not None:
        field: Any = scenario.drift
        drift_description = f"caller_supplied_module:{type(scenario.drift).__name__}"
    else:
        field = _build_declared_drift(scenario, dtype)
        drift_description = (
            f"declared_linear_mean_reversion:dz/dt=-{scenario.drift_rate:g}*z"
        )

    if scenario.diffusion is not None:
        diffusion: Any = scenario.diffusion
        diffusion_description = (
            f"caller_supplied_module:{type(scenario.diffusion).__name__}"
        )
    else:
        diffusion = ConstantDiffusion(float(scenario.diffusion_scale))
        diffusion_description = (
            f"declared_constant_diagonal:sigma={scenario.diffusion_scale:g}"
        )

    stochastic = NeuralSDEMemory(
        len(ids),
        memory_dim=width,
        field=field,
        integration_steps=steps,
        mode=scenario.integrator,
        diffusion=diffusion,
        seed=scenario.seed,
        antithetic=scenario.antithetic,
    )
    deterministic = NeuralSDEMemory(
        len(ids),
        memory_dim=width,
        field=field,
        integration_steps=steps,
        mode="deterministic",
    )

    for node, (_name, vector) in enumerate(items):
        state = torch.tensor(vector, dtype=dtype)
        stochastic.write(node, state, time=0.0)
        deterministic.write(node, state, time=0.0)

    terminal_mean: Dict[str, Tuple[float, ...]] = {}
    terminal_std: Dict[str, Tuple[float, ...]] = {}
    terminal_dispersion: Dict[str, float] = {}
    drift_only_terminal: Dict[str, Tuple[float, ...]] = {}

    for node, (name, _vector) in enumerate(items):
        samples = stochastic.read_distribution(node, scenario.horizon, scenario.n_paths)
        if not bool(torch.isfinite(samples).all()):
            raise ValueError(
                f"the simulated terminal state for {name!r} is non-finite: the "
                "declared process diverged over this horizon and step size. A "
                "divergence is the result, not a dispersion to report."
            )
        mean = samples.mean(dim=0)
        # Population standard deviation over the drawn paths. `unbiased=True`
        # would be NaN at n_paths == 1; reporting the sample's own spread as zero
        # there is honest, and `n_paths` is reported so the degenerate case is
        # visible to the reader.
        std = samples.std(dim=0, unbiased=False)
        terminal_mean[name] = tuple(float(value) for value in mean)
        terminal_std[name] = tuple(float(value) for value in std)
        terminal_dispersion[name] = float(torch.linalg.vector_norm(std).item())
        drift_only_terminal[name] = tuple(
            float(value)
            for value in deterministic.read(node, scenario.horizon).memory.detach()
        )

    dispersion_values = list(terminal_dispersion.values())
    mean_dispersion = float(sum(dispersion_values) / len(dispersion_values))
    max_dispersion = float(max(dispersion_values))

    return LatentDynamicsResult(
        institution_ids=tuple(ids),
        state_width=width,
        horizon=scenario.horizon,
        dt=scenario.dt,
        steps=steps,
        n_paths=scenario.n_paths,
        seed=scenario.seed,
        integrator=scenario.integrator,
        antithetic=bool(scenario.antithetic),
        drift_description=drift_description,
        diffusion_description=diffusion_description,
        terminal_mean=terminal_mean,
        terminal_std=terminal_std,
        terminal_dispersion=terminal_dispersion,
        drift_only_terminal=drift_only_terminal,
        mean_dispersion=mean_dispersion,
        max_dispersion=max_dispersion,
    )
