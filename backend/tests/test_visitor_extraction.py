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
    assert result.status_code == 200 and result.json()['status'] == 'review_required'
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
    assert result['status'] == 'review_required' and not result['interpretation_complete'] and not result['executable_mapping'] and result['human_review_required']
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
        assert result['status'] == 'review_required'
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
    assert len(calls) == 2 and result['status'] == 'review_required'
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
            assert 'Schema: ' in instruction
            from backend.app.source_interpretation import Response
            assert json.loads(instruction.split('Schema: ',1)[1]) == Response.model_json_schema()
            assert 'source_passages' in json.loads(unit['messages'][-1]['content'])
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



def source_meaning(messages, operator='NONE'):
    data = json.loads(messages[-1]['content'])
    values = []
    for passage in data['source_passages']:
        row = dict.fromkeys(['cohort','biomarker','assay','comparator','threshold','unit','temporal_constraint','dependencies'])
        row.update(source_id=passage['source_id'], logical_operator=operator)
        values.append(row)
    return {'interpretations': values}


def test_source_first_nct06774027_accounts_for_every_original_character(monkeypatch):
    source = visitor.select_source('NCT06774027')
    units = visitor.sections(source)
    from backend.app.source_interpretation import inventory
    originals = inventory(source)
    assert len(originals) == 7
    assert 'Cohort 4:' in originals[3]['text'] and originals[3]['scope_ambiguous']
    calls = []
    async def provider(messages, key, disconnected):
        calls.append(1)
        return json.dumps(source_meaning(messages))
    monkeypatch.setattr(visitor, 'provider', provider)
    result = asyncio.run(visitor.extract({'source':source,'units':units,'quote':{'maximum_cost_usd':'0.1'}},KEY,asyncio.Event()))
    assert len(calls) == len(units)
    assert result['status'] == 'review_required'
    assert result['source_inventory_complete'] and result['full_source_coverage_validated']
    assert not result['interpretation_complete'] and result['unresolved_count'] >= 3
    assert len(result['source_passages']) == 7
    for record in result['source_passages']:
        assert source.text[record['start']:record['end']] == record['text']
    cohort = next(node for section in result['sections'] for node in section['criteria'] if 'Cohort 4:' in node['original_text'])
    assert cohort['logical_operator'] is None and cohort['cohort'] is None and cohort['dependencies'] is None
    assert not result['executable_mapping']


@pytest.mark.parametrize('failure', ['omitted', 'unknown_id', 'duplicate', 'changed_field', 'bad_dependency_quote', 'malformed'])
def test_source_first_omissions_and_unsupported_claims_cannot_be_complete(monkeypatch, failure):
    source = visitor.select_source('NCT06774027'); units = visitor.sections(source); calls=[]
    async def provider(messages, key, disconnected):
        calls.append(1); value=source_meaning(messages)
        if failure=='omitted':value['interpretations'].pop(0)
        elif failure=='unknown_id':value['interpretations'][0]['source_id']='invented-source'
        elif failure=='duplicate':value['interpretations'].append(value['interpretations'][0])
        elif failure=='changed_field':value['interpretations'][0]['threshold']='999 years'
        elif failure=='bad_dependency_quote':
            child=dict(value['interpretations'][0]);child.pop('source_id');child['quotation']='invented quotation'
            value['interpretations'][0].update(logical_operator='AND', dependencies=[child,child])
        elif failure=='malformed':return '{"interpretations": ['
        return json.dumps(value)
    monkeypatch.setattr(visitor,'provider',provider)
    result=asyncio.run(visitor.extract({'source':source,'units':units,'quote':{'maximum_cost_usd':'0.1'}},KEY,asyncio.Event()))
    assert result['status']=='incomplete' and not result['full_source_coverage_validated'] and not result['interpretation_complete']
    assert result['source_inventory_complete'] and len(result['source_passages'])==7
    assert len(calls)==1 and result['sections'][1]['status']=='not_requested'
    assert all(source.text[p['start']:p['end']]==p['text'] for p in result['source_passages'])
    if failure not in ('malformed',):assert result['sections'][0]['criteria']
    assert KEY not in json.dumps(result)


