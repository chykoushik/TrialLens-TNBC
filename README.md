# TrialLens-TNBC
https://triallens-tnbc.onrender.com/
A research prototype for reviewing missing, conflicting and time-dependent evidence in fictional triple-negative breast cancer (TNBC) trial scenarios. The demonstration runs locally without API credentials. This is not a validated clinical eligibility system, diagnostic tool or treatment recommendation service.

## Overview

Clinical criteria can depend on multiple records, assay details, timing and cohort-specific rules. TrialLens-TNBC makes these dependencies visible and asks which existing record to review next under a limited review budget. Missing evidence remains unresolved rather than being treated as a negative result.

## What TrialLens-TNBC does

The demo evaluates authored fictional evidence against fictional protocol clauses, prioritizes record reviews, and recomputes assessments after a user applies an authored fictional report outcome. It does not order tests, accept real patient uploads or establish trial eligibility.

There are two operating modes. **Offline mode is the default:** the browser uses deterministic fictional calculations without credentials. **Optional live mode** adds an authenticated operator HTTP workflow that sends the bundled fictional protocol to NVIDIA Nemotron on Nebius Token Factory. Live results are returned separately and never update the fictional cases. The browser demo has no provider-key input and does not initiate live inference.

The source also contains a controlled local workspace for registry browsing, strict extraction validation and annotation. Saved sources, provider responses, research outputs and private annotations are not distributed; optional source views can be empty in a clean checkout.

## Key features

- Five explicit criterion states: satisfied, violated, unknown, temporal and conflict.
- Provenance, logical dependencies, temporal checks and budgeted review planning.
- Before/after explanations and backend-checked restoration of fictional browser sessions.
- Four fictional cases and predefined report outcomes, with no demo credentials.
- Source-grounded extraction validation that leaves unsupported proposals unreviewed.
- Optional, explicitly approved Nemotron inference with a persistent one-request limit.
- Registry retrieval and annotation routes remain unavailable on the public server.

## Application workflow

1. Open Home and select **Try the demo**.
2. Inspect the fictional evidence gaps and suggested record review.
3. Select an existing fictional report outcome. Selection alone does not apply it.
4. Select **Apply fictional report** to recompute clause states and remaining budget.
5. Read **What changed**, then inspect the next review or start a new demonstration.

Research Tools distinguishes failed model extraction from accepted source evidence. Registry links are context, not the source of the fictional patient's assessment.

## Architecture and technology stack

```text
React 19 + TypeScript browser UI
             | same-origin /api
FastAPI: backend.public_demo:app
             |
Python criterion assessment, review planning and authored fixtures
```

Vite 7 builds the frontend. Vitest and Testing Library cover frontend behavior; pytest and FastAPI TestClient cover the backend; Playwright covers browser journeys. The public server serves the built UI and API on one origin. `backend.app.main:app` is the broader controlled workspace, not the public deployment entry point. Application extraction templates are required runtime code, not development-agent instructions.

The live router in `backend/app/public_live.py` reuses `nebius.py` for server-side HTTP and the existing extraction prompt and strict source validator. Its protocol text is bundled and explicitly synthetic. It requires no saved registry data, private modules, internal annotations or developer services. The upstream call is `POST https://api.tokenfactory.nebius.com/v1/chat/completions` with model `nvidia/nemotron-3-super-120b-a12b`; the supported regional base URL is `https://api.tokenfactory.us-central1.nebius.com/v1`. No local model weights or GPU are needed.

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

No public repository URL is verified yet. After publication, copy its actual HTTPS clone URL from GitHub:

```powershell
$repositoryUrl = Read-Host 'Paste the published repository HTTPS clone URL'
git clone $repositoryUrl TrialLens-TNBC
Set-Location TrialLens-TNBC
```

Alternatively use GitHub **Code > Download ZIP**, extract it and open PowerShell in the extracted project directory. This README is the only Markdown document in the proposed public package.

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
$env:VITE_PUBLIC_DEMO = '1'
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
| `VITE_PUBLIC_DEMO` | `1` | Restricts public frontend navigation. |
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
| `TRIALLENS_LIVE_INFERENCE` | `0` | Additional opt-in for the public operator API. |
| `TRIALLENS_LIVE_OPERATOR_TOKEN` | empty | Separate operator authentication secret, 32â€“128 URL-safe characters; never reuse the Nebius key. |
| `TRIALLENS_LIVE_STATE_DIR` | empty | Absolute path to durable, writable reservation storage; required for live mode. |

