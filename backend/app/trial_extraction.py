import json
import re
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.app.extraction import extract_snapshot
from backend.app.extraction_prompt import CLINICAL_FIELDS
from backend.app.extraction_source import ROOT, EligibilitySource
from backend.app.extraction_recovery import recover_truncated_criteria

MOCK_VERSION = "verbatim-sections-v1"


def mock_envelope(source: EligibilitySource):
    headings = list(re.finditer(
        r"^[ \t]*(?:#+[ \t]*)?(Inclusion|Exclusion)(?:[ \t]+Criteria)?[ \t]*:?[ \t]*$",
        source.text, re.MULTILINE | re.IGNORECASE,
    ))
    criteria, evidence = [], []
    for index, heading in enumerate(headings):
        boundary = headings[index + 1].start() if index + 1 < len(headings) else len(source.text)
        body = source.text[heading.end():boundary]
        start = heading.end() + len(body) - len(body.lstrip("\n"))
        end = boundary - len(body) + len(body.rstrip("\n"))
        if start >= end:
            continue
        identifier = f"mock-section-{index + 1}"
        node = {field: None for field in CLINICAL_FIELDS}
        node.update(criterion_id=identifier, original_text=source.text[start:end],
                    criterion_type=heading.group(1).lower())
        criteria.append(node)
        evidence.append({"criterion_id": identifier, "original_span": {"start": start, "end": end},
                         "polarity_span": {"start": heading.start(), "end": heading.end()}, "fields": {}})
    return {"mock": True, "mock_version": MOCK_VERSION,
            "description": "Simulated verbatim section replay; not model inference or executable criterion extraction.",
            "content": json.dumps({"criteria": criteria, "evidence": evidence}, ensure_ascii=False)}


def run_mock(source: EligibilitySource):
    return run_extraction(source)


def run_extraction(source: EligibilitySource, *, live: bool = False, live_approved: bool = False, authorization_id: str | None = None):
    cache = ROOT / "cache"
    cache.mkdir(exist_ok=True)
    if live:
        output = extract_snapshot(
            Path(source.source_snapshot), source.nct_id, mock=False,
            live_approved=live_approved, expected_sha256=source.sha256,
            **({'authorization_id': authorization_id} if authorization_id else {}),
        )
    else:
        output = run_mock_snapshot(source, cache)
    return extraction_report(source, output)


def run_mock_snapshot(source, cache):
    with TemporaryDirectory(dir=cache) as directory:
        fixture = Path(directory) / "mock.json"
        fixture.write_text(json.dumps(mock_envelope(source), ensure_ascii=False), encoding="utf-8")
        output = extract_snapshot(Path(source.source_snapshot), source.nct_id, mock=True, mock_response=fixture)
    return output


def extraction_report(source, output, *, persist=True):
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    privacy_failed = manifest.get("status") == "privacy_failed"
    if not privacy_failed and (manifest.get("snapshot_sha256") != source.sha256
                               or manifest.get("source_snapshot") != source.source_snapshot):
        raise ValueError("Extraction source identity mismatch")
    errors = json.loads((output / "validation_errors.json").read_text(encoding="utf-8"))
    validated = json.loads((output / "validated.json").read_text(encoding="utf-8"))
    try:
        raw = json.loads((output / "raw_response.json").read_text(encoding="utf-8"))
    except ValueError:
        raw = None
    try:
        candidate = json.loads(raw["content"] if manifest["mode"] == "mock" else raw["choices"][0]["message"]["content"])
    except (TypeError, ValueError, KeyError, IndexError):
        candidate = None
    if privacy_failed:
        candidate = None
    partial_recovery = None
    finish_reason = None
    if not privacy_failed and manifest.get("mode") == "live" and isinstance(raw, dict):
        try:
            choice = raw["choices"][0]
            finish_reason = choice.get("finish_reason")
            partial_recovery = recover_truncated_criteria(choice["message"]["content"], source,
                finish_reason=finish_reason, timestamp=manifest["timestamp"])
        except (KeyError, IndexError, TypeError, RecursionError):
            pass
    candidates = candidate.get("criteria", []) if isinstance(candidate, dict) else []
    unsupported = [{"criterion_id": node.get("criterion_id"), "reason": "unreviewed_semantics_no_execution_mapping"}
                   for node in candidates if isinstance(node, dict)] if isinstance(candidates, list) else []
    if not candidates:
        reason = ("credential_echo_redacted" if privacy_failed else
                  "incomplete_provider_response" if finish_reason in ("length", "content_filter") else
                  "no_supported_section_headings" if manifest.get("mode") == "mock" else "no_parseable_structured_criteria")
        unsupported.append({"criterion_id": None, "reason": reason})
    source_payload = None if privacy_failed else asdict(source)
    report = {"manifest": manifest, "mock_version": MOCK_VERSION, "source": source_payload,
              "validated": validated, "validation_errors": errors, "candidate": candidate,
              "unsupported_criteria": unsupported, "assessment_allowed": False,
              "assessment_block_reason": "Real criteria require validated extraction, human-reviewed executable bindings and compatible synthetic evidence; this workflow does not accept assessment inputs.",
              "output_directory": output.relative_to(ROOT).as_posix()}
    if partial_recovery is not None:
        report["partial_recovery"] = partial_recovery
    for name, value in (("source.json", source_payload), ("integration.json", report)) if persist else ():
        with (output / name).open("x", encoding="utf-8") as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
    return report
