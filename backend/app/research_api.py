from decimal import Decimal
from fractions import Fraction
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.app.portfolio import evaluate_portfolio
from backend.app.prioritization import hypothetical_reviews, select_reviews
from backend.app.prioritization_models import ExperimentConfig, STRATEGIES
from backend.app.review_planning import ReviewPlanner, legacy_compatible
from backend.app.review_planning_models import UnsupportedReviewModel
from backend.app.synthetic_review_research import research_cases
from backend.app.saved_trials import catalog
from backend.app.trial_source import RAW_TRIALS_DIR

router = APIRouter(prefix="/research", tags=["synthetic research"])
Algorithm = Literal[
    "expected_per_cost", "expected_reduction", "random", "affected_trials",
    "uncertainty_only", "cost_only", "decisiveness_per_cost", "joint_greedy",
    "exact_nonadaptive", "adaptive_replan", "risk_greedy", "risk_exact", "risk_adaptive",
]


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    outcomes: dict[str, str] = Field(default_factory=dict, max_length=10)
    algorithm: Algorithm = "exact_nonadaptive"
    budget: Decimal = Field(default=Decimal(2), ge=0, le=100)
    seed: int = Field(default=7, ge=0, le=2147483647, strict=True)


def json_value(value):
    if hasattr(value, "model_dump"):
        return json_value(value.model_dump())
    if isinstance(value, (Decimal, Fraction)):
        return str(value)
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def case_model(case_id):
    for case in research_cases():
        if case.case_id == case_id:
            return case.model
    raise HTTPException(404, "Synthetic case not found")


@router.get("/cases")
def cases():
    result = []
    for case in research_cases():
        try:
            ReviewPlanner(case.model)
            unsupported = None
        except UnsupportedReviewModel as error:
            unsupported = str(error)
        result.append({"case_id": case.case_id, "is_synthetic": True,
                       "trial_count": len(case.model.portfolio.trials),
                       "review_count": len(case.model.portfolio.candidates),
                       "budgets": case.budgets, "unsupported": unsupported})
    return result


@router.post("/cases/{case_id}/evaluate")
def evaluate(case_id: str, request: ReviewRequest):
    return evaluate_model(case_id, case_model(case_id), request)


def evaluate_model(case_id, model, request: ReviewRequest):
    try:
        planner = ReviewPlanner(model)
        planner.conditional(request.outcomes)
        patient = hypothetical_reviews(model.portfolio, request.outcomes)
        spent = planner.cost(request.outcomes)
        remaining = Fraction(request.budget) - spent
        if remaining < 0:
            raise ValueError("Reviewed evidence exceeds total budget")
        risk = Fraction(3) if request.algorithm.startswith("risk_") else Fraction()
        if request.algorithm in STRATEGIES:
            if request.outcomes:
                raise UnsupportedReviewModel("legacy_plans_require_empty_history")
            if not legacy_compatible(model):
                raise UnsupportedReviewModel("legacy_baseline_assumes_independent_outcomes")
            plan = select_reviews(model.portfolio, request.algorithm,
                                  ExperimentConfig(budget=request.budget, seed=request.seed))
            plan.update(planner.value(plan["selected_items"]))
        elif request.algorithm in ("joint_greedy", "risk_greedy"):
            if request.outcomes:
                raise UnsupportedReviewModel("greedy_plans_require_empty_history")
            plan = planner.greedy(remaining, risk)
        else:
            plan = planner.exact(remaining, request.outcomes, risk)
        adaptive = request.algorithm in ("adaptive_replan", "risk_adaptive")
        return json_value({
            "is_synthetic": True, "case_id": case_id, "patient": patient,
            "assessment": evaluate_portfolio(model.portfolio, patient),
            "trials": model.portfolio.trials, "candidates": model.portfolio.candidates,
            "assumptions": model.assumptions + model.portfolio.assumptions,
            "reliability": model.reliability, "dependence_groups": model.dependence_groups,
            "cost_unit": model.portfolio.cost_unit, "spent": spent, "remaining_budget": remaining,
            "plan": plan, "adaptive": adaptive,
            "next_review": plan["selected_items"][0] if adaptive and plan["selected_items"] else None,
            "plan_scope": "conditional nonadaptive forecast; reveal one review then replan" if adaptive else "nonadaptive",
        })
    except UnsupportedReviewModel as error:
        raise HTTPException(409, str(error)) from error
    except (ValueError, KeyError) as error:
        raise HTTPException(422, str(error)) from error


@router.get("/trials")
def saved_trials(limit: int = Query(default=50, ge=1, le=100), history: bool = False):
    records, warnings = catalog(RAW_TRIALS_DIR, history=history)
    return {"trials": records[:limit], "warnings": warnings}
