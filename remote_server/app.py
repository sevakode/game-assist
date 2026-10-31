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
import threading
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
from pydantic import AnyHttpUrl, ValidationError, BaseModel, ConfigDict, Field
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
from .auth_response import identify_authorization_errors
from .database import Database
from .achievements import AchievementReader
from .library_reader import LibraryReader
from . import ui
from .browser_errors import http_exception as browser_http_exception, wants_browser_error, error_page
from .games import CURRENT_GAME_IDS, CATALOG_REVISION, GAMES, DISCOVERY_TITLES, discovery_catalog

APPID = 4231820
COOKIE = '__Host-ga_session'
SCOPES = {'saves.summary','saves.metadata'}
ACCOUNT_SCOPES = SCOPES | {'achievements.read'}
MAX_GAMES = 100
LIBRARY_ROWS_GLOBAL = 128
ACHIEVEMENT_ROWS_GLOBAL = 512
ACHIEVEMENT_ROWS_PER_OWNER = 20

class SaveMetadataSummary(BaseModel):
    model_config = ConfigDict(extra='forbid')
    size_bytes: int = Field(strict=True,ge=0,le=1073741824)
    modified_ns: int = Field(strict=True,ge=0,le=2**63-1)

def validated_summary(payload):
    """One allowlist for manual and device summaries; never raw-save decoding."""
    return SaveSummary.model_validate(payload).model_dump_json()

def parse_appid(value):
    if not isinstance(value,str) or not re.fullmatch(r'[1-9][0-9]{0,9}',value) or int(value)>2147483647:
        raise HTTPException(422,'Positive Steam AppID up to 2147483647 required')
    return int(value)
