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


@pytest.mark.parametrize("action", ["expiry", "removal"])
def test_temporary_key_cancels_inflight_and_prevents_next_section(prepared, monkeypatch, action):
    value = quote(prepared[0])
    calls = []
    cancelled = []
    async def provider(*args):
        calls.append(1)
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.append(True)
    async def connected():
        return False
    request = SimpleNamespace(client=SimpleNamespace(host='testclient'), url=SimpleNamespace(scheme='https'),
                              headers={}, base_url='https://trusted.example/', is_disconnected=connected)
    monkeypatch.setattr(visitor, 'provider', provider)
    monkeypatch.setattr(visitor, 'KEY_TTL', .03 if action == 'expiry' else 300)
    async def scenario():
        task = asyncio.create_task(visitor.run(visitor.Approval(**approval(value)), request))
        await asyncio.sleep(.01)
        if action == 'removal':
            result = await visitor.remove(visitor.Removal(analysis_id=value['analysis_id']), request)
            assert result == {'removed': True, 'provider_key_revoked': False}
        with pytest.raises(HTTPException) as error:
            await task
        assert error.value.status_code == (408 if action == 'expiry' else 409)
    asyncio.run(scenario())
    assert calls == [1] and cancelled == [True]
    assert not visitor.active and not visitor.running
    assert KEY not in repr(visitor.plans)


def test_removal_before_submission_consumes_capability(prepared):
    value = quote(prepared[0])
    assert client.post('/visitor-analysis/remove', json={'analysis_id': value['analysis_id']}).status_code == 200
    assert client.post('/visitor-analysis/run', json=approval(value)).status_code == 409



def test_render_https_is_bound_to_platform_hostname(prepared, monkeypatch):
    monkeypatch.setenv('RENDER', 'true')
    monkeypatch.setenv('RENDER_EXTERNAL_HOSTNAME', 'triallens-tnbc.onrender.com')
    with TestClient(app, base_url='http://triallens-tnbc.onrender.com', client=('proxy', 1)) as proxy:
        headers = {'X-Forwarded-Proto': 'https', 'Origin': 'https://triallens-tnbc.onrender.com'}
        assert proxy.post('/visitor-analysis/prepare', json=prepared[0], headers=headers).status_code == 200
        assert proxy.post('/visitor-analysis/prepare', json=prepared[0]).status_code == 400
        assert proxy.post('/visitor-analysis/prepare', json=prepared[0], headers={**headers, 'Host': 'spoof.invalid'}).status_code == 400



def test_two_visitors_cancel_independently(prepared, monkeypatch):
    requests = []
    def request(host):
        async def connected():
            return False
        return SimpleNamespace(client=SimpleNamespace(host=host), url=SimpleNamespace(scheme='https'),
                               headers={}, base_url='https://trusted.example/', is_disconnected=connected)
    one, two = request('visitor-one'), request('visitor-two')
    first = visitor.prepare(visitor.Preparation(**prepared[0]), one)
    second = visitor.prepare(visitor.Preparation(**prepared[0]), two)
    async def scenario():
        release = asyncio.Event()
        async def provider(messages, key, disconnected):
            requests.append(key)
            await release.wait()
            return content(messages)
        monkeypatch.setattr(visitor, 'provider', provider)
        a = asyncio.create_task(visitor.run(visitor.Approval(**approval(first)), one))
        b = asyncio.create_task(visitor.run(visitor.Approval(**approval(second, api_key='other-visitor-fixture')), two))
        await asyncio.sleep(.01)
        await visitor.remove(visitor.Removal(analysis_id=first['analysis_id']), one)
        release.set()
        with pytest.raises(HTTPException):
            await a
        result = await b
        assert result['status'] == 'complete'
    asyncio.run(scenario())
    assert requests.count(KEY) == 1
    assert requests.count('other-visitor-fixture') == 2
    assert not visitor.active and not visitor.running



