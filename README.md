# TrialLens-TNBC

A research prototype for reviewing missing, conflicting and time-dependent evidence in fictional triple-negative breast cancer (TNBC) trial scenarios. The demonstration runs locally without API credentials. This is not a validated clinical eligibility system, diagnostic tool or treatment recommendation service.

## Overview

Clinical criteria can depend on multiple records, assay details, timing and cohort-specific rules. TrialLens-TNBC makes these dependencies visible and asks which existing record to review next under a limited review budget. Missing evidence remains unresolved rather than being treated as a negative result.

## What TrialLens-TNBC does

The demo evaluates authored fictional evidence against fictional protocol clauses, prioritizes record reviews, and recomputes assessments after a user applies an authored fictional report outcome. It does not order tests, accept real patient uploads or establish trial eligibility.

The source also contains a controlled local workspace for registry browsing, strict extraction validation and annotation. The public package includes explicitly allowlisted registry snapshots, aggregate research results and the actual compiled inference/planning code. Raw provider responses, authorization records, private annotations and individual patient records are excluded.

## Key features

- Five explicit criterion states: satisfied, violated, unknown, temporal and conflict.
- Provenance, logical dependencies, temporal checks and budgeted review planning.
- Before/after explanations and backend-checked restoration of fictional browser sessions.
- Four fictional cases and predefined report outcomes, with no demo credentials.
- Source-grounded extraction validation that leaves unsupported proposals unreviewed.
- Real ClinicalTrials.gov search and source-only trial analysis, plus compiled Boolean inference and constrained adaptive review.
- A public server without paid provider, operator or annotation routes. BYOK remains available only in the controlled local workspace.

## Application workflow

1. Search ClinicalTrials.gov or choose a bundled saved trial.
2. Select the trial and click **Analyze trial**. This sends no paid inference request.
3. Read source-linked results and their limitations.
4. Open **Evidence Review** to run the actual planner on synthetic scenarios.
5. Browse **Research Results** for the paper, baselines, METABRIC, TCGA, BDD, caching and certification findings.

Research Tools distinguishes failed model extraction from accepted source evidence. Registry links are context, not the source of the fictional patient's assessment.

## Architecture and technology stack

```text
React 19 + TypeScript browser UI
             | same-origin /api
FastAPI: backend.research_public:app
             |
Python criterion assessment, review planning and authored fixtures
```

Vite 7 builds the frontend. Vitest and Testing Library cover frontend behavior; pytest and FastAPI TestClient cover the backend; Playwright covers browser journeys. The public server serves the built UI and API on one origin. `backend.app.main:app` is the broader controlled workspace, not the public deployment entry point. Application extraction templates are required runtime code, not development-agent instructions.

## Screenshots

Actual local application captures using fictional data:

![Fictional evidence review and before/after assessment](assets/screenshots/demo-desktop.png)

<img src="assets/screenshots/home-mobile.png" alt="TrialLens-TNBC mobile home page" width="320">

## System requirements

- Python 3.12 and public package registry access during installation.
- Node.js 22.12 or later compatible with Vite 7, and npm. Local verification used Node 24 and npm 11; `package-lock.json` pins the frontend tree.
- Windows PowerShell and a modern browser. No GPU or model download is required for the fictional demo.
- Chrome or Edge for the supplied browser-test projects.

## Clone or download

Source repository: https://github.com/chykoushik/TrialLens-TNBC.

```powershell
git clone https://github.com/chykoushik/TrialLens-TNBC.git TrialLens-TNBC
Set-Location TrialLens-TNBC
```

Alternatively use GitHub **Code > Download ZIP**, extract it and open PowerShell in the extracted project directory. The package includes this README and an explicit allowlist of authored research reports needed by the public research views.

## Backend installation and configuration

Run from the project root. Activation is optional because commands use the virtual environment interpreter directly:

```powershell
New-Item -ItemType Directory -Force cache | Out-Null
$env:TEMP = "$PWD/cache"
$env:TMP = "$PWD/cache"
$env:PIP_CACHE_DIR = "$PWD/cache/pip"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-demo.lock.txt
.\.venv\Scripts\python.exe -m pip check
```

The pinned file includes API and test dependencies. `requirements.txt` lists direct dependencies; use the lock file above for tested versions.

## Frontend installation and configuration

