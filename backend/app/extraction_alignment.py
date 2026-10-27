import copy
import json
import re
from collections import Counter

from backend.app.annotation_candidates import BULLET, candidate_clauses
from backend.app.extraction_source import ROOT
from backend.app.extraction_validation import validate_extraction

ALIGNMENTS = ROOT / "results/extraction-alignment"


def matches(text, quotation):
    if not quotation.strip():
        return []
    pattern = r"\s+".join(re.escape(part) for part in quotation.split())
    return [(match.start(), match.end()) for match in re.finditer(pattern, text)]


def canonical(text):
    return " ".join(text.split())


def align(payload, source, timestamp):
    proposed = copy.deepcopy(payload)
    clauses = candidate_clauses(source.text)
    entries = []
    evidence = {item["criterion_id"]: item for item in proposed["evidence"]}
    nodes = []

    def visit(items):
        for node in items:
            nodes.append(node)
            visit(node.get("dependencies") or [])
    visit(proposed["criteria"])
    for node in nodes:
        occurrences = matches(source.text, node["original_text"])
        row = {"criterion_id": node["criterion_id"], "proposal": copy.deepcopy(node),
               "match_count": len(occurrences), "status": "missing_match", "issues": [],
               "clause": None, "context": None, "heading": None,
               "original_evidence": copy.deepcopy(evidence.get(node["criterion_id"]))}
        entries.append(row)
        if len(occurrences) != 1:
            row["status"] = "ambiguous_match" if occurrences else "missing_match"
            continue
        start, end = occurrences[0]
        containing = [c for c in clauses if c["original"]["span"]["start"] <= start < end <= c["original"]["span"]["end"]]
        if len(containing) != 1:
            row["status"] = "boundary_review"
            continue
        clause = containing[0]
        row.update(clause=clause["original"], context=clause["context"], heading=clause["heading"])
        row["candidate_id"] = clause["id"]
        original = clause["original"]["text"]
        body = BULLET.sub("", original, count=1)
        if (canonical(node["original_text"]) not in (canonical(original), canonical(body))
                or clause["warnings"]):
            row["status"] = "boundary_review"
            continue
        entry = evidence.get(node["criterion_id"])
        if entry is None or clause["heading"] is None:
            row["status"] = "provenance_review"
            continue
        node["original_text"] = original
        entry["original_span"] = copy.deepcopy(clause["original"]["span"])
        entry["polarity_span"] = copy.deepcopy(clause["heading"]["span"])
        for field, span in entry["fields"].items():
            value = node.get(field)
            locations = matches(original, value) if isinstance(value, str) else []
            if len(locations) == 1:
                a, b = locations[0]
                if original[a:b] == value:
                    span.update(start=entry["original_span"]["start"] + a,
                                end=entry["original_span"]["start"] + b)
        row["status"] = "proposed_alignment"
    _, errors = validate_extraction(json.dumps(proposed), source, method="offline-source-alignment", timestamp=timestamp)
    schema_failed = any(error["code"] in ("schema_error", "invalid_json_or_schema") for error in errors)
    counts = Counter(row.get("candidate_id") for row in entries if row.get("candidate_id"))
    accepted = set()
    for row in entries:
        row["issues"] = [error for error in errors if error["criterion_id"] == row["criterion_id"]]
        if row["status"] == "proposed_alignment":
            if schema_failed:
                row["status"] = "provenance_review"
            elif counts[row["candidate_id"]] > 1:
                row["status"] = "ambiguous_match"
            elif row["issues"]:
                row["status"] = "clinical_review"
            else:
                row["status"] = "automatically_recovered"
                row["applied_evidence"] = copy.deepcopy(evidence[row["criterion_id"]])
                accepted.add(row["criterion_id"])
    recovered = copy.deepcopy(payload)
    proposed_nodes = {node["criterion_id"]: node for node in nodes}

    def apply(items):
        for node in items:
            if node["criterion_id"] in accepted:
                node["original_text"] = proposed_nodes[node["criterion_id"]]["original_text"]
            apply(node.get("dependencies") or [])
    apply(recovered["criteria"])
    for entry in recovered["evidence"]:
        if entry["criterion_id"] in accepted:
            entry.update(copy.deepcopy(evidence[entry["criterion_id"]]))
    return recovered, {"entries": entries, "counts": dict(Counter(row["status"] for row in entries)),
                       "human_review_required": True,
                       "note": "Alignment is not human review. Only entries passing existing local checks are applied."}


def review_proposals(source):
    for path in sorted(ALIGNMENTS.glob("*/manifest.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if (manifest["snapshot_sha256"] != source.sha256 or manifest["nct_id"] != source.nct_id
                    or manifest["source_snapshot"] != source.source_snapshot):
                continue
            report = json.loads(path.with_name("alignment_report.json").read_text(encoding="utf-8"))
            result = []
            for row in report["entries"]:
                quote = row.get("clause")
                if quote and source.text[quote["span"]["start"]:quote["span"]["end"]] == quote["text"]:
                    result.append(row)
            return result
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return []
