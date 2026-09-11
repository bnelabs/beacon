"""TNCM-VAE: counterfactual trajectories over a declared structural causal model.

What is and is not causal here
------------------------------

The name "causal" is doing real work in this file and should not be taken on
trust. A variational autoencoder trained on observational data learns the
*conditional* distribution ``p(x | z)``. It cannot identify a causal direction:
every DAG in an equivalence class implies the same observational likelihood, so no
amount of observational data distinguishes "A causes B" from "B causes A" from "a
common cause drives both". A VAE that claims otherwise is claiming something it
cannot know.

So the causal structure is **declared, not learned**. The caller supplies
:class:`StructuralCausalModel`: which variables exist, who is a parent of whom,
and the structural coefficients. That declaration is the modelling assumption, and
it is written down where it can be argued with. The VAE's jobs are narrower and
honest ones: compress the exogenous variation into a low-dimensional latent,
measure how well the model reconstructs what actually happened, and provide a
prior from which plausible exogenous paths can be drawn.

The counterfactual itself uses Pearl's three steps, which are well defined once the
structure is declared:

1. **Abduction** -- infer the exogenous noise that, together with the structural
   equations, reproduces the observed trajectory exactly. For this linear model
   that inversion is closed form, so the inferred noise is exact rather than
   approximate.
2. **Action** -- replace the structural equation for the intervened variable with
   the intervention. This is what ``do(X = x)`` means: the variable stops being a
   function of its parents, so an intervention severs the incoming edges rather
   than merely conditioning on a value.
3. **Prediction** -- propagate the same inferred noise through the modified
   system.

The distinction this buys is testable. A correlational model, told that one
variable moved, moves everything correlated with it. A structural model moves that
variable's *descendants* and leaves everything else exactly where it was. The
tests check precisely that.

An honest limit on the answer
-----------------------------

Nothing here validates that the declared structure is the true one. The
counterfactual is exactly as good as the DAG and coefficients handed in. What is
verified is the arithmetic: that the procedure reproduces observation when it
should, that intervening severs the right edges, and that effects propagate only
downstream. Whether "downstream" was drawn correctly is a question for the
economics, not for this module.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

__all__ = [
    "StructuralCausalModel",
    "Intervention",
    "CounterfactualResult",
    "TrajectoryConstraints",
    "TrajectoryVAE",
    "CounterfactualError",
]


class CounterfactualError(Exception):
    """Raised when a counterfactual cannot be formed from the given inputs."""


# ---------------------------------------------------------------------------
# Causal structure
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Intervention:
    """A ``do`` operation on one variable.

    Attributes:
        variable: Name of the intervened node.
        value: The value forced on it. A scalar applies at every timestep; a
            sequence of length ``n_steps`` applies per timestep, which is how a
            scenario such as "the funding spread jumps by 200bp at t=3" is
            expressed.
    """

    variable: str
    value: Any

    def value_at(self, step: int, n_steps: int) -> float:
        array = np.asarray(self.value, dtype=float).reshape(-1) if not np.isscalar(
            self.value
        ) else np.asarray([self.value], dtype=float)
        if array.size == 1:
            value = float(array[0])
        elif array.size == n_steps:
            value = float(array[step])
        else:
            raise CounterfactualError(
                f"intervention on {self.variable!r} has {array.size} values, which "
                f"is neither 1 nor the trajectory length {n_steps}"
            )
        if not math.isfinite(value):
            raise CounterfactualError(
                f"intervention on {self.variable!r} is not finite at step {step}"
            )
        return value


@dataclass(frozen=True)
class CounterfactualResult:
    """A factual trajectory, a counterfactual one, and the difference."""

    factual: np.ndarray
    counterfactual: np.ndarray
    variables: Tuple[str, ...]
    interventions: Tuple[Intervention, ...]
    affected: Tuple[str, ...]
    unaffected: Tuple[str, ...]
    constraints_ok: bool
    constraint_violations: Tuple[str, ...] = ()

    @property
    def delta(self) -> np.ndarray:
        return self.counterfactual - self.factual

    def effect_on(self, variable: str) -> np.ndarray:
        """Per-timestep change in one variable."""
        if variable not in self.variables:
            raise KeyError(f"unknown variable {variable!r}")
        return self.delta[:, self.variables.index(variable)]

    @property
    def max_absolute_effect(self) -> float:
        return float(np.max(np.abs(self.delta))) if self.delta.size else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variables": list(self.variables),
            "interventions": [
                {"variable": item.variable, "value": _jsonable(item.value)}
                for item in self.interventions
            ],
            "affected": list(self.affected),
            "unaffected": list(self.unaffected),
            "constraints_ok": bool(self.constraints_ok),
            "constraint_violations": list(self.constraint_violations),
            "max_absolute_effect": self.max_absolute_effect,
            "effect_by_variable": {
                name: float(np.max(np.abs(self.effect_on(name)))) if self.delta.size else 0.0
                for name in self.variables
            },
        }

    def summary(self) -> str:
        if not self.affected:
            return "The intervention changes nothing downstream"
        return (
            f"Intervening on {', '.join(i.variable for i in self.interventions)} "
            f"changes {', '.join(self.affected)} "
            f"(largest change {self.max_absolute_effect:.6g}) and leaves "
            f"{', '.join(self.unaffected) or 'nothing else'} untouched"
        )


def _jsonable(value: Any) -> Any:
    if np.isscalar(value):
        return float(value)
    return [float(item) for item in np.asarray(value, dtype=float).reshape(-1)]


class StructuralCausalModel:
    """A declared linear structural model with contemporaneous and lagged edges.

    Each variable follows::

        X_i(t) = intercept_i
                 + sum_{j in parents(i)} a_ij * X_j(t)      contemporaneous
                 + b_i * X_i(t - 1)                          own lag
                 + eps_i(t)                                  exogenous noise

    The self-lag is what makes this a *time-series* causal model rather than a
    static one: an intervention persists through its own dynamics as well as
    propagating through the contemporaneous graph.

    Args:
        variables: Variable names, in any order.
        coefficients: ``{child: {parent: coefficient}}`` for contemporaneous
            edges. Any parent named must be a declared variable. Defaults to no
            contemporaneous edges, which is the correct model for a set of series
            coupled only through their own lags.
        self_lag: ``{variable: coefficient}`` on the variable's own lag.
        intercepts: ``{variable: constant}``.
        initial_state: Values at ``t = -1``, used for the lag term at ``t = 0``.
            Defaults to zeros.
    """

    def __init__(
        self,
        variables: Sequence[str],
        coefficients: Optional[Mapping[str, Mapping[str, float]]] = None,
        self_lag: Optional[Mapping[str, float]] = None,
        intercepts: Optional[Mapping[str, float]] = None,
        initial_state: Optional[Mapping[str, float]] = None,
    ) -> None:
        names = tuple(variables)
        if not names:
            raise ValueError("a structural model needs at least one variable")
        if len(set(names)) != len(names):
            raise ValueError("variable names must be unique")
        self.variables = names
        self.index = {name: position for position, name in enumerate(names)}

        parents: Dict[str, Tuple[str, ...]] = {name: () for name in names}
        self.coefficients: Dict[str, Dict[str, float]] = {name: {} for name in names}
        for child, mapping in (coefficients or {}).items():
            if child not in self.index:
                raise ValueError(f"coefficients reference unknown child {child!r}")
            for parent, value in mapping.items():
                if parent not in self.index:
                    raise ValueError(
                        f"variable {child!r} lists parent {parent!r}, which is not "
                        "a declared variable"
                    )
                if parent == child:
                    raise ValueError(
                        f"variable {child!r} lists itself as a contemporaneous "
                        "parent; use self_lag for own dynamics"
                    )
                if not math.isfinite(float(value)):
                    raise ValueError(
                        f"coefficient {child!r} <- {parent!r} is not finite"
                    )
                self.coefficients[child][parent] = float(value)
            parents[child] = tuple(mapping.keys())
        self.parents = parents

        self.self_lag = {name: float((self_lag or {}).get(name, 0.0)) for name in names}
        self.intercepts = {name: float((intercepts or {}).get(name, 0.0)) for name in names}
        for name, value in self.self_lag.items():
            if not math.isfinite(value):
                raise ValueError(f"self_lag for {name!r} is not finite")
            if abs(value) >= 1.0:
                # |b| >= 1 makes the recursion non-stationary: a shock never decays.
                logger.warning(
                    "self_lag for %s is %s, which is at or beyond the stability "
                    "boundary; trajectories will not mean-revert",
                    name,
                    value,
                )
        for name, value in self.intercepts.items():
            if not math.isfinite(value):
                raise ValueError(f"intercept for {name!r} is not finite")

        initial = initial_state or {}
        unknown = set(initial) - set(names)
        if unknown:
            raise ValueError(f"initial_state names unknown variables: {sorted(unknown)}")
        self.initial_state = np.asarray(
            [float(initial.get(name, 0.0)) for name in names], dtype=float
        )

        self.order = self._topological_order()

    # -- structure ------------------------------------------------------

    def _topological_order(self) -> Tuple[str, ...]:
        """Kahn's algorithm over the contemporaneous edges; raises on a cycle."""
        in_degree = {name: len(self.parents[name]) for name in self.variables}
        children: Dict[str, List[str]] = {name: [] for name in self.variables}
        for child, parents in self.parents.items():
            for parent in parents:
                children[parent].append(child)

        ready = sorted(name for name, degree in in_degree.items() if degree == 0)
        order: List[str] = []
        while ready:
            name = ready.pop(0)
            order.append(name)
            for child in sorted(children[name]):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    ready.append(child)

        if len(order) != len(self.variables):
            cyclic = sorted(set(self.variables) - set(order))
            raise ValueError(
                f"the contemporaneous edges contain a cycle through {cyclic}; a "
                "structural model must be acyclic"
            )
        return tuple(order)

    def descendants(self, variable: str) -> Tuple[str, ...]:
        """Every variable reachable downstream, excluding ``variable`` itself.

        The self-lag is deliberately excluded: it propagates a variable's own
        history, not causal influence on anything else.
        """
        if variable not in self.index:
            raise KeyError(f"unknown variable {variable!r}")
        children: Dict[str, List[str]] = {name: [] for name in self.variables}
        for child, parents in self.parents.items():
            for parent in parents:
                children[parent].append(child)

        seen: set = set()
        frontier = list(children[variable])
        while frontier:
            node = frontier.pop()
            if node in seen:
                continue
            seen.add(node)
            frontier.extend(children[node])
        return tuple(name for name in self.variables if name in seen)

    # -- the three steps ------------------------------------------------

    def abduct(self, observations: np.ndarray) -> np.ndarray:
        """Recover the exogenous noise that reproduces ``observations`` exactly.

        The structural equations are linear, so this is a closed-form inversion
        rather than an approximation. That matters: abduction with an approximate
        noise recovers the observation only approximately, and the identity test
        below would then be measuring the approximation error instead of the
        correctness of the procedure.
        """
        matrix = self._as_trajectory(observations)
        n_steps = matrix.shape[0]
        noise = np.zeros_like(matrix)

        for step in range(n_steps):
            for name in self.order:
                position = self.index[name]
                predicted = self._structural_value(name, step, matrix, n_steps)
                noise[step, position] = matrix[step, position] - predicted
        return noise

    def _structural_value(
        self, name: str, step: int, matrix: np.ndarray, n_steps: int
    ) -> float:
        """Right-hand side of ``name``'s structural equation, without noise."""
        position = self.index[name]
        value = self.intercepts[name]
        for parent, coefficient in self.coefficients[name].items():
            value += coefficient * matrix[step, self.index[parent]]
        lagged = (
            matrix[step - 1, position]
            if step > 0
            else self.initial_state[position]
        )
        value += self.self_lag[name] * lagged
        return float(value)

    def propagate(
        self,
        exogenous: np.ndarray,
        interventions: Sequence[Intervention] = (),
        initial_state: Optional[Sequence[float]] = None,
    ) -> np.ndarray:
        """Run the structural equations forward under a set of interventions."""
        noise = np.asarray(exogenous, dtype=float)
        if noise.ndim == 1:
            noise = noise.reshape(-1, 1)
        if noise.shape[1] != len(self.variables):
            raise ValueError(
                f"exogenous noise has {noise.shape[1]} columns but the model has "
                f"{len(self.variables)} variables"
            )
        n_steps = noise.shape[0]
        if n_steps == 0:
            raise ValueError("exogenous noise is empty")

        registry = self._intervention_map(interventions)
        initial = (
            self.initial_state
            if initial_state is None
            else np.asarray(list(initial_state), dtype=float)
        )
        if initial.size != len(self.variables):
            raise ValueError(
                f"initial_state has {initial.size} entries but the model has "
                f"{len(self.variables)} variables"
            )

        out = np.zeros((n_steps, len(self.variables)), dtype=float)
        for step in range(n_steps):
            for name in self.order:
                position = self.index[name]
                if name in registry:
                    # Action: the equation is replaced, so the incoming edges are
                    # severed. This is what distinguishes do(X = x) from
                    # conditioning on X = x.
                    out[step, position] = registry[name].value_at(step, n_steps)
                    continue

                value = self.intercepts[name]
                for parent, coefficient in self.coefficients[name].items():
                    if parent in registry:
                        # A parent that was intervened on supplies its forced
                        # value at this step, which the topological order
                        # guarantees has already been written.
                        parent_value = registry[parent].value_at(step, n_steps)
                    else:
                        parent_value = out[step, self.index[parent]]
                    value += coefficient * parent_value
                lagged = out[step - 1, position] if step > 0 else initial[position]
                value += self.self_lag[name] * lagged
                out[step, position] = value + noise[step, position]
        return out

    def counterfactual(
        self,
        observations: np.ndarray,
        interventions: Sequence[Intervention],
        constraints: Optional["TrajectoryConstraints"] = None,
    ) -> CounterfactualResult:
        """Abduction, action, prediction.

        Args:
            observations: The factual trajectory, ``(n_steps, n_variables)``.
            interventions: The ``do`` operations to apply.
            constraints: Optional feasibility checks applied to the result.

        Returns:
            A :class:`CounterfactualResult` including which variables moved.
        """
        factual = self._as_trajectory(observations)
        if not interventions:
            raise CounterfactualError(
                "a counterfactual needs at least one intervention; without one the "
                "answer is the observation and the procedure would test nothing"
            )

        # Validate the targets before doing any work, so a typo fails loudly
        # rather than producing a counterfactual that quietly ignored it.
        self._intervention_map(interventions)
        noise = self.abduct(factual)
        counterfactual = self.propagate(noise, interventions)

        delta = counterfactual - factual
        affected: List[str] = []
        unaffected: List[str] = []
        for name in self.variables:
            position = self.index[name]
            moved = bool(np.max(np.abs(delta[:, position])) > 1e-9)
            (affected if moved else unaffected).append(name)

        violations: Tuple[str, ...] = ()
        ok = True
        if constraints is not None:
            ok, violations = constraints.check(counterfactual, self.variables)

        return CounterfactualResult(
            factual=factual,
            counterfactual=counterfactual,
            variables=self.variables,
            interventions=tuple(interventions),
            affected=tuple(affected),
            unaffected=tuple(unaffected),
            constraints_ok=ok,
            constraint_violations=violations,
        )

    def _intervention_map(
        self, interventions: Sequence[Intervention]
    ) -> Dict[str, Intervention]:
        registry: Dict[str, Intervention] = {}
        for item in interventions:
            if item.variable not in self.index:
                raise CounterfactualError(
                    f"intervention targets {item.variable!r}, which is not a "
                    f"declared variable; known: {list(self.variables)}"
                )
            registry[item.variable] = item
        return registry

    def _as_trajectory(self, observations: np.ndarray) -> np.ndarray:
        matrix = np.asarray(observations, dtype=float)
        if matrix.ndim != 2:
            raise ValueError(
                f"observations must be 2-D (steps, variables), got shape {matrix.shape}"
            )
        if matrix.shape[1] != len(self.variables):
            raise ValueError(
                f"observations have {matrix.shape[1]} columns but the model has "
                f"{len(self.variables)} variables"
            )
        if matrix.shape[0] == 0:
            raise ValueError("observations are empty")
        if not np.all(np.isfinite(matrix)):
            raise ValueError("observations contain non-finite values")
        return matrix

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variables": list(self.variables),
            "topological_order": list(self.order),
            "coefficients": {k: dict(v) for k, v in self.coefficients.items()},
            "self_lag": dict(self.self_lag),
            "intercepts": dict(self.intercepts),
        }


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TrajectoryConstraints:
    """Feasibility bounds a counterfactual must respect to be believable.

    A structural model will happily produce a negative funding spread or a
    negative capital ratio if the arithmetic says so. Neither is a plausible
    state of the world, so constraints are checked and reported rather than
    silently clipped -- clipping would hide that the counterfactual had left the
    feasible region, which is itself the interesting finding.

    Args:
        lower: ``{variable: minimum}``.
        upper: ``{variable: maximum}``.
    """

    lower: Mapping[str, float] = field(default_factory=dict)
    upper: Mapping[str, float] = field(default_factory=dict)

    def check(
        self, trajectory: np.ndarray, variables: Sequence[str]
    ) -> Tuple[bool, Tuple[str, ...]]:
        matrix = np.asarray(trajectory, dtype=float)
        violations: List[str] = []
        for name, bound in self.lower.items():
            if name not in variables:
                raise ValueError(f"lower bound names unknown variable {name!r}")
            position = list(variables).index(name)
            worst = float(np.min(matrix[:, position]))
            if worst < bound - 1e-12:
                violations.append(
                    f"{name} falls to {worst:.6g}, below the lower bound {bound:.6g}"
                )
        for name, bound in self.upper.items():
            if name not in variables:
                raise ValueError(f"upper bound names unknown variable {name!r}")
            position = list(variables).index(name)
            worst = float(np.max(matrix[:, position]))
            if worst > bound + 1e-12:
                violations.append(
                    f"{name} rises to {worst:.6g}, above the upper bound {bound:.6g}"
                )
        return (not violations, tuple(violations))