```powershell
npm.cmd --prefix frontend ci --cache "$PWD/cache/npm" --no-audit --no-fund
$env:VITE_PUBLIC_DEMO = '0'
$env:VITE_PUBLIC_RESEARCH = '1'
$env:VITE_API_BASE_URL = '/api'
npm.cmd --prefix frontend run build
New-Item -ItemType Directory -Force frontend/dist/assets/licenses | Out-Null
Copy-Item third_party/licenses/*.txt frontend/dist/assets/licenses/
```

`VITE_*` variables are public build-time settings. Rebuild after changing them. Never put an API key into a `VITE_*` variable.

## Environment variables

`.env.example` has empty credential fields and safe example values. Neither the Python server nor Vite automatically loads it; Vite explicitly disables environment-file loading. Set process variables in PowerShell. Do not commit actual environment files or credentials.

| Variable | Safe value | Purpose |
|---|---|---|
| `VITE_PUBLIC_DEMO` | `0` | Legacy fictional-only build; disabled for the complete research demo. |
| `VITE_PUBLIC_RESEARCH` | `1` | Public research interface; hides operator and unsupported local controls. |
| `TRIALLENS_BYOK_ENABLED` | `0` | Public server always blocks BYOK until infrastructure handling is verified. |
| `VITE_API_BASE_URL` | `/api` | Same-origin API path. |
| `TRIALLENS_API_TARGET` | `http://127.0.0.1:8000` | Vite development proxy target. |
| `PORT` | `8080` | Port for the optional `backend.serve_public` launcher. |
| `TRIALLENS_PUBLIC_DEMO` | `1` | Restricts the broader workspace; dedicated public server is independent. |
| `TRIALLENS_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Broader workspace CORS. |
| `NEBIUS_API_KEY` | empty | Controlled integration only; leave unset for demo. |
| `NEBIUS_MODEL` | `nvidia/nemotron-3-super-120b-a12b` | Controlled integration model ID. |
| `NEBIUS_BASE_URL` | `https://api.tokenfactory.nebius.com/v1` | Controlled inference endpoint. |
| `NEBIUS_TIMEOUT_SECONDS` | `120` | Controlled request timeout. |
| `NEBIUS_LIVE_EXTRACTION` | `0` | Live extraction disabled. |
| `NEBIUS_INPUT_USD_PER_MILLION` / `NEBIUS_OUTPUT_USD_PER_MILLION` | empty | Optional declared pricing; no price assumed. |

## Start the backend and frontend

Serve the built public UI and backend together:

```powershell
.\.venv\Scripts\python.exe -B -m uvicorn backend.research_public:app --host 127.0.0.1 --port 8080 --limit-concurrency 16 --no-access-log --no-proxy-headers
```

For frontend development, use two terminals at the project root. Terminal one:

```powershell
.\.venv\Scripts\python.exe -B -m uvicorn backend.research_public:app --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
```

Terminal two:

```powershell
$env:VITE_PUBLIC_DEMO = '0'
$env:VITE_PUBLIC_RESEARCH = '1'
$env:VITE_API_BASE_URL = '/api'
$env:TRIALLENS_API_TARGET = 'http://127.0.0.1:8000'
npm.cmd --prefix frontend run dev
```

The proxy removes `/api`; the public backend supports both prefixed and unprefixed demo routes. Stop servers with Ctrl+C.

For the optional controlled workspace, use `backend.app.main:app` on port 8000 and set `VITE_PUBLIC_DEMO='0'`. Keep it local, set `VITE_PUBLIC_RESEARCH='0'` and `TRIALLENS_PUBLIC_RESEARCH='0'`, leave `NEBIUS_LIVE_EXTRACTION='0'` and expect missing source views. Its `/readiness` checks optional local source availability and can report missing private snapshots. Use the dedicated public server for the reproducible demo.

## Open and use the application

