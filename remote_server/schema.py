"""Version-one durable schema. PostgreSQL epoch timestamps are float64, not REAL."""
SQLITE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, steamid TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, owner TEXT, csrf TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS login_states(hash TEXT PRIMARY KEY, session_hash TEXT NOT NULL, return_to TEXT NOT NULL, expires REAL NOT NULL, next_path TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS grants(owner TEXT NOT NULL, appid INTEGER NOT NULL, scope TEXT NOT NULL, PRIMARY KEY(owner,appid,scope));
CREATE TABLE IF NOT EXISTS pairings(hash TEXT PRIMARY KEY,user_hash TEXT UNIQUE,expires REAL NOT NULL,last_poll REAL NOT NULL DEFAULT 0,owner TEXT,scopes TEXT,consumed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS devices(hash TEXT PRIMARY KEY,owner TEXT NOT NULL,appid INTEGER NOT NULL,scopes TEXT NOT NULL,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS observations(owner TEXT NOT NULL,appid INTEGER NOT NULL,payload TEXT NOT NULL,observed REAL NOT NULL,PRIMARY KEY(owner,appid));
CREATE TABLE IF NOT EXISTS events(owner TEXT NOT NULL,device_hash TEXT NOT NULL,event_id TEXT NOT NULL,created REAL NOT NULL,payload_hash TEXT NOT NULL,PRIMARY KEY(device_hash,event_id));
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
