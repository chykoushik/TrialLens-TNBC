import os

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from backend.app.research_api import router
from backend.app.tnbc_api import router as tnbc_router
from backend.app.trial_extraction_api import router as trial_extraction_router
from backend.app.annotation_api import router as annotation_router
from backend.app.demo_session import router as demo_session_router

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
app.include_router(tnbc_router)
app.include_router(trial_extraction_router)
app.include_router(annotation_router)
app.include_router(demo_session_router)


@app.middleware("http")
async def public_demo_boundary(request, call_next):
    if os.environ.get("TRIALLENS_PUBLIC_DEMO") == "1":
        path = request.url.path.rstrip("/")
        if path == "/trials" or path.startswith("/annotations") or (
            request.method == "POST" and path.startswith("/saved-trials")
        ):
            return JSONResponse(status_code=403, content={"detail": "Unavailable in public demo mode. Use the controlled local workspace."})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
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
