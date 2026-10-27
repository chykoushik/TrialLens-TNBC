import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from backend.app.extraction_source import ROOT, load_source
from backend.app.extraction_validation import unique_object, validate_extraction


def normalize_evidence(payload):
    candidate = copy.deepcopy(payload)
    changes = []
    for index, entry in enumerate(candidate.get("evidence", [])):
        for field in ("logical_operator", "dependencies"):
            if field in entry and entry[field] is None:
                del entry[field]
                changes.append({"path": f"evidence.{index}.{field}", "removed_value": None})
    return candidate, changes


def recover(directory: Path, *, source_alignment=False):
    directory = (ROOT / directory).resolve()
    if not directory.is_relative_to((ROOT / "results/extraction").resolve()):
        raise ValueError("Invalid extraction directory")
    originals = {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}
    manifest = json.loads(originals["manifest.json"])
    source = load_source(Path(manifest["source_snapshot"]), manifest["nct_id"])
    if source.sha256 != manifest["snapshot_sha256"]:
        raise ValueError("Snapshot hash mismatch")
    raw = json.loads(originals["raw_response.json"], object_pairs_hook=unique_object)
    choice = raw["choices"][0]
    if choice.get("finish_reason") != "stop":
        raise ValueError("Incomplete saved response")
    payload = json.loads(choice["message"]["content"], object_pairs_hook=unique_object)
    candidate, changes = normalize_evidence(payload)
    timestamp = datetime.now(timezone.utc).isoformat()
    alignment_report = None
    if source_alignment:
        from backend.app.extraction_alignment import align
        candidate, alignment_report = align(candidate, source, timestamp)
    validated, errors = validate_extraction(
        json.dumps(candidate), source, method="offline-source-alignment" if source_alignment else "offline-null-evidence-normalization", timestamp=timestamp,
    )
    report = {
        "mode": "derived_offline_revalidation", "timestamp": timestamp,
        "original_directory": directory.relative_to(ROOT).as_posix(),
        "original_sha256": {name: hashlib.sha256(value).hexdigest() for name, value in originals.items()},
        "source_snapshot": source.source_snapshot, "snapshot_sha256": source.sha256,
        "nct_id": source.nct_id, "normalizations": changes,
        "evidence_count": len(candidate["evidence"]),
        "status": "validated" if validated is not None else "validation_failed",
        "human_review_required": True, "validation_scope": "structural_and_source_only",
        "request_count": 0,
    }
    destination = ROOT / ("results/extraction-alignment" if source_alignment else "results/extraction-recovery") / uuid4().hex
    destination.mkdir(parents=True, exist_ok=False)
    artifacts = {"manifest.json": report, "normalized_candidate.json": candidate,
                 "validated.json": validated.model_dump(mode="json") if validated else None,
                 "validation_errors.json": errors}
    if alignment_report is not None:
        artifacts["alignment_report.json"] = alignment_report
        report["alignment_counts"] = alignment_report["counts"]
    for name, value in artifacts.items():
        with (destination / name).open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
    if any((directory / name).read_bytes() != value for name, value in originals.items()):
        raise ValueError("Original artifacts changed")
    return destination, report, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--align-source", action="store_true")
    args = parser.parse_args()
    destination, report, errors = recover(args.directory, source_alignment=args.align_source)
    print(json.dumps({"directory": destination.relative_to(ROOT).as_posix(),
                      "status": report["status"], "error_count": len(errors)}))


if __name__ == "__main__":
    main()
