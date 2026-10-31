"""Small explicit SQLite/PostgreSQL boundary, with no fallback between backends.

All SQL originates in this application. The narrow dialect conversion is not a
SQL parser for external input. A transaction-scoped PostgreSQL advisory lock
preserves the prototype's SQLite BEGIN IMMEDIATE serialization across processes
and transaction-pooled connections. It intentionally limits throughput.
"""
import os
import logging
import re
import time
from pathlib import Path
import sqlite3
import threading
from urllib.parse import parse_qsl, urlsplit

from .schema import SCHEMA, migrate

# Bound simultaneous connections even without a pool dependency. PostgreSQL
# connections close at transaction exit; no session locks survive pool handoff.
_CONNECTION_SLOTS = threading.BoundedSemaphore(8)
_ADVISORY_LOCK_ID = 0x47414D4541535354


_LOG = logging.getLogger(__name__)
_FAILURE_CATEGORIES = frozenset({'TLS_ROOTS', 'TLS_VERIFY', 'TLS_ISSUER', 'TLS_SELF_SIGNED', 'TLS_EXPIRED', 'TLS_HOSTNAME', 'TLS_PROTOCOL', 'TLS_HANDSHAKE', 'TLS_OTHER', 'AUTH', 'CHANNEL_BINDING', 'DNS', 'TIMEOUT', 'NETWORK', 'OTHER'})
_TRANSIENT_CATEGORIES = frozenset({'DNS', 'TIMEOUT', 'NETWORK'})


class ConnectionUnavailable(RuntimeError):
    """Only constant classification survives; raw driver exception is not retained."""
    def __init__(self, category):
        self.category = category if category in _FAILURE_CATEGORIES else 'OTHER'
        super().__init__('PostgreSQL connection unavailable')


def connection_failure_category(error):
    """Best-effort local inspection. NEVER emit exception text or connection data."""
    message = str(error).lower()[:16384]
    state = getattr(error, 'sqlstate', None)
    state = state if isinstance(state, str) and re.fullmatch(r'[0-9A-Z]{5}', state) else ''
    if any(term in message for term in ('channel binding', 'invalid channel_binding', 'channel_binding must')):
        return 'CHANNEL_BINDING'
    if any(term in message for term in ('root certificate file', 'sslrootcert', 'load root certificate', 'system root certificates', 'default certificate paths', 'no certificate or crl found')):
        return 'TLS_ROOTS'
    if any(term in message for term in ('does not match host name', 'hostname mismatch', 'host name mismatch', 'certificate is not valid for')):
        return 'TLS_HOSTNAME'
    if any(term in message for term in ('certificate has expired', 'certificate expired', 'certificate is not yet valid', 'certificate not yet valid')):
        return 'TLS_EXPIRED'
    if any(term in message for term in ('self-signed certificate', 'self signed certificate')):
        return 'TLS_SELF_SIGNED'
    if any(term in message for term in ('unable to get local issuer certificate', 'unable to get issuer certificate', 'unable to verify the first certificate', 'unknown ca', 'unknown certificate authority')):
        return 'TLS_ISSUER'
    if any(term in message for term in ('certificate verify failed', 'certificate verification failed')):
        return 'TLS_VERIFY'
    if any(term in message for term in ('wrong version number', 'unsupported protocol', 'alert protocol version', 'no protocols available')):
        return 'TLS_PROTOCOL'
    if any(term in message for term in ('alert handshake failure', 'handshake failure', 'handshake failed')):
        return 'TLS_HANDSHAKE'
    if any(term in message for term in ('ssl error', 'tls error', 'ssl syscall error')):
        return 'TLS_OTHER'
    if state.startswith('28') or any(term in message for term in ('password authentication failed', 'authentication failed', 'no pg_hba.conf entry', 'no password supplied', 'invalid password')):
        return 'AUTH'
    if any(term in message for term in ('could not translate host name', 'name or service not known', 'temporary failure in name resolution', 'nodename nor servname', 'getaddrinfo failed')):
        return 'DNS'
    if isinstance(error, TimeoutError) or any(term in message for term in ('timeout expired', 'connection timed out', 'connect timeout', 'connection timeout')):
        return 'TIMEOUT'
    if state.startswith('08') or any(term in message for term in ('connection refused', 'network is unreachable', 'no route to host', 'connection reset', 'server closed the connection unexpectedly')):
        return 'NETWORK'
    return 'OTHER'


