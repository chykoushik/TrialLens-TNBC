import argparse
import hashlib
import json
import re
import os
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from backend.app import nebius
from backend.app.extraction_source import ROOT, load_source
from backend.app.extraction_prompt import build_messages

AUTHORIZATIONS = ROOT / 'results/nebius/authorizations'
EXTRACTIONS = ROOT / 'results/extraction'


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scope_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def quote_source(source):
    rates = nebius.pricing()
    model = os.environ.get('NEBIUS_MODEL', '').strip()
    base = os.environ.get('NEBIUS_BASE_URL', nebius.BASE_URL).strip().rstrip('/')
    if rates is None or model != nebius.DEFAULT_MODEL or base not in (nebius.BASE_URL, nebius.REGIONAL_BASE_URL):
        raise nebius.NebiusError('authorization_configuration_required')
    messages = build_messages(source)
    if sum(len(message['content'].encode('utf-8')) + 256 for message in messages) > nebius.MAX_INPUT_TOKENS:
        raise nebius.NebiusError('input_limit_exceeded')
    bound = (Decimal(str(rates['input_usd_per_million'])) * nebius.MAX_INPUT_TOKENS
             + Decimal(str(rates['output_usd_per_million'])) * nebius.MAX_OUTPUT_TOKENS) / Decimal(1_000_000)
    return {'nct_id': source.nct_id, 'snapshot': source.source_snapshot, 'snapshot_sha256': source.sha256,
            'model': model, 'base_url': base, 'timeout_seconds': nebius.inference_timeout(),
            'prompt_sha256': scope_digest(messages), 'max_input_tokens': nebius.MAX_INPUT_TOKENS,
            'max_output_tokens': nebius.MAX_OUTPUT_TOKENS, 'pricing': rates,
            'maximum_estimated_cost_usd': str(bound), 'max_requests': 1, 'automatic_retries': 0}


def authorize_source(previous_attempt, source, maximum_cost, actor, note):
    if not actor.strip() or not note.strip():
        raise nebius.NebiusError('authorization_identity_required')
    anchor = inspect_attempt(previous_attempt)
    quote = quote_source(source)
    try:
        cap = Decimal(str(maximum_cost))
        server_cap = Decimal(os.environ.get('NEBIUS_MAX_REQUEST_USD', 'NaN'))
        if not cap.is_finite() or not server_cap.is_finite() or cap <= 0 or cap > server_cap or cap < Decimal(quote['maximum_estimated_cost_usd']):
            raise ValueError
    except (InvalidOperation, ValueError):
        raise nebius.NebiusError('authorization_cost_limit') from None
    identifier = uuid4().hex
    record = {'version': 3, 'authorization_id': identifier, 'request_id': identifier,
              'actor': actor.strip(), 'note': note.strip(), 'authorized_at': datetime.now(timezone.utc).isoformat(),
              'previous_attempt': anchor['previous_attempt'], 'audit_anchor': anchor,
              **quote, 'scope_sha256': scope_digest(quote), 'authorized_maximum_estimated_cost_usd': str(cap)}
    AUTHORIZATIONS.mkdir(parents=True, exist_ok=True)
    with (AUTHORIZATIONS / f'{identifier}.json').open('x', encoding='utf-8') as file:
        json.dump(record, file, indent=2)
    return identifier


def authorization_matches(record, source):
    if record.get('version') == 3:
        quote = quote_source(source)
        return (record['scope_sha256'] == scope_digest(quote)
                and all(record.get(key) == value for key, value in quote.items())
                and Decimal(quote['maximum_estimated_cost_usd']) <= Decimal(record['authorized_maximum_estimated_cost_usd']))
    return (record['nct_id'] == source.nct_id and record['snapshot'] == source.source_snapshot
            and record['snapshot_sha256'] == source.sha256 and record['model'] == nebius.DEFAULT_MODEL
            and record['timeout_seconds'] == nebius.inference_timeout())


