import asyncio
import hashlib
import json
import re
import os
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from backend.research_public import app
from backend.app import visitor_extraction as visitor, research_catalog, research_api
from backend.app.extraction_prompt import CLINICAL_FIELDS
from backend.app.trial_extraction_api import select_source
from backend.app.nebius import NebiusError
from backend import serve_public
from scripts.public_release import ROOT, runtime_files

client = TestClient(app)


def test_public_routes_enable_only_visitor_inference(monkeypatch, caplog):
    monkeypatch.setenv('TRIALLENS_BYOK_ENABLED', '1')
    monkeypatch.setenv('NEBIUS_API_KEY', 'owner-account-never-use')
    async def forbidden(*args, **kwargs):
        pytest.fail('Paid transport forbidden')
    monkeypatch.setattr(visitor, 'provider', forbidden)
    sentinel = 'non-secret-infrastructure-test'
    for prefix in ('', '/api'):
        assert client.get(prefix + '/health').json()['visitor_extraction_enabled'] is True
        for route in ('/visitor-analysis/prepare', '/visitor-analysis/run'):
            response = client.post(prefix + route, json={'api_key': sentinel}, headers={'X-Forwarded-Proto': 'https'})
            assert response.status_code == 422 and sentinel not in response.text
            assert response.headers['Cache-Control'] == 'no-store'
        for route in ('/operator/session', '/saved-trials/configuration', '/annotations/NCT04331067', '/openapi.json', '/docs',
                      '/results/nebius/live-request.claim', '/results/extraction/example/raw_response.json', '/.env'):
            assert client.get(prefix + route).status_code == 404
    assert sentinel not in caplog.text
    settings = serve_public.settings()
    assert settings['proxy_headers'] is False and settings['access_log'] is False
    assert settings['workers'] == 1


def test_public_research_artifacts_and_executable_planner_are_available():
    assert client.get('/api/readiness').status_code == 200
    saved = client.get('/api/research/trials').json()['trials']
    trial = next(t for t in saved if t['nct_id'] == 'NCT04331067')
    analysis = client.get('/api/clinical-trials/NCT04331067/analysis', params={k: trial[k] for k in ('snapshot', 'snapshot_sha256')})
    assert analysis.status_code == 200 and not analysis.json()['inference']['request_sent']
    assert not analysis.json()['assessment_available']
    for identifier in research_catalog.ARTIFACTS:
        assert client.get('/api/research/evaluation/' + identifier).status_code == 200, identifier
    scenarios = client.get('/api/research/planner/scenarios').json()['scenarios']
    before = client.post('/api/research/planner/evaluate', json={'scenario': scenarios[0]['id'], 'budget': 1}).json()
    report = next(row for row in before['reports'] if row['selection_probability'] > 0)
    after = client.post('/api/research/planner/evaluate', json={'scenario': scenarios[0]['id'], 'budget': 1, 'outcomes': {report['id']: 1}}).json()
    assert before['bdd_nodes'] > 2 and after['spent'] <= 1
    assert after['protocol_probabilities'] != before['protocol_probabilities']
    assert before['expected_policy_metrics']['max_model_risk'] <= .08 + 1e-8
    stop = client.post('/api/research/planner/evaluate', json={'scenario': scenarios[0]['id'], 'budget': 0}).json()
    assert stop['stop_probability'] == pytest.approx(1)
    assert all(row['selection_probability'] == 0 for row in stop['reports'])
    assert client.get('/api/research/results').status_code == 200


