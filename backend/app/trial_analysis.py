import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from httpx import Client
from fastapi import APIRouter, HTTPException, Query

from backend.app import research_api
from backend.app.real_trial_review import review
from backend.app.saved_trials import catalog
from backend.app.trial_parser import parse_trials
from backend.app.trial_source import API_URL

router = APIRouter(prefix="/clinical-trials", tags=["trial search and analysis"])


@router.get("/search")
def search(condition: str = Query(default="", max_length=300), intervention: str = Query(default="", max_length=300),
           keywords: str = Query(default="", max_length=300), nct_id: str = Query(default="", pattern=r"^(NCT\d{8})?$"),
           status: str = Query(default="", pattern=r"^(RECRUITING|NOT_YET_RECRUITING|ACTIVE_NOT_RECRUITING|COMPLETED|TERMINATED|WITHDRAWN|SUSPENDED)?$"),
           page_token: str = Query(default="", max_length=4000)):
    if not any(value.strip() for value in (condition, intervention, keywords, nct_id)):
        raise HTTPException(422, "Enter a condition, treatment, keyword or NCT identifier.")
    for value in (condition, intervention, keywords):
        if re.fullmatch(r"NCT\d{8}", value.strip(), re.I):
            nct_id = value.strip().upper()
            condition = intervention = keywords = ""
            break
    records, _ = catalog(research_api.RAW_TRIALS_DIR)
    if nct_id and not any((condition, intervention, keywords, status, page_token)):
        saved = [record for record in records if record["nct_id"] == nct_id and record.get("is_synthetic") is not True]
        if saved:
            for record in saved:
                payload = json.loads((research_api.RAW_TRIALS_DIR / record["snapshot"]).read_bytes())
                study = next(study for study in payload["studies"] if study["protocolSection"]["identificationModule"]["nctId"] == nct_id)
                record["phases"] = study["protocolSection"].get("designModule", {}).get("phases", [])
            return {"trials": saved, "total": len(saved), "next_page_token": None, "origin": "Saved registry snapshot"}
    params = {"format": "json", "pageSize": 10, "countTotal": "true"}
    for key, value in (("query.cond", condition), ("query.intr", intervention), ("query.term", keywords),
                       ("filter.ids", nct_id), ("filter.overallStatus", status), ("pageToken", page_token)):
        if value:
            params[key] = value
    try:
        with Client(timeout=20.0, follow_redirects=False) as client:
            response = client.get(API_URL, params=params)
            response.raise_for_status()
        raw = response.content
        payload = response.json()
        trials = parse_trials(payload)
        if any(not trial.nct_id or not re.fullmatch(r"NCT\d{8}", trial.nct_id) for trial in trials):
            raise ValueError("Invalid registry identifier")
        now = datetime.now(timezone.utc)
        digest = hashlib.sha256(raw).hexdigest()
        identical = next((path for path in research_api.RAW_TRIALS_DIR.glob("*/response.json")
                          if hashlib.sha256(path.read_bytes()).hexdigest() == digest), None)
        if identical is None:
            folder = research_api.RAW_TRIALS_DIR / f"{now:%Y%m%dT%H%M%S%fZ}_{uuid4().hex}"
            folder.mkdir(parents=True, exist_ok=False)
            (folder / "response.json").write_bytes(raw)
            (folder / "metadata.json").write_text(json.dumps({"retrieved_at": now.isoformat(),
                "source_url": str(response.url), "nct_ids": [trial.nct_id for trial in trials]}), encoding="utf-8")
            identical = folder / "response.json"
        snapshot = identical.relative_to(research_api.RAW_TRIALS_DIR).as_posix()
        saved, _ = catalog(research_api.RAW_TRIALS_DIR, history=True)
        selected = [record for record in saved if record["snapshot"] == snapshot]
        phases = {study["protocolSection"]["identificationModule"]["nctId"]:
                  study["protocolSection"].get("designModule", {}).get("phases", []) for study in payload["studies"]}
        return {"trials": [{**record, "phases": phases.get(record["nct_id"], [])} for record in selected],
                "total": payload.get("totalCount"), "next_page_token": payload.get("nextPageToken"),
                "origin": "ClinicalTrials.gov API v2"}
    except httpx.TimeoutException:
        raise HTTPException(504, "ClinicalTrials.gov took too long. Retry or choose a saved trial.") from None
    except httpx.HTTPError:
        raise HTTPException(502, "ClinicalTrials.gov is unavailable. Retry or choose a saved trial.") from None
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(502, "The registry returned an incompatible record. No fictional replacement was used.") from None
    except OSError:
        raise HTTPException(503, "The registry snapshot could not be saved. Please retry.") from None


@router.get("/{nct_id}/analysis")
def analyze(nct_id: str, snapshot: str | None = Query(default=None, max_length=200), snapshot_sha256: str | None = Query(default=None, pattern=r"^[a-f0-9]{64}$")):
    if not re.fullmatch(r"NCT\d{8}", nct_id):
        raise HTTPException(422, "Invalid NCT identifier")
    result = review(nct_id, snapshot, snapshot_sha256)
    snapshot_sha256 = result["source"]["sha256"]
    result["extracted_conditions"] = []
    from backend.app import extraction
    from backend.app.inference_review import report_for
    for path in sorted(extraction.RESULTS_DIR.glob("*/manifest.json"), reverse=True):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if (manifest.get("nct_id"), manifest.get("snapshot_sha256"), manifest.get("source_snapshot"), manifest.get("mode")) != (
                    nct_id, snapshot_sha256, result["source"]["source_snapshot"], "live"):
                continue
            _, report, model = report_for(nct_id, path.parent.name)
            if report["review_checks_passed"] and model is not None:
                result["extracted_conditions"] = [{key: value for key, value in node.model_dump(mode="json").items()
                    if key in ("criterion_id", "original_text", "criterion_type", "logical_operator", "biomarker", "comparator", "threshold", "unit", "temporal_constraint")}
                    for node in model.criteria]
                break
        except (OSError, ValueError, KeyError, TypeError, HTTPException):
            continue
    result["inference"] = {"mode": "saved-or-source-only", "request_sent": False,
        "explanation": "Matching saved outputs are checked against this source. Optional visitor extraction requires your own key and explicit cost approval."}
    return result
