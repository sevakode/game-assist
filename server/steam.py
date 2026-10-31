"""Opt-in Steam boundary; caller enforces session/state and per-game consent.

No credentials are requested from players. SGC_STEAM_API_KEY is an operator
secret. Nonce cache is process-local: run this local prototype with one worker;
a hosted deployment needs a shared atomic replay store and session lifecycle.
"""
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit

import httpx

OPENID_ENDPOINT = 'https://steamcommunity.com/openid/login'
OPENID_NS = 'http://specs.openid.net/auth/2.0'
ACHIEVEMENTS_ENDPOINT = 'https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v1/'
STEAM_ID = re.compile(r'[0-9]{17}')


class SteamError(ValueError):
    """Safe error code only; never include upstream request or credential text."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class SteamService:
    def __init__(self, api_key=None, transport=None, clock=time.time):
        self._api_key = os.environ.get('SGC_STEAM_API_KEY', '') if api_key is None else api_key
        self._transport = transport
        self._clock = clock
        self._nonces = {}
        self._nonce_lock = threading.Lock()

    @property
    def configured(self):
        return bool(self._api_key)

    @staticmethod
    def login_url(return_to, realm=None):
        """Return navigation URL. Caller embeds one-time browser-bound state."""
        parts = urlsplit(return_to)
        if (parts.scheme not in ('http', 'https') or not parts.netloc or parts.fragment
                or parts.username or parts.password
                or (parts.scheme == 'http' and parts.hostname not in ('127.0.0.1', 'localhost', '::1'))):
            raise SteamError('invalid_return_to')
        origin = f'{parts.scheme}://{parts.netloc}'
        if realm is not None and realm.rstrip('/') != origin:
            raise SteamError('invalid_realm')
        return OPENID_ENDPOINT + '?' + urlencode({
            'openid.ns': OPENID_NS, 'openid.mode': 'checkid_setup',
            'openid.return_to': return_to, 'openid.realm': origin + '/',
            'openid.identity': OPENID_NS + '/identifier_select',
            'openid.claimed_id': OPENID_NS + '/identifier_select',
        })

    def _request(self, method, url, limit=1048576, **kwargs):
        try:
            with httpx.Client(transport=self._transport, timeout=httpx.Timeout(8.0, connect=3.0),
                              follow_redirects=False, trust_env=False) as client:
                with client.stream(method, url, **kwargs) as response:
                    body = bytearray()
                    started = time.monotonic()
                    for chunk in response.iter_bytes():
                        if len(body) + len(chunk) > limit or time.monotonic() - started > 12:
                            raise SteamError('upstream_unavailable')
                        body.extend(chunk)
                    return response.status_code, bytes(body)
        except (httpx.HTTPError, OSError):
            raise SteamError('upstream_unavailable') from None

    def verify_callback(self, params, expected_return_to):
        """Verify direct Steam assertion, returning SteamID. No account writes.

        Pass QueryParams or a sequence of pairs to detect duplicate parameters.
        Caller must validate and consume its own one-time browser state first.
        """
        pairs = list(params.multi_items()) if hasattr(params, 'multi_items') else list(params.items()) if hasattr(params, 'items') else list(params)
        if len(pairs) > 40 or len({k for k, _ in pairs}) != len(pairs):
            raise SteamError('invalid_assertion')
        if any(not isinstance(k, str) or not isinstance(v, str) or len(k) > 100 or len(v) > 4096 for k, v in pairs):
            raise SteamError('invalid_assertion')
        p = {k: v for k, v in pairs if k.startswith('openid.')}
        required = {'op_endpoint', 'claimed_id', 'identity', 'return_to', 'response_nonce', 'assoc_handle'}
        if (p.get('openid.ns') != OPENID_NS or p.get('openid.mode') != 'id_res'
                or p.get('openid.op_endpoint') != OPENID_ENDPOINT
                or p.get('openid.return_to') != expected_return_to
                or not p.get('openid.sig')
                or not required.issubset(set(p.get('openid.signed', '').split(',')))
                or any(not p.get('openid.' + field) for field in required)):
            raise SteamError('invalid_assertion')
        identity = p['openid.claimed_id']
        match = re.fullmatch(r'https?://steamcommunity\.com/openid/id/([0-9]{17})', identity)
        if not match or p['openid.identity'] != identity:
            raise SteamError('invalid_identity')
        nonce = p['openid.response_nonce']
        try:
            stamp = datetime.strptime(nonce[:20], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            raise SteamError('invalid_nonce') from None
        now = self._clock()
        if len(nonce) <= 20 or len(nonce) > 256 or not -30 <= now - stamp <= 300:
            raise SteamError('invalid_nonce')
        # Reserve before I/O, preventing simultaneous replay. Failed assertions
        # consume the nonce too; restart sign-in rather than retrying assertions.
        with self._nonce_lock:
            self._nonces = {n: expiry for n, expiry in self._nonces.items() if expiry >= now}
            if nonce in self._nonces:
                raise SteamError('replayed_assertion')
            if len(self._nonces) >= 4096:
                raise SteamError('verification_busy')
            self._nonces[nonce] = stamp + 300
        p['openid.mode'] = 'check_authentication'
        status, body = self._request('POST', OPENID_ENDPOINT, limit=16384, data=p)
        try:
            lines = [line.split(':', 1) for line in body.decode('utf-8').splitlines() if line]
            if any(len(line) != 2 for line in lines) or len({line[0] for line in lines}) != len(lines):
                raise ValueError()
            answer = dict(lines)
        except (UnicodeError, ValueError):
            raise SteamError('invalid_verification') from None
        if status != 200 or answer.get('is_valid') != 'true' or answer.get('ns') != OPENID_NS:
            raise SteamError('invalid_verification')
        return match.group(1)

    def get_achievements(self, steamid, appid):
        """Read only one explicitly permitted game's achievements; never raw saves."""
        if not isinstance(steamid, str) or not STEAM_ID.fullmatch(steamid) or type(appid) is not int or not 0 < appid < 2**32:
            raise SteamError('invalid_subject')
        def result(status, message, achievements=None):
            return {'status': status, 'message': message, 'achievements': achievements or [], 'source': 'steam_web_api'}
        if not self.configured:
            return result('not_configured', 'Operator Steam API access is not configured. Players do not need to supply a key.')
        try:
            status, body = self._request('GET', ACHIEVEMENTS_ENDPOINT,
                params={'steamid': steamid, 'appid': appid, 'l': 'english'},
                headers={'x-webapi-key': self._api_key})
            if status in (401, 403):
                return result('unavailable', 'Steam denied API access; this does not establish profile privacy.')
            if status != 200:
                return result('unavailable', 'Steam achievements are temporarily unavailable.')
            stats = json.loads(body).get('playerstats')
            if not isinstance(stats, dict):
                raise ValueError()
            if stats.get('success') is not True:
                if 'private' in str(stats.get('error', '')).lower():
                    return result('private', 'Steam reports this profile is private. No progress was inferred.')
                return result('unavailable', 'Steam did not expose achievement data for this game.')
            rows = stats.get('achievements')
            if not isinstance(rows, list) or len(rows) > 10000:
                raise ValueError()
            achievements = []
            seen = set()
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError()
                name, achieved, unlocked = row.get('apiname'), row.get('achieved'), row.get('unlocktime', 0)
                display = row.get('name')
                if (not isinstance(name, str) or not 0 < len(name) <= 200 or name in seen
                        or type(achieved) is not int or achieved not in (0, 1)
                        or type(unlocked) is not int or unlocked < 0
                        or (display is not None and (not isinstance(display, str) or len(display) > 300))):
                    raise ValueError()
                seen.add(name)
                achievements.append({'apiname': name, 'name': display, 'achieved': bool(achieved), 'unlock_time': unlocked or None})
            return result('ok', 'Achievement absence alone does not establish incomplete game state.', achievements)
        except (SteamError, ValueError, TypeError, AttributeError):
            return result('unavailable', 'Steam returned unavailable or invalid achievement data.')
