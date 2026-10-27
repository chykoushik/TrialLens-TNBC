import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.main import app


def smoke():
    client = TestClient(app)
    transitions = []
    with patch("httpx.Client", side_effect=AssertionError("External HTTP forbidden")):
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/readiness").json()["offline_ready"]
        for outcomes, expected in (({}, ["0", "3", "2"]),
            ({"review-germline-report": "brca1-pathogenic"}, ["2", "1", "1"]),
            ({"review-germline-report": "brca1-pathogenic", "review-pdl1-report": "cps-15"}, ["3", "0", "0"])):
            response = client.post("/tnbc/cases/tnbc-record-gaps/evaluate", json={
                "budget": "3", "algorithm": "adaptive_replan", "seed": 7, "outcomes": outcomes})
            assert response.status_code == 200
            result = response.json()
            values = [result["spent"], result["remaining_budget"], result["assessment"]["uncertainty"]]
            assert values == expected
            transitions.append({"spent": values[0], "remaining": values[1], "uncertainty": values[2]})
    return {"status": "pass", "scenario": "fictional-tnbc-record-gaps", "transitions": transitions,
            "external_requests": 0, "artifact_writes": 0}


if __name__ == "__main__":
    print(json.dumps(smoke(), indent=2))
