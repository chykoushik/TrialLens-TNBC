import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import extraction, research_api, trial_analysis
from backend.app.extraction_source import ROOT
from backend.app.main import app
from backend.app.paper_planner import Request, cases, evaluate
from backend.app.research_catalog import ARTIFACTS

client = TestClient(app)


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.delenv("TRIALLENS_PUBLIC_DEMO", raising=False)
    monkeypatch.setattr(extraction, "chat_completion", lambda *a, **k: pytest.fail("Paid transport forbidden"))
    with TemporaryDirectory(dir=ROOT / "data/raw/trials") as temporary:
        root = Path(temporary)
        monkeypatch.setattr(research_api, "RAW_TRIALS_DIR", root)
        payload = json.loads((Path(__file__).parent / "fixtures/extraction_snapshot.json").read_text())
        payload.pop("is_synthetic", None)
        calls = []
        def get(self, url, params):
            calls.append(params)
            return httpx.Response(200, json={**payload, "totalCount": 12, "nextPageToken": "cursor"}, request=httpx.Request("GET", url))
        class Provider:
            def __init__(self, **kwargs):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        Provider.get = get
        monkeypatch.setattr(trial_analysis, "Client", Provider)
        yield root, payload, calls


def test_search_persists_source_and_reuses_identical_snapshots(registry):
    root, payload, calls = registry
    first = client.get("/clinical-trials/search", params={"condition": "software fixture"}).json()
    trial = first["trials"][0]
    assert first["next_page_token"] == "cursor" and calls[0]["query.cond"] == "software fixture"
    raw = (root / trial["snapshot"]).read_bytes()
    assert trial["snapshot_sha256"] == hashlib.sha256(raw).hexdigest()
    assert trial["eligibility_criteria"] == payload["studies"][0]["protocolSection"]["eligibilityModule"]["eligibilityCriteria"]
    assert client.get("/clinical-trials/search", params={"condition": "software fixture", "page_token": "cursor"}).status_code == 200
    assert len(list(root.glob("*/response.json"))) == 1
    assert calls[-1]["pageToken"] == "cursor"
    assert client.get("/clinical-trials/search", params={"nct_id": trial["nct_id"]}).json()["origin"] == "Saved registry snapshot"
    assert len(calls) == 2


def test_analysis_is_read_only_source_scoped_and_cannot_assess_patient(registry):
    trial = client.get("/clinical-trials/search", params={"intervention": "software fixture"}).json()["trials"][0]
    params = {"snapshot": trial["snapshot"], "snapshot_sha256": trial["snapshot_sha256"]}
    first = client.get(f'/clinical-trials/{trial["nct_id"]}/analysis', params=params)
    assert first.status_code == 200
    value = first.json()
    assert not value["assessment_available"] and not value["inference"]["request_sent"]
    assert value["patient_evidence"] == [] and not value["planning"]["available"]
    assert client.get(f'/clinical-trials/{trial["nct_id"]}/analysis', params=params).json() == value
    params["snapshot_sha256"] = "0" * 64
    assert client.get(f'/clinical-trials/{trial["nct_id"]}/analysis', params=params).status_code == 409


def test_invalid_search_and_source_errors_are_explicit(registry, monkeypatch):
    assert client.get("/clinical-trials/search").status_code == 422
    assert client.get("/clinical-trials/search", params={"nct_id": "../private"}).status_code == 422
    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("fixture")
    monkeypatch.setattr(trial_analysis.Client, "get", timeout)
    assert client.get("/clinical-trials/search", params={"keywords": "fixture"}).status_code == 504


def test_exact_planner_obeys_budget_risk_and_actual_report_branch():
    identifier = cases()[0]["id"]
    initial = evaluate(Request(scenario=identifier, budget=1))
    assert initial["expected_policy_metrics"]["max_model_risk"] <= .08 + 1e-8
    assert initial["numerical_gap"] <= 1e-8
    assert initial["bdd_nodes"] > 2
    chosen = next(report for report in initial["reports"] if report["selection_probability"] > 0)
    updated = evaluate(Request(scenario=identifier, budget=1, outcomes={chosen["id"]: 1}))
    assert updated["spent"] == chosen["cost"] and updated["stop_probability"] == pytest.approx(1)
    assert updated["protocol_probabilities"] != initial["protocol_probabilities"]
    no_budget = evaluate(Request(scenario=identifier, budget=0))
    assert no_budget["stop_probability"] == pytest.approx(1)
    assert all(report["selection_probability"] == 0 for report in no_budget["reports"])


def test_aggregate_allowlist_loads_all_sources_and_blocks_arbitrary_paths():
    for identifier in ARTIFACTS:
        response = client.get(f"/research/evaluation/{identifier}")
        assert response.status_code == 200, identifier
        assert response.json()["sha256"]
    assert client.get("/research/evaluation/private-patient-records").status_code == 404
    registry = client.get("/research/evaluation/registry", params={"limit": 2}).json()
    assert len(registry["rows"]) == 2 and registry["total"] > 8000


def test_operator_raw_outputs_and_grant_status_require_authentication(monkeypatch):
    monkeypatch.setenv("TRIALLENS_OPERATOR_TOKEN", "software-test-operator-0123456789abcdef")
    for path in ("/operator/session", "/saved-trials/NCT04331067/inference", "/saved-trials/NCT04331067/inference/example", "/saved-trials/NCT04331067/authorization-quote"):
        assert client.get(path).status_code == 401