def test_nct06774027_exact_quotes_with_wrong_offsets_are_reanchored(monkeypatch):
    source = visitor.select_source('NCT06774027')
    units = visitor.sections(source)
    assert len(units) == 2
    assert 'Cohort 4:' in units[0]['source'].text
    assert not any(ord(char) > 127 for char in units[0]['source'].text)
    calls = []
    async def provider(messages, key, disconnected):
        payload = json.loads(content(messages))
        payload['criteria'][0]['logical_operator'] = None
        entry = payload['evidence'][0]
        entry['original_span']['start'] += 1
        entry['original_span']['end'] += 1
        entry['polarity_span'] = {'start': 1, 'end': 2}
        raw = json.dumps(payload)
        section = units[len(calls)]['source']
        _, errors = visitor.validate_extraction(raw, section, method='fixture', timestamp='2026-10-29T00:00:00Z', allow_unresolved_logic=True)
        assert 'unsupported_original_text' in {error['code'] for error in errors}
        calls.append(1)
        return raw
    monkeypatch.setattr(visitor, 'provider', provider)
    plan = {'source': source, 'units': units, 'quote': {'maximum_cost_usd': '0.1'}}
    result = asyncio.run(visitor.extract(plan, KEY, asyncio.Event()))
    assert len(calls) == 2 and result['status'] == 'complete'
    assert all(section['exact_offsets_reanchored'] for section in result['sections'])
    for section in result['sections']:
        for node, evidence in zip(section['criteria'], section['source_evidence']):
            span = evidence['original_span']
            assert source.text[span['start']:span['end']] == node['original_text']
    assert 'Cohort 4:' in result['merged_criteria'][0]['original_text']
    assert result['merged_criteria'][0]['logical_operator'] is None