NOTICE = 'Получена сводка с изменением разрешённых счётчиков сохранения. Получение предметов или улучшений не подтверждено.'
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
        self.achievements_available = False
        self.library_available = False

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

    def catalog(self, owner, connection=None):
        if connection is None:
            with self.db() as db:
                return self.catalog(owner,db)
        db=connection
        selected={row['appid'] for row in db.execute('SELECT appid FROM game_selections WHERE owner=?',(owner,))}
        grants={(row['appid'],row['scope']) for row in db.execute('SELECT appid,scope FROM grants WHERE owner=?',(owner,))}
        registered={row['appid']:row['label'] for row in db.execute('SELECT appid,label FROM game_registrations WHERE owner=?',(owner,))}
        ids=list(CURRENT_GAME_IDS)+sorted(set(registered)-set(CURRENT_GAME_IDS))
        return [{'appid':appid,'name':GAMES[appid]['name'] if appid in CURRENT_GAME_IDS else (registered[appid] or DISCOVERY_TITLES.get(appid) or f'Steam AppID {appid}'),
                 'user_label_unverified':appid not in CURRENT_GAME_IDS and bool(registered[appid] or appid not in DISCOVERY_TITLES),
                 'selected':appid in selected,
                 'authorized':appid in selected and (appid,'saves.summary') in grants,
                 'authorized_scopes':sorted(scope for scope in ACCOUNT_SCOPES if appid in selected and (appid,scope) in grants),
                 'metadata_authorized':appid in selected and (appid,'saves.metadata') in grants,
                 'summary_supported':appid==APPID,'metadata_supported':True,
                 'cloud_available':False,'achievements_available':self.achievements_available,
                 'achievements_authorized':appid in selected and (appid,'achievements.read') in grants,
                 'parser_version':'1.1.3' if appid==APPID else None,'save_format_version':'1.1.3' if appid==APPID else None,'game_build':None,
                 'source_status':'device_summary_only' if appid==APPID else 'metadata_only_parser_unavailable'} for appid in ids]

    @staticmethod
    def catalog_revision(owner,catalog):
        return digest('catalog-v2:'+owner+':'+json.dumps([(g['appid'],g['name']) for g in catalog],ensure_ascii=False,separators=(',',':')))

    @staticmethod
    def revoke_scope(db,owner,appid,scope):
        db.execute('DELETE FROM grants WHERE owner=? AND appid=? AND scope=?',(owner,appid,scope))
        if scope=='achievements.read':
            db.execute('DELETE FROM achievement_cache WHERE owner=? AND appid=?',(owner,appid))
            return
        for row in db.execute('SELECT hash,scopes FROM devices WHERE owner=? AND appid=?',(owner,appid)).fetchall():
            if scope in json.loads(row['scopes']):
                db.execute('DELETE FROM events WHERE owner=? AND device_hash=?',(owner,row['hash']))
                db.execute('DELETE FROM devices WHERE hash=? AND owner=?',(row['hash'],owner))
        for row in db.execute('SELECT hash,scopes FROM pairings WHERE owner=? AND appid=?',(owner,appid)).fetchall():
            if scope in json.loads(row['scopes'] or '[]'):
                db.execute('DELETE FROM pairings WHERE hash=? AND owner=?',(row['hash'],owner))
        kind='save_summary' if scope=='saves.summary' else 'save_metadata'
        db.execute('DELETE FROM observations_v2 WHERE owner=? AND appid=? AND kind=?',(owner,appid,kind))
        db.execute('DELETE FROM events WHERE owner=? AND appid=? AND kind=?',(owner,appid,kind))
        if scope=='saves.summary':
            for table in ('observations','notification_settings','notifications'):
                db.execute(f'DELETE FROM {table} WHERE owner=? AND appid=?',(owner,appid))

    @staticmethod
    def revoke_game(db, owner, appid, deselect=False):
        for scope in ACCOUNT_SCOPES:
            Store.revoke_scope(db,owner,appid,scope)
        for table in ('grants','devices','observations','observations_v2','notification_settings','notifications','events','pairings'):
            db.execute(f'DELETE FROM {table} WHERE owner=? AND appid=?',(owner,appid))
        if deselect:
            db.execute('DELETE FROM game_selections WHERE owner=? AND appid=?',(owner,appid))

    def library(self,owner):
        with self.db() as db:
            row=db.execute('SELECT * FROM library_cache WHERE owner=?',(owner,)).fetchone()
            state={'configured':self.library_available,'enabled':bool(row),'status':'not_requested','games':[],'received_at':None,'source':'steam_web_api'}
            if not self.library_available:state['status']='not_configured'
            elif row:
                state.update(status=row['status'],received_at=row['received_at'])
                if row['expires'] and row['expires']<=time.time():
                    state['status']='expired'
                    db.execute("UPDATE library_cache SET payload=NULL,status='expired' WHERE owner=?",(owner,))
                elif row['status']=='ok' and row['payload']:state['games']=json.loads(row['payload'])
            return state

    @staticmethod
    def expire_achievements(db):
        for row in db.execute('SELECT owner,appid FROM achievement_cache WHERE expires<? AND payload IS NOT NULL LIMIT 100',(time.time(),)).fetchall():
            db.execute("UPDATE achievement_cache SET payload=NULL,status='expired' WHERE owner=? AND appid=?",(row['owner'],row['appid']))

    def projection(self, owner):
        result={'spoiler_policy':'strict','games':[]}
        with self.db() as db:
            catalog=self.catalog(owner,db)
            for game in catalog:
                scopes=game['authorized_scopes']
                if not game['selected'] or not scopes:
                    continue
                item={'appid':game['appid'],'status':'unknown','summary':None,'metadata':None,'received_at':None,'summary_received_at':None,'metadata_received_at':None,'summary_source':None,'metadata_source':None,'observation_time':'unknown',
                      'summary_supported':game['summary_supported'],'cloud_available':False,'achievements_available':self.achievements_available}
                if 'achievements.read' in scopes:
                    cached=db.execute('SELECT * FROM achievement_cache WHERE owner=? AND appid=?',(owner,game['appid'])).fetchone()
                    status='not_requested';items=[];received=None
                    if not self.achievements_available:status='not_configured'
                    elif cached:
                        status=cached['status'];received=cached['received_at']
                        if cached['expires'] and cached['expires']<=time.time():
                            status='expired'
                            db.execute("UPDATE achievement_cache SET payload=NULL,status='expired' WHERE owner=? AND appid=?",(owner,game['appid']))
                        elif status=='ok' and cached['payload']:items=json.loads(cached['payload'])
                    item['achievements']={'status':status,'items':items,'received_at':received,'source':'steam_web_api'}
                for kind,scope,model,key in [('save_summary','saves.summary',SaveSummary,'summary'),('save_metadata','saves.metadata',SaveMetadataSummary,'metadata')]:
                    if scope not in scopes or (kind=='save_summary' and game['appid']!=APPID):
                        continue
                    row=db.execute('SELECT payload,observed,source FROM observations_v2 WHERE owner=? AND appid=? AND kind=?',(owner,game['appid'],kind)).fetchone()
                    if row:
                        item[key]=model.model_validate_json(row['payload']).model_dump(mode='json')
                        item[key+'_received_at']=row['observed']
                        item[key+'_source']=row['source']
                        item['received_at']=max(item['received_at'] or 0,row['observed'])
                if item['summary'] is not None:item['status']='reported_not_independently_verified'
                elif item['metadata'] is not None:item['status']='metadata_only_not_game_progress'
                result['games'].append(item)
        return result

    def inbox(self, owner):
        now = time.time()
        with self.db() as db:
            db.execute('DELETE FROM notifications WHERE created<?', (now-INBOX_TTL,))
            permitted = bool(db.execute("SELECT 1 FROM grants WHERE owner=? AND appid=? AND scope='saves.summary'", (owner,APPID)).fetchone()) and bool(db.execute('SELECT 1 FROM game_selections WHERE owner=? AND appid=?',(owner,APPID)).fetchone())
            settings = db.execute('SELECT enabled FROM notification_settings WHERE owner=? AND appid=?', (owner,APPID)).fetchone()
            rows = db.execute('SELECT id,created,read_at FROM notifications WHERE owner=? AND appid=? ORDER BY created DESC,id DESC LIMIT 50', (owner,APPID)).fetchall() if permitted else []
        items = [{'id':row['id'], 'message':NOTICE, 'created_at':row['created'], 'read':row['read_at'] is not None} for row in rows]
        return {'enabled':bool(permitted and settings and settings['enabled']), 'can_enable':permitted,
                'unread_count':sum(not row['read'] for row in items), 'items':items,
                'source':'accepted_safe_summary', 'cloud_available':False, 'push_available':False}

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
        async def secure(message):
            if message['type'] == 'http.response.start':
                message['headers'] = [(k,v) for k,v in message['headers'] if k.lower() not in (b'access-control-allow-origin', b'cache-control')]
                message['headers'] += [(b'cache-control', b'no-store'), (b'referrer-policy', b'no-referrer'),
                    (b'x-content-type-options', b'nosniff'), (b'content-security-policy', (b"default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'" + (b"; script-src 'self'; connect-src 'self'" if scope['path']=='/import' else b''))),
                    (b'strict-transport-security', b'max-age=31536000')]
            await send(message)
        async def reject(data, status):
            response=error_page(request,status) if wants_browser_error(request) else JSONResponse(data,status)
            return await response(scope,receive,secure)
        if len(scope.get('query_string', b'')) > 8192:
            return await reject({'error': 'query_too_large'}, 414)
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body.extend(message.get('body', b''))
            if len(body) > 16384:
                return await reject({'error': 'body_too_large'}, 413)
            if not message.get('more_body'):
                break
        path = scope['path']
        if request.headers.get('origin') not in (None, self.config.issuer):
            return await reject({'error': 'origin_denied'}, 403)
        if path in ('/authorize', '/token', '/register', '/login', '/steam/callback', '/v1/devices/pair/start', '/v1/devices/pair/poll', '/v1/device/observations'):
            try:
                self.store.limit('edge:' + path + ':' + digest(request.client.host if request.client else 'unknown'), 600 if path in ('/v1/devices/pair/poll','/v1/device/observations') else 60)
            except HTTPException:
                return await reject({'error': 'rate_limited'}, 429)
        if path == '/register':
            try:
                registration = json.loads(body)
                redirects = registration.get('redirect_uris') if isinstance(registration, dict) else None
                if not isinstance(redirects, list) or not redirects or any(not isinstance(u, str) or u not in self.config.redirect_uris for u in redirects):
                    raise ValueError()
            except (ValueError, TypeError):
                return await reject({'error': 'invalid_client_metadata'}, 400)
        if path in ('/authorize', '/token'):
            from urllib.parse import parse_qsl
            try:
                pairs = list(request.query_params.multi_items()) if request.method == 'GET' else parse_qsl(body.decode(), keep_blank_values=True, strict_parsing=True, max_num_fields=30)
            except (ValueError, UnicodeError):
                return await reject({'error': 'invalid_request'}, 400)
            params = dict(pairs)
            if len(params) != len(pairs) or ('redirect_uri' in params and params['redirect_uri'] not in self.config.redirect_uris) or ('resource' in params and params['resource'] != self.config.issuer + '/mcp'):
                return await reject({'error': 'invalid_request'}, 400)
        sent = False
        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()
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