def test_clean_public_package_uses_only_bundled_sources_and_aggregate_artifacts(tmp_path):
    package = tmp_path / 'runtime'
    for name in ('backend/app', 'frontend/dist'):
        shutil.copytree(ROOT / name, package / name, ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('public_demo.py', 'research_public.py', 'serve_public.py'):
        shutil.copyfile(ROOT / 'backend' / name, package / 'backend' / name)
    for name in runtime_files():
        target = package / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    assert not (package / 'results/nebius').exists()
    assert not (package / 'results/extraction').exists()
    script = '''import sys,socket
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
connect=socket.socket.connect
def guarded(self, address):
    if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','::1','localhost'):
        raise AssertionError('External network forbidden')
    return connect(self,address)
socket.socket.connect=guarded
from backend.research_public import app
from fastapi.testclient import TestClient
with TestClient(app) as c:
    assert c.get('/').status_code==200
    assert c.get('/api/readiness').status_code==200
    assert c.get('/api/health').json()['visitor_extraction_enabled'] is True
    trial=c.get('/api/clinical-trials/search',params={'nct_id':'NCT04331067'}).json()['trials'][0]
    r=c.get('/api/clinical-trials/NCT04331067/analysis',params={k:trial[k] for k in ('snapshot','snapshot_sha256')})
    assert r.status_code==200 and not r.json()['inference']['request_sent']
    assert not r.json()['saved_extractions']
    artifacts=c.get('/api/research/evaluation').json()['artifacts']
    assert all(row['available'] for row in artifacts)
    for row in artifacts:
        assert c.get('/api/research/evaluation/'+row['id']).status_code==200
    scenario=c.get('/api/research/planner/scenarios').json()['scenarios'][0]['id']
    result=c.post('/api/research/planner/evaluate',json={'scenario':scenario,'budget':1})
    assert result.status_code==200 and result.json()['bdd_nodes']>2
    assert c.get('/api/operator/session').status_code==404
    assert c.post('/api/visitor-analysis/run',json={'api_key':'non-secret-isolation-fixture'}).status_code==422
print('Isolated runtime passed')
'''
    environment = {'SystemRoot': os.environ.get('SystemRoot', 'C:/Windows'), 'TEMP': str(tmp_path), 'TMP': str(tmp_path),
                   'PYTHONIOENCODING': 'utf-8', 'TRIALLENS_BYOK_ENABLED': '1'}
    result = subprocess.run([sys.executable, '-I', '-B', '-c', script], cwd=package, env=environment,
                            capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stderr
    assert 'Isolated runtime passed' in result.stdout


def test_render_and_container_configuration_are_consistent():
    docker = (ROOT / 'Dockerfile').read_text()
    render = (ROOT / 'render.yaml').read_text()
    assert 'ENV VITE_PUBLIC_RESEARCH=1' in docker and 'ENV VITE_PUBLIC_DEMO=0' in docker
    assert 'ENV TRIALLENS_BYOK_ENABLED=1' in docker
    assert 'COPY data/raw/trials/' in docker and 'COPY research/' in docker and 'COPY results/' in docker
    assert 'USER demo' in docker and 'python", "-B", "-m", "backend.serve_public' in docker
    assert 'healthCheckPath: /api/readiness' in render and 'autoDeployTrigger: "off"' in render
    assert 'key: TRIALLENS_BYOK_ENABLED\n        value: "1"' in render
    snapshots = [ROOT / name for name in runtime_files() if name.startswith('data/raw/trials/') and name.endswith('response.json')]
    assert len(snapshots) == 2
    for path in snapshots:
        payload = json.loads(path.read_bytes())
        assert payload.get('is_synthetic') is not True
        metadata = json.loads(path.with_name('metadata.json').read_bytes())
        assert metadata['source_url'].startswith('https://clinicaltrials.gov/api/v2/studies')


def section_fixture(messages):
    text = json.loads(messages[-1]['content'])['eligibility_text']
    heading = re.match(r'[^\n]+', text).group()
    body_start = len(heading) + 1
    starts = [m.start() for m in re.finditer(r'^\* ', text, re.M)]
    boundaries = starts + [len(text)]
    criteria, evidence = [], []
    for number, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        while end > start and text[end - 1] == '\n':
            end -= 1
        node = dict.fromkeys(CLINICAL_FIELDS)
        node.update(criterion_id=f'criterion-{number}', original_text=text[start:end], criterion_type='inclusion' if 'Inclusion' in heading else 'exclusion')
        criteria.append(node)
        evidence.append({'criterion_id': node['criterion_id'], 'original_span': {'start': start, 'end': end},
                         'polarity_span': {'start': 0, 'end': len(heading)}, 'fields': {}})
        # Mock schema exercise.
        if node['original_text'].startswith('* Women of childbearing potential'):
            split = text.index(' or ', start, end)
            children = []
            for child_number, (a, b) in enumerate(((start, split), (split + 4, end))):
                child = dict.fromkeys(CLINICAL_FIELDS)
                child.update(criterion_id=f'operand-{child_number}', original_text=text[a:b], criterion_type='inclusion')
                children.append(child)
                evidence.append({'criterion_id': child['criterion_id'], 'original_span': {'start': a, 'end': b},
                                 'polarity_span': {'start': 0, 'end': len(heading)}, 'fields': {}})
            node.update(logical_operator='OR', dependencies=children)
    assert text[body_start:starts[0]].strip() == ''
    return json.dumps({'criteria': criteria, 'evidence': evidence})


@pytest.mark.parametrize('failure', [None, 0, 1, 2, 'omission', 'dependency'])
def test_actual_nct04331067_all_sections_merge_and_partial_failure(monkeypatch, failure):
    source = select_source('NCT04331067')
    units = visitor.sections(source)
    assert len(units) == 3
    calls = []
    async def provider(messages, key, disconnected):
        section = len(calls)
        calls.append(section)
        if failure == section:
            raise NebiusError('incomplete_response')
        value = json.loads(section_fixture(messages))
        if failure == 'omission' and section == 0:
            value['criteria'].pop()
        if failure == 'dependency' and section == 0:
            dependency = next(node for node in value['criteria'] if node['dependencies'])['dependencies'][0]
            dependency['original_text'] = 'FABRICATED SOFTWARE FIXTURE'
        return json.dumps(value)
    monkeypatch.setattr(visitor, 'provider', provider)
    plan = {'source': source, 'units': units, 'quote': {'maximum_cost_usd': '0.1'}}
    result = asyncio.run(visitor.extract(plan, 'non-secret-fixture', asyncio.Event()))
    assert len(result['sections']) == 3
    if failure is not None:
        assert result['status'] == 'incomplete' and not result['full_source_coverage_validated']
        assert not result['merged_criteria']
        failed = failure if type(failure) is int else 0
        assert len(calls) == failed + 1
        assert all(section['status'] == 'validated' for section in result['sections'][:failed])
        return
    assert result['status'] == 'complete' and len(calls) == 3
    assert result['full_source_coverage_validated'] and result['human_review_required'] and not result['executable_mapping']
    assert any(node['dependencies'] for node in result['merged_criteria'])
    identifiers = []
    def collect(nodes):
        for node in nodes:
            identifiers.append(node['criterion_id'])
            collect(node['dependencies'] or [])
    collect(result['merged_criteria'])
    assert len(identifiers) == len(set(identifiers))
    for section in result['sections']:
        for entry in section['source_evidence']:
            span = entry['original_span']
            assert source.text[span['start']:span['end']]
    assert 'Absolute neutrophil count' in ''.join(node['original_text'] for node in result['merged_criteria'])



def test_public_search_prepare_approve_and_view_mocked_nvidia(monkeypatch):
    visitor.plans.clear(); visitor.attempts.clear(); visitor.active.clear()
    monkeypatch.setenv('TRIALLENS_BYOK_ENABLED', '1')
    monkeypatch.setenv('NEBIUS_INPUT_USD_PER_MILLION', '0.30')
    monkeypatch.setenv('NEBIUS_OUTPUT_USD_PER_MILLION', '0.90')
    monkeypatch.setenv('NEBIUS_API_KEY', 'operator-must-never-be-used')
    calls = []
    async def provider(messages, key, disconnected):
        assert key == 'public-visitor-software-fixture'
        calls.append(1)
        return section_fixture(messages)
    monkeypatch.setattr(visitor, 'provider', provider)
    trial = client.get('/api/clinical-trials/search', params={'nct_id': 'NCT04331067'}).json()['trials'][0]
    body = {k: trial[k] for k in ('nct_id', 'snapshot', 'snapshot_sha256')}
    quote = client.post('/api/visitor-analysis/prepare', json=body)
    assert quote.status_code == 200
    value = quote.json()
    assert value['request_count'] == 3
    result = client.post('/api/visitor-analysis/run', json={
        'analysis_id': value['analysis_id'], 'api_key': 'public-visitor-software-fixture',
        'confirmed': True, 'maximum_cost_usd': value['maximum_cost_usd']})
    assert result.status_code == 200
    assert result.json()['full_source_coverage_validated']
    assert len(calls) == 3
    assert result.headers['Cache-Control'] == 'no-store'
    assert 'public-visitor-software-fixture' not in result.text



def test_public_unexpected_visitor_errors_never_log_credentials(monkeypatch, caplog):
    monkeypatch.setenv('TRIALLENS_BYOK_ENABLED', '1')
    def fail(*args):
        raise RuntimeError('non-secret-exception-redaction-fixture')
    monkeypatch.setattr(visitor, 'boundary', fail)
    response = client.post('/api/visitor-analysis/remove', json={'analysis_id': 'a' * 64})
    assert response.status_code == 500
    assert response.headers['Cache-Control'] == 'no-store'
    assert 'non-secret-exception-redaction-fixture' not in response.text + caplog.text
