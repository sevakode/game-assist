"""Persistent storage hooks for the official MCP SDK authorization server.

The SDK owns OAuth protocol parsing, client authentication and PKCE validation.
This module owns short-lived opaque credentials and atomic replay prevention.
Single-instance SQLite prototype; no claim of production AS certification.
"""
import hashlib
import json
import re
import secrets
import time
from urllib.parse import urlsplit
from .database import Database

from mcp.server.auth.provider import (AccessToken, AuthorizationCode, AuthorizationParams,
    AuthorizeError, RefreshToken, RegistrationError, TokenError, construct_redirect_uri)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


MAX_TOKEN_ROWS = 100_000
MAX_SUBJECT_TOKEN_ROWS = 16_384
MAX_SUBJECT_CODES = 20
MAX_CODE_ROWS = 2_000


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class OAuthProvider:
    def __init__(self, db_path, issuer, redirect_uris, clock=time.time, database=None):
        self.db_path = str(db_path)
        self.issuer = issuer.rstrip('/')
        self.resource = self.issuer + '/mcp'
        self.redirect_uris = frozenset(redirect_uris)
        self.clock = clock
        for uri in (self.issuer, *self.redirect_uris):
            p = urlsplit(uri)
            if p.scheme != 'https' or not p.hostname or p.username or p.password or p.fragment or '*' in uri:
                raise ValueError('OAuth requires exact HTTPS issuer and redirects')
        self.database = database or Database(db_path)
        self.database.initialize()

    def db(self):
        return self.database.transaction()

    async def get_client(self, client_id):
        with self.db() as db:
            row = db.execute('SELECT data FROM oauth_clients WHERE id=?', (client_id,)).fetchone()
        return OAuthClientInformationFull.model_validate_json(row['data']) if row else None

    async def register_client(self, client_info):
        redirects = [str(x) for x in client_info.redirect_uris or []]
        if not redirects or any(x not in self.redirect_uris for x in redirects):
            raise RegistrationError('invalid_redirect_uri', 'Redirect is not operator-approved')
        if (client_info.token_endpoint_auth_method != 'none' or client_info.client_secret
            or set(client_info.grant_types) - {'authorization_code', 'refresh_token'}
            or 'authorization_code' not in client_info.grant_types
            or client_info.response_types != ['code']
            or set((client_info.scope or '').split()) - {'progress.read'}
            or not client_info.client_id):
            raise RegistrationError('invalid_client_metadata', 'Public PKCE clients with progress.read only')
        client_info.scope = 'progress.read'
        with self.db() as db:
            if db.execute('SELECT count(*) FROM oauth_clients').fetchone()[0] >= 10000:
                raise RegistrationError('invalid_client_metadata', 'Registration capacity reached')
            db.execute('INSERT INTO oauth_clients VALUES (?,?)', (client_info.client_id, client_info.model_dump_json()))

    async def authorize(self, client, params: AuthorizationParams):
        if (str(params.redirect_uri) not in self.redirect_uris
            or str(params.redirect_uri) not in [str(x) for x in client.redirect_uris or []]
            or not params.redirect_uri_provided_explicitly
            or not params.state or len(params.state) > 1024
            or not re.fullmatch(r'[A-Za-z0-9_-]{43}', params.code_challenge)
            or params.resource != self.resource):
            raise AuthorizeError('invalid_request', 'Explicit redirect, state, S256 PKCE and resource required')
        if params.scopes != ['progress.read']:
            raise AuthorizeError('invalid_scope', 'progress.read required')
        request_id = secrets.token_urlsafe(32)
        data = params.model_dump(mode='json') | {'client_id': client.client_id}
        with self.db() as db:
            db.execute('DELETE FROM oauth_pending WHERE expires<=?', (self.clock(),))
            db.execute('DELETE FROM oauth_codes WHERE expires<=?', (self.clock(),))
            if db.execute('SELECT count(*) FROM oauth_pending').fetchone()[0] >= 2000:
                raise AuthorizeError('temporarily_unavailable', 'Authorization capacity reached')
            db.execute('INSERT INTO oauth_pending VALUES (?,?,?)', (digest(request_id), json.dumps(data), self.clock()+600))
        return self.issuer + '/oauth/consent?request=' + request_id

    def get_pending(self, request_id):
        with self.db() as db:
            row = db.execute('SELECT data FROM oauth_pending WHERE id=? AND expires>?', (digest(request_id), self.clock())).fetchone()
        return json.loads(row['data']) if row else None

    def approve(self, request_id, subject):
        if not subject or len(subject) > 128:
            raise ValueError('Invalid subject')
        with self.db() as db:
            row = db.execute('DELETE FROM oauth_pending WHERE id=? AND expires>? RETURNING data', (digest(request_id), self.clock())).fetchone()
            if not row:
                raise ValueError('Expired or consumed authorization request')
            data = json.loads(row['data'])
            state = data.pop('state')
            db.execute('DELETE FROM oauth_codes WHERE expires<=?', (self.clock(),))
            if (db.execute('SELECT count(*) FROM oauth_codes').fetchone()[0] >= MAX_CODE_ROWS
                or db.execute("SELECT count(*) FROM oauth_codes WHERE json_extract(data,'$.subject')=?", (subject,)).fetchone()[0] >= MAX_SUBJECT_CODES):
                raise ValueError('Authorization capacity reached; retry later')
            code = secrets.token_urlsafe(32)
            auth = AuthorizationCode(code='', expires_at=self.clock()+120, subject=subject, **data)
            db.execute('INSERT INTO oauth_codes VALUES (?,?,?)', (digest(code), auth.model_dump_json(), auth.expires_at))
        return construct_redirect_uri(str(auth.redirect_uri), code=code, state=state)

    async def load_authorization_code(self, client, authorization_code):
        with self.db() as db:
            row = db.execute('SELECT data FROM oauth_codes WHERE hash=? AND expires>?', (digest(authorization_code), self.clock())).fetchone()
        if row:
            code = AuthorizationCode.model_validate_json(row['data'])
            if code.client_id == client.client_id:
                code.code = authorization_code
                return code
        return None

    def _issue(self, db, client_id, subject, scopes, family=None):
        # Expired refresh credentials cannot redeem or trigger useful replay
        # detection. Retain unexpired revoked rows to detect rotation replay.
        db.execute('DELETE FROM oauth_tokens WHERE expires<=?', (self.clock(),))
        if (db.execute('SELECT count(*) FROM oauth_tokens').fetchone()[0] + 2 > MAX_TOKEN_ROWS
            or db.execute("SELECT count(*) FROM oauth_tokens WHERE json_extract(data,'$.subject')=?", (subject,)).fetchone()[0] + 2 > MAX_SUBJECT_TOKEN_ROWS):
            raise TokenError('invalid_request', 'Token capacity reached; retry later')
        family = family or secrets.token_urlsafe(32)
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        for raw, kind, ttl in ((access, 'access', 600), (refresh, 'refresh', 2592000)):
            data = {'client_id': client_id, 'subject': subject, 'scopes': scopes,
                    'resource': self.resource, 'issuer': self.issuer}
            db.execute('INSERT INTO oauth_tokens VALUES (?,?,?,?,?,0)',
                       (digest(raw), kind, family, json.dumps(data), self.clock()+ttl))
        return OAuthToken(access_token=access, token_type='Bearer', expires_in=600,
                          refresh_token=refresh, scope=' '.join(scopes))

    async def exchange_authorization_code(self, client, authorization_code):
        with self.db() as db:
            row = db.execute('DELETE FROM oauth_codes WHERE hash=? AND expires>? RETURNING data',
                             (digest(authorization_code.code), self.clock())).fetchone()
            if not row:
                raise TokenError('invalid_grant', 'Code expired or consumed')
            stored = AuthorizationCode.model_validate_json(row['data'])
            if stored.client_id != client.client_id or stored.resource != self.resource:
                raise TokenError('invalid_grant', 'Invalid code binding')
            return self._issue(db, stored.client_id, stored.subject, stored.scopes)

    def _load(self, token, kind, include_revoked=False):
        with self.db() as db:
            row = db.execute('SELECT * FROM oauth_tokens WHERE hash=? AND kind=?', (digest(token), kind)).fetchone()
        if not row or row['expires'] <= self.clock() or (row['revoked'] and not include_revoked):
            return None
        data = json.loads(row['data'])
        if data['issuer'] != self.issuer or data['resource'] != self.resource:
            return None
        return row, data

    async def load_refresh_token(self, client, refresh_token):
        found = self._load(refresh_token, 'refresh', include_revoked=True)
        if found and found[1]['client_id'] == client.client_id:
            row, data = found
            if row['revoked']:
                with self.db() as db:
                    db.execute('UPDATE oauth_tokens SET revoked=1 WHERE family=?', (row['family'],))
                return None
            return RefreshToken(token=refresh_token, expires_at=int(row['expires']), **{k:data[k] for k in ('client_id','subject','scopes')})
        return None

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        rejected = False
        result = None
        with self.db() as db:
            row = db.execute('SELECT * FROM oauth_tokens WHERE hash=? AND kind="refresh"', (digest(refresh_token.token),)).fetchone()
            if not row:
                raise TokenError('invalid_grant', 'Refresh token not found')
            data = json.loads(row['data'])
            if data['client_id'] != client.client_id or set(scopes)-set(data['scopes']) or data['resource'] != self.resource or data['issuer'] != self.issuer:
                raise TokenError('invalid_grant', 'Invalid refresh binding')
            if row['revoked'] or row['expires'] <= self.clock():
                # Commit family revocation even for a race after a successful load.
                db.execute('UPDATE oauth_tokens SET revoked=1 WHERE family=?', (row['family'],))
                rejected = True
            else:
                db.execute('UPDATE oauth_tokens SET revoked=1 WHERE family=?', (row['family'],))
                result = self._issue(db, client.client_id, data['subject'], scopes, row['family'])
        if rejected:
            raise TokenError('invalid_grant', 'Refresh token consumed or expired')
        return result

    async def load_access_token(self, token):
        found = self._load(token, 'access')
        if found:
            row, data = found
            return AccessToken(token=token, expires_at=int(row['expires']), resource=self.resource,
                claims={'iss': self.issuer}, **{k:data[k] for k in ('client_id','subject','scopes')})
        return None

    async def verify_token(self, token):
        return await self.load_access_token(token)

    async def revoke_token(self, token):
        with self.db() as db:
            row = db.execute('SELECT family FROM oauth_tokens WHERE hash=?', (digest(token.token),)).fetchone()
            if row:
                db.execute('UPDATE oauth_tokens SET revoked=1 WHERE family=?', (row['family'],))

    def revoke_subject(self, subject, connection=None):
        def revoke(db):
            db.execute("DELETE FROM oauth_codes WHERE json_extract(data,'$.subject')=?", (subject,))
            db.execute("UPDATE oauth_tokens SET revoked=1 WHERE json_extract(data,'$.subject')=?", (subject,))
        if connection is not None:
            revoke(connection)
        else:
            with self.db() as db:
                revoke(db)


Provider = OAuthProvider
