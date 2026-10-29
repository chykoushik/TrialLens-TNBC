import json
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Path, Query

from backend.app import annotation_api
from backend.app.annotation_candidates import candidate_clauses
from backend.app.benchmark_models import ReferenceAnnotation, validate_reference
from backend.app.extraction_source import ROOT
from backend.app.extraction_validation import validate_extraction
from backend.app.trial_extraction_api import select_source

router = APIRouter(prefix="/research/trials", tags=["saved real trial review"])
EXTRACTIONS = ROOT / "results/extraction"
REFERENCES = ROOT / "data/benchmarks/tnbc-eligibility-v1"


def reviewed_annotations(source):
    references = []
    rejected = 0
    candidates = [REFERENCES / source.nct_id / "reference.json"]
    candidates += sorted((annotation_api.STORAGE / source.nct_id).glob("*/export.json"))
    for path in candidates:
        if not path.exists():
            continue
        try:
            if path.name == "export.json":
                _, selected, reference = annotation_api.load_version(source.nct_id, path.parent.name)
                if selected != source:
                    continue
            else:
                reference = ReferenceAnnotation.model_validate_json(path.read_text(encoding="utf-8"))
            if reference.nct_id != source.nct_id or reference.snapshot_sha256 != source.sha256:
                continue
            validate_reference(reference, source.text)
            for node in reference.criteria:
                if node.boundary_review.status == "reviewed":
                    references.append({"original_text": node.original.text,
                        "start": node.original.span.start, "end": node.original.span.end,
                        "polarity": node.polarity.value if node.polarity.review.status == "reviewed" else None,
                        "logic": node.logic.value.model_dump() if node.logic.review.status == "reviewed" and node.logic.value else None,
                        "executable": False})
        except (OSError, ValueError, TypeError, KeyError, HTTPException):
            rejected += 1
    unique = {(item["start"], item["end"]): item for item in references}
    return list(unique.values()), rejected


def saved_extractions(source):
    reports = []
    for path in sorted(EXTRACTIONS.glob("*/manifest.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if (manifest.get("nct_id"), manifest.get("source_snapshot"), manifest.get("snapshot_sha256")) != (source.nct_id, source.source_snapshot, source.sha256):
                continue
            valid = False
            if manifest.get("status") not in ("failed", "privacy_failed"):
                raw = json.loads(path.with_name("raw_response.json").read_text(encoding="utf-8"))
                content = raw.get("content") if manifest.get("mode") == "mock" else raw["choices"][0]["message"]["content"]
                model, errors = validate_extraction(content, source, method="saved-output-revalidation", timestamp=manifest["timestamp"])
                valid = model is not None and not errors
            reports.append({"mode": manifest.get("mode"), "saved_status": manifest.get("status"), "source_structure_valid": valid})
        except (OSError, ValueError, TypeError, KeyError, IndexError):
            continue
    return reports


@router.get("/{nct_id}/review")
def review(nct_id: str = Path(pattern=r"^NCT\d{8}$"), snapshot: str | None = Query(default=None, max_length=200),
           snapshot_sha256: str | None = Query(default=None, pattern=r"^[a-f0-9]{64}$")):
    source = select_source(nct_id, snapshot)
    if source.is_synthetic is True:
        raise HTTPException(422, "Choose a saved real registry record. Fictional cases are separate.")
    if snapshot_sha256 is not None and snapshot_sha256 != source.sha256:
        raise HTTPException(409, "Saved source changed. Reload the trial library before continuing.")
    reviewed, rejected = reviewed_annotations(source)
    passages = [{"text": clause["original"]["text"], "span": clause["original"]["span"],
                 "section": clause["suggested_polarity"], "state": "unknown",
                 "reason": "No approved executable binding or authorized patient evidence is available for this passage."}
                for clause in candidate_clauses(source.text)]
    return {"source": asdict(source), "source_passages": passages, "reviewed_source_criteria": reviewed,
            "rejected_annotation_artifacts": rejected, "saved_extractions": saved_extractions(source),
            "executable_mapping_count": 0, "assessment_available": False, "complete_eligibility_available": False,
            "patient_evidence": [], "planning": {"available": False, "selected_reports": [],
                "missing_inputs": ["Reviewed executable criterion bindings covering the relevant trial logic",
                    "Authorized, source-linked patient evidence", "Longitudinal report outcomes, dependencies, costs and an appropriate probability model"]},
            "scope": "Source review only. Source-span and structural validation do not establish clinical meaning or executable bindings. All unmapped conditions remain unresolved."}
