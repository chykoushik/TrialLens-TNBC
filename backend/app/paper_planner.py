import hashlib
import json
from functools import lru_cache

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.app.extraction_source import ROOT
from research.certified_review_v1.belief import ReusablePosterior
from research.constrained_review_v1.factorized import action, solve_fast
from research.compiled_review_v1.decision import score

router = APIRouter(prefix="/research/planner", tags=["executable synthetic paper demonstration"])
SOURCE = "results/recomb/20261026-compiled-review-v2/decision_cases.json"


def cases():
    rows = json.loads((ROOT / SOURCE).read_text(encoding="utf-8"))
    return [row["case"] for row in rows if len(row["case"]["facts"]) <= 6 and row["split"] == "final"][:3]


@router.get("/scenarios")
def scenarios():
    return {"scenarios": [{"id": case["id"], "criteria": case["n"], "reports": len(case["facts"])} for case in cases()],
            "source": SOURCE, "sha256": hashlib.sha256((ROOT / SOURCE).read_bytes()).hexdigest(),
            "scope": "Synthetic paper scenarios. Report outcomes are hypothetical, not patient records."}


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: str = Field(max_length=150)
    budget: int = Field(default=1, ge=0, le=3)
    manual: bool = False
    outcomes: dict[str, int] = Field(default_factory=dict, max_length=6)


@lru_cache(maxsize=6)
def solve(identifier, budget):
    case = next((case for case in cases() if case["id"] == identifier), None)
    if case is None:
        raise HTTPException(404, "Unknown frozen research scenario")
    models = [ReusablePosterior(case, factor) for factor in (1., .65, 1.8)]
    result = solve_fast(models, budget, .08, max_iterations=30)
    metrics = score(result["columns"], result["solution"]["weights"], models, models[0])
    return case, models, result, metrics


@router.post("/evaluate")
def evaluate(request: Request):
    case, models, result, metrics = solve(request.scenario, request.budget)
    h = [-1] * len(case["facts"])
    active = [(column, weight) for column, weight in zip(result["columns"], result["solution"]["weights"]) if weight > 1e-9]
    for key, outcome in request.outcomes.items():
        if not key.isdigit() or str(int(key)) != key or int(key) >= len(h) or outcome not in (0, 1, 2):
            raise HTTPException(422, "Invalid hypothetical report outcome")
        if not request.manual:
            active = [(column, weight) for column, weight in active if action(column["policy"], tuple(h)) == int(key)]
            if not active:
                raise HTTPException(422, "This report is not a next action of the current constrained policy")
        h[int(key)] = outcome
    if sum(case["costs"][i] for i, value in enumerate(h) if value >= 0) > request.budget:
        raise HTTPException(422, "Review history exceeds the hard budget")
    history = tuple(h)
    models = [ReusablePosterior(case, factor) for factor in (1., .65, 1.8)]
    p = models[0]
    try:
        mass, probabilities, entropy, _ = p.stats[history]
    except KeyError:
        raise HTTPException(422, "These outcomes have no probability under the declared model") from None
    counterfactual = request.manual and bool(request.outcomes)
    if counterfactual:
        active = []
    actions = {}
    labels = []
    normalization = sum(weight for _, weight in active)
    for column, weight in active:
        weight /= normalization
        if weight <= 1e-9:
            continue
        policy = column["policy"]
        chosen = action(policy, history)
        actions[chosen] = actions.get(chosen, 0.) + weight
        labels.append({"weight": weight, "decisions": list(policy.decode(history))})
    feasible = set(p.available(history, request.budget))
    reports = [{"id": str(i), "criterion": fact + 1, "cost": case["costs"][i],
                "outcome": h[i], "selection_probability": actions.get(i, 0.),
                "feasible": i in feasible,
                "unavailable_reason": "Already reviewed." if h[i] >= 0 else "Not enough review budget." if i not in feasible else None,
                "permitted_outcomes": [child[i] for _, child in p.children(history, i)] if i in feasible else [],
                "expected_entropy_reduction": entropy - sum(prob * p.stats[child][2] for prob, child in p.children(history, i)) if h[i] < 0 else None}
               for i, fact in enumerate(case["facts"])]
    return {"scenario": case["id"], "manual_counterfactual": counterfactual,
            "recommendation_available": not counterfactual, "reports": reports, "protocol_probabilities": probabilities[p.n:],
            "entropy_bits": entropy, "spent": sum(cost for cost, value in zip(case["costs"], history) if value >= 0), "budget": request.budget,
            "stop_probability": None if counterfactual else actions.get(None, 0.), "policy_decisions": labels,
            "expected_policy_metrics": metrics, "numerical_gap": result["gap"],
            "risk_limit": .08, "model_factors": [1., .65, 1.8], "bdd_nodes": len(p.diagram.nodes),
            "cache": p.diagram.evaluate.cache_info()._asdict(), "boolean_graph": case["graph"],
            "scope": ("Manual counterfactual: posterior probabilities and budget-feasible reports are recomputed; no optimizer decisions or policy risk guarantees apply to the manual path. Metrics refer to the original root policy. " if counterfactual else "") + "Exact constrained policy mixture with compiled product-mixture inference and reusable BDD caching. Risk is expected wrong protocol assertions divided by all opportunities under three static models, not a continuous or clinical safety certificate. Information gain is descriptive; the policy optimizes utility, not entropy."}
