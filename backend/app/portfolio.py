from fractions import Fraction

from backend.app.assessment import assess_criteria
from backend.app.assessment_models import SyntheticPatient
from backend.app.criteria import AssessmentState as State
from backend.app.prioritization_models import (
    Portfolio, PortfolioAssessment, ReviewOutcome, TrialDecision,
)

UNRESOLVED = {State.UNKNOWN, State.TEMPORAL, State.CONFLICT}


def evaluate_portfolio(portfolio: Portfolio, patient: SyntheticPatient | None = None) -> PortfolioAssessment:
    decisions = []
    uncertainty = Fraction()
    for trial in sorted(portfolio.trials, key=lambda item: item.trial_id):
        assessment = assess_criteria(trial.criteria_set, patient or portfolio.patient, trial.bindings, trial.context)
        unresolved, blockers = [], []

        def collect(node):
            if node.state in UNRESOLVED:
                unresolved.append(node.criterion_id)
            for child in node.dependencies:
                collect(child)

        for node in assessment.assessments:
            collect(node)
            if ((node.criterion.criterion_type == "inclusion" and node.state == State.VIOLATED)
                    or (node.criterion.criterion_type == "exclusion" and node.state == State.SATISFIED)):
                blockers.append(node.criterion_id)
        if blockers:
            decision = "observed_blocker"
        elif assessment.assessments and all(
            (node.criterion.criterion_type == "inclusion" and node.state == State.SATISFIED)
            or (node.criterion.criterion_type == "exclusion" and node.state == State.VIOLATED)
            for node in assessment.assessments
        ):
            decision = "constraints_consistent"
        else:
            decision = "unresolved"
            uncertainty += Fraction(trial.weight)
        decisions.append(TrialDecision(
            trial_id=trial.trial_id, decision=decision, assessment=assessment,
            unresolved_criterion_ids=unresolved, blocker_criterion_ids=blockers,
        ))
    return PortfolioAssessment(uncertainty=uncertainty, decisions=decisions)


def apply_outcome(patient: SyntheticPatient, outcome: ReviewOutcome) -> SyntheticPatient:
    evidence = {item.evidence_id: item.model_copy(deep=True) for item in patient.evidence}
    for retraction in outcome.retractions:
        if retraction.evidence_id not in evidence:
            raise ValueError("Cannot retract absent evidence")
        del evidence[retraction.evidence_id]
    for item in outcome.additions:
        if item.evidence_id in evidence:
            raise ValueError("Cannot overwrite evidence")
        evidence[item.evidence_id] = item.model_copy(deep=True)
    return SyntheticPatient(
        patient_id=patient.patient_id, is_synthetic=True,
        evidence=sorted(evidence.values(), key=lambda item: item.evidence_id),
    )


def decision_trace(assessment: PortfolioAssessment) -> list[dict]:
    traces = []
    for decision in assessment.decisions:
        criteria = []

        def collect(node):
            criteria.append({
                "criterion_id": node.criterion_id, "state": node.state.value,
                "polarity": node.criterion.criterion_type, "reason": node.reason_code,
                "evidence_ids": node.evidence_ids,
            })
            for child in node.dependencies:
                collect(child)

        for node in decision.assessment.assessments:
            collect(node)
        traces.append({
            "trial_id": decision.trial_id, "nct_id": decision.assessment.criteria_set.nct_id,
            "decision": decision.decision, "criteria": criteria,
            "unresolved_criterion_ids": decision.unresolved_criterion_ids,
            "blocker_criterion_ids": decision.blocker_criterion_ids,
        })
    return traces
