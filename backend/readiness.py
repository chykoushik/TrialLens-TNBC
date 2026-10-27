import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from backend.app.eligibility_benchmark import TRIAL_IDS
from backend.app.nebius import configuration_check
from backend.app.saved_trials import catalog
from backend.app.tnbc_demo import tnbc_cases

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ROUTES = {"/health", "/tnbc/cases", "/tnbc/cases/{case_id}/evaluate", "/tnbc/session/restore",
                   "/research/cases", "/research/trials", "/saved-trials/configuration", "/annotations/{nct_id}"}


def check(root=ROOT):
    from backend.app.main import app

    checks = []
    def record(name, ok, required=True):
        checks.append({"name": name, "status": "pass" if ok else "missing", "required": required})
    records, warnings = catalog(root / "data/raw/trials")
    ids = {r["nct_id"] for r in records if r["is_synthetic"] is not True}
    record("five_saved_public_studies", set(TRIAL_IDS) <= ids)
    record("snapshot_parse_warnings", not warnings, False)
    record("fictional_cases", len(tnbc_cases()) == 4)
    record("backend_routes", REQUIRED_ROUTES <= set(app.openapi()["paths"]))
    record("frontend_source", (root / "frontend/src/App.tsx").is_file())
    record("frontend_lockfile", (root / "frontend/package-lock.json").is_file())
    record("frontend_vite_configuration", (root / "frontend/vite.config.ts").is_file())
    base = os.environ.get("VITE_API_BASE_URL", "/api")
    try:
        parsed = urlsplit(base)
        local_path = base.startswith("/") and not base.startswith("//")
        origin = (parsed.scheme == "https" and bool(parsed.hostname)) or (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1"))
        valid_base = bool((local_path or origin) and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment)
    except ValueError:
        valid_base = False
    record("declared_frontend_api_configuration", valid_base)
    record("frontend_dependencies", (root / "frontend/node_modules/vite/package.json").is_file())
    record("frontend_build", (root / "frontend/dist/index.html").is_file(), False)
    benchmark = root / "data/benchmarks/tnbc-eligibility-v1"
    valid = False
    try:
        manifest = json.loads((benchmark / "manifest.json").read_text(encoding="utf-8"))
        valid = manifest["assessment_allowed"] is False and {t["nct_id"] for t in manifest["trials"]} == set(TRIAL_IDS)
        for trial in manifest["trials"]:
            path = (root / trial["source_snapshot"]).resolve()
            valid = valid and path.is_relative_to((root / "data/raw/trials").resolve())
            valid = valid and hashlib.sha256(path.read_bytes()).hexdigest() == trial["snapshot_sha256"]
            valid = valid and (benchmark / trial["nct_id"] / "reference.json").is_file()
        valid = valid and (benchmark / "annotation.schema.json").is_file()
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    record("optional_benchmark_sources", valid, False)
    record("optional_saved_reports", any((root / "results/prioritization").glob("**/report.md")), False)
    public = os.environ.get("TRIALLENS_PUBLIC_DEMO") == "1"
    record("public_inference_disabled", not public or os.environ.get("NEBIUS_LIVE_EXTRACTION") != "1")
    return {"offline_ready": all(c["status"] == "pass" for c in checks if c["required"]),
            "public_demo": public, "checks": checks, "inference": configuration_check(),
            "scope": "Offline file/configuration and registered-route checks; not a network or credential test."}


if __name__ == "__main__":
    result = check()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["offline_ready"] else 1)
