from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from itertools import product

import pytest
from pydantic import ValidationError

from backend.app.assessment import assess_criteria
from backend.app.assessment_models import (
    AssessmentContext, CriterionBinding, EvidenceProvenance, PatientEvidence,
    SyntheticPatient, TemporalRule, TrialAssessment,
)
from backend.app.criteria import AssessmentState, CriterionAssessment, TrialCriteriaSet, TrialCriterion

AS_OF = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


def criterion(attribute="ER", **updates):
    values = dict(
        criterion_id=attribute, original_text=f"Synthetic {attribute} comparison only",
        nct_id="NCT00000001", criterion_type="inclusion", logical_operator="NONE",
        biomarker=attribute, comparator="<", threshold="1", unit="%",
        source_url="https://example.invalid/synthetic-trial",
        extraction_method="manual synthetic fixture",
    )
    values.update(updates)
    return TrialCriterion(**values)


def observation(attribute="ER", value="0", **updates):
    values = dict(
        evidence_id=f"synthetic-{attribute}", clinical_attribute=attribute, value=value,
        units="%", assay=None, observation_date=AS_OF,
        source="synthetic fixture", provenance=EvidenceProvenance(
            record_id=f"synthetic-record-{attribute}", reference="synthetic://test-only",
        ),
    )
    values.update(updates)
    return PatientEvidence(**values)


def binding(node, **updates):
    values = dict(
        criterion=node, verified=True, provenance="manual synthetic mapping",
        clinical_attribute=node.biomarker, value_type="numeric",
    )
    values.update(updates)
    return CriterionBinding(**values)


def run(node, evidence, plan=None, context=None):
    criteria_set = TrialCriteriaSet(
        criteria=[node], nct_id="NCT00000001", is_synthetic=True,
        original_text=node.original_text, source_snapshot="data/synthetic/test.json",
    )
    patient = SyntheticPatient(patient_id="synthetic-patient", is_synthetic=True, evidence=evidence)
    result = assess_criteria(
        criteria_set, patient, [plan or binding(node)], context or AssessmentContext(as_of=AS_OF),
    )
    return result.assessments[0]


@pytest.mark.parametrize("attribute,value,expected", [
    ("ER", "0.5", "satisfied"), ("ER", "1", "violated"),
    ("PR", "0", "satisfied"), ("PR", None, "unknown"),
])
def test_synthetic_receptor_thresholds(attribute, value, expected):
    node = criterion(attribute)
    result = run(node, [observation(attribute, value)])
    assert result.state.value == expected
    assert isinstance(result, CriterionAssessment)


@pytest.mark.parametrize("observed,expected", [("negative", "satisfied"), ("positive", "violated"), ("equivocal", "unknown")])
def test_her2_explicit_categories(observed, expected):
    node = criterion("HER2", comparator="==", threshold="negative", unit=None, assay="synthetic-HER2-assay")
    plan = binding(node, value_type="categorical", categories=["positive", "negative"])
    evidence = observation("HER2", observed, units=None, assay=node.assay)
    assert run(node, [evidence], plan).state.value == expected


def test_her2_ihc_number_is_not_inferred_negative():
    node = criterion("HER2", comparator="==", threshold="negative", unit=None)
    plan = binding(node, value_type="categorical", categories=["positive", "negative"])
    assert run(node, [observation("HER2", "0", units=None)], plan).state == AssessmentState.UNKNOWN


@pytest.mark.parametrize("evidence,expected", [
    ([], "unknown"),
    ([observation("BRCA", None, units=None)], "unknown"),
    ([observation("BRCA", "negative", units=None)], "violated"),
    ([observation("BRCA", "positive", units=None)], "satisfied"),
])
def test_brca_missing_is_not_negative(evidence, expected):
    node = criterion("BRCA", comparator="==", threshold="positive", unit=None)
    plan = binding(node, value_type="categorical", categories=["positive", "negative"])
    assert run(node, evidence, plan).state.value == expected


def test_pd_l1_assays_and_scores_stay_distinct():
    node = criterion("PD-L1", comparator=">=", threshold="10", unit="CPS", assay="synthetic-22C3")
    other = observation("PD-L1", "80", units="TPS", assay="synthetic-SP142")
    assert run(node, [other]).state == AssessmentState.UNKNOWN
    correct = observation("PD-L1", "12", units="CPS", assay=node.assay, evidence_id="synthetic-cps")
    result = run(node, [other, correct])
    assert result.state == AssessmentState.SATISFIED
    assert set(result.evidence_ids) == {other.evidence_id, correct.evidence_id}
    wrong_score = observation("PD-L1", "80", units="TPS", assay=node.assay)
    assert run(node, [wrong_score]).state == AssessmentState.UNKNOWN
    no_assay = node.model_copy(update={"assay": None})
    assert run(no_assay, [correct]).state == AssessmentState.UNKNOWN


