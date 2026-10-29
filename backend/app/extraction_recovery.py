import hashlib
import json
import re

from backend.app.extraction_validation import unique_object, validate_extraction


def recover_truncated_criteria(content, source, *, finish_reason, timestamp):
    if finish_reason != "length" or not isinstance(content, str):
        return None
    prefix = re.match(r'\s*\{\s*"criteria"\s*:\s*\[', content)
    if prefix is None:
        return None
    decoder = json.JSONDecoder(object_pairs_hook=unique_object)
    position = prefix.end()
    recovered = []
    while position < len(content):
        position += len(content[position:]) - len(content[position:].lstrip())
        start = position
        if content[position:position + 1] != "{":
            break
        try:
            node, end = decoder.raw_decode(content, position)
        except (ValueError, RecursionError):
            break
        recovered.append({"candidate": node, "response_span": {"start": start, "end": end}})
        position = end
        position += len(content[position:]) - len(content[position:].lstrip())
        if content[position:position + 1] != ",":
            break
        position += 1

    def anchors(node, path):
        if not isinstance(node, dict):
            return []
        text = node.get("original_text")
        matches = [match.start() for match in re.finditer(re.escape(text), source.text)] if isinstance(text, str) and text else []
        span = {"start": matches[0], "end": matches[0] + len(text)} if len(matches) == 1 else None
        row = {"path": path, "criterion_id": node.get("criterion_id"), "exact_match_count": len(matches),
               "source_span": span, "span_origin": "offline_exact_text_search_not_provider_evidence",
               "clinical_meaning_verified": False, "executable": False}
        children = node.get("dependencies")
        return [row] + [item for index, child in enumerate(children if isinstance(children, list) else [])
                        for item in anchors(child, f"{path}.dependencies[{index}]")]

    for index, item in enumerate(recovered):
        item["source_checks"] = anchors(item["candidate"], f"criteria[{index}]")
    candidates = [item["candidate"] for item in recovered]
    _, original_errors = validate_extraction(content, source, method="offline-truncated-original", timestamp=timestamp)
    _, prefix_errors = validate_extraction(json.dumps({"criteria": candidates, "evidence": []}), source,
        method="offline-partial-prefix-diagnostic-only", timestamp=timestamp)
    checks = [row for item in recovered for row in item["source_checks"]]
    return {"status": "partial_unvalidated", "complete_extraction": False, "assessment_allowed": False,
            "nct_id": source.nct_id, "snapshot_sha256": source.sha256, "source_snapshot": source.source_snapshot,
            "response_content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "provider_evidence_recovered": False, "finish_reason": finish_reason,
            "complete_top_level_objects": len(recovered), "complete_nodes_including_dependencies": len(checks),
            "exact_source_top_level_objects": sum(bool(item["source_checks"] and item["source_checks"][0]["exact_match_count"]) for item in recovered),
            "exact_source_nodes": sum(row["exact_match_count"] > 0 for row in checks),
            "unparsed_tail_start": position, "unparsed_tail_characters": len(content) - position,
            "objects": recovered, "original_validation_errors": original_errors,
            "prefix_validation_errors": prefix_errors,
            "scope": "Intact JSON objects only, preserved verbatim with response offsets. No truncated object, missing criterion or evidence entry is completed. Exact text matches do not validate polarity, field attribution, logical scope or clinical meaning. Never an executable extraction."}
