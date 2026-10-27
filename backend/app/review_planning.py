from fractions import Fraction
from itertools import combinations, product

from backend.app.portfolio import decision_trace, evaluate_portfolio
from backend.app.prioritization import dependency_bundle, hypothetical_reviews
from backend.app.review_planning_models import ReviewPlanningModel, UnsupportedReviewModel


def scenario_distribution(model: ReviewPlanningModel) -> list[tuple[Fraction, dict[str, str]]]:
    actions = sorted(model.portfolio.candidates, key=lambda item: item.item_id)
    if len(actions) > model.max_actions:
        raise UnsupportedReviewModel("exact_action_limit")
    for action in actions:
        if any(outcome.probability is None for outcome in action.outcomes):
            raise UnsupportedReviewModel("missing_outcome_probabilities")
    overlapping = []
    baseline = {item.evidence_id: item for item in model.portfolio.patient.evidence}
    for first, second in combinations(actions, 2):
        attributes = []
        for action in (first, second):
            touched = {item.clinical_attribute for outcome in action.outcomes for item in outcome.additions}
            touched.update(baseline[item.evidence_id].clinical_attribute
                           for outcome in action.outcomes for item in outcome.retractions)
            attributes.append(touched)
        shared_record = (first.existing_record.record_id == second.existing_record.record_id
                         or first.existing_record.reference == second.existing_record.reference)
        if shared_record or attributes[0] & attributes[1]:
            overlapping.append({first.item_id, second.item_id})
    declared = [set(group.item_ids) for group in model.dependence_groups]
    if overlapping and (model.dependence_mode != "explicit_joint"
                        or any(not any(pair <= group for group in declared) for pair in overlapping)):
        raise UnsupportedReviewModel("overlap_requires_declared_joint_model")
    if model.dependence_groups and model.dependence_mode != "explicit_joint":
        raise UnsupportedReviewModel("dependence_requires_joint_model")
    if model.dependence_mode == "explicit_joint":
        if model.joint_scenarios is None:
            raise UnsupportedReviewModel("missing_joint_distribution")
        distribution = [(Fraction(item.probability), dict(item.outcomes))
                        for item in model.joint_scenarios if item.probability > 0]
    else:
        if model.joint_scenarios is not None:
            raise UnsupportedReviewModel("unexpected_joint_distribution")
        possibilities = [[outcome for outcome in action.outcomes if outcome.probability > 0] for action in actions]
        count = 1
        for values in possibilities:
            count *= len(values)
        if count > model.max_scenarios:
            raise UnsupportedReviewModel("exact_scenario_limit")
        distribution = []
        for outcomes in product(*possibilities):
            probability = Fraction(1)
            for outcome in outcomes:
                probability *= Fraction(outcome.probability)
            distribution.append((probability, {action.item_id: outcome.outcome_id
                                                for action, outcome in zip(actions, outcomes)}))
    if len(distribution) > model.max_scenarios:
        raise UnsupportedReviewModel("exact_scenario_limit")
    return distribution


def legacy_compatible(model: ReviewPlanningModel) -> bool:
    distribution = scenario_distribution(model)
    probabilities = {}
    for probability, outcomes in distribution:
        key = tuple(sorted(outcomes.items()))
        probabilities[key] = probabilities.get(key, Fraction()) + probability
    actions = model.portfolio.candidates
    possibilities = [[outcome for outcome in action.outcomes if outcome.probability > 0] for action in actions]
    count = 1
    for values in possibilities:
        count *= len(values)
    if count > len(probabilities):
        return False
    for outcomes in product(*possibilities):
        expected = Fraction(1)
        for outcome in outcomes:
            expected *= Fraction(outcome.probability)
        key = tuple(sorted((action.item_id, outcome.outcome_id) for action, outcome in zip(actions, outcomes)))
        if probabilities.get(key, Fraction()) != expected:
            return False
    return True


