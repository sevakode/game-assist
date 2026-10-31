"""Read-only selected-game companion: minimal metadata or explicit Belmont summary."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import ssl
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from agent import watch
from decoders import belmont

LIMIT = 16384
MAX_APPID = 2147483647
MAX_METADATA_BYTES = 1024 ** 3
MODES = ('metadata', 'belmont-summary')
DEFAULT_HOME = Path.home() / '.config' / 'steam-game-companion'


def server_origin(value, allow_local_test=False):
    try:
        p = urllib.parse.urlsplit(value)
        port = p.port
    except ValueError:
        raise ValueError('Invalid server origin') from None
    local = p.hostname in ('localhost', '127.0.0.1', '::1')
    if (not p.hostname or p.username is not None or p.password is not None
            or p.query or p.fragment or p.path not in ('', '/')
            or p.scheme not in ('https', 'http')
            or (p.scheme != 'https' and not (allow_local_test and local))
            or (port is not None and not 1 <= port <= 65535)
            or any(c.isspace() for c in value)):
        raise ValueError('Use an explicit HTTPS origin without path or credentials')
    host = '[::1]' if p.hostname == '::1' else p.hostname
    if p.scheme == 'http' and p.hostname == 'localhost':
        host = '127.0.0.1'
    return p.scheme + '://' + host + (':' + str(port) if port else '')


class Transport:
    def __init__(self, origin, allow_local_test=False):
        self.origin = server_origin(origin, allow_local_test)
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), watch._NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    def post(self, route, payload, token=None):
        if route not in ('/v1/devices/pair/start', '/v1/devices/pair/poll', '/v1/device/observations'):
            raise ValueError('Unsupported route')
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        data = json.dumps(payload, allow_nan=False).encode()
        if len(data) > LIMIT:
            raise ValueError('Request exceeds size limit')
        request = urllib.request.Request(self.origin + route, data=data, headers=headers, method='POST')
        with self.opener.open(request, timeout=15) as response:
            raw = response.read(LIMIT + 1)
            if not 200 <= response.status < 300 or len(raw) > LIMIT:
                raise ValueError('Invalid service response')
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError('Invalid service response')
            return result


class Store:
    """Private own-state only. Reject symlink parents and non-private files."""
    def __init__(self, directory=DEFAULT_HOME):
        self.directory = Path(directory).absolute()
        for part in reversed((self.directory, *self.directory.parents)):
            if part.exists() and part.is_symlink():
                raise ValueError('State directory must not contain symlinks')
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        st = self.directory.stat()
        if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
            raise ValueError('State directory must be owned by you and mode 0700')

    @contextmanager
    def lock(self):
        fd = os.open(self.directory / '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
                raise ValueError('Lock must be private and regular')
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def read(self, name):
        path = self.directory / name
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return {}
        with os.fdopen(fd, 'rb') as stream:
            st = os.fstat(stream.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
                raise ValueError('State file must be private and regular')
            data = stream.read(LIMIT + 1)
            if len(data) > LIMIT:
                raise ValueError('State exceeds size limit')
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError('Invalid state')
            return value

    def write(self, name, value):
        data = json.dumps(value, allow_nan=False).encode()
        if len(data) > LIMIT:
            raise ValueError('State exceeds size limit')
        tmp = self.directory / ('.tmp-' + uuid.uuid4().hex)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.directory / name)
        finally:
            tmp.unlink(missing_ok=True)


def selection(appid, mode):
    if type(appid) is not int or not 1 <= appid <= MAX_APPID:
        raise ValueError('Steam AppID must be 1..2147483647')
    if mode not in MODES or (mode == 'belmont-summary' and appid != 4231820):
        raise ValueError('Summary decoder is available only for Belmont app 4231820; choose metadata for other games')
    return 'saves.metadata' if mode == 'metadata' else 'saves.summary'


def clean_metadata(value):
    if not isinstance(value, dict) or set(value) != {'size_bytes', 'modified_ns'}:
        raise ValueError('Invalid minimal metadata')
    for key, limit in (('size_bytes', MAX_METADATA_BYTES), ('modified_ns', 2**63 - 1)):
        if type(value[key]) is not int or not 0 <= value[key] <= limit:
            raise ValueError('Invalid minimal metadata value')
    return dict(value)


def signature(path, max_bytes=belmont.MAX_BYTES):
    fd, _ = watch._open_root(path)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > max_bytes:
            raise watch.SnapshotError('Select one bounded regular save file')
        return list(watch._signature(st))
    finally:
        os.close(fd)


def clean_summary(value):
    """Reconstruct the exact decoder allowlist before loading an offline queue."""
    if not isinstance(value, dict) or value.get('format_version') != belmont.VERSION:
        raise ValueError('Invalid queued summary')
    scalars = value.get('player_scalars', {})
    player = {}
    for key in belmont.SCALARS:
        field = scalars.get(key, {})
        if field.get('status') == 'known':
            player[key] = field.get('value')
            if player[key] is None:
                raise ValueError('Invalid known scalar')
        elif field.get('status') == 'unknown' and field.get('value') is None:
            player[key] = None
        elif field.get('status') != 'missing' or field.get('value') is not None:
            raise ValueError('Invalid scalar status')
    decoded = belmont.decode_bytes(json.dumps({'version': belmont.VERSION, 'playerSave': player}).encode())
    world = value.get('decoder_coverage', {}).get('world_structure')
    if world not in ('missing', 'validated_structural_only'):
        raise ValueError('Invalid coverage')
    decoded.world_status = world
    clean = belmont.safe_summary(decoded)
    if clean != value:
        raise ValueError('Queued summary has extra or altered fields')
    return clean


def pair(store, transport, path, sleep=time.sleep, monotonic=time.monotonic, *, appid=4231820, mode='belmont-summary', ask=input):
    scope = selection(appid, mode)
    previous = store.read('config.json')
    previous_generation = previous.get('pairing_id')
    if previous:
        print('Only one selected game/file is watched by this installation. Existing pairing and queued observations will be replaced, not combined.')
        if ask('Replace the existing pairing? [y/N] ').strip().lower() not in ('y', 'yes'):
            raise ValueError('Replacement not approved')
    signature(path, MAX_METADATA_BYTES if mode == 'metadata' else belmont.MAX_BYTES)  # Explicit selection is mandatory; never discover or traverse home.
    print(f'Steam AppID: {appid}; mode: {mode}.')
    print('The game/file association is your selection, not proof that the file belongs to this game. Only this one file will be watched.')
    if mode == 'metadata':
        print('Локальный файл — только чтение; передаются только размер и время изменения. Содержимое не читается и не передаётся; прогресс игры неизвестен. Декодер не требуется.')
    else:
        print('Локальный файл — только чтение; передаются только четыре поля Belmont 1.1.3 и ограничения декодера, не содержимое сейва.')
    print('Approve this same game and scope on your phone. Add an unknown game to your service catalogue first.')
    start = transport.post('/v1/devices/pair/start', {'appid': appid, 'scopes': [scope]})
    uri = start['verification_uri']
    parsed = urllib.parse.urlsplit(uri)
    if server_origin(urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, '', '', '')),
                     transport.origin.startswith('http:')) != transport.origin or parsed.fragment or parsed.query:
        raise ValueError('Pairing browser URL must use the configured service origin')
    code = start['user_code']
    if not isinstance(code, str) or not code or len(code) > 32 or not all(c.isalnum() or c == '-' for c in code):
        raise ValueError('Invalid pairing code')
    # Print only a short-lived code and verification page, never the device code/token.
    print('Open on your phone: ' + uri)
    print('Pairing code: ' + code)
    print('Sign in through Steam and explicitly approve this device, selected game and ' + scope + ' scope.')
    lifetime = min(600, max(1, int(start['expires_in'])))
    interval = min(60, max(5, int(start.get('interval', 5))))
    until = monotonic() + lifetime
    while monotonic() < until:
        sleep(interval)
        if monotonic() >= until:
            break
        result = transport.post('/v1/devices/pair/poll', {'device_code': start['device_code']})
        if result.get('status') == 'pending':
            interval = min(60, max(5, int(result.get('interval', interval))))
            continue
        token = result.get('device_token')
        if result.get('status') != 'approved' or not isinstance(token, str) or not token or len(token) > 4096 or any(c.isspace() for c in token):
            raise ValueError('Pairing denied or expired')
        if type(result.get('appid')) is not int or result['appid'] != appid or result.get('scopes') != [scope]:
            raise ValueError('Approved game/scope does not match requested selection')
        generation = uuid.uuid4().hex
        with store.lock():
            if store.read('config.json').get('pairing_id') != previous_generation:
                raise ValueError('Another pairing changed; repeat explicit replacement')
            store.write('config.json', {'server': transport.origin, 'path': os.path.abspath(os.path.expanduser(path)), 'device_token': token, 'pairing_id': generation, 'appid': appid, 'mode': mode, 'expires_at': time.time() + min(2592000, max(1, int(result.get('expires_in', 2592000))))})
            store.write('state.json', {'pairing_id': generation, 'appid': appid, 'mode': mode})
        # Generation binding rejects old queues even if interrupted between writes.
        print('Device paired. Private credential saved; no raw save data will be uploaded.')
        return
    raise ValueError('Pairing expired; run pair again')


class RePairRequired(Exception):
    pass


class Runner:
    def __init__(self, store, transport, config, now=time.time):
        self.store, self.transport, self.config, self.now = store, transport, config, now
        self.appid = config.get('appid', 4231820)
        self.mode = config.get('mode', 'belmont-summary')
        selection(self.appid, self.mode)
        self.kind = 'save_metadata' if self.mode == 'metadata' else 'save_summary'
        self.state = store.read('state.json')
        if (self.state.get('pairing_id') != config.get('pairing_id')
                or self.state.get('appid', 4231820) != self.appid
                or self.state.get('mode', 'belmont-summary') != self.mode):
            self.state = {'pairing_id': config.get('pairing_id'), 'appid': self.appid, 'mode': self.mode}
        self.candidate = None
        self.delay = 60
        self.failures = 0
        self.retry_at = 0

    def tick(self):
        # Serialize configuration changes with each observation/send. An old runner
        # exits after re-pairing rather than overwriting another account's state.
        with self.store.lock():
            if self.config.get('pairing_id') is not None:
                current_config = self.store.read('config.json')
                if (current_config.get('pairing_id') != self.config['pairing_id']
                        or current_config.get('appid', 4231820) != self.appid
                        or current_config.get('mode', 'belmont-summary') != self.mode):
                    raise RePairRequired()
            return self._tick_locked()

    def _tick_locked(self):
        if self.now() >= self.config.get('expires_at', float('inf')):
            self.state['sync_status'] = 'pairing_or_consent_required'
            self.store.write('state.json', self.state)
            raise RePairRequired()
        byte_limit = MAX_METADATA_BYTES if self.mode == 'metadata' else belmont.MAX_BYTES
        current = signature(self.config['path'], byte_limit)
        if current != self.state.get('signature'):
            if current == self.candidate:
                if self.mode == 'metadata':
                    summary = clean_metadata({'size_bytes': current[3], 'modified_ns': current[4]})
                    self.state['observation_status'] = 'metadata_only_contents_and_progress_unknown'
                else:
                    records = watch.snapshot([self.config['path']], single_file_only=True)
                    try:
                        summary = clean_summary(watch.belmont_summary(self.config['path'], records))
                    except watch.SnapshotError:
                        self.state['observation_status'] = 'unsupported_or_invalid_or_unstable_summary_format'
                        self.store.write('state.json', self.state)
                        raise
                    self.state['observation_status'] = 'belmont_four_raw_fields_only'
                if current != signature(self.config['path'], byte_limit):
                    raise watch.SnapshotError('Save changed during observation')
                digest = hashlib.sha256(json.dumps(summary, sort_keys=True).encode()).hexdigest()
                if digest != self.state.get('summary_digest'):
                    self.state['queue'] = {'event_id': str(uuid.uuid4()), 'appid': self.appid,
                                           'kind': self.kind, 'payload': summary}
                    self.state['summary_digest'] = digest
                self.state['signature'] = current
                self.state['observed_at'] = self.now()
                self.store.write('state.json', self.state)
            self.candidate = current
            self.delay = 60
        else:
            self.delay = min(600, self.delay * 2)
        queued = self.state.get('queue')
        if queued and self.now() >= self.retry_at:
            # Rebuild envelope so arbitrary state-file content cannot be uploaded.
            event = str(uuid.UUID(queued['event_id']))
            if queued.get('appid') != self.appid or queued.get('kind') != self.kind:
                raise ValueError('Queued game/mode does not match pairing')
            envelope = {'event_id': event, 'appid': self.appid, 'kind': self.kind,
                        'payload': (clean_metadata if self.mode == 'metadata' else clean_summary)(queued['payload'])}
            try:
                result = self.transport.post('/v1/device/observations', envelope, self.config['device_token'])
                if result.get('accepted') is not True:
                    raise ValueError('Observation not accepted')
            except (urllib.error.URLError, OSError, ValueError) as error:
                if isinstance(error, urllib.error.HTTPError) and error.code in (401, 403):
                    self.state['sync_status'] = 'pairing_or_consent_required'
                    self.store.write('state.json', self.state)
                    raise RePairRequired() from None
                self.failures += 1
                self.retry_at = self.now() + min(3600, 60 * 2 ** min(self.failures, 6)) * random.uniform(.8, 1.2)
                self.state['sync_status'] = 'offline_or_rejected'
                self.store.write('state.json', self.state)
                return
            self.state.pop('queue', None)
            self.state['synced_at'] = self.now()
            self.state['sync_status'] = 'synced'
            self.failures = 0
            self.store.write('state.json', self.state)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('setup', 'discover', 'pair', 'run', 'status'))
    parser.add_argument('--server', help='Explicit HTTPS service origin, required for pairing')
    parser.add_argument('--path', help='One explicitly selected regular save file; never a directory or archive to extract')
    parser.add_argument('--appid', type=int, help='Selected Steam AppID, 1..2147483647; required for pair, asked during setup')
    parser.add_argument('--mode', choices=MODES, help='metadata: size/time only, no decoder needed; belmont-summary: only app 4231820 / format 1.1.3')
    parser.add_argument('--allow-local-test', action='store_true', help='Testing only: permit loopback HTTP')
    parser.add_argument('--enable', action='store_true', help='setup only: explicitly enable/start the user service after pairing')
    args = parser.parse_args(argv)
    if args.appid is not None:
        try:
            selection(args.appid, args.mode or 'metadata')
        except ValueError as error:
            parser.error(str(error))
    if args.command == 'discover':
        from .discovery import discover
        if args.appid not in (None, 4231820):
            parser.error('No automatic path discovery for this game; select an explicit file with --path')
        candidates = discover()
        for candidate in candidates:
            print(str(candidate))
        if not candidates:
            print('No safe candidate found; provide an explicit actual save path during setup.')
        return 0
    if args.command == 'setup':
        from .setup import setup
        if not args.server or args.allow_local_test:
            parser.error('setup requires --server HTTPS; local-test is not permitted')
        return setup(args.server, args.path, enable=args.enable, appid=args.appid, mode=args.mode)
    if args.enable:
        parser.error('--enable applies only to setup')
    try:
        store = Store()
        if args.command == 'pair':
            if not args.server or not args.path or args.appid is None:
                parser.error('pair requires --server, --path and --appid; default mode is metadata')
            pair(store, Transport(args.server, args.allow_local_test), args.path, appid=args.appid, mode=args.mode or 'metadata')
            return 0
        config = store.read('config.json')
        if args.command == 'status':
            state = store.read('state.json')
            print(json.dumps({'paired': bool(config), 'sync_status': state.get('sync_status', 'not_synced'),
                              'observed_at': state.get('observed_at'), 'synced_at': state.get('synced_at'),
                              'queued': bool(state.get('queue')), 'appid': config.get('appid', 4231820) if config else None,
                              'mode': config.get('mode', 'belmont-summary') if config else None,
                              'observation_status': state.get('observation_status', 'not_observed')}))
            return 0
        if args.server or args.path or args.appid is not None or args.mode is not None:
            parser.error('run uses the paired server/path; pair again to change them')
        if not config:
            raise ValueError('Not paired')
        runner = Runner(store, Transport(config['server'], args.allow_local_test), config)
        while True:
            try:
                runner.tick()
            except (watch.SnapshotError, OSError, ValueError, KeyError, TypeError):
                # Never print exception strings, paths, saves, credentials, or HTTP bodies.
                print('Observation unavailable: file unreadable, unstable, oversized, or summary format unsupported. Previous remote observation retained; metadata mode requires separate explicit pairing.', flush=True)
                runner.candidate = None
            time.sleep(runner.delay)
    except RePairRequired:
        print('Pairing expired or permission revoked. Re-pair explicitly before restarting.')
        return 3
    except KeyboardInterrupt:
        return 0
    except (watch.SnapshotError, OSError, ValueError, KeyError, TypeError, EOFError, urllib.error.URLError):
        print('Companion setup/state/network unavailable. Check private configuration and explicit consent; no credentials logged.')
        return 1
