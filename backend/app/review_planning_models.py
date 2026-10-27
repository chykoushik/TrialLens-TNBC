from decimal import Decimal
from fractions import Fraction
from typing import Literal

from pydantic import Field, model_validator

from backend.app.criteria import Identifier
from backend.app.prioritization_models import Portfolio, ResearchModel


class JointReviewScenario(ResearchModel):
    scenario_id: Identifier
    probability: Decimal = Field(ge=0, le=1)
    outcomes: dict[str, str]


class ReviewDependence(ResearchModel):
    item_ids: list[Identifier] = Field(min_length=2)
    relationship: Literal["shared_fact", "correlated_records", "duplicate_record"]
    assumption: Identifier


class ReviewReliability(ResearchModel):
    conditional_error_probabilities: dict[str, dict[str, Decimal]]
    assumption: Identifier
    combination: Literal["union_bound"] = "union_bound"

    @model_validator(mode="after")
    def validate_probabilities(self) -> "ReviewReliability":
        for outcomes in self.conditional_error_probabilities.values():
            for value in outcomes.values():
                if not value.is_finite() or not 0 <= value <= 1:
                    raise ValueError("Invalid assumed review error probability")
        return self


class ReviewPlanningModel(ResearchModel):
    portfolio: Portfolio
    dependence_mode: Literal["independent_disjoint", "explicit_joint"]
    dependence_groups: list[ReviewDependence] = Field(default_factory=list)
    joint_scenarios: list[JointReviewScenario] | None = None
    reliability: ReviewReliability | None = None
    assumptions: list[Identifier] = Field(min_length=1)
    max_actions: int = Field(default=10, gt=0, le=16)
    max_scenarios: int = Field(default=512, gt=0)

    @model_validator(mode="after")
    def validate_metadata(self) -> "ReviewPlanningModel":
        actions = {action.item_id: action for action in self.portfolio.candidates}
        for group in self.dependence_groups:
            if len(set(group.item_ids)) != len(group.item_ids) or not set(group.item_ids) <= set(actions):
                raise ValueError("Invalid dependence group")
        if self.reliability:
            rates = self.reliability.conditional_error_probabilities
            if set(rates) != set(actions):
                raise ValueError("Reliability must cover every review")
            for identifier, action in actions.items():
                if set(rates[identifier]) != {outcome.outcome_id for outcome in action.outcomes}:
                    raise ValueError("Reliability must cover every review outcome")
        if self.joint_scenarios is not None:
            scenarios = self.joint_scenarios
            if not scenarios or len({item.scenario_id for item in scenarios}) != len(scenarios):
                raise ValueError("Invalid joint scenario IDs")
            if sum((Fraction(item.probability) for item in scenarios), Fraction()) != 1:
                raise ValueError("Joint probabilities must sum exactly to one")
            for item in scenarios:
                if set(item.outcomes) != set(actions):
                    raise ValueError("Joint scenarios must specify every review")
                for identifier, label in item.outcomes.items():
                    if label not in {outcome.outcome_id for outcome in actions[identifier].outcomes}:
                        raise ValueError("Unknown joint outcome")
            for identifier, action in actions.items():
                for outcome in action.outcomes:
                    if outcome.probability is None:
                        raise ValueError("Missing marginal outcome probabilities")
                    marginal = sum((Fraction(item.probability) for item in scenarios
                                    if item.outcomes[identifier] == outcome.outcome_id), Fraction())
                    if marginal != Fraction(outcome.probability):
                        raise ValueError("Joint and marginal probabilities disagree")
        return self


class UnsupportedReviewModel(ValueError):
    pass
