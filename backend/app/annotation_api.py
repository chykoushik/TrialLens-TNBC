import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.benchmark_models import ReferenceAnnotation, SLOTS, validate_reference
from backend.app.eligibility_benchmark import DATASET_VERSION, TRIAL_IDS, digest, evaluate_dataset, read_json, write_json
from backend.app.extraction_source import ROOT
from backend.app.trial_extraction_api import select_source
from backend.app import research_api
from backend.app.saved_trials import catalog
from backend.app.annotation_candidates import candidate_clauses
from backend.app.extraction_alignment import review_proposals

router = APIRouter(prefix="/annotations", tags=["offline reference annotation"])
STORAGE = ROOT / "data/annotations"
RESULTS = ROOT / "results/annotation-evaluation"


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot: str = Field(max_length=200)
    reference: ReferenceAnnotation


class Save(Document):
    reviewer: str = Field(min_length=1, max_length=100)
    note: str = Field(min_length=1, max_length=4000)
    stage: Literal["draft", "reviewed", "adjudicated"] = "draft"
    approve_review: bool = False
    parent: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    operation: Literal["edit", "import"] = "edit"


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prediction_directory: str | None = Field(default=None, max_length=300)
    references: dict[str, str] = Field(default_factory=dict, max_length=5)
    predictions: dict[str, str] = Field(default_factory=dict, max_length=5)


class Audit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: str = Field(pattern=r"^[a-f0-9]{32}$")
    parent: str | None
    stage: Literal["draft", "reviewed", "adjudicated"]
    reviewer: str = Field(min_length=1, max_length=100)
    note: str = Field(min_length=1, max_length=4000)
    operation: Literal["edit", "import"]
    saved_at: str
    reference_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def source_for(nct_id, snapshot=None):
    if nct_id not in TRIAL_IDS:
        raise HTTPException(404, "Study outside saved benchmark")
    source = select_source(nct_id, snapshot)
    if source.is_synthetic is True:
        raise HTTPException(422, "Public protocol required")
    return source


def check(source, reference):
    if reference.nct_id != source.nct_id or reference.snapshot_sha256 != source.sha256:
        raise HTTPException(409, "Annotation source hash or NCT ID mismatch")
    try:
        validate_reference(reference, source.text)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


def coverage(reference):
    def visit(nodes):
        for node in nodes:
            yield node
            yield from visit(node.dependencies)
    nodes = list(visit(reference.criteria))
    return {"criteria": len(nodes), "inventory": reference.inventory_review.status,
            "reviewed_boundaries": sum(node.boundary_review.status == "reviewed" for node in nodes),
            "unreviewed_boundaries": sum(node.boundary_review.status != "reviewed" for node in nodes),
            "reviewed_slots": sum(getattr(node, slot).review.status == "reviewed" for node in nodes for slot in SLOTS),
            "unreviewed_slots": sum(getattr(node, slot).review.status != "reviewed" for node in nodes for slot in SLOTS)}


def load_version(nct_id, version):
    if nct_id not in TRIAL_IDS or len(version) != 32 or any(c not in "0123456789abcdef" for c in version):
        raise HTTPException(404, "Annotation version not found")
    try:
        bundle = read_json(STORAGE / nct_id / version / "export.json")
    except FileNotFoundError as error:
        raise HTTPException(404, "Annotation version not found") from error
    source = source_for(nct_id, bundle["snapshot"])
    reference = ReferenceAnnotation.model_validate(bundle["reference"])
    check(source, reference)
    if asdict(source) != bundle["source"]:
        raise HTTPException(409, "Saved source provenance changed")
    canonical = canonical_json(reference.model_dump(mode="json"))
    if hashlib.sha256(canonical.encode()).hexdigest() != bundle["audit"]["reference_sha256"]:
        raise HTTPException(409, "Saved reference checksum mismatch")
    return bundle, source, reference


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


