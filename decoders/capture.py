"""Linux-only private capture of one explicitly selected Belmont save copy.

No network, discovery, mutation of input, or semantic attestation. Raw packages
are unencrypted and must never be published. CLI output is categorical only.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import json
import os
from pathlib import Path
import re
import secrets
import signal
import stat
import sys

from . import inspection
from .belmont import DecodeError

ROLES = ('control', 'action', 'repeat', 'baseline', 'unknown')
PHASES = ('before', 'after', 'unknown')
ACTIONS = ('hp_pickup', 'mana_pickup', 'spend_health', 'spend_mana', 'no_action', 'unknown')
PLATFORMS = ('windows', 'linux', 'steamos_proton', 'unknown')


class CaptureError(ValueError):
    """Fixed, identifier-free diagnostics only."""


def _report(status, reason):
    return {'status': status, 'reason': reason, 'observations_verified': False,
            'semantic_mapping_status': 'unknown', 'collected_item_status': 'unknown',
            'private_package_encrypted': False}


def _metadata(role, phase, action, build, platform):
    if (role not in ROLES or phase not in PHASES or action not in ACTIONS or
            platform not in PLATFORMS or
            (build is not None and (type(build) is not str or
             re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', build) is None))):
        raise CaptureError('invalid_observation')
    if role == 'control' and action not in ('no_action', 'unknown'):
        raise CaptureError('invalid_control_action')
    return {'schema_version': '1.0', 'appid': 4231820, 'save_format_version': '1.1.3',
            'role': role, 'phase': phase, 'action': action, 'game_build': build,
            'platform': platform, 'observations_verified': False,
            'same_selected_slot': 'unknown', 'independent_ground_truth': 'unknown',
            'semantic_mapping_status': 'unknown', 'collected_item_status': 'unknown',
            'private_package_encrypted': False}


def _reject_checkout(fd):
    # .git files/symlinks are rejected outright. A directory must contain HEAD:
    # an empty reserved .git directory (e.g. sandbox mount) is not a checkout.
    # Only these fixed markers are inspected; no repository discovery command.
    def exists(name):
        try:
            os.stat(name, dir_fd=fd, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False
    git_repository = False
    if exists('.git'):
        marker = os.stat('.git', dir_fd=fd, follow_symlinks=False)
        if not stat.S_ISDIR(marker.st_mode):
            git_repository = True
        else:
            git_fd = os.open('.git', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                try:
                    os.stat('HEAD', dir_fd=git_fd, follow_symlinks=False)
                    git_repository = True
                except FileNotFoundError:
                    pass
            finally:
                os.close(git_fd)
    if git_repository or all(exists(name) for name in ('HEAD', 'objects', 'refs')):
        raise CaptureError('repository_destination_forbidden')


def _open_parent(destination):
    """Pin every ancestor without following symlinks; caller owns returned fd."""
    path = Path(destination)
    if not path.is_absolute() or '..' in path.parts or path.name in ('', '.', '..'):
        raise CaptureError('absolute_destination_required')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open('/', flags)
    try:
        _reject_checkout(fd)
        for part in path.parent.parts[1:]:
            new_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = new_fd
            _reject_checkout(fd)
        parent = os.fstat(fd)
        if parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) != 0o700:
            raise CaptureError('private_parent_required')
        # No replacement, including empty directories and broken symlinks.
        try:
            os.stat(path.name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return fd, path.name
        raise CaptureError('destination_exists')
    except BaseException:
        os.close(fd)
        raise


def _publish(parent_fd, staging, name):
    # Linux atomic directory rename with NOREPLACE. Never fall back to rename(),
    # whose POSIX semantics can replace an existing empty directory.
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    if rename is None:
        raise CaptureError('atomic_publish_unavailable')
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(parent_fd, os.fsencode(staging), parent_fd, os.fsencode(name), 1):
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise CaptureError('destination_exists')
        raise CaptureError('atomic_publish_failed')


def _write_file(fd, name, data):
    out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    with os.fdopen(out, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _cleanup(parent_fd, staging, stage_fd):
    # If publication completed immediately before interruption, the staging
    # name is absent. Never unlink through the still-open fd in that case.
    try:
        current = os.stat(staging, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if stage_fd is not None:
        owned = os.fstat(stage_fd)
        if (current.st_dev, current.st_ino) != (owned.st_dev, owned.st_ino):
            raise CaptureError('cleanup_incomplete')
        for filename in ('snapshot.sav', 'observation.json'):
            try:
                os.unlink(filename, dir_fd=stage_fd)
            except FileNotFoundError:
                pass
    os.rmdir(staging, dir_fd=parent_fd)


def capture(source, destination, *, role='unknown', phase='unknown', action='unknown',
            build=None, platform='unknown', confirmed=False):
    """Publish one new private package, or leave no package on pre-publish failure.

    Explicit confirmation is required. A successful atomic rename is the commit
    point; interruption after it may leave a complete package (never retry by
    overwriting). Caller must keep parent directories private and stable.
    """
    if not confirmed:
        return _report('cancelled', 'capture_not_confirmed')
    if sys.platform != 'linux':
        raise CaptureError('platform_not_supported')
    metadata = _metadata(role, phase, action, build, platform)
    parent_fd = stage_fd = None
    staging = None
    published = False
    try:
        parent_fd, name = _open_parent(destination)
        raw = inspection.read_snapshot(source)
        if inspection.inspect_bytes(4231820, raw)['status'] != 'known':
            raise CaptureError('unsupported_or_invalid_save')
        # Data is fully validated before the first filesystem mutation.
        candidate = '.capture-' + secrets.token_hex(16)
        # Defer Ctrl+C across allocation + ownership bookkeeping, so cleanup
        # cannot miss a directory created just before the interrupt.
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
        try:
            os.mkdir(candidate, 0o700, dir_fd=parent_fd)
            staging = candidate
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        stage_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        _write_file(stage_fd, 'snapshot.sav', raw)
        _write_file(stage_fd, 'observation.json', (json.dumps(metadata, indent=2) + '\n').encode())
        os.fsync(stage_fd)
        _publish(parent_fd, staging, name)
        published = True
        # After the commit point no further fallible filesystem operation is
        # performed. Power-loss durability of the directory rename is not claimed.
        return _report('captured', 'private_unverified_package_created')
    except (OSError, DecodeError):
        raise CaptureError('capture_unavailable') from None
    finally:
        try:
            if staging is not None and not published and parent_fd is not None:
                try:
                    _cleanup(parent_fd, staging, stage_fd)
                except OSError:
                    raise CaptureError('cleanup_incomplete') from None
        finally:
            if stage_fd is not None:
                os.close(stage_fd)
            if parent_fd is not None:
                os.close(parent_fd)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CaptureError('invalid_arguments')


def main(argv=None):
    parser = _Parser(description='Create an unencrypted private research copy; never publish it')
    parser.add_argument('--source', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--role', choices=ROLES, default='unknown')
    parser.add_argument('--phase', choices=PHASES, default='unknown')
    parser.add_argument('--action', choices=ACTIONS, default='unknown')
    parser.add_argument('--build')
    parser.add_argument('--platform', choices=PLATFORMS, default='unknown')
    parser.add_argument('--confirm-capture', action='store_true')
    try:
        args = parser.parse_args(argv)
        result = capture(args.source, args.destination, role=args.role, phase=args.phase,
                         action=args.action, build=args.build, platform=args.platform,
                         confirmed=args.confirm_capture)
        code = 0
    except CaptureError as exc:
        result, code = _report('unknown', str(exc)), 2
    except KeyboardInterrupt:
        result, code = _report('unknown', 'interrupted_check_private_destination'), 130
    print(json.dumps(result, allow_nan=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
