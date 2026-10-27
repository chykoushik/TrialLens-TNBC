import copy
import json
from dataclasses import replace

from backend.app import extraction_alignment as alignment
from backend.app.extraction_source import EligibilitySource
from backend.app.extraction_validation import validate_extraction
from backend.app.extraction_prompt import CLINICAL_FIELDS

TIMESTAMP = "2026-10-26T00:00:00Z"


def case(quotation="ECOG \U0001f9ec \u2264 1", text=None):
    text = text or "Inclusion Criteria:\n\n* " + quotation
    source = EligibilitySource("NCT00000001", text, "https://clinicaltrials.gov/study/NCT00000001",
                               "data/synthetic/response.json", TIMESTAMP, True, "a" * 64)
    node = dict.fromkeys(CLINICAL_FIELDS)
    node.update(criterion_id="c1", original_text=quotation, criterion_type="inclusion", logical_operator="NONE")
    payload = {"criteria": [node], "evidence": [{"criterion_id": "c1", "original_span": {"start": 1, "end": 2},
                                                "polarity_span": {"start": 1, "end": 2}, "fields": {}}]}
    return source, payload


def test_unicode_offsets_and_formatting_only_expansion():
    source, payload = case()
    before = copy.deepcopy(payload)
    candidate, report = alignment.align(payload, source, TIMESTAMP)
    assert payload == before
    assert report["counts"] == {"automatically_recovered": 1}
    entry = candidate["evidence"][0]
    assert source.text[entry["original_span"]["start"]:entry["original_span"]["end"]] == candidate["criteria"][0]["original_text"]
    assert candidate["criteria"][0]["original_text"].startswith("* ")
    result, errors = validate_extraction(json.dumps(candidate), source, method="offline-test", timestamp=TIMESTAMP)
    assert result is not None and not errors


def test_wrapped_whitespace_preserves_source_characters():
    source, payload = case("ECOG score 1", "Inclusion Criteria:\n* ECOG  score\n  1")
    candidate, report = alignment.align(payload, source, TIMESTAMP)
    assert report["counts"] == {"automatically_recovered": 1}
    assert candidate["criteria"][0]["original_text"] == "* ECOG  score\n  1"


def test_ambiguous_missing_and_incomplete_qualification():
    for text, quote, status in [
        ("Inclusion Criteria:\n* ECOG 1\n* ECOG 1", "ECOG 1", "ambiguous_match"),
        ("Inclusion Criteria:\n* ECOG 1", "ECOG 2", "missing_match"),
        ("Inclusion Criteria:\n* ECOG 1 unless unstable", "ECOG 1", "boundary_review"),
    ]:
        source, payload = case(quote, text)
        candidate, report = alignment.align(payload, source, TIMESTAMP)
        assert report["entries"][0]["status"] == status
        assert candidate == payload


def test_scope_polarity_and_unresolved_logic_are_not_repaired():
    for updates in ({"cohort": "all subjects"}, {"criterion_type": "exclusion"},
                    {"logical_operator": None}):
        source, payload = case()
        payload["criteria"][0].update(updates)
        candidate, report = alignment.align(payload, source, TIMESTAMP)
        assert candidate == payload
        assert report["counts"] == {"clinical_review": 1}
    source, payload = case("A or B")
    candidate, report = alignment.align(payload, source, TIMESTAMP)
    assert candidate == payload
    assert report["entries"][0]["issues"][0]["code"] == "unresolved_compound_logic"


def test_matching_does_not_normalize_symbols_or_invent_fields():
    source, payload = case("ECOG <= 1", "Inclusion Criteria:\n* ECOG \u2264 1")
    candidate, report = alignment.align(payload, source, TIMESTAMP)
    assert candidate == payload
    assert report["counts"] == {"missing_match": 1}


def test_review_proposals_require_matching_snapshot_and_exact_clause(tmp_path, monkeypatch):
    source, payload = case()
    _, report = alignment.align(payload, source, TIMESTAMP)
    monkeypatch.setattr(alignment, "ALIGNMENTS", tmp_path)
    folder = tmp_path / "derived"
    folder.mkdir()
    manifest = {"nct_id": source.nct_id, "snapshot_sha256": source.sha256, "source_snapshot": source.source_snapshot}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "alignment_report.json").write_text(json.dumps(report), encoding="utf-8")
    assert len(alignment.review_proposals(source)) == 1
    assert alignment.review_proposals(replace(source, sha256="b" * 64)) == []
    report["entries"][0]["clause"]["text"] = "Invented"
    (folder / "alignment_report.json").write_text(json.dumps(report), encoding="utf-8")
    assert alignment.review_proposals(source) == []


def test_saved_third_extraction_only_recovers_five_source_valid_entries():
    import hashlib
    from pathlib import Path
    from backend.recover_extraction import normalize_evidence
    from backend.app.extraction_source import ROOT, load_source
    directory = ROOT / "results/extraction/20261026T001316900955Z_91c45c376f604f17a6a2bdc48dce58f2"
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()}
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    source = load_source(Path(manifest["source_snapshot"]), manifest["nct_id"])
    assert source.sha256 == manifest["snapshot_sha256"]
    raw = json.loads((directory / "raw_response.json").read_text(encoding="utf-8"))
    payload, _ = normalize_evidence(json.loads(raw["choices"][0]["message"]["content"]))
    candidate, report = alignment.align(payload, source, TIMESTAMP)
    assert report["counts"] == {"clinical_review": 18, "boundary_review": 1, "automatically_recovered": 5}
    assert all(row["match_count"] == 1 for row in report["entries"])
    result, errors = validate_extraction(json.dumps(candidate), source, method="offline-test", timestamp=TIMESTAMP)
    assert result is None and len(errors) == 39
    for old, new in zip(payload["criteria"], candidate["criteria"]):
        assert {k: v for k, v in old.items() if k != "original_text"} == {k: v for k, v in new.items() if k != "original_text"}
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()}
