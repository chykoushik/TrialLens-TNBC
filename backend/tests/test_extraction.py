import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import pytest

from backend import extract_criteria
from backend.app import extraction
from backend.app.extraction_prompt import PROMPT_VERSION, build_messages
from backend.app.extraction_source import ROOT, load_source
from backend.app.extraction_validation import validate_extraction

FIXTURES = Path(__file__).parent / "fixtures"
TIMESTAMP = "2026-10-23T12:00:00Z"


@pytest.fixture
def extraction_case(monkeypatch):
    def no_network(**kwargs):
        pytest.fail("Unexpected network access")

    monkeypatch.setattr(httpx, "Client", no_network)
    directory = ROOT / "data" / "synthetic"
    with TemporaryDirectory(dir=directory) as temporary:
        path = Path(temporary)
        snapshot = path / "response.json"
        snapshot.write_bytes((FIXTURES / "extraction_snapshot.json").read_bytes())
        (path / "metadata.json").write_text(json.dumps({"retrieved_at": TIMESTAMP}), encoding="utf-8")
        mock = path / "mock.json"
        mock.write_bytes((FIXTURES / "extraction_mock.json").read_bytes())
        monkeypatch.setattr(extraction, "RESULTS_DIR", path / "results")
        source = load_source(snapshot, "NCT00000001")
        payload = json.loads(json.loads(mock.read_text(encoding="utf-8"))["content"])
        yield snapshot, mock, source, payload


def validate(payload, source):
    return validate_extraction(
        json.dumps(payload), source, method="synthetic-test", timestamp=TIMESTAMP,
    )


def test_validated_synthetic_extraction(extraction_case):
    snapshot, mock, source, payload = extraction_case
    result, errors = validate(payload, source)
    assert errors == []
    assert result.nct_id == "NCT00000001"
    assert result.is_synthetic is True
    assert result.original_text == source.text
    assert result.source_url == source.source_url
    assert result.source_snapshot == snapshot.relative_to(ROOT).as_posix()
    assert result.retrieval_timestamp.isoformat() == "2026-10-23T12:00:00+00:00"
    inclusion, exclusion = result.criteria
    assert inclusion.criterion_type == "inclusion"
    assert exclusion.criterion_type == "exclusion"
    assert inclusion.logical_operator == "AND"
    choice = inclusion.dependencies[1]
    assert choice.logical_operator == "OR"
    assay = choice.dependencies[0]
    assert assay.threshold == "10"
    assert assay.comparator == ">="
    assert assay.unit == "units"
    assert assay.temporal_constraint == "within 7 days"
    assert assay.cohort == "Cohort A"
    assert assay.biomarker is None
    assert assay.nct_id == result.nct_id
    assert assay.source_url == source.source_url
    output = extraction.extract_snapshot(snapshot, source.nct_id, mock_response=mock)
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["status"] == "validated"
    assert manifest["mode"] == "mock"
    assert manifest["requested_model"] == "mock-no-model"
    assert manifest["prompt_version"] == PROMPT_VERSION
    assert manifest["snapshot_sha256"] == source.sha256
    assert json.loads((output / "validation_errors.json").read_text()) == []
    assert json.loads((output / "validated.json").read_text())["criteria"][0]["cohort"] == "Cohort A"
    assert json.loads((output / "raw_response.json").read_text())["mock"] is True


