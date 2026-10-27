import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from backend.app import nebius
from backend.app.extraction_prompt import build_messages
from backend.app.extraction_source import EligibilitySource
from backend.app.extraction_validation import validate_extraction

router = APIRouter(prefix='/inference', tags=['optional operator-only inference'])
SOURCE_ID = 'fictional-protocol-v1'
SOURCE_TEXT = 'Inclusion Criteria:\nAge >=18 years.\nExclusion Criteria:\nPrior PARP inhibitor treatment.'
SOURCE = EligibilitySource(nct_id='NCT00000000', text=SOURCE_TEXT,
    source_url='synthetic://triallens/fictional-protocol-v1', source_snapshot=SOURCE_ID,
    retrieval_timestamp=None, is_synthetic=True, sha256=hashlib.sha256(SOURCE_TEXT.encode()).hexdigest())
OUTPUT_CAP = 8192
APPROVAL_SECONDS = 300


def enabled():
    return os.environ.get('TRIALLENS_LIVE_INFERENCE') == '1' and os.environ.get('NEBIUS_LIVE_EXTRACTION') == '1'


@dataclass
class Context:
    config: nebius.NebiusConfig
    token: str = field(repr=False)
    state: Path


def context(request: Request):
    if not enabled():
        raise HTTPException(404, 'Live inference disabled')
    token = os.environ.get('TRIALLENS_LIVE_OPERATOR_TOKEN', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', token):
        raise HTTPException(503, 'Live inference configuration unavailable')
    authorization = request.headers.get('Authorization', '')
    expected = 'Bearer '+token
    if not secrets.compare_digest(authorization.encode(), expected.encode()):
        raise HTTPException(401, 'Operator authorization required', headers={'WWW-Authenticate': 'Bearer'})
    try:
        config = nebius.NebiusConfig.from_environment()
        if config.model != nebius.DEFAULT_MODEL or config.timeout_seconds > 120 or config.api_key == token:
            raise ValueError
        state = Path(os.environ.get('TRIALLENS_LIVE_STATE_DIR', ''))
        if not state.is_absolute() or state == Path(state.anchor):
            raise ValueError
    except (nebius.NebiusError, ValueError, OSError):
        raise HTTPException(503, 'Live inference configuration unavailable') from None
    return Context(config, token, state)


class PrepareRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    source_id: Literal['fictional-protocol-v1']


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    approval: str = Field(min_length=1, max_length=2048)
    confirm_paid_request: StrictBool

    @field_validator('confirm_paid_request')
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError('Explicit paid-request confirmation required')
        return value


def fingerprint(ctx):
    payload = nebius.build_chat_payload(build_messages(SOURCE), model=ctx.config.model,
                                       max_tokens=OUTPUT_CAP, non_reasoning=True)
    value = [SOURCE_ID, SOURCE.sha256, payload, ctx.config.base_url, ctx.config.timeout_seconds,
             hashlib.sha256(ctx.config.api_key.encode()).hexdigest(), str(ctx.state)]
    return hashlib.sha256(json.dumps(value, separators=(',', ':')).encode()).hexdigest()


def signature(encoded, ctx):
    return hmac.new(ctx.token.encode(), ('triallens-approval-v1:'+encoded).encode(), hashlib.sha256).hexdigest()


def approval(ctx):
    issued = int(time.time())
    value = dict(issued=issued, expires=issued+APPROVAL_SECONDS, nonce=secrets.token_hex(16), fingerprint=fingerprint(ctx))
    encoded = base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).decode().rstrip('=')
    return encoded+'.'+signature(encoded, ctx), value['expires']


def check_approval(value, ctx):
    try:
        encoded, signed = value.split('.')
        if not secrets.compare_digest(signed, signature(encoded, ctx)):
            raise ValueError
        payload = json.loads(base64.b64decode(encoded+'='*(-len(encoded) % 4), altchars=b'-_', validate=True))
        if set(payload) != {'issued', 'expires', 'nonce', 'fingerprint'}:
            raise ValueError
        if type(payload['issued']) is not int or type(payload['expires']) is not int:
            raise ValueError
        if not payload['issued'] <= time.time() < payload['expires'] or payload['expires']-payload['issued'] != APPROVAL_SECONDS:
            raise ValueError
        if payload['fingerprint'] != fingerprint(ctx) or not re.fullmatch('[a-f0-9]{32}', payload['nonce']):
            raise ValueError
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise HTTPException(409, 'Approval invalid, expired or configuration changed') from None


