from fastapi import APIRouter, HTTPException

from backend.app.research_api import ReviewRequest, evaluate_model
from backend.app.tnbc_demo import LABELS, PROTOCOL_TITLES, tnbc_cases

router = APIRouter(prefix="/tnbc", tags=["fictional TNBC demonstration"])


@router.get("/cases")
def cases():
    return [{"case_id": case.case_id, "title": case.title, "description": case.description,
             "is_synthetic": True, "trial_count": len(case.model.portfolio.trials),
             "review_count": len(case.model.portfolio.candidates), "budgets": ["0", "1", "2", "3"],
             "unsupported": None} for case in tnbc_cases()]


@router.post("/cases/{case_id}/evaluate")
def evaluate(case_id: str, request: ReviewRequest):
    from backend.app.demo_session import fixture_hash
    case = next((item for item in tnbc_cases() if item.case_id == case_id), None)
    if case is None:
        raise HTTPException(404, "Fictional TNBC case not found")
    return {**evaluate_model(case_id, case.model, request), "demo_fixture_sha256": fixture_hash(case.model), "case_title": case.title,
            "case_description": case.description, "display_labels": LABELS,
            "protocol_titles": PROTOCOL_TITLES}
