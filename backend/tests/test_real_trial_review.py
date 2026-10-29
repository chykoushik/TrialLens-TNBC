from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app import real_trial_review as module
from backend.app.benchmark_models import ReferenceAnnotation, ReferenceCriterion, Quote, Review
from backend.app.extraction_validation import Span
from backend.app.trial_extraction_api import select_source

client = TestClient(app)
IDS = ['NCT01770353', 'NCT02648477', 'NCT03538028', 'NCT04331067', 'NCT04691375']


@pytest.mark.parametrize('nct_id', IDS)
def test_real_sources_preserve_text_and_never_invent_patient_or_plan(nct_id):
    source = select_source(nct_id)
    response = client.get(f'/research/trials/{nct_id}/review', params={'snapshot_sha256': source.sha256})
    assert response.status_code == 200
    value = response.json()
    assert value['source']['text'] == source.text
    assert value['source']['source_url'] == f'https://clinicaltrials.gov/study/{nct_id}'
    assert value['patient_evidence'] == []
    assert not value['assessment_available'] and not value['complete_eligibility_available']
    assert not value['planning']['available'] and value['planning']['selected_reports'] == []
    assert value['executable_mapping_count'] == 0
    for passage in value['source_passages']:
        assert source.text[passage['span']['start']:passage['span']['end']] == passage['text']
        assert passage['state'] == 'unknown'


def test_changed_source_and_invalid_identity_are_blocked():
    assert client.get('/research/trials/NCT01770353/review', params={'snapshot_sha256': '0' * 64}).status_code == 409
    assert client.get('/research/trials/invalid/review').status_code == 422
    assert client.get('/research/trials/NCT99999999/review').status_code == 404
    assert client.post('/research/trials/NCT01770353/review', json={'patient': {}}).status_code == 405


def test_fictional_source_cannot_enter_real_review(monkeypatch):
    source = replace(select_source('NCT01770353'), is_synthetic=True)
    monkeypatch.setattr(module, 'select_source', lambda *args: source)
    assert client.get('/research/trials/NCT01770353/review').status_code == 422


def test_source_boundary_review_is_not_executable_mapping_approval(tmp_path, monkeypatch):
    source = select_source('NCT01770353')
    clause = module.candidate_clauses(source.text)[0]['original']
    reference = ReferenceAnnotation(nct_id=source.nct_id, snapshot_sha256=source.sha256, criteria=[
        ReferenceCriterion(reference_id='boundary-test', original=Quote(text=clause['text'], span=Span(**clause['span'])),
                           boundary_review=Review(status='reviewed', reviewer='unit-test reviewer', reviewed_at='2026-10-28T00:00:00Z'))])
    directory = tmp_path / source.nct_id
    directory.mkdir()
    path = directory / 'reference.json'
    path.write_text(reference.model_dump_json(), encoding='utf-8')
    monkeypatch.setattr(module, 'REFERENCES', tmp_path)
    value = module.review(source.nct_id, None, source.sha256)
    assert len(value['reviewed_source_criteria']) >= 1
    assert all(not row['executable'] for row in value['reviewed_source_criteria'])
    assert value['executable_mapping_count'] == 0 and not value['assessment_available']
    reference.snapshot_sha256 = '0' * 64
    path.write_text(reference.model_dump_json(), encoding='utf-8')
    assert module.review(source.nct_id, None, source.sha256)['reviewed_source_criteria'] == []