class Row(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def _row(self, value):
        if value is None:
            return None
        names = [column[0] for column in self.cursor.description]
        return Row(zip(names, value))

    def fetchone(self):
        return self._row(self.cursor.fetchone())

    def fetchall(self):
        return [self._row(row) for row in self.cursor.fetchall()]

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def __iter__(self):
        while (row := self.fetchone()) is not None:
            yield row


def _postgres_sql(query):
    """Translate only known application dialect differences; bind values separately."""
    query = query.replace("json_extract(data,'$.subject')", "(data::jsonb->>'subject')")
    query = query.replace('kind="refresh"', "kind='refresh'")
    stripped = query.strip()
    if stripped.startswith('INSERT OR IGNORE INTO grants '):
        query = query.replace('INSERT OR IGNORE INTO grants ', 'INSERT INTO grants ', 1).rstrip().rstrip(';') + ' ON CONFLICT(owner,appid,scope) DO NOTHING'
    elif stripped.startswith('INSERT OR REPLACE INTO limits '):
        query = query.replace('INSERT OR REPLACE INTO limits ', 'INSERT INTO limits ', 1).rstrip().rstrip(';') + ' ON CONFLICT(bucket) DO UPDATE SET start=EXCLUDED.start,count=EXCLUDED.count'
    elif stripped.startswith('INSERT OR REPLACE INTO observations '):
        query = query.replace('INSERT OR REPLACE INTO observations ', 'INSERT INTO observations ', 1).rstrip().rstrip(';') + ' ON CONFLICT(owner,appid) DO UPDATE SET payload=EXCLUDED.payload,observed=EXCLUDED.observed'
    elif 'INSERT OR ' in query:
        raise ValueError('Unsupported application SQL dialect')
    # No current application statement contains a question mark inside a literal.
    # Refuse it rather than accidentally interpreting it as a parameter.
    quoted = False
    result = []
    index = 0
    while index < len(query):
        char = query[index]
        if char == "'":
            if quoted and index + 1 < len(query) and query[index + 1] == "'":
                result.extend([char, char]); index += 2; continue
            quoted = not quoted
        if char == '?':
            if quoted:
                raise ValueError('Question marks in SQL literals are unsupported')
            result.append('%s')
        else:
            result.append(char)
        index += 1
    return ''.join(result)


class Connection:
    def __init__(self, raw, backend):
        self.raw = raw
        self.backend = backend

    def execute(self, query, params=()):
        statement = _postgres_sql(query) if self.backend == 'postgres' else query
        return Cursor(self.raw.execute(statement, params))

    def executescript(self, script):
        # Schema scripts contain no procedural bodies or semicolons in literals.
        # Execute individually so SQLite executescript cannot implicitly COMMIT
        # and escape the transaction boundary.
        for statement in script.split(';'):
            if statement.strip():
                self.execute(statement.strip())


class Transaction:
    def __init__(self, database):
        self.database = database
        self.raw = None
        self.slot = False

    def __enter__(self):
        if not _CONNECTION_SLOTS.acquire(timeout=10):
            raise TimeoutError('Database connection capacity reached')
        self.slot = True
        try:
            if self.database.backend == 'sqlite':
                self.raw = sqlite3.connect(self.database.path, timeout=10)
                self.raw.execute('BEGIN IMMEDIATE')
            else:
                import psycopg
                kwargs = {'connect_timeout': 5, 'client_encoding': 'UTF8'}
                if not self.database.allow_insecure_test:
                    kwargs['sslmode'] = 'verify-full'
                    if self.database.options.get('sslrootcert') in (None, 'system'):
                        # Pinned certifi supplies Mozilla's public trust roots.
                        # An explicit CA file avoids bundled OpenSSL build-path
                        # ambiguity; hostname verification remains mandatory.
                        import certifi
                        roots = certifi.where()
                        if not Path(roots).is_file():
                            raise ConnectionUnavailable('TLS_ROOTS')
                        kwargs['sslrootcert'] = roots
                failure_category = None
                try:
                    self.raw = psycopg.connect(self.database.database_url, **kwargs)
                except psycopg.Error as error:
                    failure_category = connection_failure_category(error)
                # Raise after leaving the driver exception handler: even the
                # suppressed __context__ must not retain credential-bearing text.
                if failure_category is not None:
                    raise ConnectionUnavailable(failure_category) from None
                # Transaction-local settings work with transaction poolers; startup
                # options and session state must not be required for correctness.
                self.raw.execute('SET LOCAL statement_timeout = 10000')
                self.raw.execute('SET LOCAL lock_timeout = 10000')
                self.raw.execute('SET LOCAL idle_in_transaction_session_timeout = 30000')
                self.raw.execute('SELECT pg_advisory_xact_lock(%s)', (_ADVISORY_LOCK_ID,))
            return Connection(self.raw, self.database.backend)
        except BaseException:
            if self.raw is not None:
                self.raw.close()
            _CONNECTION_SLOTS.release()
            self.slot = False
            raise

    def __exit__(self, exc_type, exc, traceback):
        # Class context manager: do not write __traceback__ on the official SDK's
        # frozen dataclass errors, as contextlib.generator-based managers do.
        try:
            if exc_type:
                self.raw.rollback()
            else:
                self.raw.commit()
        finally:
            try:
                self.raw.close()
            finally:
                if self.slot:
                    _CONNECTION_SLOTS.release()
                    self.slot = False
        return False


class Database:
    def __init__(self, path, database_url=None, allow_insecure_test=False):
        self.path = str(path)
        self.database_url = database_url
        self.allow_insecure_test = allow_insecure_test
        self.backend = 'postgres' if database_url is not None else 'sqlite'
        self.options = {}
        self._initialized = False
        self._initialization_lock = threading.Lock()
        if database_url is not None:
            try:
                parsed = urlsplit(database_url)
                pairs = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=20)
                self.options = dict(pairs)
                if (parsed.scheme not in ('postgres', 'postgresql') or not parsed.hostname
                    or parsed.fragment or not parsed.path or parsed.path == '/'
                    or len(pairs) != len(self.options)
                    or any(key in self.options for key in ('host', 'hostaddr', 'port', 'dbname', 'user', 'password', 'service', 'servicefile', 'options'))):
                    raise ValueError()
                if allow_insecure_test:
                    if parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
                        raise ValueError()
                elif self.options.get('sslmode') != 'verify-full':
                    raise ValueError()
                # Trigger malformed-port validation without disclosing the DSN.
                parsed.port
            except (ValueError, TypeError, AttributeError):
                raise ValueError('Invalid database configuration; PostgreSQL requires an explicit database and verified TLS') from None

    def transaction(self):
        return Transaction(self)

    def initialize(self):
        # Only startup/schema initialization retries. Ordinary request connections
        # retain a five-second timeout and a single attempt; TLS/auth never retry.
        with self._initialization_lock:
            if self._initialized:
                return
            if self.backend == 'sqlite':
                target = Path(self.path)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                descriptor = os.open(target, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
                try:
                    os.fchmod(descriptor, 0o600)
                finally:
                    os.close(descriptor)
            for attempt in range(1, 4):
                try:
                    with self.transaction() as connection:
                        if self.backend == 'postgres' and connection.execute('SHOW server_encoding').fetchone()[0] != 'UTF8':
                            raise ValueError('PostgreSQL database must use UTF8 encoding')
                        connection.executescript(SCHEMA[self.backend])
                        migrate(connection,self.backend)
                    self._initialized = True
                    return
                except ConnectionUnavailable as error:
                    # Fixed vocabulary + bounded integer only. No exc_info,
                    # SQLSTATE, repr(error), DSN, hostname, user or driver args.
                    _LOG.error('GA_DB_CONNECT category=%s attempt=%d', error.category, attempt)
                    if error.category not in _TRANSIENT_CATEGORIES or attempt == 3:
                        raise
                    time.sleep(attempt)
