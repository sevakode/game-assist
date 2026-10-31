"""Local-only, single-user Game Assist API. No hosted OAuth or Steam login."""
import json
import os
import secrets
import sqlite3
import time
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Path as PathParam, Request
from fastapi.responses import FileResponse, JSONResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, field_validator, model_validator

SCOPES = ('library.read', 'achievements.read', 'saves.metadata', 'recommendations', 'saves.summary')
Scope = Literal['library.read', 'achievements.read', 'saves.metadata', 'recommendations', 'saves.summary']
AppID = Annotated[int, Field(strict=True, gt=0, le=2147483647)]
RouteAppID = Annotated[int, PathParam(gt=0, le=2147483647)]
CAVEAT = 'Save metadata alone cannot prove items, bosses, or map completion. Missing achievements do not prove incomplete game state.'


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Game(StrictModel):
    appid: AppID
    name: str = Field(min_length=1, max_length=200, pattern=r'\S')


class Permissions(StrictModel):
    scopes: list[Scope] = Field(max_length=5)


class AssistanceSettings(StrictModel):
    assistance: Literal['minimal', 'standard', 'guided'] = 'standard'
    neutral_reminders: StrictBool = True


class SaveFile(StrictModel):
    name: str = Field(min_length=1, max_length=4096)

    @field_validator('name')
    @classmethod
    def safe_relative_name(cls, value):
        if any(part in ('', '.', '..') for part in value.split('/')) or any(ord(c) < 32 or ord(c) == 127 for c in value) or '\\' in value or ':' in value:
            raise ValueError('Expected a safe relative metadata name')
        return value
    size: int = Field(strict=True, ge=0)
    sha256: str = Field(pattern=r'^[a-fA-F0-9]{64}$')
    modified_ns: int = Field(strict=True, ge=0)


class SaveMetadata(StrictModel):
    files: list[SaveFile] = Field(max_length=10000)


class Achievement(StrictModel):
    apiname: str = Field(min_length=1, max_length=200)
    name: str | None = Field(default=None, max_length=300)
    achieved: StrictBool
    unlock_time: int | None = Field(default=None, strict=True, ge=0)


class Achievements(StrictModel):
    achievements: list[Achievement] = Field(max_length=10000)


RawInt = Annotated[int, Field(strict=True, ge=0, le=2**53)]
RawFloat = Annotated[float, Field(strict=True, ge=0, le=2**53, allow_inf_nan=False)]


class RawScalar(StrictModel):
    status: Literal['known', 'missing', 'unknown']
    value: RawInt | RawFloat | None

    @field_validator('value', mode='before')
    @classmethod
    def exact_numeric_range(cls, value):
        if value is not None and (type(value) not in (int, float) or not 0 <= value <= 2**53):
            raise ValueError('Invalid raw scalar')
        return value

    @model_validator(mode='after')
    def matching_status(self):
        if (self.status == 'known') != (self.value is not None):
            raise ValueError('Scalar status and value do not match')
        return self


class FragmentScalar(RawScalar):
    value: RawInt | None


class PlayerScalars(StrictModel):
    healthUpgradeFragmentCount: FragmentScalar
    manaUpgradeFragmentCount: FragmentScalar
    currentHealth: RawScalar
    currentMana: RawScalar


class SummaryCoverage(StrictModel):
    player_scalars: Literal['four_raw_fields_only']
    world_structure: Literal['missing', 'validated_structural_only']
    collectible_semantics: Literal['unknown']
    location_mapping: Literal['unknown']


class SaveSummary(StrictModel):
    format_version: Literal['1.1.3']
    player_scalars: PlayerScalars
    semantic_caveats: tuple[
        Literal['Fragment counters are raw values; cumulative versus remainder semantics are unknown.'],
        Literal['currentHealth and currentMana are current values, not maxima.'],
        Literal['No HP/mana pickup classification, collected-state semantics, or location mapping is established.'],
    ]
    decoder_coverage: SummaryCoverage