## Start the backend and frontend

Serve the built public UI and backend together:

```powershell
.\.venv\Scripts\python.exe -B -m uvicorn backend.public_demo:app --host 127.0.0.1 --port 8080 --limit-concurrency 16 --no-access-log
```

For frontend development, use two terminals at the project root. Terminal one:

```powershell
.\.venv\Scripts\python.exe -B -m uvicorn backend.public_demo:app --host 127.0.0.1 --port 8000 --no-access-log
```

Terminal two:

```powershell
$env:VITE_PUBLIC_DEMO = '1'
$env:VITE_API_BASE_URL = '/api'
$env:TRIALLENS_API_TARGET = 'http://127.0.0.1:8000'
npm.cmd --prefix frontend run dev
```

The proxy removes `/api`; the public backend supports both prefixed and unprefixed demo routes. Stop servers with Ctrl+C.

For the optional controlled workspace, use `backend.app.main:app` on port 8000 and set `VITE_PUBLIC_DEMO='0'`. Keep it local, leave `NEBIUS_LIVE_EXTRACTION='0'` and expect missing source views. Its `/readiness` checks optional local source availability and can report missing private snapshots. Use the dedicated public server for the reproducible demo.

## Open and use the application

Open `http://127.0.0.1:8080` for the built application or `http://127.0.0.1:5173` for development. Check connectivity:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/api/health
Invoke-RestMethod http://127.0.0.1:8080/api/readiness
```

In default mode, public health reports `paid_inference: false`. In optional live mode this flag reports that the operator API is enabled, not that a provider call has occurred or succeeded. Health, readiness and preview requests never trigger inference. Public readiness requires the fictional cases and built frontend. Browser storage contains fictional demonstration state only.

## Optional live NVIDIA Nemotron inference

Use this mode only if you intend to authorize a potentially billable provider request. It is an operator-only API workflow, not a browser button or a replacement for the fictional demonstration. The only accepted input is bundled `fictional-protocol-v1`; its `NCT00000000` is a synthetic placeholder, not a registry study. Arbitrary text, patient records and local file paths are not accepted.

After installation and the frontend build, configure the **server terminal** from the release root. Read secrets privately; do not paste them into source files or command literals:

```powershell
$providerSecret = Read-Host 'Nebius API key (server only)' -AsSecureString
$env:NEBIUS_API_KEY = [System.Net.NetworkCredential]::new('', $providerSecret).Password
$operatorSecret = Read-Host 'Separate operator token, 32-128 URL-safe characters' -AsSecureString
$env:TRIALLENS_LIVE_OPERATOR_TOKEN = [System.Net.NetworkCredential]::new('', $operatorSecret).Password
$env:NEBIUS_MODEL = 'nvidia/nemotron-3-super-120b-a12b'
$env:NEBIUS_BASE_URL = 'https://api.tokenfactory.nebius.com/v1'
$env:NEBIUS_TIMEOUT_SECONDS = '120'
$env:TRIALLENS_LIVE_STATE_DIR = "$PWD/cache/public-live-state"
New-Item -ItemType Directory -Force $env:TRIALLENS_LIVE_STATE_DIR | Out-Null
$env:TRIALLENS_LIVE_INFERENCE = '1'
$env:NEBIUS_LIVE_EXTRACTION = '1'
.\.venv\Scripts\python.exe -B -m uvicorn backend.public_demo:app --host 127.0.0.1 --port 8080 --limit-concurrency 16 --no-access-log
```

Both enable flags, server-side provider configuration, a separate operator token and a valid storage path are required. Keep `VITE_PUBLIC_DEMO=1`; do not put either secret in a `VITE_*` variable or browser storage. `TRIALLENS_PUBLIC_DEMO` does not enable this new API. A provider key alone cannot send a request. The offline browser remains available at the same address.

In a **second operator terminal**, supply only the separate operator token, not the Nebius key. Use the assigned HTTPS origin for hosting; the loopback HTTP address below is for local testing:

```powershell
$baseUrl = 'http://127.0.0.1:8080'
$operatorSecret = Read-Host 'Operator token for this server' -AsSecureString
$headers = @{ Authorization = 'Bearer ' + [System.Net.NetworkCredential]::new('', $operatorSecret).Password }
$preview = Invoke-RestMethod "$baseUrl/api/inference/prepare" -Method Post -Headers $headers -ContentType 'application/json' -Body '{"source_id":"fictional-protocol-v1"}'
$preview | Select-Object model, max_output_tokens, timeout_seconds, source, expires_at, charge_warning | Format-List
```

Preparation sends **no provider request**. Review the exact synthetic source, source hash, model, output cap and charge warning. Signed approval expires after five minutes and is bound to the request and server configuration. The next block can incur charges and is intentionally separate:

```powershell
$confirmation = Read-Host 'Type APPROVE ONE PAID REQUEST to authorize this preview'
if ($confirmation -cne 'APPROVE ONE PAID REQUEST') { throw 'Not approved; no provider request sent' }
$body = @{ approval = $preview.approval; confirm_paid_request = $true } | ConvertTo-Json
$result = Invoke-RestMethod "$baseUrl/api/inference/execute" -Method Post -Headers $headers -ContentType 'application/json' -Body $body
$result | ConvertTo-Json -Depth 30
Remove-Variable headers, operatorSecret -ErrorAction SilentlyContinue
```

`GET /api/inference/status` requires the same operator authorization and never calls the provider. The API returns 404 when disabled, 401 for invalid operator authorization, 503 for unavailable configuration/storage, and 409 for invalid/expired approval or a consumed reservation. Missing or non-boolean paid confirmation is rejected before any reservation or request.

Exactly **one provider attempt is permitted per persistent state directory**, using an atomic `request.claim` file across workers. Reservation is recorded before HTTP dispatch. Provider errors, timeouts and invalid model output do not release it: processing/billing can be uncertain after timeout. There are no automatic retries, reset endpoints, alternate-model substitutions or live-to-mock fallback. Do not clear, replace or restore older reservation storage to retry. Any later increase in allowance requires a separate explicit operator decision and billing review. This is not an account-wide spending cap across unrelated tools or installations.

Output is capped at 8,192 tokens with a timeout at most 120 seconds. The reused client's model-specific reasoning control still requires provider-side compatibility verification. No successful real provider call is claimed by mocked tests. A completed response must pass the existing structural and exact-source validator; otherwise the API returns `validation_failed` with no proposal. A `source_validated` proposal remains unreviewed, requires qualified human review and has `assessment_allowed: false`. Source validation is not clinical validation. Raw provider responses are not stored or returned; credential echoes are withheld. Live output is never applied to the fictional demonstration.

## Available fictional demonstration data

Four cases are included: **Complete fictional records**, **Missing assay-matched records**, **Stale laboratory observation** and **Conflicting performance records**. Two fictional protocol examples illustrate PD-L1 and germline BRCA record cohorts. All are synthetic.

Frontend fixtures are in `frontend/src/fixtures/`; backend cases are constructed in `backend/app/tnbc_demo.py`. Backend fixtures are software test data, not clinical reference labels. No real patient records are included.

## Testing

Build the public frontend first, then run:

```powershell
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q --basetemp=cache/pytest-public -o cache_dir=cache/pytest-public-cache
$env:VITE_PUBLIC_DEMO = '0'
npm.cmd --prefix frontend test
```

Frontend tests exercise both controlled and demo components with mocked responses. Tests requiring optional private saved-source integration data are explicitly skipped in a clean checkout. Provider unit tests use synthetic values and mocked transports, never paid inference.

Targeted public live-inference tests also run without credentials, network access or charges:

```powershell
.\.venv\Scripts\python.exe -B -m pytest backend/tests/test_public_live.py backend/tests/test_public_release.py backend/tests/test_public_submission.py -q --basetemp=cache/pytest-live -o cache_dir=cache/pytest-live-cache
```

They verify approval, authentication, missing configuration, one atomic reservation under concurrent requests, sanitized provider failures/timeouts, credential-echo blocking and strict output validation. No successful live provider call is implied by passing mocks.

For the existing public browser journey, keep the built public server running on port 8080 and run in another terminal:

```powershell
$env:VITE_PUBLIC_DEMO = '1'
$env:DROPDOWN_BASE_URL = 'http://127.0.0.1:8080'
$env:DROPDOWN_EXTERNAL_SERVER = '1'
$env:DROPDOWN_RUN = 'local-public-check'
npm.cmd --prefix frontend run test:browser -- e2e/public-submission.spec.mjs --project=chrome
```

This checks real API-backed fictional review, session handling, keyboard use, responsive layout and blocked private routes. Outputs stay ignored. `python scripts/public_release.py` checks the public inventory and writes an ignored JSON inventory under `cache/`, without staging Git changes.

## Deployment information

There is no verified hosted URL. Existing `Dockerfile` and `render.yaml` describe a Node build stage, Python 3.12 runtime, non-root user and `PORT` configuration. Render checks `/api/readiness`, which returns HTTP 503 if the fictional cases or built frontend are unavailable; `/api/health` remains a liveness endpoint. Auto-deploy is disabled. The container launcher is `python -B -m backend.serve_public`.

Local startup verification does not establish a successful Docker/Linux build or hosted deployment. The owner must verify those before claiming availability. Repository preparation performs no deployment.

The default Render blueprint leaves both live enable flags at `0` and needs no persistent application data. For optional live mode, use one service instance with a [Render persistent disk](https://render.com/docs/disks), available on paid services. Mount durable storage, for example at `/var/data`, and set `TRIALLENS_LIVE_STATE_DIR` to a writable directory on that disk. Ensure Docker UID 10001 can create and retain the reservation file there; unwritable storage fails closed before inference. Set the Nebius key and separate operator token privately in the hosting dashboard, configure the model/base URL, then explicitly set both enable flags to `1`. Keep both secrets out of `render.yaml`, the frontend build and logs. Keep the existing public entry point; do not expose the broader controlled app to enable this feature.

Do not enable paid inference with ephemeral reservation storage, multiple independent state directories or independently scaled replicas. Restarts/redeploys must preserve `request.claim`; otherwise a one-request limit would reset. The free offline blueprint is not a persistent live-inference configuration. Docker/Linux disk permissions, the hosted endpoint and real provider behavior still need owner verification; no hosting resources are provisioned here.

## Limitations and research prototype disclaimer

Authored probabilities, costs and examples do not establish clinical calibration, benefit or safety. Missing, conflicting and stale evidence must not be converted into unsupported eligibility assertions. No diagnosis or treatment recommendation is provided.

The controlled NVIDIA Nemotron / Nebius integration produced saved attempts, including structured output rejected by validation. The public showcase retains that failed status and human-review requirement; it is not a clinical accuracy benchmark. The new optional operator API performs genuine inference only when explicitly executed and configured; its mocked tests are not live-provider verification. Model proposals require source validation and qualified human review. The offline browser demo always uses deterministic calculations and never substitutes model output.

## License and attribution

The project-owned source code in this repository is licensed under the Mozilla Public License, version 2.0 (MPL-2.0); see `LICENSE` for the complete official text. Third-party materials retain their own terms. The license selection is approved, but the available records do not establish copyright ownership or contributor rights. Publication remains blocked until the owner confirms the necessary rights. No copyright holder has been invented. This preparation is not legal clearance.

When distributing compiled frontend code or a container, make the corresponding MPL-covered source available and inform recipients how to obtain it. Before hosting a build, provide a link to the actual published source revision; no public repository URL is established yet.

Third-party terms remain in `THIRD_PARTY_NOTICES.txt` and `third_party/licenses/`. Preserve React, React DOM, Scheduler, Vite and installed Python notices. NVIDIA model and Nebius service terms are separate; no weights, credentials or raw model responses are distributed. Registry attribution remains ClinicalTrials.gov / U.S. National Library of Medicine. No sponsor endorsement is implied.

The [Nebius x NVIDIA Global AI Hackathon official rules](https://nebiusglobalaihackathon.devpost.com/rules) require an open-source repository and an NVIDIA model with qualifying Nebius runtime calls or Nebius AI Cloud execution. The optional API now supplies a public, independently configurable Token Factory request path, but the offline browser demo and mocked tests do not establish successful live runtime. Integration code and saved attempts must not be presented as clinical validation or a deployed Nebius application. Before publication/submission the owner must resolve licensing, ownership, approved live runtime verification, a working demo/test-build link and remaining submission materials.
