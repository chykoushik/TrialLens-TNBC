from decimal import Decimal
from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.app.assessment_models import (
    AssessmentContext, CriterionBinding, EvidenceProvenance, PatientEvidence, SyntheticPatient,
    TrialAssessment,
)
from backend.app.criteria import Identifier, TrialCriteriaSet

Strategy = Literal[
    "expected_per_cost", "expected_reduction", "random", "affected_trials",
    "uncertainty_only", "cost_only", "decisiveness_per_cost",
]
STRATEGIES = (
    "expected_per_cost", "expected_reduction", "random", "affected_trials",
    "uncertainty_only", "cost_only", "decisiveness_per_cost",
)


class ResearchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TrialProtocol(ResearchModel):
    trial_id: Identifier
    criteria_set: TrialCriteriaSet
    bindings: list[CriterionBinding]
    context: AssessmentContext
    weight: Decimal = Field(default=Decimal(1), gt=0)


class CriterionReference(ResearchModel):
    trial_id: Identifier
    criterion_id: Identifier


class EvidenceRetraction(ResearchModel):
    evidence_id: Identifier
    reason: Identifier
    provenance: EvidenceProvenance


class ReviewOutcome(ResearchModel):
    outcome_id: Identifier
    probability: Decimal | None = Field(default=None, ge=0, le=1)
    additions: list[PatientEvidence] = Field(default_factory=list)
    retractions: list[EvidenceRetraction] = Field(default_factory=list)
    description: Identifier

    @model_validator(mode="after")
    def unique_updates(self) -> "ReviewOutcome":
        for identifiers in (
            [item.evidence_id for item in self.additions],
            [item.evidence_id for item in self.retractions],
        ):
            if len(identifiers) != len(set(identifiers)):
                raise ValueError("Duplicate evidence update")
        return self


class EvidenceReview(ResearchModel):
    item_id: Identifier
    action_type: Literal["review_existing_evidence"]
    existing_record: EvidenceProvenance
    description: Identifier
    cost: Decimal = Field(gt=0)
    targets: list[CriterionReference] = Field(min_length=1)
    depends_on: list[Identifier] = Field(default_factory=list)
    outcomes: list[ReviewOutcome] = Field(min_length=1)
    probability_basis: Identifier | None = None

    @model_validator(mode="after")
    def validate_outcomes(self) -> "EvidenceReview":
        if len({outcome.outcome_id for outcome in self.outcomes}) != len(self.outcomes):
            raise ValueError("Outcome IDs must be unique")
        probabilities = [outcome.probability for outcome in self.outcomes]
        if any(value is None for value in probabilities):
            if not all(value is None for value in probabilities):
                raise ValueError("Partially specified distribution")
        else:
            if sum((Fraction(value) for value in probabilities), Fraction()) != 1:
                raise ValueError("Probabilities must sum exactly to one")
            if self.probability_basis is None:
                raise ValueError("Probability assumptions must be documented")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("Duplicate dependencies")
        references = [(ref.trial_id, ref.criterion_id) for ref in self.targets]
        if len(references) != len(set(references)):
            raise ValueError("Duplicate target references")
        return self


class Portfolio(ResearchModel):
    portfolio_id: Identifier
    patient: SyntheticPatient
    trials: list[TrialProtocol] = Field(min_length=1)
    candidates: list[EvidenceReview]
    cost_unit: Identifier
    outcome_model: Literal["independent_review_outcomes"]
    assumptions: list[Identifier] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_portfolio(self) -> "Portfolio":
        trials = {trial.trial_id: trial for trial in self.trials}
        actions = {action.item_id: action for action in self.candidates}
        if len(trials) != len(self.trials) or len(actions) != len(self.candidates):
            raise ValueError("Trial and review IDs must be unique")
        known = set()
        bindings = {}

        def collect(trial_id, node):
            known.add((trial_id, node.criterion_id))
            for child in node.dependencies or []:
                collect(trial_id, child)

        for trial in self.trials:
            for node in trial.criteria_set.criteria:
                collect(trial.trial_id, node)
            identifiers = [binding.criterion.criterion_id for binding in trial.bindings]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError("Duplicate protocol bindings")
            for binding in trial.bindings:
                key = (trial.trial_id, binding.criterion.criterion_id)
                if key not in known:
                    raise ValueError("Unknown protocol binding")
                bindings[key] = binding
        if len({trial.context.as_of for trial in self.trials}) != 1:
            raise ValueError("Protocols require a common assessment time")
        baseline = {item.evidence_id: item for item in self.patient.evidence}
        additions = {}
        removals = {}
        for action in self.candidates:
            targets = {(ref.trial_id, ref.criterion_id) for ref in action.targets}
            if not targets <= known:
                raise ValueError("Unknown criterion target")
            if set(action.depends_on) - set(actions):
                raise ValueError("Unknown review dependency")
            attributes = set()
            for outcome in action.outcomes:
                for item in outcome.additions:
                    if item.evidence_id in baseline:
                        raise ValueError("Review cannot overwrite original evidence")
                    owner = additions.setdefault(item.evidence_id, action.item_id)
                    if owner != action.item_id:
                        raise ValueError("Reviews cannot share added evidence IDs")
                    attributes.add(item.clinical_attribute)
                for retraction in outcome.retractions:
                    if retraction.evidence_id not in baseline:
                        raise ValueError("Retractions must reference original evidence")
                    owner = removals.setdefault(retraction.evidence_id, action.item_id)
                    if owner != action.item_id:
                        raise ValueError("Overlapping review retractions are unsupported")
                    attributes.add(baseline[retraction.evidence_id].clinical_attribute)
            required = {key for key, binding in bindings.items()
                        if binding.clinical_attribute in attributes}
            if not required <= targets:
                raise ValueError("Targets must include every affected attribute binding")
        visited, active = set(), set()

        def visit(identifier):
            if identifier in active:
                raise ValueError("Cyclic review dependencies")
            if identifier in visited:
                return
            active.add(identifier)
            for dependency in actions[identifier].depends_on:
                visit(dependency)
            active.remove(identifier)
            visited.add(identifier)

        for identifier in actions:
            visit(identifier)
        return self


class TrialDecision(ResearchModel):
    trial_id: Identifier
    decision: Literal["unresolved", "observed_blocker", "constraints_consistent"]
    assessment: TrialAssessment
    unresolved_criterion_ids: list[str]
    blocker_criterion_ids: list[str]


class PortfolioAssessment(ResearchModel):
    uncertainty: Fraction
    decisions: list[TrialDecision]


class ExperimentConfig(ResearchModel):
    seed: StrictInt = Field(default=7, ge=0)
    budget: Decimal = Field(default=Decimal(2), ge=0)
    max_scenarios: StrictInt = Field(default=512, gt=0)
    selection_policy: Literal["greedy_prerequisite_bundles"] = "greedy_prerequisite_bundles"
    stopping_rule: Literal["until_no_feasible_bundle"] = "until_no_feasible_bundle"