@pytest.mark.parametrize('failure,expected', [
    ('quotation', 'unsupported_original_text'), ('numbering', 'partial_top_level_line'),
    ('schema', 'schema_error'), ('logic', 'unresolved_compound_logic'),
    ('field', 'unsupported_field'), ('duplicate', 'invalid_json_or_schema'),
])
def test_validation_diagnostics_reject_unsupported_output_and_stop(prepared, monkeypatch, failure, expected):
    calls = []
    async def provider(messages, key, disconnected):
        calls.append(1)
        value = json.loads(content(messages))
        node, entry = value['criteria'][0], value['evidence'][0]
        if failure == 'quotation':
            node['original_text'] = 'non-secret-hallucinated-fixture'
        elif failure == 'numbering':
            node['original_text'] = node['original_text'][1:]
            entry['original_span']['start'] += 1
        elif failure == 'schema':
            node['non-secret-private-field-fixture'] = KEY
        elif failure == 'logic':
            node['original_text'] = 'marker present AND assay positive'
        elif failure == 'field':
            node['biomarker'] = 'unsupported-biomarker'
            entry['fields']['biomarker'] = {'start': 0, 'end': 1}
        raw = json.dumps(value)
        if failure == 'duplicate':
            raw = raw.replace('"criteria":', '"criteria": [], "criteria":', 1)
        return raw
    if failure == 'logic':
        body, path = prepared
        payload = json.loads(path.read_text())
        payload['studies'][0]['protocolSection']['eligibilityModule']['eligibilityCriteria'] = 'Inclusion Criteria:\nmarker present AND assay positive\nExclusion Criteria:\ncondition present'
        path.write_text(json.dumps(payload))
        body['snapshot_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(visitor, 'provider', provider)
    result = client.post('/visitor-analysis/run', json=approval(quote(prepared[0]))).json()
    assert result['status'] == 'incomplete' and len(calls) == 1
    section = result['sections'][0]
    assert section['error'] == 'source_validation_failed'
    assert expected in {item['code'] for item in section['diagnostics']}
    assert result['sections'][1]['status'] == 'not_requested'
    assert KEY not in json.dumps(result)
    assert 'non-secret-private-field-fixture' not in json.dumps(result)


def test_exact_reanchoring_rejects_ambiguous_and_normalized_quotes(prepared):
    from backend.app.extraction_validation import reanchor_exact_spans
    source = visitor.select_source(prepared[0]['nct_id'], prepared[0]['snapshot'])
    for text, quotation in [('Inclusion Criteria:\nrepeat\nrepeat', 'repeat'),
                            ('Inclusion Criteria:\nCafe\u0301 \u2265 18 \U0001f9ec', 'Caf\u00e9 \u2265 18 \U0001f9ec')]:
        source = replace(source, text=text)
        value = json.loads(content(visitor.build_messages(source)))
        value['criteria'][0]['original_text'] = quotation
        value['evidence'][0]['original_span'] = {'start': 0, 'end': 1}
        recovered = reanchor_exact_spans(json.dumps(value), source)
        _, errors = visitor.validate_extraction(recovered, source, method='fixture', timestamp='2026-10-29T00:00:00Z', allow_unresolved_logic=True)
        assert 'unsupported_original_text' in {error['code'] for error in errors}


def test_unicode_byte_offsets_reanchor_to_python_characters(prepared):
    from backend.app.extraction_validation import reanchor_exact_spans
    source = visitor.select_source(prepared[0]['nct_id'], prepared[0]['snapshot'])
    source = replace(source, text='Inclusion Criteria:\n* Caf\u00e9 \U0001f9ec \u2265 18')
    assert '\u2265' in visitor.build_messages(source)[-1]['content']
    value = json.loads(content(visitor.build_messages(source)))
    node, entry = value['criteria'][0], value['evidence'][0]
    node['threshold'] = '18'
    entry['original_span']['end'] = len(source.text.encode())
    entry['fields']['threshold'] = {'start': len(source.text.encode()) - 2, 'end': len(source.text.encode())}
    recovered = reanchor_exact_spans(json.dumps(value), source)
    model, errors = visitor.validate_extraction(recovered, source, method='fixture', timestamp='2026-10-29T00:00:00Z', allow_unresolved_logic=True)
    assert model is not None and not errors
    assert model.criteria[0].original_text == node['original_text']



def test_nested_exact_reanchoring_preserves_dependencies(prepared):
    from backend.app.extraction_validation import reanchor_exact_spans
    source = visitor.select_source(prepared[0]['nct_id'], prepared[0]['snapshot'])
    source = replace(source, text='Inclusion Criteria:\n* marker present AND assay positive')
    value = json.loads(content(visitor.build_messages(source)))
    parent = value['criteria'][0]
    children = []
    for i, original in enumerate(['marker present', 'assay positive']):
        node = dict.fromkeys(CLINICAL_FIELDS)
        node.update(criterion_id=f'child-{i}', original_text=original, criterion_type='inclusion', logical_operator='NONE')
        children.append(node)
        value['evidence'].append({'criterion_id': node['criterion_id'], 'original_span': {'start': 0, 'end': 1},
                                  'polarity_span': {'start': 1, 'end': 2}, 'fields': {}})
    parent.update(logical_operator='AND', dependencies=children)
    value['evidence'][0]['original_span'] = {'start': 0, 'end': 1}
    recovered = reanchor_exact_spans(json.dumps(value), source)
    assert json.loads(recovered)['criteria'] == value['criteria']
    model, errors = visitor.validate_extraction(recovered, source, method='fixture', timestamp='2026-10-29T00:00:00Z', allow_unresolved_logic=True)
    assert not errors and len(model.criteria[0].dependencies) == 2


def test_validation_failure_retains_previous_section_and_merge_reason(prepared, monkeypatch):
    source = visitor.select_source(prepared[0]['nct_id'], prepared[0]['snapshot'])
    plan = {'source': source, 'units': visitor.sections(source), 'quote': {'maximum_cost_usd': '0.1'}}
    async def provider(messages, key, disconnected):
        payload = json.loads(content(messages))
        if payload['criteria'][0]['criterion_type'] == 'exclusion':
            payload['criteria'][0]['original_text'] = 'invented quotation'
        return json.dumps(payload)
    monkeypatch.setattr(visitor, 'provider', provider)
    result = asyncio.run(visitor.extract(plan, KEY, asyncio.Event()))
    assert result['status'] == 'incomplete' and result['sections'][0]['criteria']
    assert result['sections'][1]['diagnostics'][0]['code'] == 'unsupported_original_text'
    validate = visitor.validate_extraction
    def failed_merge(*args, **kwargs):
        if kwargs['method'] == 'visitor-merged-v1':
            return None, [{'code': 'lost_cohort_scope', 'criterion_id': KEY, 'field': KEY}]
        return validate(*args, **kwargs)
    async def valid(messages, *args):
        return content(messages)
    monkeypatch.setattr(visitor, 'provider', valid)
    monkeypatch.setattr(visitor, 'validate_extraction', failed_merge)
    result = asyncio.run(visitor.extract(plan, KEY, asyncio.Event()))
    assert result['status'] == 'incomplete' and all(s['status'] == 'validated' for s in result['sections'])
    assert result['merge_diagnostics'] == [{'code': 'lost_cohort_scope', 'message': visitor.VALIDATION_REASONS['lost_cohort_scope']}]
    assert KEY not in json.dumps(result)



@pytest.mark.parametrize('failure,field,category', [
    ('missing_null', 'criteria.0.cohort', 'missing_required_property'),
    ('numeric_threshold', 'criteria.0.threshold', 'incorrect_type'),
    ('upper_polarity', 'criteria.0.criterion_type', 'invalid_enum_value'),
    ('dependencies_string', 'criteria.0.dependencies', 'incorrect_type'),
    ('nested_missing', 'criteria.0.dependencies.0.threshold', 'missing_required_property'),
    ('and_without_operands', 'criteria.0.dependencies', 'dependency_structure'),
    ('fields_list', 'evidence.0.fields', 'incorrect_type'),
    ('missing_span', 'evidence.0.original_span.end', 'missing_required_property'),
    ('string_offset', 'evidence.0.original_span.start', 'incorrect_type'),
    ('unexpected_private_key', 'evidence.0.[unexpected]', 'unexpected_property'),
    ('malformed_json', '$', 'malformed_json'),
    ('nonfinite_json', '$', 'malformed_json'),
])
def test_nct06774027_schema_failure_paths_are_precise_and_secret_safe(monkeypatch, failure, field, category):
    source = visitor.select_source('NCT06774027')
    units = visitor.sections(source)
    calls = []
    async def provider(messages, key, disconnected):
        calls.append(1)
        value = json.loads(content(messages))
        node, entry = value['criteria'][0], value['evidence'][0]
        node['logical_operator'] = None
        if failure == 'missing_null': del node['cohort']
        elif failure == 'numeric_threshold': node['threshold'] = 18
        elif failure == 'upper_polarity': node['criterion_type'] = 'INCLUSION'
        elif failure == 'dependencies_string': node['dependencies'] = 'none'
        elif failure == 'nested_missing':
            child = dict(node); child['criterion_id'] = 'child'; del child['threshold']
            node.update(logical_operator='AND', dependencies=[child, dict(node, criterion_id='other-child')])
        elif failure == 'and_without_operands': node['logical_operator'] = 'AND'
        elif failure == 'fields_list': entry['fields'] = []
        elif failure == 'missing_span': del entry['original_span']['end']
        elif failure == 'string_offset': entry['original_span']['start'] = str(entry['original_span']['start'])
        elif failure == 'unexpected_private_key': entry[KEY] = KEY
        elif failure == 'malformed_json': return '{"criteria": ['
        elif failure == 'nonfinite_json': return '{"criteria":NaN,"evidence":[]}'
        return json.dumps(value)
    monkeypatch.setattr(visitor, 'provider', provider)
    plan = {'source':source, 'units':units, 'quote':{'maximum_cost_usd':'0.1'}}
    result = asyncio.run(visitor.extract(plan, KEY, asyncio.Event()))
    assert len(calls) == 1 and result['status'] == 'incomplete'
    assert result['sections'][1]['status'] == 'not_requested'
    assert any(item.get('field') == field and item.get('category') == category for item in result['sections'][0]['diagnostics'])
    assert KEY not in json.dumps(result)


def test_prompt_publishes_actual_required_wire_schema_and_keeps_small_sections():
    from backend.app.extraction_validation import ExtractionResponse, ExtractedCriterion
    schema = ExtractionResponse.model_json_schema()
    criterion = schema['$defs']['ExtractedCriterion']
    assert set(criterion['required']) == set(CLINICAL_FIELDS)
    assert criterion['additionalProperties'] is False
    assert criterion['properties']['dependencies']['anyOf'][0]['items']['$ref'].endswith('/ExtractedCriterion')
    for nct_id in ['NCT06774027', 'NCT04331067']:
        units = visitor.sections(visitor.select_source(nct_id))
        for unit in units:
            assert len(unit['source'].text.encode()) <= visitor.SECTION_BYTES + len('Exclusion Criteria:\n')
            instruction = unit['messages'][0]['content']
            assert 'Required JSON schema:' in instruction
            assert json.loads(instruction.split('Required JSON schema: ',1)[1]) == schema
    assert set(ExtractedCriterion.model_fields) == set(CLINICAL_FIELDS)


def test_provider_json_mode_and_truncation_are_not_schema_or_quote_success(prepared, monkeypatch):
    calls = []
    async def post(self, url, **kwargs):
        calls.append(1)
        assert kwargs['json']['response_format'] == {'type':'json_object'}
        assert kwargs['json']['max_tokens'] == visitor.OUTPUT_LIMIT
        return httpx.Response(200, json={'model':visitor.DEFAULT_MODEL,'choices':[{'finish_reason':'length','message':{'content':'{"criteria": ['}}]})
    monkeypatch.setattr(httpx.AsyncClient, 'post', post)
    result = client.post('/visitor-analysis/run', json=approval(quote(prepared[0]))).json()
    assert len(calls) == 1 and result['status'] == 'incomplete'
    section = result['sections'][0]
    assert section['error'] == 'incomplete_response'
    assert section['diagnostics'][0]['category'] == 'incomplete_response'
    assert result['sections'][1]['status'] == 'not_requested'



def test_later_schema_failure_retains_validated_sections_without_paid_retry(prepared, monkeypatch):
    source = visitor.select_source(prepared[0]['nct_id'], prepared[0]['snapshot'])
    source = replace(source, text=source.text + '\nInclusion Criteria:\nthird fixture requirement')
    calls = []
    async def provider(messages, key, disconnected):
        calls.append(1)
        value = json.loads(content(messages))
        if len(calls) == 2:
            value['criteria'][0]['threshold'] = 18
        return json.dumps(value)
    monkeypatch.setattr(visitor, 'provider', provider)
    plan = {'source':source,'units':visitor.sections(source),'quote':{'maximum_cost_usd':'0.1'}}
    result = asyncio.run(visitor.extract(plan, KEY, asyncio.Event()))
    assert result['status'] == 'incomplete' and not result['full_source_coverage_validated']
    assert len(calls) == 2
    assert result['sections'][0]['status'] == 'validated' and result['sections'][0]['criteria']
    assert result['sections'][1]['diagnostics'][0]['field'] == 'criteria.0.threshold'
    assert result['sections'][2]['status'] == 'not_requested'
    assert KEY not in json.dumps(result)
