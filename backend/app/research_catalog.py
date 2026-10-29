import csv
import hashlib
import io

from fastapi import APIRouter, HTTPException, Query

from backend.app.extraction_source import ROOT

router = APIRouter(prefix="/research/evaluation", tags=["allowlisted aggregate experiments"])
PAPER = "results/recomb/20261026-compiled-review-v2/"
PACKAGE = "research/manuscript_evidence_package_v1/"
ARTIFACTS = {
    "paper-methods": ("Authoritative manuscript: methods, assumptions and limits", PAPER + "research_report.md", "Original manuscript", "Restricted authored source law; computational specialization, not clinical validation."),
    "paper-means": ("Original paper: all policies and splits", PAPER + "decision_means.csv", "Original manuscript", "48 held-out instances × two budgets = 96 conditions; correlated seed bundles, not patient samples."),
    "paper-conditions": ("Original paper: individual synthetic evaluation conditions", PAPER + "decision.csv", "Original manuscript", "Synthetic conditions, budget comparisons, ablations and OOD results. No patient records."),
    "paper-benchmarks": ("Exact inference, runtime and memory", PAPER + "benchmark_summary.csv", "Original manuscript", "Local hardware; unsupported and timed-out references are not assigned speedups."),
    "paper-fidelity": ("Matched numerical fidelity", PAPER + "numerical_fidelity.csv", "Original manuscript", "Exactness under the specified law, not clinical accuracy."),
    "paper-effects": ("Paired effects and uncertainty", PAPER + "paired_effects.csv", "Original manuscript", "Synthetic-seed intervals; utility gains are not error or cost dominance."),
    "paper-ordering": ("BDD ordering counterexample", PAPER + "ordering_counterexample.csv", "Original manuscript", "Variable order can cause exponential growth; occurrence order is not universally optimal."),
    "continuous": ("Continuous certification and OOD comparisons", "results/recomb/20261026-certified-review-v1/comparison.csv", "Later extension", "24 independent primary cases, 48 budget conditions; certification depends on prior, dependence and reliability assumptions."),
    "continuous-conditions": ("Continuous certification: conditions and baselines", "results/recomb/20261026-certified-review-v1/decision_metrics.csv", "Later extension", "Finite-model constraints and continuous certificates are different guarantees."),
    "metabric": ("METABRIC primary proxy comparison", "research/metabric_realdata_v1/results/main_table.csv", "Archival evaluation", "1021 complete-case evaluation patients; rule proxies, not independently adjudicated eligibility. Primary constrained and unconstrained methods tie."),
    "matched": ("METABRIC matched coverage: primary operating points", "research/matched_coverage_v1/results/primary_table.csv", "Later extension", "Primary comparisons fail the requested matched-coverage gate; do not claim clinical superiority."),
    "matched-statistics": ("METABRIC paired statistics", "research/matched_coverage_v1/results/primary_statistics.csv", "Later extension", "Intervals condition on fitted models and assumed observation channels."),
    "shared-rule": ("Adaptive versus fixed: shared terminal rule", "research/matched_coverage_v1/results/adaptive_nonadaptive_shared_rule.csv", "Later extension", "Identical proxy error and coverage in the shared-rule comparison; atomic utility and stopping can differ."),
    "selection": ("Outcome-blind selection diagnostic", "research/clinical_validation_v1/results/primary_operating_points.csv", "Later extension", "Common decoder diagnostic gives adverse selection evidence; it does not inherit the native risk cap."),
    "tcga-expanded": ("TCGA expanded extraction methods", "research/clinical_extraction_v2/results/method_metrics.csv", "Source extraction evaluation", "Overlapping, partly exposed cases; source support is not clinical adjudication."),
    "tcga-holdout": ("TCGA internal holdout extraction", "research/clinical_extraction_generalization_v1/results/method_metrics.csv", "Later extension", "100 processed / 24 reviewed / eight patients with 20 primary facts. No whole-document or clinical eligibility accuracy."),
    "tcga-intervals": ("TCGA extraction intervals", "research/clinical_extraction_generalization_v1/results/confidence_intervals.csv", "Later extension", "Small patient clusters and degenerate recovery intervals do not establish certainty."),
    "ablation": ("METABRIC selector and decoder decomposition", "research/matched_coverage_v1/results/ablation_decomposition.csv", "Later extension", "Decoder abstention and report selection have distinct effects."),
    "claims": ("Claims and evidence: supported, qualified and unsupported", PACKAGE + "11_CLAIMS_EVIDENCE_MATRIX.csv", "Later evidence consolidation", "A claim audit, not additional experiments or a newer complete manuscript."),
    "registry": ("Complete verified aggregate results registry", PACKAGE + "03_MASTER_RESULTS_REGISTRY.csv", "Later evidence consolidation", "8183 source metric cells across distinct studies; cells are not independent experiments. Includes TrialGPT retrieval, synthetic studies and later extensions."),
}


@router.get("")
def catalog():
    return {"manuscript": PAPER + "manuscript.html", "title": "Compiled Product-Mixture Beliefs for Error-Constrained Adaptive Evidence Review",
            "artifacts": [{"id": key, "title": value[0], "source": value[1], "study": value[2], "limitation": value[3],
                           "available": (ROOT / value[1]).is_file()} for key, value in ARTIFACTS.items()],
            "implementation": [{"method": name, "code": code, "capability": capability} for name, code, capability in (
                ("Five-state Boolean evidence", "backend/app/assessment.py", "Fictional case tools; real sources remain unresolved without approved inputs"),
                ("Exact product mixtures and BDD weighted counting", "research/compiled_review_v1/belief.py", "Evidence Review: computed protocol probabilities"),
                ("Reusable bounded factor caches", "research/certified_review_v1/belief.py", "Evidence Review: live computation and cache diagnostics"),
                ("Hard budgets, adaptive pricing and policy mixtures", "research/constrained_review_v1/factorized.py", "Evidence Review: executable constrained recommendations and abstention"),
                ("Continuous interval risk enclosure", "research/certified_review_v1/certificate.py", "Saved continuous-certification evaluation, separate from the finite-model interactive planner"),
                ("Source-grounded Nemotron extraction", "backend/app/extraction.py", "Trial analysis reuses saved checks; protected operator extraction requires explicit authorization"))]}


@router.get("/{identifier}")
def artifact(identifier: str, offset: int = Query(default=0, ge=0, le=100000), limit: int = Query(default=30, ge=1, le=100),
             query: str = Query(default="", max_length=200)):
    if identifier not in ARTIFACTS:
        raise HTTPException(404, "Unknown aggregate artifact")
    title, source, study, limitation = ARTIFACTS[identifier]
    try:
        raw = (ROOT / source).read_bytes()
        content = raw.decode("utf-8-sig")
    except (OSError, UnicodeError):
        raise HTTPException(404, "Saved artifact is unavailable; no result substituted") from None
    result = {"title": title, "source": source, "study": study, "limitation": limitation, "sha256": hashlib.sha256(raw).hexdigest()}
    if source.endswith(".csv"):
        reader = csv.DictReader(io.StringIO(content))
        rows = [row for row in reader if not query or query.casefold() in " ".join(str(value) for value in row.values()).casefold()]
        result.update(columns=reader.fieldnames or [], rows=rows[offset:offset + limit], total=len(rows), offset=offset)
    else:
        result["text"] = content
    return result
