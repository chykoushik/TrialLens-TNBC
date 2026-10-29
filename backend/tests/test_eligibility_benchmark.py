import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import pytest
from pydantic import ValidationError

from backend import benchmark_eligibility
from backend.app import eligibility_benchmark as benchmark
from backend.app.benchmark_models import ReferenceAnnotation, validate_reference
from backend.app.extraction_source import ROOT, load_source

FIXTURE = Path(__file__).parent / "fixtures/eligibility_benchmark_case.json"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Unexpected network access")

    monkeypatch.setattr(httpx, "Client", fail)


@pytest.fixture
def workspace():
    with TemporaryDirectory(dir=ROOT / "cache") as temporary:
        yield Path(temporary)


@pytest.fixture
def software_case(workspace):
    fixture = benchmark.read_json(FIXTURE)
    with TemporaryDirectory(dir=ROOT / "data/synthetic") as temporary:
        snapshot = Path(temporary) / "response.json"
        benchmark.write_json(snapshot, {"is_synthetic": True, "description": fixture["purpose"], "studies": [
            {"protocolSection": {"identificationModule": {"nctId": "NCT00000001"},
                                 "eligibilityModule": {"eligibilityCriteria": fixture["text"]}}}]})
        source = load_source(snapshot, "NCT00000001")
        reference = ReferenceAnnotation.model_validate({
            "nct_id": source.nct_id, "snapshot_sha256": source.sha256,
            "annotation_origin": "software_test_fixture", "inventory_review": fixture["inventory_review"],
            "criteria": fixture["gold_criteria"],
        })
        dataset = workspace / "dataset"
        directory = dataset / source.nct_id
        directory.mkdir(parents=True)
        benchmark.write_json(directory / "source.json", benchmark.asdict(source))
        with (directory / "source.txt").open("w", encoding="utf-8", newline="") as file:
            file.write(source.text)
        benchmark.write_json(directory / "reference.json", reference.model_dump(mode="json"))
        entry = {"nct_id": source.nct_id, "snapshot_sha256": source.sha256,
                 "source_snapshot": source.source_snapshot, "text_sha256": benchmark.digest(source.text)}
        benchmark.write_json(dataset / "manifest.json", {"dataset_version": benchmark.DATASET_VERSION,
                             "annotation_version": benchmark.ANNOTATION_VERSION, "trials": [entry]})
        artifact = workspace / "prediction"
        artifact.mkdir()
        benchmark.write_json(artifact / "manifest.json", {"nct_id": source.nct_id, "snapshot_sha256": source.sha256,
                             "source_snapshot": source.source_snapshot, "mode": "software_test_fixture",
                             "requested_model": "independently-authored-test-fixture", "prompt_version": "not-inference"})
        benchmark.write_json(artifact / "raw_response.json", {"content": json.dumps(fixture["prediction"])})
        index = workspace / "index.json"
        benchmark.write_json(index, {"predictions": {source.nct_id: artifact.relative_to(ROOT).as_posix()}})
        yield fixture, source, reference, dataset, artifact, index


def test_five_genuine_studies_deduplicated_and_reproducible(workspace):
    raw_files = list((ROOT / "data/raw/trials").glob("*/*.json"))
    before = {path: path.read_bytes() for path in raw_files}
    first = benchmark.build_dataset(workspace / "first")
    second = benchmark.build_dataset(workspace / "second")
    assert {p.relative_to(first): p.read_bytes() for p in first.rglob("*") if p.is_file()} == {
        p.relative_to(second): p.read_bytes() for p in second.rglob("*") if p.is_file()}
    manifest = benchmark.read_json(first / "manifest.json")
    assert [entry["nct_id"] for entry in manifest["trials"]] == list(benchmark.TRIAL_IDS)
    for entry in manifest["trials"]:
        available = [path for path in raw_files if path.name == 'response.json' and any(
            study.get('protocolSection', {}).get('identificationModule', {}).get('nctId') == entry['nct_id']
            for study in benchmark.read_json(path).get('studies', []))]
        assert len(entry["historical_snapshots"]) == len(available) > 0
        source, annotation, _ = benchmark.load_trial(first, entry)
        assert source.is_synthetic is not True
        assert annotation.criteria == []
        assert annotation.inventory_review.status == "unreviewed"
        worksheet = benchmark.read_json(first / entry["nct_id"] / "worksheet.json")
        assert all(source.text[line["span"]["start"]:line["span"]["end"]] == line["text"]
                   and line["review_status"] == "unreviewed" for line in worksheet["lines"])
    report = benchmark.evaluate_dataset(first, workspace / "report")
    assert report["counts"]["missing_prediction"] == 5
    assert report["counts"]["unreviewed_inventory"] == 5
    assert report["counts"]["reference_error"] == 0
    assert all(value["value"] is None for key, value in report["metrics"].items() if key != "slots")
    assert all(value["value"] is None for value in report["metrics"]["slots"].values())
    assert all(path.read_bytes() == raw for path, raw in before.items())
    with pytest.raises(FileExistsError):
        benchmark.build_dataset(first)