def test_source_first_later_invalid_section_preserves_prior_interpretations(prepared,monkeypatch):
    source=visitor.select_source(prepared[0]['nct_id'],prepared[0]['snapshot']);calls=[]
    async def provider(messages,key,disconnected):
        calls.append(1)
        return json.dumps(source_meaning(messages)) if len(calls)==1 else '{"interpretations":null}'
    monkeypatch.setattr(visitor,'provider',provider)
    result=asyncio.run(visitor.extract({'source':source,'units':visitor.sections(source),'quote':{'maximum_cost_usd':'0.1'}},KEY,asyncio.Event()))
    assert result['status']=='incomplete' and len(calls)==2
    assert result['sections'][0]['status']=='validated' and result['sections'][0]['criteria']
    assert result['sections'][1]['status']=='failed'


def test_numbered_boolean_dependencies_validate_without_dropping_number_prefix(prepared):
    from backend.app.source_interpretation import inventory, messages, interpret
    source=visitor.select_source(prepared[0]['nct_id'],prepared[0]['snapshot'])
    source=replace(source,text='Inclusion Criteria:\n1. A AND (B OR C)')
    passages=inventory(source); value=source_meaning(messages(source,passages))
    def child(quote,operator='NONE',dependencies=None):
        row=dict.fromkeys(['cohort','biomarker','assay','comparator','threshold','unit','temporal_constraint'])
        row.update(quotation=quote,logical_operator=operator,dependencies=dependencies);return row
    value['interpretations'][0].update(logical_operator='AND',dependencies=[child('A'),child('(B OR C)','OR',[child('B'),child('C')])])
    nodes,evidence,ledger,errors=interpret(json.dumps(value),source,passages,'2026-10-30T00:00:00Z')
    assert not errors and ledger[0]['interpretation_status']=='unresolved'
    assert nodes[0]['logical_operator']=='AND'
    assert nodes[0]['original_text']=='1. A AND (B OR C)'
    assert nodes[0]['dependencies'][1]['dependencies'][1]['original_text']=='C'
    for item in evidence:
        span=item['original_span'];assert source.text[span['start']:span['end']]


def test_source_first_ambiguous_boundaries_remain_one_verbatim_unresolved_group(prepared):
    from backend.app.source_interpretation import inventory, messages, interpret
    source=visitor.select_source(prepared[0]['nct_id'],prepared[0]['snapshot'])
    source=replace(source,text='Inclusion Criteria:\nFor cohort A:\n  * marker present\n  * assay positive')
    passages=inventory(source);assert len(passages)==1 and passages[0]['boundary_ambiguous']
    value=source_meaning(messages(source,passages))
    nodes,_,ledger,errors=interpret(json.dumps(value),source,passages,'2026-10-30T00:00:00Z')
    assert not errors and ledger[0]['interpretation_status']=='unresolved'
    assert nodes[0]['original_text']==source.text.split('\n',1)[1]
    assert nodes[0]['logical_operator'] is None and nodes[0]['dependencies'] is None


@pytest.mark.parametrize('quotation', ['A', 'partial quotation', ''])
def test_source_first_evidence_never_guesses_repeated_or_incomplete_quotations(quotation):
    from backend.app.source_interpretation import unique_quote
    text = 'A AND A; partial quotations'
    with pytest.raises(ValueError):
        unique_quote(text, quotation, 0, len(text))


def test_source_first_exact_unicode_offsets_do_not_normalize_quotations(prepared):
    from backend.app.source_interpretation import inventory, messages, interpret
    source = visitor.select_source(prepared[0]['nct_id'],prepared[0]['snapshot'])
    source = replace(source,text='Inclusion Criteria:\n1. Age \u226518 years')
    passages = inventory(source)
    value = source_meaning(messages(source,passages))
    value['interpretations'][0].update(comparator='>=', threshold='18', unit='years')
    nodes, _, ledger, errors = interpret(json.dumps(value),source,passages,'2026-10-30T00:00:00Z')
    assert nodes[0]['comparator'] is None and nodes[0]['threshold'] == '18'
    assert errors[0]['code'] == 'ambiguous_interpretation_evidence'
    assert ledger[0]['interpretation_status'] == 'unsupported'
    value['interpretations'][0]['comparator']='\u2265'
    nodes, evidence, ledger, errors = interpret(json.dumps(value),source,passages,'2026-10-30T00:00:00Z')
    assert not errors and ledger[0]['interpretation_status']=='validated'
    span=evidence[0]['fields']['comparator']
    assert source.text[span['start']:span['end']]=='\u2265'



