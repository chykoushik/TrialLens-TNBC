import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from pydantic import ValidationError

from backend.app.benchmark_models import (
    ANNOTATION_VERSION, SLOTS, ReferenceAnnotation, ReferenceCriterion, validate_reference,
)
from backend.app.extraction_source import ROOT, EligibilitySource, load_source
from backend.app.extraction_validation import unique_object, validate_extraction
from backend.app.saved_trials import catalog

DATASET_VERSION = "tnbc-eligibility-v1"
TRIAL_IDS = ("NCT01770353", "NCT02648477", "NCT03538028", "NCT04331067", "NCT04691375")
TIMESTAMP = "2000-01-01T00:00:00+00:00"
SLOT_MAPPING = {"polarity": "criterion_type", "threshold_operator": "comparator",
                "threshold_value": "threshold", "unit": "unit", "temporal_constraint": "temporal_constraint",
                "cohort": "cohort", "biomarker": "biomarker", "assay": "assay"}


def local_path(path):
    resolved = (ROOT / path).resolve()
    if not resolved.is_relative_to(ROOT):
        raise ValueError("Benchmark paths must be project-local")
    return resolved


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)


def write_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_dataset(output, *, raw_root=None):
    output = local_path(output)
    raw_root = local_path(raw_root or Path("data/raw/trials"))
    records, warnings = catalog(raw_root)
    history, _ = catalog(raw_root, history=True)
    selected = {record["nct_id"]: record for record in records if record["nct_id"] in TRIAL_IDS}
    if set(selected) != set(TRIAL_IDS):
        raise ValueError("Five saved studies required")
    sources = {}
    for identifier in TRIAL_IDS:
        record = selected[identifier]
        source = load_source(raw_root / record["snapshot"], identifier)
        if source.is_synthetic is True:
            raise ValueError("Benchmark requires genuine saved studies")
        sources[identifier] = source
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "annotation.schema.json", ReferenceAnnotation.model_json_schema())
    manifest = {"dataset_version": DATASET_VERSION, "annotation_version": ANNOTATION_VERSION,
                "source_kind": "saved_clinicaltrials_gov", "selection": "latest_retrieval_per_nct_id",
                "scope": "TNBC-related; includes mixed-cancer and non-TNBC cohorts",
                "assessment_allowed": False, "warnings": warnings, "trials": []}
    for identifier in TRIAL_IDS:
        record, source = selected[identifier], sources[identifier]
        directory = output / identifier
        directory.mkdir()
        with (directory / "source.txt").open("x", encoding="utf-8", newline="") as file:
            file.write(source.text)
        write_json(directory / "source.json", asdict(source))
        reference = ReferenceAnnotation(nct_id=identifier, snapshot_sha256=source.sha256)
        write_json(directory / "reference.json", reference.model_dump(mode="json"))
        lines, position = [], 0
        for number, line in enumerate(source.text.splitlines(keepends=True), 1):
            text = line.rstrip("\r\n")
            if text.strip():
                lines.append({"line_number": number, "text": text,
                              "span": {"start": position, "end": position + len(text)},
                              "review_status": "unreviewed"})
            position += len(line)
        write_json(directory / "worksheet.json", {"purpose": "Verbatim line inventory, not criterion annotations",
                   "annotation_version": ANNOTATION_VERSION, "nct_id": identifier, "lines": lines})
        example = ReferenceCriterion(reference_id="replace-manually", original={
            "span": lines[0]["span"], "text": lines[0]["text"]})
        write_json(directory / "criterion.template.json", example.model_dump(mode="json"))
        snapshots = [{"source_snapshot": (raw_root / item["snapshot"]).relative_to(ROOT).as_posix(),
                      "snapshot_sha256": item["snapshot_sha256"], "retrieved_at": item["retrieved_at"]}
                     for item in history if item["nct_id"] == identifier]
        manifest["trials"].append({"nct_id": identifier, "title": record["title"], "conditions": record["conditions"],
                                  "source_snapshot": source.source_snapshot, "snapshot_sha256": source.sha256,
                                  "text_sha256": digest(source.text), "historical_snapshots": snapshots})
    write_json(output / "manifest.json", manifest)
    return output


def ratio(correct, total):
    return {"value": correct / total if total else None, "numerator": correct, "denominator": total}


