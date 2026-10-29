import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import pytest

from backend import extraction_authorization as authorization
from backend.app import extraction, nebius
from backend.app.extraction_source import ROOT, load_source

FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv('NEBIUS_API_KEY', 'synthetic-authorization-test')
    monkeypatch.setenv('NEBIUS_MODEL', nebius.DEFAULT_MODEL)
    monkeypatch.setenv('NEBIUS_BASE_URL', nebius.BASE_URL)
    monkeypatch.setenv('NEBIUS_LIVE_EXTRACTION', '1')
    monkeypatch.setenv('NEBIUS_TIMEOUT_SECONDS', '120')
    monkeypatch.delenv('TRIALLENS_PUBLIC_DEMO', raising=False)
    with TemporaryDirectory(dir=ROOT / 'data/synthetic') as temporary:
        root = Path(temporary)
        snapshot = root / 'response.json'
        snapshot.write_bytes((FIXTURES / 'extraction_snapshot.json').read_bytes())
        source = load_source(snapshot, 'NCT00000001')
        prior = root / 'prior'
        prior.mkdir()
        manifest = prior / 'manifest.json'
        manifest.write_text(json.dumps({'mode': 'live', 'status': 'failed', 'request_count': 1,
            'returned_model': None, 'nct_id': source.nct_id, 'source_snapshot': source.source_snapshot,
            'snapshot_sha256': source.sha256}), encoding='utf-8')
        (prior / 'validation_errors.json').write_text('[{"code":"timeout"}]', encoding='utf-8')
        claim = root / 'original.claim'
        claim.write_text('Software test reservation', encoding='utf-8')
        monkeypatch.setattr(nebius, 'LIVE_CLAIM', claim)
        monkeypatch.setattr(authorization, 'AUTHORIZATIONS', root / 'authorizations')
        monkeypatch.setattr(authorization, 'EXTRACTIONS', root)
        monkeypatch.setattr(extraction, 'RESULTS_DIR', root / 'new-results')
        original = httpx.Client
        calls = []
        content = json.loads((FIXTURES / 'extraction_mock.json').read_text())['content']
        def install(timeout=False, empty_content=False):
            def handler(request):
                calls.append(request)
                assert request.extensions['timeout']['read'] == 120
                assert json.loads(request.content)['extra_body']['chat_template_kwargs']['enable_thinking'] is False
                if timeout:
                    raise httpx.ReadTimeout('Software timeout', request=request)
                return httpx.Response(200, json={'model': nebius.DEFAULT_MODEL,
                    'choices': [{'message': {'content': None if empty_content else content}, 'finish_reason': 'stop'}]})
            monkeypatch.setattr(nebius.httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
        install()
        originals = {p: p.read_bytes() for p in (claim, manifest, prior / 'validation_errors.json', snapshot)}
        yield root, snapshot, source, manifest, calls, install
        assert all(p.read_bytes() == data for p, data in originals.items())


def run(snapshot, source, **kwargs):
    output = extraction.extract_snapshot(snapshot, source.nct_id, mock=False,
        live_approved=True, expected_sha256=source.sha256, **kwargs)
    return output, json.loads((output / 'manifest.json').read_text())


@pytest.fixture
def fresh_source(setup, monkeypatch):
    root, _, _, prior, calls, _ = setup
    monkeypatch.setenv('NEBIUS_INPUT_USD_PER_MILLION', '0.30')
    monkeypatch.setenv('NEBIUS_OUTPUT_USD_PER_MILLION', '0.90')
    monkeypatch.setenv('NEBIUS_MAX_REQUEST_USD', '0.05')
    snapshot = root / 'target' / 'response.json'
    snapshot.parent.mkdir()
    value = json.loads((FIXTURES / 'extraction_snapshot.json').read_text())
    value['studies'][0]['protocolSection']['identificationModule']['nctId'] = 'NCT00000002'
    snapshot.write_text(json.dumps(value), encoding='utf-8')
    source = load_source(snapshot, 'NCT00000002')
    return root, snapshot, source, prior, calls


def test_new_source_quote_is_exact_and_non_consuming(fresh_source, capsys):
    _, snapshot, source, _, calls = fresh_source
    assert authorization.main(['--quote-source', '--nct-id', source.nct_id, '--snapshot', str(snapshot.relative_to(ROOT))]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value['quote']['maximum_estimated_cost_usd'] == '0.0145728'
    assert value['authorization_created'] is False and value['request_consumed'] is False
    assert not authorization.AUTHORIZATIONS.exists() and not calls


@pytest.mark.parametrize('cap', ['0.001', '0.06', 'NaN', 'Infinity', '-1'])
def test_invalid_or_excess_cost_never_creates_grant(fresh_source, cap):
    _, _, source, prior, calls = fresh_source
    with pytest.raises(nebius.NebiusError, match='authorization_cost_limit'):
        authorization.authorize_source(prior, source, cap, 'software-operator', 'Mock authorization test')
    assert not authorization.AUTHORIZATIONS.exists() and not calls


@pytest.mark.parametrize('timeout', [False, True])
def test_fresh_source_grant_preserves_history_and_is_exactly_one_request(fresh_source, setup, timeout):
    setup[-1](timeout)
    _, snapshot, source, prior, calls = fresh_source
    identifier = authorization.authorize_source(prior, source, '0.0145728', 'software-operator', 'Explicit mock source grant')
    record = authorization.read_authorization(identifier)
    assert record['version'] == 3 and record['request_id'] == identifier
    assert record['nct_id'] == 'NCT00000002' and record['audit_anchor']['nct_id'] == 'NCT00000001'
    assert record['max_requests'] == 1 and record['automatic_retries'] == 0
    assert record['authorized_maximum_estimated_cost_usd'] == '0.0145728'
    assert record['audit_anchor']['original_claim_sha256'] == authorization.checksum(nebius.LIVE_CLAIM)
    assert not calls
    _, result = run(snapshot, source, authorization_id=identifier)
    assert result['request_count'] == 1 and result['request_id'] == identifier
    assert result['status'] == ('failed' if timeout else 'validated')
    _, blocked = run(snapshot, source, authorization_id=identifier)
    assert blocked['request_count'] == 0 and len(calls) == 1


@pytest.mark.parametrize('setting,value', [('NEBIUS_INPUT_USD_PER_MILLION', '0.4'), ('NEBIUS_BASE_URL', nebius.REGIONAL_BASE_URL), ('NEBIUS_MAX_REQUEST_USD', '0.001')])
def test_changed_price_endpoint_or_server_cap_blocks_before_claim(fresh_source, monkeypatch, setting, value):
    _, snapshot, source, prior, calls = fresh_source
    identifier = authorization.authorize_source(prior, source, '0.0145728', 'software-operator', 'Explicit mock source grant')
    monkeypatch.setenv(setting, value)
    _, result = run(snapshot, source, authorization_id=identifier)
    assert result['request_count'] == 0 and not calls
    assert not (authorization.AUTHORIZATIONS / f'{identifier}.claim').exists()


def test_new_source_authorization_is_atomic_under_concurrency(fresh_source):
    _, _, source, prior, calls = fresh_source
    identifier = authorization.authorize_source(prior, source, '0.0145728', 'software-operator', 'Concurrent mock grant')
    config = nebius.NebiusConfig.from_environment()
    def reserve(_):
        try:
            authorization.reserve_authorized_request(identifier, source, config, ROOT / 'cache/mock-request-output')
            return True
        except nebius.NebiusError:
            return False
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(reserve, range(8))) == 1
    assert not calls


def test_multiple_source_grants_never_automatically_fall_back(fresh_source, monkeypatch):
    from backend.app.inference_access import scoped_authorization
    _, snapshot, source, prior, calls = fresh_source
    first = authorization.authorize_source(prior, source, '0.0145728', 'software-operator', 'Mock allocation one')
    second = authorization.authorize_source(prior, source, '0.0145728', 'software-operator', 'Mock allocation two')
    assert first != second
    monkeypatch.setenv('NEBIUS_EXTRACTION_AUTHORIZATION_ID', first)
    assert scoped_authorization(source) == first
    output, result = run(snapshot, source, authorization_id=first)
    assert result['request_count'] == 1
    authorization.inspect_attempt(output / 'manifest.json')
    assert scoped_authorization(source) is None
    assert not (authorization.AUTHORIZATIONS / f'{second}.claim').exists()
    monkeypatch.setenv('NEBIUS_EXTRACTION_AUTHORIZATION_ID', second)
    assert scoped_authorization(source) == second and len(calls) == 1


def test_http_requires_matching_request_id_and_explicit_cost_confirmation(fresh_source, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app.main import app
    from backend.app import research_api
    root, _, source, prior, calls = fresh_source
    monkeypatch.setattr(research_api, 'RAW_TRIALS_DIR', root)
    token = 'test-operator-access-code-0123456789abcdef'
    monkeypatch.setenv('TRIALLENS_OPERATOR_TOKEN', token)
    identifier = authorization.authorize_source(prior, source, '0.0145728', 'software-operator', 'HTTP mock grant')
    monkeypatch.setenv('NEBIUS_EXTRACTION_AUTHORIZATION_ID', identifier)
    client = TestClient(app)
    endpoint = f'/saved-trials/{source.nct_id}/extractions'
    headers = {'Authorization': f'Bearer {token}'}
    payload = {'snapshot': 'target/response.json', 'snapshot_sha256': source.sha256, 'mode': 'live', 'live_approved': True}
    assert client.post(endpoint, json=payload).status_code == 401
    assert client.post(endpoint, json=payload, headers=headers).status_code == 422
    payload['authorization_id'] = 'f' * 32
    payload['maximum_estimated_cost_usd'] = '0.0145728'
    assert client.post(endpoint, json=payload, headers=headers).status_code == 409
    payload['authorization_id'] = identifier
    payload['maximum_estimated_cost_usd'] = '0.02'
    assert client.post(endpoint, json=payload, headers=headers).status_code == 422
    assert not calls
    state = client.get(f'/saved-trials/{source.nct_id}/inference?snapshot=target/response.json', headers=headers).json()['configuration']
    assert state['remaining_authorized_requests'] == 1 and state['authorization_id'] == identifier
    payload['maximum_estimated_cost_usd'] = '0.0145728'
    result = client.post(endpoint, json=payload, headers=headers).json()
    assert result['manifest']['request_count'] == 1 and len(calls) == 1
    assert client.post(endpoint, json=payload, headers=headers).status_code == 409
    assert len(calls) == 1
    state = client.get(f'/saved-trials/{source.nct_id}/inference?snapshot=target/response.json', headers=headers).json()['configuration']
    assert state['remaining_authorized_requests'] == 0 and not state['ready']


def test_unauthorized_second_request_and_check_are_non_consuming(setup, capsys):
    root, snapshot, source, prior, calls, _ = setup
    assert authorization.main(['--previous-attempt', str(prior.relative_to(ROOT))]) == 0
    assert json.loads(capsys.readouterr().out)['additional_request_available'] is False
    assert not authorization.AUTHORIZATIONS.exists()
    _, result = run(snapshot, source)
    assert result['request_count'] == 0
    assert not calls
    _, result = run(snapshot, source, authorization_id='f' * 32)
    assert result['request_count'] == 0
    assert not calls


@pytest.mark.parametrize('timeout', [False, True])
def test_separate_authorization_is_exactly_one_attempt(setup, timeout):
    root, snapshot, source, prior, calls, install = setup
    identifier = authorization.authorize(prior, 'software-test', 'Separate test allocation')
    assert not (authorization.AUTHORIZATIONS / f'{identifier}.claim').exists()
    _, blocked = run(snapshot, source)
    assert blocked['request_count'] == 0 and not calls
    install(timeout)
    output, result = run(snapshot, source, authorization_id=identifier)
    assert result['status'] == ('failed' if timeout else 'validated')
    assert result['request_count'] == 1
    assert result['request_authorization_id'] == identifier
    claim = ROOT / result['request_claim']
    original = claim.read_bytes()
    assert json.loads(original)['extraction_directory'] == output.relative_to(ROOT).as_posix()
    _, blocked = run(snapshot, source, authorization_id=identifier)
    assert blocked['request_count'] == 0
    assert claim.read_bytes() == original
    assert len(calls) == 1


def test_scope_mismatch_does_not_consume_grant(setup):
    _, _, source, prior, calls, _ = setup
    identifier = authorization.authorize(prior, 'software-test', 'Exact source only')
    with pytest.raises(nebius.NebiusError, match='authorization_scope_mismatch'):
        authorization.reserve_authorized_request(identifier, replace(source, sha256='0' * 64),
            nebius.NebiusConfig.from_environment(), ROOT / 'cache/software-output')
    assert not (authorization.AUTHORIZATIONS / f'{identifier}.claim').exists()
    assert not calls


def test_additional_claim_is_atomic(setup):
    _, _, source, prior, calls, _ = setup
    identifier = authorization.authorize(prior, 'software-test', 'Concurrent test')
    config = nebius.NebiusConfig.from_environment()
    def reserve(_):
        try:
            authorization.reserve_authorized_request(identifier, source, config, ROOT / 'cache/software-output')
            return True
        except nebius.NebiusError:
            return False
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sum(executor.map(reserve, range(2))) == 1
    assert not calls


def test_existing_authorization_cannot_be_overwritten_and_invalid_ids_fail(setup, monkeypatch):
    _, _, _, prior, calls, _ = setup
    identifier = authorization.authorize(prior, 'software-test', 'Immutable test record')
    record = authorization.AUTHORIZATIONS / f'{identifier}.json'
    before = record.read_bytes()
    assert authorization.read_authorization(identifier)['max_requests'] == 1
    assert authorization.read_authorization(identifier)['automatic_retries'] == 0
    for invalid in ('../original', '', 'A' * 32):
        with pytest.raises(nebius.NebiusError, match='invalid_authorization'):
            authorization.read_authorization(invalid)
    from types import SimpleNamespace
    monkeypatch.setattr(authorization, 'uuid4', lambda: SimpleNamespace(hex=identifier))
    with pytest.raises(FileExistsError):
        authorization.authorize(prior, 'software-test', 'Collision cannot overwrite')
    assert record.read_bytes() == before and not calls

def test_public_mode_and_missing_live_approval_cannot_consume_grant(setup, monkeypatch):
    _, snapshot, source, prior, calls, _ = setup
    identifier = authorization.authorize(prior, 'software-test', 'Approval gates')
    output = extraction.extract_snapshot(snapshot, source.nct_id, mock=False,
        expected_sha256=source.sha256, authorization_id=identifier)
    assert json.loads((output / 'manifest.json').read_text())['request_count'] == 0
    monkeypatch.setenv('TRIALLENS_PUBLIC_DEMO', '1')
    with pytest.raises(nebius.NebiusError, match='live_extraction_unavailable'):
        authorization.reserve_authorized_request(identifier, source,
            nebius.NebiusConfig.from_environment(), ROOT / 'cache/software-output')
    assert not (authorization.AUTHORIZATIONS / f'{identifier}.claim').exists()
    assert not calls


def test_changed_grant_cannot_consume_a_request(setup):
    _, _, source, prior, calls, _ = setup
    identifier = authorization.authorize(prior, 'software-test', 'Pinned source')
    path = authorization.AUTHORIZATIONS / f'{identifier}.json'
    record = json.loads(path.read_text())
    record['snapshot_sha256'] = '0' * 64
    path.write_text(json.dumps(record), encoding='utf-8')
    with pytest.raises(nebius.NebiusError, match='authorization_mismatch'):
        authorization.reserve_authorized_request(identifier, source,
            nebius.NebiusConfig.from_environment(), ROOT / 'cache/software-output')
    assert not (authorization.AUTHORIZATIONS / f'{identifier}.claim').exists()
    assert not calls


def second_attempt(setup):
    _, snapshot, source, prior, calls, install = setup
    identifier = authorization.authorize(prior, 'software-test', 'Second software request')
    grant = authorization.AUTHORIZATIONS / f'{identifier}.json'
    record = json.loads(grant.read_text())
    record['version'] = 1
    grant.write_text(json.dumps(record), encoding='utf-8')
    install(empty_content=True)
    output, manifest = run(snapshot, source, authorization_id=identifier)
    assert manifest['status'] == 'failed'
    assert manifest['returned_model'] == nebius.DEFAULT_MODEL
    assert json.loads((output / 'validation_errors.json').read_text())[0]['code'] == 'invalid_response'
    assert len(calls) == 1
    return output / 'manifest.json', identifier


@pytest.mark.parametrize('timeout', [False, True])
def test_third_request_requires_new_authorization_and_cannot_replay(setup, timeout, capsys):
    _, snapshot, source, _, calls, install = setup
    prior, second_id = second_attempt(setup)
    originals = {p: p.read_bytes() for p in [*prior.parent.iterdir(), *authorization.AUTHORIZATIONS.iterdir()] if p.is_file()}
    assert authorization.main(['--previous-attempt', str(prior.relative_to(ROOT))]) == 0
    check = json.loads(capsys.readouterr().out)
    assert check['previous_authorization_id'] == second_id
    assert check['additional_request_available'] is False
    assert check['authorization_created'] is False
    assert check['timeout_seconds'] == 120 and check['automatic_retries'] == 0
    for kwargs in ({}, {'authorization_id': second_id}):
        _, blocked = run(snapshot, source, **kwargs)
        assert blocked['request_count'] == 0
    assert len(calls) == 1
    third = authorization.authorize(prior, 'software-test-third', 'Independent third software allocation')
    record = authorization.read_authorization(third)
    assert record['version'] == 2
    assert record['previous_claim_sha256'] == authorization.checksum(authorization.AUTHORIZATIONS / f'{second_id}.claim')
    install(timeout=timeout)
    output, manifest = run(snapshot, source, authorization_id=third)
    assert manifest['request_count'] == 1
    assert manifest['status'] == ('failed' if timeout else 'validated')
    claim = authorization.AUTHORIZATIONS / f'{third}.claim'
    before = claim.read_bytes()
    _, blocked = run(snapshot, source, authorization_id=third)
    assert blocked['request_count'] == 0 and len(calls) == 2
    assert claim.read_bytes() == before
    assert authorization.inspect_attempt(output / 'manifest.json')['previous_authorization_id'] == third
    assert all(p.read_bytes() == data for p, data in originals.items())


def test_concurrent_third_executions_send_once(setup):
    _, snapshot, source, _, calls, install = setup
    prior, _ = second_attempt(setup)
    identifier = authorization.authorize(prior, 'software-test-third', 'Concurrent third allocation')
    install()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: run(snapshot, source, authorization_id=identifier), range(2)))
    assert sorted(manifest['request_count'] for _, manifest in results) == [0, 1]
    assert len(calls) == 2
    winner = next(output for output, manifest in results if manifest['request_count'] == 1)
    claim = json.loads((authorization.AUTHORIZATIONS / f'{identifier}.claim').read_text())
    assert claim['extraction_directory'] == winner.relative_to(ROOT).as_posix()


