from fastapi import APIRouter, Header

from backend.app.inference_access import require_operator

router = APIRouter(prefix="/operator", tags=["operator authentication"])


@router.get("/session")
def session(authorization: str | None = Header(default=None)):
    require_operator(authorization)
    return {"authenticated": True}
