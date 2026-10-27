import json
import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.criteria import TrialCriteriaSet, TrialCriterion
from backend.app.extraction_prompt import CLINICAL_FIELDS, SPAN_FIELDS
from backend.app.extraction_source import EligibilitySource


class Span(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(gt=0)]


class CriterionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criterion_id: str
    original_span: Span
    polarity_span: Span
    fields: dict[str, Span]


class ExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criteria: list[dict]
    evidence: list[CriterionEvidence]


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def logical_tree(tokens: list[str]):
    position = 0

    def expression(operator, operand):
        nonlocal position
        nodes = [operand()]
        while position < len(tokens) and tokens[position] == operator:
            position += 1
            nodes.append(operand())
        return nodes[0] if len(nodes) == 1 else (operator, tuple(nodes))

    def atom():
        nonlocal position
        if position >= len(tokens):
            raise ValueError("Missing logical operand")
        token = tokens[position]
        position += 1
        if token == "(":
            node = expression("OR", conjunction)
            if position >= len(tokens) or tokens[position] != ")":
                raise ValueError("Unbalanced grouping")
            position += 1
            return node
        if not re.fullmatch(r"x\d+", token):
            raise ValueError("Unsupported logical text")
        return token

    def conjunction():
        return expression("AND", atom)

    tree = expression("OR", conjunction)
    if position != len(tokens):
        raise ValueError("Unsupported logical text")
    return tree


