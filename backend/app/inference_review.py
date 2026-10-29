import hashlib
import json
import os
import re
from decimal import DecimalException
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from backend.app import extraction, research_api
from backend.app.assessment_models import CriterionBinding
from backend.app.assessment_values import COMPARATORS, UNITS, number
from backend.app.extraction_source import ROOT
from backend.app.extraction_validation import validate_extraction
from backend.app.inference_access import operator_status, require_operator
from backend.app.trial_extraction import extraction_report
from backend.app.trial_extraction_api import select_source

router = APIRouter(prefix='/saved-trials', tags=['operator extraction review'])
REVIEWS = ROOT / 'data/mapping-reviews'


@router.get('/{nct_id}/authorization-quote')
def authorization_quote(nct_id: str = Path(pattern=r'^NCT\d{8}$'), snapshot: str | None = Query(default=None, max_length=200), authorization: str | None = Header(default=None)):
    require_operator(authorization)
    from backend.extraction_authorization import quote_source, scope_digest
    from backend.app.nebius import NebiusError
    selected = select_source(nct_id, snapshot)
    try:
        quote = quote_source(selected)
    except NebiusError:
        raise HTTPException(409, 'Source quote unavailable. Check model, pricing and input limits.') from None
    return {'quote': quote, 'scope_sha256': scope_digest(quote), 'authorization_created': False, 'request_consumed': False}


def report_for(nct_id, attempt):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', attempt):
        raise HTTPException(422, 'Invalid extraction selection.')
    directory = (extraction.RESULTS_DIR / attempt).resolve()
    if not directory.is_relative_to(extraction.RESULTS_DIR.resolve()):
        raise HTTPException(422, 'Invalid extraction selection.')
    try:
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
        if manifest['nct_id'] != nct_id:
            raise HTTPException(409, 'Extraction belongs to a different trial.')
        snapshot = (ROOT / manifest['source_snapshot']).resolve().relative_to(research_api.RAW_TRIALS_DIR.resolve()).as_posix()
        source = select_source(nct_id, snapshot)
        report = extraction_report(source, directory, persist=False)
        candidate = report['candidate']
        model, errors = validate_extraction(json.dumps(candidate), source, method='saved-output-review', timestamp=manifest['timestamp']) if candidate is not None else (None, report['validation_errors'])
        report['validated'] = model.model_dump(mode='json') if model and not errors else None
        report['validation_errors'] = errors
        report['review_checks_passed'] = model is not None and not errors and manifest['status'] == 'validated'
        fingerprint = hashlib.sha256((directory / 'manifest.json').read_bytes() + (directory / 'raw_response.json').read_bytes()).hexdigest()
        report['attempt_sha256'] = fingerprint
        secret = os.environ.get('NEBIUS_API_KEY', '').strip()
        if secret and secret in json.dumps(report, ensure_ascii=False):
            raise HTTPException(409, 'Saved output requires privacy review and cannot be displayed.')
        return source, report, model
    except FileNotFoundError:
        raise HTTPException(404, 'Saved extraction is unavailable.') from None
    except (OSError, ValueError, TypeError, KeyError):
        raise HTTPException(409, 'Saved extraction failed source or structure checks.') from None


def nodes(criteria):
    for node in criteria:
        yield node
        yield from nodes(node.dependencies or [])


def supported_binding(binding):
    criterion = binding.criterion
    if criterion.criterion_type is None or criterion.logical_operator is None:
        raise ValueError('Unresolved inclusion/exclusion or Boolean logic requires correction.')
    if criterion.dependencies:
        if any(getattr(criterion, key) is not None for key in ('biomarker', 'assay', 'comparator', 'threshold', 'unit', 'temporal_constraint')) or any((binding.clinical_attribute, binding.value_type, binding.categories, binding.temporal_rule)):
            raise ValueError('Compound rules cannot have atomic execution qualifiers.')
        return
    if not binding.clinical_attribute or not binding.value_type or criterion.comparator not in COMPARATORS or criterion.threshold is None:
        raise ValueError('A supported attribute, value type and source-grounded comparison are required.')
    if criterion.biomarker and binding.clinical_attribute != criterion.biomarker:
        raise ValueError('The mapped attribute must match the source-grounded biomarker.')
    if criterion.temporal_constraint or binding.temporal_rule or binding.value_type == 'elapsed_days':
        raise ValueError('Temporal mappings are not enabled in this review; they require an explicitly reviewed temporal rule.')
    if binding.value_type == 'categorical':
        if criterion.comparator not in ('==', '!=') or criterion.unit is not None or not binding.categories or criterion.threshold not in binding.categories:
            raise ValueError('Categorical rules need a supported comparison and an explicit category domain.')
    else:
        if binding.categories is not None or criterion.unit not in UNITS:
            raise ValueError('Numeric units or category domain are unsupported.')
        try:
            number(criterion.threshold)
        except (ValueError, DecimalException):
            raise ValueError('The source threshold is not a supported numeric value.') from None


class MappingReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    snapshot_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    attempt_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    criterion_id: str = Field(min_length=1, max_length=200)
    decision: Literal['approve', 'reject']
    reviewer: str = Field(min_length=1, max_length=100)
    note: str = Field(min_length=1, max_length=2000)
    semantics_reviewed: bool = False
    clinical_attribute: str | None = Field(default=None, max_length=150)
    value_type: Literal['numeric', 'categorical'] | None = None
    categories: list[str] | None = Field(default=None, max_length=100)


