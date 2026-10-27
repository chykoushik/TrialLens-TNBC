import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.criteria import (
    AssessmentState,
    CriterionAssessment,
    TrialCriteriaSet,
    TrialCriterion,
)


@pytest.fixture
def synthetic_payload():
    path = Path(__file__).parent / "fixtures" / "synthetic_criteria.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_optional_fields_remain_null():
    criterion = TrialCriterion(criterion_id="test", original_text="Synthetic text")
    fields = criterion.model_dump()
    assert all(value is None for key, value in fields.items()
               if key not in {"criterion_id", "original_text"})
    assert TrialCriterion.model_validate_json(criterion.model_dump_json()) == criterion


def test_nested_logic_and_polarity(synthetic_payload):
    criteria_set = TrialCriteriaSet.model_validate(synthetic_payload)
    inclusion, exclusion = criteria_set.criteria
    assert criteria_set.is_synthetic is True
    assert criteria_set.nct_id is None
    assert "SYNTHETIC TEST ONLY" in criteria_set.original_text
    assert inclusion.criterion_type == "inclusion"
    assert exclusion.criterion_type == "exclusion"
    assert exclusion.original_text == "condition D present"
    assert inclusion.logical_operator == "AND"
    marker, choice = inclusion.dependencies
    assert marker.original_text == "marker A present"
    assert choice.logical_operator == "OR"
    assert [node.original_text for node in choice.dependencies] == [
        "assay B positive", "assay C positive",
    ]
    assert inclusion.original_text == synthetic_payload["criteria"][0]["original_text"]
    assert TrialCriteriaSet.model_validate_json(criteria_set.model_dump_json()) == criteria_set


@pytest.mark.parametrize("updates", [
    {"criterion_id": ""},
    {"criterion_id": "  "},
    {"original_text": ""},
    {"criterion_type": "other"},
    {"logical_operator": "NOT"},
    {"logical_operator": "AND"},
    {"logical_operator": "OR", "dependencies": []},
    {"extraction_timestamp": "2026-10-23T12:00:00"},
    {"threshold": 10},
    {"invented_field": "value"},
])
def test_invalid_criterion(updates):
    payload = {"criterion_id": "synthetic", "original_text": "Synthetic text"}
    payload.update(updates)
    with pytest.raises(ValidationError):
        TrialCriterion.model_validate(payload)


@pytest.mark.parametrize("operator", [None, "NONE", "AND", "OR"])
def test_dependency_operator_arity(operator):
    with pytest.raises(ValidationError):
        TrialCriterion(
            criterion_id="parent", original_text="Synthetic compound",
            logical_operator=operator,
            dependencies=[TrialCriterion(criterion_id="child", original_text="Synthetic operand")],
        )


def test_contradictory_polarity_rejected(synthetic_payload):
    synthetic_payload["criteria"][0]["dependencies"][1]["criterion_type"] = "exclusion"
    with pytest.raises(ValidationError, match="polarity"):
        TrialCriteriaSet.model_validate(synthetic_payload)


def test_polarity_preserved_across_unknown_node(synthetic_payload):
    choice = synthetic_payload["criteria"][0]["dependencies"][1]
    choice["criterion_type"] = None
    choice["dependencies"][0]["criterion_type"] = "exclusion"
    with pytest.raises(ValidationError, match="polarity"):
        TrialCriteriaSet.model_validate(synthetic_payload)


def test_duplicate_nested_ids_rejected(synthetic_payload):
    synthetic_payload["criteria"][1]["criterion_id"] = "synthetic-assay-c"
    with pytest.raises(ValidationError, match="unique"):
        TrialCriteriaSet.model_validate(synthetic_payload)


def test_grouped_trial_mismatch_rejected(synthetic_payload):
    synthetic_payload["nct_id"] = "synthetic-trial-a"
    synthetic_payload["criteria"][0]["dependencies"][0]["nct_id"] = "synthetic-trial-b"
    with pytest.raises(ValidationError, match="grouped trial"):
        TrialCriteriaSet.model_validate(synthetic_payload)


def test_parent_trial_mismatch_rejected(synthetic_payload):
    parent = synthetic_payload["criteria"][0]
    parent["nct_id"] = "synthetic-trial-a"
    parent["dependencies"][0]["nct_id"] = "synthetic-trial-b"
    with pytest.raises(ValidationError, match="same trial"):
        TrialCriterion.model_validate(parent)


def test_provenance_preserved(synthetic_payload):
    synthetic_payload.update(
        source_url="https://example.invalid/synthetic",
        source_snapshot="data/synthetic/example.json",
        retrieval_timestamp="2026-10-23T12:00:00Z",
    )
    synthetic_payload["criteria"][0].update(
        cohort="synthetic cohort",
        comparator=">=",
        threshold="10",
        unit="synthetic units",
        temporal_constraint="within 7 days (synthetic)",
        extraction_timestamp="2026-10-23T12:30:00+00:00",
    )
    criteria_set = TrialCriteriaSet.model_validate(synthetic_payload)
    exported = criteria_set.model_dump(mode="json")
    assert exported == TrialCriteriaSet.model_validate(exported).model_dump(mode="json")
    assert exported["source_url"] == synthetic_payload["source_url"]
    assert exported["source_snapshot"] == synthetic_payload["source_snapshot"]
    for key, value in synthetic_payload["criteria"][0].items():
        if key not in {"dependencies", "extraction_timestamp"}:
            assert exported["criteria"][0][key] == value


@pytest.mark.parametrize("state", ["satisfied", "violated", "unknown", "temporal", "conflict"])
def test_assessment_states(state):
    assessment = CriterionAssessment(
        criterion_id="synthetic-inclusion", state=state,
        evidence_ids=["synthetic-evidence"], explanation="Synthetic label only",
        assessment_timestamp="2026-10-23T12:00:00Z",
    )
    assert assessment.state is AssessmentState(state)
    assert assessment.model_dump(mode="json")["state"] == state
    assert CriterionAssessment.model_validate_json(assessment.model_dump_json()) == assessment


def test_assessment_unknown_metadata():
    assessment = CriterionAssessment(criterion_id="synthetic", state="unknown")
    assert assessment.evidence_ids is None
    assert assessment.explanation is None
    assert assessment.assessment_timestamp is None


@pytest.mark.parametrize("updates", [
    {"state": "eligible"},
    {"state": None},
    {"criterion_id": ""},
    {"evidence_ids": [""]},
    {"assessment_timestamp": "invalid"},
    {"assessment_timestamp": "2026-10-23T12:00:00"},
])
def test_invalid_assessment(updates):
    payload = {"criterion_id": "synthetic", "state": "unknown"}
    payload.update(updates)
    with pytest.raises(ValidationError):
        CriterionAssessment.model_validate(payload)