def inspect_attempt(previous_attempt, _seen=frozenset()):
    path = (ROOT / previous_attempt).resolve()
    if not path.is_relative_to(EXTRACTIONS.resolve()) or path.name != 'manifest.json':
        raise nebius.NebiusError('invalid_previous_attempt')
    if path in _seen:
        raise nebius.NebiusError('authorization_chain_cycle')
    seen = _seen | {path}
    manifest = json.loads(path.read_text(encoding='utf-8'))
    errors_path = path.with_name('validation_errors.json')
    errors = json.loads(errors_path.read_text(encoding='utf-8'))
    if (manifest.get('mode') != 'live' or manifest.get('request_count') != 1
            or manifest.get('status') not in ('failed', 'validation_failed', 'validated', 'privacy_failed')
            or not nebius.LIVE_CLAIM.is_file()):
        raise nebius.NebiusError('invalid_previous_attempt')
    source = load_source(Path(manifest['source_snapshot']), manifest['nct_id'])
    if source.sha256 != manifest['snapshot_sha256']:
        raise nebius.NebiusError('source_identity_changed')
    parent = {}
    identifier = manifest.get('request_authorization_id')
    if identifier:
        record = read_authorization(identifier, seen)
        grant_path = AUTHORIZATIONS / f'{identifier}.json'
        claim_path = AUTHORIZATIONS / f'{identifier}.claim'
        if (ROOT / manifest.get('request_claim', '')).resolve() != claim_path.resolve():
            raise nebius.NebiusError('authorization_claim_mismatch')
        claim = json.loads(claim_path.read_text(encoding='utf-8'))
        if record.get('version') == 3 and any(claim.get(key) != record.get(key) for key in (
                'request_id', 'scope_sha256', 'authorized_maximum_estimated_cost_usd')):
            raise nebius.NebiusError('authorization_chain_mismatch')
        if (claim.get('authorization_id') != identifier
                or claim.get('authorization_sha256') != checksum(grant_path)
                or (ROOT / claim.get('extraction_directory', '')).resolve() != path.parent
                or source.nct_id != record['nct_id'] or source.source_snapshot != record['snapshot']
                or source.sha256 != record['snapshot_sha256']
                or manifest.get('requested_model') != record['model']
                or datetime.fromisoformat(claim['reserved_at']).tzinfo is None
                or datetime.fromisoformat(manifest['completed_at']).tzinfo is None):
            raise nebius.NebiusError('authorization_chain_mismatch')
        parent = {'previous_authorization_id': identifier,
                  'previous_authorization_sha256': checksum(grant_path),
                  'previous_claim': claim_path.relative_to(ROOT).as_posix(),
                  'previous_claim_sha256': checksum(claim_path)}
    elif (manifest.get('request_claim') is not None or manifest.get('status') != 'failed'
          or manifest.get('returned_model') is not None
          or not any(item.get('code') == 'timeout' for item in errors)):
        raise nebius.NebiusError('invalid_previous_attempt')
    return {
        **parent,
        'previous_attempt': path.relative_to(ROOT).as_posix(),
        'previous_attempt_sha256': checksum(path), 'previous_errors_sha256': checksum(errors_path),
        'original_claim_sha256': checksum(nebius.LIVE_CLAIM),
        'nct_id': source.nct_id, 'snapshot': source.source_snapshot,
        'snapshot_sha256': source.sha256, 'model': nebius.DEFAULT_MODEL,
        'timeout_seconds': nebius.inference_timeout(), 'max_requests': 1, 'automatic_retries': 0,
    }


def authorize(previous_attempt, actor, note):
    if not actor.strip() or not note.strip():
        raise nebius.NebiusError('authorization_identity_required')
    record = inspect_attempt(previous_attempt)
    identifier = uuid4().hex
    record.update(version=2, authorization_id=identifier, actor=actor.strip(), note=note.strip(),
                  authorized_at=datetime.now(timezone.utc).isoformat())
    AUTHORIZATIONS.mkdir(parents=True, exist_ok=True)
    with (AUTHORIZATIONS / f'{identifier}.json').open('x', encoding='utf-8') as file:
        json.dump(record, file, indent=2)
    return identifier


def read_authorization(identifier, _seen=frozenset()):
    if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{32}', identifier):
        raise nebius.NebiusError('invalid_authorization')
    try:
        record = json.loads((AUTHORIZATIONS / f'{identifier}.json').read_text(encoding='utf-8'))
        expected = inspect_attempt(record['previous_attempt'], _seen)
        if record.get('version') == 3:
            quote_keys = ('nct_id', 'snapshot', 'snapshot_sha256', 'model', 'base_url', 'timeout_seconds',
                          'prompt_sha256', 'max_input_tokens', 'max_output_tokens', 'pricing',
                          'maximum_estimated_cost_usd', 'max_requests', 'automatic_retries')
            quote = {key: record[key] for key in quote_keys}
            cap = Decimal(record['authorized_maximum_estimated_cost_usd'])
            bound = Decimal(record['maximum_estimated_cost_usd'])
            if (record['audit_anchor'] != expected or record['request_id'] != identifier
                    or record['authorization_id'] != identifier or not record['actor'].strip() or not record['note'].strip()
                    or datetime.fromisoformat(record['authorized_at']).tzinfo is None
                    or record['scope_sha256'] != scope_digest(quote) or record['max_requests'] != 1
                    or record['automatic_retries'] != 0 or not cap.is_finite() or not bound.is_finite()
                    or cap <= 0 or bound < 0 or cap < bound):
                raise nebius.NebiusError('authorization_mismatch')
            return record
        if (record['version'] not in (1, 2) or record['authorization_id'] != identifier
                or not record['actor'].strip() or not record['note'].strip()
                or datetime.fromisoformat(record['authorized_at']).tzinfo is None
                or any(record.get(key) != value for key, value in expected.items())):
            raise nebius.NebiusError('authorization_mismatch')
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError, InvalidOperation):
        raise nebius.NebiusError('invalid_authorization') from None
    return record


