from decimal import DecimalException
from fractions import Fraction

from backend.app.assessment_models import (
    AssessedCriterion, AssessmentContext, CriterionBinding, PatientEvidence,
    SyntheticPatient, TrialAssessment,
)
from backend.app.assessment_values import COMPARATORS, UNITS, converted, number, seconds
from backend.app.criteria import AssessmentState as State
from backend.app.criteria import TrialCriteriaSet, TrialCriterion


def atomic_state(
    criterion: TrialCriterion, binding: CriterionBinding,
    evidence: list[PatientEvidence], context: AssessmentContext,
) -> tuple[State, str]:
    if not binding.clinical_attribute or not binding.value_type:
        return State.UNKNOWN, "missing_execution_mapping"
    if criterion.biomarker and criterion.biomarker != binding.clinical_attribute:
        return State.UNKNOWN, "attribute_mapping_mismatch"
    if criterion.comparator not in COMPARATORS or criterion.threshold is None:
        return State.UNKNOWN, "unsupported_comparison"
    if criterion.assay is None and any(item.assay is not None for item in evidence):
        return State.UNKNOWN, "unspecified_criterion_assay"
    matched = [item for item in evidence if item.assay == criterion.assay]
    if not matched or all(item.value is None for item in matched):
        return State.UNKNOWN, "missing_compatible_evidence"
    temporal = binding.temporal_rule
    if temporal and temporal.source_text != criterion.temporal_constraint:
        return State.UNKNOWN, "unsupported_temporal_mapping"
    if criterion.temporal_constraint and temporal is None:
        return State.TEMPORAL, "unresolved_temporal_constraint"
    elapsed = binding.value_type == "elapsed_days"
    if elapsed and (temporal is None or temporal.kind != "elapsed"):
        return State.UNKNOWN, "missing_elapsed_mapping"
    if not elapsed and temporal and temporal.kind != "freshness":
        return State.UNKNOWN, "unsupported_temporal_mapping"
    categorical = binding.value_type == "categorical"
    try:
        if categorical:
            if criterion.comparator not in ("==", "!=") or criterion.unit is not None:
                return State.UNKNOWN, "unsupported_categorical_comparison"
            if not binding.categories or criterion.threshold not in binding.categories:
                return State.UNKNOWN, "missing_category_domain"
            threshold = criterion.threshold
            if not threshold.strip():
                return State.UNKNOWN, "empty_categorical_threshold"
        else:
            if binding.categories is not None:
                return State.UNKNOWN, "unsupported_category_domain"
            if criterion.unit not in UNITS:
                return State.UNKNOWN, "unsupported_criterion_units"
            if elapsed and UNITS[criterion.unit][0] != "time":
                return State.UNKNOWN, "unsupported_elapsed_units"
            threshold = Fraction(number(criterion.threshold)) * Fraction(UNITS[criterion.unit][1])
    except (ValueError, DecimalException):
        return State.UNKNOWN, "unsupported_threshold"

    values = []
    problems = set()
    for item in matched:
        if item.observation_date and item.observation_date > context.as_of:
            problems.add(State.TEMPORAL)
        if temporal and item.observation_date is None:
            problems.add(State.TEMPORAL)
        if (temporal and temporal.kind == "freshness" and item.observation_date
                and seconds(context.as_of - item.observation_date) > Fraction(temporal.max_age_days) * 86400):
            problems.add(State.TEMPORAL)
        try:
            if elapsed:
                if item.value != "completed" or item.units is not None:
                    raise ValueError("Event must be explicitly completed")
                if item.observation_date is None:
                    continue
                value = seconds(context.as_of - item.observation_date)
            elif categorical:
                if not isinstance(item.value, str) or not item.value.strip() or item.units is not None:
                    raise ValueError("Unsupported categorical observation")
                if item.value not in binding.categories:
                    raise ValueError("Unresolved categorical observation")
                value = item.value
            else:
                value = converted(item.value, item.units, criterion.unit)
            values.append(value)
        except (ValueError, DecimalException):
            problems.add(State.UNKNOWN)
    if len(set(values)) > 1:
        return State.CONFLICT, "contradictory_observations"
    if State.TEMPORAL in problems:
        return State.TEMPORAL, "evidence_time_unresolved"
    if State.UNKNOWN in problems or not values:
        return State.UNKNOWN, "unusable_or_missing_observation"
    matched_condition = COMPARATORS[criterion.comparator](values[0], threshold)
    if elapsed and not matched_condition:
        return State.TEMPORAL, "elapsed_constraint_not_met"
    return ((State.SATISFIED, "condition_matched") if matched_condition
            else (State.VIOLATED, "condition_not_matched"))