@pytest.mark.parametrize("mutation, code", [
    ("polarity", "unsupported_polarity"),
    ("cohort", "unsupported_field"),
    ("lost_cohort", "lost_cohort_scope"),
    ("threshold", "unsupported_field"),
    ("temporal", "unsupported_field"),
    ("text", "unsupported_original_text"),
    ("logic", "unsupported_logical_structure"),
    ("flatten", "partial_top_level_line"),
    ("missing_evidence", "missing_evidence"),
    ("missing_criterion", "uncovered_source_text"),
    ("span", "unsupported_original_text"),
    ("missing_field", "schema_error"),
    ("missing_original", "schema_error"),
    ("invented_metadata", "schema_error"),
])
def test_unsupported_or_incomplete_extraction(extraction_case, mutation, code):
    _, _, source, original = extraction_case
    payload = copy.deepcopy(original)
    inclusion, exclusion = payload["criteria"]
    assay = inclusion["dependencies"][1]["dependencies"][0]
    if mutation == "polarity":
        exclusion["criterion_type"] = "inclusion"
    elif mutation == "cohort":
        inclusion["cohort"] = "Cohort Z"
    elif mutation == "lost_cohort":
        assay["cohort"] = None
    elif mutation == "threshold":
        assay["threshold"] = "99"
    elif mutation == "temporal":
        assay["temporal_constraint"] = "within 30 days"
    elif mutation == "text":
        exclusion["original_text"] = "Invented diagnosis"
    elif mutation == "logic":
        inclusion["logical_operator"] = "OR"
    elif mutation == "flatten":
        payload["criteria"] = inclusion["dependencies"] + [exclusion]
    elif mutation == "missing_evidence":
        payload["evidence"] = payload["evidence"][:-1]
    elif mutation == "missing_criterion":
        payload["criteria"] = [inclusion]
    elif mutation == "span":
        payload["evidence"][-1]["original_span"]["end"] = 99999
    elif mutation == "missing_field":
        del assay["threshold"]
    elif mutation == "missing_original":
        del exclusion["original_text"]
    elif mutation == "invented_metadata":
        exclusion["nct_id"] = "NCT99999999"
    result, errors = validate(payload, source)
    assert result is None
    assert code in {error["code"] for error in errors}


@pytest.mark.parametrize("content", [
    "not json", '```json\n{}\n```', '{}', '{"criteria": [], "criteria": [], "evidence": []}',
])
def test_malformed_model_output(extraction_case, content):
    snapshot, mock, source, _ = extraction_case
    mock.write_text(json.dumps({"mock": True, "content": content}), encoding="utf-8")
    output = extraction.extract_snapshot(snapshot, source.nct_id, mock_response=mock)
    assert json.loads((output / "validated.json").read_text()) is None
    assert json.loads((output / "validation_errors.json").read_text())
    assert json.loads((output / "raw_response.json").read_text())["content"] == content


def test_provenance_cannot_be_model_supplied(extraction_case):
    _, _, source, payload = extraction_case
    payload["source_url"] = "https://example.invalid"
    result, errors = validate(payload, source)
    assert result is None
    assert errors[0]["code"] == "schema_error"


def test_mock_runs_unique_and_cli(extraction_case):
    snapshot, mock, source, _ = extraction_case
    args = [str(snapshot), "--nct-id", source.nct_id, "--mock-response", str(mock)]
    assert extract_criteria.main(args) == 0
    assert extract_criteria.main(args + ["--mock"]) == 0
    assert len(list(extraction.RESULTS_DIR.iterdir())) == 2


def test_mock_requires_explicit_label(extraction_case):
    snapshot, mock, source, _ = extraction_case
    mock.write_text('{"content": "{}"}', encoding="utf-8")
    output = extraction.extract_snapshot(snapshot, source.nct_id, mock_response=mock)
    assert json.loads((output / "manifest.json").read_text())["status"] == "failed"