@router.get("/{nct_id}")
def workspace(nct_id: str, snapshot: str | None = Query(default=None, max_length=200)):
    source = source_for(nct_id, snapshot)
    reference = ReferenceAnnotation(nct_id=nct_id, snapshot_sha256=source.sha256)
    versions = []
    for path in sorted((STORAGE / nct_id).glob("*/export.json")):
        bundle = read_json(path)
        if bundle["source"]["source_snapshot"] == source.source_snapshot and bundle["source"]["sha256"] == source.sha256:
            versions.append(bundle["audit"])
    return {"extraction_proposals": review_proposals(source), "candidates": candidate_clauses(source.text), "source": asdict(source), "reference": reference.model_dump(mode="json"),
            "versions": sorted(versions, key=lambda item: item["saved_at"]), "slots": SLOTS,
            "snapshots": [item for item in catalog(research_api.RAW_TRIALS_DIR, history=True)[0] if item["nct_id"] == nct_id],
            "schema": ReferenceAnnotation.model_json_schema(), "coverage": coverage(reference)}


@router.post("/{nct_id}/validate")
def validate(nct_id: str, request: Document):
    source = source_for(nct_id, request.snapshot)
    check(source, request.reference)
    return {"valid": True, "coverage": coverage(request.reference), "assessment_allowed": False}


@router.post("/{nct_id}/import")
def import_reference(nct_id: str, bundle: dict):
    try:
        if bundle["bundle_version"] != "eligibility-review-bundle-v1":
            raise ValueError("Unsupported review bundle")
        source = source_for(nct_id, bundle["snapshot"])
        if bundle["source"] != asdict(source):
            raise HTTPException(409, "Imported source provenance mismatch")
        reference = ReferenceAnnotation.model_validate(bundle["reference"])
        check(source, reference)
        audit = Audit.model_validate(bundle["audit"])
        timestamp = datetime.fromisoformat(audit.saved_at.replace("Z", "+00:00"))
        if timestamp.tzinfo is None or not audit.reviewer.strip():
            raise ValueError("Invalid audit identity or timestamp")
        if hashlib.sha256(canonical_json(reference.model_dump(mode="json")).encode()).hexdigest() != audit.reference_sha256:
            raise HTTPException(409, "Imported reference checksum mismatch")
    except (KeyError, ValueError, ValidationError) as error:
        raise HTTPException(422, "Invalid review bundle; check schema and provenance") from error
    return {"reference": reference.model_dump(mode="json"), "coverage": coverage(reference),
            "stage": "draft", "message": "Imported claims are unverified. Explicit local review is required."}


@router.post("/{nct_id}/versions")
def save(nct_id: str, request: Save):
    source = source_for(nct_id, request.snapshot)
    check(source, request.reference)
    if not request.reviewer.strip() or not request.note.strip():
        raise HTTPException(422, "Reviewer and audit note required")
    parent = None
    if request.parent:
        parent, previous_source, previous_reference = load_version(nct_id, request.parent)
        if previous_source != source:
            raise HTTPException(409, "Parent snapshot differs")
        if request.reference.annotation_revision <= previous_reference.annotation_revision:
            raise HTTPException(409, "Increment annotation revision")
    if request.stage != "draft":
        if not request.approve_review:
            raise HTTPException(422, "Explicit human approval required")
        if not coverage(request.reference)["reviewed_boundaries"]:
            raise HTTPException(422, "Review criterion boundaries explicitly first")
    if request.stage == "adjudicated":
        if not parent or parent["audit"]["stage"] != "reviewed":
            raise HTTPException(422, "Adjudication requires a saved reviewed parent")
        def reviewers(value):
            if isinstance(value, dict):
                yield from ([value["reviewer"]] if value.get("status") == "reviewed" else [])
                for child in value.values():
                    yield from reviewers(child)
            elif isinstance(value, list):
                for child in value:
                    yield from reviewers(child)
        identities = {parent["audit"]["reviewer"], *reviewers(parent["reference"])}
        if request.reviewer.strip().casefold() in {item.strip().casefold() for item in identities}:
            raise HTTPException(422, "Adjudicator must differ from prior reviewers")
    version = uuid4().hex
    audit = {"version": version, "parent": request.parent, "stage": request.stage,
             "reviewer": request.reviewer.strip(), "note": request.note, "operation": request.operation,
             "saved_at": datetime.now(timezone.utc).isoformat(),
             "reference_sha256": hashlib.sha256(canonical_json(request.reference.model_dump(mode="json")).encode()).hexdigest()}
    bundle = {"bundle_version": "eligibility-review-bundle-v1", "snapshot": request.snapshot,
              "source": asdict(source), "reference": request.reference.model_dump(mode="json"), "audit": audit}
    directory = STORAGE / nct_id / version
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "reference.json", bundle["reference"])
    write_json(directory / "export.json", bundle)
    return {"bundle": bundle, "export_json": canonical_json(bundle),
            "path": (directory / "export.json").relative_to(ROOT).as_posix()}


