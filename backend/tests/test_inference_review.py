import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from backend.app import extraction, inference_review, nebius, research_api
from backend.app.extraction_source import ROOT
from backend.app.inference_access import operator_status
from backend.app.main import app

client = TestClient(app)
TOKEN = 'test-operator-access-code-0123456789abcdef'
HEADERS = {'Authorization': f'Bearer {TOKEN}'}
FIXTURES = Path(__file__).parent / 'fixtures'
NCT = 'NCT00000001'


@pytest.fixture
def saved(monkeypatch, tmp_path):
    monkeypatch.setenv('TRIALLENS_OPERATOR_TOKEN', TOKEN)
    monkeypatch.setenv('NEBIUS_MAX_REQUEST_USD', '1')
    monkeypatch.setenv('NEBIUS_API_KEY', 'synthetic-provider-secret')
    monkeypatch.setenv('NEBIUS_MODEL', nebius.DEFAULT_MODEL)
    monkeypatch.setenv('NEBIUS_LIVE_EXTRACTION', '1')
    monkeypatch.setenv('NEBIUS_INPUT_USD_PER_MILLION', '0.3')
    monkeypatch.setenv('NEBIUS_OUTPUT_USD_PER_MILLION', '0.9')
    monkeypatch.delenv('TRIALLENS_PUBLIC_DEMO', raising=False)
    monkeypatch.setattr(nebius, 'LIVE_CLAIM', tmp_path / 'request.claim')
    monkeypatch.setattr(extraction, 'RESULTS_DIR', tmp_path / 'extraction')
    monkeypatch.setattr(inference_review, 'REVIEWS', tmp_path / 'reviews')
    def blocked(*args, **kwargs):
        pytest.fail('Provider transport must not be called')
    monkeypatch.setattr(extraction, 'chat_completion', blocked)
    with TemporaryDirectory(dir=ROOT / 'data/raw/trials') as temporary:
        directory = Path(temporary)
        source = directory / 'saved' / 'response.json'
        source.parent.mkdir()
        source.write_bytes((FIXTURES / 'extraction_snapshot.json').read_bytes())
        monkeypatch.setattr(research_api, 'RAW_TRIALS_DIR', directory)
        output = extraction.extract_snapshot(source.relative_to(ROOT), NCT, mock_response=FIXTURES / 'extraction_mock.json')
        yield source, output


def inspect(saved):
    return client.get(f'/saved-trials/{NCT}/inference/{saved[1].name}', headers=HEADERS)


def body(report, decision='approve', criterion='mock-inclusion'):
    return {'snapshot_sha256': report['source']['sha256'], 'attempt_sha256': report['attempt_sha256'],
            'criterion_id': criterion, 'decision': decision, 'reviewer': 'Software test reviewer',
            'note': 'Software fixture review; no clinical evidence.', 'semantics_reviewed': True}


def post(saved, payload, headers=HEADERS):
    return client.post(f'/saved-trials/{NCT}/inference/{saved[1].name}/reviews', json=payload, headers=headers)


def test_read_only_inspection_revalidates_source_and_never_claims_live_inference(saved):
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in saved[1].glob('*')}
    response = inspect(saved)
    assert response.status_code == 200
    value = response.json()
    assert value['review_checks_passed'] and value['manifest']['mode'] == 'mock'
    assert not value['assessment_allowed']
    original = json.loads(saved[0].read_text())['studies'][0]['protocolSection']['eligibilityModule']['eligibilityCriteria']
    assert value['source']['text'] == original
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in saved[1].glob('*')}
    status = client.get(f'/saved-trials/{NCT}/inference?snapshot=saved/response.json', headers=HEADERS).json()
    assert status['configuration']['ready']
    assert len(status['attempts']) == 1
    assert 'synthetic-provider-secret' not in response.text


def test_mapping_requires_operator_authentication_and_current_identity(saved):
    payload = body(inspect(saved).json())
    assert post(saved, payload, {}).status_code == 401
    assert post(saved, payload, {'Authorization': 'Bearer wrong'}).status_code == 401
    payload['snapshot_sha256'] = '0' * 64
    assert post(saved, payload).status_code == 409
    assert not list(inference_review.REVIEWS.glob('**/*.json'))