def test_source_first_atomic_sections_merge_exactly_without_model_source_copy(prepared, monkeypatch):
    source=visitor.select_source(prepared[0]['nct_id'],prepared[0]['snapshot'])
    source=replace(source,text='Inclusion Criteria:\n1. Age \u226518 years\n\nExclusion Criteria:\n1. Prior surgery')
    calls=[]
    async def provider(messages,key,disconnected):
        calls.append(1)
        return json.dumps(source_meaning(messages))
    monkeypatch.setattr(visitor,'provider',provider)
    result=asyncio.run(visitor.extract({'source':source,'units':visitor.sections(source),'quote':{'maximum_cost_usd':'0.1'}},KEY,asyncio.Event()))
    assert len(calls)==2 and result['status']=='review_required'
    assert not result['interpretation_complete'] and result['full_source_coverage_validated']
    assert result['human_review_required'] and not result['executable_mapping']
    assert [n['original_text'] for n in result['merged_criteria']]==['1. Age \u226518 years','1. Prior surgery']
    for section in result['sections']:
        for node,entry in zip(section['criteria'],section['source_evidence']):
            span=entry['original_span']
            assert source.text[span['start']:span['end']]==node['original_text']



def test_source_first_nested_unresolved_logic_never_claims_complete_interpretation(prepared, monkeypatch):
    source = visitor.select_source(prepared[0]['nct_id'], prepared[0]['snapshot'])
    source = replace(source, text='Inclusion Criteria:\n1. A AND (B OR C)')
    def child(quotation, operator):
        row = dict.fromkeys(['cohort', 'biomarker', 'assay', 'comparator', 'threshold', 'unit', 'temporal_constraint', 'dependencies'])
        row.update(quotation=quotation, logical_operator=operator)
        return row
    async def provider(messages, key, disconnected):
        value = source_meaning(messages)
        value['interpretations'][0].update(logical_operator='AND', dependencies=[child('A', 'NONE'), child('(B OR C)', None)])
        return json.dumps(value)
    monkeypatch.setattr(visitor, 'provider', provider)
    result = asyncio.run(visitor.extract({'source': source, 'units': visitor.sections(source), 'quote': {'maximum_cost_usd': '0.1'}}, KEY, asyncio.Event()))
    assert result['status'] == 'review_required'
    assert result['full_source_coverage_validated'] and not result['interpretation_complete']
    assert result['unresolved_count'] == 1
    assert result['source_passages'][0]['interpretation_status'] == 'unresolved'
    root = result['merged_criteria'][0]
    assert root['logical_operator'] == 'AND'
    assert root['dependencies'][1]['logical_operator'] is None
    assert root['dependencies'][1]['original_text'] == '(B OR C)'
    assert result['human_review_required'] and not result['executable_mapping']


@pytest.mark.parametrize('text,fields', [
    ('Age \u226518 years', {'comparator': '\u2265', 'threshold': '18', 'unit': 'years'}),
    ('1. Age \u226518 years', {'comparator': '\u2265', 'threshold': '18', 'unit': 'years'}),
    ('Life expectancy \u22653 months', {'comparator': '\u2265', 'threshold': '3', 'unit': 'months'}),
    ('2. Life expectancy \u22653 months', {'comparator': '\u2265', 'threshold': '3', 'unit': 'months'}),
    ('PD-L1 CPS \u226510', {'biomarker': 'PD-L1', 'assay': 'CPS', 'comparator': '\u2265', 'threshold': '10'}),
    ('Cohort 1: HER2 IHC 3+', {'cohort': 'Cohort 1', 'biomarker': 'HER2', 'assay': 'IHC', 'threshold': '3+'}),
])
def test_supported_scalar_fields_survive_numbered_and_single_line_sources(prepared, text, fields):
    from backend.app.source_interpretation import inventory, messages, interpret
    source = replace(visitor.select_source(prepared[0]['nct_id'], prepared[0]['snapshot']), text='Inclusion Criteria:\n'+text)
    passages = inventory(source)
    value = source_meaning(messages(source, passages))
    value['interpretations'][0].update(fields)
    nodes, evidence, ledger, errors = interpret(json.dumps(value), source, passages, '2026-10-30T00:00:00Z')
    assert not errors and not passages[0]['boundary_ambiguous']
    assert {name: nodes[0][name] for name in fields} == fields
    for name, val in fields.items():
        span = evidence[0]['fields'][name]
        assert source.text[span['start']:span['end']] == val
        assert ledger[0]['field_status'][name] == 'retained'


