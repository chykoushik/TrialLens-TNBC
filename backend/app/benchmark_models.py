from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.extraction_validation import Span

ANNOTATION_VERSION = "eligibility-reference-v1"
T = TypeVar("T")


class ReferenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Quote(ReferenceModel):
    span: Span
    text: str = Field(min_length=1)


class Review(ReferenceModel):
    status: Literal["unreviewed", "uncertain", "reviewed"] = "unreviewed"
    reviewer: str | None = None
    reviewed_at: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def reviewed_identity(self):
        if self.status == "reviewed":
            if not self.reviewer or not self.reviewer.strip() or not self.reviewed_at:
                raise ValueError("Reviewed labels require reviewer and timestamp")
            timestamp = datetime.fromisoformat(self.reviewed_at.replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("Review timestamp requires timezone")
        return self


class Label(ReferenceModel, Generic[T]):
    review: Review = Field(default_factory=Review)
    value: T | None = None
    evidence: list[Quote] = Field(default_factory=list)


class Logic(ReferenceModel):
    operator: Literal["AND", "OR", "NONE"]
    span: Span
    children: list["Logic"] = Field(default_factory=list)

    @model_validator(mode="after")
    def operands(self):
        if self.operator == "NONE" and self.children:
            raise ValueError("Atomic logic cannot have operands")
        if self.operator != "NONE" and len(self.children) < 2:
            raise ValueError("Compound logic requires operands")
        previous = self.span.start
        for child in self.children:
            if not previous <= child.span.start < child.span.end <= self.span.end:
                raise ValueError("Logic operands must be ordered and contained")
            previous = child.span.end
        return self


class ReferenceCriterion(ReferenceModel):
    reference_id: str = Field(min_length=1)
    boundary_review: Review = Field(default_factory=Review)
    original: Quote
    polarity: Label[Literal["inclusion", "exclusion"]] = Field(default_factory=Label)
    threshold_operator: Label[str] = Field(default_factory=Label)
    threshold_value: Label[str] = Field(default_factory=Label)
    unit: Label[str] = Field(default_factory=Label)
    temporal_constraint: Label[str] = Field(default_factory=Label)
    cohort: Label[str] = Field(default_factory=Label)
    biomarker: Label[str] = Field(default_factory=Label)
    assay: Label[str] = Field(default_factory=Label)
    logic: Label[Logic] = Field(default_factory=Label)
    exceptions: Label[list[str]] = Field(default_factory=Label)
    unsupported_semantics: Label[bool] = Field(default_factory=Label)
    dependencies: list["ReferenceCriterion"] = Field(default_factory=list)


SLOTS = tuple(name for name in ReferenceCriterion.model_fields
              if name not in ("reference_id", "boundary_review", "original", "dependencies"))


class ReferenceAnnotation(ReferenceModel):
    annotation_version: Literal["eligibility-reference-v1"] = ANNOTATION_VERSION
    annotation_revision: int = Field(default=1, ge=1)
    nct_id: str = Field(pattern=r"^NCT\d{8}$")
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    annotation_origin: Literal["manual", "software_test_fixture"] = "manual"
    inventory_review: Review = Field(default_factory=Review)
    criteria: list[ReferenceCriterion] = Field(default_factory=list)


def validate_reference(annotation, text, *, allow_test_fixture=False):
    if annotation.annotation_origin == "software_test_fixture" and not allow_test_fixture:
        raise ValueError("Software fixtures cannot be clinical references")
    identifiers, spans = set(), []
    def visit(criterion, parent=None):
        if criterion.reference_id in identifiers:
            raise ValueError("Duplicate reference ID")
        identifiers.add(criterion.reference_id)
        original = criterion.original
        if not 0 <= original.span.start < original.span.end <= len(text):
            raise ValueError("Reference span outside source")
        if text[original.span.start:original.span.end] != original.text:
            raise ValueError("Reference text differs from source")
        if parent is not None and not (parent.start <= original.span.start < original.span.end <= parent.end):
            raise ValueError("Dependency outside reference parent")
        if parent is None:
            spans.append((original.span.start, original.span.end))
        if parent is None and annotation.inventory_review.status == "reviewed" and criterion.boundary_review.status != "reviewed":
            raise ValueError("Complete inventory requires reviewed boundaries")
        for name in SLOTS:
            label = getattr(criterion, name)
            for quote in label.evidence:
                if not 0 <= quote.span.start < quote.span.end <= len(text):
                    raise ValueError("Evidence outside source")
                if text[quote.span.start:quote.span.end] != quote.text:
                    raise ValueError("Evidence differs from source")
            if label.review.status != "reviewed":
                continue
            if label.value is None and not label.review.note:
                raise ValueError("Reviewed absence requires explanation")
            if name == "unsupported_semantics" and label.value is None:
                raise ValueError("Reviewed support status must be explicit")
            if label.value is not None and not label.evidence:
                raise ValueError("Reviewed values require source evidence")
            if name not in ("polarity", "logic", "unsupported_semantics"):
                values = label.value if isinstance(label.value, list) else [label.value]
                if any(value is not None and not any(value == q.text for q in label.evidence) for value in values):
                    raise ValueError("Reviewed values must be verbatim evidence")
            if name == "unsupported_semantics" and label.value is True and not label.review.note:
                raise ValueError("Unsupported semantics require explanation")
            if name == "logic" and label.value is not None:
                if label.value.span != original.span:
                    raise ValueError("Logic root must cover criterion")
        children = sorted(criterion.dependencies, key=lambda child: child.original.span.start)
        if any(a.original.span.end > b.original.span.start for a, b in zip(children, children[1:])):
            raise ValueError("Reference dependencies overlap")
        for child in criterion.dependencies:
            visit(child, original.span)
    for criterion in annotation.criteria:
        visit(criterion)
    spans.sort()
    if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
        raise ValueError("Top-level reference criteria overlap")
