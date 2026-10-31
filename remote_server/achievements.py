"""Opt-in, bounded Steam reader. Only verified-unlocked rows leave this module.

No schema/catalog download, background polling, or player-supplied credentials.
The caller is responsible for current account/game consent before and after I/O.
"""
from contextvars import ContextVar
import json
import logging
import os
import re
import threading
import time

import httpx

ENDPOINT = 'https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v1/'
MAX_RESPONSE = 1024 * 1024
MAX_RESULT = 128 * 1024
_private_request = ContextVar('game_assist_steam_private_request', default=False)
_factory_lock = threading.Lock()
_factory_installed = False


def _install_private_transport_logging():
    """Redact only this reader's httpx/httpcore records, before any handlers.

    Logger filters on a parent do not cover child loggers; a narrowly scoped
    record factory also covers future httpcore child names and debug headers.
    The previous factory and all unrelated security/audit records are preserved.
    No per-request global logger level changes or race-prone filter removal.
    """
    global _factory_installed
    with _factory_lock:
        if _factory_installed:
            return
        previous = logging.getLogRecordFactory()

        def factory(*args, **kwargs):
            record = previous(*args, **kwargs)
            if _private_request.get() and (record.name == 'httpx' or record.name.startswith('httpx.')
                    or record.name == 'httpcore' or record.name.startswith('httpcore.')):
                record.msg = 'Steam API transport activity (private request details redacted)'
                record.args = ()
                record.exc_info = None
                record.exc_text = None
                record.stack_info = None
            return record

        logging.setLogRecordFactory(factory)
        _factory_installed = True


def _result(status, rows=None):
    return {'status': status, 'achievements': rows or [], 'source': 'steam_web_api'}


def _unique(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError('invalid response')
    return result


def _reject_constant(_):
    raise ValueError('invalid response')


class AchievementReader:
    def __init__(self, api_key=None, transport=None, monotonic=time.monotonic):
        self._api_key = os.environ.get('SGC_STEAM_API_KEY', '') if api_key is None else api_key
        self._transport = transport
        self._monotonic = monotonic
        _install_private_transport_logging()

    @property
    def configured(self):
        return isinstance(self._api_key, str) and bool(self._api_key.strip())

    def get_unlocked(self, steamid, appid):
        if not self.configured:
            return _result('not_configured')
        if not isinstance(steamid, str) or not re.fullmatch(r'[0-9]{17}', steamid) or type(appid) is not int or not 0 < appid <= 2147483647:
            return _result('unavailable')
        token = _private_request.set(True)
        try:
            started = self._monotonic()
            with httpx.Client(transport=self._transport, timeout=httpx.Timeout(8.0, connect=3.0),
                              follow_redirects=False, trust_env=False) as client:
                with client.stream('GET', ENDPOINT, params={'steamid': steamid, 'appid': appid, 'l': 'english'},
                                   headers={'x-webapi-key': self._api_key}) as response:
                    if response.status_code != 200:
                        return _result('unavailable')
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        if len(body) + len(chunk) > MAX_RESPONSE or self._monotonic() - started > 12:
                            return _result('unavailable')
                        body.extend(chunk)
                    if self._monotonic() - started > 12:
                        return _result('unavailable')
            data = json.loads(body, object_pairs_hook=_unique, parse_constant=_reject_constant)
            stats = data.get('playerstats') if isinstance(data, dict) else None
            if (not isinstance(stats, dict) or stats.get('success') is not True
                    or stats.get('steamID') != steamid
                    or ('appid' in stats and (type(stats['appid']) is not int or stats['appid'] != appid))):
                return _result('unavailable')
            rows = stats.get('achievements')
            if not isinstance(rows, list) or len(rows) > 10000:
                return _result('unavailable')
            unlocked = []
            seen = set()
            for row in rows:
                if not isinstance(row, dict):
                    return _result('unavailable')
                name, achieved = row.get('apiname'), row.get('achieved')
                if not isinstance(name, str) or not 0 < len(name) <= 200 or not name.isprintable() or name in seen or type(achieved) is not int or achieved not in (0, 1):
                    return _result('unavailable')
                seen.add(name)
                if achieved != 1:
                    continue  # Never retain/project names, descriptions, times of locked rows.
                display, stamp = row.get('name'), row.get('unlocktime', 0)
                if ((display is not None and (not isinstance(display, str) or len(display) > 300 or (display and not display.isprintable())))
                        or type(stamp) is not int or not 0 <= stamp <= 2**63 - 1):
                    return _result('unavailable')
                unlocked.append({'apiname': name, 'name': display, 'unlock_time': stamp or None})
                if len(unlocked) > 500:
                    return _result('unavailable')
            result = _result('ok', unlocked)
            if len(json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) > MAX_RESULT:
                return _result('unavailable')
            return result
        except (httpx.HTTPError, OSError, ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
            # Deliberately do not log/return an exception, URL, upstream body, or key.
            return _result('unavailable')
        finally:
            _private_request.reset(token)
