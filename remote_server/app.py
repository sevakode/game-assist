"""HTTPS-only, single-instance remote companion. No raw save ingestion.

Use a TLS reverse proxy with request/access logging disabled for auth routes.
The local server remains a separate application. No credentials are provisioned
at import time and no Steam requests occur without an explicit browser login.
"""
import hashlib
import html
import json
import os
import re
import secrets
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from uuid import UUID, uuid4

from mcp.server.fastmcp import FastMCP
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.auth.routes import build_metadata
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl, ValidationError
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse, PlainTextResponse
from starlette.routing import Route
from starlette.concurrency import run_in_threadpool

from server.app import SaveSummary
from server.steam import SteamService, SteamError
from .oauth import OAuthProvider
from .database import Database
from . import ui

APPID = 4231820
COOKIE = '__Host-ga_session'
SCOPES = {'saves.summary', 'saves.metadata'}
NOTICE = 'Компаньон сообщил об изменении разрешённых счётчиков сохранения. Получение предметов или улучшений не подтверждено.'
NOTIFICATION_FIELDS = ('healthUpgradeFragmentCount','manaUpgradeFragmentCount')
INBOX_TTL = 30 * 86400
INBOX_LIMIT = 50
INBOX_COALESCE = 300

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

@dataclass(frozen=True)
class Config:
    issuer: str
    db_path: str
    redirect_uris: tuple[str, ...]
    database_url: str | None = field(default=None, repr=False)

    def __post_init__(self):
        if self.database_url == '':
            raise ValueError('DATABASE_URL cannot be empty; no local fallback')
        p = urlsplit(self.issuer)
        if (p.scheme != 'https' or not p.hostname or p.username or p.password
                or p.path or p.query or p.fragment or '*' in p.netloc):
            raise ValueError('An explicit HTTPS origin (without path/trailing slash) is required')
        if not self.redirect_uris:
            raise ValueError('Explicit OAuth redirect allowlist required')
        for uri in self.redirect_uris:
            p = urlsplit(uri)
            if p.scheme != 'https' or not p.hostname or p.username or p.password or p.fragment or '*' in uri:
                raise ValueError('OAuth redirects must be exact HTTPS URLs')

    @classmethod
    def from_env(cls):
        issuer = os.environ.get('GA_PUBLIC_ORIGIN')
        if issuer is None and os.environ.get('GA_DEPLOYMENT_MODE') == 'render':
            issuer = os.environ.get('RENDER_EXTERNAL_URL')
        return cls(issuer or '', os.environ.get('GA_REMOTE_DB', 'remote.sqlite'),
                   tuple(filter(None, os.environ.get('GA_OAUTH_REDIRECT_URIS', '').split(','))), os.environ.get('DATABASE_URL'))

