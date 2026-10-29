import hashlib
import csv
import json
import os
from pathlib import Path

from fastapi import APIRouter
from backend.app.nebius import configuration_check

ROOT = Path(__file__).resolve().parents[2]
router = APIRouter(prefix="/research", tags=["saved aggregate research"])
SUMMARIES = [
    ("METABRIC archival mapping", "Research evaluation data", "research/metabric_realdata_v1/results/mapping_summary.json",
     ["mapping_atoms", "distinct_mapped_trials", "criterion_assessments", "benchmark_complete_patients", "evaluation_complete_patients", "complete_current_trial_eligibility_labels"],
     "Archival rule proxies, not current trial eligibility. Complete-case selection and unsupported assay equivalences limit interpretation. Primary comparisons did not establish an incremental benefit over unconstrained or lookahead methods."),
    ("TCGA extraction evaluation", "Research evaluation data", "research/clinical_extraction_v1/results/evaluation_summary.json",
     ["documents", "patients", "total_reference_facts", "original_predictions", "improved_predictions", "source_aligned_predictions", "clinical_accuracy", "document_F1"],
     "Historically exposed assistant annotations, not independent clinical labels. Oracle-passage scores use known reference locations and favorable transcription; they are not end-to-end performance. No exhaustive document annotation; clinical accuracy and document F1 are unmeasured."),
    ("Expanded extraction audit", "Research evaluation data", "research/clinical_extraction_v2/results/summary.json",
     ["documents", "patients", "categorical_reference_facts", "expanded_total_factual_inventory", "source_alignment_checked", "independent_clinician_labels", "clinical_accuracy", "whole_document_F1"],
     "Expanded inventory on an overlapping cohort, not a new sequential validation cohort. Rule scores are not probabilities."),
    ("Registry inference benchmark", "Saved extraction benchmark", "results/benchmark/tnbc-eligibility-v1/report.json",
     ["assessment_allowed"],
     "Missing predictions and unreviewed references prevent a clinical performance claim. Zero evaluated denominators are not zero error rates."),
]
REPORTS = [
    ("Synthetic planning experiments", "results/prioritization/sensitivity/20261025-final/report.md"),
    ("Risk and reliability evaluation", "results/prioritization/coherent/20261025-imperfect-analysis-v1/report.md"),
]
TABLES = {
    "METABRIC archival mapping": "research/metabric_realdata_v1/reports/scientific_findings.md",
    "TCGA extraction evaluation": "research/clinical_extraction_v1/reports/scientific_findings.md",
    "Expanded extraction audit": "research/clinical_extraction_v2/reports/scientific_findings.md",
}


def research_overview():
    overview = {"sources": []}

    def read(source, format="json"):
        raw = (ROOT / source).read_bytes()
        value = json.loads(raw) if format == "json" else list(csv.DictReader(raw.decode("utf-8").splitlines()))
        overview["sources"].append({"path": source, "sha256": hashlib.sha256(raw).hexdigest()})
        return value

    try:
        audit = read("research/metabric_realdata_v1/results/data_audit.json")
        mapping = read("research/metabric_realdata_v1/results/mapping_summary.json")
        rows = read("research/metabric_realdata_v1/results/main_table.csv", "csv")
        overview["metabric"] = {"patients": audit["patients"], "evaluation_patients": mapping["evaluation_complete_patients"],
            "comparison": [{"method": row["method"], "error": float(row["proxy_error"]), "coverage": float(row["proxy_coverage"])} for row in rows if row["method"] in ("triallens_nominal", "unconstrained", "lookahead1", "random", "uncertainty")]}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        rows = read("results/recomb/20261026-certified-review-v1/decision_metrics.csv", "csv")
        final = [row for row in rows if row["split"] == "final" and row["method"] == "bernstein_repair"]
        if final:
            outside = [row for row in rows if row["split"] == "ood" and row["method"] == "bernstein_repair"]
            overview["synthetic"] = {"instances": len({row["case"] for row in final}), "conditions": len({(row["case"], row["budget"]) for row in final}),
                "budgets": sorted({int(row["budget"]) for row in final}), "violations": sum(float(row["actual_violation"]) > 0 for row in final),
                "ood_conditions": len(outside), "ood_violations": sum(float(row["actual_violation"]) > 0 for row in outside)}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        rows = read("results/recomb/20261026-certified-review-v1/scaling_summary.json")
        cached = [row for row in rows if row["split"] == "final" and row["backend"] == "reusable" and row["capacity"] == 512 and row["median_seconds"]]
        timing = []
        for row in cached:
            old = next((item for item in rows if item["split"] == "final" and item["backend"] == "old" and item["n"] == row["n"] and item["m"] == row["m"]), None)
            if old and old["median_seconds"]:
                timing.append({"criteria": row["n"], "reports": row["m"], "old_seconds": old["median_seconds"], "reusable_seconds": row["median_seconds"], "speedup": old["median_seconds"] / row["median_seconds"]})
        overview["caching"] = timing
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return overview


@router.get("/results")
def results():
    sections = []
    for title, kind, source, fields, limitation in SUMMARIES:
        section = {"title": title, "kind": kind, "source": source, "limitation": limitation, "metrics": {}}
        try:
            raw = (ROOT / source).read_bytes()
            value = json.loads(raw)
            section["metrics"] = {key: value[key] for key in fields if key in value and (value[key] is None or isinstance(value[key], (int, float, bool)))}
            if title == "Registry inference benchmark":
                counts = value.get("counts", {})
                section["metrics"].update({key: counts[key] for key in ("trials", "missing_prediction", "reviewed_slots", "unreviewed_slots") if isinstance(counts.get(key), int)})
            section["sha256"] = hashlib.sha256(raw).hexdigest()
            section["status"] = "available"
        except (OSError, ValueError, TypeError):
            section["status"] = "unavailable"
        if title in TABLES:
            try:
                raw = (ROOT / TABLES[title]).read_bytes()
                lines = raw.decode("utf-8").splitlines()
                start = next(index for index, line in enumerate(lines) if line.startswith("|"))
                table = []
                for line in lines[start:]:
                    if not line.startswith("|"):
                        break
                    table.append([cell.strip() for cell in line.strip("|").split("|")])
                section.update(table=[table[0], *table[2:]], table_source=TABLES[title], table_sha256=hashlib.sha256(raw).hexdigest())
            except (OSError, UnicodeError, StopIteration):
                pass
        sections.append(section)
    for title, source in REPORTS:
        section = {"title": title, "kind": "Synthetic planning evaluation", "source": source, "metrics": {}, "limitation": "Authored synthetic worlds and assumed observation laws; not measured clinical performance."}
        try:
            raw = (ROOT / source).read_bytes()
            section.update(text=raw.decode("utf-8"), sha256=hashlib.sha256(raw).hexdigest(), status="available")
        except (OSError, UnicodeError):
            section["status"] = "unavailable"
        sections.append(section)
    configuration = configuration_check()
    configuration["missing_variables"] = [key for key in ("NEBIUS_API_KEY", "NEBIUS_MODEL") if not os.environ.get(key, "").strip()]
    return {"sections": sections, "overview": research_overview(), "inference": configuration, "privacy": "Aggregate research findings only. Individual patient records and restricted clinical reports are not published here."}