def test_saved_nct06774027_numeric_interpretations_reach_merged_results(monkeypatch):
    source = visitor.select_source('NCT06774027')
    calls = []
    async def provider(messages, key, disconnected):
        calls.append(1)
        value = source_meaning(messages)
        for row, passage in zip(value['interpretations'], json.loads(messages[-1]['content'])['source_passages']):
            if 'aged 18 years' in passage['text']:
                row.update(threshold='18', unit='years', comparator='or greater')
            elif 'life expectancy' in passage['text']:
                row.update(threshold='3', unit='months', comparator='at least')
        return json.dumps(value)
    monkeypatch.setattr(visitor, 'provider', provider)
    units = visitor.sections(source)
    result = asyncio.run(visitor.extract({'source': source, 'units': units, 'quote': {'maximum_cost_usd': '0.1'}}, KEY, asyncio.Event()))
    assert len(calls) == len(units) == 2
    assert result['full_source_coverage_validated'] and result['status'] == 'review_required'
    assert not result['interpretation_complete'] and not result['executable_mapping']
    assert result['merged_criteria'][0]['threshold'] == '18'
    assert result['merged_criteria'][0]['logical_operator'] is None
    assert result['merged_criteria'][1]['threshold'] == '3'
    assert result['merged_criteria'][1]['unit'] == 'months'
    assert 'field_status' not in result['source_passages'][0]


def test_supported_field_survives_another_rejected_field_without_validating_the_section(prepared, monkeypatch):
    source = replace(visitor.select_source(prepared[0]['nct_id'], prepared[0]['snapshot']), text='Inclusion Criteria:\n1. Age \u226518 years\nExclusion Criteria:\n1. Prior surgery')
    calls = []
    async def provider(messages, key, disconnected):
        calls.append(1)
        value = source_meaning(messages)
        value['interpretations'][0].update(threshold='18', unit='years', assay='invented-assay')
        return json.dumps(value)
    monkeypatch.setattr(visitor, 'provider', provider)
    result = asyncio.run(visitor.extract({'source': source, 'units': visitor.sections(source), 'quote': {'maximum_cost_usd': '0.1'}}, KEY, asyncio.Event()))
    assert result['status'] == 'incomplete' and not result['full_source_coverage_validated']
    assert len(calls) == 1 and result['sections'][1]['status'] == 'not_requested'
    node = result['sections'][0]['criteria'][0]
    assert node['threshold'] == '18' and node['unit'] == 'years' and node['assay'] is None
    assert result['source_passages'][0]['interpretation_status'] == 'unsupported'
    assert 'field_status' not in result['source_passages'][0]
    assert any(d.get('field') == 'assay' for d in result['sections'][0]['diagnostics'])


@pytest.mark.parametrize('change,category', [({'threshold': 18}, 'incorrect_type'), ({'unit': ['years']}, 'incorrect_type'), ({'threshold': 'missing'}, 'missing_required_property')])
def test_missing_and_malformed_clinical_fields_are_never_coerced(prepared, change, category):
    from backend.app.source_interpretation import inventory, messages, interpret
    source = replace(visitor.select_source(prepared[0]['nct_id'], prepared[0]['snapshot']), text='Inclusion Criteria:\nAge \u226518 years')
    passages = inventory(source); value = source_meaning(messages(source, passages))
    if change.get('threshold') == 'missing':
        del value['interpretations'][0]['threshold']
    else:
        value['interpretations'][0].update(change)
    nodes, _, _, errors = interpret(json.dumps(value), source, passages, '2026-10-30T00:00:00Z')
    assert not nodes and any(e.get('category') == category for e in errors)


def test_null_numeric_fields_are_not_invented_and_ambiguous_cohort_fields_are_explicitly_withheld(monkeypatch):
    from backend.app.source_interpretation import inventory, messages, interpret
    source = visitor.select_source('NCT06774027'); passages = inventory(source)
    value = source_meaning(messages(source, passages))
    value['interpretations'][3].update(cohort='Cohort 1', biomarker='HR+', threshold='1')
    nodes, _, ledger, errors = interpret(json.dumps(value), source, passages, '2026-10-30T00:00:00Z')
    assert not errors
    assert nodes[0]['threshold'] == '18'
    assert ledger[0]['field_origin']['threshold'] == 'literal_source_rule'
    cohort = next(n for n in nodes if 'Cohort 4:' in n['original_text'])
    assert cohort['cohort'] is None and cohort['biomarker'] is None and cohort['threshold'] is None
    assert ledger[3]['field_status']['threshold'] == 'withheld_ambiguous_scope_or_boundary'
    assert ledger[3]['interpretation_status'] == 'unresolved'


