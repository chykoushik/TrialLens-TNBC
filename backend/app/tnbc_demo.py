from dataclasses import dataclass
from datetime import datetime, timezone

from backend.app.assessment_models import (
    AssessmentContext, CriterionBinding, EvidenceProvenance, PatientEvidence,
    SyntheticPatient, TemporalRule,
)
from backend.app.criteria import TrialCriteriaSet, TrialCriterion
from backend.app.prioritization_models import (
    CriterionReference, EvidenceRetraction, EvidenceReview, Portfolio, ReviewOutcome, TrialProtocol,
)
from backend.app.review_planning_models import ReviewPlanningModel

AS_OF = "2026-10-24T12:00:00Z"
OBSERVED = "2026-10-20T12:00:00Z"
LABELS = {
    "ER": "Estrogen receptor (ER)", "PR": "Progesterone receptor (PR)",
    "HER2": "HER2 interpretation", "PD-L1": "PD-L1 expression",
    "gBRCA1": "Germline BRCA1", "gBRCA2": "Germline BRCA2",
    "ECOG": "ECOG performance status", "hemoglobin": "Hemoglobin",
    "disease_setting": "Disease setting", "CNS": "CNS disease status",
    "prior_checkpoint": "Prior checkpoint inhibitor exposure",
    "prior_platinum": "Prior platinum exposure", "prior_parp": "Prior PARP inhibitor exposure",
}
PROTOCOL_TITLES = {
    "demo-pdl1": "Fictional TNBC / PD-L1 record cohort",
    "demo-brca": "Fictional TNBC / germline BRCA record cohort",
}


@dataclass
class TNBCDemoCase:
    case_id: str
    title: str
    description: str
    model: ReviewPlanningModel


def provenance(identifier):
    return EvidenceProvenance(record_id=f"fictional-{identifier}", reference=f"synthetic://tnbc/records/{identifier}")


def evidence(attribute, value, *, suffix="baseline", units=None, assay=None, specimen=None,
             scoring=None, date=OBSERVED, availability="recorded"):
    return PatientEvidence(
        evidence_id=f"fictional-{attribute}-{suffix}", clinical_attribute=attribute,
        value=value, units=units, assay=assay, observation_date=date,
        specimen_context=specimen, scoring_method=scoring, availability=availability,
        source="Fictional TNBC demonstration record", provenance=provenance(f"{attribute}-{suffix}"),
    )


def protocols():
    trials = []
    for identifier in PROTOCOL_TITLES:
        bindings = []

        def atomic(key, attribute, comparator, threshold, *, units=None, assay=None,
                   categories=None, polarity="inclusion", temporal=None):
            text = f"FICTIONAL DEMO ONLY: {LABELS[attribute]} {comparator} {threshold}"
            if units:
                text += f" {units}"
            if assay:
                text += f" using {assay}"
            if temporal:
                text += f"; {temporal}"
            node = TrialCriterion(
                criterion_id=f"{identifier}-{key}", original_text=text,
                criterion_type=polarity, logical_operator="NONE", biomarker=attribute,
                comparator=comparator, threshold=threshold, unit=units, assay=assay,
                temporal_constraint=temporal, source_url=f"synthetic://tnbc/protocols/{identifier}",
                extraction_method="manual fictional demonstration",
            )
            bindings.append(CriterionBinding(
                criterion=node, verified=True, provenance="Manual fictional mapping; not a real protocol",
                clinical_attribute=attribute, value_type="categorical" if categories else "numeric",
                categories=categories,
                temporal_rule=TemporalRule(source_text=temporal, kind="freshness", max_age_days=14) if temporal else None,
            ))
            return node

        def group(key, operator, children, text):
            node = TrialCriterion(
                criterion_id=f"{identifier}-{key}", original_text=f"FICTIONAL DEMO ONLY: {text}",
                criterion_type="inclusion", logical_operator=operator, dependencies=children,
                source_url=f"synthetic://tnbc/protocols/{identifier}", extraction_method="manual fictional demonstration",
            )
            bindings.append(CriterionBinding(criterion=node, verified=True, provenance="Manual fictional Boolean mapping"))
            return node

        receptors = group("receptors", "AND", [
            atomic("er", "ER", "<", "1", units="%", assay="IHC"),
            atomic("pr", "PR", "<", "1", units="%", assay="IHC"),
        ], "ER < 1% AND PR < 1%, both by IHC.")
        tnbc = group("tnbc", "AND", [receptors, atomic(
            "her2", "HER2", "==", "negative", assay="IHC/ISH reviewed interpretation",
            categories=["negative", "positive"],
        )], "(ER < 1% AND PR < 1%) AND an explicitly reviewed HER2-negative interpretation.")
        criteria = [
            tnbc,
            atomic("setting", "disease_setting", "==", "metastatic", categories=["metastatic", "early"]),
            atomic("ecog", "ECOG", "<=", "1", units="ECOG"),
            atomic("hemoglobin", "hemoglobin", ">=", "9", units="g/dL",
                   temporal="Fictional protocol requires a hemoglobin observation within 14 days of assessment."),
        ]
        if identifier == "demo-pdl1":
            criteria.append(atomic("pdl1", "PD-L1", ">=", "10", units="CPS", assay="22C3"))
            criteria.append(atomic("checkpoint", "prior_checkpoint", "==", "yes",
                                   categories=["yes", "no"], polarity="exclusion"))
        else:
            criteria.append(group("brca", "OR", [
                atomic("brca1", "gBRCA1", "==", "pathogenic_variant", assay="germline sequencing",
                       categories=["pathogenic_variant", "negative"]),
                atomic("brca2", "gBRCA2", "==", "pathogenic_variant", assay="germline sequencing",
                       categories=["pathogenic_variant", "negative"]),
            ], "A recorded germline pathogenic BRCA1 variant OR a recorded germline pathogenic BRCA2 variant."))
            criteria.append(atomic("platinum", "prior_platinum", "==", "yes", categories=["yes", "no"]))
            criteria.append(atomic("parp", "prior_parp", "==", "yes", categories=["yes", "no"], polarity="exclusion"))
        criteria.append(atomic("cns", "CNS", "==", "active", categories=["active", "stable", "none"], polarity="exclusion"))
        trials.append(TrialProtocol(
            trial_id=identifier,
            criteria_set=TrialCriteriaSet(
                criteria=criteria, nct_id=None, is_synthetic=True,
                original_text="\n".join(node.original_text for node in criteria),
                source_url=f"synthetic://tnbc/protocols/{identifier}", source_snapshot="backend/app/tnbc_demo.py",
            ), bindings=bindings, context=AssessmentContext(as_of=AS_OF),
        ))
    return trials


