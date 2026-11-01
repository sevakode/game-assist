"""Flat allowlisted report contract; rejects raw logs rather than redacting them.

No filesystem, environment, subprocess, network or logging calls. Callers supply
classified facts explicitly. Validation errors never include submitted values.
"""
import json
import re

MAX_REPORT_BYTES = 2048
REASONS = (
    'none', 'unknown', 'install_interrupted', 'install_partial', 'unit_mismatch',
    'working_directory_unavailable', 'venv_unavailable', 'service_failed',
    'pairing_pending', 'pairing_expired', 'pairing_denied', 'consent_required',
    'network_unavailable', 'upstream_timeout', 'upstream_unavailable',
    'origin_denied', 'csrf_denied', 'unauthenticated', 'rate_limited',
    'invalid_request', 'not_found', 'internal_error', 'request_cancelled',
)
VERSION_PATTERN = r'(?:unknown|[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})'
ID_PATTERN = r'[0-9a-f]{32}'

def enum(*values):
    return {'type': 'string', 'enum': list(values)}

PROPERTIES = {
    'schema_version': {'type': 'integer', 'const': 1},
    'app_version': {'type': 'string', 'pattern': '^' + VERSION_PATTERN + r'(?![\s\S])', 'maxLength': 11},
    'python_version': {'type': 'string', 'pattern': '^' + VERSION_PATTERN + r'(?![\s\S])', 'maxLength': 11},
    'platform': enum('linux', 'windows', 'macos', 'unknown'),
    'component': enum('server', 'web', 'deck'),
    'stage': enum('install', 'service', 'pairing', 'authorization', 'request', 'unknown'),
    'reason': enum(*REASONS),
    'request_id': {'type': ['string', 'null'], 'pattern': '^' + ID_PATTERN + r'(?![\s\S])', 'maxLength': 32},
    'http_status': {'type': ['integer', 'null'], 'minimum': 100, 'maximum': 599},
    'installation': enum('unknown', 'missing', 'interrupted', 'partial', 'unit_mismatch', 'present', 'unsafe_or_unreadable'),
    'service': enum('unknown', 'active', 'inactive', 'failed', 'activating', 'deactivating', 'unavailable'),
    'pairing': enum('unknown', 'missing', 'pending', 'expired', 'denied', 'locally_valid_remote_not_checked'),
    'venv_available': {'type': ['boolean', 'null']},
}
REPORT_SCHEMA = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    'title': 'Game Assist diagnostic report v1', 'type': 'object',
    'additionalProperties': False, 'required': list(PROPERTIES),
    'properties': PROPERTIES,
}

class ReportError(ValueError):
    """Only fixed reason codes; safe to display without submitted payload."""


def _fail():
    raise ReportError('invalid_diagnostic_report') from None


def validate_report(value):
    """Return a fresh flat dict, using exact Python types (bool is not int)."""
    if type(value) is not dict or value.keys() != PROPERTIES.keys():
        _fail()
    for key, spec in PROPERTIES.items():
        item = value[key]
        types = spec['type'] if type(spec['type']) is list else [spec['type']]
        actual = {str: 'string', int: 'integer', bool: 'boolean', type(None): 'null'}.get(type(item))
        if actual not in types:
            _fail()
        if item is None:
            continue
        if 'const' in spec and item != spec['const']:
            _fail()
        if 'enum' in spec and item not in spec['enum']:
            _fail()
        if actual == 'string':
            if len(item) > spec.get('maxLength', 64):
                _fail()
            if 'pattern' in spec and re.fullmatch(spec['pattern'], item) is None:
                _fail()
        if actual == 'integer' and not spec.get('minimum', 0) <= item <= spec.get('maximum', 599):
            _fail()
    result = dict(value)
    if len(json.dumps(result, separators=(',', ':'), ensure_ascii=True).encode()) > MAX_REPORT_BYTES:
        _fail()
    return result


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail()
        result[key] = value
    return result


def parse_report(payload):
    """Bound before parsing; reject duplicate keys, NaN, coercion, extra fields."""
    if type(payload) not in (bytes, str) or len(payload) > MAX_REPORT_BYTES:
        _fail()
    try:
        raw = payload.encode('utf-8') if type(payload) is str else payload
        if len(raw) > MAX_REPORT_BYTES:
            _fail()
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique,
                           parse_constant=lambda _: _fail())
        return validate_report(value)
    except (ValueError, UnicodeError, RecursionError):
        _fail()


def build_report(*, component, stage, reason='unknown', app_version='unknown',
                 python_version='unknown', platform='unknown', request_id=None,
                 http_status=None, installation='unknown', service='unknown',
                 pairing='unknown', venv_available=None):
    """Prepare only. No implicit host inspection or transmission."""
    return validate_report(dict(schema_version=1, component=component, stage=stage,
        reason=reason, app_version=app_version, python_version=python_version,
        platform=platform, request_id=request_id, http_status=http_status,
        installation=installation, service=service, pairing=pairing,
        venv_available=venv_available))


def serialize_report(report):
    return json.dumps(validate_report(report), sort_keys=True, separators=(',', ':'))