def test_nested_boolean_clinical_values_and_offsets_are_preserved(prepared):
    from backend.app.source_interpretation import inventory, messages, interpret
    source = replace(visitor.select_source(prepared[0]['nct_id'], prepared[0]['snapshot']), text='Inclusion Criteria:\n1. Age \u226518 years AND (PD-L1 CPS \u226510 OR HER2 IHC 3+)')
    passages = inventory(source); value = source_meaning(messages(source, passages))
    def child(text, **fields):
        node = dict.fromkeys(['cohort', 'biomarker', 'assay', 'comparator', 'threshold', 'unit', 'temporal_constraint', 'dependencies'])
        node.update(quotation=text, logical_operator='NONE');node.update(fields);return node
    age = child('Age \u226518 years', comparator='\u2265', threshold='18', unit='years')
    marker = child('PD-L1 CPS \u226510', biomarker='PD-L1', assay='CPS', comparator='\u2265', threshold='10')
    her2 = child('HER2 IHC 3+', biomarker='HER2', assay='IHC', threshold='3+')
    group = child('(PD-L1 CPS \u226510 OR HER2 IHC 3+)', logical_operator='OR', dependencies=[marker, her2])
    value['interpretations'][0].update(logical_operator='AND', dependencies=[age, group])
    nodes, evidence, ledger, errors = interpret(json.dumps(value), source, passages, '2026-10-30T00:00:00Z')
    assert not errors and ledger[0]['interpretation_status'] == 'validated'
    assert nodes[0]['dependencies'][0]['threshold'] == '18'
    assert nodes[0]['dependencies'][1]['dependencies'][0]['threshold'] == '10'
    assert nodes[0]['dependencies'][1]['dependencies'][1]['threshold'] == '3+'
    assert len(evidence) == 5



def test_exact_substring_that_fails_numeric_validation_is_not_reported_retained(prepared):
    from backend.app.source_interpretation import inventory, messages, interpret
    source = replace(visitor.select_source(prepared[0]['nct_id'], prepared[0]['snapshot']), text='Inclusion Criteria:\nAge \u226518.5 years')
    passages = inventory(source); value = source_meaning(messages(source, passages))
    value['interpretations'][0].update(threshold='18', unit='years')
    nodes, _, ledger, errors = interpret(json.dumps(value), source, passages, '2026-10-30T00:00:00Z')
    assert not nodes and any(error['code'] == 'partial_numeric_threshold' for error in errors)
    assert ledger[0]['field_status']['threshold'] == 'not_retained_validation_failed'
    assert 'retained' not in ledger[0]['field_status'].values()



def test_all_null_model_output_preserves_literal_facts_without_claiming_model_or_clinical_success(monkeypatch):
    source = visitor.select_source('NCT06774027')
    async def provider(messages, key, disconnected):
        return json.dumps(source_meaning(messages))
    monkeypatch.setattr(visitor, 'provider', provider)
    plan = {'source': source, 'units': visitor.sections(source), 'quote': {'maximum_cost_usd':'0.1'}, 'debug': True}
    result = asyncio.run(visitor.extract(plan, KEY, asyncio.Event()))
    assert result['full_source_coverage_validated'] and not result['interpretation_complete']
    assert result['literal_source_rules_used'] and result['status'] == 'review_required'
    assert len(result['merged_criteria']) == 7
    assert result['merged_criteria'][0]['threshold'] == '18'
    assert result['merged_criteria'][1]['threshold'] == '3'
    stats = result['debug_diagnostics']['sections']
    assert sum(s['model_fields_received'] for s in stats) == 0
    assert sum(s['fields_null'] for s in stats) == 49
    assert sum(s['model_fields_accepted'] for s in stats) == 0
    assert sum(s['deterministic_fields_accepted'] for s in stats) == 6
    assert not result['executable_mapping']