def baseline_evidence():
    return [
        evidence("ER", "0", units="%", assay="IHC", specimen="Fictional metastatic tumor biopsy", scoring="Tumor nuclear staining percentage"),
        evidence("PR", "0", units="%", assay="IHC", specimen="Fictional metastatic tumor biopsy", scoring="Tumor nuclear staining percentage"),
        evidence("HER2", "negative", assay="IHC/ISH reviewed interpretation", specimen="Fictional metastatic tumor biopsy", scoring="Recorded negative interpretation; no score conversion"),
        evidence("PD-L1", "15", units="CPS", assay="22C3", specimen="Fictional metastatic tumor biopsy", scoring="Combined positive score (CPS)"),
        evidence("gBRCA1", "pathogenic_variant", assay="germline sequencing", specimen="Fictional peripheral blood"),
        evidence("gBRCA2", "negative", assay="germline sequencing", specimen="Fictional peripheral blood"),
        evidence("ECOG", "1", units="ECOG", scoring="Recorded ECOG scale"),
        evidence("hemoglobin", "11.8", units="g/dL", specimen="Fictional peripheral blood"),
        evidence("disease_setting", "metastatic"), evidence("CNS", "none"),
        evidence("prior_checkpoint", "no"), evidence("prior_platinum", "yes"), evidence("prior_parp", "no"),
    ]


def review(identifier, description, attributes, patient, trials, variants, cost):
    retracted = [item for item in patient.evidence if item.clinical_attribute in attributes]
    record = provenance(identifier)
    outcomes = []
    for name, probability, additions in variants:
        outcomes.append(ReviewOutcome(
            outcome_id=name, probability=probability, description=f"FICTIONAL existing record review: {name}",
            additions=additions,
            retractions=[EvidenceRetraction(evidence_id=item.evidence_id,
                        reason="Explicit hypothetical replacement from fictional record addendum; not automatic adjudication",
                        provenance=record) for item in retracted] if additions else [],
        ))
    return EvidenceReview(
        item_id=identifier, action_type="review_existing_evidence", existing_record=record,
        description=description, cost=cost,
        targets=[CriterionReference(trial_id=trial.trial_id, criterion_id=binding.criterion.criterion_id)
                 for trial in trials for binding in trial.bindings if binding.clinical_attribute in attributes],
        outcomes=outcomes,
        probability_basis="Illustrative fictional review-outcome distribution; not empirical or clinically calibrated",
    )


