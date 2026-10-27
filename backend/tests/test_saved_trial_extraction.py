import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from backend.app import extraction, research_api, trial_extraction
from backend.app.extraction_source import ROOT
from backend.app.main import app

client = TestClient(app)
FIXTURES = Path(__file__).parent / "fixtures"
NCT_ID = "NCT00000001"


@pytest.fixture
def storage(monkeypatch):
    with TemporaryDirectory(dir=ROOT / "data/raw/trials") as temporary:
        root = Path(temporary)
        for name, timestamp in (("z_old", "2026-10-20T12:00:00Z"), ("a_latest", "2026-10-23T12:00:00Z")):
            path = root / name
            path.mkdir()
            (path / "response.json").write_bytes((FIXTURES / "extraction_snapshot.json").read_bytes())
            (path / "metadata.json").write_text(json.dumps({"retrieved_at": timestamp}))
        monkeypatch.setattr(research_api, "RAW_TRIALS_DIR", root)
        monkeypatch.setattr(extraction, "RESULTS_DIR", root / "results")
        def no_inference(*args, **kwargs):
            pytest.fail("Unexpected inference")
        monkeypatch.setattr(extraction, "chat_completion", no_inference)
        yield root


def source(snapshot=None):
    return client.get(f"/saved-trials/{NCT_ID}", params={"snapshot": snapshot} if snapshot else {})


def run(**body):
    return client.post(f"/saved-trials/{NCT_ID}/extractions", json=body)


def test_latest_dedup_uses_retrieval_timestamp_not_directory_order(storage):
    records = client.get("/research/trials").json()["trials"]
    assert len(records) == 1
    assert records[0]["snapshot"] == "a_latest/response.json"
    assert records[0]["snapshot_count"] == 2
    assert len(client.get("/research/trials?history=true").json()["trials"]) == 2
    assert source().json()["source"]["source_snapshot"].endswith("a_latest/response.json")
    historical = source("z_old/response.json").json()["source"]
    assert historical["retrieval_timestamp"] == "2026-10-20T12:00:00Z"
    assert historical["source_snapshot"].endswith("z_old/response.json")
    assert historical["sha256"] == hashlib.sha256((storage / "z_old/response.json").read_bytes()).hexdigest()


def test_source_selection_preserves_exact_text_identity_and_history(storage):
    result = source().json()
    payload = json.loads((storage / "a_latest/response.json").read_text())
    expected = payload["studies"][0]["protocolSection"]["eligibilityModule"]["eligibilityCriteria"]
    assert result["source"]["text"] == expected
    assert result["source"]["nct_id"] == NCT_ID
    assert result["source"]["source_url"] == f"https://clinicaltrials.gov/study/{NCT_ID}"
    assert len(result["snapshots"]) == 2


@pytest.mark.parametrize("snapshot", ["../response.json", "a_latest/../z_old/response.json", "D:/other/response.json"])
def test_snapshot_path_validation(storage, snapshot):
    assert source(snapshot).status_code == 422
    assert run(snapshot=snapshot).status_code == 422


def test_invalid_selection_hash_and_live_mode_are_rejected(storage):
    assert source("missing/response.json").status_code == 404
    assert client.get("/saved-trials/not-an-nct").status_code == 422
    assert client.get("/saved-trials/NCT99999999").status_code == 404
    assert run(snapshot_sha256="0" * 64).status_code == 409
    assert run(mode="live").status_code == 422
    assert run(patient_id="tnbc-complete").status_code == 422
    assert run(mock_version="invented").status_code == 422


def test_mock_preserves_source_spans_and_abstains_without_repair(storage):
    before = {str(path): path.read_bytes() for path in storage.glob("*/*.json")}
    response = run(snapshot="a_latest/response.json")
    assert response.status_code == 200
    result = response.json()
    assert result["manifest"]["mode"] == "mock"
    assert result["manifest"]["returned_model"] == "mock-no-model"
    assert result["manifest"]["status"] == "validation_failed"
    assert result["validated"] is None and result["assessment_allowed"] is False
    assert result["unsupported_criteria"]
    assert "unresolved_logical_operator" in {item["code"] for item in result["validation_errors"]}
    for node, evidence in zip(result["candidate"]["criteria"], result["candidate"]["evidence"]):
        span = evidence["original_span"]
        assert result["source"]["text"][span["start"]:span["end"]] == node["original_text"]
        assert node["logical_operator"] is None
        assert all(node[field] is None for field in ("comparator", "threshold", "unit", "biomarker", "cohort"))
    output = ROOT / result["output_directory"]
    assert json.loads((output / "source.json").read_text())["sha256"] == result["source"]["sha256"]
    assert (output / "prompt.json").exists() and (output / "raw_response.json").exists()
    second = run().json()
    assert second["output_directory"] != result["output_directory"]
    assert all(Path(name).read_bytes() == data for name, data in before.items())