def test_ecog_conflict_even_when_both_pass_threshold():
    node = criterion("ECOG", comparator="<=", threshold="2", unit="ECOG")
    first = observation("ECOG", "0", units="ECOG", evidence_id="first")
    second = observation("ECOG", "1", units="ECOG", evidence_id="second", observation_date=AS_OF - timedelta(days=1))
    result = run(node, [first, second])
    assert result.state == AssessmentState.CONFLICT
    assert result.evidence_ids == ["first", "second"]
    assert run(node, [second, first]) == result


@pytest.mark.parametrize("comparator,value,expected", [
    ("<", "10", "violated"), ("<=", "10", "satisfied"),
    (">", "10", "violated"), (">=", "10", "satisfied"),
    ("==", "10", "satisfied"), ("!=", "10", "violated"),
    ("==", "10.0001", "violated"), (">", "10.0001", "satisfied"),
])
def test_numeric_boundaries(comparator, value, expected):
    node = criterion("synthetic-number", comparator=comparator, threshold="10", unit="1")
    assert run(node, [observation(node.biomarker, value, units="1")]).state.value == expected


@pytest.mark.parametrize("criterion_unit,evidence_unit,value,expected", [
    ("%", "fraction", "0.005", "satisfied"),
    ("mg/dL", "g/L", "0.005", "satisfied"),
    ("g/L", "mg/dL", "50", "satisfied"),
    ("g/L", "mg/dL", "100", "violated"),
    ("%", None, "0", "unknown"),
    ("%", "mg/dL", "0", "unknown"),
    ("%", "percent", "0", "unknown"),
    (None, None, "0", "unknown"),
    ("unknown-unit", "unknown-unit", "0", "unknown"),
])
def test_compatible_units_only(criterion_unit, evidence_unit, value, expected):
    node = criterion(unit=criterion_unit)
    assert run(node, [observation(value=value, units=evidence_unit)]).state.value == expected


def test_equivalent_units_do_not_create_conflict():
    node = criterion()
    evidence = [observation(value="0.5", evidence_id="percent"),
                observation(value="0.005", units="fraction", evidence_id="fraction")]
    assert run(node, evidence).state == AssessmentState.SATISFIED


def test_exclusion_state_is_not_inverted():
    inclusion = criterion()
    exclusion = inclusion.model_copy(update={"criterion_type": "exclusion"})
    result = run(exclusion, [observation()])
    assert result.state == run(inclusion, [observation()]).state == AssessmentState.SATISFIED
    assert result.criterion.criterion_type == "exclusion"
    assert "eligible" not in result.model_dump()


def test_no_arbitrary_freshness_window():
    node = criterion()
    old = observation(observation_date=AS_OF - timedelta(days=3000))
    assert run(node, [old]).state == AssessmentState.SATISFIED
    undated = observation(observation_date=None)
    assert run(node, [undated]).state == AssessmentState.SATISFIED


@pytest.mark.parametrize("age,expected", [(6, "satisfied"), (7, "satisfied"), (8, "temporal")])
def test_explicit_freshness_window(age, expected):
    node = criterion(temporal_constraint="within 7 days")
    plan = binding(node, temporal_rule=TemporalRule(source_text=node.temporal_constraint, kind="freshness", max_age_days=7))
    assert run(node, [observation(observation_date=AS_OF - timedelta(days=age))], plan).state.value == expected


def test_missing_and_unresolved_dates():
    node = criterion(temporal_constraint="within 7 days")
    plan = binding(node, temporal_rule=TemporalRule(source_text=node.temporal_constraint, kind="freshness", max_age_days=7))
    assert run(node, [observation(observation_date=None)], plan).state == AssessmentState.TEMPORAL
    assert run(node, [observation()]).state == AssessmentState.TEMPORAL
    assert run(node, [], plan).state == AssessmentState.UNKNOWN
    assert run(node, [observation(value=None)], plan).state == AssessmentState.UNKNOWN
    assert run(criterion(), [observation(observation_date=AS_OF + timedelta(days=1))]).state == AssessmentState.TEMPORAL