def tnbc_cases():
    cases = []
    descriptions = [
        ("tnbc-complete", "Complete fictional records", "Recorded receptor, PD-L1, germline, treatment and laboratory evidence."),
        ("tnbc-record-gaps", "Missing assay-matched records", "Unavailable 22C3 CPS report, an incompatible SP142 IC score and unknown germline results."),
        ("tnbc-stale-labs", "Stale laboratory observation", "Old hemoglobin under an explicit fictional 14-day window; PD-L1 below the fictional threshold."),
        ("tnbc-conflicting-records", "Conflicting performance records", "Contradictory ECOG observations and recorded prior checkpoint exposure; polarity stays explicit."),
    ]
    for case_id, title, description in descriptions:
        trials = protocols()
        observations = baseline_evidence()
        by_attribute = {item.clinical_attribute: item for item in observations}
        if case_id == "tnbc-record-gaps":
            by_attribute["PD-L1"].value = None
            by_attribute["PD-L1"].availability = "unavailable"
            by_attribute["PD-L1"].observation_date = None
            for attribute in ("gBRCA1", "gBRCA2"):
                by_attribute[attribute].value = None
                by_attribute[attribute].availability = "unknown"
                by_attribute[attribute].observation_date = None
            observations.append(evidence("PD-L1", "2", suffix="other-assay", units="%", assay="SP142",
                                         specimen="Fictional archival primary tumor", scoring="Immune-cell area score (IC)"))
        elif case_id == "tnbc-stale-labs":
            by_attribute["hemoglobin"].observation_date = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
            by_attribute["PD-L1"].value = "4"
        elif case_id == "tnbc-conflicting-records":
            observations.append(evidence("ECOG", "3", suffix="contradiction", units="ECOG", scoring="Recorded ECOG scale"))
            by_attribute["prior_checkpoint"].value = "yes"
        patient = SyntheticPatient(patient_id=case_id, is_synthetic=True, evidence=observations)
        reviews = []
        if case_id == "tnbc-record-gaps":
            def pdl1(value):
                return [evidence("PD-L1", value, suffix="review", units="CPS", assay="22C3",
                                 specimen="Fictional metastatic tumor biopsy", scoring="Combined positive score (CPS)")]
            reviews.append(review("review-pdl1-report", "Read the existing fictional 22C3 CPS pathology report",
                                  {"PD-L1"}, patient, trials,
                                  [("cps-15", "0.45", pdl1("15")), ("cps-4", "0.45", pdl1("4")),
                                   ("report-unavailable", "0.10", [])], "1"))
            def germline(value):
                return [evidence("gBRCA1", value, suffix="review", assay="germline sequencing", specimen="Fictional peripheral blood"),
                        evidence("gBRCA2", "negative", suffix="review", assay="germline sequencing", specimen="Fictional peripheral blood")]
            reviews.append(review("review-germline-report", "Read the existing fictional germline BRCA1/2 laboratory report",
                                  {"gBRCA1", "gBRCA2"}, patient, trials,
                                  [("brca1-pathogenic", "0.45", germline("pathogenic_variant")),
                                   ("both-negative", "0.45", germline("negative")), ("report-unavailable", "0.10", [])], "2"))
        elif case_id == "tnbc-stale-labs":
            reviews.append(review("review-lab-record", "Read the existing fictional dated blood-count record",
                                  {"hemoglobin"}, patient, trials,
                                  [("hemoglobin-10", "0.45", [evidence("hemoglobin", "10", suffix="review", units="g/dL", specimen="Fictional peripheral blood")]),
                                   ("hemoglobin-8", "0.45", [evidence("hemoglobin", "8", suffix="review", units="g/dL", specimen="Fictional peripheral blood")]),
                                   ("record-unavailable", "0.10", [])], "1"))
        elif case_id == "tnbc-conflicting-records":
            reviews.append(review("review-ecog-addendum", "Read the existing fictional ECOG reconciliation addendum",
                                  {"ECOG"}, patient, trials,
                                  [("ecog-1", "0.45", [evidence("ECOG", "1", suffix="review", units="ECOG", scoring="Recorded ECOG scale")]),
                                   ("ecog-2", "0.45", [evidence("ECOG", "2", suffix="review", units="ECOG", scoring="Recorded ECOG scale")]),
                                   ("unresolved-addendum", "0.10", [])], "1"))
        assumptions = [
            "All TNBC demonstration patients, observations, protocols and records are fictional; these are not actual trial rules.",
            "All thresholds and the 14-day lab window are explicit demonstration assumptions, not medical guidance.",
            "Review probabilities and effort costs are illustrative; no clinical calibration, reliability rates or hidden truth are supplied.",
            "Distinct review records are assumed independent for this demonstration; no new medical tests are proposed.",
            "Assay identifiers and scoring units must match; specimen context is preserved but not automatically adjudicated.",
        ]
        model = ReviewPlanningModel(
            portfolio=Portfolio(portfolio_id=case_id, patient=patient, trials=trials, candidates=reviews,
                                cost_unit="fictional record-review effort units", outcome_model="independent_review_outcomes",
                                assumptions=assumptions),
            dependence_mode="independent_disjoint", assumptions=["Fictional TNBC demonstration, separate from mathematical experiments."],
        )
        cases.append(TNBCDemoCase(case_id, title, description, model))
    return cases
