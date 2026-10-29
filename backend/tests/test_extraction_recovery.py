import hashlib
import json
from pathlib import Path

import httpx
import pytest

from backend.app import nebius
from backend.app.extraction_recovery import recover_truncated_criteria
from backend.app.extraction_source import ROOT, load_source
from backend.app.extraction_validation import validate_extraction
from backend.app.inference_review import report_for
from backend.app.trial_extraction import extraction_report

ATTEMPT = ROOT / "results/extraction/20261029T000537077640Z_f0f39c0f41224168a9120332d84ec55f"


@pytest.fixture
def saved(monkeypatch):
    if not ATTEMPT.is_dir():
        pytest.skip("Private saved provider artifact not distributed")
    def forbidden(*args, **kwargs):
        pytest.fail("Network and reservation prohibited")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(nebius, "reserve_live_request", forbidden)
    monkeypatch.setattr("backend.extraction_authorization.reserve_authorized_request", forbidden)
    paths = list(ATTEMPT.glob("*")) + list((ROOT / "results/nebius/authorizations").glob("*")) + [ROOT / "results/nebius/live-request.claim"]
    manifest = json.loads((ATTEMPT / "manifest.json").read_text())
    source = load_source(Path(manifest["source_snapshot"]), manifest["nct_id"])
    paths.append(ROOT / manifest["source_snapshot"])
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}
    raw = json.loads((ATTEMPT / "raw_response.json").read_text(encoding="utf-8"))
    yield source, manifest, raw
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}


def test_private_saved_response_is_truncated_not_reasoning_or_parser_rejection(saved, monkeypatch):
    source, manifest, raw = saved
    choice = raw["choices"][0]
    assert choice["finish_reason"] == "length"
    assert raw["usage"]["completion_tokens"] == 8192
    assert raw["usage"]["completion_tokens_details"]["reasoning_tokens"] == 0
    assert manifest["estimated_cost_usd"] == .00813
    content = choice["message"]["content"]
    with pytest.raises(json.JSONDecodeError, match="Unterminated string"):
        json.loads(content)
    model, errors = validate_extraction(content, source, method="offline-original", timestamp=manifest["timestamp"])
    assert model is None and errors[0]["code"] == "invalid_json_or_schema"
    response = httpx.Response(200, content=(ATTEMPT / "raw_response.json").read_bytes(), request=httpx.Request("POST", "https://example.invalid"))
    monkeypatch.setattr(httpx.Client, "post", lambda *a, **k: response)
    with pytest.raises(nebius.NebiusError) as failure:
        nebius.chat_completion([], config=nebius.NebiusConfig(api_key="synthetic-provider-secret", model=manifest["requested_model"], base_url=nebius.BASE_URL), max_tokens=8192)
    assert failure.value.code == "incomplete_response"


def test_private_saved_prefix_recovery_preserves_objects_and_rejects_execution(saved):
    source, manifest, raw = saved
    content = raw["choices"][0]["message"]["content"]
    result = recover_truncated_criteria(content, source, finish_reason="length", timestamp=manifest["timestamp"])
    assert result["complete_top_level_objects"] == 23
    assert result["complete_nodes_including_dependencies"] == 56
    assert result["exact_source_top_level_objects"] == 21
    assert result["exact_source_nodes"] == 39
    assert not result["complete_extraction"] and not result["assessment_allowed"]
    assert not result["provider_evidence_recovered"]
    assert {row["code"] for row in result["prefix_validation_errors"]} == {"missing_evidence", "uncovered_source_text"}
    for item in result["objects"]:
        span = item["response_span"]
        assert json.loads(content[span["start"]:span["end"]]) == item["candidate"]
        for check in item["source_checks"]:
            assert check["span_origin"] == "offline_exact_text_search_not_provider_evidence"
            assert not check["executable"]
    assert result["objects"][-1]["candidate"]["criterion_id"] == "NCT04331067_EXC_010"
    assert "NCT04331067_EXC_011" not in json.dumps(result["objects"])


def test_read_only_operator_report_recovers_without_promoting_partial_candidate(saved):
    source, manifest, _ = saved
    result = extraction_report(source, ATTEMPT, persist=False)
    assert result["manifest"]["status"] == "failed" and result["candidate"] is None and result["validated"] is None
    assert result["unsupported_criteria"] == [{"criterion_id": None, "reason": "incomplete_provider_response"}]
    assert result["partial_recovery"]["complete_top_level_objects"] == 23
    _, report, model = report_for(manifest["nct_id"], ATTEMPT.name)
    assert not report["review_checks_passed"] and model is None


@pytest.mark.parametrize("content", ['{"evidence": [], "criteria": [{"original_text":"x"}', 'commentary {"criteria": [{"original_text":"x"}', '{"criteria":[{"original_text":"x","original_text":"y"}'])
def test_recovery_does_not_scan_commentary_reorder_or_accept_duplicate_keys(saved, content):
    source, manifest, _ = saved
    result = recover_truncated_criteria(content, source, finish_reason="length", timestamp=manifest["timestamp"])
    assert result is None or result["complete_top_level_objects"] == 0


@pytest.mark.parametrize("reason", ["stop", "content_filter", None])
def test_recovery_requires_explicit_output_limit(saved, reason):
    source, manifest, raw = saved
    assert recover_truncated_criteria(raw["choices"][0]["message"]["content"], source, finish_reason=reason, timestamp=manifest["timestamp"]) is None
