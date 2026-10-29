# TrialLens-TNBC

TrialLens-TNBC investigates **risk-constrained adaptive evidence review for clinical trial eligibility**, motivated by triple-negative breast cancer (TNBC). Given logical eligibility requirements, uncertain reports and a limited review budget, it asks which existing evidence to review next and when to abstain.

The released research application combines real ClinicalTrials.gov browsing, source-linked trial analysis, an executable synthetic planning demonstration and aggregate research results. It is a computational research prototype, not a clinically validated patient screening system.

## Research contribution and methodology

The manuscript, *Compiled Product-Mixture Beliefs for Error-Constrained Adaptive Evidence Review*, studies an exact computational specialization of constrained partially observable planning. Its contribution is a model-specific implementation and analysis, building on established inference and planning methods; it does not establish a new general inference algorithm.

- **Eligibility logic:** AND, OR and NOT predicates preserve repeated and shared Boolean criteria. The application separately exposes satisfied, violated, unknown, temporal and conflict evidence states.
- **Probabilistic inference:** finite mixtures of product beliefs represent uncertain criterion truth and correlated reports under a specified source-group model. Compiled reduced ordered binary decision diagrams (BDDs) support weighted probability evaluation without enumerating every truth assignment for that model.
- **Inference caching:** reusable posterior summaries and BDD evaluations avoid repeated work. Diagram size, source mixtures and adaptive histories can still grow exponentially.
- **Adaptive prioritization:** constrained policy-column generation selects reports and stopping decisions to optimize utility, subject to hard review budgets and modelwise expected-error caps. Information gain is displayed as a diagnostic, not the planner's objective.
- **Reliability and abstention:** policies can withhold assertions. The interactive planner uses three fixed reliability models and reports a numerical optimization gap. Separate research code evaluates continuous-interval risk certification and abstention repair; that certificate is not provided by the interactive demonstration.

The risk constraint concerns the expected fraction of incorrect protocol assertions across all protocol opportunities under the supplied models. It is neither an individual-patient safety guarantee nor an error rate conditional on answering.

See the published [methods and findings](results/recomb/20261026-compiled-review-v2/research_report.md), [compiled inference implementation](research/compiled_review_v1), [constrained planner](research/constrained_review_v1) and [certification implementation](research/certified_review_v1). The public methods excerpt accompanies the local manuscript; the full manuscript is not bundled in this release. Scientific attribution includes Bryant's BDDs, Chavira and Darwiche's weighted model counting, and Walraven and Spaan's constrained POMDP column generation, discussed in the methods report.

## Application

1. **Search and select trials:** query ClinicalTrials.gov by condition, intervention, keywords or NCT identifier, or select a bundled registry snapshot.
2. **Analyze trial:** inspect source-linked criteria, unresolved passages and any matching saved extraction evidence. This action makes no paid model request and produces no patient eligibility determination.
3. **Evidence Review:** execute the actual compiled inference and constrained planner on frozen synthetic paper scenarios; choose a budget and apply hypothetical report outcomes. Four additional fictional TNBC cases illustrate missing, stale and conflicting evidence.
4. **Research Results:** inspect allowlisted aggregate tables, comparisons, source paths and checksums for synthetic studies, METABRIC, TCGA, caching and certification.

The frontend uses React, TypeScript and Vite; the backend uses FastAPI and Python. The public entry point is `backend.research_public:app`. The broader `backend.app.main:app` supplies controlled local research tools and is not the public server.

## NVIDIA Nemotron through Nebius

The controlled extraction integration targets NVIDIA `nvidia/nemotron-3-super-120b-a12b` through Nebius Token Factory's OpenAI-compatible endpoint, `https://api.tokenfactory.nebius.com/v1`.

Its section-based pipeline preserves inclusion/exclusion boundaries, checks source coverage, remaps quotation offsets to the original registry text and validates the merged structured proposal. Ambiguous or oversized sections, unsupported fields and incomplete responses remain unresolved or fail validation. Source alignment and schema validation do not establish clinical correctness or an approved executable eligibility mapping; qualified human review remains necessary.

