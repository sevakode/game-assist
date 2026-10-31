"""Opt-in, read-only save watcher. Default: metadata only. --decode-belmont:
summary only, independently authorized by saves.summary. No discovery or raw uploads.

Safe traversal currently requires POSIX dir_fd/O_NOFOLLOW primitives. Platforms
without them (notably Windows Python) fail closed; Windows support is not claimed.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_FILES = 4096
MAX_ENTRIES = 16384
MAX_DEPTH = 64


class SnapshotError(Exception):
    """Incomplete or unstable observation; must never replace server state."""


def _signature(st):
    return (st.st_dev, st.st_ino, st.st_mode, st.st_size,
            st.st_mtime_ns, st.st_ctime_ns)


def _supported():
    return (os.name == 'posix' and hasattr(os, 'O_NOFOLLOW')
            and os.open in os.supports_dir_fd and os.stat in os.supports_dir_fd
            and os.scandir in os.supports_fd)


def _parts(path):
    raw = os.fspath(path)
    if not raw or '\x00' in raw or '..' in Path(raw).parts:
        raise SnapshotError('Explicit path is empty or contains traversal components')
    # Do not resolve(): doing so would hide symlinks in the opted-in path.
    return Path(os.path.abspath(os.path.expanduser(raw))).parts[1:]


def _safe_name(parts):
    # Escape separators/control characters inside individual names. Never transmit
    # absolute paths, parent directories, file contents, or exception filenames.
    return '/'.join(urllib.parse.quote(p, safe='-_. ') for p in parts)


def _open_root(path):
    parts = _parts(path)
    if not parts:
        raise SnapshotError('Filesystem root is not an eligible save path')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for index, component in enumerate(parts):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if index < len(parts) - 1:
                flags |= os.O_DIRECTORY
            new_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = new_fd
        return fd, parts[-1]
    except BaseException:
        os.close(fd)
        raise


def snapshot(paths, *, single_file_only=False):
    """Return a complete snapshot, or raise; no partial/empty-on-error result."""
    if not paths:
        raise SnapshotError('At least one explicit save path is required')
    if not _supported():
        raise SnapshotError('Safe no-follow traversal unavailable on this platform; Windows is not yet supported')
    result = []
    budget = {'bytes': 0, 'files': 0, 'entries': 0}

    def visit(fd, names, depth):
        before = os.fstat(fd)
        if stat.S_ISREG(before.st_mode):
            budget['files'] += 1
            budget['bytes'] += before.st_size
            if (before.st_size > MAX_FILE_BYTES or budget['bytes'] > MAX_TOTAL_BYTES
                    or budget['files'] > MAX_FILES):
                raise SnapshotError('Save snapshot exceeds file size, total size, or file count budget')
            digest = hashlib.sha256()
            read_bytes = 0
            while True:
                chunk = os.read(fd, min(1024 * 1024, before.st_size - read_bytes + 1))
                if not chunk:
                    break
                read_bytes += len(chunk)
                if read_bytes > before.st_size:
                    raise SnapshotError('Save changed during hashing; retry after it settles')
                digest.update(chunk)
            if read_bytes != before.st_size or _signature(before) != _signature(os.fstat(fd)):
                raise SnapshotError('Save changed during hashing; retry after it settles')
            result.append({'name': _safe_name(names), 'size': read_bytes,
                           'sha256': digest.hexdigest(), 'modified_ns': before.st_mtime_ns})
        elif stat.S_ISDIR(before.st_mode):
            if depth > MAX_DEPTH:
                raise SnapshotError('Save directory depth exceeds budget')
            # Enumerate lazily: never allocate an unbounded directory listing.
            with os.scandir(fd) as entries:
                for entry in entries:
                    budget['entries'] += 1
                    if budget['entries'] > MAX_ENTRIES:
                        raise SnapshotError('Save directory entry count exceeds budget')
                    child = entry.name
                    child_stat = os.stat(child, dir_fd=fd, follow_symlinks=False)
                    if not (stat.S_ISREG(child_stat.st_mode) or stat.S_ISDIR(child_stat.st_mode)):
                        raise SnapshotError('Save path contains a symlink or special file')
                    child_fd = os.open(child, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                       dir_fd=fd)
                    try:
                        if _signature(child_stat) != _signature(os.fstat(child_fd)):
                            raise SnapshotError('Save entry changed during traversal')
                        visit(child_fd, names + [child], depth + 1)
                        if _signature(child_stat) != _signature(os.stat(child, dir_fd=fd, follow_symlinks=False)):
                            raise SnapshotError('Save entry changed during traversal')
                    finally:
                        os.close(child_fd)
        else:
            raise SnapshotError('Only regular save files and directories are eligible')
        if _signature(before) != _signature(os.fstat(fd)):
            raise SnapshotError('Save path changed during observation')

    try:
        for index, path in enumerate(paths):
            budget['entries'] += 1
            if budget['entries'] > MAX_ENTRIES:
                raise SnapshotError('Selected path count exceeds budget')
            fd, basename = _open_root(path)
            try:
                if single_file_only and not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise SnapshotError('--decode-belmont requires one explicit regular file, not a directory')
                initial = _signature(os.fstat(fd))
                names = ['root-' + str(index + 1)] if len(paths) > 1 else []
                if stat.S_ISREG(os.fstat(fd).st_mode):
                    names.append(basename)
                visit(fd, names, 0)
                # Re-open via the explicit path: detect ancestor/root replacement.
                check_fd, _ = _open_root(path)
                try:
                    if initial != _signature(os.fstat(check_fd)):
                        raise SnapshotError('Selected save path changed during observation')
                finally:
                    os.close(check_fd)
            finally:
                os.close(fd)
    except (OSError, ValueError) as error:
        raise SnapshotError('Save path unreadable, missing, unsafe, or changing; previous state retained') from error
    return sorted(result, key=lambda item: item['name'])


_DECODER = None


def _belmont_decoder():
    """Load only this repository's fixed decoder, without modifying sys.path."""
    global _DECODER
    if _DECODER is None:
        source = Path(__file__).resolve().parents[1] / 'decoders' / 'belmont.py'
        spec = importlib.util.spec_from_file_location('_sgc_watch_belmont', source)
        if spec is None or spec.loader is None:
            raise SnapshotError('Local Belmont decoder unavailable')
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module  # Required by dataclasses; no search path added.
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(spec.name, None)
            raise
        _DECODER = module
    return _DECODER