class Store:
    def __init__(self, path, database=None):
        self.path = str(path)
        self.database = database or Database(path)
        self.database.initialize()

    def db(self):
        return self.database.transaction()

    def limit(self, bucket, maximum, window=600):
        now = time.time()
        with self.db() as db:
            db.execute('DELETE FROM limits WHERE start<?', (now-3600,))
            row = db.execute('SELECT * FROM limits WHERE bucket=?', (bucket,)).fetchone()
            if not row or row['start'] + window <= now:
                if not row and db.execute('SELECT count(*) FROM limits').fetchone()[0] >= 10000:
                    raise HTTPException(429, 'Rate limit capacity reached')
                db.execute('INSERT OR REPLACE INTO limits VALUES(?,?,1)', (bucket, now))
            elif row['count'] >= maximum:
                raise HTTPException(429, 'Rate limit; retry later')
            else:
                db.execute('UPDATE limits SET count=count+1 WHERE bucket=?', (bucket,))

    def session(self, request, require_owner=False):
        raw = request.cookies.get(COOKIE, '')
        with self.db() as db:
            row = db.execute('SELECT * FROM sessions WHERE hash=? AND expires>?', (digest(raw), time.time())).fetchone()
        if not row or (require_owner and not row['owner']):
            raise HTTPException(401, 'Sign in on this website first')
        return dict(row)

    def projection(self, owner):
        with self.db() as db:
            permitted = db.execute("SELECT 1 FROM grants WHERE owner=? AND appid=? AND scope='saves.summary'", (owner, APPID)).fetchone()
            row = db.execute('SELECT payload,observed FROM observations WHERE owner=? AND appid=?', (owner, APPID)).fetchone() if permitted else None
        result = {'spoiler_policy': 'strict', 'games': []}
        if permitted:
            result['games'] = [{'appid': APPID, 'status': 'unknown' if not row else 'reported_not_independently_verified',
                                'summary': SaveSummary.model_validate_json(row['payload']).model_dump(mode='json') if row else None,
                                'received_at': row['observed'] if row else None, 'observation_time': 'unknown'}]
        return result

    def inbox(self, owner):
        now = time.time()
        with self.db() as db:
            db.execute('DELETE FROM notifications WHERE created<?', (now-INBOX_TTL,))
            permitted = bool(db.execute("SELECT 1 FROM grants WHERE owner=? AND appid=? AND scope='saves.summary'", (owner,APPID)).fetchone())
            settings = db.execute('SELECT enabled FROM notification_settings WHERE owner=? AND appid=?', (owner,APPID)).fetchone()
            rows = db.execute('SELECT id,created,read_at FROM notifications WHERE owner=? AND appid=? ORDER BY created DESC,id DESC LIMIT 50', (owner,APPID)).fetchall() if permitted else []
        items = [{'id':row['id'], 'message':NOTICE, 'created_at':row['created'], 'read':row['read_at'] is not None} for row in rows]
        return {'enabled':bool(permitted and settings and settings['enabled']), 'can_enable':permitted,
                'unread_count':sum(not row['read'] for row in items), 'items':items,
                'source':'device_companion', 'cloud_available':False, 'push_available':False}

    @staticmethod
    def record_notification(db, owner, appid, payload, event_key, now):
        settings = db.execute('SELECT * FROM notification_settings WHERE owner=? AND appid=? AND enabled=1', (owner,appid)).fetchone()
        if not settings:
            return
        # Validate both projections; corrupt/old baselines establish a new baseline
        # rather than inventing progress. No raw source strings enter the notice.
        current = SaveSummary.model_validate_json(payload).player_scalars.model_dump()
        try:
            previous = SaveSummary.model_validate_json(settings['baseline']).player_scalars.model_dump() if settings['baseline'] else None
        except (ValidationError,ValueError,TypeError):
            previous = None
        db.execute('UPDATE notification_settings SET baseline=?,updated=? WHERE owner=? AND appid=?', (payload,now,owner,appid))
        changed = previous is not None and any(previous[field]['status']=='known' and value['status']=='known' and previous[field]['value'] != value['value'] for field,value in current.items() if field in NOTIFICATION_FIELDS)
        if not changed:
            return
        db.execute('DELETE FROM notifications WHERE created<?', (now-INBOX_TTL,))
        key = digest(str(settings['epoch'])+':'+event_key)
        if db.execute('SELECT 1 FROM notifications WHERE owner=? AND appid=? AND event_key=?',(owner,appid,key)).fetchone():
            return
        latest = db.execute('SELECT id FROM notifications WHERE owner=? AND appid=? AND created>? ORDER BY created DESC,id DESC LIMIT 1',(owner,appid,now-INBOX_COALESCE)).fetchone()
        if latest:
            # Rotate the item ID so a stale browser form cannot mark a newer
            # coalesced change as read without having seen that version.
            db.execute('UPDATE notifications SET id=?,event_key=?,created=?,read_at=NULL WHERE id=? AND owner=?',(str(uuid4()),key,now,latest['id'],owner))
        else:
            db.execute('INSERT INTO notifications VALUES(?,?,?,?,?,NULL)',(str(uuid4()),owner,appid,key,now))
        db.execute('DELETE FROM notifications WHERE owner=? AND id NOT IN (SELECT id FROM notifications WHERE owner=? ORDER BY created DESC,id DESC LIMIT 50)',(owner,owner))

