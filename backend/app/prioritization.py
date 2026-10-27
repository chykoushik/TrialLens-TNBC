from dataclasses import dataclass
from fractions import Fraction
import random

from backend.app.assessment_models import SyntheticPatient
from backend.app.portfolio import apply_outcome, decision_trace, evaluate_portfolio
from backend.app.prioritization_models import ExperimentConfig, Portfolio, STRATEGIES, Strategy


@dataclass
class World:
    probability: Fraction
    patient: SyntheticPatient
    outcomes: dict[str, str]


def dependency_bundle(portfolio: Portfolio, item_id: str, completed: set[str]) -> list[str]:
    actions = {action.item_id: action for action in portfolio.candidates}
    ordered, visited = [], set(completed)

    def visit(identifier):
        if identifier in visited:
            return
        if identifier not in actions:
            raise ValueError("Unknown review item")
        visited.add(identifier)
        for dependency in sorted(actions[identifier].depends_on):
            visit(dependency)
        ordered.append(identifier)

    visit(item_id)
    return ordered


def expand_worlds(portfolio: Portfolio, worlds: list[World], bundle: list[str], max_scenarios: int) -> list[World]:
    actions = {action.item_id: action for action in portfolio.candidates}
    for identifier in bundle:
        action = actions[identifier]
        if any(outcome.probability is None for outcome in action.outcomes):
            raise ValueError("Missing outcome probabilities")
        possible = [outcome for outcome in action.outcomes if outcome.probability > 0]
        if len(worlds) * len(possible) > max_scenarios:
            raise ValueError("Exact scenario limit exceeded")
        expanded = []
        for world in worlds:
            if identifier in world.outcomes or not set(action.depends_on) <= set(world.outcomes):
                raise ValueError("Unmet or repeated review dependency")
            for outcome in possible:
                expanded.append(World(
                    probability=world.probability * Fraction(outcome.probability),
                    patient=apply_outcome(world.patient, outcome),
                    outcomes={**world.outcomes, identifier: outcome.outcome_id},
                ))
        worlds = expanded
    return worlds


def hypothetical_reviews(portfolio: Portfolio, outcomes: dict[str, str]) -> SyntheticPatient:
    actions = {action.item_id: action for action in portfolio.candidates}
    if set(outcomes) - set(actions):
        raise ValueError("Unknown review item")
    patient = portfolio.patient.model_copy(deep=True)
    completed = set()
    pending = set(outcomes)
    while pending:
        ready = sorted(identifier for identifier in pending if set(actions[identifier].depends_on) <= completed)
        if not ready:
            raise ValueError("Missing prerequisite review")
        for identifier in ready:
            action = actions[identifier]
            matches = [outcome for outcome in action.outcomes if outcome.outcome_id == outcomes[identifier]]
            if not matches:
                raise ValueError("Unknown review outcome")
            patient = apply_outcome(patient, matches[0])
            completed.add(identifier)
            pending.remove(identifier)
    return patient


def expected_uncertainty(portfolio: Portfolio, worlds: list[World]) -> Fraction:
    return sum((world.probability * evaluate_portfolio(portfolio, world.patient).uncertainty
                for world in worlds), Fraction())


def bundle_utility(portfolio: Portfolio, worlds: list[World], bundle: list[str], max_scenarios: int) -> dict:
    after = expand_worlds(portfolio, worlds, bundle, max_scenarios)
    baseline = expected_uncertainty(portfolio, worlds)
    expected_after = Fraction()
    optimistic = Fraction()
    traces = []
    for world in worlds:
        conditional = [candidate for candidate in after
                       if all(candidate.outcomes.get(key) == value for key, value in world.outcomes.items())]
        assessments = [evaluate_portfolio(portfolio, candidate.patient) for candidate in conditional]
        before = evaluate_portfolio(portfolio, world.patient).uncertainty
        optimistic += world.probability * (before - min(result.uncertainty for result in assessments))
        for candidate, assessment in zip(conditional, assessments):
            expected_after += candidate.probability * assessment.uncertainty
            traces.append({
                "probability": candidate.probability, "outcomes": candidate.outcomes,
                "uncertainty": assessment.uncertainty, "decisions": decision_trace(assessment),
            })
    return {
        "uncertainty_before": baseline, "expected_uncertainty_after": expected_after,
        "delta_U": baseline - expected_after, "optimistic_reduction": optimistic,
        "outcome_traces": traces,
    }