def reserve_authorized_request(identifier, source, config, output):
    record = read_authorization(identifier)
    status = nebius.configuration_check()
    if not status['configured'] or not status['live_enabled'] or status['public_demo']:
        raise nebius.NebiusError('live_extraction_unavailable')
    if (source.nct_id != record['nct_id'] or source.source_snapshot != record['snapshot']
            or source.sha256 != record['snapshot_sha256'] or config.model != record['model']
            or config.timeout_seconds != record['timeout_seconds']):
        raise nebius.NebiusError('authorization_scope_mismatch')
    if record.get('version') == 3:
        try:
            if not authorization_matches(record, source) or config.base_url != record['base_url']:
                raise nebius.NebiusError('authorization_scope_mismatch')
            server_cap = Decimal(os.environ.get('NEBIUS_MAX_REQUEST_USD', 'NaN'))
            if not server_cap.is_finite() or server_cap < Decimal(record['maximum_estimated_cost_usd']):
                raise nebius.NebiusError('authorization_cost_limit')
        except (InvalidOperation, ValueError):
            raise nebius.NebiusError('authorization_cost_limit') from None
    claim = AUTHORIZATIONS / f'{identifier}.claim'
    try:
        with claim.open('x', encoding='utf-8') as file:
            json.dump({'authorization_id': identifier,
                       'request_id': record.get('request_id', identifier),
                       'authorization_sha256': checksum(AUTHORIZATIONS / f'{identifier}.json'),
                       'scope_sha256': record.get('scope_sha256'),
                       'authorized_maximum_estimated_cost_usd': record.get('authorized_maximum_estimated_cost_usd'),
                       'extraction_directory': output.relative_to(ROOT).as_posix(),
                       'reserved_at': datetime.now(timezone.utc).isoformat()}, file, indent=2)
    except FileExistsError:
        raise nebius.NebiusError('request_limit_reached') from None
    return claim.relative_to(ROOT).as_posix()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Offline additional extraction authorization')
    parser.add_argument('--previous-attempt', type=Path)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--authorize-one-additional-request', action='store_true')
    actions.add_argument('--authorize-one-source-request', action='store_true')
    actions.add_argument('--quote-source', action='store_true')
    parser.add_argument('--nct-id')
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--maximum-estimated-cost-usd')
    parser.add_argument('--actor')
    parser.add_argument('--note')
    parser.add_argument('--authorization-id')
    args = parser.parse_args(argv)
    if not args.quote_source and not args.previous_attempt:
        parser.error('Previous attempt required')
    if args.quote_source or args.authorize_one_source_request:
        if not args.nct_id or not args.snapshot:
            parser.error('Exact trial and snapshot required')
    if args.authorize_one_source_request and (not args.actor or not args.note or not args.maximum_estimated_cost_usd or args.authorization_id):
        parser.error('Explicit actor, note and maximum cost required; no existing ID')
    if args.authorize_one_additional_request and (not args.actor or not args.note or args.authorization_id):
        parser.error('Authorization requires actor and note; no existing ID')
    try:
        if args.quote_source:
            source = load_source(args.snapshot, args.nct_id)
            print(json.dumps({'quote': quote_source(source), 'authorization_created': False, 'request_consumed': False}, indent=2))
        elif args.authorize_one_source_request:
            source = load_source(args.snapshot, args.nct_id)
            identifier = authorize_source(args.previous_attempt, source, args.maximum_estimated_cost_usd, args.actor, args.note)
            print(json.dumps({'authorization_id': identifier, 'request_id': identifier, 'request_consumed': False}))
        elif args.authorize_one_additional_request:
            identifier = authorize(args.previous_attempt, args.actor, args.note)
            print(json.dumps({'authorization_id': identifier, 'request_consumed': False}))
        else:
            result = inspect_attempt(args.previous_attempt)
            result['authorization_created'] = False
            result['original_request_available'] = False
            if args.authorization_id:
                record = read_authorization(args.authorization_id)
                if record['previous_attempt'] != result['previous_attempt']:
                    raise nebius.NebiusError('authorization_mismatch')
                result['additional_request_available'] = not (AUTHORIZATIONS / f'{args.authorization_id}.claim').exists()
            else:
                result['additional_request_available'] = False
            print(json.dumps(result, indent=2))
        return 0
    except nebius.NebiusError as error:
        print(f'Authorization {error.code}')
        return 1
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
        print('Authorization check failed')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