@pytest.mark.parametrize("age,expected", [(13, "temporal"), (14, "satisfied"), (15, "satisfied"), (-1, "temporal")])
def test_washout_elapsed_from_explicit_completed_event(age, expected):
    node = criterion("last-therapy", comparator=">=", threshold="14", unit="days", temporal_constraint="at least 14 days after therapy")
    plan = binding(node, value_type="elapsed_days", temporal_rule=TemporalRule(source_text=node.temporal_constraint, kind="elapsed"))
    evidence = observation(node.biomarker, "completed", units=None, observation_date=AS_OF - timedelta(days=age))
    assert run(node, [evidence], plan).state.value == expected


def test_washout_needs_date_and_no_event_selection():
    node = criterion("last-therapy", comparator=">=", threshold="14", unit="days", temporal_constraint="at least 14 days after therapy")
    plan = binding(node, value_type="elapsed_days", temporal_rule=TemporalRule(source_text=node.temporal_constraint, kind="elapsed"))
    missing_date = observation(node.biomarker, "completed", units=None, observation_date=None)
    assert run(node, [missing_date], plan).state == AssessmentState.TEMPORAL
    scheduled = observation(node.biomarker, "scheduled", units=None)
    assert run(node, [scheduled], plan).state == AssessmentState.UNKNOWN
    events = [observation(node.biomarker, "completed", units=None, evidence_id=str(age), observation_date=AS_OF - timedelta(days=age)) for age in (13, 20)]
    assert run(node, events, plan).state == AssessmentState.CONFLICT


def state_branch(name, state):
    node = criterion(name)
    if state == "unknown":
        return node, []
    if state == "temporal":
        return node, [observation(name, observation_date=AS_OF + timedelta(days=1))]
    if state == "conflict":
        return node, [observation(name, "0", evidence_id=name + "-a"), observation(name, "2", evidence_id=name + "-b")]
    return node, [observation(name, "0" if state == "satisfied" else "2")]


def group(identifier, operator, children):
    return TrialCriterion(
        criterion_id=identifier, original_text="Synthetic nested Boolean expression",
        criterion_type="inclusion", logical_operator=operator, dependencies=children,
    )


STATES = [state.value for state in AssessmentState]


@pytest.mark.parametrize("operator,left_state,right_state", list(product(["AND", "OR"], STATES, STATES)))
def test_conservative_boolean_truth_tables(operator, left_state, right_state):
    left, left_evidence = state_branch("left", left_state)
    right, right_evidence = state_branch("right", right_state)
    parent = group("parent", operator, [left, right])
    plans = [binding(left), binding(right), binding(parent, clinical_attribute=None, value_type=None)]
    result = assess_criteria(
        TrialCriteriaSet(criteria=[parent], is_synthetic=True),
        SyntheticPatient(patient_id="synthetic", is_synthetic=True, evidence=left_evidence + right_evidence),
        plans, AssessmentContext(as_of=AS_OF),
    ).assessments[0]
    unresolved = next((state for state in ("conflict", "temporal", "unknown") if state in (left_state, right_state)), None)
    if unresolved:
        expected = unresolved
    else:
        values = [left_state == "satisfied", right_state == "satisfied"]
        expected = "satisfied" if (all(values) if operator == "AND" else any(values)) else "violated"
    assert result.state.value == expected
    assert len(result.dependencies) == 2
    assert set(result.evidence_ids) == {item.evidence_id for item in left_evidence + right_evidence}


def test_nested_or_does_not_hide_missing_brca():
    er, er_evidence = state_branch("ER", "satisfied")
    pr, pr_evidence = state_branch("PR", "satisfied")
    brca, _ = state_branch("BRCA", "unknown")
    inner = group("inner", "OR", [pr, brca])
    outer = group("outer", "AND", [er, inner])
    plans = [binding(node) for node in (er, pr, brca)]
    plans += [binding(node, clinical_attribute=None, value_type=None) for node in (inner, outer)]
    result = assess_criteria(
        TrialCriteriaSet(criteria=[outer], is_synthetic=True),
        SyntheticPatient(patient_id="synthetic", is_synthetic=True, evidence=er_evidence + pr_evidence),
        plans, AssessmentContext(as_of=AS_OF),
    ).assessments[0]
    assert result.state == AssessmentState.UNKNOWN
    assert result.dependencies[1].state == AssessmentState.UNKNOWN
    assert result.dependencies[1].dependencies[0].state == AssessmentState.SATISFIED


