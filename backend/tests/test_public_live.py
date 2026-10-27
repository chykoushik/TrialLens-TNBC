import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import public_demo
from backend.app import nebius, public_live
from backend.app.extraction_prompt import CLINICAL_FIELDS

TOKEN = 'operator-'+48*'x'
KEY = 'synthetic-provider-key-only'
HEADERS = {'Authorization': 'Bearer '+TOKEN}


@pytest.fixture
def live(monkeypatch, tmp_path):
    for name in ('TRIALLENS_LIVE_INFERENCE', 'NEBIUS_LIVE_EXTRACTION', 'TRIALLENS_LIVE_OPERATOR_TOKEN',
                 'TRIALLENS_LIVE_STATE_DIR', 'NEBIUS_API_KEY', 'NEBIUS_MODEL', 'NEBIUS_BASE_URL',
                 'NEBIUS_TIMEOUT_SECONDS', 'TRIALLENS_PUBLIC_DEMO'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('TRIALLENS_LIVE_INFERENCE', '1')
    monkeypatch.setenv('NEBIUS_LIVE_EXTRACTION', '1')
    monkeypatch.setenv('TRIALLENS_LIVE_OPERATOR_TOKEN', TOKEN)
    monkeypatch.setenv('TRIALLENS_LIVE_STATE_DIR', str(tmp_path/'state'))
    monkeypatch.setenv('NEBIUS_API_KEY', KEY)
    monkeypatch.setenv('NEBIUS_MODEL', nebius.DEFAULT_MODEL)
    calls = []
    client_class = httpx.Client

    def install(handler):
        def capture(request):
            calls.append(request)
            return handler(request)
        monkeypatch.setattr(nebius.httpx, 'Client', lambda **kwargs: client_class(transport=httpx.MockTransport(capture), **kwargs))

    def forbidden(request):
        raise AssertionError('Unexpected provider call')
    install(forbidden)
    return TestClient(public_demo.app), install, calls, tmp_path/'state'


def prepare(client):
    response = client.post('/api/inference/prepare', headers=HEADERS, json={'source_id': public_live.SOURCE_ID})
    assert response.status_code == 200, response.text
    return response.json()['approval']


def execute(client, approval, **values):
    return client.post('/api/inference/execute', headers=HEADERS,
                       json=dict(approval=approval, confirm_paid_request=True, **values))


def valid_content():
    criteria, evidence = [], []
    for index, (polarity, text) in enumerate([('inclusion', 'Age >=18 years.'), ('exclusion', 'Prior PARP inhibitor treatment.')]):
        node = dict.fromkeys(CLINICAL_FIELDS)
        node.update(criterion_id=f'criterion-{index}', original_text=text, criterion_type=polarity, logical_operator='NONE')
        start = public_live.SOURCE_TEXT.index(text)
        heading = polarity.title()+' Criteria:'
        heading_start = public_live.SOURCE_TEXT.index(heading)
        criteria.append(node)
        evidence.append(dict(criterion_id=node['criterion_id'], original_span=dict(start=start, end=start+len(text)),
                             polarity_span=dict(start=heading_start, end=heading_start+len(heading)), fields={}))
    return json.dumps(dict(criteria=criteria, evidence=evidence))


def response(content=None, finish='stop', model=nebius.DEFAULT_MODEL):
    return httpx.Response(200, json=dict(model=model, choices=[dict(finish_reason=finish,
        message=dict(content=valid_content() if content is None else content))],
        usage=dict(prompt_tokens=10, completion_tokens=20, total_tokens=30)))


def test_live_success_is_separate_and_source_validated(live, caplog):
    client, install, calls, state = live
    before = client.post('/api/tnbc/cases/tnbc-record-gaps/evaluate', json={'budget': '3'}).json()
    approval = prepare(client)
    assert calls == [] and not (state/'request.claim').exists()
    def handler(request):
        assert str(request.url) == nebius.BASE_URL+'/chat/completions'
        assert request.headers['Authorization'] == 'Bearer '+KEY
        payload = json.loads(request.content)
        assert payload['model'] == nebius.DEFAULT_MODEL
        assert payload['max_tokens'] == 8192
        assert json.loads(payload['messages'][1]['content'])['eligibility_text'] == public_live.SOURCE_TEXT
        assert KEY not in request.content.decode() and TOKEN not in request.content.decode()
        return response()
    install(handler)
    result = execute(client, approval)
    assert result.status_code == 200, result.text
    value = result.json()
    assert value['inference_mode'] == 'live' and value['input_is_synthetic'] is True
    assert value['status'] == 'source_validated'
    assert len(value['proposal']['criteria']) == 2
    assert value['human_review_required'] is True and value['assessment_allowed'] is False
    assert value['fictional_demo_modified'] is False
    assert KEY not in result.text and TOKEN not in result.text and 'raw_response' not in value
    assert KEY not in caplog.text and TOKEN not in caplog.text
    assert state.joinpath('request.claim').is_file() and KEY not in state.joinpath('request.claim').read_text()
    assert len(calls) == 1
    assert client.post('/api/tnbc/cases/tnbc-record-gaps/evaluate', json={'budget': '3'}).json() == before
    assert result.headers['Cache-Control'] == 'no-store'
    assert execute(TestClient(public_demo.app), approval).status_code == 409
    assert client.post('/api/inference/prepare', headers=HEADERS, json={'source_id': public_live.SOURCE_ID}).status_code == 409
    assert len(calls) == 1


@pytest.mark.parametrize('missing', ['TRIALLENS_LIVE_INFERENCE', 'NEBIUS_LIVE_EXTRACTION'])
def test_disabled_mode_never_calls_provider(live, monkeypatch, missing):
    client, install, calls, state = live
    monkeypatch.delenv(missing)
    assert client.post('/api/inference/prepare', headers=HEADERS, json={'source_id': public_live.SOURCE_ID}).status_code == 404
    assert execute(client, 'unused').status_code == 404
    assert client.get('/api/health').json()['paid_inference'] is False
    assert calls == [] and not state.exists()


@pytest.mark.parametrize('header', [{}, {'Authorization': 'Bearer wrong'}, {'Authorization': 'Bearer '+KEY}])
def test_operator_authentication_required(live, header):
    client, install, calls, state = live
    assert client.post('/api/inference/prepare', headers=header, json={'source_id': public_live.SOURCE_ID}).status_code == 401
    assert calls == [] and not state.exists()


@pytest.mark.parametrize('name,value', [('NEBIUS_API_KEY', ''), ('NEBIUS_MODEL', 'other'), ('NEBIUS_BASE_URL', 'http://example.invalid'),
    ('TRIALLENS_LIVE_OPERATOR_TOKEN', ''), ('TRIALLENS_LIVE_STATE_DIR', ''), ('NEBIUS_TIMEOUT_SECONDS', '121'),
    ('NEBIUS_TIMEOUT_SECONDS', 'nan'), ('NEBIUS_API_KEY', TOKEN)])
def test_missing_or_unsafe_configuration_fails_before_reservation(live, monkeypatch, name, value):
    client, install, calls, state = live
    monkeypatch.setenv(name, value)
    result = client.post('/api/inference/prepare', headers=HEADERS, json={'source_id': public_live.SOURCE_ID})
    assert result.status_code == 503
    assert KEY not in result.text and TOKEN not in result.text
    assert calls == [] and not state.exists()


@pytest.mark.parametrize('confirmation', [False, 1, 'true', None])
def test_paid_confirmation_must_be_boolean_true(live, confirmation):
    client, install, calls, state = live
    value = prepare(client)
    result = client.post('/api/inference/execute', headers=HEADERS, json={'approval': value, 'confirm_paid_request': confirmation})
    assert result.status_code == 422
    assert calls == [] and not state.exists()


def test_get_prepare_and_health_never_send_inference(live):
    client, install, calls, state = live
    assert client.get('/api/inference/execute', headers=HEADERS).status_code == 405
    assert client.get('/api/inference/status', headers=HEADERS).json()['request_limit'] == 1
    assert client.get('/api/health').json()['paid_inference'] is True
    for _ in range(3):
        prepare(client)
    assert calls == [] and not state.exists()


@pytest.mark.parametrize('missing', ['approval', 'confirm_paid_request'])
def test_missing_approval_fields_cannot_reserve(live, missing):
    client, install, calls, state = live
    body = dict(approval=prepare(client), confirm_paid_request=True)
    del body[missing]
    assert client.post('/api/inference/execute', headers=HEADERS, json=body).status_code == 422
    assert calls == [] and not state.exists()


@pytest.mark.parametrize('change', ['tampered', 'expired', 'model-config', 'provider-key', 'source'])
def test_approval_is_bound_and_expiring(live, monkeypatch, change):
    client, install, calls, state = live
    token = prepare(client)
    if change == 'tampered':
        token += 'x'
    elif change == 'expired':
        current = public_live.time.time()
        monkeypatch.setattr(public_live.time, 'time', lambda: current+301)
    elif change == 'model-config':
        monkeypatch.setenv('NEBIUS_TIMEOUT_SECONDS', '60')
    elif change == 'provider-key':
        monkeypatch.setenv('NEBIUS_API_KEY', 'another-synthetic-key')
    else:
        monkeypatch.setattr(public_live, 'SOURCE_ID', 'changed-source')
    assert execute(client, token).status_code == 409
    assert calls == [] and not state.exists()


@pytest.mark.parametrize('status,code', [(401, 'authentication_error'), (402, 'insufficient_credits'),
    (403, 'permission_denied'), (429, 'rate_limited'), (500, 'http_error')])
def test_provider_errors_are_sanitized_and_not_retried(live, status, code):
    client, install, calls, state = live
    token = prepare(client)
    install(lambda request: httpx.Response(status, json={'error': {'message': KEY+' '+TOKEN}}))
    result = execute(client, token)
    assert result.status_code == 502 and result.json()['detail']['code'] == code
    assert KEY not in result.text and TOKEN not in result.text
    assert state.joinpath('request.claim').exists() and len(calls) == 1
    assert execute(client, token).status_code == 409 and len(calls) == 1


@pytest.mark.parametrize('error,code,status', [(httpx.ReadTimeout, 'timeout', 504), (httpx.ConnectError, 'connection_error', 502)])
def test_timeout_and_connection_failure_consume_attempt(live, error, code, status):
    client, install, calls, state = live
    token = prepare(client)
    def handler(request):
        raise error(KEY, request=request)
    install(handler)
    result = execute(client, token)
    assert result.status_code == status and result.json()['detail']['code'] == code
    assert KEY not in result.text and state.joinpath('request.claim').exists() and len(calls) == 1


@pytest.mark.parametrize('content', ['invalid JSON', '{"criteria": [], "evidence": []}'])
def test_invalid_output_is_not_mocked_or_promoted(live, content):
    client, install, calls, state = live
    token = prepare(client)
    install(lambda request: response(content))
    result = execute(client, token).json()
    assert result['status'] == 'validation_failed'
    assert result['proposal'] is None and result['assessment_allowed'] is False
    assert len(calls) == 1


@pytest.mark.parametrize('encoding', ['plain', 'json', 'escaped', 'operator'])
def test_plain_or_json_credential_echo_is_withheld(live, encoding):
    client, install, calls, state = live
    token = prepare(client)
    escaped = ''.join('\\u%04x' % ord(c) for c in KEY)
    content = {'plain': KEY, 'json': json.dumps({'secret': KEY}),
               'escaped': '{"secret":"'+escaped+'"}', 'operator': TOKEN}[encoding]
    install(lambda request: response(content))
    result = execute(client, token)
    assert result.status_code == 502
    assert KEY not in result.text and TOKEN not in result.text
    assert state.joinpath('request.claim').exists() and len(calls) == 1


def test_one_atomic_reservation_under_concurrent_execution(live):
    client, install, calls, state = live
    token = prepare(client)
    install(lambda request: response())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: execute(client, token).status_code, range(2)))
    assert sorted(results) == [200, 409]
    assert len(calls) == 1