Open `http://127.0.0.1:8080` for the built application or `http://127.0.0.1:5173` for development. Check connectivity:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/api/health
Invoke-RestMethod http://127.0.0.1:8080/api/readiness
```

Public health reports `visitor_extraction_enabled: false` and `operator_inference_enabled: false`. Public readiness checks the built frontend, bundled registry sources and required aggregate research artifacts. Browser storage contains fictional demonstration state only.

## Available fictional demonstration data

Four cases are included: **Complete fictional records**, **Missing assay-matched records**, **Stale laboratory observation** and **Conflicting performance records**. Two fictional protocol examples illustrate PD-L1 and germline BRCA record cohorts. All are synthetic.

Frontend fixtures are in `frontend/src/fixtures/`; backend cases are constructed in `backend/app/tnbc_demo.py`. Backend fixtures are software test data, not clinical reference labels. No real patient records are included.

## Testing

Build the public frontend first, then run:

```powershell
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q --basetemp=cache/pytest-public -o cache_dir=cache/pytest-public-cache
$env:VITE_PUBLIC_DEMO = '0'
$env:VITE_PUBLIC_RESEARCH = '0'
npm.cmd --prefix frontend test
```

Frontend tests exercise both controlled and demo components with mocked responses. Tests requiring optional private saved-source integration data are explicitly skipped in a clean checkout. Provider unit tests use synthetic values and mocked transports, never paid inference.

For the existing public browser journey, keep the built public server running on port 8080 and run in another terminal:

```powershell
$env:VITE_PUBLIC_DEMO = '0'
$env:VITE_PUBLIC_RESEARCH = '1'
$env:DROPDOWN_BASE_URL = 'http://127.0.0.1:8080'
$env:DROPDOWN_EXTERNAL_SERVER = '1'
$env:DROPDOWN_RUN = 'local-public-check'
npm.cmd --prefix frontend run test:browser -- e2e/production-research.spec.mjs
```

This checks live registry search, Analyze, actual synthetic planner execution, aggregate research views, desktop/mobile layout and absence of operator controls in Chrome and Edge. Outputs stay ignored. `python scripts/public_release.py` checks the public inventory and writes an ignored JSON inventory under `cache/`, without staging Git changes.

## Deployment information

The existing public service is https://triallens-tnbc.onrender.com/. Verify the running source revision and endpoints separately. Existing `Dockerfile` and `render.yaml` describe a Node build stage, Python 3.12 runtime, non-root user, `/api/readiness` deployment health check and `PORT` configuration. The container launcher is `python -B -m backend.serve_public`; it starts `backend.research_public:app` with one worker, access logs disabled and forwarded headers ignored. Render terminates TLS; the app does not trust caller-supplied forwarded headers or accept public visitor credentials.

Bundled sources and aggregate research artifacts are immutable image contents and survive redeployment as part of the image. New search snapshots are ephemeral and disappear on Render restarts, redeploys and free-service spin-down; search again if a snapshot expires. This demo has no cloud persistence for new analyses or patient data. Keeping new searches across restarts would require an explicitly configured persistent store.

Public BYOK is blocked independently of environment toggles. Infrastructure request/error tracing, edge logging and current provider pricing must be verified before changing that boundary. Do not set a server provider key for the public demonstration.

Local startup verification does not establish a successful Docker/Linux build or hosted deployment. The owner must verify those before claiming availability. Repository preparation performs no deployment.

## Limitations and research prototype disclaimer

Clinical eligibility remains unvalidated.

Authored probabilities, costs and examples do not establish clinical calibration, benefit or safety. Missing, conflicting and stale evidence must not be converted into unsupported eligibility assertions. No diagnosis or treatment recommendation is provided.

The controlled NVIDIA Nemotron / Nebius integration produced saved attempts, including structured output rejected by validation. The public showcase retains that failed status and human-review requirement; it is not a clinical accuracy benchmark. Model proposals require source validation and qualified human review. The offline demo uses deterministic calculations, not live model inference.

## License and attribution

Copyright (c) 2026 Koushik Chowdhury. Other contributors retain their respective rights.

The published project-owned source is licensed under the Mozilla Public License, version 2.0 (MPL-2.0); see LICENSE. Third-party materials retain their own license terms.

When distributing compiled frontend code or a container, retain the license notices and identify the corresponding source revision.

Third-party terms remain in `THIRD_PARTY_NOTICES.txt` and `third_party/licenses/`. Preserve React, React DOM, Scheduler, Vite and installed Python notices. NVIDIA model and Nebius service terms are separate; no weights, credentials or raw model responses are distributed. Registry attribution remains ClinicalTrials.gov / U.S. National Library of Medicine. No sponsor endorsement is implied.

The [Nebius x NVIDIA Global AI Hackathon official rules](https://nebiusglobalaihackathon.devpost.com/rules) require an open-source repository and an NVIDIA model with qualifying Nebius runtime calls or Nebius AI Cloud execution. This offline demo alone does not establish that requirement. Integration code and saved attempts must not be presented as validated extraction or a deployed Nebius application. Before submission, confirm qualifying runtime evidence, a working demo/test-build link and remaining submission materials.
