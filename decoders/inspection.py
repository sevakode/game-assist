"""Local, read-only research inspection. Never a gameplay evidence authority.

Closed dispatch is deliberately separate from the declarative profile registry.
No contributed module is imported and no public MCP contract is changed.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, DecimalException
import json
import os
from pathlib import Path
import stat

from . import belmont

MAX_BYTES = belmont.MAX_BYTES
CATEGORIES = dict(zip(belmont.SCALARS, (
    'health_fragment_counter', 'mana_fragment_counter', 'current_health', 'current_mana')))
_MISSING = object()


def read_snapshot(path: str | Path) -> bytes:
    """Bounded double read; private, stable parent directories required (Linux).

    Does not log, return paths/hashes, follow symlinks, or write input files.
    Stability here does not establish a completed game/Cloud synchronization.
    """
    path = Path(os.path.abspath(path))
    try:
        belmont._reject_symlinks(path)
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) |
                     getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            start = os.fstat(stream.fileno())
            if not stat.S_ISREG(start.st_mode) or start.st_size > MAX_BYTES:
                raise belmont.DecodeError('Input must be a bounded regular file')
            first = stream.read(MAX_BYTES + 1)
            stream.seek(0)
            second = stream.read(MAX_BYTES + 1)
            end = os.fstat(stream.fileno())
            belmont._reject_symlinks(path)
            current = path.stat()
            def stamp(s):
                return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns
            if (len(first) > MAX_BYTES or first != second or
                    stamp(start) != stamp(end) or stamp(end) != stamp(current)):
                raise belmont.DecodeError('Save changed during read')
            return first
    except OSError:
        raise belmont.DecodeError('Save could not be read safely') from None


def _result(status, reason, structure='unknown'):
    return {'status': status, 'reason': reason, 'structure': structure,
            'game_build_status': 'unknown', 'semantic_mapping_status': 'unknown',
            'collected_item_status': 'unknown'}


def inspect_bytes(appid: int, raw: bytes) -> dict:
    """Return only fixed categories, never private strings from untrusted input.

    known means only the explicitly named structural scope passed validation.
    A BND4 magic match does not validate its header, entries or game identity.
    """
    if type(raw) is not bytes or len(raw) > MAX_BYTES:
        return _result('unknown', 'invalid_or_oversized_input')
    if type(appid) is not int:
        return _result('unsupported', 'adapter_unavailable')
    if appid == 4231820:
        try:
            save = belmont.decode_bytes(raw)
        except belmont.DecodeError as exc:
            if str(exc) == 'Unsupported save version; expected 1.1.3':
                return _result('unsupported', 'save_format_not_supported')
            return _result('unknown', 'invalid_structure')
        result = _result('known', 'structural_only', 'belmont_json_1.1.3')
        result['safe_summary'] = belmont.safe_summary(save)
        return result
    if appid == 1245620:
        return _result('unsupported', 'gameplay_adapter_unavailable',
                       'bnd4_signature_only' if raw.startswith(b'BND4') else 'unknown')
    if appid == 292030:
        return _result('unsupported', 'save_format_not_validated')
    return _result('unsupported', 'adapter_unavailable')


def _exact_json(raw):
    # Decimal avoids binary-float rounding (including tiny exponents). The
    # existing reader validates outer/nested structure and complexity first.
    try:
        return json.loads(raw, object_pairs_hook=belmont._pairs,
                          parse_float=Decimal, parse_int=int,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError, DecimalException):
        raise belmont.DecodeError('Invalid JSON encoding or structure') from None


def _same(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def _positional_change(a, b):
    if isinstance(a, list) or isinstance(b, list):
        return not _same(a, b)
    if isinstance(a, dict) and isinstance(b, dict):
        return any(_positional_change(a.get(k, _MISSING), b.get(k, _MISSING))
                   for k in a.keys() | b.keys())
    # A newly added/removed container could contain arrays too.
    if isinstance(a, dict) or isinstance(b, dict):
        obj = a if isinstance(a, dict) else b
        return any(_positional_change(v, _MISSING) for v in obj.values())
    return False


def _change(a, b):
    if a is _MISSING and b is _MISSING:
        return 'unknown'
    if a is _MISSING:
        return 'added'
    if b is _MISSING:
        return 'removed'
    if type(a) is not type(b):
        return 'type_changed'
    if a is None:
        return 'null'
    if _same(a, b):
        return 'unchanged'
    if type(a) in (int, Decimal):
        return 'increased' if b > a else 'decreased'
    return 'unknown'


def compare_bytes(appid: int, before: bytes, after: bytes) -> dict:
    """Categorical observations compatible with BEL-01; no auto-attestation.

    All JSON structure participates in the conservative control check. No JSON
    pointer, entity name, raw value, digest or per-entity count is returned.
    """
    checks = [inspect_bytes(appid, raw) for raw in (before, after)]
    if any(check['status'] != 'known' for check in checks):
        status = 'unsupported' if any(c['status'] == 'unsupported' for c in checks) else 'unknown'
        return {**_result(status, 'pair_not_supported'), 'observations': [],
                'structural_changes_detected': None}
    try:
        a, b = _exact_json(before), _exact_json(after)
    except belmont.DecodeError:
        return {**_result('unknown', 'exact_comparison_unavailable'),
                'observations': [], 'structural_changes_detected': None}
    observations = []
    for key, category in CATEGORIES.items():
        x = a.get('playerSave', {}).get(key, _MISSING)
        y = b.get('playerSave', {}).get(key, _MISSING)
        observations.append({'field_category': category, 'change': _change(x, y),
                             'identity': 'not_applicable'})
    changed = not _same(a, b)
    # Include every unclassified field, so a changing control cannot appear clean
    # simply because it left the four known scalars untouched.
    for root in (a, b):
        for key in CATEGORIES:
            root.get('playerSave', {}).pop(key, None)
    other_changed = not _same(a, b)
    observations.append({'field_category': 'other_unknown',
                         'change': 'unknown' if other_changed else 'unchanged',
                         'identity': 'unknown'})
    if _positional_change(a, b):
        observations.append({'field_category': 'array_position', 'change': 'unknown',
                             'identity': 'positional_only'})
    return {**_result('known', 'structural_observations_only', 'belmont_json_1.1.3'),
            'structural_changes_detected': changed, 'observations': observations}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local read-only structural research; no pickup mapping')
    parser.add_argument('--appid', required=True, type=int)
    parser.add_argument('save')
    parser.add_argument('--compare')
    args = parser.parse_args(argv)
    try:
        before = read_snapshot(args.save)
        result = (compare_bytes(args.appid, before, read_snapshot(args.compare))
                  if args.compare else inspect_bytes(args.appid, before))
        code = 0 if result['status'] == 'known' else 2
    except belmont.DecodeError:
        result, code = _result('unknown', 'snapshot_unavailable'), 2
    print(json.dumps(result, allow_nan=False, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