Historical Nemotron attempts include failures and a structured response rejected by whole-output validation. These are not a clinical accuracy benchmark. Section-processing tests use mocked responses; they do not demonstrate successful live extraction for every trial. Raw provider responses and credentials are excluded from the public repository.

**Public BYOK is disabled.** The public server blocks visitor extraction and exposes no operator inference or annotation routes. Registry analysis and the research demonstration require no provider key and perform no live model inference. The integration is relevant to the Nebius × NVIDIA hackathon; this repository alone does not establish compliance with the [official submission rules](https://nebiusglobalaihackathon.devpost.com/rules).

## Evaluation

The manuscript's synthetic experiments and the accompanying archival extensions answer different questions and should not be pooled as clinical validation.

| Study | Supported finding and boundary |
|---|---|
| Compiled inference | Across 252 isolated runs: 159 successful, 84 unsupported under declared limits and nine timed out. All 96 successful matched-reference comparisons agreed within `5.22e-15`. The benchmark reached 64-criterion posterior queries and 24-criterion constrained planning; these are distinct workloads. Small cases favored the earlier analytical backend. |
| Adaptive review | On 48 synthetic cases at two budgets (96 conditions), exact constrained planning improved mean utility by `0.005065` over an optimized same-risk baseline mixture, with a paired synthetic-seed 95% interval `[0.003057, 0.007053]`. Cost and error counts also increased slightly; there was no consistent utility advantage over depth-two pricing. |
| Reliability | No primary exact-policy cap violations occurred when the actual law was included by construction. Outside the assumed set, violations occurred in 46/48 conditions; the repaired robust comparator also failed in 34/48. These results do not establish clinical calibration or safety. |
| Certification and caching extension | Separate continuous-interval certification and abstention-repair experiments are retained. Reusable caching achieved about 1.35–1.67× local median speedups on repeated-query workloads, with three repetitions per final size; this is not an end-to-end planning speedup. |
| METABRIC | An archive of 2,509 patients supported limited archival mappings; the complete-case evaluation used 1,021 patients and two proxy predicates. At the primary budget, nominal constrained, unconstrained and one-/two-step lookahead planners had identical proxy metrics. Matched-coverage analyses do not establish a general superiority claim. Archival rules and simulated observation errors are not current trial eligibility labels. |
| TCGA | Extraction audits compare rule variants, source alignment, recovery, precision and withholding. The generalization audit processed 100 reports, with a limited reviewed subset and historically exposed assistant annotations. Neither independent clinical gold nor exhaustive document-level accuracy is established. |

Baselines include random/cheapest/uncertainty review, information gain, VOI per cost, an EC2 adaptation, one-/two-step lookahead, exact adaptive and fixed selection, replanning, robust planning and an optimized feasible baseline mixture. Their scopes and objectives differ.

Public evidence includes [benchmark summaries](results/recomb/20261026-compiled-review-v2/benchmark_summary.csv), [policy comparisons](results/recomb/20261026-compiled-review-v2/decision_means.csv), [certification results](results/recomb/20261026-certified-review-v1/comparison.csv), [METABRIC findings](research/metabric_realdata_v1/reports/scientific_findings.md), [matched-coverage comparisons](research/matched_coverage_v1/results/primary_table.csv) and [TCGA audit metrics](research/clinical_extraction_generalization_v1/results/method_metrics.csv). Scientific code and tests are retained; restricted patient records, private annotations and complete local experiment workspaces are not distributed, so a public checkout alone cannot reproduce every archival experiment.

## Local setup

Requires Python 3.12, Node.js 22.12 or later compatible with Vite 7, npm and a browser. No local GPU or model weights are required for the public research application. Commands below use Windows PowerShell from the repository root.

```powershell
git clone https://github.com/chykoushik/TrialLens-TNBC.git
Set-Location TrialLens-TNBC
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-demo.lock.txt
npm.cmd --prefix frontend ci

$env:VITE_PUBLIC_DEMO = '0'
$env:VITE_PUBLIC_RESEARCH = '1'
$env:VITE_API_BASE_URL = '/api'
npm.cmd --prefix frontend run build
New-Item -ItemType Directory -Force frontend/dist/assets/licenses | Out-Null
Copy-Item third_party/licenses/*.txt frontend/dist/assets/licenses/

$env:TRIALLENS_BYOK_ENABLED = '0'
$env:TRIALLENS_PUBLIC_RESEARCH = '1'
$env:PORT = '8080'
.\.venv\Scripts\python.exe -B -m backend.serve_public
```

Open `http://127.0.0.1:8080`. The launcher serves the built frontend and API together; `/api/health` and `/api/readiness` report service and bundled-artifact readiness.

For frontend development, start the public backend in one terminal:

```powershell
.\.venv\Scripts\python.exe -B -m uvicorn backend.research_public:app --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
```

In a second terminal, set the frontend variables and run:

```powershell
$env:VITE_PUBLIC_DEMO = '0'
$env:VITE_PUBLIC_RESEARCH = '1'
$env:VITE_API_BASE_URL = '/api'
$env:TRIALLENS_API_TARGET = 'http://127.0.0.1:8000'
npm.cmd --prefix frontend run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` to the backend.

[`.env.example`](.env.example) lists configuration names; neither server nor Vite automatically loads it. Set process variables explicitly. `VITE_*` values are public build-time settings and require a rebuild when changed. Never place credentials in them.

No `NEBIUS_API_KEY` is needed for this setup. Optional controlled local inference uses that secret, `NEBIUS_MODEL`, `NEBIUS_BASE_URL` and explicit live-extraction/budget authorization; it is separate from the public workflow. Leave `NEBIUS_LIVE_EXTRACTION=0` and public BYOK disabled for the demonstration. Do not commit credential files.

### Tests

After building the public frontend:

```powershell
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q --basetemp=cache/pytest-public -o cache_dir=cache/pytest-public-cache
$env:VITE_PUBLIC_DEMO = '0'
$env:VITE_PUBLIC_RESEARCH = '0'
npm.cmd --prefix frontend test
```

Frontend unit tests exercise controlled and public components with mocked responses. Backend tests needing excluded private fixtures are explicitly skipped. Scientific tests accompany the modules under `research/`; browser journeys are in `frontend/e2e/`. Provider unit tests use mocked transports, not paid inference. Restore `VITE_PUBLIC_RESEARCH=1` before rebuilding the public interface.

## Deployment status

Existing public application: **https://triallens-tnbc.onrender.com/**.

On **29 October 2026**, the service health endpoint responded successfully, but `/api/research/planner/scenarios` returned 404 and the health response matched the earlier application. The current research release is therefore **not verified as deployed** at that URL.

[`Dockerfile`](Dockerfile) and [`render.yaml`](render.yaml) configure the public research server, port 8080, a non-root runtime and `/api/readiness` health checks. Automatic deployment is disabled in the blueprint. Bundled sources/results are image contents; newly fetched registry snapshots are ephemeral and can disappear on restart, redeployment or free-service spin-down. No deployment is performed by updating this README.

## Limitations

Clinical eligibility remains unvalidated. There is no clinically validated end-to-end patient eligibility screening. Registry text, model proposals, fictional case demonstrations, synthetic policy experiments and archival proxy evaluations are distinct evidence sources. None establishes treatment benefit or clinical eligibility.

Reliability models, probabilities, costs and utility preferences are authored assumptions. Certificates apply only to their stated model sets and risk definitions. Missingness may be informative in real care; the modeled unavailable-report outcome does not capture that. Boolean scope, temporal semantics and evidence sufficiency require qualified review. No real patient upload or patient-level research data is included in the public application.

## License and attribution

Copyright (c) 2026 Koushik Chowdhury. Other contributors retain their respective rights.

Project-owned source is licensed under the [Mozilla Public License 2.0 (MPL-2.0)](LICENSE). Third-party materials retain their own terms; see [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt) and [third_party/licenses](third_party/licenses). Retain applicable notices and identify the corresponding source revision when distributing compiled frontend code or containers.

Registry sources are attributed to ClinicalTrials.gov / U.S. National Library of Medicine. NVIDIA model and Nebius service terms are separate; no model weights are distributed. No sponsor endorsement is implied. Scientific citations and source provenance remain in the linked research artifacts.
