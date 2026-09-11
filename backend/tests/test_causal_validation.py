"""Tests for the declared-structure validation that guards counterfactuals.

The point of the module is a refusal, so the central tests are that it refuses
when it should, proceeds when it is told to, and does not quietly alter the
counterfactual it passes through. The "no warning" case is asserted against data
generated from the declared DAG, which is the only setting in which agreement is
even expected.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from backend.modules.engine.causal_discovery import NoteArsConfig
from backend.modules.engine.causal_validation import (
    ValidatedCounterfactual,
    counterfactual_with_validation,
    structure_risk_json,
    validate_structure,
)
from backend.modules.engine.tncm_vae import (
    CounterfactualError,
    Intervention,
    StructuralCausalModel,
)

VARIABLES = ("A", "B", "C", "D")
# C is a collider on A and B; D is downstream of C. Coefficients are 2.0 and the
# noise is unit-variance, which is the configuration the discovery module
# documents as recovering exactly.
TRUE_PARENTS = {"A": (), "B": (), "C": ("A", "B"), "D": ("C",)}
COEFFICIENTS = {"C": {"A": 2.0, "B": 2.0}, "D": {"C": 2.0}}

# standardize=False is the discovery default and is deliberate: z-scoring each
# column rescales its residual and breaks the equal-noise-variance assumption the
# least-squares loss relies on, which inverts recovered colliders.
CONFIG = NoteArsConfig(l1_strength=0.1, threshold=0.3, standardize=False)


def sample_declared(rng: np.random.Generator, n: int) -> pd.DataFrame:
    """Draw a factual sample from a linear SEM with the declared structure."""
    noise = rng.normal(0.0, 1.0, size=(n, len(VARIABLES)))
    a, b = noise[:, 0], noise[:, 1]
    c = 2.0 * a + 2.0 * b + noise[:, 2]
    d = 2.0 * c + noise[:, 3]
    return pd.DataFrame({"A": a, "B": b, "C": c, "D": d})


@pytest.fixture(scope="module")
def declared_sample() -> pd.DataFrame:
    return sample_declared(np.random.default_rng(11), 4000)


def declared_model() -> StructuralCausalModel:
    return StructuralCausalModel(variables=list(VARIABLES), coefficients=COEFFICIENTS)


class TestAgreement:
    def test_data_from_the_declared_dag_do_not_contradict_it(self, declared_sample):
        validation = validate_structure(declared_sample, TRUE_PARENTS, config=CONFIG)
        assert validation.model_risk_warning is False
        assert validation.under_specified is False
        assert validation.over_specified is False
        assert set(validation.learned_parents) == set(VARIABLES)

    def test_agreement_is_explicitly_not_reported_as_proof(self, declared_sample):
        validation = validate_structure(declared_sample, TRUE_PARENTS, config=CONFIG)
        assert validation.agreement_is_not_proof is True
        assert validation.to_dict()["agreement_is_not_proof"] is True

    def test_it_accepts_a_structural_causal_model_as_the_declaration(
        self, declared_sample
    ):
        validation = validate_structure(declared_sample, declared_model(), config=CONFIG)
        assert validation.declared_parents == {
            "A": (), "B": (), "C": ("A", "B"), "D": ("C",)
        }


class TestDisagreement:
    def test_a_missing_declared_edge_is_flagged_as_under_specification(
        self, declared_sample
    ):
        """The declaration omits C -> D, which the data support."""
        incomplete = {"A": (), "B": (), "C": ("A", "B"), "D": ()}
        validation = validate_structure(declared_sample, incomplete, config=CONFIG)
        assert validation.model_risk_warning is True
        assert validation.under_specified is True
        assert ("C", "D") in validation.comparison.learned_only

    def test_an_invented_edge_is_flagged_as_over_specification(self, declared_sample):
        """The declaration asserts B -> D, which the data do not support."""
        extra = {"A": (), "B": (), "C": ("A", "B"), "D": ("C", "B")}
        validation = validate_structure(declared_sample, extra, config=CONFIG)
        assert validation.model_risk_warning is True
        assert validation.over_specified is True
        assert ("B", "D") in validation.comparison.declared_only


class TestRefusal:
    def test_a_model_missing_a_parent_is_refused(self, declared_sample):
        """A model whose coefficients omit C -> D is contradicted by the data."""
        incomplete_model = StructuralCausalModel(
            variables=list(VARIABLES),
            coefficients={"C": {"A": 2.0, "B": 2.0}},
        )
        with pytest.raises(CounterfactualError, match="refused"):
            counterfactual_with_validation(
                declared_sample,
                incomplete_model,
                [Intervention("A", 0.0)],
                config=CONFIG,
            )

    def test_accepting_the_risk_proceeds_and_records_it(self, declared_sample):
        incomplete_model = StructuralCausalModel(
            variables=list(VARIABLES),
            coefficients={"C": {"A": 2.0, "B": 2.0}},
        )
        result = counterfactual_with_validation(
            declared_sample,
            incomplete_model,
            [Intervention("A", 0.0)],
            config=CONFIG,
            accept_structure_risk=True,
        )
        assert isinstance(result, ValidatedCounterfactual)
        assert result.structure_risk_accepted is True
        assert result.validation.model_risk_warning is True
        assert "STRUCTURAL RISK ACCEPTED" in result.summary()

    def test_a_supported_structure_reports_the_counterfactual_directly(
        self, declared_sample
    ):
        result = counterfactual_with_validation(
            declared_sample,
            declared_model(),
            [Intervention("A", 0.0)],
            config=CONFIG,
        )
        assert result.structure_risk_accepted is False
        assert "NOT a validation" in result.summary()


class TestPassThroughFidelity:
    def test_the_counterfactual_is_not_altered_by_the_validation(self, declared_sample):
        model = declared_model()
        matrix = declared_sample.loc[:, list(VARIABLES)].to_numpy(dtype=float)
        interventions = [Intervention("A", 0.0)]

        direct = model.counterfactual(matrix, interventions)
        validated = counterfactual_with_validation(
            declared_sample, model, interventions, config=CONFIG
        )
        assert np.array_equal(
            validated.counterfactual.counterfactual, direct.counterfactual
        )
        assert np.array_equal(validated.counterfactual.factual, direct.factual)

    def test_a_frame_is_reindexed_into_the_declared_variable_order(
        self, declared_sample
    ):
        """Column order must not change the answer: positional indices are used."""
        model = declared_model()
        shuffled = declared_sample.loc[:, ["D", "C", "B", "A"]]
        ordered = counterfactual_with_validation(
            declared_sample, model, [Intervention("A", 0.0)], config=CONFIG
        )
        reordered = counterfactual_with_validation(
            shuffled, model, [Intervention("A", 0.0)], config=CONFIG
        )
        assert np.array_equal(
            ordered.counterfactual.counterfactual,
            reordered.counterfactual.counterfactual,
        )


class TestDeterminismAndSerialisation:
    def test_repeated_validation_learns_the_same_structure(self, declared_sample):
        first = validate_structure(declared_sample, TRUE_PARENTS, config=CONFIG)
        second = validate_structure(declared_sample, TRUE_PARENTS, config=CONFIG)
        assert np.array_equal(first.discovery.adjacency, second.discovery.adjacency)

    def test_the_report_is_strict_json(self, declared_sample):
        incomplete = {"A": (), "B": (), "C": ("A", "B"), "D": ()}
        validation = validate_structure(declared_sample, incomplete, config=CONFIG)
        payload = json.loads(structure_risk_json(validation))
        assert payload["model_risk_warning"] is True
        assert payload["under_specified"] is True
        assert ["C", "D"] in payload["learned_only"]


class TestFailClosed:
    def test_a_missing_observation_column_raises(self, declared_sample):
        # Dropping a column removes it from the observed universe, so the first
        # thing that fails is the check that the declaration only names observed
        # variables -- which is the more informative error of the two.
        frame = declared_sample.drop(columns=["D"])
        with pytest.raises(ValueError, match="absent from the observation universe"):
            validate_structure(frame, TRUE_PARENTS, config=CONFIG)

    def test_an_unnamed_observed_variable_raises(self, declared_sample):
        frame = declared_sample.assign(E=lambda df: df["A"] * 2.0)
        with pytest.raises(ValueError, match="does not name every observed variable"):
            validate_structure(frame, TRUE_PARENTS, config=CONFIG)

    def test_non_finite_observations_raise(self, declared_sample):
        frame = declared_sample.copy()
        frame.loc[0, "A"] = np.nan
        with pytest.raises(ValueError, match="non-finite"):
            validate_structure(frame, TRUE_PARENTS, config=CONFIG)

    def test_an_empty_frame_raises(self, declared_sample):
        with pytest.raises(ValueError, match="empty"):
            validate_structure(declared_sample.iloc[:0], TRUE_PARENTS, config=CONFIG)

    def test_a_bare_array_with_the_wrong_width_raises(self, declared_sample):
        with pytest.raises(ValueError, match="column"):
            validate_structure(
                declared_sample.to_numpy(dtype=float)[:, :3],
                TRUE_PARENTS,
                variables=VARIABLES,
                config=CONFIG,
            )

    def test_a_non_model_non_mapping_declaration_raises(self, declared_sample):
        with pytest.raises(TypeError, match="StructuralCausalModel or a mapping"):
            validate_structure(declared_sample, 42, config=CONFIG)