def test_client_reuse_with_stubbed_completion(extraction_case, monkeypatch):
    snapshot, _, source, payload = extraction_case
    monkeypatch.setenv("NEBIUS_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(extraction, "reserve_live_request", lambda: None)
    monkeypatch.setenv("NEBIUS_MODEL", "synthetic-nemotron-model")
    raw = json.dumps({"model": "synthetic-returned-model", "choices": [{"message": {"content": json.dumps(payload)}}]})

    def completion(messages, *, config, max_tokens, non_reasoning):
        assert non_reasoning is True
        assert config.model == "synthetic-nemotron-model"
        assert max_tokens == 8192
        assert source.text == json.loads(messages[1]["content"])["eligibility_text"]
        assert "synthetic-test-key" not in json.dumps(messages)
        return {
            "content": json.dumps(payload), "raw_response": raw,
            "requested_model": config.model, "returned_model": "synthetic-returned-model",
        }

    monkeypatch.setattr(extraction, "chat_completion", completion)
    output = extraction.extract_snapshot(snapshot, source.nct_id, mock=False, live_approved=True)
    assert (output / "raw_response.json").read_text() == raw
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["requested_model"] == "synthetic-nemotron-model"
    assert manifest["returned_model"] == "synthetic-returned-model"


def test_credential_echo_is_not_persisted(extraction_case, monkeypatch):
    snapshot, mock, source, _ = extraction_case
    monkeypatch.setenv("NEBIUS_API_KEY", "synthetic-secret-echo")
    fixture = json.loads(mock.read_text())
    fixture["extra"] = "synthetic-secret-echo"
    mock.write_text(json.dumps(fixture), encoding="utf-8")
    output = extraction.extract_snapshot(snapshot, source.nct_id, mock_response=mock)
    assert all("synthetic-secret-echo" not in path.read_text() for path in output.iterdir())
    assert json.loads((output / "manifest.json").read_text())["status"] == "privacy_failed"
    assert (output / "validated.json").read_text() == "null"


@pytest.mark.parametrize("mutation", ["missing_trial", "missing_text", "duplicate_trial", "unlabeled"])
def test_bad_snapshot(extraction_case, mutation):
    snapshot, _, _, _ = extraction_case
    payload = json.loads(snapshot.read_text())
    if mutation == "missing_trial":
        payload["studies"] = []
    elif mutation == "missing_text":
        del payload["studies"][0]["protocolSection"]["eligibilityModule"]
    elif mutation == "duplicate_trial":
        payload["studies"] *= 2
    else:
        del payload["is_synthetic"]
    snapshot.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        load_source(snapshot, "NCT00000001")


def test_source_paths_confined(extraction_case):
    with pytest.raises(ValueError):
        load_source(Path("../outside.json"), "NCT00000001")


def test_versioned_prompt(extraction_case):
    _, _, source, _ = extraction_case
    messages = build_messages(source)
    assert PROMPT_VERSION in messages[0]["content"]
    assert "untrusted data" in messages[0]["content"]
    assert "without Markdown" in messages[0]["content"]


@pytest.mark.parametrize("field, value, code", [
    ("threshold", "1", "partial_numeric_threshold"),
    ("comparator", ">", "partial_comparator"),
])
def test_partial_tokens_are_not_supported_claims(extraction_case, field, value, code):
    _, _, source, payload = extraction_case
    assay = payload["criteria"][0]["dependencies"][1]["dependencies"][0]
    assay[field] = value
    evidence = next(item for item in payload["evidence"] if item["criterion_id"] == assay["criterion_id"])
    evidence["fields"][field]["end"] = evidence["fields"][field]["start"] + len(value)
    result, errors = validate(payload, source)
    assert result is None
    assert code in {error["code"] for error in errors}


def test_provider_error_body_preserved_without_secret(extraction_case, monkeypatch):
    from backend.app.nebius import NebiusError

    snapshot, _, source, _ = extraction_case
    monkeypatch.setenv("NEBIUS_API_KEY", "synthetic-key")
    monkeypatch.setattr(extraction, "reserve_live_request", lambda: None)
    monkeypatch.setenv("NEBIUS_MODEL", "synthetic-model")

    def completion(*args, **kwargs):
        raise NebiusError("invalid_response", raw_response="mock malformed API body")

    monkeypatch.setattr(extraction, "chat_completion", completion)
    output = extraction.extract_snapshot(snapshot, source.nct_id, mock=False, live_approved=True)
    assert (output / "raw_response.json").read_text() == "mock malformed API body"
    assert json.loads((output / "validation_errors.json").read_text()) == [{"code": "invalid_response"}]
    assert json.loads((output / "validated.json").read_text()) is None


def test_unknown_values_are_not_filled(extraction_case):
    _, _, source, payload = extraction_case
    result, errors = validate(payload, source)
    assert errors == []
    exclusion = result.criteria[1]
    assert exclusion.cohort is None
    assert exclusion.threshold is None
    assert exclusion.assay is None
    assert exclusion.temporal_constraint is None


def test_unresolved_logic_requires_review(extraction_case):
    _, _, source, payload = extraction_case
    inclusion = payload["criteria"][0]
    inclusion["logical_operator"] = None
    inclusion["dependencies"] = None
    payload["evidence"] = [item for item in payload["evidence"]
                           if item["criterion_id"] in {"mock-inclusion", "mock-exclusion"}]
    result, errors = validate(payload, source)
    assert result is None
    assert "unresolved_compound_logic" in {error["code"] for error in errors}


def test_cli_does_not_allow_implicit_live(extraction_case):
    snapshot, _, source, _ = extraction_case
    with pytest.raises(SystemExit) as error:
        extract_criteria.main([str(snapshot), "--nct-id", source.nct_id])
    assert error.value.code == 2


def test_out_of_bounds_evidence_is_reported(extraction_case):
    _, _, source, payload = extraction_case
    entry = next(item for item in payload["evidence"] if item["criterion_id"] == "mock-inclusion")
    entry["original_span"] = {"start": 99999, "end": 100000}
    result, errors = validate(payload, source)
    assert result is None
    assert "unsupported_original_text" in {error["code"] for error in errors}


@pytest.mark.parametrize("suffix", [" unless reviewed", " except subgroup E", " if marker E present"])
def test_exception_cannot_pass_as_atomic(extraction_case, suffix):
    from dataclasses import replace
    _, _, source, payload = extraction_case
    source = replace(source, text=source.text + suffix)
    node = payload["criteria"][-1]
    node["original_text"] += suffix
    entry = next(item for item in payload["evidence"] if item["criterion_id"] == node["criterion_id"])
    entry["original_span"]["end"] += len(suffix)
    result, errors = validate(payload, source)
    assert result is None
    assert "unsupported_conditional_or_exception" in {error["code"] for error in errors}


def test_live_cli_requires_separate_manual_approval(extraction_case):
    snapshot, _, source, _ = extraction_case
    with pytest.raises(SystemExit) as error:
        extract_criteria.main([str(snapshot), "--nct-id", source.nct_id, "--live"])
    assert error.value.code == 2


def test_changed_source_prevents_inference(extraction_case):
    snapshot, _, source, _ = extraction_case
    output = extraction.extract_snapshot(snapshot, source.nct_id, mock=False,
                                         live_approved=True, expected_sha256="0" * 64)
    assert json.loads((output / "validation_errors.json").read_text()) == [{"code": "source_identity_changed"}]
    assert json.loads((output / "manifest.json").read_text())["request_count"] == 0


def test_live_cli_requires_pinned_snapshot(extraction_case):
    snapshot, _, source, _ = extraction_case
    with pytest.raises(SystemExit) as error:
        extract_criteria.main([str(snapshot), "--nct-id", source.nct_id, "--live", "--approve-one-live-request"])
    assert error.value.code == 2


def test_first_public_trial_prompt_contains_only_the_selected_study():
    snapshot = Path("data/raw/trials/20261023T203036640519Z_8ee2f270a09a4c6c86a684bd69e5cfb7/response.json")
    payload = json.loads((ROOT / snapshot).read_bytes())
    source = load_source(snapshot, "NCT01770353")
    selected = next(study for study in payload["studies"] if study["protocolSection"]["identificationModule"]["nctId"] == source.nct_id)
    sent = json.loads(build_messages(source)[1]["content"])
    assert sent == {"nct_id": source.nct_id, "eligibility_text": selected["protocolSection"]["eligibilityModule"]["eligibilityCriteria"]}
    assert len(payload["studies"]) == 5
    assert len(source.text) == 1674
    assert source.sha256 == "97584332c0329bca765d3d320e4d06ecce5711ac785603345c0402571add2060"


def test_non_reasoning_dry_run_is_key_free_and_never_reserves(extraction_case, monkeypatch, capsys):
    from backend.app import nebius
    snapshot, _, source, _ = extraction_case
    monkeypatch.setenv('NEBIUS_TIMEOUT_SECONDS', '120')
    def forbidden(*args, **kwargs):
        pytest.fail('Credential or reservation access')
    monkeypatch.setattr(nebius.NebiusConfig, 'from_environment', forbidden)
    monkeypatch.setattr(nebius, 'reserve_live_request', forbidden)
    monkeypatch.setattr(extraction, 'reserve_live_request', forbidden)
    assert extract_criteria.main([str(snapshot), '--nct-id', source.nct_id, '--dry-run', '--snapshot-sha256', source.sha256]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['request_sent'] is False
    assert result['automatic_retries'] == 0 and result['timeout_seconds'] == 120
    assert result['request_body']['extra_body'] == {'chat_template_kwargs': {'enable_thinking': False}}
    assert result['request_body']['messages'] == build_messages(source)
    assert result['request_body']['max_tokens'] == 8192
    assert 'Authorization' not in json.dumps(result)
    assert not extraction.RESULTS_DIR.exists()
    with pytest.raises(SystemExit):
        extract_criteria.main([str(snapshot), '--nct-id', source.nct_id, '--dry-run', '--live'])