def test_storage_failure_cannot_send_request(live):
    client, install, calls, state = live
    token = prepare(client)
    state.write_text('Not a directory')
    assert execute(client, token).status_code == 503
    assert calls == []


def test_arbitrary_or_private_text_is_not_accepted(live):
    client, install, calls, state = live
    for body in ({'source_id': 'private-source'}, {'source_id': public_live.SOURCE_ID, 'text': 'not accepted'}):
        assert client.post('/api/inference/prepare', headers=HEADERS, json=body).status_code == 422
    assert calls == [] and not state.exists()


@pytest.mark.parametrize('kind', ['length', 'wrong-model', 'empty'])
def test_incomplete_or_incompatible_response_is_not_replaced(live, kind):
    client, install, calls, state = live
    token = prepare(client)
    install(lambda request: response(finish='length') if kind == 'length' else
            response(model='other-model') if kind == 'wrong-model' else response(content=''))
    result = execute(client, token)
    assert result.status_code == 502
    assert state.joinpath('request.claim').exists() and len(calls) == 1


def test_unknown_or_replayed_approval_cannot_reserve(live):
    client, install, calls, state = live
    assert execute(client, 'not-an-approval').status_code == 409
    assert calls == [] and not state.exists()


def test_enabled_startup_health_and_status_never_call_provider(live, tmp_path, monkeypatch):
    client, install, calls, state = live
    (tmp_path/'index.html').write_text('<html>Offline demo test</html>', encoding='utf-8')
    monkeypatch.setattr(public_demo, 'DIST', tmp_path)
    assert client.get('/').status_code == 200
    assert client.get('/api/readiness').status_code == 200
    assert client.get('/api/inference/status', headers=HEADERS).status_code == 200
    assert calls == [] and not state.exists()
