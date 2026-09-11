"""Validate a declared causal structure against data, then allow counterfactuals.

Why this module exists
----------------------
:class:`backend.modules.engine.tncm_vae.StructuralCausalModel` answers
counterfactual questions -- "what would systemic risk have been if the central bank
had not intervened?" -- by propagating a shock through a structural model the
caller *declares*. It says so in its own docstring: ``Nothing here validates that
the declared structure is the true one. The counterfactual is exactly as good as
the DAG and coefficients handed in.`` That is an honest admission and a real gap.
A counterfactual computed from a wrong DAG is not merely uncertain, it is
*confidently* wrong, and nothing inside the model can tell the difference.

:mod:`backend.modules.engine.causal_discovery` can learn a structure from data and
report exactly how it differs from a declared one. On its own it has no declared
model to argue with.

This module couples them. Before a counterfactual is reported, the declared
structure is compared against the structure the data actually support, and the
discrepancy is returned as an explicit model-risk verdict. By default a
counterfactual whose declared structure is materially contradicted is **refused**,
not reported with a footnote: a number that reaches a decision-maker tends to be
used regardless of the caveat attached to it. The refusal is not a claim that the
learned structure is correct -- see the limitations below -- only that the two
disagree and the disagreement has to be resolved by a human before the answer
means anything.

Design notes
------------
* The comparison is deliberately one-directional in its consequence. Agreement is
  *not* evidence that the declared DAG is true; it is evidence that the data do
  not contradict it at the chosen sparsity. The result records which it was so a
  reader cannot inflate "not contradicted" into "validated".
* A caller who has read the discrepancy can proceed anyway by setting
  ``accept_structure_risk``. That is recorded in the returned object, because an
  accepted risk and an unexamined one must not look alike downstream.

Limitations
-----------
* Everything :mod:`causal_discovery` documents applies to the learned structure:
  a **linear** structural equation model with equal-variance additive noise; no
  latent confounders (this is not FCI); orientation identified only up to the
  Markov equivalence class; and no principled selector for the sparsity penalty,
  so a disagreement may be the penalty's fault rather than the data's.
* A disagreement is therefore a *prompt to investigate*, not proof that the
  declared DAG is wrong. Nor is the reverse: this module cannot certify a DAG.
* Only contemporaneous structure is compared. ``tncm_vae`` also carries a
  ``self_lag`` term and this module does not estimate or check it.
* The comparison assumes the observations are contemporaneous and identically
  distributed in the sense the linear SEM requires. Regime shifts -- precisely
  what this platform studies -- violate that, and the failure will look like a
  structural disagreement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import numpy as np

from backend.modules.engine.causal_discovery import (
    DagComparison,
    NoteArsConfig,
    NoteArsResult,
    compare_dag,
    notears_linear,
    parents_to_adjacency,
)
from backend.modules.engine.tncm_vae import (
    CounterfactualError,
    CounterfactualResult,
    Intervention,
    StructuralCausalModel,
    TrajectoryConstraints,
)

__all__ = [
    "StructureValidation",
    "ValidatedCounterfactual",
    "validate_structure",
    "counterfactual_with_validation",
]


def _declared_parents(
    declared: Any,
) -> Tuple[Tuple[str, ...], Dict[str, Tuple[str, ...]]]:
    """Normalise a declared model or a parents mapping into ``(variables, parents)``."""
    if isinstance(declared, StructuralCausalModel):
        variables = tuple(declared.variables)
        return variables, {name: tuple(declared.parents[name]) for name in variables}
    if isinstance(declared, Mapping):
        parents = {str(child): tuple(str(parent) for parent in parents_)
                   for child, parents_ in declared.items()}
        if not parents:
            raise ValueError("declared structure is empty")
        # ``parents_to_adjacency`` needs the full universe, including any variable
        # that only ever appears as a parent.
        seen: list = []
        for child, parents_ in parents.items():
            if child not in seen:
                seen.append(child)
            for parent in parents_:
                if parent not in seen:
                    seen.append(parent)
        return tuple(seen), parents
    raise TypeError(
        "declared must be a StructuralCausalModel or a mapping of "
        f"child -> parents, got {type(declared).__name__}"
    )


def _observations_matrix(
    observations: Any, variables: Sequence[str]
) -> np.ndarray:
    """Coerce observations to a finite ``(T, len(variables))`` array in order.

    Column order matters: the structural model indexes its variables positionally,
    so a frame whose columns happen to be in another order would silently compute
    a counterfactual over permuted variables. The reindex below is what makes that
    impossible.
    """
    if hasattr(observations, "columns") and hasattr(observations, "to_numpy"):
        missing = [name for name in variables if name not in observations.columns]
        if missing:
            raise ValueError(
                f"observations is missing column(s) {missing} required by the "
                f"declared structure {list(variables)}"
            )
        matrix = observations.loc[:, list(variables)].to_numpy(dtype=float)
    else:
        matrix = np.asarray(observations, dtype=float)
        if matrix.ndim != 2:
            raise ValueError(
                f"observations must be 2-D, got {matrix.ndim} dimension(s)"
            )
        if matrix.shape[1] != len(variables):
            raise ValueError(
                f"observations has {matrix.shape[1]} column(s) but the declared "
                f"structure has {len(variables)} variables"
            )
    if matrix.shape[0] == 0:
        raise ValueError("observations is empty; at least one row is required")
    if not np.all(np.isfinite(matrix)):
        raise ValueError("observations contains non-finite values (NaN or inf)")
    return matrix


@dataclass(frozen=True)
class StructureValidation:
    """A declared structure, the structure the data support, and their disagreement.

    ``agreement_is_not_proof`` is a constant reminder carried in the object rather
    than only in the docstring: passing the comparison is not a validation.
    """

    variables: Tuple[str, ...]
    declared_parents: Dict[str, Tuple[str, ...]]
    learned_parents: Dict[str, Tuple[str, ...]]
    discovery: NoteArsResult
    comparison: DagComparison

    agreement_is_not_proof: bool = field(default=True, init=False)

    @property
    def model_risk_warning(self) -> bool:
        """Whether the data contradict the declared structure."""
        return bool(self.comparison.model_risk_warning)

    @property
    def under_specified(self) -> bool:
        """Declared DAG is missing edges the data support: an open confounding path."""
        return bool(self.comparison.under_specified)

    @property
    def over_specified(self) -> bool:
        """Declared DAG asserts edges the data do not support."""
        return bool(self.comparison.over_specified)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variables": list(self.variables),
            "declared_parents": {
                name: list(parents) for name, parents in self.declared_parents.items()
            },
            "learned_parents": {
                name: list(parents) for name, parents in self.learned_parents.items()
            },
            "model_risk_warning": self.model_risk_warning,
            "under_specified": self.under_specified,
            "over_specified": self.over_specified,
            "agreement_is_not_proof": True,
            "declared_only": [list(edge) for edge in self.comparison.declared_only],
            "learned_only": [list(edge) for edge in self.comparison.learned_only],
            "agreed": [list(edge) for edge in self.comparison.agreed],
            "orientation_conflicts": [
                {
                    "learned": [conflict.learned_source, conflict.learned_target],
                    "declared": [conflict.declared_source, conflict.declared_target],
                }
                for conflict in self.comparison.orientation_conflicts
            ],
            "summary": self.comparison.summary_text,
            "discovery": {
                "h_final": float(self.discovery.h_final),
                "acyclic": bool(self.discovery.acyclic),
                "converged": bool(self.discovery.converged),
                "l1_strength": float(self.discovery.l1_strength),
                "threshold": float(self.discovery.threshold),
                "standardised": bool(self.discovery.standardised),
            },
        }


@dataclass(frozen=True)
class ValidatedCounterfactual:
    """A counterfactual together with the structural check that preceded it."""

    validation: StructureValidation
    counterfactual: CounterfactualResult
    structure_risk_accepted: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "structure_risk_accepted": bool(self.structure_risk_accepted),
            "validation": self.validation.to_dict(),
            "counterfactual": self.counterfactual.to_dict(),
        }

    def summary(self) -> str:
        lines = [self.counterfactual.summary()]
        if self.structure_risk_accepted:
            lines.append(
                "\nSTRUCTURAL RISK ACCEPTED: the data contradict the declared causal "
                "structure (see below). The counterfactual above was produced anyway "
                "at the caller's explicit request and must be read as conditional on "
                "the declared structure being right."
            )
            lines.append(self.validation.comparison.summary_text)
        else:
            lines.append(
                "\nStructural check: the data do not contradict the declared causal "
                "structure at the chosen sparsity. This is NOT a validation of that "
                "structure -- see the discovery limitations."
            )
        return "\n".join(lines)


def validate_structure(
    observations: Any,
    declared: Any,
    *,
    variables: Optional[Sequence[str]] = None,
    config: Optional[NoteArsConfig] = None,
    **overrides: Any,
) -> StructureValidation:
    """Compare a declared causal structure with the one the data support.

    Args:
        observations: ``(T, n_variables)`` array, or a frame whose columns are the
            variable names. A frame is reindexed to the declared variable order.
        declared: A :class:`StructuralCausalModel` or a ``{child: (parents...)}``
            mapping. The mapping must name every variable in ``variables``.
        variables: Overrides the variable order. Defaults to the declared model's
            order, or the frame's columns.
        config: :class:`NoteArsConfig`. Defaults to the library default, which is
            ``standardize=False`` -- see the discovery module for why z-scoring
            breaks the equal-noise-variance assumption the loss relies on.
        **overrides: Passed to :func:`~causal_discovery.notears_linear`.

    Returns:
        The learned structure, the declared structure and their disagreement.

    Raises:
        ValueError: If the observations are malformed, non-finite, or do not cover
            every declared variable.
    """
    declared_variables, declared_parents = _declared_parents(declared)

    if variables is not None:
        universe = tuple(str(name) for name in variables)
    elif hasattr(observations, "columns"):
        universe = tuple(str(name) for name in observations.columns)
    else:
        universe = declared_variables

    unknown = [name for name in declared_variables if name not in universe]
    if unknown:
        raise ValueError(
            f"declared structure names variables absent from the observation "
            f"universe: {unknown}"
        )
    incomplete = sorted(set(universe) - set(declared_parents))
    if incomplete:
        raise ValueError(
            "the declared structure does not name every observed variable, so a "
            f"learned edge touching one could not be compared: {incomplete}. Give "
            "every variable a (possibly empty) parent tuple."
        )

    matrix = _observations_matrix(observations, universe)
    resolved = config if config is not None else NoteArsConfig()

    discovery = notears_linear(matrix, universe, resolved, **overrides)
    learned_parents = _parents_from_result(discovery, universe)
    declared_adjacency = parents_to_adjacency(declared_parents, universe)
    # `compare_dag` takes a structure -- an adjacency or a parents mapping -- and
    # not a discovery result, so the already-thresholded adjacency is handed over.
    # Passing the raw weights would compare the unthresholded pattern instead.
    comparison = compare_dag(
        discovery.adjacency, declared_adjacency, variables=universe
    )

    return StructureValidation(
        variables=universe,
        declared_parents={name: tuple(declared_parents[name]) for name in universe},
        learned_parents=learned_parents,
        discovery=discovery,
        comparison=comparison,
    )


def _parents_from_result(
    discovery: NoteArsResult, variables: Sequence[str]
) -> Dict[str, Tuple[str, ...]]:
    """Read the thresholded adjacency back into a ``child -> parents`` mapping."""
    adjacency = np.asarray(discovery.adjacency, dtype=float)
    parents: Dict[str, Tuple[str, ...]] = {}
    for target, name in enumerate(variables):
        sources = [
            variables[source]
            for source in range(len(variables))
            if source != target and adjacency[source, target] != 0.0
        ]
        parents[str(name)] = tuple(sources)
    return parents


def counterfactual_with_validation(
    observations: Any,
    declared: StructuralCausalModel,
    interventions: Sequence[Intervention],
    *,
    accept_structure_risk: bool = False,
    constraints: Optional[TrajectoryConstraints] = None,
    variables: Optional[Sequence[str]] = None,
    config: Optional[NoteArsConfig] = None,
    **overrides: Any,
) -> ValidatedCounterfactual:
    """Validate the declared structure, then answer the counterfactual.

    The declared structure is checked first. If the data contradict it, this
    **refuses** to report a counterfactual unless ``accept_structure_risk`` is set,
    because a counterfactual from a contradicted DAG is wrong in a way that reads
    exactly like being right. When the risk is accepted, that fact is carried in
    the result so it cannot be lost downstream.

    Args:
        observations: The factual trajectory, frame or ``(T, n_variables)`` array.
        declared: The structural model to intervene on.
        interventions: The do() operations to apply.
        accept_structure_risk: Proceed even when the data contradict the declared
            structure. Off by default.
        constraints: Optional trajectory constraints, passed through unchanged.
        variables: Overrides the declared variable order.
        config: :class:`NoteArsConfig` for the structure check.
        **overrides: Passed to :func:`~causal_discovery.notears_linear`.

    Returns:
        The counterfactual, the structural comparison that preceded it, and whether
        structural risk was explicitly accepted.

    Raises:
        ValueError: If the structural check cannot be run on these inputs.
        CounterfactualError: If the data contradict the declared structure and
            ``accept_structure_risk`` is False.
    """
    validation = validate_structure(
        observations,
        declared,
        variables=variables,
        config=config,
        **overrides,
    )

    if validation.model_risk_warning and not accept_structure_risk:
        comparison = validation.comparison
        raise CounterfactualError(
            "the observed data contradict the declared causal structure, so the "
            "counterfactual is refused rather than reported. "
            f"{comparison.summary_text} "
            "Recall that the learned structure is itself only evidence -- its own "
            "limitations (linearity, no latent confounders, Markov equivalence, and "
            "an unselected sparsity penalty) mean a disagreement may be the "
            "penalty's fault rather than the data's. Resolve the disagreement, or "
            "pass accept_structure_risk=True to report the counterfactual knowing "
            "it is conditional on a contradicted structure."
        )

    order = tuple(str(name) for name in declared.variables)
    matrix = _observations_matrix(observations, order)
    counterfactual = declared.counterfactual(matrix, interventions, constraints)

    return ValidatedCounterfactual(
        validation=validation,
        counterfactual=counterfactual,
        structure_risk_accepted=bool(validation.model_risk_warning),
    )


def structure_risk_json(validation: StructureValidation) -> str:
    """A JSON string for reports, with no ``NaN`` that would break a strict reader."""
    return json.dumps(validation.to_dict(), allow_nan=False, sort_keys=True)