def belmont_summary(path, stable_records):
    """Read a private bounded buffer through safe descriptors; expose only allowlist.

    The fresh buffer must match the already debounced snapshot. Raw data remains
    in process memory only and is never logged, written, or passed to send().
    """
    if not _supported() or len(stable_records) != 1:
        raise SnapshotError('Belmont decoding requires one safely readable file')
    decoder = _belmont_decoder()
    try:
        fd, _ = _open_root(path)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > decoder.MAX_BYTES:
                raise SnapshotError('Belmont input must be a regular file within decoder size limit')
            chunks = []
            count = 0
            while True:
                chunk = os.read(fd, min(1024 * 1024, before.st_size - count + 1))
                if not chunk:
                    break
                count += len(chunk)
                if count > before.st_size:
                    raise SnapshotError('Belmont source changed after debounce; no summary sent')
                chunks.append(chunk)
            raw = b''.join(chunks)
            if count != before.st_size or _signature(before) != _signature(os.fstat(fd)):
                raise SnapshotError('Belmont source changed during read; no summary sent')
            check_fd, _ = _open_root(path)
            try:
                if _signature(before) != _signature(os.fstat(check_fd)):
                    raise SnapshotError('Belmont source path changed during read; no summary sent')
            finally:
                os.close(check_fd)
            record = stable_records[0]
            if (count != record['size'] or before.st_mtime_ns != record['modified_ns']
                    or hashlib.sha256(raw).hexdigest() != record['sha256']):
                raise SnapshotError('Belmont source changed after debounce; no summary sent')
        finally:
            os.close(fd)
        try:
            return decoder.safe_summary(decoder.decode_bytes(raw))
        except decoder.DecodeError as error:
            raise SnapshotError('Belmont decode rejected: ' + str(error)) from None
    except OSError:
        raise SnapshotError('Belmont source could not be read safely; no summary sent') from None


