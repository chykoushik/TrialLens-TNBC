import os

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from backend.app.inference_review import router as inference_review_router
from backend.app.real_trial_review import router as real_review_router
from backend.app.research_results import router as results_router
from backend.app.research_api import router
from backend.app.tnbc_api import router as tnbc_router
from backend.app.trial_extraction_api import router as trial_extraction_router
from backend.app.annotation_api import router as annotation_router
from backend.app.demo_session import router as demo_session_router
from backend.app.trial_analysis import router as analysis_router
from backend.app.paper_planner import router as paper_planner_router
from backend.app.research_catalog import router as research_catalog_router
from backend.app.operator_access import router as operator_router
from backend.app.visitor_extraction import router as visitor_router
from fastapi.exceptions import RequestValidationError

from backend.app.trial_parser import Trial, parse_trials
from backend.app.trial_source import retrieve_trials

app = FastAPI(title="TrialLens-TNBC")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.environ.get("TRIALLENS_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip() and origin.strip() != "*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(router)
app.include_router(results_router)
app.include_router(real_review_router)
app.include_router(inference_review_router)
app.include_router(tnbc_router)
app.include_router(trial_extraction_router)
app.include_router(annotation_router)
app.include_router(demo_session_router)
app.include_router(analysis_router)
app.include_router(paper_planner_router)
app.include_router(research_catalog_router)
app.include_router(operator_router)
app.include_router(visitor_router)


@app.exception_handler(RequestValidationError)
async def invalid_request(request, error):
    if request.url.path.startswith('/visitor-analysis'):
        return JSONResponse(status_code=422, content={"detail": "Invalid visitor analysis request."})
    from fastapi.exception_handlers import request_validation_exception_handler
    return await request_validation_exception_handler(request, error)


@app.middleware("http")
async def public_demo_boundary(request, call_next):
    if request.url.path.startswith('/visitor-analysis'):
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 8192:
                return JSONResponse(status_code=413, content={"detail": "Request too large"})
            body.extend(chunk)
        request._body = bytes(body)
    if os.environ.get("TRIALLENS_PUBLIC_DEMO") == "1":
        path = request.url.path.rstrip("/")
        if path == "/trials" or path.startswith("/annotations") or (
            request.method == "POST" and path.startswith("/saved-trials")
        ):
            return JSONResponse(status_code=403, content={"detail": "Unavailable in public demo mode. Use the controlled local workspace."})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith('/visitor-analysis'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readiness")
def readiness():
    from backend.readiness import check
    return check()


@app.get("/trials", response_model=list[Trial])
def trials(limit: int = Query(default=10, ge=1, le=100)) -> list[Trial]:
    try:
        return parse_trials(retrieve_trials(limit))
    except httpx.TimeoutException as error:
        raise HTTPException(status_code=504, detail="Trial source timed out") from error
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail="Trial source request failed") from error
    except (ValueError, TypeError, AttributeError) as error:
        raise HTTPException(status_code=502, detail="Invalid trial source response") from error
    except OSError as error:
        raise HTTPException(status_code=500, detail="Trial snapshot storage failed") from error