def test_existing_validated_mock_schema_can_pass_without_authorizing_assessment(storage, monkeypatch):
    fixture = json.loads((FIXTURES / "extraction_mock.json").read_text())
    monkeypatch.setattr(trial_extraction, "mock_envelope", lambda selected: fixture)
    result = run().json()
    assert result["manifest"]["status"] == "validated"
    assert result["validation_errors"] == []
    assert result["validated"]["nct_id"] == NCT_ID
    assert result["validated"]["source_snapshot"] == result["source"]["source_snapshot"]
    assert result["assessment_allowed"] is False


@pytest.mark.parametrize("mutation,code", [("text", "unsupported_original_text"), ("malformed", "invalid_json_or_schema")])
def test_existing_validator_rejects_unsupported_claims_and_malformed_output(storage, monkeypatch, mutation, code):
    fixture = json.loads((FIXTURES / "extraction_mock.json").read_text())
    if mutation == "text":
        payload = json.loads(fixture["content"])
        payload["criteria"][0]["original_text"] = "Unsupported clinical claim"
        fixture["content"] = json.dumps(payload)
    else:
        fixture["content"] = "{invalid"
    monkeypatch.setattr(trial_extraction, "mock_envelope", lambda selected: fixture)
    result = run().json()
    assert result["validated"] is None
    assert code in {item["code"] for item in result["validation_errors"]}


def test_missing_timestamp_and_eligibility_are_explicit(storage):
    (storage / "a_latest/metadata.json").write_text("{}")
    assert source().json()["source"]["source_snapshot"].endswith("z_old/response.json")
    assert source("a_latest/response.json").json()["source"]["retrieval_timestamp"] is None
    (storage / "a_latest/response.json").write_text('{"studies": []}')
    assert source("a_latest/response.json").status_code == 422