def empty_counts():
    return {"trials": 1, "missing_prediction": 0, "prediction_error": 0, "reference_error": 0,
            "unreviewed_inventory": 0, "reviewed_boundaries": 0, "unreviewed_boundaries": 0,
            "reviewed_slots": 0, "unreviewed_slots": 0, "unmatched_reviewed_criteria": 0,
            "detection_trials": 0, "tp": 0, "fp": 0, "fn": 0,
            "validation_passed": 0, "validation_evaluated": 0,
            "span_valid": 0, "span_evaluated": 0,
            "unsupported_predictions": 0, "unsupported_evaluated": 0,
            "reference_unsupported": 0, "reference_unsupported_evaluated": 0,
            **{f"{slot}_{suffix}": 0 for slot in SLOTS for suffix in ("correct", "evaluated", "missing_prediction")}}


def metrics(counts):
    tp, fp, fn = (counts[name] for name in ("tp", "fp", "fn"))
    return {"criterion_detection_precision": ratio(tp, tp + fp),
            "criterion_detection_recall": ratio(tp, tp + fn),
            "criterion_detection_f1": ratio(2 * tp, 2 * tp + fp + fn),
            "polarity_accuracy": ratio(counts["polarity_correct"], counts["polarity_evaluated"]),
            "slots": {slot: ratio(counts[f"{slot}_correct"], counts[f"{slot}_evaluated"]) for slot in SLOTS},
            "source_span_validity": ratio(counts["span_valid"], counts["span_evaluated"]),
            "unsupported_rate": ratio(counts["unsupported_predictions"], counts["unsupported_evaluated"]),
            "reference_unsupported_rate": ratio(counts["reference_unsupported"], counts["reference_unsupported_evaluated"]),
            "validation_pass_rate": ratio(counts["validation_passed"], counts["validation_evaluated"])}


def flatten(nodes):
    result = []
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("Invalid prediction node")
        result.append(node)
        if isinstance(node.get("dependencies"), list):
            result.extend(flatten(node["dependencies"]))
    return result


def exact_span(node, evidence, text):
    span = evidence.get("original_span", {})
    if not isinstance(span, dict):
        return None
    start, end = span.get("start"), span.get("end")
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
        return None
    if text[start:end] != node.get("original_text"):
        return None
    return start, end


def prediction_logic(node, evidence):
    if node.get("logical_operator") is None and node.get("dependencies") is None:
        return None
    entry = evidence.get(node.get("criterion_id"), {})
    children = node.get("dependencies")
    return {"operator": node.get("logical_operator"), "span": entry.get("original_span"),
            "children": [prediction_logic(child, evidence) for child in children] if isinstance(children, list) else []}