def assess_criteria(
    criteria_set: TrialCriteriaSet, patient: SyntheticPatient,
    bindings: list[CriterionBinding], context: AssessmentContext,
) -> TrialAssessment:
    plans = {binding.criterion.criterion_id: binding for binding in bindings}
    if len(plans) != len(bindings):
        raise ValueError("Duplicate criterion bindings")
    identifiers = set()

    def collect(node):
        identifiers.add(node.criterion_id)
        for child in node.dependencies or []:
            collect(child)

    for criterion in criteria_set.criteria:
        collect(criterion)
    if set(plans) - identifiers:
        raise ValueError("Binding references an unknown criterion")

    def evaluate(node, inherited_cohort=None):
        cohort = node.cohort or inherited_cohort
        children = [evaluate(child, cohort) for child in node.dependencies or []]
        binding = plans.get(node.criterion_id)
        candidates = [item for item in patient.evidence
                      if binding and item.clinical_attribute == binding.clinical_attribute]
        by_id = {item.evidence_id: item for item in candidates}
        for child in children:
            by_id.update({item.evidence_id: item for item in child.evidence})
        evidence = sorted(by_id.values(), key=lambda item: item.evidence_id)
        state, reason = State.UNKNOWN, "unverified_or_missing_binding"
        if binding and binding.verified:
            if binding.criterion != node:
                reason = "binding_criterion_mismatch"
            elif node.criterion_type is None or node.logical_operator is None:
                reason = "ambiguous_criterion"
            elif inherited_cohort and node.cohort and node.cohort != inherited_cohort:
                reason = "ambiguous_cohort_scope"
            elif cohort and cohort != context.cohort:
                reason = "unresolved_cohort_scope"
            elif children:
                if any(getattr(node, field) is not None for field in (
                    "biomarker", "assay", "comparator", "threshold", "unit", "temporal_constraint",
                )) or binding.value_type or binding.clinical_attribute or binding.temporal_rule or binding.categories:
                    reason = "unsupported_compound_qualifier"
                else:
                    states = {child.state for child in children}
                    for unresolved in (State.CONFLICT, State.TEMPORAL, State.UNKNOWN):
                        if unresolved in states:
                            state, reason = unresolved, "unresolved_dependency"
                            break
                    else:
                        satisfied = (all(child.state == State.SATISFIED for child in children)
                                     if node.logical_operator == "AND"
                                     else any(child.state == State.SATISFIED for child in children))
                        state = State.SATISFIED if satisfied else State.VIOLATED
                        reason = "boolean_condition_evaluated"
            else:
                state, reason = atomic_state(node, binding, candidates, context)
        return AssessedCriterion(
            criterion_id=node.criterion_id, state=state,
            evidence_ids=[item.evidence_id for item in evidence], explanation=reason,
            assessment_timestamp=context.as_of, reason_code=reason,
            criterion=node.model_copy(deep=True),
            binding=binding.model_copy(deep=True) if binding else None,
            evidence=[item.model_copy(deep=True) for item in evidence], dependencies=children,
        )

    assessments = [evaluate(criterion) for criterion in criteria_set.criteria]
    return TrialAssessment(
        patient_id=patient.patient_id, is_synthetic=patient.is_synthetic,
        context=context.model_copy(deep=True), criteria_set=criteria_set.model_copy(deep=True),
        assessments=assessments,
    )