def test_interrupted_third_reservation_remains_consumed(setup):
    _, snapshot, source, _, calls, _ = setup
    prior, _ = second_attempt(setup)
    identifier = authorization.authorize(prior, 'software-test-third', 'Interrupted software allocation')
    claim = ROOT / authorization.reserve_authorized_request(identifier, source,
        nebius.NebiusConfig.from_environment(), ROOT / 'cache/software-interrupted-output')
    before = claim.read_bytes()
    _, blocked = run(snapshot, source, authorization_id=identifier)
    assert blocked['request_count'] == 0 and len(calls) == 1
    assert claim.read_bytes() == before


@pytest.mark.parametrize('target', ['root_claim', 'root_manifest', 'root_errors', 'parent_grant', 'parent_claim', 'second_manifest', 'missing_claim', 'claim_link', 'cycle'])
def test_chain_corruption_blocks_third_without_consuming(setup, target):
    _, snapshot, source, root_manifest, calls, _ = setup
    prior, parent = second_attempt(setup)
    identifier = authorization.authorize(prior, 'software-test-third', 'Chain integrity test')
    paths = {
        'root_claim': nebius.LIVE_CLAIM, 'root_manifest': root_manifest,
        'root_errors': root_manifest.with_name('validation_errors.json'),
        'parent_grant': authorization.AUTHORIZATIONS / f'{parent}.json',
        'parent_claim': authorization.AUTHORIZATIONS / f'{parent}.claim',
        'second_manifest': prior, 'missing_claim': authorization.AUTHORIZATIONS / f'{parent}.claim',
        'claim_link': prior, 'cycle': authorization.AUTHORIZATIONS / f'{parent}.json',
    }
    path = paths[target]
    original = path.read_bytes()
    try:
        if target == 'missing_claim':
            path.unlink()
        elif target == 'claim_link':
            record = json.loads(original)
            record['request_claim'] = 'cache/not-the-parent.claim'
            path.write_text(json.dumps(record), encoding='utf-8')
        elif target == 'cycle':
            record = json.loads(original)
            record['previous_attempt'] = prior.relative_to(ROOT).as_posix()
            path.write_text(json.dumps(record), encoding='utf-8')
        else:
            path.write_bytes(original + b' ')
        with pytest.raises(nebius.NebiusError):
            authorization.read_authorization(identifier)
        _, blocked = run(snapshot, source, authorization_id=identifier)
        assert blocked['request_count'] == 0
        assert not (authorization.AUTHORIZATIONS / f'{identifier}.claim').exists()
        assert len(calls) == 1
    finally:
        path.write_bytes(original)


def test_copied_manifest_cannot_reuse_another_output_claim(setup):
    root, _, _, _, calls, _ = setup
    prior, _ = second_attempt(setup)
    clone = root / 'copied-output'
    clone.mkdir()
    for path in prior.parent.iterdir():
        if path.is_file():
            (clone / path.name).write_bytes(path.read_bytes())
    with pytest.raises(nebius.NebiusError, match='authorization_chain_mismatch'):
        authorization.inspect_attempt(clone / 'manifest.json')
    assert len(calls) == 1