def claim_path(ctx):
    return ctx.state/'request.claim'


def reserve(ctx):
    try:
        ctx.state.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        raise HTTPException(503, 'Live reservation storage unavailable; no provider request sent') from None
    try:
        descriptor = os.open(claim_path(ctx), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(dict(reserved_at=datetime.now(timezone.utc).isoformat(), source_sha256=SOURCE.sha256), stream)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise HTTPException(409, 'One-request reservation already consumed; no retry was sent') from None
    except OSError:
        raise HTTPException(503, 'Live reservation storage unavailable; no provider request sent') from None


def reject_secret_echo(response, ctx, proposal=None):
    texts = [response.get('content', ''), response.get('raw_response', '')]
    for text in list(texts):
        try:
            texts.append(json.dumps(json.loads(text), ensure_ascii=False))
        except (ValueError, TypeError, RecursionError):
            pass
    if proposal is not None:
        texts.append(json.dumps(proposal, ensure_ascii=False))
    if any(secret in text for secret in (ctx.config.api_key, ctx.token) for text in texts):
        raise HTTPException(502, 'Provider response withheld for credential protection')


@router.get('/status')
def status(ctx: Context = Depends(context)):
    try:
        consumed = claim_path(ctx).exists()
    except OSError:
        raise HTTPException(503, 'Live reservation storage unavailable') from None
    return dict(enabled=True, model=nebius.DEFAULT_MODEL, source_id=SOURCE_ID, input_is_synthetic=True,
                reservation_consumed=consumed, request_limit=1, automatic_retries=0)


@router.post('/prepare')
def prepare(request: PrepareRequest, ctx: Context = Depends(context)):
    if status(ctx)['reservation_consumed']:
        raise HTTPException(409, 'One-request reservation already consumed')
    value, expires = approval(ctx)
    return dict(approval=value, expires_at=expires, source=asdict(SOURCE), model=nebius.DEFAULT_MODEL,
                max_output_tokens=OUTPUT_CAP, timeout_seconds=ctx.config.timeout_seconds, request_limit=1,
                charge_warning='Execution can incur provider charges. No price is assumed. Preview sends no provider request.')


@router.post('/execute')
def execute(request: ExecuteRequest, ctx: Context = Depends(context)):
    check_approval(request.approval, ctx)
    reserve(ctx)
    try:
        response = nebius.chat_completion(build_messages(SOURCE), config=ctx.config, max_tokens=OUTPUT_CAP, non_reasoning=True)
    except nebius.NebiusError as error:
        code = error.code if re.fullmatch('[a-z_]{1,80}', error.code) else 'provider_error'
        status_code = 504 if code == 'timeout' else 502
        raise HTTPException(status_code, dict(code=code, reservation_consumed=True, automatic_retries=0)) from None
    if len(response['content']) > 100000:
        raise HTTPException(502, 'Provider output exceeds response limit; reservation remains consumed')
    reject_secret_echo(response, ctx)
    proposal, errors = validate_extraction(response['content'], SOURCE, method='nebius-public-live',
                                           timestamp=datetime.now(timezone.utc).isoformat())
    result = proposal.model_dump(mode='json') if proposal is not None else None
    reject_secret_echo(response, ctx, result)
    codes = sorted({item['code'] for item in errors if re.fullmatch('[a-z_]{1,80}', item['code'])})
    return dict(inference_mode='live', provider='Nebius Token Factory', model=nebius.DEFAULT_MODEL,
                input_is_synthetic=True, source_id=SOURCE_ID, source_sha256=SOURCE.sha256,
                status='source_validated' if proposal is not None else 'validation_failed', proposal=result,
                validation_error_codes=codes, validation_scope='structural_and_source_only', human_review_required=True,
                assessment_allowed=False, fictional_demo_modified=False, reservation_consumed=True,
                usage=response.get('usage'), automatic_retries=0)
