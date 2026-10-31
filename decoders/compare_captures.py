"""Read two explicitly selected private capture packages; emit categories only.

No metadata-supplied paths, writes, network, evidence attestations or mapping.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys

from . import capture, inspection
from .belmont import DecodeError, _pairs

MAX_METADATA_BYTES = 8192
FILES = {'snapshot.sav', 'observation.json'}


class PacketError(ValueError):
    def __init__(self, reason, status='unknown'):
        super().__init__(reason)
        self.status = status


def _result(reason, status='unknown'):
    return {'status': status, 'reason': reason, 'comparison_status': 'unknown',
            'structural_changes_detected': None, 'observations': [],
            'observations_verified': False, 'semantic_mapping_status': 'unknown',
            'collected_item_status': 'unknown', 'review_blockers': [reason]}


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode, info.st_uid, info.st_nlink)


def _open_directory(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise PacketError('absolute_packet_path_required')
    if path.name.startswith('.capture-'):
        raise PacketError('incomplete_capture_package')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _private(info):
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise PacketError('private_packet_permissions_required')


def _names(fd):
    # Bounded enumeration; do not follow or print arbitrary entries.
    names = set()
    with os.scandir(fd) as entries:
        for entry in entries:
            names.add(entry.name)
            if len(names) > len(FILES):
                break
    if names != FILES:
        raise PacketError('incomplete_or_extra_packet_files')


def _read_file(fd, name, limit):
    source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(source, 'rb') as stream:
        start = os.fstat(stream.fileno())
        _private(start)
        if not stat.S_ISREG(start.st_mode) or start.st_nlink != 1 or start.st_size > limit:
            raise PacketError('invalid_or_oversized_packet_file')
        raw = stream.read(limit + 1)
        end = os.fstat(stream.fileno())
        current = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if len(raw) > limit or _stamp(start) != _stamp(end) or _stamp(end) != _stamp(current):
            raise PacketError('unstable_capture_package')
        return raw, _stamp(end)


def _read_packet(path):
    fd = _open_directory(path)
    try:
        start = os.fstat(fd)
        _private(start)
        _names(fd)
        raw, raw_stamp = _read_file(fd, 'snapshot.sav', inspection.MAX_BYTES)
        metadata, meta_stamp = _read_file(fd, 'observation.json', MAX_METADATA_BYTES)
        # Catch changes to the first file while the second file was read.
        if (raw_stamp != _stamp(os.stat('snapshot.sav', dir_fd=fd, follow_symlinks=False)) or
                meta_stamp != _stamp(os.stat('observation.json', dir_fd=fd, follow_symlinks=False))):
            raise PacketError('unstable_capture_package')
        _names(fd)
        end = os.fstat(fd)
        check_fd = _open_directory(path)
        try:
            current = os.fstat(check_fd)
        finally:
            os.close(check_fd)
        if _stamp(start) != _stamp(end) or _stamp(end) != _stamp(current):
            raise PacketError('unstable_capture_package')
        return raw, metadata, (_stamp(end), raw_stamp, meta_stamp)
    finally:
        os.close(fd)


def _metadata(raw):
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise PacketError('invalid_capture_metadata') from None
    if not isinstance(value, dict):
        raise PacketError('invalid_capture_metadata')
    if value.get('schema_version') != '1.0':
        raise PacketError('unsupported_capture_schema', 'unsupported')
    if value.get('appid') != 4231820 or value.get('save_format_version') != '1.1.3':
        raise PacketError('unsupported_capture_format', 'unsupported')
    try:
        expected = capture._metadata(value.get('role'), value.get('phase'), value.get('action'),
                                     value.get('game_build'), value.get('platform'))
    except capture.CaptureError:
        raise PacketError('invalid_capture_metadata') from None
    # Strict types/closed schema, including all false/unknown attestations.
    if not inspection._same(value, expected):
        raise PacketError('invalid_capture_metadata')
    return value


def _context(a, b):
    if a['phase'] != 'before' or b['phase'] != 'after':
        raise PacketError('before_after_order_unconfirmed')
    if any(a[key] in (None, 'unknown') or b[key] in (None, 'unknown')
           for key in ('role', 'action', 'game_build', 'platform')):
        raise PacketError('capture_context_incomplete')
    if any(a[key] != b[key] for key in ('role', 'action', 'game_build', 'platform')):
        raise PacketError('capture_context_mismatch')
    if a['role'] == 'baseline':
        raise PacketError('trial_role_not_comparable')
    if a['role'] in ('action', 'repeat') and a['action'] == 'no_action':
        raise PacketError('trial_action_mismatch')


def compare_captures(before, after):
    """Read-only comparison, never a complete action/control/repeat evaluation.

    Stable reads and matching declarations do not establish provenance, game
    build, slot identity or ground truth. Overall evidence status stays unknown.
    """
    if sys.platform != 'linux':
        return _result('platform_not_supported', 'unsupported')
    try:
        a, b = _read_packet(before), _read_packet(after)
        # Re-read both selected packages to catch mutation across pair capture.
        if a != _read_packet(before) or b != _read_packet(after):
            raise PacketError('unstable_capture_package')
        if a[2][0][:2] == b[2][0][:2]:
            raise PacketError('distinct_capture_packages_required')
        first, second = _metadata(a[1]), _metadata(b[1])
        _context(first, second)
        result = inspection.compare_bytes(4231820, a[0], b[0])
        if result['status'] != 'known':
            return _result(result['reason'], result['status'])
        blockers = ['same_selected_slot_unconfirmed', 'independent_ground_truth_unconfirmed',
                    'action_control_repeat_not_evaluated', 'owner_attestation_not_recorded']
        if first['role'] == 'control' and result['structural_changes_detected']:
            blockers.append('control_changed')
        if any(o['change'] in ('unknown', 'null', 'type_changed') for o in result['observations']):
            blockers.append('ambiguous_observations')
        if any(o['identity'] == 'positional_only' for o in result['observations']):
            blockers.append('positional_array_changes_not_identity')
        return {**_result('unverified_capture_pair'), 'comparison_status': 'known',
                'structural_changes_detected': result['structural_changes_detected'],
                'observations': result['observations'], 'review_blockers': blockers}
    except PacketError as exc:
        return _result(str(exc), exc.status)
    except (OSError, ValueError, DecodeError):
        return _result('capture_package_unavailable')


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise PacketError('invalid_arguments')


def main(argv=None):
    parser = _Parser(description='Read-only categorical comparison of two private capture folders')
    parser.add_argument('before')
    parser.add_argument('after')
    try:
        args = parser.parse_args(argv)
        result = compare_captures(args.before, args.after)
        # 0 means structural comparison only; evidence still unknown/blocked.
        code = 0 if result['comparison_status'] == 'known' else 2
    except PacketError as exc:
        result, code = _result(str(exc), exc.status), 2
    except KeyboardInterrupt:
        result, code = _result('comparison_interrupted'), 130
    print(json.dumps(result, allow_nan=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