def validate_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise ValueError('Endpoint must be a loopback HTTP base URL') from error
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in ('', '/')
            or (port is not None and not 1 <= port <= 65535)):
        raise ValueError('Endpoint must be a loopback HTTP base URL without credentials, path, query, or fragment')
    # Pin localhost to loopback; do not trust DNS or environment HTTP proxies.
    host = '[::1]' if parsed.hostname == '::1' else '127.0.0.1'
    return 'http://' + host + (':' + str(port) if port else '')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, 'Redirect refused', headers, fp)


def send(url, token, appid, items):
    return _send_observation(url, token, appid, 'save_metadata', {'files': items})


def send_summary(url, token, appid, summary):
    return _send_observation(url, token, appid, 'save_summary', summary)


def _send_observation(url, token, appid, kind, payload):
    endpoint = validate_url(url) + '/v1/observations'
    data = json.dumps({'appid': appid, 'kind': kind, 'payload': payload}).encode()
    req = urllib.request.Request(endpoint, data=data, headers={
        'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, method='POST')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(req, timeout=10) as response:
        if not 200 <= response.status < 300:
            raise urllib.error.URLError('Non-success response')
        return response.status


def _positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('must be finite and greater than zero')
    return number


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--path', action='append', required=True, help='Explicit save file/directory; may be repeated')
    ap.add_argument('--appid', type=int, default=4231820)
    ap.add_argument('--url', default='http://127.0.0.1:8000')
    ap.add_argument('--interval', type=_positive, default=60)
    ap.add_argument('--once', action='store_true', help='Take two stable samples, send once, and exit nonzero on failure')
    ap.add_argument('--decode-belmont', action='store_true', help='Summary-only mode (no metadata upload): four raw fields from one Belmont 1.1.3 file; requires saves.summary consent')
    args = ap.parse_args(argv)
    if args.decode_belmont and (len(args.path) != 1 or args.appid != 4231820):
        ap.error('--decode-belmont requires exactly one --path file and --appid 4231820')
    if args.appid <= 0:
        ap.error('--appid must be positive')
    try:
        validate_url(args.url)
    except ValueError as error:
        ap.error(str(error))
    token = os.environ.get('SGC_TOKEN')
    if not token:
        ap.error('Set SGC_TOKEN')
    previous = None
    candidate = None
    while True:
        try:
            current = snapshot(args.path, single_file_only=True) if args.decode_belmont else snapshot(args.path)
            if current == candidate:
                if current != previous:
                    summary = belmont_summary(args.path[0], current) if args.decode_belmont else None
                    if summary is not None:
                        send_summary(args.url, token, args.appid, summary)
                        print('Updated Belmont raw scalar summary (current values, not maxima; no pickup inference)', flush=True)
                    else:
                        send(args.url, token, args.appid, current)
                        print(f'Updated {len(current)} stable save metadata records (no contents)', flush=True)
                    previous = current
                if args.once:
                    return 0
            elif args.once and candidate is not None:
                print('Save metadata did not settle across two samples; nothing sent', flush=True)
                return 1
            candidate = current
        except SnapshotError as error:
            print('Observation failed: ' + str(error) + '; previous server state retained', flush=True)
            candidate = None
            if args.once:
                return 1
        except urllib.error.HTTPError as error:
            print(f'Local service rejected observation (HTTP {error.code}); check game consent and saves.metadata / saves.summary scopes; no summary cleared', flush=True)
            candidate = None
            if args.once:
                return 1
        except (urllib.error.URLError, OSError, ValueError):
            # Do not log exceptions: filesystem paths, endpoint details, or token
            # may appear in them. Never clear server records on a failed scan.
            print('Observation/sync failed: unreadable, unsafe, changing, over-budget save path or local endpoint unavailable; previous server state retained', flush=True)
            candidate = None
            if args.once:
                return 1
        time.sleep(args.interval)


if __name__ == '__main__':
    raise SystemExit(main())
