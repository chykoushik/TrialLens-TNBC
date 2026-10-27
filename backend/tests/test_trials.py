import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app import trial_source


@pytest.fixture
def source(monkeypatch):
    cache = Path(__file__).resolve().parents[2] / "cache"
    cache.mkdir(exist_ok=True)
    original_client = httpx.Client
    with TemporaryDirectory(dir=cache) as directory:
        storage = Path(directory) / "trials"
        monkeypatch.setattr(trial_source, "RAW_TRIALS_DIR", storage)

        def mock(handler):
            transport = httpx.MockTransport(handler)
            monkeypatch.setattr(
                trial_source.httpx, "Client",
                lambda **kwargs: original_client(transport=transport, **kwargs),
            )

        yield storage, mock


def test_trials_and_snapshots(source):
    storage, mock = source
    criteria = "Mock eligibility text.\n  Preserve spacing and punctuation."
    payload = {"studies": [{"protocolSection": {
        "identificationModule": {"nctId": "NCT00000001", "briefTitle": "Mock study"},
        "statusModule": {"overallStatus": "RECRUITING"},
        "conditionsModule": {"conditions": ["Mock condition"]},
        "eligibilityModule": {"eligibilityCriteria": criteria},
    }}], "nextPageToken": "mock-token", "extra": {"preserved": True}}
    body = json.dumps(payload, indent=2).encode()

    def handler(request):
        assert str(request.url).startswith(trial_source.API_URL)
        assert request.url.params["query.cond"] == "triple-negative breast cancer"
        assert request.url.params["pageSize"] == "10"
        assert request.url.params["format"] == "json"
        assert request.extensions["timeout"]["read"] == 20.0
        return httpx.Response(200, content=body)

    mock(handler)
    with TestClient(app) as client:
        for _ in range(2):
            response = client.get("/trials")
            assert response.status_code == 200
            assert response.json() == [{
                "nct_id": "NCT00000001",
                "title": "Mock study",
                "recruitment_status": "RECRUITING",
                "conditions": ["Mock condition"],
                "eligibility_criteria": criteria,
                "source_url": "https://clinicaltrials.gov/study/NCT00000001",
            }]

    snapshots = list(storage.iterdir())
    assert len(snapshots) == 2
    for snapshot in snapshots:
        assert (snapshot / "response.json").read_bytes() == body
        metadata = json.loads((snapshot / "metadata.json").read_text())
        assert metadata["nct_ids"] == ["NCT00000001"]
        assert datetime.fromisoformat(metadata["retrieved_at"]).utcoffset().total_seconds() == 0
        assert "pageSize=10" in metadata["source_url"]


@pytest.mark.parametrize("payload, expected", [
    ({"studies": []}, []),
    ({"studies": [{}]}, [{
        "nct_id": None, "title": None, "recruitment_status": None,
        "conditions": [], "eligibility_criteria": None, "source_url": None,
    }]),
])
def test_missing_fields(source, payload, expected):
    _, mock = source
    mock(lambda request: httpx.Response(200, json=payload))
    with TestClient(app) as client:
        response = client.get("/trials?limit=1")
    assert response.status_code == 200
    assert response.json() == expected


@pytest.mark.parametrize("limit", ["0", "-1", "101", "1.5", "abc", ""])
def test_invalid_limits(source, limit):
    storage, mock = source

    def handler(request):
        pytest.fail("Unexpected network request")

    mock(handler)
    with TestClient(app) as client:
        assert client.get(f"/trials?limit={limit}").status_code == 422
    assert not storage.exists()


@pytest.mark.parametrize("failure, expected", [
    ("http", 502), ("timeout", 504), ("connection", 502),
])
def test_source_errors(source, failure, expected):
    storage, mock = source

    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("Mock timeout", request=request)
        if failure == "connection":
            raise httpx.ConnectError("Mock connection failure", request=request)
        return httpx.Response(503)

    mock(handler)
    with TestClient(app) as client:
        assert client.get("/trials").status_code == expected
    assert not storage.exists()


@pytest.mark.parametrize("body", [
    b"invalid json", b"{}", b'{"studies": null}',
    b'{"studies": [null]}', b'{"studies": [{"protocolSection": 1}]}',
])
def test_invalid_responses(source, body):
    storage, mock = source
    mock(lambda request: httpx.Response(200, content=body))
    with TestClient(app) as client:
        assert client.get("/trials").status_code == 502
    snapshot, = storage.iterdir()
    assert (snapshot / "response.json").read_bytes() == body
    assert (snapshot / "metadata.json").exists()


def test_storage_failure(source):
    storage, mock = source
    storage.write_text("Mock obstruction", encoding="utf-8")
    mock(lambda request: httpx.Response(200, json={"studies": []}))
    with TestClient(app) as client:
        assert client.get("/trials").status_code == 500