@pytest.mark.parametrize("updates,expected_reason", [
    ({"comparator": "approximately"}, "unsupported_comparison"),
    ({"threshold": "1-2"}, "unsupported_threshold"),
    ({"threshold": "NaN"}, "unsupported_threshold"),
    ({"threshold": None}, "unsupported_comparison"),
    ({"logical_operator": None}, "ambiguous_criterion"),
    ({"criterion_type": None}, "ambiguous_criterion"),
])
def test_unsupported_extracted_criteria_abstain(updates, expected_reason):
    result = run(criterion(**updates), [observation()])
    assert result.state == AssessmentState.UNKNOWN
    assert result.reason_code == expected_reason


def test_bindings_are_explicit_and_do_not_follow_changed_criteria():
    node = criterion()
    plan = binding(node, verified=False)
    assert run(node, [observation()], plan).state == AssessmentState.UNKNOWN
    verified = binding(node)
    node.threshold = "99"
    result = run(node, [observation()], verified)
    assert result.state == AssessmentState.UNKNOWN
    assert result.reason_code == "binding_criterion_mismatch"
    assert run(node, [observation()], binding(node, clinical_attribute="PR")).state == AssessmentState.UNKNOWN


def test_missing_binding_abstains():
    node = criterion()
    result = assess_criteria(
        TrialCriteriaSet(criteria=[node]),
        SyntheticPatient(patient_id="synthetic", is_synthetic=True, evidence=[observation()]),
        [], AssessmentContext(as_of=AS_OF),
    ).assessments[0]
    assert result.state == AssessmentState.UNKNOWN


def test_category_domain_is_required():
    node = criterion("BRCA", comparator="==", threshold="negative", unit=None)
    result = run(node, [observation("BRCA", "negative", units=None)], binding(node, value_type="categorical"))
    assert result.state == AssessmentState.UNKNOWN
    assert result.reason_code == "missing_category_domain"


def test_cohort_scope_is_not_inferred():
    node = criterion(cohort="synthetic-cohort-A")
    assert run(node, [observation()]).state == AssessmentState.UNKNOWN
    assert run(node, [observation()], context=AssessmentContext(as_of=AS_OF, cohort="synthetic-cohort-B")).state == AssessmentState.UNKNOWN
    assert run(node, [observation()], context=AssessmentContext(as_of=AS_OF, cohort=node.cohort)).state == AssessmentState.SATISFIED


def test_compound_temporal_qualifier_not_silently_discarded():
    left, evidence = state_branch("ER", "satisfied")
    right, more = state_branch("PR", "satisfied")
    parent = group("parent", "AND", [left, right])
    parent.temporal_constraint = "synthetic unresolved sequence"
    result = assess_criteria(
        TrialCriteriaSet(criteria=[parent]),
        SyntheticPatient(patient_id="synthetic", is_synthetic=True, evidence=evidence + more),
        [binding(left), binding(right), binding(parent, value_type=None, clinical_attribute=None)],
        AssessmentContext(as_of=AS_OF),
    ).assessments[0]
    assert result.state == AssessmentState.UNKNOWN
    assert result.reason_code == "unsupported_compound_qualifier"


def test_temporal_mapping_must_match_source():
    node = criterion(temporal_constraint="within 7 days")
    plan = binding(node, temporal_rule=TemporalRule(source_text="within 30 days", kind="freshness", max_age_days=30))
    assert run(node, [observation()], plan).state == AssessmentState.UNKNOWN


def test_atomic_conflict_precedes_time_and_missing_values():
    node = criterion(temporal_constraint="within 7 days")
    plan = binding(node, temporal_rule=TemporalRule(source_text=node.temporal_constraint, kind="freshness", max_age_days=7))
    evidence = [
        observation(value="0", evidence_id="old", observation_date=AS_OF - timedelta(days=30)),
        observation(value="2", evidence_id="future", observation_date=AS_OF + timedelta(days=1)),
        observation(value=None, evidence_id="missing"),
    ]
    assert run(node, evidence, plan).state == AssessmentState.CONFLICT
    assert run(node, [evidence[0], evidence[2]], plan).state == AssessmentState.TEMPORAL
    assert run(criterion(), [observation(), evidence[2]]).state == AssessmentState.UNKNOWN


