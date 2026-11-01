"""Synthetic native-form contracts; no production requests or real credentials.

ASGI tests always run. Browser tests use an already-installed Playwright Chromium,
intercept every request and forward only assist.example to the local ASGI app.
They skip explicitly when the optional browser runtime is unavailable.
"""
import base64
import hashlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from starlette.testclient import TestClient

from remote_server.app import Config, create_app, COOKIE
from test_remote_browser_flows import FormReader
import test_remote_games as games
from test_remote_library import FakeLibrary
import test_remote_service as service

ORIGIN, REDIRECT = service.ORIGIN, service.REDIRECT


class NativeFormTests(unittest.TestCase):
    sign_in = service.RemoteTests.sign_in
    csrf = service.RemoteTests.csrf
    owner = games.GameSelectionTests.owner
    catalog = games.GameSelectionTests.catalog
    choose = games.GameSelectionTests.choose

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.steam, self.library = service.FakeSteam(), FakeLibrary()
        self.app = create_app(
            Config(ORIGIN, str(Path(self.temp.name)/'forms.sqlite'), (REDIRECT,)),
            steam=self.steam, library_reader=self.library,
            achievement_reader=SimpleNamespace(configured=False))
        self.client = TestClient(self.app, base_url=ORIGIN, follow_redirects=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.sign_in()

    def form(self, path, action):
        response = self.client.get(path, headers={'accept': 'text/html'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get_list('referrer-policy'), ['strict-origin'])
        form = next(f for f in FormReader(response.text).forms if f['action'] == action)
        return form['fields']

    def pending_oauth(self):
        client = self.client.post('/register', json={
            'redirect_uris': [REDIRECT], 'token_endpoint_auth_method': 'none',
            'scope': 'progress.read'}).json()['client_id']
        verifier = 'synthetic-verifier-' * 4
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        response = self.client.get('/authorize', params={
            'client_id': client, 'redirect_uri': REDIRECT, 'response_type': 'code',
            'scope': 'progress.read', 'state': 'synthetic-state',
            'code_challenge': challenge, 'code_challenge_method': 'S256',
            'resource': ORIGIN+'/mcp'})
        self.assertEqual(response.status_code, 302)
        return response.headers['location'], client, verifier

    def reject_invalid_submissions(self, path, fields):
        # Includes the original no-referrer native-form output: literal null Origin.
        for origin in (None, 'null', 'https://other.example'):
            with self.subTest(path=path, origin=origin):
                headers = {'accept': 'text/html'}
                if origin is not None:
                    headers['origin'] = origin
                self.assertEqual(self.client.post(path, data=fields, headers=headers).status_code, 403)
        for changes in ({'csrf': 'synthetic-stale'}, {'csrf': ''}):
            self.assertEqual(self.client.post(path, data=fields | changes,
                headers={'origin': ORIGIN, 'accept': 'text/html'}).status_code, 403)

    def submit(self, path, fields):
        return self.client.post(path, data=fields, headers={'origin': ORIGIN, 'accept': 'text/html'})

    def test_library_form_retains_guards_and_opt_in_does_not_fetch(self):
        fields = self.form('/games', '/account/library/permission')
        self.reject_invalid_submissions('/account/library/permission', fields)
        self.assertFalse(self.app.state.store.library(self.owner())['enabled'])
        self.assertEqual(self.library.calls, [])
        self.assertEqual(self.submit('/account/library/permission', fields).status_code, 303)
        self.assertTrue(self.app.state.store.library(self.owner())['enabled'])
        self.assertEqual(self.library.calls, [])
        refresh = self.form('/games', '/account/library/refresh')
        self.reject_invalid_submissions('/account/library/refresh', refresh)
        self.assertEqual(self.library.calls, [])
        self.assertEqual(self.submit('/account/library/refresh', refresh).status_code, 303)
        self.assertEqual(len(self.library.calls), 1)

    def test_pair_approval_form_retains_guards_and_exact_game_scope(self):
        pair = self.client.post('/v1/devices/pair/start', json={
            'appid': 4231820, 'scopes': ['saves.summary']}).json()
        fields = self.form('/devices/approve', '') | {
            'user_code': pair['user_code'], 'appid': '4231820', 'saves.summary': 'yes'}
        self.reject_invalid_submissions('/devices/approve', fields)
        with self.app.state.store.db() as db:
            self.assertIsNone(db.execute('SELECT owner FROM pairings').fetchone()[0])
            self.assertEqual(db.execute('SELECT count(*) FROM grants').fetchone()[0], 0)
        wrong = fields | {'appid': '1245620'}
        self.assertEqual(self.submit('/devices/approve', wrong).status_code, 422)
        self.assertEqual(self.submit('/devices/approve', fields).status_code, 200)
        poll = self.client.post('/v1/devices/pair/poll', json={'device_code':pair['device_code']})
        self.assertEqual(poll.status_code, 200)
        self.assertEqual(poll.json()['status'], 'approved')

    def test_oauth_consent_form_retains_guards_pkce_state_and_issuer(self):
        location, client, verifier = self.pending_oauth()
        fields = self.form(location, '')
        self.reject_invalid_submissions('/oauth/consent', fields)
        self.assertIsNotNone(self.app.state.provider.get_pending(fields['request']))
        consent = self.submit('/oauth/consent', fields)
        self.assertEqual(consent.status_code, 303)
        callback = parse_qs(urlsplit(consent.headers['location']).query)
        self.assertEqual(callback['state'], ['synthetic-state'])
        self.assertEqual(callback['iss'], [ORIGIN+'/'])
        token = self.client.post('/token', data={
            'client_id': client, 'grant_type': 'authorization_code', 'code': callback['code'][0],
            'redirect_uri': REDIRECT, 'code_verifier': verifier, 'resource': ORIGIN+'/mcp'})
        self.assertEqual(token.status_code, 200)
        self.assertEqual(token.json()['scope'], 'progress.read')

    def test_stale_form_after_session_rotation_still_fails(self):
        old = self.form('/games', '/account/library/permission')
        self.sign_in()
        self.assertEqual(self.submit('/account/library/permission', old).status_code, 403)
        fresh = self.form('/games', '/account/library/permission')
        self.assertEqual(self.submit('/account/library/permission', fresh).status_code, 303)

    def test_policy_singleton_and_other_boundary_headers_unchanged(self):
        for path in ('/games', '/devices/approve', '/data-handling'):
            response = self.client.get(path)
            self.assertEqual(response.headers.get_list('referrer-policy'), ['strict-origin'])
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(response.headers['strict-transport-security'], 'max-age=31536000')
            self.assertIn("form-action 'self'", response.headers['content-security-policy'])
            self.assertIn("frame-ancestors 'none'", response.headers['content-security-policy'])
        # Browser error responses also have exactly the same document policy.
        response = self.client.post('/account/library/permission', data={},
                                    headers={'origin':'null','accept':'text/html'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.headers.get_list('referrer-policy'), ['strict-origin'])

    def browser_page(self, *, old_policy=False):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest('Optional Playwright is not installed')
        playwright = sync_playwright().start()
        self.addCleanup(playwright.stop)
        if not Path(playwright.chromium.executable_path).exists():
            self.skipTest('Optional Chromium executable is not installed')
        browser = playwright.chromium.launch(headless=True, chromium_sandbox=True)
        self.addCleanup(browser.close)
        context = browser.new_context()
        context.add_cookies([{'name': COOKIE, 'value': self.client.cookies[COOKIE],
                             'url': ORIGIN, 'secure': True, 'httpOnly': True, 'sameSite': 'Lax'}])
        records = []

        def bridge(route):
            request = route.request
            headers = request.all_headers()
            records.append((request.method, urlsplit(request.url).path,
                            headers.get('origin'), headers.get('referer')))
            if not request.url.startswith(ORIGIN+'/'):
                # Fulfill synthetic callback locally; never contact Claude/Steam.
                route.fulfill(status=200, content_type='text/html', body='Synthetic callback')
                return
            response = self.client.request(request.method, request.url,
                                           content=request.post_data_buffer, headers=headers)
            output_headers = dict(response.headers)
            if old_policy:
                output_headers['referrer-policy'] = 'no-referrer'
            route.fulfill(status=response.status_code, headers=output_headers, body=response.content)

        context.route('**/*', bridge)
        return context.new_page(), records

    def test_browser_reproduces_original_policy_rejection(self):
        page, records = self.browser_page(old_policy=True)
        page.goto(ORIGIN+'/games')
        with page.expect_navigation():
            page.locator('form[action="/account/library/permission"] button').click()
        self.assertIn(('POST', '/account/library/permission', 'null', None), records)
        self.assertIn('Код ответа: 403', page.content())
        self.assertFalse(self.app.state.store.library(self.owner())['enabled'])

    def test_browser_native_library_forms_use_exact_origin_without_url_details(self):
        page, records = self.browser_page()
        page.goto(ORIGIN+'/games?synthetic_private_context=do-not-forward')
        with page.expect_navigation():
            page.locator('form[action="/account/library/permission"] button').click()
        self.assertTrue(self.app.state.store.library(self.owner())['enabled'])
        self.assertEqual(self.library.calls, [])
        with page.expect_navigation():
            page.locator('form[action="/account/library/refresh"] button').click()
        self.assertEqual(len(self.library.calls), 1)
        for path in ('/account/library/permission', '/account/library/refresh'):
            self.assertIn(('POST', path, ORIGIN, ORIGIN+'/'), records)

    def test_browser_native_pair_approval_and_oauth_consent(self):
        pair = self.client.post('/v1/devices/pair/start', json={
            'appid': 4231820, 'scopes': ['saves.summary']}).json()
        location, client, verifier = self.pending_oauth()
        page, records = self.browser_page()
        page.goto(ORIGIN+'/devices/approve')
        page.locator('input[name="user_code"]').fill(pair['user_code'])
        page.locator('select[name="appid"]').select_option('4231820')
        page.locator('input[name="saves.summary"]').check()
        with page.expect_navigation():
            page.locator('form button').click()
        self.assertEqual(self.client.post('/v1/devices/pair/poll',
                         json={'device_code':pair['device_code']}).json()['status'], 'approved')
        page.goto(location)
        with page.expect_navigation():
            page.locator('form button').click()
        for path in ('/devices/approve', '/oauth/consent'):
            self.assertIn(('POST', path, ORIGIN, ORIGIN+'/'), records)
        self.assertIn(('GET', urlsplit(REDIRECT).path, None, ORIGIN+'/'), records)
        self.assertNotIn('/oauth/consent', records[-1][3] or '')
        self.assertNotIn('request=', records[-1][3] or '')


if __name__ == '__main__':
    unittest.main()
