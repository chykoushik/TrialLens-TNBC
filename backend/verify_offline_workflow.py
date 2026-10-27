import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import get_args
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import extraction, research_api
from backend.app.extraction_source import ROOT
from backend.app.main import app
from backend.app.tnbc_demo import tnbc_cases


def criterion_states(data):
    def visit(node):
        yield node
        for child in node["dependencies"]:
            yield from visit(child)
    return {node["criterion_id"]: node["state"]
            for decision in data["assessment"]["decisions"]
            for root in decision["assessment"]["assessments"] for node in visit(root)}


def verify(output):
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT) or output == ROOT:
        raise ValueError("Project output required")
    output.mkdir(parents=True, exist_ok=False)
    client = TestClient(app)
    files = sorted((ROOT / "data/raw/trials").rglob("*.json"))
    files += [ROOT / "backend/app/tnbc_demo.py", ROOT / "frontend/src/fixtures/tnbc_demo.json"]
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    originals = [case.model.model_dump(mode="json") for case in tnbc_cases()]
    transitions = []

    def evaluate(outcomes, expected, budget="3", case="tnbc-record-gaps", algorithm="adaptive_replan"):
        response = client.post(f"/tnbc/cases/{case}/evaluate", json={
            "algorithm": algorithm, "budget": budget, "outcomes": outcomes, "seed": 7})
        assert response.status_code == 200, response.text
        data = response.json()
        actual = [data["spent"], data["remaining_budget"], data["assessment"]["uncertainty"], data["next_review"]]
        assert actual == expected, (actual, expected)
        transitions.append({"case": case, "algorithm": algorithm, "budget": budget, "outcomes": outcomes,
                            "spent": actual[0], "remaining": actual[1], "uncertainty": actual[2],
                            "next_review": actual[3], "selected_reviews": data["plan"]["selected_items"],
                            "expected_reduction": data["plan"]["expected_reduction"],
                            "expected_final_uncertainty": data["plan"]["expected_final_uncertainty"],
                            "states": criterion_states(data)})
        return data

    baseline = evaluate({}, ["0", "3", "2", "review-germline-report"])
    assert baseline["plan"]["expected_reduction"] == "9/5"
    assert baseline["plan"]["expected_final_uncertainty"] == "1/5"
    assert set(baseline["plan"]["selected_items"]) == {"review-germline-report", "review-pdl1-report"}
    assert criterion_states(baseline)["demo-pdl1-pdl1"] == "unknown"
    for candidate in baseline["candidates"]:
        assert candidate["targets"]
        assert all(target["criterion_id"] in criterion_states(baseline) for target in candidate["targets"])
    germline = {"review-germline-report": "brca1-pathogenic"}
    brca = evaluate(germline, ["2", "1", "1", "review-pdl1-report"])
    assert criterion_states(brca)["demo-brca-brca"] == "satisfied"
    assert {e["clinical_attribute"]: e["value"] for e in brca["patient"]["evidence"] if e["clinical_attribute"].startswith("gBRCA")} == {"gBRCA1": "pathogenic_variant", "gBRCA2": "negative"}
    pdl1 = {"review-pdl1-report": "cps-15"}
    cps = evaluate(pdl1, ["1", "2", "1", "review-germline-report"])
    assert criterion_states(cps)["demo-pdl1-pdl1"] == "satisfied"
    assert "fictional-PD-L1-review" in next(node for decision in cps["assessment"]["decisions"] for node in decision["assessment"]["assessments"] if node["criterion_id"] == "demo-pdl1-pdl1")["evidence_ids"]
    other_assay = next(e for e in baseline["patient"]["evidence"] if e["assay"] == "SP142")
    report_candidate = next(item for item in baseline["candidates"] if item["item_id"] == "review-pdl1-report")
    outcome = next(item for item in report_candidate["outcomes"] if item["outcome_id"] == "cps-15")
    assert other_assay["evidence_id"] in {item["evidence_id"] for item in outcome["retractions"]}
    assert all(e["assay"] != "SP142" for e in cps["patient"]["evidence"])
    matched = [e for e in cps["patient"]["evidence"] if e["assay"] == "22C3"]
    assert any(e["value"] == "15" and e["units"] == "CPS" for e in matched)
    both = evaluate({**germline, **pdl1}, ["3", "0", "0", None])
    assert not both["plan"]["selected_items"]
    assert criterion_states(both)["demo-brca-brca"] == "satisfied"
    unavailable = evaluate({"review-pdl1-report": "report-unavailable"}, ["1", "2", "2", "review-germline-report"])
    assert {e["evidence_id"]: e for e in unavailable["patient"]["evidence"]} == {e["evidence_id"]: e for e in baseline["patient"]["evidence"]}
    evaluate({}, ["0", "0", "2", None], budget="0")
    evaluate({}, ["0", "3", "0", None], case="tnbc-complete")
    assert evaluate({}, ["0", "3", "2", None], algorithm="exact_nonadaptive")["patient"] == baseline["patient"]
    assert evaluate({}, ["0", "3", "2", "review-germline-report"])["patient"] == baseline["patient"]
    assert client.post("/tnbc/cases/tnbc-record-gaps/evaluate", json={"budget": "1", "outcomes": germline}).status_code == 422
    assert client.post("/tnbc/cases/tnbc-record-gaps/evaluate", json={"criteria": {"nct_id": "NCT02648477"}}).status_code == 422
    assert client.post("/tnbc/cases/NCT02648477/evaluate", json={}).status_code == 404
    assert len(client.get("/tnbc/cases").json()) == 4
    assert len(client.get("/research/cases").json()) == 9
    assert len(get_args(research_api.Algorithm)) == 13
    studies = [item for item in client.get("/research/trials").json()["trials"] if item["is_synthetic"] is not True]
    assert {item["nct_id"] for item in studies} == {
        "NCT01770353", "NCT02648477", "NCT03538028", "NCT04331067", "NCT04691375"}
    sources = []
    with patch.object(extraction, "RESULTS_DIR", output / "mock-extractions"), patch.object(
            extraction, "chat_completion", side_effect=AssertionError("Inference prohibited")):
        for study in studies:
            identity = client.get(f"/saved-trials/{study['nct_id']}").json()
            assert len(identity["snapshots"]) == 2
            for version in identity["snapshots"]:
                historical = client.get(f"/saved-trials/{study['nct_id']}", params={"snapshot": version["snapshot"]})
                assert historical.status_code == 200
                assert historical.json()["source"]["sha256"] == version["snapshot_sha256"]
            result = client.post(f"/saved-trials/{study['nct_id']}/extractions", json={"mode": "mock"})
            assert result.status_code == 200, result.text
            result = result.json()
            assert result["assessment_allowed"] is False and result["validated"] is None
            assert result["manifest"]["status"] == "validation_failed"
            assert result["validation_errors"] and result["unsupported_criteria"]
            for node, evidence in zip(result["candidate"]["criteria"], result["candidate"]["evidence"]):
                span = evidence["original_span"]
                assert identity["source"]["text"][span["start"]:span["end"]] == node["original_text"]
            sources.append({"nct_id": study["nct_id"], "snapshots": identity["snapshots"],
                            "mock_status": result["manifest"]["status"], "assessment_allowed": False,
                            "validation_error_count": len(result["validation_errors"]),
                            "unsupported_count": len(result["unsupported_criteria"])})
    assert originals == [case.model.model_dump(mode="json") for case in tnbc_cases()]
    assert hashes == {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in hashes}
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "scenario": "Offline software regression, not clinical validation",
              "transitions": transitions, "sources": sources, "unchanged_source_hashes": hashes,
              "checks": ["four fictional cases", "nine mathematical scenarios", "13 strategies",
                         "assay separation", "working-copy isolation", "insufficient budget rejected",
                         "unreviewed real criteria blocked", "five studies and ten snapshots",
                         "strict mock validation", "no inference"],
              "limitations": ["Model assumptions and fictional outcomes do not establish clinical validity.",
                              "This API report does not itself verify browser interactions; see browser test results.",
                              "No extraction accuracy metrics: reference annotations remain unreviewed."]}
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    rows = ["| Outcomes | Spent | Remaining | Uncertainty | Next review |", "| --- | --- | --- | --- | --- |"]
    for item in transitions:
        rows.append(f"| {item['case']} / {item['algorithm']} / {item['outcomes'] or 'original'} | {item['spent']} | {item['remaining']} | {item['uncertainty']} | {item['next_review'] or 'None'} |")
    (output / "report.md").write_text("# Offline workflow verification\n\n" + report["scenario"] + "\n\n" + "\n".join(rows)
        + "\n\nAssertions passed: " + "; ".join(report["checks"]) + ".\n\n"
        + "\n".join(report["limitations"]) + "\n\nExact states, snapshot identities, hashes and isolated mock artifacts accompany this report.\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    verify(parser.parse_args().output)