@pytest.mark.parametrize('text', [
    'Age under 18 years', 'Age >=18 years unless waived', 'Not aged 18 years or greater',
    'Age between 18 and 65 years', 'Age >=18 years or age >=21 years', '1. Age >=1 years',
    'Life expectancy unknown', 'Age greater than eighteen years',
])
def test_literal_rules_abstain_on_unsupported_or_ambiguous_wording(text):
    from backend.app.source_interpretation import literal_fields
    assert not literal_fields({'text':text,'scope_ambiguous':False,'boundary_ambiguous':False})


def test_literal_rules_do_not_mix_with_conflicting_model_values(prepared):
    from backend.app.source_interpretation import inventory, messages, interpret
    source = replace(visitor.select_source(prepared[0]['nct_id'], prepared[0]['snapshot']),text='Inclusion Criteria:\nAge >=18 years; review after 20 days')
    passages=inventory(source);value=source_meaning(messages(source,passages))
    value['interpretations'][0]['threshold']='20'
    nodes,_,records,errors=interpret(json.dumps(value),source,passages,'2026-10-30T00:00:00Z')
    assert not errors and nodes[0]['comparator'] is None and nodes[0]['unit'] is None
    assert records[0]['field_origin']['threshold']=='model'


def test_safe_diagnostic_counts_identify_missing_unknown_and_withheld_fields():
    from backend.app.source_interpretation import diagnostic_counts
    fields = dict.fromkeys(['cohort','biomarker','assay','comparator','threshold','unit','temporal_constraint','dependencies'])
    item = dict(fields,source_id='not-known',logical_operator='NONE',threshold='999',unit='years')
    passages=[{'source_id':'source-0-10','scope_ambiguous':False,'boundary_ambiguous':False}]
    stats=diagnostic_counts(json.dumps({'interpretations':[item]}),passages,[],[],[{'code':'unknown_source_segment'}])
    assert stats['model_fields_received']==2 and stats['fields_rejected']==2
    assert stats['fields_matched_to_passages']==0 and stats['fields_missing']==7
    assert '999' not in json.dumps(stats) and 'not-known' not in json.dumps(stats)
    item['source_id']='source-0-10';passages[0]['scope_ambiguous']=True
    stats=diagnostic_counts(json.dumps({'interpretations':[item]}),passages,[],[],[])
    assert stats['fields_withheld']==2 and stats['fields_rejected']==0


def test_debug_requires_explicit_enablement_and_operator_authentication(prepared,monkeypatch):
    calls=[]
    async def provider(messages,key,disconnected):
        calls.append(1);return json.dumps(source_meaning(messages))
    monkeypatch.setattr(visitor,'provider',provider)
    value=quote(prepared[0]);body=approval(value)
    monkeypatch.delenv('TRIALLENS_EXTRACTION_DEBUG',raising=False)
    assert client.post('/visitor-analysis/run',json=body,headers={'X-TrialLens-Debug':'1'}).status_code==403
    monkeypatch.setenv('TRIALLENS_EXTRACTION_DEBUG','1')
    monkeypatch.setenv('TRIALLENS_OPERATOR_TOKEN','non-secret-debug-operator-0123456789')
    assert client.post('/visitor-analysis/run',json=body,headers={'X-TrialLens-Debug':'1'}).status_code==401
    assert calls==[]
    response=client.post('/visitor-analysis/run',json=body,headers={'X-TrialLens-Debug':'1','Authorization':'Bearer non-secret-debug-operator-0123456789'})
    assert response.status_code==200 and 'debug_diagnostics' in response.json()
    assert KEY not in json.dumps(response.json()['debug_diagnostics'])
    public=client.post('/visitor-analysis/run',json=approval(quote(prepared[0]))).json()
    assert 'debug_diagnostics' not in public
    assert all('field_status' not in p and 'field_origin' not in p for p in public['source_passages'])



