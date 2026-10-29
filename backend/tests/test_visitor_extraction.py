import hashlib
import asyncio
import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

from backend.app import visitor_extraction as visitor, research_api
from backend.app.extraction_prompt import CLINICAL_FIELDS
from backend.app.extraction_source import ROOT
from backend.app.main import app
from backend.app.nebius import NebiusError

client = TestClient(app)
KEY = "non-secret-visitor-fixture"


@pytest.fixture
def prepared(monkeypatch):
    visitor.plans.clear(); visitor.attempts.clear(); visitor.active.clear()
    monkeypatch.setenv("TRIALLENS_BYOK_ENABLED", "1")
    monkeypatch.setenv("NEBIUS_INPUT_USD_PER_MILLION", "0.3")
    monkeypatch.setenv("NEBIUS_OUTPUT_USD_PER_MILLION", "0.9")
    monkeypatch.setenv("NEBIUS_API_KEY", "never-use-the-owner-key")
    with TemporaryDirectory(dir=ROOT / "data/raw/trials") as temp:
        root = Path(temp)
        path = root / "fixture/response.json"
        path.parent.mkdir()
        payload = {"studies": [{"protocolSection": {"identificationModule": {"nctId": "NCT00000001"},
                   "eligibilityModule": {"eligibilityCriteria": "Inclusion Criteria:\nmarker present\nExclusion Criteria:\ncondition present"}}}]}
        path.write_text(json.dumps(payload))
        monkeypatch.setattr(research_api, "RAW_TRIALS_DIR", root)
        body = {"nct_id": "NCT00000001", "snapshot": "fixture/response.json", "snapshot_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        yield body, path


def quote(body):
    response = client.post('/visitor-analysis/prepare', json=body)
    assert response.status_code == 200, response.text
    return response.json()


def approval(value, **changes):
    return {"analysis_id": value["analysis_id"], "api_key": KEY, "confirmed": True,
            "maximum_cost_usd": value["maximum_cost_usd"], **changes}


def content(messages):
    text = json.loads(messages[-1]['content'])['eligibility_text']
    heading, rest = text.split('\n', 1)
    original = rest.strip('\n')
    start = text.index(original)
    node = dict.fromkeys(CLINICAL_FIELDS)
    node.update(criterion_id='criterion', original_text=original, criterion_type='inclusion' if 'Inclusion' in heading else 'exclusion', logical_operator='NONE')
    return json.dumps({"criteria": [node], "evidence": [{"criterion_id": "criterion", "original_span": {"start": start, "end": start + len(original)},
                       "polarity_span": {"start": 0, "end": len(heading)}, "fields": {}}]})


def test_explicit_aggregate_approval_sections_replay_and_no_persistence(prepared, monkeypatch, caplog):
    body, path = prepared
    calls = []
    async def provider(messages, key, disconnected):
        assert key == KEY
        calls.append(messages)
        return content(messages)
    monkeypatch.setattr(visitor, 'provider', provider)
    before = {p: p.stat().st_mtime_ns for folder in ('results/extraction', 'results/nebius') for p in (ROOT / folder).rglob('*') if p.is_file()}
    value = quote(body)
    assert value['request_count'] == 2 and float(value['maximum_cost_usd']) > 0
    assert KEY not in repr(visitor.plans)
    assert client.post('/visitor-analysis/run', json=approval(value, confirmed=False)).status_code == 422
    assert client.post('/visitor-analysis/run', json=approval(value, maximum_cost_usd='100')).status_code == 409
    result = client.post('/visitor-analysis/run', json=approval(value))
    assert result.status_code == 200 and result.json()['status'] == 'complete'
    assert len(calls) == 2 and not result.json()['executable_mapping']
    assert result.headers['cache-control'] == 'no-store'
    source_text = visitor.select_source(body['nct_id'], body['snapshot']).text
    for section in result.json()['sections']:
        for entry, node in zip(section['source_evidence'], section['criteria']):
            span = entry['original_span']
            assert source_text[span['start']:span['end']] == node['original_text']
    assert client.post('/visitor-analysis/run', json=approval(value)).status_code == 409
    assert len(calls) == 2
    assert KEY not in result.text + caplog.text + repr(visitor.plans)
    after = {p: p.stat().st_mtime_ns for folder in ('results/extraction', 'results/nebius') for p in (ROOT / folder).rglob('*') if p.is_file()}
    assert after == before


@pytest.mark.parametrize('code', ['incomplete_response', 'timeout', 'authentication_error', 'insufficient_credits', 'http_error'])
def test_failure_retains_valid_sections_and_never_retries(prepared, monkeypatch, code):
    calls = []
    async def provider(messages, key, disconnected):
        calls.append(1)
        if len(calls) == 2:
            raise NebiusError(code, raw_response=KEY)
        return content(messages)
    monkeypatch.setattr(visitor, 'provider', provider)
    result = client.post('/visitor-analysis/run', json=approval(quote(prepared[0]))).json()
    assert result['status'] == 'incomplete' and len(calls) == 2
    assert result['sections'][0]['status'] == 'validated'
    assert result['sections'][1]['error'] == code
    assert KEY not in json.dumps(result)


def test_limits_source_binding_isolation_and_validation_redaction(prepared, monkeypatch):
    body, path = prepared
    value = quote(body)
    for change in ({'api_key': ''}, {'api_key': None}, {'api_key': {'private': KEY}}, {'api_key': KEY, 'extra': KEY}):
        response = client.post('/visitor-analysis/run', json=approval(value, **change))
        assert response.status_code == 422 and KEY not in response.text
    with TestClient(app, client=('other-visitor', 123)) as other:
        assert other.post('/visitor-analysis/run', json=approval(value)).status_code == 400
    visitor.active.add(hashlib.sha256(b'testclient').hexdigest())
    assert client.post('/visitor-analysis/run', json=approval(value)).status_code == 429
    visitor.active.clear()
    path.write_text(path.read_text() + ' ')
    assert client.post('/visitor-analysis/run', json=approval(value)).status_code == 409
    assert client.post('/visitor-analysis/run', json=approval(value)).status_code == 409
    for _ in range(5):
        client.post('/visitor-analysis/prepare', json=body)
    assert client.post('/visitor-analysis/prepare', json=body).status_code == 429
    assert client.get('/operator/session').status_code in (401, 503)


def test_server_ceiling_missing_rates_and_disabled_gate(prepared, monkeypatch):
    monkeypatch.setenv('TRIALLENS_BYOK_MAX_USD', '0.000001')
    assert client.post('/visitor-analysis/prepare', json=prepared[0]).status_code == 422
    monkeypatch.delenv('NEBIUS_OUTPUT_USD_PER_MILLION')
    assert client.post('/visitor-analysis/prepare', json=prepared[0]).status_code == 503
    monkeypatch.setenv('TRIALLENS_BYOK_ENABLED', '0')
    assert client.post('/visitor-analysis/prepare', json=prepared[0]).status_code == 503


def test_section_boundaries_cover_all_text_and_keep_nested_blocks(prepared):
    source = visitor.select_source(prepared[0]['nct_id'], prepared[0]['snapshot'])
    source = replace(source, text='Inclusion Criteria:\n' + ''.join('* criterion ' + str(i) + ' ' + 'x' * 100 + '\n  - child\n' for i in range(70)) + 'Exclusion Criteria:\n* condition')
    units = visitor.sections(source)
    assert len(units) > 2
    coverage = set()
    for unit in units:
        assert unit['source_end'] > unit['source_start']
        coverage.update(range(unit['source_start'], unit['source_end']))
        assert not unit['source'].text.splitlines()[1].startswith('  -')
    for i, char in enumerate(source.text):
        if not char.isspace() and not any(h.start() <= i < h.end() for h in __import__('re').finditer(r'(Inclusion|Exclusion) Criteria:', source.text)):
            assert i in coverage


@pytest.mark.parametrize('finish,status,expected', [('length', 200, 'incomplete_response'), ('stop', 401, 'authentication_error'), ('stop', 402, 'insufficient_credits'), ('stop', 500, 'http_error')])
def test_allowlisted_transport_redacts_provider_errors(prepared, monkeypatch, finish, status, expected):
    async def post(self, url, **kwargs):
        assert url == visitor.BASE_URL + '/chat/completions'
        assert kwargs['headers']['Authorization'] == 'Bearer ' + KEY
        assert kwargs['json']['model'] == visitor.DEFAULT_MODEL
        assert kwargs['json']['store'] is False and kwargs['json']['n'] == 1
        return httpx.Response(status, json={'error': KEY, 'choices': [{'finish_reason': finish, 'message': {'content': KEY}}]})
    monkeypatch.setattr(httpx.AsyncClient, 'post', post)
    result = client.post('/visitor-analysis/run', json=approval(quote(prepared[0])))
    assert result.json()['sections'][0]['error'] == expected
    assert KEY not in result.text


@pytest.mark.parametrize('failure', ['timeout', 'echo', 'escaped_echo', 'invalid_json', 'wrong_model'])
def test_transport_failures_are_secret_safe_and_stop_further_requests(prepared, monkeypatch, failure):
    calls = []
    async def post(self, url, **kwargs):
        calls.append(1)
        if failure == 'timeout':
            raise httpx.ReadTimeout(KEY)
        value = content(kwargs['json']['messages'])
        if failure in ('echo', 'escaped_echo'):
            value = json.dumps({'secret': KEY})
            if failure == 'escaped_echo':
                value = ''.join('\\u%04x' % ord(c) for c in KEY).join(value.split(KEY))
        if failure == 'invalid_json':
            value = '{'
        return httpx.Response(200, json={'model': 'wrong' if failure == 'wrong_model' else visitor.DEFAULT_MODEL,
            'choices': [{'finish_reason': 'stop', 'message': {'content': value}}]})
    monkeypatch.setattr(httpx.AsyncClient, 'post', post)
    result = client.post('/visitor-analysis/run', json=approval(quote(prepared[0])))
    assert result.json()['status'] == 'incomplete'
    assert len(calls) == 1 and result.json()['sections'][1]['status'] == 'not_requested'
    assert KEY not in result.text


def test_expiry_cross_origin_and_https_visitor_isolation(prepared):
    value = quote(prepared[0])
    visitor.plans[value['analysis_id']]['expires'] = 0
    assert client.post('/visitor-analysis/run', json=approval(value)).status_code == 409
    assert client.post('/visitor-analysis/prepare', json=prepared[0], headers={'Origin': 'https://untrusted.invalid'}).status_code == 403
    value = quote(prepared[0])
    with TestClient(app, base_url='https://trusted.example', client=('different-visitor', 123)) as other:
        assert other.post('/visitor-analysis/run', json=approval(value)).status_code == 409


def test_disconnect_cancels_transport_and_releases_concurrency(prepared, monkeypatch):
    value = quote(prepared[0])
    state = {'polls': 0, 'cancelled': False}
    async def provider(*args):
        try:
            await asyncio.sleep(10)
        finally:
            state['cancelled'] = True
    async def disconnect():
        state['polls'] += 1
        return state['polls'] > 1
    monkeypatch.setattr(visitor, 'provider', provider)
    request = SimpleNamespace(client=SimpleNamespace(host='testclient'), url=SimpleNamespace(scheme='https'),
                              headers={}, base_url='https://trusted.example/', is_disconnected=disconnect)
    with pytest.raises(HTTPException) as error:
        asyncio.run(visitor.run(visitor.Approval(**approval(value)), request))
    assert error.value.status_code == 499 and state['cancelled']
    assert not visitor.active and value['analysis_id'] not in visitor.plans


def test_real_long_source_is_split_without_provider_requests():
    from backend.app.trial_extraction_api import select_source
    try:
        source = select_source('NCT04331067')
    except HTTPException:
        pytest.skip('Optional saved registry source absent')
    units = visitor.sections(source)
    assert len(units) >= 3
    assert all(unit['input_limit'] <= visitor.MAX_INPUT_TOKENS for unit in units)


def test_unresolved_conditional_is_source_validated_but_never_executable(prepared, monkeypatch):
    body, path = prepared
    payload = json.loads(path.read_text())
    payload['studies'][0]['protocolSection']['eligibilityModule']['eligibilityCriteria'] = 'Inclusion Criteria:\nmarker present AND assay positive unless condition present'
    path.write_text(json.dumps(payload))
    body['snapshot_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    async def provider(messages, key, disconnected):
        value = json.loads(content(messages))
        value['criteria'][0]['logical_operator'] = None
        return json.dumps(value)
    monkeypatch.setattr(visitor, 'provider', provider)
    result = client.post('/visitor-analysis/run', json=approval(quote(body))).json()
    assert result['status'] == 'complete' and not result['executable_mapping'] and result['human_review_required']
    assert result['sections'][0]['criteria'][0]['logical_operator'] is None