class ReviewPlanner:
    def __init__(self, model: ReviewPlanningModel):
        self.model = model.model_copy(deep=True)
        self.distribution = scenario_distribution(self.model)
        self.actions = {item.item_id: item for item in self.model.portfolio.candidates}
        self.value_cache = {}
        self.assessment_cache = {}

    def assessment(self, history: dict[str, str]):
        key = tuple(sorted(history.items()))
        if key not in self.assessment_cache:
            patient = hypothetical_reviews(self.model.portfolio, history)
            self.assessment_cache[key] = evaluate_portfolio(self.model.portfolio, patient)
        return self.assessment_cache[key]

    def conditional(self, history: dict[str, str]):
        if set(history) - set(self.actions):
            raise ValueError("Unknown observed review")
        self.assessment(history)
        matching = [(probability, outcomes) for probability, outcomes in self.distribution
                    if all(outcomes[key] == value for key, value in history.items())]
        total = sum((probability for probability, _ in matching), Fraction())
        if not total:
            raise UnsupportedReviewModel("observed_history_has_zero_model_probability")
        return [(probability / total, outcomes) for probability, outcomes in matching]

    def cost(self, identifiers) -> Fraction:
        return sum((Fraction(self.actions[item].cost) for item in identifiers), Fraction())

    def ordered(self, selected, history) -> list[str]:
        result, completed = [], set(history)
        for identifier in sorted(selected):
            for item in dependency_bundle(self.model.portfolio, identifier, completed):
                if item not in selected:
                    raise ValueError("Selected set is not prerequisite-closed")
                result.append(item)
                completed.add(item)
        return result

    def error_bound(self, history: dict[str, str], assessment) -> Fraction:
        reliability = self.model.reliability
        if reliability is None:
            raise UnsupportedReviewModel("missing_review_reliability")
        weights = {trial.trial_id: Fraction(trial.weight) for trial in self.model.portfolio.trials}
        risk = Fraction()
        for decision in assessment.decisions:
            if decision.decision == "unresolved":
                continue
            errors = Fraction()
            for identifier, label in history.items():
                action = self.actions[identifier]
                outcome = next(item for item in action.outcomes if item.outcome_id == label)
                if ((outcome.additions or outcome.retractions)
                        and any(ref.trial_id == decision.trial_id for ref in action.targets)):
                    errors += Fraction(reliability.conditional_error_probabilities[identifier][label])
            risk += weights[decision.trial_id] * min(Fraction(1), errors)
        return risk

    def value(self, selected, history=None, risk_weight=Fraction()) -> dict:
        history = dict(history or {})
        risk_weight = Fraction(risk_weight)
        if risk_weight < 0:
            raise ValueError("Negative risk weight")
        identifiers = tuple(selected)
        selected = frozenset(identifiers)
        if len(selected) != len(identifiers):
            raise ValueError("Repeated selected reviews")
        if selected & set(history) or selected - set(self.actions):
            raise ValueError("Repeated or unknown selected reviews")
        self.ordered(selected, history)
        key = (tuple(sorted(selected)), tuple(sorted(history.items())), risk_weight)
        if key in self.value_cache:
            return dict(self.value_cache[key])
        before = self.assessment(history)
        initial_risk = self.error_bound(history, before) if risk_weight else Fraction()
        expected_u, expected_risk = Fraction(), Fraction()
        for probability, outcomes in self.conditional(history):
            observed = {**history, **{item: outcomes[item] for item in selected}}
            after = self.assessment(observed)
            expected_u += probability * after.uncertainty
            if self.model.reliability:
                expected_risk += probability * self.error_bound(observed, after)
        reduction = before.uncertainty - expected_u
        result = {
            "expected_reduction": reduction, "expected_final_uncertainty": expected_u,
            "expected_error_bound": expected_risk if self.model.reliability else None,
            "expected_utility": reduction - risk_weight * (expected_risk - initial_risk),
            "risk_weight": risk_weight,
        }
        self.value_cache[key] = result
        return dict(result)

    def feasible_sets(self, budget, history=None):
        budget, history = Fraction(budget), dict(history or {})
        if budget < 0:
            raise ValueError("Negative remaining budget")
        self.conditional(history)
        identifiers = sorted(set(self.actions) - set(history))
        for size in range(len(identifiers) + 1):
            for selected in combinations(identifiers, size):
                if self.cost(selected) > budget:
                    continue
                if any(set(self.actions[item].depends_on) - set(history) - set(selected) for item in selected):
                    continue
                yield selected

    def exact(self, budget, history=None, risk_weight=Fraction()) -> dict:
        history = dict(history or {})
        feasible = []
        for selected in self.feasible_sets(budget, history):
            feasible.append({"selected_items": self.ordered(selected, history), "spent": self.cost(selected),
                             **self.value(selected, history, risk_weight)})
        best = min(feasible, key=lambda row: (-row["expected_utility"], row["spent"], tuple(row["selected_items"])))
        return {**best, "feasible_sets_evaluated": len(feasible), "benchmark": "exact_nonadaptive"}

    def greedy(self, budget, risk_weight=Fraction()) -> dict:
        selected, remaining, trace = [], Fraction(budget), []
        if remaining < 0:
            raise ValueError("Negative budget")
        while True:
            current = self.value(selected, risk_weight=risk_weight)
            candidates = []
            for identifier in sorted(set(self.actions) - set(selected)):
                bundle = dependency_bundle(self.model.portfolio, identifier, set(selected))
                cost = self.cost(bundle)
                if cost <= remaining:
                    future = self.value(selected + bundle, risk_weight=risk_weight)
                    delta = future["expected_utility"] - current["expected_utility"]
                    candidates.append({"item_id": identifier, "bundle": bundle, "cost": cost, "delta": delta, "score": delta / cost})
            candidates.sort(key=lambda row: (-row["score"], row["item_id"]))
            if not candidates or candidates[0]["delta"] <= 0:
                break
            chosen = candidates[0]
            trace.append({"ranking": candidates, "selected": chosen["item_id"]})
            selected.extend(chosen["bundle"])
            remaining -= chosen["cost"]
        return {"selected_items": selected, "spent": Fraction(budget) - remaining,
                **self.value(selected, risk_weight=risk_weight), "trace": trace}

    def next_review(self, history, remaining, risk_weight=Fraction()):
        plan = self.exact(remaining, history, risk_weight)
        return (plan["selected_items"][0] if plan["selected_items"] else None), plan

    def simulate(self, budget, reveal, risk_weight=Fraction()) -> dict:
        history, remaining, trace = {}, Fraction(budget), []
        while True:
            identifier, forecast = self.next_review(history, remaining, risk_weight)
            if identifier is None:
                break
            before = self.assessment(history)
            label = reveal(identifier)
            history[identifier] = label
            self.conditional(history)
            remaining -= self.cost([identifier])
            after = self.assessment(history)
            trace.append({"review": identifier, "forecast_before_observation": forecast,
                          "observed_outcome": label, "uncertainty_before": before.uncertainty,
                          "uncertainty_after": after.uncertainty, "remaining_budget": remaining,
                          "decisions": decision_trace(after)})
        return {"selected_items": list(history), "observed_outcomes": history,
                "spent": Fraction(budget) - remaining, "trace": trace}

    def adaptive_value(self, budget, risk_weight=Fraction()) -> dict:
        initial = self.assessment({}).uncertainty
        expected_u, expected_risk, expected_cost = Fraction(), Fraction(), Fraction()
        for probability, outcomes in self.distribution:
            result = self.simulate(budget, lambda identifier: outcomes[identifier], risk_weight)
            assessment = self.assessment(result["observed_outcomes"])
            expected_u += probability * assessment.uncertainty
            expected_cost += probability * result["spent"]
            if self.model.reliability:
                expected_risk += probability * self.error_bound(result["observed_outcomes"], assessment)
        return {"expected_reduction": initial - expected_u,
                "expected_final_uncertainty": expected_u,
                "expected_error_bound": expected_risk if self.model.reliability else None,
                "expected_utility": initial - expected_u - Fraction(risk_weight) * expected_risk,
                "expected_spent": expected_cost, "risk_weight": Fraction(risk_weight)}
