import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from backend.app import nebius
from backend.app.extraction_source import ROOT, load_source

AUTHORIZATIONS = ROOT / 'results/nebius/authorizations'
EXTRACTIONS = ROOT / 'results/extraction'


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        if (record['version'] not in (1, 2) or record['authorization_id'] != identifier
                or not record['actor'].strip() or not record['note'].strip()
                or datetime.fromisoformat(record['authorized_at']).tzinfo is None
                or any(record.get(key) != value for key, value in expected.items())):
            raise nebius.NebiusError('authorization_mismatch')
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
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
    claim = AUTHORIZATIONS / f'{identifier}.claim'
    try:
        with claim.open('x', encoding='utf-8') as file:
            json.dump({'authorization_id': identifier,
                       'authorization_sha256': checksum(AUTHORIZATIONS / f'{identifier}.json'),
                       'extraction_directory': output.relative_to(ROOT).as_posix(),
                       'reserved_at': datetime.now(timezone.utc).isoformat()}, file, indent=2)
    except FileExistsError:
        raise nebius.NebiusError('request_limit_reached') from None
    return claim.relative_to(ROOT).as_posix()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Offline additional extraction authorization')
    parser.add_argument('--previous-attempt', type=Path, required=True)
    parser.add_argument('--authorize-one-additional-request', action='store_true')
    parser.add_argument('--actor')
    parser.add_argument('--note')
    parser.add_argument('--authorization-id')
    args = parser.parse_args(argv)
    if args.authorize_one_additional_request and (not args.actor or not args.note or args.authorization_id):
        parser.error('Authorization requires actor and note; no existing ID')
    try:
        if args.authorize_one_additional_request:
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
