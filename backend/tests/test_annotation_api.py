import copy
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from backend.app import annotation_api as annotations
from backend.app.benchmark_models import ReferenceAnnotation, ReferenceCriterion
from backend.app.extraction_source import ROOT, EligibilitySource
from backend.app.main import app

client = TestClient(app)
NCT = "NCT01770353"


@pytest.fixture
def workspace(monkeypatch):
    with TemporaryDirectory(dir=ROOT / "cache") as temporary:
        monkeypatch.setattr(annotations, "STORAGE", Path(temporary) / "annotations")
        monkeypatch.setattr(annotations, "RESULTS", Path(temporary) / "evaluation")
        yield client.get(f"/annotations/{NCT}").json()


def body(workspace):
    source = workspace["source"]
    text = source["text"].splitlines()[0]
    ref = ReferenceAnnotation(nct_id=NCT, snapshot_sha256=source["sha256"], criteria=[ReferenceCriterion(
        reference_id="software-test-not-gold", original={"span": {"start": 0, "end": len(text)}, "text": text})])
    return {"snapshot": workspace["snapshots"][0]["snapshot"], "reference": ref.model_dump(mode="json"),
            "reviewer": "software-tester-a", "note": "Software regression only, not a human gold annotation"}


def save(request):
    return client.post(f"/annotations/{NCT}/versions", json=request)


def test_draft_export_import_edit_and_append_only_history(workspace):
    request = body(workspace)
    saved = save(request)
    assert saved.status_code == 200
    result = saved.json()
    version = result["bundle"]["audit"]["version"]
    again = client.get(f"/annotations/{NCT}/versions/{version}").json()
    assert again["export_json"] == result["export_json"]
    imported = client.post(f"/annotations/{NCT}/import", json=result["bundle"])
    assert imported.status_code == 200 and imported.json()["stage"] == "draft"
    assert imported.json()["reference"]["criteria"][0]["boundary_review"]["status"] == "unreviewed"
    request["parent"] = version
    assert save(request).status_code == 409
    request["reference"]["annotation_revision"] += 1
    request["reference"]["criteria"][0]["polarity"]["value"] = "inclusion"
    assert save(request).status_code == 200
    assert client.get(f"/annotations/{NCT}/versions/{version}").json() == again
    assert len(client.get(f"/annotations/{NCT}").json()["versions"]) == 2


def test_hash_snapshot_and_schema_mismatches(workspace):
    request = body(workspace)
    request["reference"]["snapshot_sha256"] = "0" * 64
    assert save(request).status_code == 409
    request = body(workspace)
    request["reference"]["criteria"][0]["original"]["text"] += "invented"
    assert save(request).status_code == 422
    request = body(workspace)
    request["reference"]["criteria"][0]["polarity"]["value"] = "positive"
    assert save(request).status_code == 422
    result = save(body(workspace)).json()["bundle"]
    result["source"]["sha256"] = "0" * 64
    assert client.post(f"/annotations/{NCT}/import", json=result).status_code == 409
    assert client.get('/annotations/NCT00000001').status_code == 404


