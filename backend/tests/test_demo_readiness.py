import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from backend.app.demo_session import fixture_hash
from backend.app.main import app
from backend.app.tnbc_demo import tnbc_cases
from backend.readiness import ROOT, check

client = TestClient(app)


def session():
    case = next(c for c in tnbc_cases() if c.case_id == "tnbc-record-gaps")
    return {"version": 1, "kind": "fictional-tnbc-demo", "savedAt": int(time.time() * 1000), "fixtureHash": fixture_hash(case.model),
            "caseId": case.case_id, "step": 4, "algorithm": "adaptive_replan", "budget": "3",
            "outcomes": {"review-germline-report": "brca1-pathogenic"}, "drafts": {"review-pdl1-report": "cps-15"}}


def test_restore_replays_against_immutable_fixture_without_duplicate_spending():
    before = [c.model.model_dump_json() for c in tnbc_cases()]
    value = session()
    for _ in range(2):
        response = client.post("/tnbc/session/restore", json=value)
        assert response.status_code == 200
        assert response.json() == {"session": value, "validated": True}
    evaluated = client.post("/tnbc/cases/tnbc-record-gaps/evaluate", json={"algorithm": value["algorithm"], "budget": "3", "outcomes": value["outcomes"]}).json()
    assert [evaluated["spent"], evaluated["remaining_budget"]] == ["2", "1"]
    assert evaluated["demo_fixture_sha256"] == value["fixtureHash"]
    assert before == [c.model.model_dump_json() for c in tnbc_cases()]


@pytest.mark.parametrize("change", [
    {"version": 0}, {"kind": "real-patient"}, {"caseId": "NCT01770353"}, {"fixtureHash": "0" * 64},
    {"budget": "1"}, {"budget": "NaN"}, {"budget": "101"}, {"step": 5}, {"algorithm": "unknown"},
    {"outcomes": {"forged": "positive"}}, {"outcomes": {"review-germline-report": "invented"}},
    {"drafts": {"review-germline-report": "brca1-pathogenic"}}, {"patient": {"name": "forbidden"}},
    {"algorithm": "joint_greedy"}, {"savedAt": 0},
])
def test_restore_rejects_inconsistent_or_nonfictional_state(change):
    assert client.post("/tnbc/session/restore", json={**session(), **change}).status_code in (409, 422)


def test_readiness_is_offline_secret_safe_and_optional_files_are_nonblocking(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "software-test-secret")
    with patch("httpx.Client.send", side_effect=AssertionError("Network forbidden")):
        result = check()
    assert result["offline_ready"]
    assert "software-test-secret" not in str(result)
    with TemporaryDirectory(dir=ROOT / "cache") as temporary:
        missing = check(Path(temporary))
    assert not missing["offline_ready"]
    assert next(c for c in missing["checks"] if c["name"] == "optional_benchmark_sources")["required"] is False
    assert next(c for c in result["checks"] if c["name"] == "backend_routes")["status"] == "pass"


def test_public_demo_blocks_provider_writes_and_retrieval_without_network(monkeypatch):
    monkeypatch.setenv("TRIALLENS_PUBLIC_DEMO", "1")
    for method, path in (("GET", "/trials"), ("POST", "/saved-trials/NCT01770353/extractions"),
                         ("GET", "/annotations/NCT01770353"), ("POST", "/annotations/NCT01770353/versions")):
        assert client.request(method, path, json={}).status_code == 403
    assert client.get("/health").status_code == 200
    assert client.post("/tnbc/session/restore", json=session()).status_code == 200


def test_smoke_exercises_real_fictional_calculations_without_external_requests():
    from backend.demo_smoke import smoke
    assert smoke()["transitions"] == [
        {"spent": "0", "remaining": "3", "uncertainty": "2"},
        {"spent": "2", "remaining": "1", "uncertainty": "1"},
        {"spent": "3", "remaining": "0", "uncertainty": "0"}]


def test_optional_artifacts_do_not_block_ready_required_environment(monkeypatch):
    from backend.app.eligibility_benchmark import TRIAL_IDS
    monkeypatch.setattr("backend.readiness.catalog", lambda path: ([{"nct_id": nct, "is_synthetic": False} for nct in TRIAL_IDS], []))
    with TemporaryDirectory(dir=ROOT / "cache") as temporary:
        root = Path(temporary)
        for name in ("frontend/src/App.tsx", "frontend/package-lock.json", "frontend/vite.config.ts", "frontend/node_modules/vite/package.json"):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}")
        assert check(root)["offline_ready"]
        monkeypatch.setenv("VITE_API_BASE_URL", "https://demo:software-secret@example.invalid")
        result = check(root)
        assert not result["offline_ready"]
        assert "software-secret" not in str(result)