def test_approve_and_reject_preserve_immutable_audit_without_patient_assessment(saved):
    payload = body(inspect(saved).json())
    value = post(saved, payload).json()
    assert value['binding_approved'] and not value['assessment_allowed']
    records = list(inference_review.REVIEWS.glob('**/*.json'))
    first = records[0].read_bytes()
    assert json.loads(first)['binding']['verified'] is True
    approved = client.get(f'/saved-trials/{NCT}/inference/{saved[1].name}/bindings', headers=HEADERS).json()
    assert len(approved['bindings']) == 1 and not approved['assessment_available']
    payload['decision'] = 'reject'
    assert post(saved, payload).status_code == 200
    assert records[0].read_bytes() == first
    assert len(list(inference_review.REVIEWS.glob('**/*.json'))) == 2
    assert inspect(saved).json()['mapping_reviews']['mock-inclusion']['decision'] == 'reject'
    assert client.get(f'/saved-trials/{NCT}/inference/{saved[1].name}/bindings', headers=HEADERS).json()['bindings'] == []


@pytest.mark.parametrize('change', [{'semantics_reviewed': False}, {'criterion_id': 'missing'}, {'clinical_attribute': 'invented', 'value_type': 'numeric'}])
def test_unsupported_or_unreviewed_bindings_cannot_be_approved(saved, change):
    payload = {**body(inspect(saved).json()), **change}
    assert post(saved, payload).status_code in (409, 422)
    assert not list(inference_review.REVIEWS.glob('**/*.json'))


def test_failed_source_validation_cannot_be_bypassed_by_approval(saved):
    path = saved[1] / 'raw_response.json'
    raw = json.loads(path.read_text())
    candidate = json.loads(raw['content'])
    candidate['criteria'][0]['original_text'] = 'Unsupported invented source claim'
    raw['content'] = json.dumps(candidate)
    path.write_text(json.dumps(raw))
    report = inspect(saved).json()
    assert not report['review_checks_passed'] and report['validated'] is None
    assert post(saved, body(report)).status_code == 409


def test_cost_and_reservation_guards_stop_before_transport(saved, monkeypatch):
    report = inspect(saved).json()
    payload = {'snapshot': 'saved/response.json', 'snapshot_sha256': report['source']['sha256'], 'mode': 'live', 'live_approved': True}
    monkeypatch.setenv('NEBIUS_MAX_REQUEST_USD', '0.000001')
    assert not operator_status()['ready']
    assert client.post(f'/saved-trials/{NCT}/extractions', json=payload, headers=HEADERS).status_code == 409
    assert not nebius.LIVE_CLAIM.exists()
    monkeypatch.setenv('NEBIUS_MAX_REQUEST_USD', '1')
    nebius.LIVE_CLAIM.write_text('Preserved consumed reservation')
    before = nebius.LIVE_CLAIM.read_bytes()
    assert client.post(f'/saved-trials/{NCT}/extractions', json=payload, headers=HEADERS).status_code == 409
    assert nebius.LIVE_CLAIM.read_bytes() == before


def test_operator_and_pricing_configuration_fail_closed(saved, monkeypatch):
    payload = body(inspect(saved).json())
    monkeypatch.delenv('TRIALLENS_OPERATOR_TOKEN')
    assert not operator_status()['ready']
    assert inspect(saved).status_code == 503
    assert post(saved, payload).status_code == 503
    monkeypatch.setenv('TRIALLENS_OPERATOR_TOKEN', TOKEN)
    monkeypatch.delenv('NEBIUS_INPUT_USD_PER_MILLION')
    assert not operator_status()['cost_controls_ready']


def test_existing_separate_authorization_is_source_scoped_and_never_resets_original_claim(saved, monkeypatch, tmp_path):
    from backend import extraction_authorization
    from backend.app.inference_access import scoped_authorization
    from backend.app.trial_extraction_api import select_source
    source = select_source(NCT, 'saved/response.json')
    identifier = 'a' * 32
    monkeypatch.setenv('NEBIUS_EXTRACTION_AUTHORIZATION_ID', identifier)
    monkeypatch.setattr(extraction_authorization, 'AUTHORIZATIONS', tmp_path)
    record = {'nct_id': source.nct_id, 'snapshot': source.source_snapshot, 'snapshot_sha256': source.sha256,
              'model': nebius.DEFAULT_MODEL, 'timeout_seconds': nebius.inference_timeout()}
    monkeypatch.setattr(extraction_authorization, 'read_authorization', lambda value: record)
    nebius.LIVE_CLAIM.write_text('Original reservation remains consumed')
    before = nebius.LIVE_CLAIM.read_bytes()
    assert scoped_authorization(source) == identifier
    assert operator_status(source)['additional_authorization_available']
    record['snapshot_sha256'] = '0' * 64
    assert scoped_authorization(source) is None
    record['snapshot_sha256'] = source.sha256
    (tmp_path / f'{identifier}.claim').write_text('Additional request already consumed')
    assert scoped_authorization(source) is None
    assert nebius.LIVE_CLAIM.read_bytes() == before