def create_app(config=None, steam=None, database=None, download_dir=None, achievement_reader=None, library_reader=None):
    config = config or Config.from_env()
    database = database or Database(config.db_path, database_url=config.database_url)
    store = Store(config.db_path, database=database)
    steam = steam or SteamService()
    achievements = achievement_reader or AchievementReader()
    store.achievements_available = achievements.configured
    achievement_slots = threading.BoundedSemaphore(2)
    libraries = library_reader or LibraryReader()
    store.library_available = libraries.configured
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
        requested = request.query_params.get('game')
        if requested is not None:
            if not re.fullmatch(r'[1-9][0-9]{0,9}', requested) or int(requested) > 2147483647:
                raise HTTPException(400, 'Invalid game')
            return RedirectResponse('/games?' + urlencode({'game': requested}), 303)
        try:
            store.session(request, True)
            signed_in = True
        except HTTPException:
            signed_in = False
        return page('Играй. Открывай сам.', ui.welcome_panel(signed_in))

    async def connect_claude(request):
        return page('Подключить Claude', ui.claude_body(config.issuer + '/mcp'))

    async def games(request):
        try:
            session = store.session(request, True)
        except HTTPException:
            requested=request.query_params.get('game')
            if requested is not None and requested not in {str(i) for i in DISCOVERY_TITLES}:
                raise HTTPException(404,'Public game preset unavailable')
            return page('Игровой спутник', ui.landing_body(selected_appid=int(requested) if requested else None,discovery_catalog=discovery_catalog(),mcp_url=config.issuer+'/mcp'))
        inbox = store.inbox(session['owner'])
        catalog = store.catalog(session['owner'])
        requested = request.query_params.get('game')
        selected_ids = {item['appid'] for item in catalog if item['selected']}
        try:
            focus = int(requested) if requested is not None else next((g['appid'] for g in catalog if g['appid'] in selected_ids),None)
        except (ValueError,TypeError):
            raise HTTPException(400,'Invalid game') from None
        if requested is not None and focus not in selected_ids:
            raise HTTPException(404,'Selected game unavailable')
        return page('Твоя игровая станция', ui.home_body(store.projection(session['owner']),session['csrf'],inbox,capabilities={'mcp_url':config.issuer+'/mcp','discovery_catalog':discovery_catalog(store.achievements_available),'owned_library':store.library(session['owner']),'catalog':catalog,'catalog_revision':store.catalog_revision(session['owner'],catalog),'selected_appid':focus}))

    async def login(request):
        next_path = request.query_params.get('next', '/')
        if next_path not in ('/', '/games', '/devices/approve', '/import') and not re.fullmatch(r'/oauth/consent\?request=[A-Za-z0-9_-]{43}', next_path):
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
        data=await json_body(request)
        if data=={}:
            appid,scopes=APPID,['saves.summary']
        else:
            if set(data)!={'appid','scopes'} or type(data['appid']) is not int or not 0<data['appid']<=2147483647 or not isinstance(data['scopes'],list):
                raise HTTPException(422,'Explicit AppID and scopes required')
            appid=data['appid'];scopes=data['scopes']
            if not scopes or len(scopes)>2 or any(not isinstance(x,str) or x not in SCOPES for x in scopes) or len(set(scopes))!=len(scopes) or ('saves.summary' in scopes and appid!=APPID):
                raise HTTPException(422,'Unsupported game/source pairing request')
            scopes=sorted(scopes)
        code,user=secrets.token_urlsafe(32),secrets.token_hex(4).upper()
        with store.db() as db:
            db.execute('DELETE FROM pairings WHERE expires<?',(time.time(),))
            if db.execute('SELECT count(*) FROM pairings').fetchone()[0]>=2000:
                raise HTTPException(429,'Pairing capacity reached')
            db.execute('INSERT INTO pairings(hash,user_hash,expires,appid,requested_scopes) VALUES(?,?,?,?,?)',(digest(code),digest(user),time.time()+600,appid,json.dumps(scopes)))
        return JSONResponse({'device_code':code,'user_code':user,'verification_uri':config.issuer+'/devices/approve','expires_in':600,'interval':5,'appid':appid,'scopes':scopes})

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
            scopes=json.loads(row['scopes'])
            if not db.execute('SELECT 1 FROM game_selections WHERE owner=? AND appid=?',(row['owner'],row['appid'])).fetchone() or any(not db.execute('SELECT 1 FROM grants WHERE owner=? AND appid=? AND scope=?',(row['owner'],row['appid'],scope)).fetchone() for scope in scopes):
                return JSONResponse({'status':'expired'},400)
            db.execute('DELETE FROM devices WHERE expires<=?', (time.time(),))
            if db.execute('SELECT count(*) FROM devices WHERE owner=?',(row['owner'],)).fetchone()[0] >= 100:
                raise HTTPException(429, 'Device quota reached; revoke unused devices')
            raw = secrets.token_urlsafe(32)
            db.execute('INSERT INTO devices VALUES(?,?,?,?,?)', (digest(raw),row['owner'],row['appid'],row['scopes'],time.time()+2592000))
            db.execute('UPDATE pairings SET consumed=1 WHERE hash=?', (key,))
        return JSONResponse({'status':'approved','device_token':raw,'token_type':'Bearer','expires_in':2592000,'appid':row['appid'],'scopes':scopes})

    async def approve_device(request):
        try:
            session=store.session(request,True)
        except HTTPException:
            if request.method=='GET':return RedirectResponse('/login?'+urlencode({'next':'/devices/approve'}),303)
            raise
        if request.method=='GET':
            return page('Подключить устройство',ui.device_body(session['csrf'],catalog=store.catalog(session['owner'])))
        data=await form(request,session,config.issuer)
        store.limit('approve:'+session['owner'],10)
        if set(data)-{'csrf','user_code','appid',*SCOPES}:
            raise HTTPException(422,'Unknown pairing field')
        appid=parse_appid(str(data.get('appid','')))
        if any(data.get(scope) not in (None,'yes') for scope in SCOPES):
            raise HTTPException(422,'Explicit permissions required')
        scopes=sorted(scope for scope in ACCOUNT_SCOPES if data.get(scope)=='yes')
        user=str(data.get('user_code','')).upper()
        if not scopes or not re.fullmatch('[A-F0-9]{8}',user):
            raise HTTPException(400,'Invalid device code or permissions')
        with store.db() as db:
            if appid not in {g['appid'] for g in store.catalog(session['owner'],db)}:
                raise HTTPException(422,'Add this AppID to your games before pairing')
            pending=db.execute('SELECT * FROM pairings WHERE user_hash=? AND expires>? AND owner IS NULL AND consumed=0',(digest(user),time.time())).fetchone()
            if not pending:
                raise HTTPException(400,'Invalid or expired device code')
            if appid!=pending['appid'] or scopes!=sorted(json.loads(pending['requested_scopes'])) or ('saves.summary' in scopes and appid!=APPID):
                raise HTTPException(422,'Game and scopes must exactly match the request shown on your device')
            db.execute('UPDATE pairings SET owner=?,scopes=? WHERE hash=?',(session['owner'],json.dumps(scopes),pending['hash']))
            db.execute('INSERT INTO game_selections(owner,appid,selected_at) VALUES(?,?,?) ON CONFLICT(owner,appid) DO NOTHING',(session['owner'],appid,time.time()))
            for scope in scopes:db.execute('INSERT OR IGNORE INTO grants VALUES(?,?,?)',(session['owner'],appid,scope))
        return page('Устройство подключено',ui.approved_body())

    async def ingest(request):
        bearer=request.headers.get('authorization','')
        if not bearer.startswith('Bearer ') or len(bearer)>150:
            raise HTTPException(401,'Device credential required')
        key=digest(bearer[7:]);store.limit('ingest:'+key,120)
        data=await json_body(request)
        try:
            if set(data)!={'event_id','appid','kind','payload'} or type(data['appid']) is not int or not 0<data['appid']<=2147483647:
                raise ValueError()
            if not isinstance(data['event_id'],str) or len(data['event_id'])!=36:raise ValueError()
            UUID(data['event_id'])
            appid,kind=data['appid'],data['kind']
            if kind=='save_summary' and appid==APPID:
                model,scope=SaveSummary,'saves.summary'
            elif kind=='save_metadata':
                model,scope=SaveMetadataSummary,'saves.metadata'
            else:raise ValueError()
            payload=validated_summary(data['payload']) if model is SaveSummary else model.model_validate(data['payload']).model_dump_json()
        except (ValueError,TypeError,KeyError,ValidationError):
            raise HTTPException(422,'Only permitted bounded metadata or supported four-field summaries are accepted') from None
        with store.db() as db:
            device=db.execute('SELECT * FROM devices WHERE hash=? AND expires>?',(key,time.time())).fetchone()
            if not device:raise HTTPException(401,'Invalid device credential')
            if device['appid']!=appid or scope not in json.loads(device['scopes']) or not db.execute('SELECT 1 FROM grants WHERE owner=? AND appid=? AND scope=?',(device['owner'],appid,scope)).fetchone() or not db.execute('SELECT 1 FROM game_selections WHERE owner=? AND appid=?',(device['owner'],appid)).fetchone():
                raise HTTPException(403,'Current scoped game permission required')
            prior=db.execute('SELECT payload_hash,appid,kind FROM events WHERE device_hash=? AND event_id=?',(key,data['event_id'])).fetchone()
            duplicate=bool(prior)
            if prior and (prior['payload_hash']!=digest(payload) or prior['appid']!=appid or prior['kind']!=kind):
                raise HTTPException(409,'Event ID already used with different content')
            if not duplicate:
                now=time.time()
                db.execute('DELETE FROM events WHERE created<?',(now-2678400,))
                if db.execute('SELECT count(*) FROM events WHERE device_hash=?',(key,)).fetchone()[0]>=10000:
                    raise HTTPException(429,'Device event quota reached; re-pair required')
                db.execute('INSERT INTO events(owner,device_hash,event_id,created,payload_hash,appid,kind) VALUES(?,?,?,?,?,?,?)',(device['owner'],key,data['event_id'],now,digest(payload),appid,kind))
                db.execute("INSERT INTO observations_v2(owner,appid,kind,payload,observed) VALUES(?,?,?,?,?) ON CONFLICT(owner,appid,kind) DO UPDATE SET payload=excluded.payload,observed=excluded.observed,source='device'",(device['owner'],appid,kind,payload,now))
                if kind=='save_summary':store.record_notification(db,device['owner'],appid,payload,key+':'+data['event_id'],now)
        return JSONResponse({'accepted':True,'duplicate':duplicate})

    async def manual_import_page(request):
        try:session=store.session(request,True)
        except HTTPException:return RedirectResponse('/login?next=%2Fimport',303)
        permitted=any(game['appid']==APPID and game['selected'] and 'saves.summary' in game['authorized_scopes'] for game in store.catalog(session['owner']))
        return page('Ручной импорт',ui.manual_import_body(session['csrf'],permitted))

    async def import_script(request):
        return FileResponse(Path(__file__).parent/'import.js',media_type='text/javascript')

    async def parser_script(request):
        return FileResponse(Path(__file__).parent/'belmont-parser.js',media_type='text/javascript')

    async def manual_import(request):
        session=store.session(request,True)
        if request.headers.get('origin')!=config.issuer:
            raise HTTPException(403,'Origin required')
        data=await json_body(request)
        if not isinstance(data.get('csrf'),str) or not secrets.compare_digest(data['csrf'],session['csrf']):
            raise HTTPException(403,'Invalid CSRF token')
        try:
            if set(data)!={'csrf','event_id','appid','kind','payload'} or type(data['appid']) is not int or data['appid']!=APPID or data['kind']!='save_summary':raise ValueError()
            if not isinstance(data['event_id'],str) or len(data['event_id'])!=36:raise ValueError()
            UUID(data['event_id'])
            payload=validated_summary(data['payload'])
        except (ValueError,TypeError,KeyError,ValidationError):
            raise HTTPException(422,'Only the supported Belmont four-field summary is accepted') from None
        owner=session['owner']
        # Separate server-bound channel; no device credential or client owner accepted.
        key='browser:'+digest(owner)
        store.limit('manual:'+digest(owner),30)
        with store.db() as db:
            if not db.execute("SELECT 1 FROM grants WHERE owner=? AND appid=? AND scope='saves.summary'",(owner,APPID)).fetchone() or not db.execute('SELECT 1 FROM game_selections WHERE owner=? AND appid=?',(owner,APPID)).fetchone():
                raise HTTPException(403,'Current selected game and summary permission required')
            prior=db.execute('SELECT payload_hash FROM events WHERE device_hash=? AND event_id=?',(key,data['event_id'])).fetchone()
            if prior and prior['payload_hash']!=digest(payload):raise HTTPException(409,'Event ID already used with different content')
            if not prior:
                now=time.time()
                db.execute('DELETE FROM events WHERE created<?',(now-2678400,))
                if db.execute('SELECT count(*) FROM events WHERE device_hash=?',(key,)).fetchone()[0]>=10000:raise HTTPException(429,'Manual import event quota reached')
                db.execute('INSERT INTO events(owner,device_hash,event_id,created,payload_hash,appid,kind) VALUES(?,?,?,?,?,?,?)',(owner,key,data['event_id'],now,digest(payload),APPID,'save_summary'))
                db.execute("INSERT INTO observations_v2(owner,appid,kind,payload,observed,source) VALUES(?,?,?,?,?,?) ON CONFLICT(owner,appid,kind) DO UPDATE SET payload=excluded.payload,observed=excluded.observed,source=excluded.source",(owner,APPID,'save_summary',payload,now,'browser_manual'))
                store.record_notification(db,owner,APPID,payload,key+':'+data['event_id'],now)
        return JSONResponse({'accepted':True,'duplicate':bool(prior),'source':'browser_manual'})

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

    async def add_game(request):
        session=store.session(request,True)
        data=await form(request,session,config.issuer)
        if set(data)-{'csrf','appid','label'} or 'appid' not in data:
            raise HTTPException(422,'AppID and optional label required')
        appid=parse_appid(data['appid'])
        label=str(data.get('label','')).strip()
        if len(label)>120 or (label and not label.isprintable()):
            raise HTTPException(422,'Use a plain text label up to 120 characters')
        with store.db() as db:
            ids={g['appid'] for g in store.catalog(session['owner'],db)}
            if appid not in ids and len(ids)>=MAX_GAMES:
                raise HTTPException(429,'Maximum 100 games per account')
            if appid not in CURRENT_GAME_IDS:
                db.execute('INSERT INTO game_registrations(owner,appid,label,created) VALUES(?,?,?,?) ON CONFLICT(owner,appid) DO UPDATE SET label=excluded.label',(session['owner'],appid,label,time.time()))
        return RedirectResponse('/games#library',303)

    async def choose_games(request):
        session=store.session(request,True)
        data=await form(request,session,config.issuer)
        catalog=store.catalog(session['owner'])
        ids={g['appid'] for g in catalog}
        game_fields={f'game_{i}' for i in ids}
        metadata_fields={f'metadata_{i}' for i in ids}
        choices=game_fields|metadata_fields|{'summary_4231820'}
        if set(data)-({'csrf','action','catalog_revision'}|choices) or any(data.get(k) not in (None,'yes') for k in choices):
            raise HTTPException(422,'Unknown or invalid game choice')
        action=data.get('action')
        if action not in ('review','review_all','confirm'):
            raise HTTPException(422,'Review or confirm games')
        selected=ids if action=='review_all' else {i for i in ids if data.get(f'game_{i}')=='yes'}
        if action!='confirm':
            revision=store.catalog_revision(session['owner'],catalog)
            for game in catalog:game['selected']=game['appid'] in selected
            return page('Проверить игры и разрешения',ui.games_review_body(session['csrf'],catalog,catalog_revision=revision))
        summary=data.get('summary_4231820')=='yes'
        metadata={i for i in ids if data.get(f'metadata_{i}')=='yes'}
        if (summary and APPID not in selected) or metadata-selected:
            raise HTTPException(422,'Select a game before granting access')
        with store.db() as db:
            if data.get('catalog_revision')!=store.catalog_revision(session['owner'],store.catalog(session['owner'],db)):
                raise HTTPException(409,'Game list changed; review it again')
            previous={row['appid'] for row in db.execute('SELECT appid FROM game_selections WHERE owner=?',(session['owner'],))}
            for appid in previous-selected:store.revoke_game(db,session['owner'],appid,deselect=True)
            for appid in selected:
                db.execute('INSERT INTO game_selections(owner,appid,selected_at) VALUES(?,?,?) ON CONFLICT(owner,appid) DO NOTHING',(session['owner'],appid,time.time()))
                for scope,enabled in [('saves.metadata',appid in metadata),('saves.summary',appid==APPID and summary)]:
                    if enabled:db.execute('INSERT OR IGNORE INTO grants VALUES(?,?,?)',(session['owner'],appid,scope))
                    else:store.revoke_scope(db,session['owner'],appid,scope)
        return RedirectResponse('/games',303)

    async def game_permission(request):
        session=store.session(request,True)
        data=await form(request,session,config.issuer)
        if set(data)!={'csrf','appid','scope','enabled'} or data.get('enabled') not in ('yes','no'):
            raise HTTPException(422,'Explicit game and scope required')
        appid=parse_appid(data['appid']);scope=data['scope']
        if scope not in ACCOUNT_SCOPES or (scope=='saves.summary' and appid!=APPID):
            raise HTTPException(422,'This interpretation capability is unavailable')
        if scope=='achievements.read' and data['enabled']=='yes' and not achievements.configured:
            raise HTTPException(503,'Operator achievement access is not configured')
        with store.db() as db:
            if not db.execute('SELECT 1 FROM game_selections WHERE owner=? AND appid=?',(session['owner'],appid)).fetchone():
                raise HTTPException(403,'Select this game first')
            request.state.browser_return='/games?game='+str(appid)+'#permissions'
            if data['enabled']=='yes':
                db.execute('INSERT OR IGNORE INTO grants VALUES(?,?,?)',(session['owner'],appid,scope))
                if scope=='achievements.read':
                    store.expire_achievements(db)
                    if not db.execute('SELECT 1 FROM achievement_cache WHERE owner=? AND appid=?',(session['owner'],appid)).fetchone():
                        if db.execute('SELECT count(*) FROM achievement_cache').fetchone()[0]>=ACHIEVEMENT_ROWS_GLOBAL or db.execute('SELECT count(*) FROM achievement_cache WHERE owner=?',(session['owner'],)).fetchone()[0]>=ACHIEVEMENT_ROWS_PER_OWNER:
                            raise HTTPException(429,'Achievement cache capacity reached; revoke an unused achievement permission')
                    db.execute('INSERT INTO achievement_cache(owner,appid,consent_id) VALUES(?,?,?) ON CONFLICT(owner,appid) DO NOTHING',(session['owner'],appid,secrets.token_urlsafe(32)))
            else:store.revoke_scope(db,session['owner'],appid,scope)
        return RedirectResponse('/games?game='+str(appid)+'#permissions',303)

    async def library_permission(request):
        session=store.session(request,True)
        data=await form(request,session,config.issuer)
        if set(data)!={'csrf','enabled'} or data['enabled'] not in ('yes','no'):raise HTTPException(422,'Explicit library choice required')
        if data['enabled']=='yes' and not libraries.configured:raise HTTPException(503,'Operator library access is not configured')
        with store.db() as db:
            if data['enabled']=='no':db.execute('DELETE FROM library_cache WHERE owner=?',(session['owner'],))
            else:
                for row in db.execute('SELECT owner FROM library_cache WHERE expires<? AND payload IS NOT NULL LIMIT 100',(time.time(),)).fetchall():
                    db.execute("UPDATE library_cache SET payload=NULL,status='expired' WHERE owner=?",(row['owner'],))
                if not db.execute('SELECT 1 FROM library_cache WHERE owner=?',(session['owner'],)).fetchone() and db.execute('SELECT count(*) FROM library_cache').fetchone()[0]>=LIBRARY_ROWS_GLOBAL:raise HTTPException(429,'Library cache capacity reached')
                db.execute('INSERT INTO library_cache(owner,consent_id) VALUES(?,?) ON CONFLICT(owner) DO NOTHING',(session['owner'],secrets.token_urlsafe(32)))
        return RedirectResponse('/games#steam-library',303)

    async def refresh_library(request):
        session=store.session(request,True)
        data=await form(request,session,config.issuer)
        if set(data)!={'csrf'}:raise HTTPException(422,'Only library refresh is accepted')
        if not libraries.configured:raise HTTPException(503,'Operator library access is not configured')
        owner=session['owner']
        store.limit('library-owner:'+digest(owner),4,3600);store.limit('library-global',60,3600)
        if not achievement_slots.acquire(blocking=False):raise HTTPException(429,'Steam reader busy')
        try:
            with store.db() as db:
                row=db.execute('SELECT c.*,u.steamid FROM library_cache c JOIN users u ON u.id=c.owner WHERE c.owner=?',(owner,)).fetchone()
                if not row:raise HTTPException(403,'Explicit library.read permission required')
                now=time.time()
                if row['attempted_at'] is not None and now-row['attempted_at']<900:raise HTTPException(429,'Refresh available after fifteen minutes')
                nonce=secrets.token_urlsafe(32);epoch=row['consent_id'];steamid=row['steamid']
                db.execute('UPDATE library_cache SET refresh_nonce=?,attempted_at=? WHERE owner=?',(nonce,now,owner))
            try:result=await run_in_threadpool(libraries.get_games,steamid)
            except Exception:result={'status':'unavailable','games':[]}
            status=result['status'] if result.get('status') in ('ok','unavailable','not_configured') else 'unavailable'
            payload=json.dumps(result['games'],ensure_ascii=False,separators=(',',':')) if status=='ok' else None
            with store.db() as db:
                if not db.execute('SELECT 1 FROM library_cache WHERE owner=? AND consent_id=? AND refresh_nonce=?',(owner,epoch,nonce)).fetchone():raise HTTPException(409,'Library permission changed during refresh')
                now=time.time()
                db.execute('UPDATE library_cache SET payload=?,status=?,received_at=?,expires=?,refresh_nonce=NULL WHERE owner=?',(payload,status,now,now+86400,owner))
        finally:achievement_slots.release()
        return RedirectResponse('/games#steam-library',303)

    async def refresh_achievements(request):
        session=store.session(request,True)
        data=await form(request,session,config.issuer)
        if set(data)!={'csrf','appid'}:raise HTTPException(422,'Game required')
        appid=parse_appid(data['appid']);owner=session['owner']
        if not achievements.configured:raise HTTPException(503,'Operator achievement access is not configured')
        store.limit('ach-owner:'+digest(owner),12,3600)
        store.limit('ach-global',120,3600)
        if not achievement_slots.acquire(blocking=False):raise HTTPException(429,'Achievement reader busy')
        try:
            with store.db() as db:
                row=db.execute("SELECT c.*,u.steamid FROM achievement_cache c JOIN users u ON u.id=c.owner WHERE c.owner=? AND c.appid=? AND EXISTS(SELECT 1 FROM grants g WHERE g.owner=c.owner AND g.appid=c.appid AND g.scope='achievements.read') AND EXISTS(SELECT 1 FROM game_selections s WHERE s.owner=c.owner AND s.appid=c.appid)",(owner,appid)).fetchone()
                if not row:raise HTTPException(403,'Current selected game and achievement permission required')
                request.state.browser_return='/games?game='+str(appid)+'#achievements'
                store.expire_achievements(db)
                now=time.time()
                if row['attempted_at'] is not None and now-row['attempted_at']<900:raise HTTPException(429,'Refresh available after fifteen minutes')
                nonce=secrets.token_urlsafe(32);epoch=row['consent_id'];steamid=row['steamid']
                db.execute('UPDATE achievement_cache SET refresh_nonce=?,attempted_at=? WHERE owner=? AND appid=?',(nonce,now,owner,appid))
            try:result=await run_in_threadpool(achievements.get_unlocked,steamid,appid)
            except Exception:result={'status':'unavailable','achievements':[]}
            status=result['status'] if result.get('status') in ('ok','unavailable','not_configured') else 'unavailable'
            payload=json.dumps(result['achievements'],ensure_ascii=False,separators=(',',':')) if status=='ok' else None
            with store.db() as db:
                row=db.execute("SELECT 1 FROM achievement_cache c WHERE owner=? AND appid=? AND consent_id=? AND refresh_nonce=? AND EXISTS(SELECT 1 FROM grants g WHERE g.owner=c.owner AND g.appid=c.appid AND g.scope='achievements.read') AND EXISTS(SELECT 1 FROM game_selections s WHERE s.owner=c.owner AND s.appid=c.appid)",(owner,appid,epoch,nonce)).fetchone()
                if not row:raise HTTPException(409,'Achievement permission changed during refresh')
                now=time.time()
                db.execute('UPDATE achievement_cache SET payload=?,status=?,received_at=?,expires=?,refresh_nonce=NULL WHERE owner=? AND appid=?',(payload,status,now,now+86400,owner,appid))
        finally:achievement_slots.release()
        return RedirectResponse('/games?game='+str(appid)+'#achievements',303)

    async def revoke_selected_game(request):
        session=store.session(request,True)
        data=await form(request,session,config.issuer)
        if set(data)!={'csrf','appid'}:raise HTTPException(422,'Game required')
        appid=parse_appid(data['appid'])
        with store.db() as db:
            if appid not in {g['appid'] for g in store.catalog(session['owner'],db)}:
                raise HTTPException(404,'Game unavailable')
            store.revoke_game(db,session['owner'],appid,deselect=True)
        return RedirectResponse('/games',303)

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
                row = db.execute("SELECT payload FROM observations_v2 WHERE owner=? AND appid=? AND kind='save_summary'",(session['owner'],APPID)).fetchone() if enabled else None
                epoch = previous['epoch']+1 if previous else 1
                db.execute('INSERT INTO notification_settings(owner,appid,enabled,baseline,epoch,updated) VALUES(?,?,?,?,?,?) ON CONFLICT(owner,appid) DO UPDATE SET enabled=excluded.enabled,baseline=excluded.baseline,epoch=excluded.epoch,updated=excluded.updated',
                    (session['owner'],APPID,int(enabled),row['payload'] if row else None,epoch,time.time()))
            if not enabled:
                db.execute('DELETE FROM notifications WHERE owner=? AND appid=?',(session['owner'],APPID))
            selected=db.execute('SELECT 1 FROM game_selections WHERE owner=? AND appid=?',(session['owner'],APPID)).fetchone()
        return RedirectResponse('/games?game='+str(APPID)+'#updates' if selected else '/games#library',303)

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
        return RedirectResponse('/games?game='+str(APPID)+'#updates',303)

    async def revoke(request):
        session=store.session(request,True)
        await form(request,session,config.issuer)
        with store.db() as db:
            for table in ('grants','devices','observations','events','notification_settings','notifications','game_selections','observations_v2','achievement_cache','library_cache'):
                db.execute(f'DELETE FROM {table} WHERE owner=?',(session['owner'],))
            db.execute('DELETE FROM pairings WHERE owner=?',(session['owner'],))
            provider.revoke_subject(session['owner'], connection=db)
        return RedirectResponse('/games',303)

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
        data['authorization_response_iss_parameter_supported']=True
        return JSONResponse(data)

    app=mcp.streamable_http_app()
    identify_authorization_errors(app.routes, provider.authorization_issuer)
    app.add_exception_handler(HTTPException,browser_http_exception)
    app.routes.insert(0,Route('/.well-known/oauth-authorization-server',metadata))
    app.routes.extend([Route('/import',manual_import_page),Route('/assets/import.js',import_script),Route('/assets/belmont-parser.js',parser_script),Route('/v1/browser/observations',manual_import,methods=['POST']),Route('/assets/console.css',stylesheet),Route('/setup',setup_page),Route('/downloads/deck-companion.zip',download),Route('/downloads/deck-companion.zip.sha256',download_checksum),Route('/healthz',health),Route('/',home),Route('/games',games),Route('/connect/claude',connect_claude),Route('/login',login),Route('/steam/callback',callback),
        Route('/v1/devices/pair/start',pair_start,methods=['POST']),Route('/v1/devices/pair/poll',pair_poll,methods=['POST']),
        Route('/devices/approve',approve_device,methods=['GET','POST']),Route('/v1/device/observations',ingest,methods=['POST']),
        Route('/oauth/consent',consent,methods=['GET','POST']),Route('/account/library/permission',library_permission,methods=['POST']),Route('/account/library/refresh',refresh_library,methods=['POST']),Route('/account/achievements/refresh',refresh_achievements,methods=['POST']),Route('/account/games/add',add_game,methods=['POST']),Route('/account/games',choose_games,methods=['POST']),Route('/account/games/permissions',game_permission,methods=['POST']),Route('/account/games/revoke',revoke_selected_game,methods=['POST']),Route('/account/notifications',notification_settings,methods=['POST']),Route('/account/notifications/read',notification_read,methods=['POST']),Route('/account/revoke',revoke,methods=['POST']),Route('/logout',logout,methods=['POST'])])
    app.add_middleware(Boundary,config=config,store=store)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=[urlsplit(config.issuer).hostname])
    app.state.store,app.state.provider,app.state.config=store,provider,config
    return app