# ---------------------------------------------------------------------------
# Generative model
# ---------------------------------------------------------------------------

class TrajectoryVAE:
    """A small variational autoencoder over flattened trajectories.

    Its role is generative, not causal: it learns a low-dimensional latent for the
    exogenous variation, reports how well it reconstructs what happened, and can
    sample plausible alternative paths. The counterfactual itself comes from the
    structural model, because a VAE cannot identify direction.

    Args:
        n_features: Flattened trajectory length (``n_steps * n_variables``).
        latent_dim: Latent width.
        hidden_dim: Hidden width.
        seed: Seed for reproducible initialisation and sampling.
    """

    def __init__(
        self,
        n_features: int,
        latent_dim: int = 4,
        hidden_dim: int = 64,
        seed: Optional[int] = None,
    ) -> None:
        if n_features < 1:
            raise ValueError(f"n_features must be positive, got {n_features}")
        if latent_dim < 1:
            raise ValueError(f"latent_dim must be positive, got {latent_dim}")
        if hidden_dim < 1:
            raise ValueError(f"hidden_dim must be positive, got {hidden_dim}")

        import torch
        import torch.nn as nn

        self._torch = torch
        self.n_features = int(n_features)
        self.latent_dim = int(latent_dim)
        self.hidden_dim = int(hidden_dim)
        self.seed = seed
        self.generator = torch.Generator().manual_seed(seed if seed is not None else 0)

        torch.manual_seed(seed if seed is not None else 0)
        self.encoder = nn.Sequential(
            nn.Linear(self.n_features, self.hidden_dim),
            nn.ReLU(),
            nn.Linear(self.hidden_dim, 2 * self.latent_dim),
        )
        self.decoder = nn.Sequential(
            nn.Linear(self.latent_dim, self.hidden_dim),
            nn.ReLU(),
            nn.Linear(self.hidden_dim, self.n_features),
        )
        self.training_history: List[float] = []

    # -- internals ------------------------------------------------------

    def _parameters(self) -> List[Any]:
        return list(self.encoder.parameters()) + list(self.decoder.parameters())

    def _as_matrix(self, X: Any) -> Any:
        tensor = self._torch.as_tensor(np.asarray(X, dtype=np.float32))
        if tensor.ndim == 1:
            tensor = tensor.reshape(1, -1)
        if tensor.ndim != 2 or tensor.shape[1] != self.n_features:
            raise ValueError(
                f"expected trajectories of width {self.n_features}, got shape "
                f"{tuple(tensor.shape)}"
            )
        return tensor

    def encode(self, X: Any) -> Tuple[Any, Any]:
        """Posterior mean and log-variance of the latent for each trajectory."""
        with self._torch.no_grad():
            output = self.encoder(self._as_matrix(X))
        return output[:, : self.latent_dim], output[:, self.latent_dim :]

    def reconstruct(self, X: Any) -> np.ndarray:
        """Reconstruction through the posterior mean (no sampling noise)."""
        matrix = self._as_matrix(X)
        with self._torch.no_grad():
            mean, _ = self.encode(matrix)
            return self.decoder(mean).numpy()

    def sample(self, n: int) -> np.ndarray:
        """Draw trajectories from the prior."""
        if n < 1:
            raise ValueError(f"n must be positive, got {n}")
        with self._torch.no_grad():
            latent = self._torch.randn(
                n, self.latent_dim, generator=self.generator
            )
            return self.decoder(latent).numpy()

    def elbo(self, X: Any) -> float:
        """Mean evidence lower bound on the given data."""
        torch = self._torch
        matrix = self._as_matrix(X)
        output = self.encoder(matrix)
        mean, logvar = output[:, : self.latent_dim], output[:, self.latent_dim :]
        std = torch.exp(0.5 * logvar)
        epsilon = torch.randn(
            mean.shape, generator=self.generator
        )
        latent = mean + epsilon * std
        reconstruction = self.decoder(latent)
        recon_loss = torch.mean((reconstruction - matrix) ** 2)
        kl = -0.5 * torch.mean(1 + logvar - mean.pow(2) - logvar.exp())
        # Detach: the ELBO is a reported number, not a gradient target.
        return float((-(recon_loss + kl)).detach())

    def fit(
        self,
        X: Any,
        *,
        epochs: int = 200,
        learning_rate: float = 1e-2,
        batch_size: Optional[int] = None,
    ) -> List[float]:
        """Train by maximising the ELBO. Returns the per-epoch loss."""
        torch = self._torch
        if epochs < 1:
            raise ValueError(f"epochs must be positive, got {epochs}")
        if learning_rate <= 0:
            raise ValueError(f"learning_rate must be positive, got {learning_rate}")

        matrix = self._as_matrix(X)
        if matrix.shape[0] == 0:
            raise ValueError("training data is empty")
        size = int(matrix.shape[0]) if batch_size is None else int(batch_size)

        torch.manual_seed(self.seed if self.seed is not None else 0)
        optimizer = torch.optim.Adam(self._parameters(), lr=learning_rate)
        history: List[float] = []

        for _ in range(epochs):
            permutation = torch.randperm(matrix.shape[0], generator=self.generator)
            epoch_loss = 0.0
            batches = 0
            for start in range(0, matrix.shape[0], size):
                batch = matrix[permutation[start:start + size]]
                output = self.encoder(batch)
                mean, logvar = output[:, : self.latent_dim], output[:, self.latent_dim :]
                std = torch.exp(0.5 * logvar)
                epsilon = torch.randn(mean.shape, generator=self.generator)
                latent = mean + epsilon * std
                reconstruction = self.decoder(latent)
                recon_loss = torch.mean((reconstruction - batch) ** 2)
                kl = -0.5 * torch.mean(1 + logvar - mean.pow(2) - logvar.exp())
                loss = recon_loss + kl

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                epoch_loss += float(loss.item())
                batches += 1
            history.append(epoch_loss / max(batches, 1))

        self.training_history = history
        return history