def saved_reviews(source, attempt, fingerprint):
    result = {}
    for path in sorted((REVIEWS / source.nct_id / attempt).glob('*.json')):
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            if record['snapshot_sha256'] == source.sha256 and record['attempt_sha256'] == fingerprint:
                previous = result.get(record['criterion_id'])
                if not previous or record['reviewed_at'] > previous['reviewed_at']:
                    result[record['criterion_id']] = record
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return result


@router.get('/{nct_id}/inference')
def status(nct_id: str = Path(pattern=r'^NCT\d{8}$'), snapshot: str | None = Query(default=None, max_length=200), authorization: str | None = Header(default=None)):
    require_operator(authorization)
    source = select_source(nct_id, snapshot)
    attempts = []
    for path in sorted(extraction.RESULTS_DIR.glob('*/manifest.json')):
        try:
            manifest = json.loads(path.read_text(encoding='utf-8'))
            if (manifest.get('nct_id'), manifest.get('snapshot_sha256'), manifest.get('source_snapshot')) == (nct_id, source.sha256, source.source_snapshot):
                attempts.append({'id': path.parent.name, 'mode': manifest.get('mode'), 'status': manifest.get('status'), 'timestamp': manifest.get('timestamp')})
        except (OSError, ValueError, TypeError):
            continue
    return {'configuration': operator_status(source), 'attempts': attempts, 'snapshot_sha256': source.sha256,
            'assessment_available': False, 'assessment_reason': 'No authorized real-patient evidence adapter is configured. Operator-approved mappings alone do not permit a patient assessment.'}


@router.get('/{nct_id}/inference/{attempt}')
def inspect(nct_id: str, attempt: str, authorization: str | None = Header(default=None)):
    require_operator(authorization)
    source, report, _ = report_for(nct_id, attempt)
    reviews = saved_reviews(source, attempt, report['attempt_sha256'])
    report['mapping_reviews'] = {key: {'decision': value['decision'], 'reviewed_at': value['reviewed_at']} for key, value in reviews.items()}
    report['assessment_allowed'] = False
    return report


@router.get('/{nct_id}/inference/{attempt}/bindings')
def approved_bindings(nct_id: str, attempt: str, authorization: str | None = Header(default=None)):
    require_operator(authorization)
    source, report, model = report_for(nct_id, attempt)
    approved = []
    if report['review_checks_passed'] and model is not None:
        criteria = {node.criterion_id: node for node in nodes(model.criteria)}
        for identifier, record in saved_reviews(source, attempt, report['attempt_sha256']).items():
            if record.get('decision') != 'approve' or record.get('semantics_reviewed') is not True:
                continue
            try:
                binding = CriterionBinding.model_validate(record['binding'])
                if not binding.verified or binding.criterion != criteria.get(identifier):
                    continue
                supported_binding(binding)
                approved.append(binding.model_dump(mode='json'))
            except (ValueError, KeyError, TypeError):
                continue
    return {'bindings': approved, 'assessment_available': False,
            'scope': 'Supported operator-approved research bindings only. Missing or rejected dependencies remain unresolved in the existing engine. No authorized real-patient evidence adapter is configured.'}


@router.post('/{nct_id}/inference/{attempt}/reviews')
def review_mapping(nct_id: str, attempt: str, request: MappingReview, authorization: str | None = Header(default=None)):
    require_operator(authorization)
    source, report, model = report_for(nct_id, attempt)
    if request.snapshot_sha256 != source.sha256 or request.attempt_sha256 != report['attempt_sha256']:
        raise HTTPException(409, 'The source or extraction changed. Reload it before reviewing.')
    if not request.reviewer.strip() or not request.note.strip():
        raise HTTPException(422, 'Reviewer and review note are required.')
    binding = None
    if request.decision == 'approve':
        if not request.semantics_reviewed or not report['review_checks_passed'] or model is None:
            raise HTTPException(409, 'Approval requires passing source/structure checks and explicit semantic review. Source alignment alone is insufficient.')
        node = next((node for node in nodes(model.criteria) if node.criterion_id == request.criterion_id), None)
        if node is None:
            raise HTTPException(422, 'Criterion not found in the validated extraction.')
        try:
            binding = CriterionBinding(criterion=node, verified=True, provenance=f'operator-review:{attempt}:{report["attempt_sha256"]}',
                clinical_attribute=request.clinical_attribute, value_type=request.value_type, categories=request.categories)
            supported_binding(binding)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
    else:
        def identifiers(items):
            for item in items:
                if isinstance(item, dict):
                    yield item.get('criterion_id')
                    yield from identifiers(item.get('dependencies') or [])
        candidate = report['candidate'] if isinstance(report['candidate'], dict) else {}
        if list(identifiers(candidate.get('criteria', []))).count(request.criterion_id) != 1:
            raise HTTPException(422, 'Criterion not found in this extraction.')
    record = {**request.model_dump(), 'reviewed_at': datetime.now(timezone.utc).isoformat(),
              'nct_id': nct_id, 'binding': binding.model_dump(mode='json') if binding else None,
              'assessment_allowed': False}
    directory = REVIEWS / source.nct_id / attempt
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f'{uuid4().hex}.json').open('x', encoding='utf-8') as file:
        json.dump(record, file, ensure_ascii=False, indent=2)
    return {'decision': request.decision, 'criterion_id': request.criterion_id, 'binding_approved': binding is not None,
            'assessment_allowed': False, 'message': 'Review saved. This is an operator research review, not independent clinical verification. Patient assessment remains unavailable.'}
