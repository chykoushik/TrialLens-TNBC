import hashlib
import time
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.app.research_api import Algorithm, ReviewRequest, evaluate_model
from backend.app.tnbc_demo import tnbc_cases

router = APIRouter(prefix="/tnbc/session", tags=["fictional session recovery"])


def fixture_hash(model):
    return hashlib.sha256(model.model_dump_json().encode("utf-8")).hexdigest()


class DemoSession(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1]
    kind: Literal["fictional-tnbc-demo"]
    savedAt: int = Field(ge=0)
    fixtureHash: str = Field(pattern=r"^[a-f0-9]{64}$")
    caseId: str = Field(max_length=60)
    step: int = Field(ge=0, le=4)
    algorithm: Algorithm
    budget: str = Field(pattern=r"^\d{1,3}(\.\d{1,4})?$")
    outcomes: dict[str, str] = Field(max_length=10)
    drafts: dict[str, str] = Field(max_length=10)


@router.post("/restore")
def restore(session: DemoSession):
    now = int(time.time() * 1000)
    if not now - 7 * 86400000 <= session.savedAt <= now + 60000:
        raise HTTPException(409, "Saved fictional demonstration expired. Start a new demonstration.")
    case = next((c for c in tnbc_cases() if c.case_id == session.caseId), None)
    if case is None or session.fixtureHash != fixture_hash(case.model):
        raise HTTPException(409, "Saved fictional fixture is incompatible. Start a new demonstration.")
    if Decimal(session.budget) > 100:
        raise HTTPException(422, "Invalid fictional review budget")
    actions = {a.item_id: a for a in case.model.portfolio.candidates}
    if any(key not in actions or value not in {o.outcome_id for o in actions[key].outcomes}
           or key in session.outcomes for key, value in session.drafts.items()):
        raise HTTPException(422, "Invalid fictional draft selection")
    history = {}
    evaluate_model(case.case_id, case.model, ReviewRequest(algorithm=session.algorithm, budget=session.budget, seed=7))
    for key, value in session.outcomes.items():
        if key not in actions or not set(actions[key].depends_on) <= set(history):
            raise HTTPException(422, "Invalid fictional review sequence")
        history[key] = value
        evaluate_model(case.case_id, case.model, ReviewRequest(
            algorithm=session.algorithm, budget=session.budget, outcomes=history, seed=7))
    return {"session": session.model_dump(), "validated": True}
