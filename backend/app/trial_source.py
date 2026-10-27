import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

API_URL = "https://clinicaltrials.gov/api/v2/studies"
RAW_TRIALS_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "trials"


def retrieve_trials(limit: int) -> object:
    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100")
    params = {"query.cond": "triple-negative breast cancer", "pageSize": limit, "format": "json"}
    with httpx.Client(timeout=20.0) as client:
        response = client.get(API_URL, params=params)
        response.raise_for_status()

    retrieved_at = datetime.now(timezone.utc)
    snapshot = RAW_TRIALS_DIR / f"{retrieved_at:%Y%m%dT%H%M%S%fZ}_{uuid4().hex}"
    snapshot.mkdir(parents=True, exist_ok=False)
    with (snapshot / "response.json").open("xb") as file:
        file.write(response.content)
    metadata = {
        "retrieved_at": retrieved_at.isoformat(),
        "source_url": str(response.url),
        "nct_ids": [],
    }
    try:
        payload = response.json()
        if isinstance(payload, dict) and isinstance(payload.get("studies"), list):
            for study in payload["studies"]:
                if isinstance(study, dict):
                    protocol = study.get("protocolSection")
                    if isinstance(protocol, dict):
                        identification = protocol.get("identificationModule")
                        if isinstance(identification, dict):
                            nct_id = identification.get("nctId")
                            if isinstance(nct_id, str):
                                metadata["nct_ids"].append(nct_id)
    finally:
        with (snapshot / "metadata.json").open("x", encoding="utf-8") as file:
            json.dump(metadata, file, ensure_ascii=False, indent=2)
    return payload
