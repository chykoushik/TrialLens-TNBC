import os

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.public_demo import DIST, index, public_headers
from backend.app import demo_session, tnbc_api, research_api, trial_analysis, paper_planner, research_catalog, research_results, visitor_extraction

app = FastAPI(title="TrialLens-TNBC research prototype", docs_url=None, redoc_url=None, openapi_url=None)
app.middleware("http")(public_headers)


def health():
    return {"status": "ok", "public_demo": True, "visitor_extraction_enabled": os.environ.get("TRIALLENS_BYOK_ENABLED") == "1",
            "operator_inference_enabled": False, "storage": "bundled sources plus ephemeral search snapshots"}


def readiness():
    artifacts = all((research_catalog.ROOT / row[1]).is_file() for row in research_catalog.ARTIFACTS.values())
    sources, _ = research_api.catalog(research_api.RAW_TRIALS_DIR)
    try:
        ready = artifacts and bool(sources) and (DIST / "index.html").is_file() and bool(paper_planner.cases()) and len(tnbc_api.cases()) == 4
    except (OSError, ValueError, KeyError, TypeError):
        ready = False
    if not ready:
        raise HTTPException(503, "Required public research assets are missing.")
    return {"offline_ready": True, "research_ready": True, "visitor_extraction_enabled": os.environ.get("TRIALLENS_BYOK_ENABLED") == "1",
            "snapshot_persistence": "New searches expire on restart; bundled sources remain available."}


for prefix in ("", "/api"):
    app.add_api_route(prefix + "/health", health, methods=["GET"])
    app.add_api_route(prefix + "/readiness", readiness, methods=["GET"])
    for selected in (tnbc_api.router, demo_session.router, research_api.router, trial_analysis.router,
                     paper_planner.router, research_catalog.router, research_results.router, visitor_extraction.router):
        app.include_router(selected, prefix=prefix)


@app.exception_handler(RequestValidationError)
async def invalid_request(request, error):
    if "/visitor-analysis/" in request.url.path:
        return JSONResponse(status_code=422, content={"detail": "Invalid visitor analysis request."})
    from fastapi.exception_handlers import request_validation_exception_handler
    return await request_validation_exception_handler(request, error)


app.add_api_route("/", index, methods=["GET"], include_in_schema=False)
if (DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")
