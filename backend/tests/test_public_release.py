from pathlib import Path

import pytest

from backend import serve_public
from scripts import public_release


@pytest.mark.parametrize('port', ['8080', '10000', '1', '65535'])
def test_public_launcher_reads_only_port(monkeypatch, port):
    class Environment(dict):
        def get(self, key, default=None):
            assert key == 'PORT'
            return super().get(key, default)
    monkeypatch.setattr(serve_public.os, 'environ', Environment(PORT=port))
    settings = serve_public.settings()
    assert settings['port'] == int(port)
    assert settings['workers'] == 1
    assert settings['limit_concurrency'] == 16
    assert settings['access_log'] is False


@pytest.mark.parametrize('port', ['', '0', '65536', '-1', '8080;command', ' 8080', '1.5'])
def test_public_launcher_rejects_invalid_ports(monkeypatch, port):
    monkeypatch.setenv('PORT', port)
    with pytest.raises(ValueError):
        serve_public.settings()


def test_public_inventory_excludes_internal_material():
    for name in ['AGENTS.md', 'docs/guide.md', 'research/method.py', 'results/raw.json', '.env',
                 'frontend/node_modules/library.js', 'backend/authorizations/record.py', '../private.py']:
        assert not public_release.eligible(name)
    assert public_release.eligible('.env.example')
    assert public_release.eligible('backend/app/extraction_prompt.py')
    names = public_release.inventory()
    assert all(name == 'README.md' or name in public_release.runtime_files() for name in names if name.endswith('.md'))
    assert 'backend/research_public.py' in names
    assert public_release.runtime_files() <= set(names)
    assert not public_release.audit(names)


def test_public_notices_preserve_required_attribution():
    root = Path(__file__).resolve().parents[2]
    assert (root/'THIRD_PARTY_NOTICES.txt').is_file()
    for name in ('react', 'react-dom', 'scheduler', 'vite'):
        text = (root/f'third_party/licenses/{name}.txt').read_text(encoding='utf-8')
        assert 'Permission is hereby granted' in text


def test_public_example_has_no_credentials():
    root = Path(__file__).resolve().parents[2]
    rows = dict(line.split('=', 1) for line in (root/'.env.example').read_text().splitlines() if '=' in line)
    assert rows['NEBIUS_API_KEY'] == ''
    assert rows['NEBIUS_LIVE_EXTRACTION'] == '0'
    assert rows['VITE_PUBLIC_DEMO'] == '0'
    assert rows['VITE_PUBLIC_RESEARCH'] == '1'
    assert rows['TRIALLENS_BYOK_ENABLED'] == '0'

def test_readiness_rejects_missing_build_and_accepts_present_build(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend import public_demo
    monkeypatch.setattr(public_demo, 'DIST', tmp_path)
    with TestClient(public_demo.app) as client:
        assert client.get('/api/health').status_code == 200
        missing = client.get('/api/readiness')
        assert missing.status_code == 503
        assert missing.json()['offline_ready'] is False
        assert client.get('/').status_code == 503
        (tmp_path/'index.html').write_text('<html>Fictional demo test</html>', encoding='utf-8')
        assert client.get('/api/readiness').status_code == 200
        assert client.get('/api/readiness').json()['offline_ready'] is True
        assert client.get('/').status_code == 200


def test_readiness_rejects_missing_cases(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend import public_demo
    (tmp_path/'index.html').write_text('<html>Fictional demo test</html>', encoding='utf-8')
    monkeypatch.setattr(public_demo, 'DIST', tmp_path)
    monkeypatch.setattr(public_demo.tnbc_api, 'cases', lambda: [])
    assert TestClient(public_demo.app).get('/api/readiness').status_code == 503


def test_configured_key_does_not_enable_public_inference(monkeypatch):
    from fastapi.testclient import TestClient
    from backend import public_demo
    from backend.app import nebius
    monkeypatch.setenv('NEBIUS_API_KEY', 'synthetic-offline-test-only')
    monkeypatch.setenv('NEBIUS_MODEL', nebius.DEFAULT_MODEL)
    monkeypatch.setenv('NEBIUS_LIVE_EXTRACTION', '1')
    monkeypatch.setenv('TRIALLENS_PUBLIC_DEMO', '0')
    def forbidden(*args, **kwargs):
        raise AssertionError('Provider access forbidden')
    monkeypatch.setattr(nebius, 'chat_completion', forbidden)
    client = TestClient(public_demo.app)
    assert client.post('/api/saved-trials/NCT01770353/extractions', json={'mode': 'live', 'live_approved': True}).status_code == 404
    assert client.get('/api/saved-trials/configuration').status_code == 404
    assert client.get('/api/health').json()['paid_inference'] is False


def test_render_probes_readiness_without_auto_deploy():
    root = Path(__file__).resolve().parents[2]
    blueprint = (root/'render.yaml').read_text(encoding='utf-8')
    assert 'healthCheckPath: /api/readiness' in blueprint
    assert 'autoDeployTrigger: "off"' in blueprint
    assert '\n    autoDeploy:' not in blueprint



def test_public_license_and_readme_links_are_consistent():
    import json
    root = Path(__file__).resolve().parents[2]
    text = (root/'LICENSE').read_text(encoding='utf-8')
    if text.startswith('Mozilla Public License Version 2.0'):
        expected = 'MPL-2.0'
        for section in ('2.5. Representation', '3.2. Distribution of Executable Form', '10.3. Modified Versions', 'Exhibit A', 'Exhibit B'):
            assert section in text
    else:
        expected = 'MIT'
        assert text.startswith('MIT License')
        assert 'Copyright (c) 2026 Koushik Chowdhury' in text
        assert 'Permission is hereby granted' in text
    assert 'COPYRIGHT HOLDER - OWNER CONFIRMATION REQUIRED' not in text
    assert json.loads((root/'frontend/package.json').read_text())['license'] == expected
    assert json.loads((root/'frontend/package-lock.json').read_text())['packages']['']['license'] == expected
    readme = (root/'README.md').read_text(encoding='utf-8')
    assert expected in readme
    assert 'https://github.com/chykoushik/TrialLens-TNBC.git' in readme
    assert 'https://triallens-tnbc.onrender.com/' in readme
    assert 'Clinical eligibility remains unvalidated.' in readme