def test_independently_authored_metric_expectations(software_case, workspace):
    fixture, _, _, dataset, _, index = software_case
    report = benchmark.evaluate_dataset(dataset, workspace / "report", predictions=index, allow_test_fixture=True)
    for name, value in fixture["expected"].items():
        assert report["counts"][name] == value, name
    metrics = report["metrics"]
    assert metrics["criterion_detection_precision"]["value"] == pytest.approx(0.75)
    assert metrics["criterion_detection_recall"]["value"] == 1
    assert metrics["criterion_detection_f1"]["value"] == pytest.approx(6 / 7)
    assert metrics["polarity_accuracy"]["value"] == pytest.approx(2 / 3)
    assert metrics["source_span_validity"]["value"] == pytest.approx(5 / 8)
    assert metrics["slots"]["biomarker"]["value"] is None
    assert report["software_test_only"] is True
    assert report["assessment_allowed"] is False
    codes = {entry["code"] for entry in report["errors"]}
    assert {"unsupported_field", "unsupported_polarity", "unsupported_logical_structure",
            "unsupported_conditional_or_exception", "slot_mismatch", "unmatched_prediction"} <= codes
    again = benchmark.evaluate_dataset(dataset, workspace / "again", predictions=index, allow_test_fixture=True)
    assert report == again
    assert (workspace / "report/report.md").read_bytes() == (workspace / "again/report.md").read_bytes()


def test_software_fixtures_never_become_clinical_gold(software_case, workspace):
    _, source, reference, _, _, _ = software_case
    with pytest.raises(ValueError, match="Software fixtures"):
        validate_reference(reference, source.text)
    data = reference.model_dump(mode="json")
    data["annotation_origin"] = "mock"
    with pytest.raises(ValidationError):
        ReferenceAnnotation.model_validate(data)


def test_partial_review_cannot_produce_detection_metrics(software_case):
    _, source, reference, _, artifact, _ = software_case
    reference.inventory_review.status = "unreviewed"
    prediction = benchmark.load_prediction(artifact, source)
    counts, _ = benchmark.score_trial(reference, source, prediction)
    metrics = benchmark.metrics(counts)
    assert metrics["criterion_detection_f1"]["value"] is None
    assert metrics["validation_pass_rate"]["value"] is None
    assert metrics["polarity_accuracy"]["value"] == pytest.approx(2 / 3)


def test_missing_predictions_are_not_perfect_scores(software_case):
    _, source, reference, _, _, _ = software_case
    counts, _ = benchmark.score_trial(reference, source, None)
    assert counts["missing_prediction"] == 1
    assert counts["polarity_missing_prediction"] == 3
    assert benchmark.metrics(counts)["polarity_accuracy"]["value"] is None
    assert benchmark.metrics(counts)["criterion_detection_recall"]["value"] is None


def test_positive_validation_rate_uses_existing_strict_validator(software_case):
    from dataclasses import replace

    fixture, source, reference, _, _, _ = software_case
    payload = copy.deepcopy(fixture["prediction"])
    payload["criteria"] = payload["criteria"][:2]
    payload["criteria"][0]["threshold"] = "9"
    payload["criteria"][1]["logical_operator"] = "AND"
    payload["evidence"] = [entry for entry in payload["evidence"] if entry["criterion_id"] not in ("infection", "extra")]
    source = replace(source, text=source.text[:source.text.index("* Active infection")])
    reference.criteria = reference.criteria[:2]
    result, errors = benchmark.validate_extraction(json.dumps(payload), source, method="software-test", timestamp=benchmark.TIMESTAMP)
    assert result is not None and errors == []
    prediction = {"nodes": payload["criteria"], "evidence": {e["criterion_id"]: e for e in payload["evidence"]},
                  "errors": errors, "validation_passed": result is not None}
    counts, _ = benchmark.score_trial(reference, source, prediction)
    assert benchmark.metrics(counts)["validation_pass_rate"]["value"] == 1
    assert benchmark.metrics(counts)["source_span_validity"]["value"] == 1