OBSERVATION_SCOPES = {'save_metadata': 'saves.metadata', 'achievements': 'achievements.read', 'save_summary': 'saves.summary'}
OBSERVATION_MODELS = {'save_metadata': SaveMetadata, 'achievements': Achievements, 'save_summary': SaveSummary}


class Observation(StrictModel):
    steamid: Literal['local'] = 'local'
    appid: AppID
    kind: Literal['save_metadata', 'achievements', 'save_summary']
    payload: dict


class BodySizeLimit:
    """Bound buffered JSON before FastAPI parses it; no reliance on Content-Length."""
    def __init__(self, app, limit=2 * 1024 * 1024):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in ('POST', 'PUT', 'PATCH'):
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            if len(body) + len(chunk) > self.limit:
                return await JSONResponse({'detail': 'Request body exceeds 2 MiB'}, status_code=413)(scope, receive, send)
            body.extend(chunk)
            if not message.get('more_body', False):
                break
        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()
        return await self.app(scope, replay, send)


def create_app(db_path=None, token=None, steam_service=None):
    from server.steam import SteamService, SteamError
    steam = steam_service if steam_service is not None else SteamService()
    pending_logins = {}
    login_generation = [0]
    login_lock = threading.Lock()
    token = token or os.getenv('SGC_TOKEN')
    if not token or len(token) < 32:
        raise RuntimeError('Set SGC_TOKEN to a random secret of at least 32 characters')
    db_path = str(db_path or os.getenv('SGC_DB', 'companion.db'))
    if db_path == ':memory:':
        raise ValueError('Use a temporary SQLite file, not :memory: (connections are isolated)')
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection():
        db = sqlite3.connect(db_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    with connection() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS games (appid INTEGER PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS permissions (appid INTEGER PRIMARY KEY, scopes TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY, steamid TEXT, appid INTEGER, kind TEXT, payload TEXT, observed_at INTEGER);
            CREATE INDEX IF NOT EXISTS observations_game ON observations(appid, id);
        ''')
        if 'source' not in {row['name'] for row in db.execute('PRAGMA table_info(observations)')}:
            db.execute("ALTER TABLE observations ADD COLUMN source TEXT NOT NULL DEFAULT 'local_import'")
        db.execute("CREATE TABLE IF NOT EXISTS game_settings (appid INTEGER PRIMARY KEY, assistance TEXT NOT NULL DEFAULT 'standard')")
        if 'neutral_reminders' not in {row['name'] for row in db.execute('PRAGMA table_info(game_settings)')}:
            db.execute('ALTER TABLE game_settings ADD COLUMN neutral_reminders INTEGER NOT NULL DEFAULT 1')
        # Bound existing history too; newest snapshots remain the evidence source.
        db.execute('DELETE FROM observations WHERE id NOT IN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY appid,kind,source ORDER BY id DESC) AS rank FROM observations) WHERE rank <= 10)')
        db.execute('CREATE TABLE IF NOT EXISTS steam_link (singleton INTEGER PRIMARY KEY CHECK(singleton=1), steamid TEXT NOT NULL)')

    app = FastAPI(title='Game Assist — local beta', version='0.2.0', docs_url=None, redoc_url=None, openapi_url=None)

    app.add_middleware(BodySizeLimit)

    @app.middleware('http')
    async def local_boundary(request: Request, call_next):
        # Prevent DNS rebinding and browser cross-origin requests, even with a token.
        if request.url.hostname not in {'localhost', '127.0.0.1', '::1', 'testserver'}:
            return JSONResponse({'detail': 'Local hosts only'}, status_code=403)
        origin = request.headers.get('origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail': 'Cross-origin requests are not supported'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    def auth(authorization: str | None = Header(default=None)):
        if not authorization or not secrets.compare_digest(authorization.encode(), ('Bearer ' + token).encode()):
            raise HTTPException(401, 'Unauthorized', headers={'WWW-Authenticate': 'Bearer'})

    protected = [Depends(auth)]

    def game_scopes(db, appid):
        row = db.execute('SELECT scopes FROM permissions WHERE appid=?', (appid,)).fetchone()
        return set(json.loads(row['scopes'])) if row else set()

    def require_game(db, appid):
        if not db.execute('SELECT 1 FROM games WHERE appid=?', (appid,)).fetchone():
            raise HTTPException(404, 'Game not registered')

    def require_scope(db, appid, scope):
        if scope not in game_scopes(db, appid):
            raise HTTPException(403, f'Permission required: {scope}')

    def latest(db, appid, kind):
        row = db.execute('SELECT payload,observed_at,source FROM observations WHERE appid=? AND kind=? ORDER BY id DESC LIMIT 1', (appid, kind)).fetchone()
        if row is None:
            return None
        # Ignore incompatible legacy payloads rather than disclosing unchecked data.
        try:
            model = OBSERVATION_MODELS[kind]
            data = model.model_validate_json(row['payload']).model_dump(mode='json')
        except (ValidationError, ValueError):
            return None
        # All outward-facing consumers share this strict view. Raw snapshots
        # stay local; neither permission grants nor assistance weaken spoilers.
        if kind == 'achievements':
            data = {'achievements': [{'name': item['name'] or 'Unlocked achievement', 'achieved': True, 'unlock_time': item['unlock_time']} for item in data['achievements'] if item['achieved'] is True]}
        elif kind == 'save_metadata':
            files = data['files']
            data = {'file_count': len(files), 'total_bytes': sum(item['size'] for item in files), 'last_modified_ns': max((item['modified_ns'] for item in files), default=None)}
        return {'data': data, 'spoiler_policy': 'strict', 'observed_at': row['observed_at'], 'source': row['source'], 'verification': 'steam_api_reported' if row['source'] == 'steam_web_api' else 'reported_not_independently_verified'}

    def list_games(db):
        return {'games': [{'appid': r['appid'], 'name': r['name'], 'scopes': sorted(game_scopes(db, r['appid']))} for r in db.execute('SELECT * FROM games ORDER BY name,appid') if 'library.read' in game_scopes(db, r['appid'])]}

    def evidence(db, appid, kind):
        require_scope(db, appid, OBSERVATION_SCOPES[kind])
        record = latest(db, appid, kind)
        return {'appid': appid, 'status': 'available' if record else 'unknown', 'observation': record, 'caveat': CAVEAT}

    def progress(db, appid):
        scopes = game_scopes(db, appid)
        if not scopes.intersection(set(OBSERVATION_SCOPES.values())):
            raise HTTPException(403, 'Permission required: achievements.read, saves.metadata or saves.summary')
        observations, coverage = {}, {}
        for kind, scope in [('achievements', 'achievements.read'), ('save_metadata', 'saves.metadata'), ('save_summary', 'saves.summary')]:
            record = latest(db, appid, kind) if scope in scopes else None
            coverage[kind] = 'not_permitted' if scope not in scopes else ('available' if record else 'unknown')
            if record:
                observations[kind] = record
        return {'appid': appid, 'observations': observations, 'coverage': coverage, 'game_completion': 'unknown', 'settings': settings_for(db, appid), 'caveat': CAVEAT}

    @app.get('/health')
    def health():
        return {'status': 'ok', 'mode': 'local-only'}

    @app.get('/v1/games', dependencies=protected)
    def games():
        with connection() as db:
            return list_games(db)

    @app.post('/v1/games', dependencies=protected)
    def register_game(data: Game):
        with connection() as db:
            db.execute('INSERT INTO games(appid,name) VALUES (?,?) ON CONFLICT(appid) DO UPDATE SET name=excluded.name', (data.appid, data.name))
            return {**data.model_dump(), 'scopes': sorted(game_scopes(db, data.appid))}

    def settings_for(db, appid):
        row = db.execute('SELECT assistance,neutral_reminders FROM game_settings WHERE appid=?', (appid,)).fetchone()
        return {'assistance': row['assistance'] if row else 'standard', 'spoiler_policy': 'strict', 'neutral_reminders': bool(row['neutral_reminders']) if row else True}

    @app.get('/v1/games/{appid}/settings', dependencies=protected)
    def get_settings(appid: RouteAppID):
        with connection() as db:
            require_game(db, appid)
            return settings_for(db, appid)

    @app.put('/v1/games/{appid}/settings', dependencies=protected)
    def set_settings(appid: RouteAppID, data: AssistanceSettings):
        with connection() as db:
            require_game(db, appid)
            reminders = settings_for(db, appid)['neutral_reminders'] if 'neutral_reminders' not in data.model_fields_set else data.neutral_reminders
            db.execute('INSERT INTO game_settings(appid,assistance,neutral_reminders) VALUES (?,?,?) ON CONFLICT(appid) DO UPDATE SET assistance=excluded.assistance,neutral_reminders=excluded.neutral_reminders', (appid, data.assistance, int(reminders)))
            return settings_for(db, appid)

    @app.get('/v1/games/{appid}/permissions', dependencies=protected)
    def permissions(appid: RouteAppID):
        with connection() as db:
            require_game(db, appid)
            return {'appid': appid, 'scopes': sorted(game_scopes(db, appid)), 'available_scopes': SCOPES}

    @app.put('/v1/games/{appid}/permissions', dependencies=protected)
    def set_permissions(appid: RouteAppID, data: Permissions):
        with connection() as db:
            require_game(db, appid)
            scopes = sorted(set(data.scopes))
            db.execute('INSERT INTO permissions VALUES (?,?) ON CONFLICT(appid) DO UPDATE SET scopes=excluded.scopes', (appid, json.dumps(scopes)))
            return {'appid': appid, 'scopes': scopes}

    def store_observation(db, steamid, appid, kind, payload, source='local_import'):
        serialized = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        previous = db.execute('SELECT payload FROM observations WHERE appid=? AND kind=? AND source=? ORDER BY id DESC LIMIT 1', (appid, kind, source)).fetchone()
        try:
            duplicate = previous and json.loads(previous['payload']) == payload
        except (TypeError, ValueError):
            duplicate = False
        if duplicate:
            return  # Do not turn an unchanged snapshot into false fresh evidence.
        db.execute('INSERT INTO observations(steamid,appid,kind,payload,observed_at,source) VALUES (?,?,?,?,?,?)', (steamid, appid, kind, serialized, int(time.time()), source))
        db.execute('DELETE FROM observations WHERE appid=? AND kind=? AND source=? AND id NOT IN (SELECT id FROM observations WHERE appid=? AND kind=? AND source=? ORDER BY id DESC LIMIT 10)', (appid, kind, source, appid, kind, source))

    @app.post('/v1/observations', dependencies=protected)
    def ingest(data: Observation):
        model = OBSERVATION_MODELS[data.kind]
        if data.kind == 'save_summary' and data.appid != 4231820:
            raise HTTPException(422, 'Structural summary is supported only for AppID 4231820')
        try:
            payload = model.model_validate(data.payload).model_dump(mode='json')
        except ValidationError as exc:
            raise HTTPException(422, 'Invalid observation payload') from exc
        with connection() as db:
            require_game(db, data.appid)
            require_scope(db, data.appid, OBSERVATION_SCOPES[data.kind])
            db.execute('BEGIN IMMEDIATE')
            require_scope(db, data.appid, OBSERVATION_SCOPES[data.kind])
            store_observation(db, 'local', data.appid, data.kind, payload, 'local_reported_parser' if data.kind == 'save_summary' else 'local_import')
        return {'ok': True}

    @app.get('/v1/games/{appid}/progress', dependencies=protected)
    def get_progress(appid: RouteAppID):
        with connection() as db:
            return progress(db, appid)

    @app.get('/v1/games/{appid}/achievements', dependencies=protected)
    def get_achievements(appid: RouteAppID):
        with connection() as db:
            return evidence(db, appid, 'achievements')

    @app.get('/v1/games/{appid}/save-status', dependencies=protected)
    def get_save_status(appid: RouteAppID):
        with connection() as db:
            return evidence(db, appid, 'save_metadata')

    @app.get('/v1/games/{appid}/save-summary', dependencies=protected)
    def get_save_summary(appid: RouteAppID):
        with connection() as db:
            return evidence(db, appid, 'save_summary')

    @app.delete('/v1/games/{appid}/data', dependencies=protected)
    def delete_data(appid: RouteAppID):
        with connection() as db:
            require_game(db, appid)
            cursor = db.execute('DELETE FROM observations WHERE appid=?', (appid,))
            return {'ok': True, 'deleted': cursor.rowcount}

    @app.get('/v1/export', dependencies=protected)
    def export():
        with connection() as db:
            result = []
            for game in db.execute('SELECT * FROM games ORDER BY appid'):
                scopes = game_scopes(db, game['appid'])
                if not scopes:
                    continue
                item = {'appid': game['appid'], 'scopes': sorted(scopes), 'observations': {}}
                if 'library.read' in scopes:
                    item['name'] = game['name']
                for kind, scope in [('achievements', 'achievements.read'), ('save_metadata', 'saves.metadata'), ('save_summary', 'saves.summary')]:
                    if scope in scopes and (record := latest(db, game['appid'], kind)):
                        item['observations'][kind] = record
                result.append(item)
            return {'format_version': 1, 'games': result, 'spoiler_policy': 'strict', 'note': 'Latest snapshots only; only currently permitted spoiler-filtered data is exported. Locked achievements and save filenames are omitted.'}

    def linked_id(db):
        row = db.execute('SELECT steamid FROM steam_link WHERE singleton=1').fetchone()
        return row['steamid'] if row else None

    @app.get('/v1/steam/status', dependencies=protected)
    def steam_status():
        with connection() as db:
            steamid = linked_id(db)
        return {'linked': steamid is not None, 'steamid': steamid, 'api_configured': steam.configured, 'mode': 'local-only'}

    @app.post('/v1/steam/login', dependencies=protected)
    def steam_login(request: Request):
        state, binding = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        base = str(request.base_url).rstrip('/')
        return_to = base + '/v1/steam/callback?state=' + state
        with login_lock:
            now = time.time()
            for key in list(pending_logins):
                if pending_logins[key]['expires'] < now:
                    del pending_logins[key]
            if len(pending_logins) >= 20:
                raise HTTPException(429, 'Too many pending login requests')
            pending_logins[state] = {'binding': binding, 'expires': now + 300, 'return_to': return_to, 'generation': login_generation[0]}
        response = JSONResponse({'authorize_url': steam.login_url(return_to), 'expires_in': 300})
        response.set_cookie('sgc_steam_state', binding, max_age=300, httponly=True, samesite='lax', secure=request.url.scheme == 'https', path='/v1/steam/callback')
        return response

    @app.get('/v1/steam/callback')
    def steam_callback(request: Request):
        states = request.query_params.getlist('state')
        if len(states) != 1:
            raise HTTPException(400, 'Invalid Steam login state')
        state = states[0]
        with login_lock:
            pending = pending_logins.pop(state, None)
        binding = request.cookies.get('sgc_steam_state', '')
        if not pending or pending['expires'] < time.time() or not secrets.compare_digest(binding, pending['binding']):
            raise HTTPException(400, 'Expired or invalid Steam login state; start again')
        if request.query_params.get('openid.mode') == 'cancel':
            response = RedirectResponse('/?steam=canceled', status_code=303)
        else:
            try:
                steamid = steam.verify_callback(request.query_params, pending['return_to'])
            except SteamError as exc:
                raise HTTPException(400, exc.code) from None
            with login_lock:
                if pending['generation'] != login_generation[0]:
                    raise HTTPException(400, 'Steam login canceled; start again')
                with connection() as db:
                    # Switching Steam identity cannot retain another user's achievements.
                    if linked_id(db) != steamid:
                        db.execute("DELETE FROM observations WHERE source='steam_web_api'")
                    db.execute('INSERT INTO steam_link VALUES (1,?) ON CONFLICT(singleton) DO UPDATE SET steamid=excluded.steamid', (steamid,))
            response = RedirectResponse('/?steam=linked', status_code=303)
        response.delete_cookie('sgc_steam_state', path='/v1/steam/callback')
        return response

    @app.post('/v1/steam/unlink', dependencies=protected)
    def steam_unlink():
        with login_lock:
            pending_logins.clear()
            login_generation[0] += 1
            with connection() as db:
                db.execute('DELETE FROM steam_link')
                db.execute("DELETE FROM observations WHERE source='steam_web_api'")
        return {'ok': True}

    @app.post('/v1/games/{appid}/steam-sync', dependencies=protected)
    def steam_sync(appid: RouteAppID):
        with connection() as db:
            require_scope(db, appid, 'achievements.read')
            steamid = linked_id(db)
            if not steamid:
                raise HTTPException(409, 'Link Steam before syncing')
        result = steam.get_achievements(steamid, appid)
        if result['status'] != 'ok':
            return result
        try:
            payload = Achievements.model_validate({'achievements': result['achievements']}).model_dump()
        except ValidationError:
            raise HTTPException(502, 'Steam returned invalid achievement data') from None
        with connection() as db:
            # Acquire a write transaction before rechecking consent and association.
            db.execute('BEGIN IMMEDIATE')
            require_scope(db, appid, 'achievements.read')
            if linked_id(db) != steamid:
                raise HTTPException(409, 'Steam link changed during sync')
            store_observation(db, steamid, appid, 'achievements', payload, 'steam_web_api')
        return {'ok': True, 'status': 'ok', 'unlocked_count': sum(item['achieved'] for item in payload['achievements']), 'source': 'steam_web_api'}

    tool_names = ['list_games', 'get_achievements', 'get_save_status', 'get_save_summary', 'get_progress', 'suggest_next_step']
    tool_descriptions = ['List explicitly approved games.', 'Read only already-unlocked achievements; locked rows and internal identifiers are omitted.', 'Read safe save metadata aggregates, never filenames, contents or game-state claims.', 'Read four reported raw scalars from the version-gated structural parser. No maxima, pickup mapping or collected-state semantics.', 'Read permission-filtered evidence; game completion may remain unknown.', 'Suggest a safe evidence-gathering next step; no invented game route.']

    @app.get('/mcp', dependencies=protected)
    def mcp_no_sse():
        raise HTTPException(405, 'SSE is not implemented by this local JSON-only transport', headers={'Allow': 'POST'})

    @app.post('/mcp', dependencies=protected)
    async def mcp(request: Request):
        if request.headers.get('mcp-protocol-version', '2025-03-26') != '2025-03-26':
            raise HTTPException(400, 'Unsupported MCP protocol version; supported: 2025-03-26')
        def error(code, message, request_id=None):
            return JSONResponse({'jsonrpc': '2.0', 'id': request_id, 'error': {'code': code, 'message': message}})
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            return error(-32700, 'Parse error')
        if not isinstance(body, dict) or body.get('jsonrpc') != '2.0' or not isinstance(body.get('method'), str):
            return error(-32600, 'Invalid Request')
        request_id = body.get('id')
        if isinstance(request_id, (dict, list, bool)) or isinstance(request_id, float):
            return error(-32600, 'Invalid Request')
        params = body.get('params', {})
        if not isinstance(params, dict):
            return error(-32602, 'Invalid params', request_id)
        method = body['method']
        if 'id' not in body:
            return Response(status_code=202)
        if method == 'initialize':
            result = {'protocolVersion': '2025-03-26', 'capabilities': {'tools': {'listChanged': False}}, 'serverInfo': {'name': 'game-assist-local', 'version': '0.2.0'}, 'instructions': 'Local stateless JSON-only Streamable HTTP subset. Not a hosted ChatGPT connector; no OAuth, SSE or remote transport.'}
        elif method == 'ping':
            result = {}
        elif method == 'tools/list':
            result = {'tools': [{'name': name, 'description': description, 'inputSchema': {'type': 'object', 'properties': {} if name == 'list_games' else {'appid': {'type': 'integer', 'minimum': 1, 'maximum': 2147483647}}, 'required': [] if name == 'list_games' else ['appid'], 'additionalProperties': False}, 'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False}} for name, description in zip(tool_names, tool_descriptions)]}
        elif method == 'tools/call':
            name, args = params.get('name'), params.get('arguments', {})
            if name not in tool_names or not isinstance(args, dict):
                return error(-32602, 'Unknown tool or invalid arguments', request_id)
            if (name == 'list_games' and args) or (name != 'list_games' and (set(args) != {'appid'} or type(args['appid']) is not int or not 1 <= args['appid'] <= 2147483647)):
                return error(-32602, 'Invalid tool arguments', request_id)
            try:
                with connection() as db:
                    if name == 'list_games':
                        data = list_games(db)
                    elif name == 'get_achievements':
                        data = evidence(db, args['appid'], 'achievements')
                    elif name == 'get_save_status':
                        data = evidence(db, args['appid'], 'save_metadata')
                    elif name == 'get_save_summary':
                        data = evidence(db, args['appid'], 'save_summary')
                    else:
                        if name == 'suggest_next_step':
                            require_scope(db, args['appid'], 'recommendations')
                        data = progress(db, args['appid'])
                        if name == 'suggest_next_step':
                            assistance = settings_for(db, args['appid'])['assistance']
                            prompts = {'minimal': 'What is your current goal? I can offer a small spoiler-free hint based on what you already know.', 'standard': 'Tell me your current goal and what you have already discovered. We can review preparation without revealing upcoming content.', 'guided': 'Share your current goal, known equipment and where you are stuck. We can work through a spoiler-free preparation checklist using only your confirmed discoveries; no game-specific rules are verified yet.'}
                            data['neutral_reminder'] = {'enabled': settings_for(db, args['appid'])['neutral_reminders'], 'status': 'no_verified_trigger', 'text': None}
                            data['suggestion'] = {'text': prompts[assistance], 'assistance': assistance, 'confidence': 'unknown', 'spoilers': 'none', 'provenance': 'Only the permitted local observations shown here; no external guide.'}
                result = {'content': [{'type': 'text', 'text': json.dumps(data)}], 'isError': False}
            except HTTPException as exc:
                result = {'content': [{'type': 'text', 'text': exc.detail}], 'isError': True}
        else:
            return error(-32601, 'Method not found', request_id)
        return {'jsonrpc': '2.0', 'id': request_id, 'result': result}

    web = Path(__file__).resolve().parent.parent / 'web'
    if web.is_dir():
        app.mount('/static', StaticFiles(directory=web), name='static')
        app.mount('/web', StaticFiles(directory=web), name='web')

        @app.get('/')
        def index():
            return FileResponse(web / 'index.html')
    return app


def __getattr__(name):
    # Keep factory import usable in tests without a global secret or database.
    if name == 'app':
        instance = create_app()
        globals()['app'] = instance
        return instance
    raise AttributeError(name)
