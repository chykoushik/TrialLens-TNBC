import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend import publication_audit
from backend.public_demo import app

client = TestClient(app)


def test_public_api_is_key_free_and_runs_fictional_calculations(monkeypatch):
    from backend.app import nebius
    def forbidden(*args, **kwargs):
        raise AssertionError("Provider access forbidden")
    monkeypatch.setattr(nebius, "configuration_check", forbidden)
    monkeypatch.setattr(nebius.NebiusConfig, "from_environment", forbidden)
    with patch("httpx.HTTPTransport.handle_request", side_effect=forbidden):
        assert client.get("/api/health").json()["paid_inference"] is False
        cases = client.get("/api/tnbc/cases").json()
        assert len(cases) == 4 and all(case["is_synthetic"] for case in cases)
        result = client.post("/api/tnbc/cases/tnbc-record-gaps/evaluate", json={"budget": "3"})
        assert result.status_code == 200
        assert result.json()["spent"] == "0"
        assert client.get("/api/research/trials").json()["trials"] == []
        assert client.get("/api/readiness").json()["public_demo"] is True


@pytest.mark.parametrize("path", ["/trials", "/saved-trials/configuration", "/saved-trials/NCT01770353",
    "/annotations/NCT01770353", "/openapi.json", "/docs", "/results/nebius/live-request.claim", "/.env"])
def test_public_app_has_no_private_or_provider_routes(path):
    for prefix in ("", "/api"):
        assert client.get(prefix + path).status_code == 404
    assert client.post("/api/saved-trials/NCT01770353/extractions", json={"mode": "live"}).status_code == 404


def test_public_input_and_security_boundaries():
    assert client.post("/api/tnbc/cases/tnbc-record-gaps/evaluate", content="x" * 8193).status_code == 413
    response = client.post("/api/tnbc/cases/tnbc-record-gaps/evaluate", json={"patient": "not accepted"})
    assert response.status_code == 422
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_audit_excludes_credentials_logs_and_never_reports_match_text(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("private contents", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs/private.log").write_text("private contents", encoding="utf-8")
    (tmp_path / "billing.json").write_text("private contents", encoding="utf-8")
    (tmp_path / "raw_response.json").write_text("private contents", encoding="utf-8")
    (tmp_path / "request.claim").write_text("private contents", encoding="utf-8")
    (tmp_path / "example.py").write_text("url = 'https://synthetic:offline-test@example.invalid'", encoding="utf-8")
    original = Path.read_text
    def guarded(path, *args, **kwargs):
        assert path.name not in (".env", "private.log", "billing.json", "raw_response.json", "request.claim")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", guarded)
    class Result:
        stdout = b""
    monkeypatch.setattr(publication_audit.subprocess, "run", lambda *args, **kwargs: Result())
    result = publication_audit.audit(tmp_path)
    assert result["findings"] == [{"category": "credential_url", "path": "example.py", "line": 1}]
    assert "offline-test" not in json.dumps(result)


def test_showcase_matches_saved_recovery_when_locally_available():
    root = Path(__file__).resolve().parents[2]
    path = root / "results/extraction-alignment/460b07792d0d41ce94472a0158f3ecac"
    if not path.is_dir():
        pytest.skip("Private saved artifacts absent")
    facts = json.loads((root / "frontend/src/fixtures/research_showcase.json").read_text())
    manifest = json.loads((path / "manifest.json").read_text())
    report = json.loads((path / "alignment_report.json").read_text())
    errors = json.loads((path / "validation_errors.json").read_text())
    assert facts["status"] == manifest["status"] == "validation_failed"
    assert facts["evidence_entries"] == len(report["entries"]) == 24
    assert facts["automatically_recovered"] == report["counts"]["automatically_recovered"] == 5
    assert facts["remaining_entries"] == 19
    assert facts["validation_errors"] == len(errors) == 39
    assert json.loads((path / "validated.json").read_text()) is facts["validated_output"] is None