def test_result_is_reproducible_and_preserves_provenance():
    node = criterion()
    evidence = observation()
    patient = SyntheticPatient(patient_id="synthetic", is_synthetic=True, evidence=[evidence])
    criteria_set = TrialCriteriaSet(
        criteria=[node], is_synthetic=True, nct_id=node.nct_id,
        source_snapshot="data/synthetic/example.json", source_url=node.source_url,
        retrieval_timestamp=AS_OF - timedelta(days=1), original_text=node.original_text,
    )
    plans = [binding(node)]
    context = AssessmentContext(as_of=AS_OF)
    result = assess_criteria(criteria_set, patient, plans, context)
    assert result == assess_criteria(criteria_set, patient, plans, context)
    assert TrialAssessment.model_validate_json(result.model_dump_json()) == result
    assessment = result.assessments[0]
    assert assessment.criterion == node
    assert assessment.assessment_timestamp == AS_OF
    assert assessment.evidence[0].provenance == evidence.provenance
    assert assessment.evidence[0].source == "synthetic fixture"
    assert assessment.binding.provenance == "manual synthetic mapping"
    assert result.criteria_set.source_snapshot == criteria_set.source_snapshot
    original = result.model_dump_json()
    node.original_text = "Changed input"
    evidence.provenance.record_id = "changed"
    assert result.model_dump_json() == original


@pytest.mark.parametrize("updates", [
    {"value": True}, {"value": Decimal("NaN")}, {"value": Decimal("Infinity")},
    {"observation_date": "2026-10-23T12:00:00"}, {"evidence_id": ""},
    {"source": ""}, {"provenance": {}},
])
def test_invalid_evidence_models(updates):
    with pytest.raises(ValidationError):
        observation(**updates)


def test_patient_and_context_validation():
    with pytest.raises(ValidationError):
        SyntheticPatient(patient_id="synthetic", is_synthetic=False, evidence=[])
    with pytest.raises(ValidationError):
        SyntheticPatient(patient_id="synthetic", is_synthetic=True, evidence=[observation(), observation()])
    with pytest.raises(ValidationError):
        AssessmentContext(as_of="2026-10-23T12:00:00")
    with pytest.raises(ValidationError):
        TemporalRule(source_text="synthetic window", kind="freshness")
    with pytest.raises(ValidationError):
        TemporalRule(source_text="synthetic window", kind="freshness", max_age_days=-1)
    with pytest.raises(ValidationError):
        TemporalRule(source_text="synthetic elapsed", kind="elapsed", max_age_days=7)


def test_invalid_binding_references_rejected():
    node = criterion()
    criteria_set = TrialCriteriaSet(criteria=[node])
    patient = SyntheticPatient(patient_id="synthetic", is_synthetic=True, evidence=[])
    context = AssessmentContext(as_of=AS_OF)
    with pytest.raises(ValueError, match="Duplicate"):
        assess_criteria(criteria_set, patient, [binding(node), binding(node)], context)
    with pytest.raises(ValueError, match="unknown criterion"):
        assess_criteria(criteria_set, patient, [binding(criterion("PR"))], context)


def test_exact_comparison_is_independent_of_decimal_context():
    threshold = "1." + "0" * 60
    value = "1." + "0" * 59 + "1"
    node = criterion(comparator=">", threshold=threshold, unit="g/L")
    evidence = observation(value=value, units="g/L")
    with localcontext() as context:
        context.prec = 2
        result = run(node, [evidence])
    assert result.state == AssessmentState.SATISFIED


def test_freshness_boundary_uses_exact_time():
    node = criterion(temporal_constraint="within 7 days")
    plan = binding(node, temporal_rule=TemporalRule(source_text=node.temporal_constraint, kind="freshness", max_age_days=7))
    evidence = observation(observation_date=AS_OF - timedelta(days=7, microseconds=1))
    assert run(node, [evidence], plan).state == AssessmentState.TEMPORAL


def test_small_numeric_evidence_is_not_rejected_due_to_decimal_display():
    node = criterion(comparator="<", threshold="0.000001", unit="1")
    assert run(node, [observation(value=Decimal("0.00000001"), units="1")]).state == AssessmentState.SATISFIED


@pytest.mark.parametrize("label", [1, "true"])
def test_synthetic_label_is_explicit_boolean(label):
    with pytest.raises(ValidationError):
        SyntheticPatient(patient_id="synthetic", is_synthetic=label, evidence=[])