def rank_worlds(
    portfolio: Portfolio, worlds: list[World], completed: set[str], strategy: Strategy,
    config: ExperimentConfig, remaining: Fraction,
) -> list[dict]:
    if strategy not in STRATEGIES:
        raise ValueError("Unknown strategy")
    actions = {action.item_id: action for action in portfolio.candidates}
    rng = random.Random(f"ranking:{config.seed}")
    random_scores = {identifier: Fraction(rng.getrandbits(53), 2 ** 53) for identifier in sorted(actions)}
    weights = {trial.trial_id: Fraction(trial.weight) for trial in portfolio.trials}
    current = [(world, evaluate_portfolio(portfolio, world.patient)) for world in worlds]
    rows = []
    for identifier in sorted(set(actions) - completed):
        bundle = dependency_bundle(portfolio, identifier, completed)
        cost = sum((Fraction(actions[item].cost) for item in bundle), Fraction())
        targets = {reference.trial_id for item in bundle for reference in actions[item].targets}
        row = {"item_id": identifier, "bundle": bundle, "cost": cost, "status": "feasible", "score": None}
        if any(actions[item].outcomes[0].probability is None for item in bundle):
            row["status"] = "missing_outcome_probabilities"
        elif cost > remaining:
            row["status"] = "over_budget"
        else:
            utility = bundle_utility(portfolio, worlds, bundle, config.max_scenarios)
            uncertainty = sum((world.probability * sum(
                (weights[decision.trial_id] for decision in assessment.decisions
                 if decision.trial_id in targets and decision.decision == "unresolved"), Fraction(),
            ) for world, assessment in current), Fraction())
            scores = {
                "expected_per_cost": utility["delta_U"] / cost,
                "expected_reduction": utility["delta_U"],
                "random": random_scores[identifier],
                "affected_trials": Fraction(len(targets)),
                "uncertainty_only": uncertainty,
                "cost_only": -cost,
                "decisiveness_per_cost": utility["optimistic_reduction"] / cost,
            }
            row.update(utility, score=scores[strategy], targets=sorted(targets))
        rows.append(row)
    return sorted(rows, key=lambda row: (
        row["status"] != "feasible", -(row["score"] or Fraction()), row["item_id"],
    ))


def rank_candidates(
    portfolio: Portfolio, strategy: Strategy, config: ExperimentConfig,
    reviewed_outcomes: dict[str, str] | None = None,
) -> list[dict]:
    reviewed = reviewed_outcomes or {}
    patient = hypothetical_reviews(portfolio, reviewed)
    costs = {action.item_id: Fraction(action.cost) for action in portfolio.candidates}
    remaining = Fraction(config.budget) - sum((costs[identifier] for identifier in reviewed), Fraction())
    if remaining < 0:
        raise ValueError("Completed reviews exceed budget")
    return rank_worlds(portfolio, [World(Fraction(1), patient, dict(reviewed))], set(reviewed), strategy, config, remaining)


def select_reviews(portfolio: Portfolio, strategy: Strategy, config: ExperimentConfig) -> dict:
    actions = {action.item_id: action for action in portfolio.candidates}
    worlds = [World(Fraction(1), portfolio.patient.model_copy(deep=True), {})]
    remaining = Fraction(config.budget)
    completed, ordered, steps = set(), [], []
    initial = evaluate_portfolio(portfolio)
    while len(completed) < len(actions):
        ranking = rank_worlds(portfolio, worlds, completed, strategy, config, remaining)
        feasible = [row for row in ranking if row["status"] == "feasible"]
        if not feasible:
            steps.append({"ranking": ranking, "selected": None})
            break
        best = feasible[0]
        worlds = expand_worlds(portfolio, worlds, best["bundle"], config.max_scenarios)
        remaining -= best["cost"]
        completed.update(best["bundle"])
        ordered.extend(best["bundle"])
        steps.append({"ranking": ranking, "selected": best["item_id"], "remaining_budget": remaining})
    final = expected_uncertainty(portfolio, worlds)
    return {
        "strategy": strategy, "seed": config.seed, "selected_items": ordered,
        "spent": Fraction(config.budget) - remaining, "remaining_budget": remaining,
        "initial_uncertainty": initial.uncertainty, "final_expected_uncertainty": final,
        "expected_reduction": initial.uncertainty - final, "steps": steps,
    }


def sample_outcomes(portfolio: Portfolio, seed: int) -> dict[str, str]:
    rng = random.Random(seed)
    result = {}
    for action in sorted(portfolio.candidates, key=lambda item: item.item_id):
        if action.outcomes[0].probability is None:
            continue
        draw, cumulative = Fraction(rng.getrandbits(53), 2 ** 53), Fraction()
        for outcome in sorted(action.outcomes, key=lambda item: item.outcome_id):
            cumulative += Fraction(outcome.probability)
            if draw < cumulative:
                result[action.item_id] = outcome.outcome_id
                break
    return result
