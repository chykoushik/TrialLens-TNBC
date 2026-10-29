import hmac
import math
import os
from decimal import Decimal

from fastapi import HTTPException

from backend.app import nebius


def scoped_authorization(source):
    identifier = os.environ.get('NEBIUS_EXTRACTION_AUTHORIZATION_ID', '').strip()
    if not identifier or source is None:
        return None
    try:
        from backend.extraction_authorization import AUTHORIZATIONS, read_authorization, authorization_matches
        record = read_authorization(identifier)
        if (authorization_matches(record, source)
                and not (AUTHORIZATIONS / f'{identifier}.claim').exists()):
            return identifier
    except (nebius.NebiusError, OSError, ValueError, KeyError, TypeError):
        pass
    return None


def operator_status(source=None):
    status = nebius.configuration_check()
    missing = [name for name in ('NEBIUS_API_KEY', 'NEBIUS_MODEL', 'TRIALLENS_OPERATOR_TOKEN',
                                 'NEBIUS_INPUT_USD_PER_MILLION', 'NEBIUS_OUTPUT_USD_PER_MILLION',
                                 'NEBIUS_MAX_REQUEST_USD') if not os.environ.get(name, '').strip()]
    bound = None
    bound_exact = None
    limit = None
    try:
        rates = nebius.pricing()
        limit = float(os.environ.get('NEBIUS_MAX_REQUEST_USD', 'nan'))
        if not math.isfinite(limit) or limit <= 0:
            limit = None
        if rates:
            estimate = (nebius.MAX_INPUT_TOKENS * Decimal(str(rates['input_usd_per_million']))
                        + nebius.MAX_OUTPUT_TOKENS * Decimal(str(rates['output_usd_per_million']))) / Decimal(1_000_000)
            bound_exact, bound = str(estimate), float(estimate)
    except (ValueError, nebius.NebiusError):
        pass
    token = os.environ.get('TRIALLENS_OPERATOR_TOKEN', '').strip()
    authorized = len(token) >= 32
    bounded = bound is not None and limit is not None and bound <= limit
    identifier = scoped_authorization(source)
    additional = identifier is not None
    available = status['request_available'] or additional
    cap = None
    if identifier:
        from backend.extraction_authorization import read_authorization
        cap = read_authorization(identifier).get('authorized_maximum_estimated_cost_usd')
    return {**status, 'ready': status['configured'] and status['live_enabled'] and not status['public_demo'] and available and authorized and bounded, 'missing_variables': missing,
            'original_request_available': status['request_available'], 'request_available': available,
            'additional_authorization_available': additional,
            'authorization_id': identifier, 'authorized_maximum_estimated_cost_usd': cap,
            'remaining_authorized_requests': 1 if available else 0,
            'authorization_status': 'authorized' if additional else 'original_available' if status['request_available'] else 'no_matching_unused_authorization',
            'operator_configured': authorized, 'cost_controls_ready': bounded,
            'maximum_estimated_cost_usd': bound, 'maximum_estimated_cost_usd_exact': bound_exact, 'maximum_request_usd': limit}


def require_operator(authorization):
    token = os.environ.get('TRIALLENS_OPERATOR_TOKEN', '').strip()
    if len(token) < 32:
        raise HTTPException(503, 'Operator access is not configured.')
    supplied = authorization[7:] if authorization and authorization.startswith('Bearer ') else ''
    if not hmac.compare_digest(token.encode(), supplied.encode()):
        raise HTTPException(401, 'Operator authorization required.', headers={'WWW-Authenticate': 'Bearer'})


def require_live_access(authorization, source=None):
    require_operator(authorization)
    if not operator_status(source)['ready']:
        raise HTTPException(409, 'Live extraction is unavailable. Check server configuration, cost controls and the existing request reservation. No request was sent.')
    return scoped_authorization(source)


def confirm_scoped_request(identifier, supplied_identifier, supplied_cost):
    if supplied_identifier and supplied_identifier != identifier:
        raise HTTPException(409, 'The selected request authorization changed. Reload status and confirm again.')
    if identifier:
        from backend.extraction_authorization import read_authorization
        record = read_authorization(identifier)
        if record.get('version') == 3 and (supplied_identifier != identifier or supplied_cost is None
                or Decimal(str(supplied_cost)) != Decimal(record['authorized_maximum_estimated_cost_usd'])):
            raise HTTPException(422, 'Explicit confirmation of the request identifier and authorized maximum cost is required.')
