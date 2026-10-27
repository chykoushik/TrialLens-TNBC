import json
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import research_api
from backend.app.assessment_models import PatientEvidence
from backend.app.main import app
from backend.app.portfolio import evaluate_portfolio
from backend.app.prioritization import hypothetical_reviews
from backend.app.review_planning import ReviewPlanner
from backend.app.synthetic_review_research import research_cases
from backend.app.tnbc_demo import tnbc_cases

client = TestClient(app)


def nodes(assessment):
    def visit(node):
        yield node
        for child in node.dependencies:
            yield from visit(child)
    return {node.criterion_id: node for decision in assessment.decisions
            for root in decision.assessment.assessments for node in visit(root)}


@pytest.fixture
def cases():
    return {case.case_id: case for case in tnbc_cases()}


def evaluate(case_id, **body):
    return client.post(f"/tnbc/cases/{case_id}/evaluate", json=body)


def test_catalog_has_four_fictional_cases_and_no_nct_ids(cases):
    result = client.get("/tnbc/cases").json()
    assert len(result) == 4
    assert all(item["is_synthetic"] and item["title"] and item["description"] for item in result)
    for case in cases.values():
        for trial in case.model.portfolio.trials:
            assert trial.criteria_set.nct_id is None
            assert trial.criteria_set.is_synthetic is True
            for node in nodes(evaluate_portfolio(case.model.portfolio)).values():
                assert node.criterion.nct_id is None
                assert node.criterion.source_url.startswith("synthetic://")
                assert "FICTIONAL DEMO ONLY" in node.criterion.original_text


@pytest.mark.parametrize("case_id,criterion_id,state", [
    ("tnbc-complete", "demo-pdl1-tnbc", "satisfied"),
    ("tnbc-stale-labs", "demo-pdl1-pdl1", "violated"),
    ("tnbc-record-gaps", "demo-pdl1-pdl1", "unknown"),
    ("tnbc-stale-labs", "demo-brca-hemoglobin", "temporal"),
    ("tnbc-conflicting-records", "demo-brca-ecog", "conflict"),
])
def test_all_five_states_use_existing_engine(cases, case_id, criterion_id, state):
    model = cases[case_id].model
    assert nodes(evaluate_portfolio(model.portfolio))[criterion_id].state.value == state
    assert evaluate(case_id).status_code == 200


def test_biomarker_metadata_provenance_and_null_availability(cases):
    patient = cases["tnbc-record-gaps"].model.portfolio.patient
    pdl1 = [item for item in patient.evidence if item.clinical_attribute == "PD-L1"]
    assert {item.assay for item in pdl1} == {"22C3", "SP142"}
    unavailable = next(item for item in pdl1 if item.assay == "22C3")
    assert unavailable.value is None and unavailable.observation_date is None
    assert unavailable.availability == "unavailable"
    assert unavailable.units == "CPS" and unavailable.scoring_method == "Combined positive score (CPS)"
    assert unavailable.specimen_context and unavailable.provenance.reference.startswith("synthetic://")
    unknown = next(item for item in patient.evidence if item.clinical_attribute == "gBRCA2")
    assert unknown.value is None and unknown.availability == "unknown"
    negative = next(item for item in cases["tnbc-complete"].model.portfolio.patient.evidence if item.clinical_attribute == "gBRCA2")
    assert negative.value == "negative" and negative.availability == "recorded"
    assert PatientEvidence.model_validate(unavailable.model_dump()).model_dump() == unavailable.model_dump()
    with pytest.raises(ValidationError):
        PatientEvidence.model_validate({**unavailable.model_dump(), "value": "negative"})


def test_inclusion_exclusion_polarity_and_original_nested_logic(cases):
    assessment = evaluate_portfolio(cases["tnbc-conflicting-records"].model.portfolio)
    found = nodes(assessment)
    assert found["demo-pdl1-checkpoint"].criterion.criterion_type == "exclusion"
    assert found["demo-pdl1-checkpoint"].state.value == "satisfied"
    assert next(item for item in assessment.decisions if item.trial_id == "demo-pdl1").decision == "observed_blocker"
    assert found["demo-brca-tnbc"].criterion.logical_operator == "AND"
    assert found["demo-brca-receptors"].criterion.logical_operator == "AND"
    assert found["demo-brca-brca"].criterion.logical_operator == "OR"
    assert len(found["demo-brca-tnbc"].dependencies) == 2
    portfolio = cases["tnbc-complete"].model.portfolio.model_copy(deep=True)
    next(item for item in portfolio.patient.evidence if item.clinical_attribute == "gBRCA2").value = None
    assert nodes(evaluate_portfolio(portfolio))["demo-brca-brca"].state.value == "unknown"


