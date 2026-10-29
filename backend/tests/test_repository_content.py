import pytest

from scripts import public_release


@pytest.mark.parametrize('name', ['AGENTS.md', 'docs/chat-transcript.md', 'results/nebius/live-request.claim',
    'results/nebius/authorizations/grant.json', 'results/extraction/attempt/raw_response.json', '.env.production',
    'data/patients/private.csv', 'cache/temporary.json', 'frontend/src/ProductHome.tsx'])
def test_private_and_obsolete_material_is_excluded(name):
    assert not public_release.eligible(name)


def test_runtime_allowlist_cannot_override_credential_exclusion(tmp_path, monkeypatch):
    monkeypatch.setattr(public_release, 'ROOT', tmp_path)
    (tmp_path / '.dockerignore').write_text('!results/nebius/authorizations/grant.json\n')
    with pytest.raises(ValueError):
        public_release.runtime_files()


def test_patient_level_table_rejected_without_echoing_content(tmp_path, monkeypatch):
    monkeypatch.setattr(public_release, 'ROOT', tmp_path)
    path = tmp_path / 'research/public.csv'
    path.parent.mkdir()
    path.write_text('patient_id,value\nprivate-audit-sentinel,1\n')
    with pytest.raises(ValueError) as error:
        public_release.audit(['research/public.csv'])
    assert 'patient_level_content' in str(error.value)
    assert 'private-audit-sentinel' not in str(error.value)
