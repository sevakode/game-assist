import asyncio
import base64
import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import unittest
import tempfile
from pathlib import Path
from mcp.server.auth.provider import AuthorizationParams, AuthorizeError, RegistrationError, TokenError
from mcp.server.auth.routes import create_auth_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.testclient import TestClient

from remote_server.oauth import OAuthProvider

ISSUER = 'https://assist.example'
REDIRECT = 'https://client.example/callback'
VERIFIER = 'a' * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip('=')


def run(awaitable):
    return asyncio.run(awaitable)



def authorize(provider, client, **changes):
    args = dict(state='random-client-state', scopes=['progress.read'], code_challenge=CHALLENGE,
        redirect_uri=REDIRECT, redirect_uri_provided_explicitly=True, resource=ISSUER+'/mcp')
    args.update(changes)
    url = run(provider.authorize(client, AuthorizationParams(**args)))
    return parse_qs(urlsplit(url).query)['request'][0]


def issue_code(provider, client, subject='user-a'):
    rid = authorize(provider, client)
    return parse_qs(urlsplit(provider.approve(rid, subject)).query)['code'][0]


class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        provider = OAuthProvider(Path(self.tmp.name)/'db.sqlite', ISSUER, [REDIRECT], database=getattr(self, 'database', None))
        client = OAuthClientInformationFull(client_id='client', redirect_uris=[REDIRECT],
            token_endpoint_auth_method='none', scope='progress.read')
        run(provider.register_client(client))
        self.oauth = provider, client

    def test_pending_one_use_and_hashed(self):
        provider, client = self.oauth
        rid = authorize(provider, client)
        assert provider.get_pending(rid)['resource'] == ISSUER+'/mcp'
        redirect = provider.approve(rid, 'user-a')
        assert parse_qs(urlsplit(redirect).query)['state'] == ['random-client-state']
        assert provider.get_pending(rid) is None
        with self.assertRaises(ValueError): provider.approve(rid, 'user-b')
        code = parse_qs(urlsplit(redirect).query)['code'][0]
        with provider.db() as db:
            assert code not in str([tuple(x) for x in db.execute('SELECT * FROM oauth_codes')])


    def test_authorize_fail_closed(self):
        changes = [dict(state=None), dict(resource=None), dict(resource='https://other.example/mcp'),
            dict(redirect_uri='https://client.example/callback/'), dict(code_challenge='x'), dict(scopes=['write'])]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(AuthorizeError):
                authorize(*self.oauth, **change)


    def test_registration_allowlist(self):
        provider, _ = self.oauth
        client = OAuthClientInformationFull(client_id='bad', redirect_uris=['https://evil.example/callback'], token_endpoint_auth_method='none')
        with self.assertRaises(RegistrationError): run(provider.register_client(client))


    def test_official_sdk_pkce_redirect_replay(self):
        provider, client = self.oauth
        app = Starlette(routes=create_auth_routes(provider, AnyHttpUrl(ISSUER),
            client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=['progress.read']),
            revocation_options=RevocationOptions(enabled=True)))
        with TestClient(app, base_url=ISSUER) as http:
            code = issue_code(provider, client)
            payload = dict(grant_type='authorization_code', client_id='client', code=code,
                           redirect_uri=REDIRECT, code_verifier=VERIFIER)
            assert http.post('/token', data=payload | {'code_verifier': 'wrong'}).status_code == 400
            assert http.post('/token', data=payload | {'redirect_uri':REDIRECT+'/wrong'}).status_code == 400
            response = http.post('/token', data=payload)
            assert response.status_code == 200, response.text
            tokens = response.json()
            assert run(provider.load_access_token(tokens['access_token'])).subject == 'user-a'
            assert http.post('/token', data=payload).status_code == 400
            refresh = dict(grant_type='refresh_token', client_id='client', refresh_token=tokens['refresh_token'])
            rotated = http.post('/token', data=refresh)
            assert rotated.status_code == 200, rotated.text
            assert run(provider.load_access_token(tokens['access_token'])) is None
            assert run(provider.load_access_token(rotated.json()['access_token']))
            assert http.post('/token', data=refresh).status_code == 400
            assert run(provider.load_access_token(rotated.json()['access_token'])) is None


    def test_subject_resource_expiry_and_restart(self):
        provider, client = self.oauth
        code = issue_code(provider, client)
        loaded = run(provider.load_authorization_code(client, code))
        token = run(provider.exchange_authorization_code(client, loaded))
        restarted = OAuthProvider(provider.db_path, ISSUER, [REDIRECT], database=provider.database)
        access = run(restarted.load_access_token(token.access_token))
        assert access.subject == 'user-a' and access.resource == ISSUER+'/mcp'
        other_issuer = OAuthProvider(provider.db_path, 'https://different.example', [REDIRECT], database=provider.database)
        assert run(other_issuer.load_access_token(token.access_token)) is None
        restarted.clock = lambda: provider.clock()+601
        assert run(restarted.load_access_token(token.access_token)) is None
        run(provider.revoke_token(access))
        assert run(provider.load_refresh_token(client, token.refresh_token)) is None


    def test_code_cross_client_and_expiry(self):
        provider, client = self.oauth
        code = issue_code(provider, client)
        other = client.model_copy(update={'client_id':'other'})
        assert run(provider.load_authorization_code(other, code)) is None
        provider.clock = lambda: 9999999999
        assert run(provider.load_authorization_code(client, code)) is None

    def test_refresh_race_revokes_family(self):
        provider, client = self.oauth
        code = issue_code(provider, client)
        tokens = run(provider.exchange_authorization_code(client, run(provider.load_authorization_code(client, code))))
        loaded = run(provider.load_refresh_token(client, tokens.refresh_token))
        rotated = run(provider.exchange_refresh_token(client, loaded, ['progress.read']))
        with self.assertRaises(TokenError):
            run(provider.exchange_refresh_token(client, loaded, ['progress.read']))
        assert run(provider.load_access_token(rotated.access_token)) is None

    def test_token_secrets_not_stored(self):
        provider, client = self.oauth
        code = issue_code(provider, client)
        tokens = run(provider.exchange_authorization_code(client, run(provider.load_authorization_code(client, code))))
        with provider.db() as db:
            stored = str([tuple(row) for row in db.execute('SELECT * FROM oauth_tokens')])
        assert tokens.access_token not in stored
        assert tokens.refresh_token not in stored

    def test_pending_expires(self):
        provider, client = self.oauth
        rid = authorize(provider, client)
        provider.clock = lambda: 9999999999
        assert provider.get_pending(rid) is None
        with self.assertRaises(ValueError): provider.approve(rid, 'user-a')

    def test_sdk_registration_and_authorization(self):
        provider, _ = self.oauth
        app = Starlette(routes=create_auth_routes(provider, AnyHttpUrl(ISSUER),
            client_registration_options=ClientRegistrationOptions(enabled=True,
                valid_scopes=['progress.read'], default_scopes=['progress.read'])))
        with TestClient(app, base_url=ISSUER, follow_redirects=False) as http:
            registration = http.post('/register', json={'redirect_uris':[REDIRECT],
                'token_endpoint_auth_method':'none'})
            assert registration.status_code == 201, registration.text
            cid = registration.json()['client_id']
            assert 'client_secret' not in registration.json() or registration.json()['client_secret'] is None
            params = dict(client_id=cid, redirect_uri=REDIRECT, state='client-random-state',
                scope='progress.read', response_type='code', code_challenge=CHALLENGE,
                code_challenge_method='S256', resource=ISSUER+'/mcp')
            answer = http.get('/authorize', params=params)
            assert answer.status_code == 302
            assert answer.headers['location'].startswith(ISSUER+'/oauth/consent?request=')
            invalid = http.get('/authorize', params=params | {'code_challenge_method':'plain'})
            assert 'error=' in invalid.headers['location']
            bad_redirect = http.get('/authorize', params=params | {'redirect_uri':'https://evil.example/callback'})
            assert bad_redirect.status_code == 400

    def test_subject_revocation_removes_unredeemed_codes(self):
        provider, client = self.oauth
        code_a = issue_code(provider, client, 'user-a')
        code_b = issue_code(provider, client, 'user-b')
        already_loaded = run(provider.load_authorization_code(client, code_a))
        provider.revoke_subject('user-a')
        assert run(provider.load_authorization_code(client, code_a)) is None
        assert run(provider.load_authorization_code(client, code_b)) is not None
        with self.assertRaises(TokenError):
            run(provider.exchange_authorization_code(client, already_loaded))

    def test_expired_rows_pruned_and_live_revoked_retained(self):
        provider, client = self.oauth
        code = issue_code(provider, client)
        first = run(provider.exchange_authorization_code(client, run(provider.load_authorization_code(client, code))))
        access = run(provider.load_access_token(first.access_token))
        run(provider.revoke_token(access))
        with provider.db() as db:
            db.execute("UPDATE oauth_tokens SET expires=0 WHERE kind='access'")
            db.execute('INSERT INTO oauth_codes VALUES (?,?,?)', ('expired', '{}', 0))
        code = issue_code(provider, client)
        run(provider.exchange_authorization_code(client, run(provider.load_authorization_code(client, code))))
        with provider.db() as db:
            assert db.execute('SELECT count(*) FROM oauth_tokens').fetchone()[0] == 3
            assert db.execute('SELECT count(*) FROM oauth_tokens WHERE revoked=1').fetchone()[0] == 1
            assert db.execute('SELECT count(*) FROM oauth_codes').fetchone()[0] == 0

    def test_token_and_code_capacity_fail_closed(self):
        from unittest.mock import patch
        provider, client = self.oauth
        with patch('remote_server.oauth.MAX_SUBJECT_CODES', 1):
            issue_code(provider, client)
            rid = authorize(provider, client)
            with self.assertRaises(ValueError): provider.approve(rid, 'user-a')
            assert provider.get_pending(rid)  # may retry after old code expires
            issue_code(provider, client, 'user-b')  # isolated subject quota
        with patch('remote_server.oauth.MAX_TOKEN_ROWS', 1):
            code = issue_code(provider, client)
            loaded = run(provider.load_authorization_code(client, code))
            with self.assertRaises(TokenError): run(provider.exchange_authorization_code(client, loaded))
            assert run(provider.load_authorization_code(client, code))  # rollback is safe
