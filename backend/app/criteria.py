from enum import Enum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, pattern=r"\S")]


class TrialCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: Identifier
    original_text: Annotated[str, Field(min_length=1, pattern=r"\S")]
    nct_id: Identifier | None = None
    criterion_type: Literal["inclusion", "exclusion"] | None = None
    cohort: str | None = None
    logical_operator: Literal["AND", "OR", "NONE"] | None = None
    dependencies: list["TrialCriterion"] | None = None
    biomarker: str | None = None
    assay: str | None = None
    comparator: str | None = None
    threshold: str | None = None
    unit: str | None = None
    temporal_constraint: str | None = None
    source_url: str | None = None
    extraction_method: str | None = None
    extraction_timestamp: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_dependencies(self) -> "TrialCriterion":
        if self.logical_operator in ("AND", "OR"):
            if not self.dependencies or len(self.dependencies) < 2:
                raise ValueError("AND/OR requires at least two operands")
        elif self.dependencies:
            raise ValueError("Dependencies require an AND/OR operator")
        def visit(child: "TrialCriterion", nct_id: str | None, polarity: str | None) -> None:
            if nct_id and child.nct_id and nct_id != child.nct_id:
                raise ValueError("Dependencies must belong to the same trial")
            if polarity and child.criterion_type and polarity != child.criterion_type:
                raise ValueError("Dependencies must preserve criterion polarity")
            for dependency in child.dependencies or []:
                visit(dependency, child.nct_id or nct_id, child.criterion_type or polarity)

        for child in self.dependencies or []:
            visit(child, self.nct_id, self.criterion_type)
        return self


class TrialCriteriaSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria: list[TrialCriterion]
    nct_id: Identifier | None = None
    original_text: str | None = None
    source_url: str | None = None
    source_snapshot: str | None = None
    retrieval_timestamp: AwareDatetime | None = None
    is_synthetic: bool | None = None

    @model_validator(mode="after")
    def validate_criteria(self) -> "TrialCriteriaSet":
        identifiers = set()

        def visit(criterion: TrialCriterion) -> None:
            if criterion.criterion_id in identifiers:
                raise ValueError("Criterion IDs must be unique within a set")
            identifiers.add(criterion.criterion_id)
            if self.nct_id and criterion.nct_id and criterion.nct_id != self.nct_id:
                raise ValueError("Criteria must belong to the grouped trial")
            for dependency in criterion.dependencies or []:
                visit(dependency)

        for criterion in self.criteria:
            visit(criterion)
        return self


class AssessmentState(str, Enum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    UNKNOWN = "unknown"
    TEMPORAL = "temporal"
    CONFLICT = "conflict"


class CriterionAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: Identifier
    state: AssessmentState
    evidence_ids: list[Identifier] | None = None
    explanation: str | None = None
    assessment_timestamp: AwareDatetime | None = None