def validate_extraction(
    content: str, source: EligibilitySource, *, method: str, timestamp: str,
) -> tuple[TrialCriteriaSet | None, list[dict]]:
    errors = []

    def report(code, criterion_id=None, field=None):
        errors.append({"code": code, "criterion_id": criterion_id, "field": field})

    try:
        payload = ExtractionResponse.model_validate(json.loads(content, object_pairs_hook=unique_object))
        if len({item.criterion_id for item in payload.evidence}) != len(payload.evidence):
            raise ValueError("Duplicate evidence")

        def convert(node):
            if not isinstance(node, dict) or set(node) != set(CLINICAL_FIELDS):
                raise ValueError("Missing or unexpected criterion fields")
            data = dict(node)
            if data["dependencies"] is not None:
                if not isinstance(data["dependencies"], list):
                    raise ValueError("Invalid dependencies")
                data["dependencies"] = [convert(child) for child in data["dependencies"]]
            return TrialCriterion.model_validate(dict(
                data, nct_id=source.nct_id, source_url=source.source_url,
                extraction_method=method, extraction_timestamp=timestamp,
            ))

        criteria_set = TrialCriteriaSet(
            criteria=[convert(node) for node in payload.criteria],
            nct_id=source.nct_id, original_text=source.text, source_url=source.source_url,
            source_snapshot=source.source_snapshot, retrieval_timestamp=source.retrieval_timestamp,
            is_synthetic=source.is_synthetic,
        )
    except (ValueError, TypeError, RecursionError) as error:
        if isinstance(error, ValidationError):
            for item in error.errors(include_input=False, include_context=False, include_url=False):
                report("schema_error", field=".".join(str(part) for part in item["loc"]))
        else:
            report("invalid_json_or_schema")
        return None, errors

    evidence = {item.criterion_id: item for item in payload.evidence}
    used = set()
    headings = list(re.finditer(
        r"^[ \t]*(?:#+[ \t]*)?(Inclusion|Exclusion)(?:[ \t]+Criteria)?[ \t]*:?[ \t]*$",
        source.text, re.MULTILINE | re.IGNORECASE,
    ))

    def exact(span, text):
        return span.start < span.end <= len(source.text) and source.text[span.start:span.end] == text

    def visit(node, parent_span=None, inherited_cohort=None, cohort_span=None):
        used.add(node.criterion_id)
        entry = evidence.get(node.criterion_id)
        if entry is None:
            report("missing_evidence", node.criterion_id)
            return
        span = entry.original_span
        if not exact(span, node.original_text):
            report("unsupported_original_text", node.criterion_id)
            return
        if parent_span and not (parent_span.start <= span.start < span.end <= parent_span.end):
            report("dependency_outside_parent", node.criterion_id)
        if inherited_cohort and node.cohort != inherited_cohort:
            report("lost_cohort_scope", node.criterion_id)
        preceding = [heading for heading in headings if heading.end() <= span.start]
        heading = preceding[-1] if preceding else None
        if (heading is None or node.criterion_type != heading.group(1).lower()
                or entry.polarity_span.start != heading.start()
                or entry.polarity_span.end != heading.end()):
            report("unsupported_polarity", node.criterion_id)
        if any(span.start <= heading.start() < span.end for heading in headings):
            report("crosses_section_boundary", node.criterion_id)
        expected_fields = {field for field in SPAN_FIELDS if getattr(node, field) is not None}
        if set(entry.fields) != expected_fields:
            report("field_evidence_mismatch", node.criterion_id)
        for field in expected_fields:
            supporting = entry.fields.get(field)
            if supporting is None:
                continue
            within = span.start <= supporting.start < supporting.end <= span.end
            inherited = field == "cohort" and node.cohort == inherited_cohort and supporting == cohort_span
            if not exact(supporting, getattr(node, field)) or not (within or inherited):
                report("unsupported_field", node.criterion_id, field)
            if field == "threshold":
                before = source.text[supporting.start - 1:supporting.start] if supporting.start else ""
                after = source.text[supporting.end:supporting.end + 1]
                if re.search(r"[\d.]$", before) or re.match(r"[\d.]", after):
                    report("partial_numeric_threshold", node.criterion_id, field)
            if field == "comparator":
                adjacent = (source.text[supporting.start - 1:supporting.start] if supporting.start else "")
                adjacent += source.text[supporting.end:supporting.end + 1]
                if any(character in "<>=≤≥" for character in adjacent):
                    report("partial_comparator", node.criterion_id, field)
        children = node.dependencies or []
        child_spans = [evidence[child.criterion_id].original_span
                       for child in children if child.criterion_id in evidence]
        if len(child_spans) != len(children):
            report("missing_dependency_evidence", node.criterion_id)
        elif children:
            cursor = span.start
            skeleton = ""
            for index, child_span in enumerate(child_spans):
                if not cursor <= child_span.start < child_span.end <= span.end:
                    report("overlapping_or_unordered_operands", node.criterion_id)
                    break
                skeleton += source.text[cursor:child_span.start] + f" x{index} "
                cursor = child_span.end
            else:
                skeleton += source.text[cursor:span.end]
                if node.cohort and skeleton.startswith(node.cohort + ":"):
                    skeleton = skeleton[len(node.cohort) + 1:]
                skeleton = re.sub(r"^\s*[-*•]\s*", "", skeleton)
                tokens = re.findall(r"x\d+|\bAND\b|\bOR\b|[()]|\S+", skeleton, re.IGNORECASE)
                tokens = [token.upper() if token.lower() in ("and", "or") else token for token in tokens]
                try:
                    expected = (node.logical_operator, tuple(f"x{i}" for i in range(len(children))))
                    if logical_tree(tokens) != expected:
                        raise ValueError
                except ValueError:
                    report("unsupported_logical_structure", node.criterion_id)
        elif re.search(r"\b(and|or)\b", node.original_text, re.IGNORECASE):
            report("unresolved_compound_logic", node.criterion_id)
        if re.search(r"\b(except|unless|otherwise|provided that|if|either)\b", node.original_text, re.IGNORECASE):
            report("unsupported_conditional_or_exception", node.criterion_id)
        if node.logical_operator is None:
            report("unresolved_logical_operator", node.criterion_id)
        for child in children:
            visit(child, span, node.cohort or inherited_cohort, entry.fields.get("cohort", cohort_span))

    top_spans = []
    for node in criteria_set.criteria:
        visit(node)
        if node.criterion_id in evidence:
            span = evidence[node.criterion_id].original_span
            if not 0 <= span.start < span.end <= len(source.text):
                continue
            top_spans.append(span)
            if ((span.start and source.text[span.start - 1] != "\n")
                    or (span.end < len(source.text) and source.text[span.end] != "\n")):
                report("partial_top_level_line", node.criterion_id)
    top_spans.sort(key=lambda span: span.start)
    if any(first.end > second.start for first, second in zip(top_spans, top_spans[1:])):
        report("overlapping_top_level_criteria")
    for index, character in enumerate(source.text):
        if (not character.isspace()
                and not any(heading.start() <= index < heading.end() for heading in headings)
                and not any(span.start <= index < span.end for span in top_spans)):
            report("uncovered_source_text")
            break
    if set(evidence) != used:
        report("unexpected_evidence")
    return (None if errors else criteria_set), errors
