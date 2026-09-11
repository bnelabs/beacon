"""Counterfactual analysis on the engine path.

``backend/modules/engine/tncm_vae.py`` is a complete counterfactual implementation
(declared structural model, abduction, intervention, propagation, optional
trajectory constraints) with a thorough test suite. It had no production importer:
the only module that touched it was ``causal_validation.py``, which is itself
unreachable. The consequence was that the engine could not answer a
"what would have happened if" question at all, while the documentation described
counterfactual analysis as a capability.

This module is the production face of that implementation, for the same reason
:mod:`~backend.modules.engine.latent_dynamics` is the production face of the SDE:
the capability is exposed as an explicit, caller-declared scenario attached to the
multi-institution analysis, so the engine runs it rather than merely importing it.

What is asserted and what is not
--------------------------------
A counterfactual here is **conditional on a caller-declared structural model**. It
is an answer to "given this model, what follows from this intervention", not
"what would happen in the world". Two consequences are stated rather than implied:

* If the model was learned rather than declared, the graph is not ground truth.
  :mod:`~backend.modules.engine.causal_discovery` says the same thing in its own
  terms: neither NOTEARS nor the constraint-based skeleton is a licence to treat a
  learned graph as identified, and the correct response to a disagreement between
  them is to inspect it, not to average it away.
* The propagation is the model's, so a misspecified coefficient produces a
  confident, precise, wrong answer. Nothing in this module bounds that error.

Everything fails closed: a scenario whose observation matrix does not match the
model's variables, whose interventions name an unknown variable, or which carries
no intervention at all, raises before any computation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from backend.exceptions import BeaconError
from backend.modules.engine.causal_discovery import NoteArsResult
from backend.modules.engine.tncm_vae import (
    CounterfactualResult,
    Intervention,
    StructuralCausalModel,
    TrajectoryConstraints,
)

__all__ = [
    "CounterfactualScenario",
    "CounterfactualOutcome",
    "CounterfactualScenarioError",
    "run_counterfactual",
    "structural_model_from_weights",
    "CONDITIONALITY_NOTE",
]

#: Carried on every outcome so a reader cannot mistake the result for a forecast.
CONDITIONALITY_NOTE = (
    "Counterfactual conditional on the caller-declared structural model: an answer "
    "to 'what follows from this intervention given this model', not a prediction of "
    "the world. A misspecified coefficient yields a precise wrong answer, and "
    "nothing here bounds that error."
)


class CounterfactualScenarioError(BeaconError):
    """Raised when a counterfactual scenario cannot be honoured as declared."""

    code = "COUNTERFACTUAL_SCENARIO_INVALID"


@dataclass(frozen=True)
class CounterfactualScenario:
    """A declared structural model, a factual trajectory, and a ``do`` operation.

    Attributes:
        model: The structural model to intervene on.
        observations: The factual trajectory, ``(n_steps, n_variables)``, with
            columns in ``model.variables`` order.
        interventions: The ``do`` operations. At least one is required: without an
            intervention the answer is the observation, and the procedure would be
            testing nothing while looking like it tested something.
        constraints: Optional feasibility checks applied to the counterfactual.
            When supplied, a violation is reported on the outcome rather than
            silently discarded.
    """

    model: StructuralCausalModel
    observations: np.ndarray
    interventions: Tuple[Intervention, ...]
    constraints: Optional[TrajectoryConstraints] = None

    def __post_init__(self) -> None:
        if not isinstance(self.model, StructuralCausalModel):
            raise CounterfactualScenarioError(
                "model must be a StructuralCausalModel, got "
                f"{type(self.model).__name__}"
            )

        trajectory = np.asarray(self.observations, dtype=float)
        if trajectory.ndim != 2:
            raise CounterfactualScenarioError(
                "observations must be a (n_steps, n_variables) trajectory, got "
                f"{trajectory.ndim} dimension(s)"
            )
        expected = len(self.model.variables)
        if trajectory.shape[1] != expected:
            raise CounterfactualScenarioError(
                f"observations have {trajectory.shape[1]} column(s) but the model "
                f"declares {expected} variable(s): {list(self.model.variables)}"
            )
        if trajectory.shape[0] < 1:
            raise CounterfactualScenarioError(
                "observations must contain at least one timestep"
            )
        if not np.all(np.isfinite(trajectory)):
            raise CounterfactualScenarioError(
                "observations contain non-finite values; a counterfactual cannot be "
                "formed from a trajectory with holes in it"
            )
        object.__setattr__(self, "observations", trajectory)

        interventions = tuple(self.interventions)
        if not interventions:
            raise CounterfactualScenarioError(
                "a counterfactual needs at least one intervention; without one the "
                "answer is the observation and nothing is tested"
            )
        for item in interventions:
            if not isinstance(item, Intervention):
                raise CounterfactualScenarioError(
                    "interventions must be Intervention instances, got "
                    f"{type(item).__name__}"
                )
            if item.variable not in self.model.index:
                raise CounterfactualScenarioError(
                    f"intervention names unknown variable {item.variable!r}; the "
                    f"model declares {list(self.model.variables)}"
                )
        object.__setattr__(self, "interventions", interventions)

        if self.constraints is not None and not isinstance(
            self.constraints, TrajectoryConstraints
        ):
            raise CounterfactualScenarioError(
                "constraints must be a TrajectoryConstraints, got "
                f"{type(self.constraints).__name__}"
            )


@dataclass(frozen=True)
class CounterfactualOutcome:
    """The counterfactual and the evidence that it was conditioned on a model."""

    result: CounterfactualResult
    reference: str
    conditionality_note: str = CONDITIONALITY_NOTE

    @property
    def moved(self) -> Tuple[str, ...]:
        """Variables the intervention actually moved."""
        return self.result.affected

    def to_dict(self) -> Dict[str, Any]:
        payload = self.result.to_dict()
        payload["reference"] = self.reference
        payload["conditionality_note"] = self.conditionality_note
        payload["is_forecast"] = False
        return payload


def run_counterfactual(scenario: CounterfactualScenario) -> CounterfactualOutcome:
    """Answer the scenario's ``do`` query under the scenario's declared model.

    Args:
        scenario: A validated :class:`CounterfactualScenario`.

    Returns:
        The counterfactual trajectory, which variables moved, and whether any
        declared trajectory constraint was violated.

    Raises:
        CounterfactualScenarioError: If ``scenario`` is not a
            :class:`CounterfactualScenario`, so a caller cannot pass a bare model
            and receive a result that ignored their intended intervention.
    """
    if not isinstance(scenario, CounterfactualScenario):
        raise CounterfactualScenarioError(
            "scenario must be a CounterfactualScenario, got "
            f"{type(scenario).__name__}"
        )

    result = scenario.model.counterfactual(
        scenario.observations, scenario.interventions, scenario.constraints
    )
    reference = (
        f"declared structural model over {len(scenario.model.variables)} variable(s); "
        f"{len(scenario.interventions)} intervention(s); "
        f"{len(result.factual)} step(s)"
    )
    return CounterfactualOutcome(result=result, reference=reference)


def structural_model_from_weights(
    result: NoteArsResult,
    *,
    self_lag: Optional[Mapping[str, float]] = None,
    intercepts: Optional[Mapping[str, float]] = None,
    initial_state: Optional[Mapping[str, float]] = None,
) -> StructuralCausalModel:
    """Build a :class:`StructuralCausalModel` from a **linear** NOTEARS fit.

    This is the seam :class:`~backend.modules.engine.causal_discovery.NoteArsResult`
    refers to when it describes itself as the integration point with ``tncm_vae``.
    Learning a graph and then asking a counterfactual question of it is a legitimate
    workflow, but it is a choice with a consequence the caller must own: the
    counterfactual is then conditional on a graph that was *estimated*, not
    declared. That is why this is a function the caller calls explicitly rather than
    something the engine does on its own.

    Args:
        result: A fit from :func:`~backend.modules.engine.causal_discovery.notears_linear`.
            A non-linear (``solver="basis"``) result is rejected: its ``weights`` are
            block norms measuring whether a dependence exists, not coefficients
            measuring how large it is, so building a linear structural model from
            them would invent coefficients.
        self_lag: Optional own-lag coefficients, ``{variable: coefficient}``.
        intercepts: Optional constants, ``{variable: constant}``.
        initial_state: Optional values at ``t = -1`` for the lag term.

    Raises:
        CounterfactualScenarioError: If the result came from the non-linear solver,
            or the fit is not acyclic and so cannot be a structural model.
    """
    if not isinstance(result, NoteArsResult):
        raise CounterfactualScenarioError(
            f"result must be a NoteArsResult, got {type(result).__name__}"
        )
    solver = str(getattr(result, "solver", "linear"))
    if solver != "linear":
        raise CounterfactualScenarioError(
            "structural_model_from_weights needs a linear NOTEARS fit, but this "
            f"result came from the {solver!r} solver. That solver's weights are "
            "group norms -- they say whether a dependence exists, not how large it "
            "is -- so reading them as structural coefficients would fabricate the "
            "coefficients of the model."
        )
    if not result.acyclic:
        raise CounterfactualScenarioError(
            "the fit's thresholded graph is not acyclic, so it is not a structural "
            "model and cannot be propagated"
        )

    variables = list(result.variables)
    coefficients: Dict[str, Dict[str, float]] = {name: {} for name in variables}
    for child_position, child in enumerate(variables):
        for parent_position, parent in enumerate(variables):
            if result.adjacency[parent_position, child_position] != 0.0:
                coefficients[child][parent] = float(
                    result.weights[parent_position, child_position]
                )

    return StructuralCausalModel(
        variables,
        coefficients=coefficients,
        self_lag=self_lag,
        intercepts=intercepts,
        initial_state=initial_state,
    )
