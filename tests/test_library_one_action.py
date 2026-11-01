"""One explicit consent+refresh action, using only mock HTTP and disposable SQLite."""
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from starlette.testclient import TestClient

from remote_server.app import COOKIE, Config, create_app, digest
from remote_server.library_reader import ENDPOINT, LibraryReader
from test_remote_browser_flows import FormReader
import test_remote_games as games
import test_remote_service as service

ORIGIN, REDIRECT = service.ORIGIN, service.REDIRECT
PERMISSION, REFRESH = '/account/library/permission', '/account/library/refresh'
HTML = {'origin': ORIGIN, 'accept': 'text/html'}


class OneActionLibraryTests(unittest.TestCase):
    sign_in = service.RemoteTests.sign_in
    csrf = service.RemoteTests.csrf
    owner = games.GameSelectionTests.owner

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.calls = []
        self.body = {'response': {'game_count': 1, 'games': [
            {'appid': 570, 'name': 'Synthetic Game', 'playtime_forever': 123}]}}
        self.status = 200
        self.during_fetch = None
        self.reader = LibraryReader('SYNTHETIC_KEY', transport=httpx.MockTransport(self.transport))
        self.steam = service.FakeSteam()
        self.app = create_app(Config(ORIGIN, str(Path(self.temp.name)/'library.sqlite'), (REDIRECT,)),
                              steam=self.steam, library_reader=self.reader,
                              achievement_reader=SimpleNamespace(configured=False))
        self.store = self.app.state.store
        self.client = TestClient(self.app, base_url=ORIGIN, follow_redirects=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.sign_in()

    def transport(self, request):
        self.calls.append(request)
        if self.during_fetch:
            self.during_fetch()
        return httpx.Response(self.status, json=self.body)

    def post(self, path=PERMISSION, **changes):
        fields = {'csrf': self.csrf()}
        if path == PERMISSION:
            fields.update(enabled='yes', action='enable_and_refresh')
        return self.client.post(path, data=fields | changes, headers=HTML)

    def permission_only(self, enabled='yes'):
        return self.client.post(PERMISSION, data={'csrf': self.csrf(), 'enabled': enabled}, headers=HTML)

    def state(self, owner=None):
        return self.store.library(owner or self.owner())

    def reset_cache(self):
        with self.store.db() as db:
            db.execute('DELETE FROM library_cache')
            db.execute('DELETE FROM limits')

    def test_rendered_action_fetches_once_and_preserves_all_other_grants(self):
        page = self.client.get('/games').text
        form = next(f for f in FormReader(page).forms if f['action'] == PERMISSION)
        self.assertIn('Разрешить и загрузить игры', page)
        self.assertEqual(form['fields'], {'csrf': self.csrf(), 'enabled': 'yes', 'action': 'enable_and_refresh'})
        self.assertEqual(self.calls, [])
        response = self.client.post(PERMISSION, data=form['fields'], headers=HTML)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['location'], '/games#steam-library')
        self.assertEqual(len(self.calls), 1)
        request = self.calls[0]
        self.assertEqual(request.method, 'GET')
        self.assertEqual(str(request.url).split('?')[0], ENDPOINT)
        self.assertEqual(json.loads(request.url.params['input_json']), {
            'steamid': '76561198000000001', 'include_appinfo': True, 'include_played_free_games': True})
        self.assertEqual(request.headers['x-webapi-key'], 'SYNTHETIC_KEY')
        self.assertNotIn('cookie', request.headers)
        self.assertEqual(self.state()['games'], [{'appid': 570, 'name': 'Synthetic Game'}])
        self.assertNotIn('playtime', json.dumps(self.state()))
        with self.store.db() as db:
            for table in ('game_registrations', 'game_selections', 'grants', 'achievement_cache', 'oauth_tokens'):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0], 0, table)
        self.client.get('/games')
        self.assertEqual(len(self.calls), 1)

    def test_permission_only_remains_no_io_and_manual_refresh_has_parity(self):
        self.assertEqual(self.permission_only().status_code, 303)
        self.assertEqual(self.state()['status'], 'not_requested')
        self.client.get('/games')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.post(REFRESH).status_code, 303)
        manual = self.state()
        self.reset_cache()
        self.assertEqual(self.post().status_code, 303)
        combined = self.state()
        self.assertEqual({k:v for k,v in manual.items() if k != 'received_at'},
                         {k:v for k,v in combined.items() if k != 'received_at'})
        self.assertEqual(self.permission_only('no').status_code, 303)
        self.assertFalse(self.state()['enabled'])
        self.assertEqual(len(self.calls), 2)

    def test_rejected_origin_csrf_fields_action_and_session_never_fetch_or_grant(self):
        fields = {'csrf': self.csrf(), 'enabled': 'yes', 'action': 'enable_and_refresh'}
        for origin in (None, 'null', 'https://other.example', ORIGIN+'/'):
            headers = {'accept': 'text/html'}
            if origin is not None:
                headers['origin'] = origin
            self.assertEqual(self.client.post(PERMISSION, data=fields, headers=headers).status_code, 403)
        self.assertEqual(self.post(csrf='stale').status_code, 403)
        for changes in ({'owner': 'other'}, {'steamid': '76561198000000002'}, {'action': ''},
                        {'action': 'refresh'}, {'enabled': 'no'}, {'enabled': 'true'}, {'scope': 'library.read'}):
            self.assertEqual(self.post(**changes).status_code, 422, changes)
        duplicate = 'csrf='+fields['csrf']+'&enabled=yes&action=enable_and_refresh&action=enable_and_refresh'
        self.assertEqual(self.client.post(PERMISSION, content=duplicate,
            headers=HTML | {'content-type': 'application/x-www-form-urlencoded'}).status_code, 403)
        self.assertFalse(self.state()['enabled'])
        self.client.cookies.clear()
        self.assertEqual(self.client.post(PERMISSION, data=fields, headers=HTML).status_code, 401)
        self.assertEqual(self.calls, [])

    def test_not_configured_and_capacity_do_not_leave_consent(self):
        with patch.object(self.reader, '_api_key', ''):
            self.assertEqual(self.post().status_code, 503)
        with patch('remote_server.app.LIBRARY_ROWS_GLOBAL', 0):
            response = self.post()
            self.assertEqual(response.status_code, 429)
            self.assertNotIn('Разрешение на чтение библиотеки было сохранено', response.text)
        self.assertFalse(self.state()['enabled'])
        self.assertEqual(self.calls, [])

    def test_owner_and_global_limits_leave_honest_permission_only_outcome(self):
        for bucket, maximum in (('library-owner:'+digest(self.owner()), 4), ('library-global', 60)):
            with self.subTest(bucket=bucket):
                self.reset_cache()
                for _ in range(maximum):
                    self.store.limit(bucket, maximum, 3600)
                response = self.post()
                self.assertEqual(response.status_code, 429)
                self.assertIn('Разрешение на чтение библиотеки было сохранено', response.text)
                self.assertIn('/games#steam-library', response.text)
                self.assertEqual(self.state()['status'], 'not_requested')
                self.assertTrue(self.state()['enabled'])
        self.assertEqual(self.calls, [])

    def test_private_empty_and_transport_failure_are_unknown_not_zero_owned(self):
        for body, status in (({'response': {}}, 200), ({'response': {'game_count': 0, 'games': []}}, 200),
                             ({}, 503)):
            with self.subTest(body=body, status=status):
                self.reset_cache()
                self.body, self.status = body, status
                self.assertEqual(self.post().status_code, 303)
                self.assertTrue(self.state()['enabled'])
                self.assertEqual(self.state()['status'], 'unavailable')
                self.assertEqual(self.state()['games'], [])
                page = self.client.get('/games').text
                self.assertIn('Разрешение включено, но список получить не удалось', page)
                self.assertIn('не означает, что у тебя нет игр', page)

    def test_shared_reader_slots_full_does_not_fetch_or_lose_saved_consent(self):
        blocked_slots = threading.BoundedSemaphore(0)
        with patch('remote_server.app.threading.BoundedSemaphore', return_value=blocked_slots):
            app = create_app(Config(ORIGIN, str(Path(self.temp.name)/'library.sqlite'), (REDIRECT,)),
                             steam=self.steam, library_reader=self.reader,
                             achievement_reader=SimpleNamespace(configured=False))
        with TestClient(app, base_url=ORIGIN, follow_redirects=False, cookies=self.client.cookies) as client:
            response = client.post(PERMISSION, data={'csrf': self.csrf(), 'enabled': 'yes',
                                                    'action': 'enable_and_refresh'}, headers=HTML)
        self.assertEqual(response.status_code, 429)
        self.assertIn('Разрешение на чтение библиотеки было сохранено', response.text)
        self.assertTrue(self.state()['enabled'])
        self.assertEqual(self.state()['status'], 'not_requested')
        self.assertEqual(self.calls, [])

    def test_exception_is_sanitized_and_manual_retry_retains_cooldown(self):
        def fail():
            raise httpx.ReadTimeout('SYNTHETIC_PRIVATE_ERROR')
        self.during_fetch = fail
        response = self.post()
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.state()['status'], 'unavailable')
        self.assertNotIn('SYNTHETIC_PRIVATE_ERROR', self.client.get('/games').text)
        self.assertEqual(self.post(REFRESH).status_code, 429)
        self.assertEqual(len(self.calls), 1)

    def test_concurrent_duplicate_and_manual_refresh_share_one_reservation(self):
        entered, release = threading.Event(), threading.Event()
        self.during_fetch = lambda: (entered.set(), release.wait(5))
        fields = {'csrf': self.csrf(), 'enabled': 'yes', 'action': 'enable_and_refresh'}
        with ThreadPoolExecutor(2) as pool:
            pending = pool.submit(self.client.post, PERMISSION, data=fields, headers=HTML)
            try:
                self.assertTrue(entered.wait(5))
                self.assertEqual(self.post().status_code, 429)
                self.assertEqual(self.post(REFRESH).status_code, 429)
                self.assertEqual(len(self.calls), 1)
            finally:
                release.set()
            self.assertEqual(pending.result(timeout=5).status_code, 303)
        self.assertEqual(self.state()['status'], 'ok')

    def test_revoke_regrant_during_io_cannot_restore_old_data_for_either_action(self):
        for path in (PERMISSION, REFRESH):
            with self.subTest(path=path):
                self.reset_cache()
                if path == REFRESH:
                    self.permission_only()
                entered, release = threading.Event(), threading.Event()
                self.during_fetch = lambda: (entered.set(), release.wait(5))
                with ThreadPoolExecutor(2) as pool:
                    pending = pool.submit(self.post, path)
                    try:
                        self.assertTrue(entered.wait(5))
                        self.assertEqual(self.permission_only('no').status_code, 303)
                        self.assertEqual(self.permission_only().status_code, 303)
                    finally:
                        release.set()
                    self.assertEqual(pending.result(timeout=5).status_code, 409)
                self.assertEqual(self.state()['status'], 'not_requested')
                self.assertEqual(self.state()['games'], [])

    def test_account_revoke_during_io_does_not_restore_consent(self):
        def revoke():
            self.assertEqual(self.client.post('/account/revoke', data={'csrf': self.csrf()}, headers=HTML).status_code, 303)
        self.during_fetch = revoke
        self.assertEqual(self.post().status_code, 409)
        self.assertFalse(self.state()['enabled'])

    def test_expired_session_after_io_cannot_write_cache_for_either_action(self):
        for path in (PERMISSION, REFRESH):
            with self.subTest(path=path):
                self.reset_cache()
                self.sign_in()
                owner = self.owner()
                if path == REFRESH:
                    self.permission_only()
                def expire():
                    with self.store.db() as db:
                        db.execute('UPDATE sessions SET expires=0 WHERE hash=?', (digest(self.client.cookies[COOKIE]),))
                self.during_fetch = expire
                self.assertEqual(self.post(path).status_code, 401)
                self.assertEqual(self.state(owner)['status'], 'not_requested')
                self.assertEqual(self.state(owner)['games'], [])

    def test_logout_or_owner_change_after_io_cannot_write_cache(self):
        for mutation in ('logout', 'owner', 'csrf'):
            with self.subTest(mutation=mutation):
                self.reset_cache()
                self.sign_in()
                owner = self.owner()
                def invalidate():
                    if mutation == 'logout':
                        self.assertEqual(self.client.post('/logout', data={'csrf': self.csrf()}, headers=HTML).status_code, 303)
                    else:
                        with self.store.db() as db:
                            db.execute('UPDATE sessions SET '+mutation+'=? WHERE hash=?',
                                       ('synthetic-changed', digest(self.client.cookies[COOKIE])))
                self.during_fetch = invalidate
                self.assertEqual(self.post().status_code, 401)
                self.assertEqual(self.state(owner)['games'], [])

    def test_consent_generation_changed_before_io_is_not_reused(self):
        original = self.store.limit
        def change_grant(bucket, *args):
            original(bucket, *args)
            if bucket.startswith('library-owner:'):
                with self.store.db() as db:
                    db.execute("UPDATE library_cache SET consent_id='synthetic-new-generation'")
        with patch.object(self.store, 'limit', side_effect=change_grant):
            self.assertEqual(self.post().status_code, 409)
        self.assertEqual(self.state()['status'], 'not_requested')
        self.assertEqual(self.calls, [])

    def test_replaced_refresh_nonce_cannot_be_overwritten(self):
        def supersede():
            with self.store.db() as db:
                db.execute("UPDATE library_cache SET refresh_nonce='synthetic-new-reservation'")
        self.during_fetch = supersede
        self.assertEqual(self.post().status_code, 409)
        self.assertEqual(self.state()['status'], 'not_requested')
        self.assertEqual(self.state()['games'], [])

    def test_expired_session_before_io_does_not_fetch(self):
        original = self.store.limit
        def expire(bucket, *args):
            original(bucket, *args)
            with self.store.db() as db:
                db.execute('UPDATE sessions SET expires=0')
        with patch.object(self.store, 'limit', side_effect=expire):
            self.assertEqual(self.post().status_code, 401)
        self.assertEqual(self.calls, [])

    def test_second_owner_never_reads_first_owner_result(self):
        self.assertEqual(self.post().status_code, 303)
        first = self.owner()
        self.client.cookies.clear()
        self.sign_in('76561198000000002')
        self.assertFalse(self.state()['enabled'])
        self.assertEqual(self.post(REFRESH).status_code, 403)
        self.assertEqual(self.post().status_code, 303)
        self.assertEqual(json.loads(self.calls[-1].url.params['input_json'])['steamid'], '76561198000000002')
        self.permission_only('no')
        self.assertEqual(self.state(first)['status'], 'ok')


if __name__ == '__main__':
    unittest.main()