@router.get("/{nct_id}/versions/{version}")
def export(nct_id: str, version: str):
    bundle, _, _ = load_version(nct_id, version)
    return {"bundle": bundle, "export_json": canonical_json(bundle)}


@router.post("/{nct_id}/versions/{version}/evaluate")
def evaluate(nct_id: str, version: str, request: EvaluationRequest):
    bundle, selected_source, reference = load_version(nct_id, version)
    if bundle["audit"]["stage"] not in ("reviewed", "adjudicated"):
        raise HTTPException(409, "Drafts cannot supply evaluation reference labels")
    if set(request.references) - set(TRIAL_IDS) or set(request.predictions) - set(TRIAL_IDS):
        raise HTTPException(422, "Evaluation selection outside benchmark")
    if request.references.get(nct_id, version) != version:
        raise HTTPException(409, "Current saved version differs from evaluation selection")
    selected = {nct_id: (bundle, selected_source, reference)}
    for identifier, reference_version in request.references.items():
        selected[identifier] = load_version(identifier, reference_version)
        if selected[identifier][0]["audit"]["stage"] not in ("reviewed", "adjudicated"):
            raise HTTPException(409, "Drafts cannot supply evaluation reference labels")
    output = RESULTS / uuid4().hex
    dataset = output / "dataset"
    dataset.mkdir(parents=True, exist_ok=False)
    entries = []
    for identifier in TRIAL_IDS:
        source = selected[identifier][1] if identifier in selected else source_for(identifier)
        annotation = selected[identifier][2] if identifier in selected else ReferenceAnnotation(nct_id=identifier, snapshot_sha256=source.sha256)
        directory = dataset / identifier
        directory.mkdir()
        write_json(directory / "source.json", asdict(source))
        (directory / "source.txt").write_bytes(source.text.encode("utf-8"))
        write_json(directory / "reference.json", annotation.model_dump(mode="json"))
        entries.append({"nct_id": identifier, "snapshot_sha256": source.sha256,
                        "source_snapshot": source.source_snapshot, "text_sha256": digest(source.text)})
    write_json(dataset / "manifest.json", {"dataset_version": DATASET_VERSION,
               "annotation_version": reference.annotation_version, "trials": entries,
               "approved_versions": {identifier: item[0]["audit"] for identifier, item in selected.items()}})
    predictions = output / "predictions.json"
    prediction_paths = {**request.predictions, **({nct_id: request.prediction_directory} if request.prediction_directory else {})}
    write_json(predictions, {"predictions": prediction_paths})
    try:
        report = evaluate_dataset(dataset, output / "report", predictions=predictions)
    except (ValueError, OSError) as error:
        raise HTTPException(422, "Evaluation failed; inspect local input paths") from error
    return {"report": report, "path": (output / "report").relative_to(ROOT).as_posix()}