def test_nested_reference_slots_match_only_inside_parent(software_case):
    _, source, reference, _, artifact, _ = software_case
    first = reference.criteria[0]
    text = "marker X positive"
    start = source.text.index(text)
    child = copy.deepcopy(first.model_dump(mode="json"))
    child.update(reference_id="reference-child", original={"text": text, "span": {"start": start, "end": start + len(text)}})
    for slot in benchmark.SLOTS:
        child.pop(slot, None)
    child["polarity"] = first.polarity.model_dump(mode="json")
    data = reference.model_dump(mode="json")
    data["criteria"][1]["dependencies"] = [child]
    updated = ReferenceAnnotation.model_validate(data)
    validate_reference(updated, source.text, allow_test_fixture=True)
    prediction = benchmark.load_prediction(artifact, source)
    counts, _ = benchmark.score_trial(updated, source, prediction)
    assert counts["tp"] == 3
    assert counts["polarity_evaluated"] == 4
    assert counts["polarity_correct"] == 3


@pytest.mark.parametrize("mutation", ["malformed", "duplicate_keys", "empty_predictions"])
def test_bad_output_is_revalidated_offline(software_case, mutation):
    _, source, reference, _, artifact, _ = software_case
    path = artifact / "raw_response.json"
    content = {"malformed": "{broken", "duplicate_keys": '{"criteria":[],"criteria":[],"evidence":[]}',
               "empty_predictions": '{"criteria":[],"evidence":[]}'}[mutation]
    path.write_text(json.dumps({"content": content}), encoding="utf-8")
    prediction = benchmark.load_prediction(artifact, source)
    assert prediction["validation_passed"] is False
    counts, _ = benchmark.score_trial(reference, source, prediction)
    assert counts["fn"] == 3
    assert benchmark.metrics(counts)["criterion_detection_recall"]["value"] == 0


@pytest.mark.parametrize("mutation", ["source", "reference", "prediction"])
def test_provenance_tampering_is_not_scored(software_case, workspace, mutation):
    _, source, _, dataset, artifact, index = software_case
    if mutation == "source":
        (dataset / source.nct_id / "source.txt").write_text("Changed source", encoding="utf-8")
    else:
        path = dataset / source.nct_id / "reference.json" if mutation == "reference" else artifact / "manifest.json"
        payload = benchmark.read_json(path)
        payload["snapshot_sha256"] = "0" * 64
        path.write_text(json.dumps(payload), encoding="utf-8")
    report = benchmark.evaluate_dataset(dataset, workspace / "report", predictions=index, allow_test_fixture=True)
    assert report["counts"]["reference_error" if mutation != "prediction" else "prediction_error"] == 1
    assert report["metrics"]["polarity_accuracy"]["value"] is None


@pytest.mark.parametrize("mutation", ["invented_text", "invented_slot", "unreviewed_boundary", "missing_reviewer", "overlap"])
def test_invalid_reference_labels_are_rejected(software_case, mutation):
    _, source, reference, _, _, _ = software_case
    data = copy.deepcopy(reference.model_dump(mode="json"))
    if mutation == "invented_text":
        data["criteria"][0]["original"]["text"] = "Invented fact"
    elif mutation == "invented_slot":
        data["criteria"][0]["threshold_value"]["value"] = "99"
    elif mutation == "unreviewed_boundary":
        data["criteria"][0]["boundary_review"]["status"] = "unreviewed"
    elif mutation == "missing_reviewer":
        data["criteria"][0]["polarity"]["review"]["reviewer"] = None
    else:
        data["criteria"].append({**data["criteria"][0], "reference_id": "duplicate-span"})
    with pytest.raises(ValueError):
        value = ReferenceAnnotation.model_validate(data)
        validate_reference(value, source.text, allow_test_fixture=True)


def test_paths_and_cli_do_not_overwrite_or_enable_live(workspace):
    with pytest.raises(ValueError):
        benchmark.local_path(Path("../outside"))
    with pytest.raises(SystemExit):
        benchmark_eligibility.main(["evaluate", "--live"])
    assert benchmark_eligibility.main(["evaluate", "--dataset", str(workspace / "missing")]) == 1


def test_malformed_dependency_does_not_crash_reporting(software_case, workspace):
    fixture, _, _, dataset, artifact, index = software_case
    payload = copy.deepcopy(fixture["prediction"])
    payload["criteria"][1]["dependencies"] = ["invalid child"]
    (artifact / "raw_response.json").write_text(json.dumps({"content": json.dumps(payload)}), encoding="utf-8")
    report = benchmark.evaluate_dataset(dataset, workspace / "report", predictions=index, allow_test_fixture=True)
    assert report["counts"]["fn"] == 3
    assert report["counts"]["validation_passed"] == 0