def test_bad_dependency_evidence_keeps_valid_root_fields_but_rejects_section(prepared):
    from backend.app.source_interpretation import inventory, messages, interpret, diagnostic_counts
    source=replace(visitor.select_source(prepared[0]['nct_id'],prepared[0]['snapshot']),text='Inclusion Criteria:\n1. Age >=18 years AND marker present')
    passages=inventory(source);value=source_meaning(messages(source,passages))
    child=dict(value['interpretations'][0]);child.pop('source_id');child.update(quotation='invented dependency')
    value['interpretations'][0].update(threshold='18',unit='years',logical_operator='AND',dependencies=[child,child])
    nodes,evidence,records,errors=interpret(json.dumps(value),source,passages,'2026-10-30T00:00:00Z')
    assert errors and nodes[0]['threshold']=='18' and nodes[0]['logical_operator'] is None
    assert nodes[0]['dependencies'] is None and len(evidence)==1
    counts=diagnostic_counts(json.dumps(value),passages,nodes,records,errors)
    assert counts['model_fields_received']==2 and counts['model_fields_accepted']==2
    assert counts['fields_accepted']>=2 and counts['evidence_matching_failures']==1
    assert records[0]['interpretation_status']=='unsupported'



@pytest.mark.parametrize('text,number,unit', [
    ('Age >=18 years','18','years'), ('Age \u226518 years','18','years'),
    ('Life expectancy \u22653 months','3','months'), ('Estimated life expectancy of at least at 3 months per investigator assessment.','3','months'),
])
def test_literal_source_rules_preserve_exact_numeric_fact_and_offsets(prepared,text,number,unit):
    from backend.app.source_interpretation import inventory,messages,interpret
    source=replace(visitor.select_source(prepared[0]['nct_id'],prepared[0]['snapshot']),text='Inclusion Criteria:\n'+text)
    passages=inventory(source);value=source_meaning(messages(source,passages))
    nodes,evidence,records,errors=interpret(json.dumps(value),source,passages,'2026-10-30T00:00:00Z')
    assert not errors and nodes[0]['threshold']==number and nodes[0]['unit']==unit
    assert records[0]['field_origin']['threshold']=='literal_source_rule'
    for name,span in evidence[0]['fields'].items():
        assert source.text[span['start']:span['end']]==nodes[0][name]


def test_source_only_atomic_answer_is_not_complete_clinical_interpretation(prepared,monkeypatch):
    async def provider(messages,key,disconnected):return json.dumps(source_meaning(messages))
    monkeypatch.setattr(visitor,'provider',provider)
    result=client.post('/visitor-analysis/run',json=approval(quote(prepared[0]))).json()
    assert result['full_source_coverage_validated'] and not result['interpretation_complete']
    assert result['status']=='review_required' and all(r['unresolved_reason']=='no_structured_fields' for r in result['source_passages'])


def test_malformed_response_diagnostics_report_schema_failure_without_raw_content():
    from backend.app.source_interpretation import diagnostic_counts
    stats=diagnostic_counts('{"interpretations":[ private-data',[],[],[],[{'code':'invalid_json_or_schema'}])
    assert stats['schema_validation_failures']==1 and stats['fields_accepted']==0
    assert not stats['counts_available']
    assert 'private-data' not in json.dumps(stats)



def test_legacy_response_diagnostics_count_actual_fields_instead_of_reporting_zero():
    from backend.app.source_interpretation import diagnostic_counts
    node=dict.fromkeys(['cohort','biomarker','assay','comparator','threshold','unit','temporal_constraint','dependencies'])
    node.update(criterion_id='legacy',threshold='18',unit='years')
    stats=diagnostic_counts(json.dumps({'criteria':[node]}),[],[node],[],[])
    assert stats['counts_available'] and stats['response_contract']=='legacy_criteria'
    assert stats['model_fields_received']==2 and stats['model_fields_accepted']==2
    assert stats['fields_rejected']==0 and stats['fields_missing']==0


def test_debug_counts_are_available_for_authenticated_legacy_requests(prepared,monkeypatch):
    monkeypatch.setenv('TRIALLENS_EXTRACTION_DEBUG','1')
    monkeypatch.setenv('TRIALLENS_OPERATOR_TOKEN','non-secret-debug-operator-0123456789')
    async def provider(messages,key,disconnected):return content(messages)
    monkeypatch.setattr(visitor,'provider',provider)
    response=client.post('/visitor-analysis/run',json=approval(quote(prepared[0])),headers={'X-TrialLens-Debug':'1','Authorization':'Bearer non-secret-debug-operator-0123456789'})
    assert response.status_code==200
    stats=response.json()['debug_diagnostics']['sections']
    assert len(stats)==2 and all(row['response_contract']=='legacy_criteria' for row in stats)
    assert sum(row['fields_null'] for row in stats)==14
