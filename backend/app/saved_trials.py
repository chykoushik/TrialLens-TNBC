import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from backend.app.trial_parser import parse_trials


def snapshot_path(root: Path, snapshot: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+/response\.json", snapshot):
        raise ValueError("Invalid snapshot identity")
    path = (root / snapshot).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Snapshot is outside local trial storage")
    if not path.with_name("metadata.json").resolve().is_relative_to(root.resolve()):
        raise ValueError("Metadata is outside local trial storage")
    return path


def retrieval_order(record):
    try:
        timestamp = datetime.fromisoformat(record["retrieved_at"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError
        timestamp = timestamp.astimezone(timezone.utc)
    except (TypeError, ValueError, AttributeError):
        timestamp = datetime.min.replace(tzinfo=timezone.utc)
    return timestamp, record["snapshot"]


def catalog(root: Path, *, history=False):
    records, warnings = [], []
    for path in sorted(root.glob("*/response.json")):
        try:
            snapshot = path.relative_to(root).as_posix()
            safe = snapshot_path(root, snapshot)
            raw = safe.read_bytes()
            payload = json.loads(raw)
            metadata_path = safe.with_name("metadata.json")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
            for trial in parse_trials(payload):
                records.append({**trial.model_dump(), "snapshot": snapshot,
                                "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
                                "retrieved_at": metadata.get("retrieved_at"),
                                "is_synthetic": payload.get("is_synthetic")})
        except (OSError, ValueError, TypeError, AttributeError):
            warnings.append(f"Unreadable snapshot: {path.parent.name}")
    records.sort(key=retrieval_order, reverse=True)
    if history:
        return records, warnings
    latest, seen = [], set()
    for record in records:
        identifier = record["nct_id"]
        if identifier is not None and identifier in seen:
            continue
        if identifier is not None:
            seen.add(identifier)
        latest.append({**record, "snapshot_count": sum(item["nct_id"] == identifier for item in records)
                       if identifier is not None else 1})
    return latest, warnings