def test_explicit_review_adjudication_and_evaluation_gating(workspace):
    request = body(workspace)
    draft = save(request).json()["bundle"]
    version = draft["audit"]["version"]
    assert client.post(f"/annotations/{NCT}/versions/{version}/evaluate", json={}).status_code == 409
    request.update(stage="reviewed", parent=version)
    request["reference"]["annotation_revision"] += 1
    assert save(request).status_code == 422
    request["approve_review"] = True
    assert save(request).status_code == 422
    reviewed = {"status": "reviewed", "reviewer": "software-tester-a", "reviewed_at": "2026-10-25T00:00:00Z", "note": "Software test, not clinical review"}
    request["reference"]["criteria"][0]["boundary_review"] = reviewed
    request["reference"]["inventory_review"] = reviewed
    accepted = save(request)
    assert accepted.status_code == 200, accepted.text
    version = accepted.json()["bundle"]["audit"]["version"]
    report = client.post(f"/annotations/{NCT}/versions/{version}/evaluate", json={})
    assert report.status_code == 200, report.text
    report = report.json()["report"]
    assert report["counts"]["unreviewed_inventory"] == 4
    assert report["counts"]["missing_prediction"] == 5
    assert report["counts"]["reviewed_boundaries"] == 1
    assert report["metrics"]["criterion_detection_f1"]["value"] is None
    assert report["counts"]["unreviewed_slots"] == len(annotations.SLOTS)
    other_nct = "NCT02648477"
    other_source = client.get(f"/annotations/{other_nct}").json()
    other_text = other_source["source"]["text"].splitlines()[0]
    other_reference = ReferenceAnnotation(nct_id=other_nct, snapshot_sha256=other_source["source"]["sha256"],
        inventory_review=reviewed, criteria=[ReferenceCriterion(reference_id="software-test-other-not-gold",
        boundary_review=reviewed, original={"span": {"start": 0, "end": len(other_text)}, "text": other_text})])
    other_saved = client.post(f"/annotations/{other_nct}/versions", json={
        "snapshot": other_source["snapshots"][0]["snapshot"], "reference": other_reference.model_dump(mode="json"),
        "reviewer": "software-tester-a", "note": "Software test only", "stage": "reviewed", "approve_review": True})
    assert other_saved.status_code == 200
    multiple = client.post(f"/annotations/{NCT}/versions/{version}/evaluate", json={
        "references": {other_nct: other_saved.json()["bundle"]["audit"]["version"]}})
    assert multiple.status_code == 200
    assert multiple.json()["report"]["counts"]["unreviewed_inventory"] == 3
    request.update(stage="adjudicated", parent=version)
    request["reference"]["annotation_revision"] += 1
    assert save(request).status_code == 422
    request["reviewer"] = "software-tester-b"
    adjudicated = save(request)
    assert adjudicated.status_code == 200
    assert adjudicated.json()["bundle"]["audit"]["stage"] == "adjudicated"
    imported = client.post(f"/annotations/{NCT}/import", json=adjudicated.json()["bundle"])
    assert imported.json()["stage"] == "draft"


def test_reviewed_values_require_evidence_and_absences_require_notes(workspace):
    request = body(workspace)
    label = request["reference"]["criteria"][0]["unit"]
    label.update(value=None, review={"status": "reviewed", "reviewer": "software-tester", "reviewed_at": "2026-10-25T00:00:00Z"})
    assert save(request).status_code == 422
    label["review"]["note"] = "Software test reviewed absence"
    assert save(request).status_code == 200
    label["value"] = "invented"
    assert save(request).status_code == 422


def test_unicode_source_spans_are_code_points(workspace, monkeypatch):
    text = "Software fixture ðŸ§¬\nÎ± â‰¥ 10 Î¼g; AND Î²\n"
    original = annotations.source_for(NCT)
    source = EligibilitySource(NCT, text, original.source_url, original.source_snapshot, original.retrieval_timestamp, None, original.sha256)
    monkeypatch.setattr(annotations, "source_for", lambda *args: source)
    request = body(workspace)
    start = text.index("Î±")
    request["reference"]["criteria"][0]["original"] = {"span": {"start": start, "end": start + 9}, "text": text[start:start + 9]}
    assert save(request).status_code == 200
    wrong = copy.deepcopy(request)
    wrong["reference"]["criteria"][0]["original"]["span"]["start"] += 1
    assert save(wrong).status_code == 422