def test_hypothetical_reviews_preserve_originals_and_all_provenance(cases):
    model = cases["tnbc-record-gaps"].model
    original = model.model_dump_json()
    patient = hypothetical_reviews(model.portfolio, {"review-pdl1-report": "cps-15"})
    assessed = nodes(evaluate_portfolio(model.portfolio, patient))["demo-pdl1-pdl1"]
    assert assessed.state.value == "satisfied"
    assert assessed.criterion.source_url.startswith("synthetic://")
    assert all(item.provenance.record_id and item.provenance.reference for item in assessed.evidence)
    assert model.model_dump_json() == original
    response = evaluate("tnbc-record-gaps", outcomes={"review-pdl1-report": "cps-15"}, budget=3)
    assert response.status_code == 200
    assert response.json()["assessment"]["uncertainty"] == "1"
    assert evaluate("tnbc-record-gaps").json()["assessment"]["uncertainty"] == "2"


def test_unavailable_noop_stays_unknown_and_reconciliation_is_explicit(cases):
    gap = cases["tnbc-record-gaps"].model.portfolio
    unchanged = hypothetical_reviews(gap, {"review-pdl1-report": "report-unavailable"})
    assert nodes(evaluate_portfolio(gap, unchanged))["demo-pdl1-pdl1"].state.value == "unknown"
    conflict = cases["tnbc-conflicting-records"].model.portfolio
    result = hypothetical_reviews(conflict, {"review-ecog-addendum": "ecog-1"})
    assert nodes(evaluate_portfolio(conflict, result))["demo-brca-ecog"].state.value == "satisfied"
    assert len([item for item in conflict.patient.evidence if item.clinical_attribute == "ECOG"]) == 2
    assert conflict.candidates[0].outcomes[0].retractions[0].provenance.reference.startswith("synthetic://")


def test_review_utilities_come_from_planner_and_assumptions_are_explicit(cases):
    planner = ReviewPlanner(cases["tnbc-record-gaps"].model)
    exact = planner.exact(3)
    assert exact["expected_reduction"] == Fraction(9, 5)
    assert evaluate("tnbc-record-gaps", budget=3).json()["plan"]["expected_reduction"] == "9/5"
    assert evaluate("tnbc-record-gaps", budget=3, algorithm="risk_exact").status_code == 409
    assert evaluate("tnbc-record-gaps", budget=0, outcomes={"review-pdl1-report": "cps-15"}).status_code == 422
    assert evaluate("ratio_trap").status_code == 404
    for case in cases.values():
        assert case.model.reliability is None
        assert all(action.action_type == "review_existing_evidence" for action in case.model.portfolio.candidates)
        assert "Illustrative" in " ".join(action.probability_basis for action in case.model.portfolio.candidates) or not case.model.portfolio.candidates


def test_original_nine_mathematical_scenarios_remain_separate():
    before = {case.case_id: case.model.model_dump_json() for case in research_cases()}
    evaluate("tnbc-record-gaps", budget=3, outcomes={"review-germline-report": "both-negative"})
    assert {case.case_id: case.model.model_dump_json() for case in research_cases()} == before
    assert len(client.get("/research/cases").json()) == 9
    assert client.post("/research/cases/ratio_trap/evaluate", json={"budget": 6}).json()["plan"]["expected_reduction"] == "8"


def test_frontend_synthetic_response_fixtures_match_engine_states_and_values():
    fixture = json.loads((Path(__file__).resolve().parents[2] / "frontend/src/fixtures/tnbc_demo.json").read_text())
    for key, case_id, outcomes in (
        ("baseline", "tnbc-record-gaps", {}),
        ("reviewed", "tnbc-record-gaps", {"review-pdl1-report": "cps-15"}),
        ("conflict", "tnbc-conflicting-records", {}),
        ("stale", "tnbc-stale-labs", {}),
    ):
        actual = evaluate(case_id, budget=3, outcomes=outcomes).json()
        saved = fixture[key]
        assert saved["patient"] == actual["patient"]
        assert saved["plan"]["expected_reduction"] == actual["plan"]["expected_reduction"]
        def flatten(data):
            result = {}
            def visit(node):
                result[node["criterion_id"]] = (node["state"], node["criterion"]["original_text"], node["evidence_ids"])
                for child in node["dependencies"]:
                    visit(child)
            for decision in data["assessment"]["decisions"]:
                for node in decision["assessment"]["assessments"]:
                    visit(node)
            return result
        assert flatten(saved) == flatten(actual)


def test_trial_snapshot_provenance_is_not_relabelled(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    with TemporaryDirectory(dir=root / "cache") as directory:
        snapshot = Path(directory) / "retrieved"
        snapshot.mkdir()
        payload = {"studies": [{"protocolSection": {"identificationModule": {"nctId": "NCT00000001"},
                                                  "eligibilityModule": {"eligibilityCriteria": "Original source text"}}}]}
        (snapshot / "response.json").write_text(json.dumps(payload))
        (snapshot / "metadata.json").write_text(json.dumps({"retrieved_at": "2026-10-23T12:00:00Z"}))
        monkeypatch.setattr(research_api, "RAW_TRIALS_DIR", Path(directory))
        record = client.get("/research/trials").json()["trials"][0]
        assert record["is_synthetic"] is None
        assert record["source_url"] == "https://clinicaltrials.gov/study/NCT00000001"
        assert record["eligibility_criteria"] == "Original source text"
        assert record["snapshot"] == "retrieved/response.json"
        assert record["retrieved_at"] == "2026-10-23T12:00:00Z"
