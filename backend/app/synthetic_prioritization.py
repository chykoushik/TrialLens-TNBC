from backend.app.assessment_models import (
    AssessmentContext, CriterionBinding, EvidenceProvenance, PatientEvidence, SyntheticPatient,
)
from backend.app.criteria import TrialCriteriaSet, TrialCriterion
from backend.app.prioritization_models import (
    CriterionReference, EvidenceReview, Portfolio, ReviewOutcome, TrialProtocol,
)


def synthetic_protocol(identifier: str, attributes: list[str]) -> TrialProtocol:
    criteria, bindings = [], []
    for attribute in attributes:
        node = TrialCriterion(
            criterion_id=f"{identifier}-{attribute}", nct_id=f"SYNTHETIC-{identifier}",
            original_text=f"SYNTHETIC ONLY: {attribute} == 1", criterion_type="inclusion",
            logical_operator="NONE", biomarker=attribute, comparator="==", threshold="1", unit="1",
            source_url=f"https://example.invalid/synthetic/{identifier}",
            extraction_method="manual synthetic protocol",
        )
        criteria.append(node)
        bindings.append(CriterionBinding(
            criterion=node, verified=True, provenance="manual synthetic mapping",
            clinical_attribute=attribute, value_type="numeric",
        ))
    return TrialProtocol(
        trial_id=identifier, criteria_set=TrialCriteriaSet(
            criteria=criteria, nct_id=f"SYNTHETIC-{identifier}", is_synthetic=True,
            source_snapshot=f"synthetic://protocol/{identifier}",
        ), bindings=bindings, context=AssessmentContext(as_of="2026-10-23T12:00:00Z"),
    )


def synthetic_review(
    identifier: str, attribute: str, trials: list[TrialProtocol], *, cost: str,
    positive_probability: str = "0.5", depends_on: list[str] | None = None, noop: bool = False,
) -> EvidenceReview:
    from decimal import Decimal

    targets = [CriterionReference(trial_id=trial.trial_id, criterion_id=binding.criterion.criterion_id)
               for trial in trials for binding in trial.bindings if binding.clinical_attribute == attribute]
    record = EvidenceProvenance(record_id=f"synthetic-record-{identifier}", reference=f"synthetic://record/{identifier}")
    if noop:
        outcomes = [ReviewOutcome(outcome_id="unreadable", probability="1", description="Synthetic review yields no usable information")]
    else:
        positive = Decimal(positive_probability)
        outcomes = []
        for label, value, probability in (("positive", "1", positive), ("negative", "0", Decimal(1) - positive)):
            outcomes.append(ReviewOutcome(
                outcome_id=label, probability=probability,
                description=f"Illustrative synthetic {label} record content",
                additions=[PatientEvidence(
                    evidence_id=f"synthetic-review-{identifier}", clinical_attribute=attribute,
                    value=value, units="1", observation_date="2026-10-23T12:00:00Z",
                    source="synthetic existing-record review", provenance=record,
                )],
            ))
    return EvidenceReview(
        item_id=identifier, action_type="review_existing_evidence", existing_record=record,
        description="Review an existing synthetic record; no new testing",
        cost=cost, targets=targets, depends_on=depends_on or [], outcomes=outcomes,
        probability_basis="ILLUSTRATIVE synthetic assumption; not empirically calibrated",
    )


def synthetic_portfolios() -> list[Portfolio]:
    broad_trials = [synthetic_protocol(f"broad-{index}", ["X", "Y"]) for index in range(3)]
    narrow = synthetic_protocol("decisive", ["Z"])
    broad = Portfolio(
        portfolio_id="synthetic-breadth-versus-resolution",
        patient=SyntheticPatient(patient_id="synthetic-patient", is_synthetic=True, evidence=[]),
        trials=broad_trials + [narrow],
        candidates=[
            synthetic_review("broad-record", "X", broad_trials, cost="1", positive_probability="0.95"),
            synthetic_review("decisive-record", "Z", [narrow], cost="2"),
            synthetic_review("noop-record", "Y", broad_trials, cost="0.5", noop=True),
        ], cost_unit="synthetic review-effort units", outcome_model="independent_review_outcomes",
        assumptions=[
            "All protocols, records, patients, costs, and outcomes are synthetic.",
            "Illustrative distributions are assumptions, not empirical estimates.",
            "Review outcomes are assumed independent across distinct items.",
            "All unresolved protocol screening decisions have equal unit weight.",
        ],
    )
    complementary = synthetic_protocol("complementary", ["A", "B"])
    dependent = Portfolio(
        portfolio_id="synthetic-prerequisite-records", patient=broad.patient.model_copy(deep=True),
        trials=[complementary], candidates=[
            synthetic_review("retrieve-record", "A", [complementary], cost="1", positive_probability="1"),
            synthetic_review("linked-record", "B", [complementary], cost="1", positive_probability="1", depends_on=["retrieve-record"]),
        ], cost_unit=broad.cost_unit, outcome_model=broad.outcome_model,
        assumptions=broad.assumptions + ["The linked record requires the first record's review; assumed positive content is illustrative."],
    )
    return [broad, dependent]
