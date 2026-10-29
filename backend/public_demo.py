from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.app import demo_session, research_api, tnbc_api

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "frontend/dist"
app = FastAPI(title="TrialLens fictional public demo", docs_url=None, redoc_url=None, openapi_url=None)
router = APIRouter()
router.include_router(tnbc_api.router)
router.include_router(demo_session.router)
router.add_api_route("/research/cases", research_api.cases, methods=["GET"])
router.add_api_route("/research/cases/{case_id}/evaluate", research_api.evaluate, methods=["POST"])


@router.get("/health")
def health():
    return {"status": "ok", "public_demo": True, "paid_inference": False}


@router.get("/readiness")
def readiness():
    ready = len(tnbc_api.cases()) == 4 and (DIST / "index.html").is_file()
    return JSONResponse({"offline_ready": ready, "public_demo": True, "paid_inference": False}, status_code=200 if ready else 503)


@router.get("/research/trials")
def trials():
    return {"trials": [], "warnings": ["Saved source browsing is available in the controlled local workspace."]}


app.include_router(router)
app.include_router(router, prefix="/api")


@app.middleware("http")
async def public_headers(request, call_next):
    if request.method == "POST":
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 8192:
                return JSONResponse(status_code=413, content={"detail": "Request too large"})
            body.extend(chunk)
        request._body = bytes(body)
    try:
        response = await call_next(request)
    except Exception:
        if '/visitor-analysis/' not in request.url.path:
            raise
        response = JSONResponse(status_code=500, content={"detail": "Visitor analysis failed; no automatic retry was made. Provider processing and billing may have occurred."})
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if '/visitor-analysis/' in request.url.path:
        response.headers['Cache-Control'] = 'no-store'
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'none'"
    )
    return response


@app.get("/", include_in_schema=False)
def index():
    if not (DIST / "index.html").is_file():
        raise HTTPException(503, "Build the public frontend first")
    return FileResponse(DIST / "index.html")


if (DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")
