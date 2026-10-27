import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class EligibilitySource:
    nct_id: str
    text: str
    source_url: str
    source_snapshot: str
    retrieval_timestamp: str | None
    is_synthetic: bool | None
    sha256: str


def load_source(snapshot: Path, nct_id: str) -> EligibilitySource:
    path = (ROOT / snapshot).resolve()
    allowed = (ROOT / "data" / "raw" / "trials", ROOT / "data" / "synthetic")
    if not any(path.is_relative_to(directory.resolve()) for directory in allowed):
        raise ValueError("Snapshot must be in project trial or synthetic storage")
    if not re.fullmatch(r"NCT\d{8}", nct_id):
        raise ValueError("Invalid NCT ID")
    raw = path.read_bytes()
    payload = json.loads(raw)
    studies = payload.get("studies")
    if not isinstance(studies, list):
        raise ValueError("Invalid snapshot studies")
    matches = [study for study in studies if isinstance(study, dict)
               and study.get("protocolSection", {}).get("identificationModule", {}).get("nctId") == nct_id]
    if len(matches) != 1:
        raise ValueError("Expected one matching trial")
    text = matches[0]["protocolSection"].get("eligibilityModule", {}).get("eligibilityCriteria")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Eligibility text missing")
    metadata_path = path.with_name("metadata.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    synthetic = payload.get("is_synthetic")
    if path.is_relative_to((ROOT / "data" / "synthetic").resolve()) and synthetic is not True:
        raise ValueError("Synthetic snapshots require explicit labeling")
    return EligibilitySource(
        nct_id=nct_id, text=text, source_url=f"https://clinicaltrials.gov/study/{nct_id}",
        source_snapshot=path.relative_to(ROOT).as_posix(),
        retrieval_timestamp=metadata.get("retrieved_at"), is_synthetic=synthetic,
        sha256=hashlib.sha256(raw).hexdigest(),
    )