def load_prediction(directory, source):
    directory = local_path(directory)
    manifest = read_json(directory / "manifest.json")
    if (manifest.get("nct_id") != source.nct_id or manifest.get("snapshot_sha256") != source.sha256
            or manifest.get("source_snapshot") != source.source_snapshot):
        raise ValueError("Prediction provenance mismatch")
    raw = (directory / "raw_response.json").read_text(encoding="utf-8")
    mode = manifest.get("mode")
    if mode not in ("mock", "live", "software_test_fixture"):
        raise ValueError("Prediction mode missing")
    try:
        body = json.loads(raw, object_pairs_hook=unique_object)
        content = body["content"] if mode in ("mock", "software_test_fixture") else body["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("Invalid prediction content")
    except (ValueError, TypeError, KeyError, IndexError):
        content = raw
    validated, errors = validate_extraction(content, source, method="offline-benchmark", timestamp=TIMESTAMP)
    try:
        payload = json.loads(content, object_pairs_hook=unique_object)
        if not isinstance(payload, dict) or not isinstance(payload.get("criteria"), list) or not isinstance(payload.get("evidence"), list):
            raise ValueError("Invalid prediction envelope")
        evidence = {}
        for entry in payload["evidence"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("criterion_id"), str) or entry["criterion_id"] in evidence:
                raise ValueError("Invalid prediction evidence")
            evidence[entry["criterion_id"]] = entry
        nodes = payload["criteria"]
        all_nodes = flatten(nodes)
        if (len(all_nodes) > 10000 or not all(isinstance(node, dict) for node in nodes)
                or any(not isinstance(node.get("criterion_id"), str) for node in all_nodes)):
            raise ValueError("Invalid prediction nodes")
    except (ValueError, TypeError, RecursionError):
        nodes, evidence = [], {}
    return {"nodes": nodes, "evidence": evidence, "errors": errors,
            "validation_passed": validated is not None, "mode": mode,
            "model_id": manifest.get("requested_model"), "prompt_version": manifest.get("prompt_version"),
            "raw_response_sha256": hashlib.sha256((directory / "raw_response.json").read_bytes()).hexdigest(),
            "manifest_sha256": hashlib.sha256((directory / "manifest.json").read_bytes()).hexdigest(),
            "artifact_directory": directory.relative_to(ROOT).as_posix()}


def score_trial(annotation, source, prediction):
    counts, errors = empty_counts(), []
    complete = annotation.inventory_review.status == "reviewed"
    counts["unreviewed_inventory"] = int(not complete)
    counts["missing_prediction"] = int(prediction is None)
    reviewed = [node for node in annotation.criteria if node.boundary_review.status == "reviewed"]
    counts["reviewed_boundaries"] = len(reviewed)
    counts["unreviewed_boundaries"] = len(annotation.criteria) - len(reviewed)
    def reference_nodes(nodes):
        return [item for node in nodes for item in [node, *reference_nodes(node.dependencies)]]

    all_references = reference_nodes(annotation.criteria)
    counts["unreviewed_slots"] = sum(getattr(node, slot).review.status != "reviewed"
                                      for node in all_references for slot in SLOTS)
    counts["reviewed_slots"] = sum(getattr(node, slot).review.status == "reviewed"
                                    for node in all_references for slot in SLOTS)
    if prediction is None:
        errors.append({"code": "missing_prediction"})
    nodes = prediction["nodes"] if prediction else []
    evidence = prediction["evidence"] if prediction else {}
    unmatched = list(range(len(nodes)))
    matches = {}
    for reference in reviewed:
        expected = (reference.original.span.start, reference.original.span.end)
        index = next((i for i in unmatched if exact_span(nodes[i], evidence.get(nodes[i].get("criterion_id"), {}), source.text) == expected), None)
        if index is None:
            counts["unmatched_reviewed_criteria"] += 1
            errors.append({"code": "missed_reference_criterion", "reference_id": reference.reference_id})
        else:
            matches[reference.reference_id] = nodes[index]
            unmatched.remove(index)
    if complete and prediction is not None:
        counts.update(detection_trials=1, tp=len(matches), fp=len(unmatched), fn=len(reviewed) - len(matches),
                      validation_passed=int(prediction["validation_passed"]), validation_evaluated=1)
        errors.extend({"code": "unmatched_prediction", "prediction_index": index} for index in unmatched)
        span_codes = {"missing_evidence", "unsupported_original_text", "unsupported_polarity", "unsupported_field",
                      "field_evidence_mismatch", "partial_numeric_threshold", "partial_comparator",
                      "dependency_outside_parent", "crosses_section_boundary"}
        for node in flatten(nodes):
            counts["span_evaluated"] += 1
            node_errors = [e for e in prediction["errors"] if e.get("criterion_id") == node.get("criterion_id")]
            valid = exact_span(node, evidence.get(node.get("criterion_id"), {}), source.text) is not None
            entry = evidence.get(node.get("criterion_id"), {})
            valid = valid and "polarity_span" in entry and isinstance(entry.get("fields"), dict)
            valid = valid and not any(e["code"] in span_codes for e in node_errors)
            valid = valid and not any(e["code"] in ("schema_error", "invalid_json_or_schema") for e in prediction["errors"])
            counts["span_valid"] += int(valid)
    if prediction:
        errors.extend(prediction["errors"])
    def match_dependencies(reference, predicted):
        children = predicted.get("dependencies") if predicted else None
        available = list(children) if isinstance(children, list) else []
        for child in reference.dependencies:
            expected = (child.original.span.start, child.original.span.end)
            match = next((candidate for candidate in available if exact_span(
                candidate, evidence.get(candidate.get("criterion_id"), {}), source.text) == expected), None)
            if match is not None:
                available.remove(match)
                matches[child.reference_id] = match
            match_dependencies(child, match)

    for reference in reviewed:
        match_dependencies(reference, matches.get(reference.reference_id))
    for reference in all_references:
        if reference.boundary_review.status != "reviewed":
            continue
        node = matches.get(reference.reference_id)
        for slot in SLOTS:
            label = getattr(reference, slot)
            if label.review.status != "reviewed":
                continue
            if slot == "unsupported_semantics" and label.value is not None:
                counts["reference_unsupported_evaluated"] += 1
                counts["reference_unsupported"] += int(label.value)
            if prediction is None:
                counts[f"{slot}_missing_prediction"] += 1
                continue
            counts[f"{slot}_evaluated"] += 1
            if node is None:
                counts[f"{slot}_missing_prediction"] += 1
                continue
            if slot in SLOT_MAPPING:
                actual = node.get(SLOT_MAPPING[slot], "__missing_field__")
                if SLOT_MAPPING[slot] not in node:
                    counts[f"{slot}_missing_prediction"] += 1
            elif slot == "logic":
                actual = prediction_logic(node, evidence)
            elif slot == "unsupported_semantics":
                actual = node.get("logical_operator") is None or any(
                    e.get("criterion_id") == node.get("criterion_id") for e in prediction["errors"])
                if label.value is not None:
                    counts["unsupported_evaluated"] += 1
                    counts["unsupported_predictions"] += int(actual)
            else:
                actual = "__unsupported_model_slot__"
                counts[f"{slot}_missing_prediction"] += 1
            expected = label.value.model_dump(mode="json") if hasattr(label.value, "model_dump") else label.value
            correct = actual == expected
            counts[f"{slot}_correct"] += int(correct)
            if not correct:
                errors.append({"code": "slot_mismatch", "reference_id": reference.reference_id, "slot": slot,
                               "expected": expected, "actual": actual})
    return counts, errors


def load_trial(dataset, entry, *, allow_test_fixture=False):
    identifier = entry["nct_id"]
    if identifier not in TRIAL_IDS and not allow_test_fixture:
        raise ValueError("Unexpected trial identity")
    directory = local_path(dataset / identifier)
    if not directory.is_relative_to(dataset):
        raise ValueError("Trial outside dataset")
    source = EligibilitySource(**read_json(directory / "source.json"))
    if source.is_synthetic is True and not allow_test_fixture:
        raise ValueError("Synthetic data cannot be clinical benchmark sources")
    with (directory / "source.txt").open(encoding="utf-8", newline="") as file:
        original = file.read()
    if (source.nct_id != identifier or source.sha256 != entry["snapshot_sha256"]
            or source.source_snapshot != entry["source_snapshot"] or source.text != original
            or digest(original) != entry["text_sha256"]):
        raise ValueError("Dataset source identity mismatch")
    saved = load_source(Path(source.source_snapshot), identifier)
    if saved != source:
        raise ValueError("Original snapshot identity changed")
    annotation_path = directory / "reference.json"
    annotation = ReferenceAnnotation.model_validate(read_json(annotation_path))
    if annotation.nct_id != identifier or annotation.snapshot_sha256 != source.sha256:
        raise ValueError("Annotation provenance mismatch")
    validate_reference(annotation, original, allow_test_fixture=allow_test_fixture)
    return source, annotation, hashlib.sha256(annotation_path.read_bytes()).hexdigest()


def report_markdown(report, title):
    lines = [f"# {title}", "", "Offline research benchmark. Assessment remains blocked.", "",
             "Unavailable metrics are null; no unreviewed labels are treated as gold.", "",
             "## Metrics", "", "| Metric | Value | Numerator | Denominator |", "| --- | --- | --- | --- |"]
    if "source_snapshot" in report:
        lines[4:4] = [f"Source: {report['source_url']}", "",
                      f"Snapshot: `{report['source_snapshot']}`", "",
                      f"Snapshot SHA-256: `{report['snapshot_sha256']}`", "",
                      f"Annotation SHA-256: `{report['reference_sha256']}`", ""]
    for name, metric in report["metrics"].items():
        values = metric.items() if name == "slots" else [(name, metric)]
        for label, value in values:
            number = "Unavailable" if value["value"] is None else f"{value['value']:.6f}"
            lines.append(f"| {label} | {number} | {value['numerator']} | {value['denominator']} |")
    lines += ["", "## Counts and missing data", ""]
    lines += [f"- {name}: {value}" for name, value in sorted(report["counts"].items())]
    lines += ["", "## Errors", ""]
    errors = report.get("errors", [])
    lines += ["```json", json.dumps(errors, ensure_ascii=False, indent=2), "```"] if errors else ["None recorded."]
    if "trials" in report:
        lines += ["", "## Trials", ""]
        lines += [f"- [{item['nct_id']}]({item['nct_id']}.md): "
                  f"{item['counts']['reviewed_boundaries']} reviewed boundaries; "
                  f"{item['counts']['missing_prediction']} missing prediction; "
                  f"{len(item['errors'])} report entries." for item in report["trials"]]
    return "\n".join(lines) + "\n"


def evaluate_dataset(dataset, output, *, predictions=None, allow_test_fixture=False):
    dataset, output = local_path(dataset), local_path(output)
    manifest = read_json(dataset / "manifest.json")
    if manifest["dataset_version"] != DATASET_VERSION or manifest["annotation_version"] != ANNOTATION_VERSION:
        raise ValueError("Unsupported benchmark version")
    entries = manifest["trials"]
    identifiers = [entry["nct_id"] for entry in entries]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Duplicate benchmark trial")
    if not allow_test_fixture and set(identifiers) != set(TRIAL_IDS):
        raise ValueError("Expected five benchmark studies")
    index = read_json(local_path(predictions)) if predictions is not None else {"predictions": {}}
    if set(index) != {"predictions"} or not isinstance(index["predictions"], dict):
        raise ValueError("Invalid prediction index")
    if set(index["predictions"]) - set(identifiers):
        raise ValueError("Prediction trial outside benchmark")
    reports = []
    for entry in sorted(entries, key=lambda item: item["nct_id"]):
        identifier = entry["nct_id"]
        counts, errors, prediction, reference_hash = empty_counts(), [], None, None
        try:
            source, annotation, reference_hash = load_trial(dataset, entry, allow_test_fixture=allow_test_fixture)
        except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
            counts["reference_error"] = 1
            details = (error.errors(include_input=False, include_context=False, include_url=False)
                       if isinstance(error, ValidationError) else str(error))
            errors = [{"code": "invalid_or_missing_reference_or_source", "details": details}]
        else:
            path = index["predictions"].get(identifier)
            if path is not None:
                try:
                    prediction = load_prediction(path, source)
                except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
                    errors.append({"code": "invalid_or_missing_prediction_artifact", "details": str(error)})
            counts, scored_errors = score_trial(annotation, source, prediction)
            if path is not None and prediction is None:
                counts["prediction_error"] = 1
            errors.extend(scored_errors)
        reports.append({"nct_id": identifier, "snapshot_sha256": entry["snapshot_sha256"],
                        "source_snapshot": entry["source_snapshot"],
                        "source_url": f"https://clinicaltrials.gov/study/{identifier}",
                        "reference_sha256": reference_hash, "counts": counts, "metrics": metrics(counts),
                        "errors": errors, "prediction": {key: value for key, value in prediction.items()
                                                          if key not in ("nodes", "evidence", "errors")} if prediction else None})
    aggregate = {name: sum(report["counts"][name] for report in reports) for name in empty_counts()}
    report = {"dataset_version": DATASET_VERSION, "annotation_version": ANNOTATION_VERSION,
              "manifest_sha256": hashlib.sha256((dataset / "manifest.json").read_bytes()).hexdigest(),
              "software_test_only": allow_test_fixture, "assessment_allowed": False,
              "counts": aggregate, "metrics": metrics(aggregate), "trials": reports,
              "errors": [{"nct_id": item["nct_id"], **error} for item in reports for error in item["errors"]]}
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "report.json", report)
    for trial in reports:
        write_json(output / f"{trial['nct_id']}.json", trial)
        with (output / f"{trial['nct_id']}.md").open("x", encoding="utf-8", newline="\n") as file:
            file.write(report_markdown(trial, trial["nct_id"]))
    with (output / "report.md").open("x", encoding="utf-8", newline="\n") as file:
        file.write(report_markdown(report, "Eligibility extraction benchmark"))
    return report