class Boundary:
    """Bound body sizes before SDK parsing; exact raw redirect/resource validation."""
    def __init__(self, app, config, store):
        self.app, self.config, self.store = app, config, store

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        request = Request(scope)
        if len(scope.get('query_string', b'')) > 8192:
            return await JSONResponse({'error': 'query_too_large'}, 414)(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body.extend(message.get('body', b''))
            if len(body) > 16384:
                return await JSONResponse({'error': 'body_too_large'}, 413)(scope, receive, send)
            if not message.get('more_body'):
                break
        path = scope['path']
        if request.headers.get('origin') not in (None, self.config.issuer):
            return await JSONResponse({'error': 'origin_denied'}, 403)(scope, receive, send)
        if path in ('/authorize', '/token', '/register', '/login', '/steam/callback', '/v1/devices/pair/start', '/v1/devices/pair/poll', '/v1/device/observations'):
            try:
                self.store.limit('edge:' + path + ':' + digest(request.client.host if request.client else 'unknown'), 600 if path in ('/v1/devices/pair/poll','/v1/device/observations') else 60)
            except HTTPException:
                return await JSONResponse({'error': 'rate_limited'}, 429)(scope, receive, send)
        if path == '/register':
            try:
                registration = json.loads(body)
                redirects = registration.get('redirect_uris') if isinstance(registration, dict) else None
                if not isinstance(redirects, list) or not redirects or any(not isinstance(u, str) or u not in self.config.redirect_uris for u in redirects):
                    raise ValueError()
            except (ValueError, TypeError):
                return await JSONResponse({'error': 'invalid_client_metadata'}, 400)(scope, receive, send)
        if path in ('/authorize', '/token'):
            from urllib.parse import parse_qsl
            try:
                pairs = list(request.query_params.multi_items()) if request.method == 'GET' else parse_qsl(body.decode(), keep_blank_values=True, strict_parsing=True, max_num_fields=30)
            except (ValueError, UnicodeError):
                return await JSONResponse({'error': 'invalid_request'}, 400)(scope, receive, send)
            params = dict(pairs)
            if len(params) != len(pairs) or ('redirect_uri' in params and params['redirect_uri'] not in self.config.redirect_uris) or ('resource' in params and params['resource'] != self.config.issuer + '/mcp'):
                return await JSONResponse({'error': 'invalid_request'}, 400)(scope, receive, send)
        sent = False
        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()
        async def secure(message):
            if message['type'] == 'http.response.start':
                message['headers'] = [(k,v) for k,v in message['headers'] if k.lower() not in (b'access-control-allow-origin', b'cache-control')]
                message['headers'] += [(b'cache-control', b'no-store'), (b'referrer-policy', b'no-referrer'),
                    (b'x-content-type-options', b'nosniff'), (b'content-security-policy', b"default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"),
                    (b'strict-transport-security', b'max-age=31536000')]
            await send(message)
        return await self.app(scope, replay, secure)

async def json_body(request):
    try:
        def unique(pairs):
            result = dict(pairs)
            if len(result) != len(pairs):
                raise ValueError()
            return result
        data = json.loads(await request.body(), object_pairs_hook=unique)
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (ValueError, UnicodeError):
        raise HTTPException(422, 'JSON object required') from None

def page(title, body):
    return ui.page(title, body)

def hidden(name, value):
    return f'<input type="hidden" name="{html.escape(name)}" value="{html.escape(value, quote=True)}">'

async def form(request, session, issuer):
    if request.headers.get('origin') != issuer:
        raise HTTPException(403, 'Origin required')
    data = await request.form()
    if len(data) != len(list(data.multi_items())) or not secrets.compare_digest(str(data.get('csrf','')), session['csrf']):
        raise HTTPException(403, 'Invalid CSRF token')
    return data

def create_app(config=None, steam=None, database=None, download_dir=None):
    config = config or Config.from_env()
    database = database or Database(config.db_path, database_url=config.database_url)
    store = Store(config.db_path, database=database)
    steam = steam or SteamService()
    downloads = Path(download_dir) if download_dir is not None else Path(__file__).parent / 'downloads'
    archive = downloads / 'deck-companion.zip'
    checksum_path = downloads / 'deck-companion.zip.sha256'
    archive_checksum = None
    if archive.exists() and checksum_path.exists():
        if archive.is_symlink() or checksum_path.is_symlink() or archive.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('Invalid Deck download artifact')
        checksum_text = checksum_path.read_text(encoding='ascii')
        if not re.fullmatch(r'[0-9a-f]{64}  deck-companion\.zip\n', checksum_text):
            raise ValueError('Invalid Deck archive checksum')
        archive_checksum = checksum_text[:64]
        if hashlib.sha256(archive.read_bytes()).hexdigest() != archive_checksum:
            raise ValueError('Deck archive checksum mismatch')
    provider = OAuthProvider(config.db_path, config.issuer, config.redirect_uris, database=database)
    registration = ClientRegistrationOptions(enabled=True, valid_scopes=['progress.read'], default_scopes=['progress.read'])
    revocation = RevocationOptions(enabled=True)
    mcp = FastMCP('Game Assist', auth_server_provider=provider,
        auth=AuthSettings(issuer_url=AnyHttpUrl(config.issuer), resource_server_url=AnyHttpUrl(config.issuer+'/mcp'),
            required_scopes=['progress.read'], client_registration_options=registration, revocation_options=revocation),
        stateless_http=True, json_response=True, max_request_body_size=16384,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=[urlsplit(config.issuer).netloc], allowed_origins=[config.issuer]))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def get_progress() -> dict:
        """Read only this account's permitted spoiler-filtered latest summary. No IDs accepted."""
        token = get_access_token()
        if not token or not token.subject:
            raise ValueError('Authentication required')
        return store.projection(token.subject)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def suggest_next_step() -> dict:
        """No future story facts; ask for known context when mapping is not established."""
        token = get_access_token()
        if not token or not token.subject:
            raise ValueError('Authentication required')
        return {'progress': store.projection(token.subject), 'suggestion': 'What is your current goal and what have you already discovered?', 'confidence': 'unknown'}

    async def download(request):
        if archive_checksum is None:
            raise HTTPException(503, 'Deck source archive has not been built')
        return FileResponse(archive, media_type='application/zip', filename='deck-companion.zip')

    async def download_checksum(request):
        if archive_checksum is None:
            raise HTTPException(503, 'Deck source archive has not been built')
        return PlainTextResponse(archive_checksum+'  deck-companion.zip\n')

    async def setup_page(request):
        if archive_checksum is None:
            return page('Настройка Deck', ui.setup_body(config.issuer,None))
        command = "cd ~/Downloads &&\n" + "printf '%s  deck-companion.zip\\n' " + shlex.quote(archive_checksum) + " | sha256sum -c - &&\n" + "mkdir deck-companion &&\npython3 -I -m zipfile -e deck-companion.zip deck-companion &&\ncd deck-companion &&\npython3 -m deck setup --server " + shlex.quote(config.issuer)
        return page('Настройка Deck', ui.setup_body(config.issuer,archive_checksum,command))

    async def stylesheet(request):
        return FileResponse(Path(__file__).parent/'ui.css',media_type='text/css')

    async def health(request):
        return JSONResponse({'status': 'ok'})

    async def home(request):
        try:
            session = store.session(request, True)
        except HTTPException:
            return page('Игровой спутник', ui.landing_body())
        inbox = store.inbox(session['owner'])
        return page('Твоя игровая станция', ui.home_body(store.projection(session['owner']),session['csrf'],inbox,capabilities={'mcp_url':config.issuer+'/mcp'}))

    async def login(request):
        next_path = request.query_params.get('next', '/')
        if next_path not in ('/', '/devices/approve') and not re.fullmatch(r'/oauth/consent\?request=[A-Za-z0-9_-]{43}', next_path):
            raise HTTPException(400, 'Invalid continuation')
        raw, csrf, state = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        return_to = config.issuer + '/steam/callback?' + urlencode({'state': state})
        with store.db() as db:
            db.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
            if db.execute('SELECT count(*) FROM sessions').fetchone()[0] >= 2000:
                raise HTTPException(429, 'Sign-in capacity reached')
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)', (digest(raw), None, csrf, time.time()+600))
            db.execute('DELETE FROM login_states WHERE expires<?', (time.time(),))
            db.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
            db.execute('INSERT INTO login_states VALUES(?,?,?,?,?)', (digest(state), digest(raw), return_to, time.time()+600, next_path))
        response = RedirectResponse(steam.login_url(return_to, config.issuer), 303)
        response.set_cookie(COOKIE, raw, max_age=600, secure=True, httponly=True, samesite='lax', path='/')
        return response

    async def callback(request):
        session = store.session(request)
        params = request.query_params
        if len(params) != len(list(params.multi_items())):
            raise HTTPException(400, 'Invalid callback')
        with store.db() as db:
            state = db.execute('DELETE FROM login_states WHERE hash=? AND session_hash=? AND expires>? RETURNING *',
                (digest(params.get('state','')), session['hash'], time.time())).fetchone()
        if not state:
            raise HTTPException(400, 'Expired or invalid login state')
        nonce = params.get('openid.response_nonce')
        if nonce is not None:
            if not 20 < len(nonce) <= 256:
                raise HTTPException(400, 'Invalid Steam assertion')
            with store.db() as db:
                db.execute('DELETE FROM steam_nonces WHERE expires<=?', (time.time(),))
                if db.execute('SELECT count(*) FROM steam_nonces').fetchone()[0] >= 4096:
                    raise HTTPException(429, 'Steam verification capacity reached')
                reserved = db.execute('INSERT INTO steam_nonces(nonce_hash,expires) VALUES(?,?) ON CONFLICT(nonce_hash) DO NOTHING RETURNING nonce_hash', (digest(nonce),time.time()+600)).fetchone()
                if not reserved:
                    raise HTTPException(400, 'Replayed Steam assertion')
        try:
            steamid = await run_in_threadpool(steam.verify_callback, params, state['return_to'])
        except SteamError:
            raise HTTPException(400, 'Steam sign-in could not be verified') from None
        if not re.fullmatch(r'[0-9]{17}', steamid):
            raise HTTPException(400, 'Invalid Steam identity')
        raw = secrets.token_urlsafe(32)
        with store.db() as db:
            row = db.execute('SELECT id FROM users WHERE steamid=?', (steamid,)).fetchone()
            owner = row['id'] if row else secrets.token_urlsafe(24)
            if not row:
                db.execute('INSERT INTO users VALUES(?,?)', (owner, steamid))
            db.execute('DELETE FROM sessions WHERE hash=?', (session['hash'],))
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)', (digest(raw), owner, secrets.token_urlsafe(32), time.time()+86400))
        response = RedirectResponse(state['next_path'], 303)
        response.set_cookie(COOKIE, raw, max_age=86400, secure=True, httponly=True, samesite='lax', path='/')
        return response

    async def pair_start(request):
        data = await json_body(request)
        if data != {}:
            raise HTTPException(422, 'Empty object required')
        code, user = secrets.token_urlsafe(32), secrets.token_hex(4).upper()
        with store.db() as db:
            db.execute('DELETE FROM pairings WHERE expires<?', (time.time(),))
            if db.execute('SELECT count(*) FROM pairings').fetchone()[0] >= 2000:
                raise HTTPException(429, 'Pairing capacity reached')
            db.execute('INSERT INTO pairings(hash,user_hash,expires) VALUES(?,?,?)', (digest(code), digest(user), time.time()+600))
        return JSONResponse({'device_code':code, 'user_code':user, 'verification_uri': config.issuer+'/devices/approve', 'expires_in':600, 'interval':5})

    async def pair_poll(request):
        data = await json_body(request)
        if set(data) != {'device_code'} or not isinstance(data['device_code'], str) or len(data['device_code'])>100:
            raise HTTPException(422, 'Invalid polling request')
        key = digest(data['device_code'])
        store.limit('poll:'+key, 130)
        with store.db() as db:
            row = db.execute('SELECT * FROM pairings WHERE hash=?', (key,)).fetchone()
            if not row or row['expires']<=time.time() or row['consumed']:
                return JSONResponse({'status':'expired'}, 400)
            if row['last_poll']+5>time.time():
                return JSONResponse({'status':'slow_down','interval':5}, 429)
            db.execute('UPDATE pairings SET last_poll=? WHERE hash=?', (time.time(), key))
            if not row['owner']:
                return JSONResponse({'status':'pending','interval':5})
            db.execute('DELETE FROM devices WHERE expires<=?', (time.time(),))
            if db.execute('SELECT count(*) FROM devices WHERE owner=?',(row['owner'],)).fetchone()[0] >= 100:
                raise HTTPException(429, 'Device quota reached; revoke unused devices')
            raw = secrets.token_urlsafe(32)
            db.execute('INSERT INTO devices VALUES(?,?,?,?,?)', (digest(raw),row['owner'],APPID,row['scopes'],time.time()+2592000))
            db.execute('UPDATE pairings SET consumed=1 WHERE hash=?', (key,))
        return JSONResponse({'status':'approved','device_token':raw,'token_type':'Bearer','expires_in':2592000})

    async def approve_device(request):
        try:
            session = store.session(request, True)
        except HTTPException:
            if request.method == 'GET':
                return RedirectResponse('/login?' + urlencode({'next':'/devices/approve'}),303)
            raise
        if request.method == 'GET':
            return page('Подключить Deck', ui.device_body(session['csrf']))
        data = await form(request, session, config.issuer)
        store.limit('approve:'+session['owner'], 10)
        if set(data)-{'csrf','user_code','appid',*SCOPES} or data.get('appid')!=str(APPID):
            raise HTTPException(422, 'Choose the supported game explicitly')
        scopes = sorted(s for s in SCOPES if data.get(s)=='yes')
        if not scopes:
            raise HTTPException(422, 'Choose at least one permission')
        user = str(data.get('user_code','')).upper()
        if not re.fullmatch('[A-F0-9]{8}', user):
            raise HTTPException(400, 'Invalid or expired device code')
        with store.db() as db:
            row = db.execute('UPDATE pairings SET owner=?,scopes=? WHERE user_hash=? AND expires>? AND owner IS NULL AND consumed=0 RETURNING hash',
                (session['owner'],json.dumps(scopes),digest(user),time.time())).fetchone()
            if not row:
                raise HTTPException(400, 'Invalid or expired device code')
            for s in scopes:
                db.execute('INSERT OR IGNORE INTO grants VALUES(?,?,?)', (session['owner'],APPID,s))
        return page('Устройство подключено', ui.approved_body())

    async def ingest(request):
        bearer = request.headers.get('authorization','')
        if not bearer.startswith('Bearer ') or len(bearer)>150:
            raise HTTPException(401, 'Device credential required')
        key = digest(bearer[7:])
        store.limit('ingest:'+key, 120)
        data = await json_body(request)
        try:
            if set(data) != {'event_id','appid','kind','payload'} or type(data['appid']) is not int or data['appid']!=APPID or data['kind']!='save_summary':
                raise ValueError()
            if not isinstance(data['event_id'], str) or len(data['event_id']) != 36:
                raise ValueError()
            UUID(data['event_id'])
            payload = SaveSummary.model_validate(data['payload']).model_dump_json()
        except (ValueError, TypeError, KeyError, ValidationError):
            raise HTTPException(422, 'Only supported four-field summaries are accepted') from None
        with store.db() as db:
            device = db.execute('SELECT * FROM devices WHERE hash=? AND expires>?', (key,time.time())).fetchone()
            if not device:
                raise HTTPException(401, 'Invalid device credential')
            if 'saves.summary' not in json.loads(device['scopes']) or not db.execute("SELECT 1 FROM grants WHERE owner=? AND appid=? AND scope='saves.summary'", (device['owner'], APPID)).fetchone():
                raise HTTPException(403, 'Current game permission required')
            prior = db.execute('SELECT payload_hash FROM events WHERE device_hash=? AND event_id=?', (key,data['event_id'])).fetchone()
            duplicate = bool(prior)
            if prior and prior['payload_hash'] != digest(payload):
                raise HTTPException(409, 'Event ID already used with different content')
            if not duplicate:
                db.execute('DELETE FROM events WHERE created<?', (time.time()-2678400,))
                if db.execute('SELECT count(*) FROM events WHERE device_hash=?', (key,)).fetchone()[0] >= 10000:
                    raise HTTPException(429, 'Device event quota reached; re-pair required')
                db.execute('INSERT INTO events VALUES(?,?,?,?,?)', (device['owner'],key,data['event_id'],time.time(),digest(payload)))
                now = time.time()
                db.execute('INSERT OR REPLACE INTO observations VALUES(?,?,?,?)', (device['owner'],APPID,payload,now))
                store.record_notification(db,device['owner'],APPID,payload,key+':'+data['event_id'],now)
        return JSONResponse({'accepted':True,'duplicate':duplicate})

    async def consent(request):
        try:
            session = store.session(request, True)
        except HTTPException:
            if request.method != 'GET':
                raise
            req = request.query_params.get('request','')
            if not provider.get_pending(req):
                raise HTTPException(400, 'Expired authorization request')
            return RedirectResponse('/login?' + urlencode({'next':'/oauth/consent?request='+req}),303)
        if request.method == 'GET':
            req = request.query_params.get('request','')
            pending = provider.get_pending(req)
            if not pending:
                raise HTTPException(400, 'Expired authorization request')
            client = await provider.get_client(pending['client_id'])
            client_label = ((client.client_name or 'Unnamed client') + ' — ' + pending['redirect_uri']) if client else 'Unknown client'
            return page('Подключить помощника', ui.consent_body(session['csrf'],req,client_label))
        data = await form(request,session,config.issuer)
        try:
            target = provider.approve(str(data.get('request','')),session['owner'])
        except (ValueError, LookupError):
            raise HTTPException(400, 'Expired authorization request') from None
        return RedirectResponse(target,303)

    async def notification_settings(request):
        session = store.session(request,True)
        data = await form(request,session,config.issuer)
        if set(data) != {'csrf','appid','enabled'} or data.get('appid') != str(APPID) or data.get('enabled') not in ('yes','no'):
            raise HTTPException(422,'Explicit game and notification choice required')
        enabled = data['enabled']=='yes'
        with store.db() as db:
            if enabled and not db.execute("SELECT 1 FROM grants WHERE owner=? AND appid=? AND scope='saves.summary'",(session['owner'],APPID)).fetchone():
                raise HTTPException(403,'Current game permission required')
            previous = db.execute('SELECT enabled,epoch FROM notification_settings WHERE owner=? AND appid=?',(session['owner'],APPID)).fetchone()
            # Repeated identical choice is idempotent, not a new consent epoch.
            if not previous or bool(previous['enabled']) != enabled:
                row = db.execute('SELECT payload FROM observations WHERE owner=? AND appid=?',(session['owner'],APPID)).fetchone() if enabled else None
                epoch = previous['epoch']+1 if previous else 1
                db.execute('INSERT INTO notification_settings(owner,appid,enabled,baseline,epoch,updated) VALUES(?,?,?,?,?,?) ON CONFLICT(owner,appid) DO UPDATE SET enabled=excluded.enabled,baseline=excluded.baseline,epoch=excluded.epoch,updated=excluded.updated',
                    (session['owner'],APPID,int(enabled),row['payload'] if row else None,epoch,time.time()))
            if not enabled:
                db.execute('DELETE FROM notifications WHERE owner=? AND appid=?',(session['owner'],APPID))
        return RedirectResponse('/',303)

    async def notification_read(request):
        session = store.session(request,True)
        data = await form(request,session,config.issuer)
        if set(data) != {'csrf','notification_id'}:
            raise HTTPException(422,'Notification ID required')
        try:
            if len(data['notification_id']) != 36:
                raise ValueError()
            UUID(data['notification_id'])
        except (ValueError,TypeError,AttributeError):
            raise HTTPException(422,'Invalid notification ID') from None
        with store.db() as db:
            row = db.execute('UPDATE notifications SET read_at=? WHERE id=? AND owner=? AND created>=? AND EXISTS(SELECT 1 FROM grants WHERE owner=? AND appid=notifications.appid AND scope=?) RETURNING id',
                (time.time(),data['notification_id'],session['owner'],time.time()-INBOX_TTL,session['owner'],'saves.summary')).fetchone()
            if not row:
                raise HTTPException(404,'Notification unavailable')
        return RedirectResponse('/',303)

    async def revoke(request):
        session=store.session(request,True)
        await form(request,session,config.issuer)
        with store.db() as db:
            for table in ('grants','devices','observations','events','notification_settings','notifications'):
                db.execute(f'DELETE FROM {table} WHERE owner=?',(session['owner'],))
            db.execute('DELETE FROM pairings WHERE owner=?',(session['owner'],))
            provider.revoke_subject(session['owner'], connection=db)
        return RedirectResponse('/',303)

    async def logout(request):
        session=store.session(request,True)
        await form(request,session,config.issuer)
        with store.db() as db:
            db.execute('DELETE FROM sessions WHERE hash=?',(session['hash'],))
        response=RedirectResponse('/',303)
        response.delete_cookie(COOKIE,secure=True,httponly=True,samesite='lax',path='/')
        return response

    async def metadata(request):
        data=build_metadata(AnyHttpUrl(config.issuer),None,registration,revocation).model_dump(mode='json',exclude_none=True)
        data['token_endpoint_auth_methods_supported']=['none']
        return JSONResponse(data)

    app=mcp.streamable_http_app()
    app.routes.insert(0,Route('/.well-known/oauth-authorization-server',metadata))
    app.routes.extend([Route('/assets/console.css',stylesheet),Route('/setup',setup_page),Route('/downloads/deck-companion.zip',download),Route('/downloads/deck-companion.zip.sha256',download_checksum),Route('/healthz',health),Route('/',home),Route('/login',login),Route('/steam/callback',callback),
        Route('/v1/devices/pair/start',pair_start,methods=['POST']),Route('/v1/devices/pair/poll',pair_poll,methods=['POST']),
        Route('/devices/approve',approve_device,methods=['GET','POST']),Route('/v1/device/observations',ingest,methods=['POST']),
        Route('/oauth/consent',consent,methods=['GET','POST']),Route('/account/notifications',notification_settings,methods=['POST']),Route('/account/notifications/read',notification_read,methods=['POST']),Route('/account/revoke',revoke,methods=['POST']),Route('/logout',logout,methods=['POST'])])
    app.add_middleware(Boundary,config=config,store=store)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=[urlsplit(config.issuer).hostname])
    app.state.store,app.state.provider,app.state.config=store,provider,config
    return app
