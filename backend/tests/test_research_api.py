import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from backend.app import research_api
from backend.app.main import app

client = TestClient(app)


@pytest.fixture
def snapshot_dir():
    cache = Path(__file__).resolve().parents[2] / "cache"
    cache.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=cache) as directory:
        yield Path(directory)


def evaluate(case="ratio_trap", **body):
    return client.post(f"/research/cases/{case}/evaluate", json=body)


def test_catalog_labels_unsupported_case_and_excludes_truth():
    response = client.get("/research/cases")
    assert response.status_code == 200
    assert len(response.json()) == 9
    assert all(item["is_synthetic"] for item in response.json())
    assert next(item for item in response.json() if item["case_id"] == "overlap_without_joint")["unsupported"]
    assert "evaluation_worlds" not in response.text


def test_exact_reuses_reference_and_does_not_expose_hidden_truth():
    response = evaluate(budget=6)
    assert response.status_code == 200
    result = response.json()
    assert result["plan"]["selected_items"] == ["b", "c"]
    assert result["plan"]["expected_reduction"] == "8"
    assert result["assessment"]["uncertainty"] == "11"
    assert "evaluation_worlds" not in response.text
    assert '"truth"' not in response.text
    assert "API_KEY" not in response.text


def test_hypothetical_reviews_leave_original_evidence_unchanged():
    result = evaluate(budget=6, outcomes={"a": "negative"}).json()
    assert len(result["patient"]["evidence"]) == 1
    assert result["spent"] == "2"
    assert evaluate(budget=6).json()["patient"]["evidence"] == []


@pytest.mark.parametrize("body", [{"budget": -1}, {"budget": "NaN"}, {"budget": 101},
                                  {"algorithm": "invented"}, {"seed": True}, {"extra": "ignored"},
                                  {"outcomes": {"missing": "positive"}},
                                  {"outcomes": {"a": "invented"}},
                                  {"budget": 1, "outcomes": {"a": "positive"}}])
def test_invalid_requests(body):
    assert evaluate(**body).status_code == 422


def test_prerequisite_and_joint_history_validation():
    assert evaluate("synthetic-prerequisite-records", outcomes={"linked-record": "positive"}).status_code == 422
    assert evaluate("correlated_duplicates", outcomes={"first": "positive", "copy": "negative"}).status_code == 409
    assert evaluate("overlap_without_joint").status_code == 409
    assert evaluate("noisy_review", algorithm="random").status_code == 409
    assert evaluate("not-found").status_code == 404


def test_adaptive_replans_conditioned_on_only_observed_report():
    result = evaluate("adaptive_branch", algorithm="adaptive_replan", budget=2, outcomes={"a": "negative"}).json()
    assert result["next_review"] == "c"
    assert result["plan"]["selected_items"] == ["c"]
    assert result["spent"] == "1"


def test_risk_and_legacy_algorithms():
    assert evaluate("noisy_review", algorithm="risk_exact", budget=2).json()["plan"]["selected_items"] == ["reliable"]
    assert evaluate(budget=6, algorithm="expected_per_cost").json()["plan"]["expected_reduction"] == "7"
    assert evaluate(budget=6, algorithm="expected_per_cost", outcomes={"a": "positive"}).status_code == 409


def test_local_snapshots_missing_fields_and_corruption(monkeypatch, snapshot_dir):
    monkeypatch.setattr(research_api, "RAW_TRIALS_DIR", snapshot_dir)
    good = snapshot_dir / "a"
    good.mkdir()
    (good / "response.json").write_text(json.dumps({"studies": [{"protocolSection": {"identificationModule": {"nctId": "NCT00000001"}}}]}))
    bad = snapshot_dir / "b"
    bad.mkdir()
    (bad / "response.json").write_text("invalid")
    result = client.get("/research/trials").json()
    assert result["trials"][0]["nct_id"] == "NCT00000001"
    assert result["trials"][0]["eligibility_criteria"] is None
    assert len(result["warnings"]) == 1
    assert client.get("/research/trials?limit=0").status_code == 422


def test_cors_only_allows_local_development():
    for origin in ("http://127.0.0.1:5173", "http://localhost:5173", "https://untrusted.example"):
        response = client.options("/research/cases", headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
        assert response.headers.get("access-control-allow-origin") == (origin if origin.startswith("http://") else None)