def test_integration_artifacts_respect_existing_credential_echo_protection(storage, monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "Cohort A")
    response = run()
    assert response.status_code == 200
    result = response.json()
    assert result["manifest"]["status"] == "privacy_failed"
    assert result["source"] is None and result["candidate"] is None
    assert "Cohort A" not in response.text
    for path in (ROOT / result["output_directory"]).glob("*.json"):
        assert "Cohort A" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("case,expected", [
    ("success", "validated"), ("malformed", "validation_failed"),
    ("provider_failure", "failed"), ("timeout", "failed"), ("reasoning_limit", "failed"), ("invalid_credentials", "failed"),
    ("unsupported", "validation_failed"), ("credential_echo", "privacy_failed"),
    ("escaped_credential_echo", "privacy_failed"), ("wrong_model", "failed"),
])
def test_live_http_integration(storage, monkeypatch, case, expected):
    import httpx
    from backend.app import nebius

    monkeypatch.setenv("NEBIUS_API_KEY", "synthetic-integration-secret")
    monkeypatch.setenv("NEBIUS_MODEL", nebius.DEFAULT_MODEL)
    monkeypatch.setenv("NEBIUS_BASE_URL", nebius.REGIONAL_BASE_URL)
    monkeypatch.setenv("NEBIUS_LIVE_EXTRACTION", "1")
    monkeypatch.setenv("NEBIUS_INPUT_USD_PER_MILLION", "0.30")
    monkeypatch.setenv("NEBIUS_OUTPUT_USD_PER_MILLION", "0.90")
    monkeypatch.setattr(nebius, "LIVE_CLAIM", storage / "live.claim")
    monkeypatch.setattr(extraction, "chat_completion", nebius.chat_completion)
    fixture = json.loads((FIXTURES / "extraction_mock.json").read_text())
    content = fixture["content"]
    if case == "malformed":
        content = "{broken"
    elif case == "unsupported":
        payload = json.loads(content)
        payload["criteria"][0]["original_text"] = "Invented claim"
        content = json.dumps(payload)
    calls = []
    original_client = httpx.Client

    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        assert body["model"] == nebius.DEFAULT_MODEL
        assert body["max_tokens"] == 8192 and body["stream"] is False
        assert body["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
        assert request.extensions["timeout"]["read"] == 120
        assert json.loads(body["messages"][1]["content"])["eligibility_text"] == selected["text"]
        assert "synthetic-integration-secret" not in json.dumps(body)
        if case == "timeout":
            raise httpx.ReadTimeout("synthetic-integration-secret", request=request)
        if case in ("provider_failure", "invalid_credentials"):
            return httpx.Response(500 if case == "provider_failure" else 401, text="Provider rejected request")
        response = {"model": "other-model" if case == "wrong_model" else nebius.DEFAULT_MODEL,
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
            "extra": "synthetic-integration-secret" if case in ("credential_echo", "escaped_credential_echo") else None}
        if case == "reasoning_limit":
            response["choices"][0]["finish_reason"] = "length"
            response["choices"][0]["message"] = {"content": None, "reasoning": "Software-only reasoning", "refusal": None}
            response["usage"] = {"prompt_tokens": 939, "completion_tokens": 8192, "total_tokens": 9131,
                                 "completion_tokens_details": {"reasoning_tokens": 8192}}
        if case == "escaped_credential_echo":
            return httpx.Response(200, text=json.dumps(response).replace("synthetic-integration-secret", "synthetic\\u002dintegration\\u002dsecret"))
        return httpx.Response(200, json=response)

    monkeypatch.setattr(nebius.httpx, "Client", lambda **kw: original_client(transport=httpx.MockTransport(handler), **kw))
    selected = source().json()["source"]
    before = (storage / "a_latest/response.json").read_bytes()
    result = run(mode="live", live_approved=True, snapshot="a_latest/response.json", snapshot_sha256=selected["sha256"]).json()
    assert len(calls) == 1
    assert result["manifest"]["status"] == expected
    assert result["manifest"]["request_count"] == 1
    assert result["manifest"]["source_url"] == selected["source_url"]
    assert result["manifest"]["retrieval_timestamp"] == selected["retrieval_timestamp"]
    assert result["assessment_allowed"] is False
    assert "synthetic-integration-secret" not in json.dumps(result)
    if case == "success":
        assert result["manifest"]["usage"]["total_tokens"] == 300
        assert result["manifest"]["estimated_cost_usd"] == pytest.approx(0.00021)
        assert result["validated"] is not None
    if case == "timeout":
        assert result["manifest"]["returned_model"] is None
        assert result["manifest"]["usage"] is None
        assert result["manifest"]["estimated_cost_usd"] is None
        assert result["manifest"]["snapshot_sha256"] == selected["sha256"]
        assert result["manifest"]["human_review_required"] is True
        assert result["validated"] is None
        assert result["validation_errors"] == [{"code": "timeout", "message": nebius.TIMEOUT_MESSAGE}]
        claim_bytes = (storage / "live.claim").read_bytes()
    if case == "reasoning_limit":
        assert result["validation_errors"] == [{"code": "incomplete_response"}]
        assert result["validated"] is None and result["candidate"] is None
        assert result["manifest"]["returned_model"] == nebius.DEFAULT_MODEL
        assert result["manifest"]["usage"] == {"prompt_tokens": 939, "completion_tokens": 8192, "total_tokens": 9131}
    if case == "invalid_credentials":
        assert result["validation_errors"] == [{"code": "authentication_error"}]
    assert (storage / "a_latest/response.json").read_bytes() == before
    blocked = run(mode="live", live_approved=True, snapshot="a_latest/response.json", snapshot_sha256=selected["sha256"]).json()
    assert blocked["manifest"]["request_count"] == 0
    assert len(calls) == 1
    if case == "timeout":
        assert (storage / "live.claim").read_bytes() == claim_bytes


def test_safe_configuration_and_live_opt_in(storage, monkeypatch):
    from backend.app import nebius
    monkeypatch.setenv("NEBIUS_API_KEY", "synthetic-private-secret")
    monkeypatch.setenv("NEBIUS_MODEL", nebius.DEFAULT_MODEL)
    monkeypatch.setenv("NEBIUS_BASE_URL", nebius.BASE_URL)
    monkeypatch.delenv("NEBIUS_LIVE_EXTRACTION", raising=False)
    monkeypatch.setattr(nebius, "LIVE_CLAIM", storage / "live.claim")
    result = client.get("/saved-trials/configuration")
    assert result.json()["configured"] is True
    assert result.json()["ready"] is False
    assert "synthetic-private-secret" not in result.text
    selected = source().json()["source"]
    assert run(mode="live", snapshot="a_latest/response.json", snapshot_sha256=selected["sha256"]).status_code == 422
    blocked = run(mode="live", live_approved=True, snapshot="a_latest/response.json", snapshot_sha256=selected["sha256"]).json()
    assert blocked["manifest"]["request_count"] == 0
    assert not nebius.LIVE_CLAIM.exists()
