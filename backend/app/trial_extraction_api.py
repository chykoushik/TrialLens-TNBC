from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.app import research_api
from backend.app.extraction_source import ROOT, load_source
from backend.app.saved_trials import catalog, snapshot_path
from backend.app.trial_extraction import MOCK_VERSION, run_mock, run_extraction
from backend.app.nebius import configuration_check

router = APIRouter(prefix="/saved-trials", tags=["saved trial extraction"])


class ExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot: str | None = Field(default=None, max_length=200)
    snapshot_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    mode: Literal["mock", "live"] = "mock"
    live_approved: bool = False
    mock_version: Literal["verbatim-sections-v1"] = MOCK_VERSION


def select_source(nct_id, snapshot=None):
    root = research_api.RAW_TRIALS_DIR
    if snapshot is None:
        records, _ = catalog(root)
        record = next((item for item in records if item["nct_id"] == nct_id), None)
        if record is None:
            raise HTTPException(404, "Saved NCT ID not found")
        snapshot = record["snapshot"]
    try:
        path = snapshot_path(root, snapshot)
        return load_source(path.relative_to(ROOT), nct_id)
    except FileNotFoundError as error:
        raise HTTPException(404, "Snapshot not found") from error
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise HTTPException(422, "Invalid or incompatible eligibility snapshot") from error
    except OSError as error:
        raise HTTPException(500, "Snapshot storage unavailable") from error


@router.get("/configuration")
def configuration():
    return configuration_check()


@router.get("/{nct_id}")
def source(nct_id: str = Path(pattern=r"^NCT\d{8}$"), snapshot: str | None = Query(default=None, max_length=200)):
    selected = select_source(nct_id, snapshot)
    records, warnings = catalog(research_api.RAW_TRIALS_DIR, history=True)
    return {"source": asdict(selected), "snapshots": [item for item in records if item["nct_id"] == nct_id],
            "warnings": warnings, "mock_version": MOCK_VERSION, "configuration": configuration_check()}


@router.post("/{nct_id}/extractions")
def extract(request: ExtractionRequest, nct_id: str = Path(pattern=r"^NCT\d{8}$")):
    if request.mode == "live" and (not request.live_approved or not request.snapshot or not request.snapshot_sha256):
        raise HTTPException(422, "Live extraction requires approval and exact snapshot identity")
    selected = select_source(nct_id, request.snapshot)
    if request.snapshot_sha256 is not None and request.snapshot_sha256 != selected.sha256:
        raise HTTPException(409, "Snapshot hash changed; reload the selected source")
    try:
        return (run_extraction(selected, live=True, live_approved=True)
                if request.mode == "live" else run_mock(selected))
    except ValueError as error:
        raise HTTPException(409, "Source identity changed during extraction; reload source") from error
    except OSError as error:
        raise HTTPException(500, "Extraction artifact storage failed") from error
