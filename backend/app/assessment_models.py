from decimal import Decimal
from typing import Literal

from pydantic import (
    AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator,
)

from backend.app.criteria import CriterionAssessment, Identifier, TrialCriteriaSet, TrialCriterion


class EvidenceProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: Identifier
    reference: Identifier


class PatientEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    evidence_id: Identifier
    clinical_attribute: Identifier
    value: Decimal | str | None
    units: str | None = None
    assay: str | None = None
    observation_date: AwareDatetime | None = None
    specimen_context: str | None = None
    scoring_method: str | None = None
    availability: Literal["recorded", "unknown", "unavailable"] | None = None
    source: Identifier
    provenance: EvidenceProvenance

    @field_validator("value", mode="before")
    @classmethod
    def reject_boolean(cls, value):
        if isinstance(value, bool):
            raise ValueError("Boolean observations require explicit categorical labels")
        return value

    @model_validator(mode="after")
    def validate_availability(self) -> "PatientEvidence":
        if self.availability in ("unknown", "unavailable") and self.value is not None:
            raise ValueError("Unknown or unavailable evidence must have a null value")
        return self


class SyntheticPatient(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: Identifier
    is_synthetic: Literal[True]
    evidence: list[PatientEvidence]

    @field_validator("is_synthetic", mode="before")
    @classmethod
    def require_synthetic_label(cls, value):
        if value is not True:
            raise ValueError("Explicit synthetic label required")
        return value

    @model_validator(mode="after")
    def unique_evidence_ids(self) -> "SyntheticPatient":
        identifiers = [item.evidence_id for item in self.evidence]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Evidence IDs must be unique")
        return self


class TemporalRule(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    source_text: Identifier
    kind: Literal["freshness", "elapsed"]
    max_age_days: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_window(self) -> "TemporalRule":
        if self.kind == "freshness" and self.max_age_days is None:
            raise ValueError("Freshness requires an explicit source window")
        if self.kind == "elapsed" and self.max_age_days is not None:
            raise ValueError("Elapsed rules use the criterion threshold")
        return self


class CriterionBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion: TrialCriterion
    verified: StrictBool = False
    provenance: Identifier
    clinical_attribute: Identifier | None = None
    value_type: Literal["numeric", "categorical", "elapsed_days"] | None = None
    temporal_rule: TemporalRule | None = None
    categories: list[Identifier] | None = None

    @field_validator("criterion")
    @classmethod
    def preserve_criterion(cls, value: TrialCriterion) -> TrialCriterion:
        return value.model_copy(deep=True)


class AssessmentContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: AwareDatetime
    cohort: Identifier | None = None


class AssessedCriterion(CriterionAssessment):
    criterion: TrialCriterion
    binding: CriterionBinding | None
    evidence: list[PatientEvidence]
    dependencies: list["AssessedCriterion"]
    reason_code: str


class TrialAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine_version: Literal["five-state-v1"] = "five-state-v1"
    patient_id: Identifier
    is_synthetic: Literal[True]
    context: AssessmentContext
    criteria_set: TrialCriteriaSet
    assessments: list[AssessedCriterion]
