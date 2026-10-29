from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app import research_results


def test_aggregate_results_have_provenance_and_no_patient_records():
    response = TestClient(app).get('/research/results')
    assert response.status_code == 200
    value = response.json()
    assert len(value['sections']) == 6
    for section in value['sections']:
        assert set(section) <= {'title', 'kind', 'source', 'limitation', 'metrics', 'sha256', 'status', 'text', 'table', 'table_source', 'table_sha256'}
        assert all(item is None or isinstance(item, (int, float, bool)) for item in section['metrics'].values())
        if section['status'] == 'available':
            assert len(section['sha256']) == 64
    assert 'api_key' not in value['inference']


def test_missing_artifacts_are_not_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(research_results, 'ROOT', tmp_path)
    value = research_results.results()
    assert all(section['status'] == 'unavailable' for section in value['sections'])
    assert all(section['metrics'] == {} for section in value['sections'])
    assert 'metabric' not in value['overview']
    assert 'synthetic' not in value['overview']


def test_overview_matches_saved_aggregate_artifacts():
    import hashlib
    import json
    value = research_results.research_overview()
    audit = json.loads((research_results.ROOT / 'research/metabric_realdata_v1/results/data_audit.json').read_text())
    assert value['metabric']['patients'] == audit['patients'] == 2509
    assert value['synthetic']['instances'] == 24
    assert value['synthetic']['conditions'] == 48
    assert value['synthetic']['budgets'] == [1, 4]
    assert round(min(row['speedup'] for row in value['caching']), 2) == 1.35
    assert round(max(row['speedup'] for row in value['caching']), 2) == 1.67
    primary = next(row for row in value['metabric']['comparison'] if row['method'] == 'triallens_nominal')
    assert round(primary['error'] * 100, 2) == 0.34
    assert round(primary['coverage'] * 100, 2) == 92.12
    for source in value['sources']:
        assert source['sha256'] == hashlib.sha256((research_results.ROOT / source['path']).read_bytes()).hexdigest()
