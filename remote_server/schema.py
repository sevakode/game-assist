"""Version-one durable schema. PostgreSQL epoch timestamps are float64, not REAL."""
SQLITE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, steamid TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, owner TEXT, csrf TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS login_states(hash TEXT PRIMARY KEY, session_hash TEXT NOT NULL, return_to TEXT NOT NULL, expires REAL NOT NULL, next_path TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schema_migrations(name TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS game_registrations(owner TEXT NOT NULL,appid INTEGER NOT NULL,label TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(owner,appid));
CREATE TABLE IF NOT EXISTS game_selections(owner TEXT NOT NULL,appid INTEGER NOT NULL,selected_at REAL NOT NULL,PRIMARY KEY(owner,appid));
CREATE TABLE IF NOT EXISTS grants(owner TEXT NOT NULL, appid INTEGER NOT NULL, scope TEXT NOT NULL, PRIMARY KEY(owner,appid,scope));
CREATE TABLE IF NOT EXISTS pairings(hash TEXT PRIMARY KEY,user_hash TEXT UNIQUE,expires REAL NOT NULL,last_poll REAL NOT NULL DEFAULT 0,owner TEXT,scopes TEXT,consumed INTEGER NOT NULL DEFAULT 0,appid INTEGER NOT NULL DEFAULT 4231820,requested_scopes TEXT NOT NULL DEFAULT '["saves.summary"]');
CREATE TABLE IF NOT EXISTS devices(hash TEXT PRIMARY KEY,owner TEXT NOT NULL,appid INTEGER NOT NULL,scopes TEXT NOT NULL,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS observations_v2(owner TEXT NOT NULL,appid INTEGER NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,observed REAL NOT NULL,PRIMARY KEY(owner,appid,kind));
CREATE TABLE IF NOT EXISTS observations(owner TEXT NOT NULL,appid INTEGER NOT NULL,payload TEXT NOT NULL,observed REAL NOT NULL,PRIMARY KEY(owner,appid));
CREATE TABLE IF NOT EXISTS events(owner TEXT NOT NULL,device_hash TEXT NOT NULL,event_id TEXT NOT NULL,created REAL NOT NULL,payload_hash TEXT NOT NULL,appid INTEGER NOT NULL DEFAULT 4231820,kind TEXT NOT NULL DEFAULT 'save_summary',PRIMARY KEY(device_hash,event_id));
CREATE TABLE IF NOT EXISTS limits(bucket TEXT PRIMARY KEY,start REAL NOT NULL,count INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS steam_nonces(nonce_hash TEXT PRIMARY KEY,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS notification_settings(owner TEXT NOT NULL,appid INTEGER NOT NULL,enabled INTEGER NOT NULL,baseline TEXT,epoch INTEGER NOT NULL,updated REAL NOT NULL,PRIMARY KEY(owner,appid));
CREATE TABLE IF NOT EXISTS notifications(id TEXT PRIMARY KEY,owner TEXT NOT NULL,appid INTEGER NOT NULL,event_key TEXT NOT NULL,created REAL NOT NULL,read_at REAL,UNIQUE(owner,appid,event_key));
CREATE INDEX IF NOT EXISTS notifications_owner_created ON notifications(owner,created);
CREATE INDEX IF NOT EXISTS notifications_expiry ON notifications(created);
CREATE TABLE IF NOT EXISTS oauth_clients(id TEXT PRIMARY KEY,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS oauth_pending(id TEXT PRIMARY KEY,data TEXT NOT NULL,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS oauth_codes(hash TEXT PRIMARY KEY,data TEXT NOT NULL,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS oauth_tokens(hash TEXT PRIMARY KEY,kind TEXT NOT NULL,family TEXT NOT NULL,data TEXT NOT NULL,expires REAL NOT NULL,revoked INTEGER NOT NULL DEFAULT 0);
INSERT INTO game_selections(owner,appid,selected_at) SELECT owner,appid,0 FROM grants WHERE appid=4231820 AND scope='saves.summary' ON CONFLICT(owner,appid) DO NOTHING;
CREATE INDEX IF NOT EXISTS oauth_token_family ON oauth_tokens(family);
CREATE INDEX IF NOT EXISTS oauth_token_expiry ON oauth_tokens(expires);
CREATE INDEX IF NOT EXISTS oauth_token_subject ON oauth_tokens(json_extract(data,'$.subject'));
CREATE INDEX IF NOT EXISTS oauth_code_expiry ON oauth_codes(expires);
CREATE INDEX IF NOT EXISTS oauth_code_subject ON oauth_codes(json_extract(data,'$.subject'));
CREATE INDEX IF NOT EXISTS events_expiry ON events(created);
CREATE INDEX IF NOT EXISTS devices_owner ON devices(owner);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires);
CREATE INDEX IF NOT EXISTS steam_nonce_expiry ON steam_nonces(expires);
'''

# These substitutions apply only to our fixed schema, never external SQL.
POSTGRES_SCHEMA = SQLITE_SCHEMA.replace(' REAL', ' DOUBLE PRECISION').replace(
    "json_extract(data,'$.subject')", "(data::jsonb->>'subject')")

SCHEMA = {'sqlite': SQLITE_SCHEMA, 'postgres': POSTGRES_SCHEMA}


# Identifiers and definitions are constants, never supplied by requests/DSNs.
_ADDITIVE_COLUMNS = {
    'pairings': {
        'appid': 'INTEGER NOT NULL DEFAULT 4231820',
        'requested_scopes': "TEXT NOT NULL DEFAULT '[\"saves.summary\"]'",
    },
    'events': {
        'appid': 'INTEGER NOT NULL DEFAULT 4231820',
        'kind': "TEXT NOT NULL DEFAULT 'save_summary'",
    },
}


def migrate(connection, backend):
    """One atomic, restart-safe upgrade from the original Belmont-only schema.

    Called within the existing serialized transaction after CREATE IF NOT EXISTS.
    Old observations remain as legacy rows; only granted summaries are copied.
    The application must clear both old and new scoped rows when access is revoked.
    """
    import json
    for table, columns in _ADDITIVE_COLUMNS.items():
        if backend == 'sqlite':
            present = {row['name'] for row in connection.execute(f'PRAGMA table_info({table})').fetchall()}
        elif backend == 'postgres':
            present = {row['column_name'] for row in connection.execute(
                'SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=?',
                (table,)).fetchall()}
        else:
            raise ValueError('Unsupported migration backend')
        for name, definition in columns.items():
            if name not in present:
                connection.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
    name = 'universal_metadata_v1'
    if connection.execute('SELECT 1 FROM schema_migrations WHERE name=?',(name,)).fetchone():
        return
    # Old saves.metadata was explicitly unavailable. Do not turn those historical
    # no-op choices into real metadata-sharing consent during a software upgrade.
    connection.execute("DELETE FROM grants WHERE scope='saves.metadata'")
    for table, identity in (('devices','hash'),('pairings','hash')):
        for row in connection.execute(f'SELECT {identity},scopes FROM {table}').fetchall():
            if row['scopes'] is None:
                continue
            try:
                scopes = json.loads(row['scopes'])
            except (ValueError,TypeError):
                connection.execute(f'DELETE FROM {table} WHERE {identity}=?',(row[identity],))
                continue
            if not isinstance(scopes,list):
                connection.execute(f'DELETE FROM {table} WHERE {identity}=?',(row[identity],))
                continue
            if 'saves.metadata' not in scopes:
                continue
            remaining = [scope for scope in scopes if scope == 'saves.summary']
            if remaining:
                connection.execute(f'UPDATE {table} SET scopes=? WHERE {identity}=?',(json.dumps(remaining),row[identity]))
            else:
                connection.execute(f'DELETE FROM {table} WHERE {identity}=?',(row[identity],))
    connection.execute("""INSERT INTO observations_v2(owner,appid,kind,payload,observed)
        SELECT o.owner,o.appid,'save_summary',o.payload,o.observed FROM observations o
        WHERE o.appid=4231820 AND EXISTS(SELECT 1 FROM grants g
            WHERE g.owner=o.owner AND g.appid=o.appid AND g.scope='saves.summary')
        ON CONFLICT(owner,appid,kind) DO NOTHING""")
    connection.execute('INSERT INTO schema_migrations(name) VALUES(?)',(name,))
