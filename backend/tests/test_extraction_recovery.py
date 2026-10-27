import copy
import json
from pathlib import Path

import pytest

from backend import recover_extraction as recovery
from backend.tests.test_extraction import extraction_case
from backend.app.extraction_validation import validate_extraction


def test_null_evidence_normalization(extraction_case):
    _, _, source, payload = extraction_case
    original = copy.deepcopy(payload)
    payload["evidence"][0].update(logical_operator=None, dependencies=None)
    candidate, changes = recovery.normalize_evidence(payload)
    assert candidate == original
    assert len(changes) == 2
    assert "logical_operator" in payload["evidence"][0]
    result, errors = validate_extraction(json.dumps(candidate), source,
        method="offline-test", timestamp="2026-10-26T00:00:00Z")
    assert result is not None and not errors


@pytest.mark.parametrize("field,value", [("logical_operator", "OR"), ("dependencies", []),
                                         ("unexpected", None)])
def test_non_null_or_unknown_extras_rejected(extraction_case, field, value):
    _, _, source, payload = extraction_case
    payload["evidence"][0][field] = value
    candidate, _ = recovery.normalize_evidence(payload)
    result, errors = validate_extraction(json.dumps(candidate), source,
        method="offline-test", timestamp="2026-10-26T00:00:00Z")
    assert result is None
    assert any(e["field"] == f"evidence.0.{field}" for e in errors)


def test_recovery_preserves_originals_and_rejects_bad_spans(extraction_case, tmp_path, monkeypatch):
    _, _, source, payload = extraction_case
    monkeypatch.setattr(recovery, "ROOT", tmp_path)
    monkeypatch.setattr(recovery, "load_source", lambda *args: source)
    directory = tmp_path / "results/extraction/attempt"
    directory.mkdir(parents=True)
    payload["evidence"][0].update(logical_operator=None, dependencies=None)
    payload["evidence"][0]["original_span"]["start"] += 1
    manifest = {"source_snapshot": source.source_snapshot, "snapshot_sha256": source.sha256,
                "nct_id": source.nct_id}
    raw = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(payload)}}]}
    for name, value in (("manifest.json", manifest), ("raw_response.json", raw)):
        (directory / name).write_text(json.dumps(value), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    destination, report, errors = recovery.recover(directory)
    assert report["status"] == "validation_failed"
    assert report["human_review_required"] is True
    assert report["request_count"] == 0
    assert json.loads((destination / "validated.json").read_text()) is None
    assert any(e["code"] == "unsupported_original_text" for e in errors)
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}
    manifest["snapshot_sha256"] = "0" * 64
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        recovery.recover(directory)
    manifest["snapshot_sha256"] = source.sha256
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    raw["choices"][0]["finish_reason"] = "length"
    (directory / "raw_response.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="Incomplete"):
        recovery.recover(directory)


def test_normalization_preserves_unicode_and_unresolved_logic():
    payload = {"criteria": [{"original_text": "Received \u2264 5 therapies", "logical_operator": None,
                             "dependencies": None}],
               "evidence": [{"criterion_id": "c1", "logical_operator": None, "dependencies": None,
                             "original_span": {"start": 4, "end": 26}, "fields": {}}]}
    candidate, changes = recovery.normalize_evidence(payload)
    assert candidate["criteria"] == payload["criteria"]
    assert candidate["evidence"][0]["original_span"] == payload["evidence"][0]["original_span"]
    assert len(changes) == 2