def test_nested_logic_and_dependencies_use_existing_strict_schema(workspace):
    request = body(workspace)
    root = request["reference"]["criteria"][0]
    original = root["original"]
    end = original["span"]["end"]
    root["logic"]["value"] = {"operator": "AND", "span": original["span"], "children": [
        {"operator": "NONE", "span": {"start": 0, "end": end // 2}, "children": []}]}
    assert save(request).status_code == 422
    root["logic"]["value"]["children"].append({"operator": "NONE", "span": {"start": end // 2, "end": end}, "children": []})
    root["dependencies"] = [ReferenceCriterion(reference_id="child-software-test", original={
        "span": {"start": 0, "end": end // 2}, "text": original["text"][:end // 2]}).model_dump(mode="json")]
    assert save(request).status_code == 200
    root["dependencies"][0]["original"]["span"]["end"] = end + 1
    assert save(request).status_code == 422


def test_import_cannot_establish_adjudication_or_test_fixture_gold(workspace):
    request = body(workspace)
    request.update(stage="adjudicated", approve_review=True, reviewer="software-tester-b")
    assert save(request).status_code == 422
    request = body(workspace)
    request["reference"]["annotation_origin"] = "software_test_fixture"
    assert save(request).status_code == 422
    request = body(workspace)
    version = save(request).json()["bundle"]["audit"]["version"]
    assert client.post(f"/annotations/{NCT}/versions/{version}/evaluate", json={"references": {"NCT00000001": version}}).status_code == 409

@pytest.mark.parametrize('nct', ['NCT02648477', 'NCT01770353'])
def test_registered_workspace_and_all_saved_snapshots(nct):
    originals = {path: path.read_bytes() for path in annotations.research_api.RAW_TRIALS_DIR.rglob('*') if path.is_file()}
    assert '/annotations/{nct_id}' in client.get('/openapi.json').json()['paths']
    response = client.get(f'/annotations/{nct}')
    assert response.status_code == 200
    workspace = response.json()
    assert workspace['source']['nct_id'] == nct
    assert workspace['reference']['criteria'] == []
    assert workspace['reference']['inventory_review']['status'] == 'unreviewed'
    assert workspace['snapshots']
    for item in workspace['snapshots']:
        selected = client.get(f'/annotations/{nct}', params={'snapshot': item['snapshot']})
        assert selected.status_code == 200
        source = selected.json()['source']
        assert source['sha256'] == item['snapshot_sha256']
        assert source['source_snapshot'] == f"data/raw/trials/{item['snapshot']}"
        assert source['text']
    assert client.get(f'/annotations/{nct}', params={'snapshot': 'missing/response.json'}).status_code == 404
    assert client.get(f'/annotations/{nct}').status_code == 200
    assert all(path.read_bytes() == content for path, content in originals.items())


def test_unknown_study_and_wrong_api_prefix():
    response = client.get('/annotations/NCT00000001')
    assert response.status_code == 404
    assert response.json()['detail'] == 'Study outside saved benchmark'
    assert client.get('/api/annotations/NCT01770353').json() == {'detail': 'Not Found'}


def test_workspace_recovers_after_temporary_storage_failure(monkeypatch):
    original = annotations.select_source
    def unavailable(*args):
        from fastapi import HTTPException
        raise HTTPException(503, 'Temporary source failure')
    with monkeypatch.context() as patch:
        patch.setattr(annotations, 'select_source', unavailable)
        assert client.get(f'/annotations/{NCT}').status_code == 503
    assert annotations.select_source is original
    assert client.get(f'/annotations/{NCT}').status_code == 200


def test_candidate_drafts_save_without_review_promotion(workspace):
    assert workspace['candidates']
    selected = workspace['candidates'][:2]
    request = body(workspace)
    request['reference']['criteria'] = [ReferenceCriterion(reference_id=item['id'], original=item['original']).model_dump(mode='json') for item in selected]
    saved = save(request)
    assert saved.status_code == 200
    bundle = saved.json()['bundle']
    assert bundle['audit']['stage'] == 'draft'
    assert bundle['reference']['inventory_review']['status'] == 'unreviewed'
    assert all(item['boundary_review']['status'] == 'unreviewed' for item in bundle['reference']['criteria'])
    version = bundle['audit']['version']
    request['parent'] = version
    request['reference']['annotation_revision'] += 1
    request['reference']['criteria'].pop()
    assert save(request).status_code == 200
    assert len(client.get(f'/annotations/{NCT}/versions/{version}').json()['bundle']['reference']['criteria']) == 2
    assert client.post(f'/annotations/{NCT}/versions/{version}/evaluate', json={}).status_code == 409


def test_source_aligned_model_proposals_do_not_become_annotations(workspace, tmp_path, monkeypatch):
    import json
    from backend.app import extraction_alignment
    monkeypatch.setattr(extraction_alignment, "ALIGNMENTS", tmp_path)
    folder = tmp_path / "alignment"
    folder.mkdir()
    source = workspace["source"]
    original = workspace["candidates"][0]["original"]
    (folder / "manifest.json").write_text(json.dumps({"nct_id": source["nct_id"],
        "snapshot_sha256": source["sha256"], "source_snapshot": source["source_snapshot"]}), encoding="utf-8")
    row = {"candidate_id": workspace["candidates"][0]["id"], "clause": original,
           "criterion_id": "software-fixture-only", "status": "clinical_review",
           "proposal": {"original_text": "Software model proposal", "logical_operator": None}, "issues": []}
    (folder / "alignment_report.json").write_text(json.dumps({"entries": [row]}), encoding="utf-8")
    result = client.get(f"/annotations/{NCT}").json()
    assert result["extraction_proposals"] == [row]
    assert result["reference"]["criteria"] == []
    assert result["reference"]["inventory_review"]["status"] == "unreviewed"
