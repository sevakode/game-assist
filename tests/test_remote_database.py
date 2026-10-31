"""Backend boundary unit tests. Real PostgreSQL tests are separate, not simulated."""
import os
from pathlib import Path
import tempfile
import unittest

from mcp.server.auth.provider import TokenError
from remote_server.database import Database, _postgres_sql
from remote_server.schema import POSTGRES_SCHEMA


class DatabaseTests(unittest.TestCase):
    def test_sqlite_initialize_private_all_tables_and_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'private'/'db.sqlite'
            db=Database(path)
            db.initialize()
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            with db.transaction() as connection:
                count=connection.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()
                self.assertEqual(count[0],16)
                connection.execute('INSERT INTO users VALUES(?,?)',('user','76561198000000000'))
                row=connection.execute('SELECT id,steamid FROM users').fetchone()
                self.assertEqual(row[0],row['id'])
                self.assertEqual(dict(row),{'id':'user','steamid':'76561198000000000'})
                connection.execute('INSERT INTO steam_nonces VALUES(?,?)',('hash',10))
                self.assertEqual(connection.execute('DELETE FROM steam_nonces WHERE nonce_hash=? RETURNING nonce_hash',('hash',)).fetchone()[0],'hash')
            db.initialize()
            with Database(path).transaction() as connection:
                self.assertEqual(connection.execute('SELECT count(*) FROM users').fetchone()[0],1)

    def test_frozen_sdk_error_rolls_back_without_masking(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Database(Path(tmp)/'db');db.initialize()
            with self.assertRaises(TokenError):
                with db.transaction() as connection:
                    connection.execute('INSERT INTO users VALUES(?,?)',('user','76561198000000000'))
                    raise TokenError('invalid_grant','synthetic')
            with db.transaction() as connection:
                self.assertEqual(connection.execute('SELECT count(*) FROM users').fetchone()[0],0)

    def test_secure_postgres_dsn_required_no_silent_sqlite_fallback(self):
        invalid=['', 'sqlite:///tmp/file','postgresql://db.example/',
                 'postgresql://db.example/game',
                 'postgresql://db.example/game?sslmode=require',
                 'postgresql://db.example/game?sslmode=verify-full&sslmode=disable',
                 'postgresql://db.example/game?sslmode=verify-full&host=other.example',
                 'postgresql://db.example/game?sslmode=verify-full#fragment']
        for url in invalid:
            with self.subTest(url=url),self.assertRaises(ValueError):
                Database('unused',url)
        db=Database('unused','postgresql://user:secret@db.example/game?sslmode=verify-full')
        self.assertEqual(db.backend,'postgres')
        with self.assertRaises(ValueError):
            Database('unused','postgresql://external.example/game?sslmode=disable',allow_insecure_test=True)
        local=Database('unused','postgresql://127.0.0.1/game?sslmode=disable',allow_insecure_test=True)
        self.assertEqual(local.backend,'postgres')

    def test_explicit_dialect_upserts_and_float64_schema(self):
        self.assertNotIn(' REAL',POSTGRES_SCHEMA)
        self.assertIn('DOUBLE PRECISION',POSTGRES_SCHEMA)
        self.assertIn("data::jsonb->>'subject'",POSTGRES_SCHEMA)
        self.assertEqual(_postgres_sql('SELECT * FROM t WHERE x=?'), 'SELECT * FROM t WHERE x=%s')
        self.assertIn('ON CONFLICT(owner,appid,scope) DO NOTHING',_postgres_sql('INSERT OR IGNORE INTO grants VALUES(?,?,?)'))
        self.assertIn('ON CONFLICT(bucket) DO UPDATE',_postgres_sql('INSERT OR REPLACE INTO limits VALUES(?,?,1)'))
        self.assertIn('ON CONFLICT(owner,appid) DO UPDATE',_postgres_sql('INSERT OR REPLACE INTO observations VALUES(?,?,?,?)'))
        self.assertIn("kind='refresh'",_postgres_sql('SELECT * FROM oauth_tokens WHERE kind="refresh"'))
        with self.assertRaises(ValueError):
            _postgres_sql('INSERT OR REPLACE INTO unknown VALUES(?)')
        with self.assertRaises(ValueError):
            _postgres_sql("SELECT '?' AS literal")

    def test_initialize_does_not_follow_sqlite_symlink(self):
        if not hasattr(os,'O_NOFOLLOW'):
            self.skipTest('Host lacks no-follow open')
        with tempfile.TemporaryDirectory() as tmp:
            original=Path(tmp)/'original';original.write_text('untouched')
            link=Path(tmp)/'link';link.symlink_to(original)
            with self.assertRaises(OSError):
                Database(link).initialize()
            self.assertEqual(original.read_text(),'untouched')


if __name__=='__main__': unittest.main()


class ConnectionDiagnosticTests(unittest.TestCase):
    SECRET = 'SYNTHETIC-PASSWORD-NOT-FOR-LOGS'

    def fake_driver(self, failures):
        from types import SimpleNamespace
        from unittest.mock import Mock
        class DriverError(Exception):
            pass
        return SimpleNamespace(Error=DriverError,connect=Mock(side_effect=[DriverError(text) if isinstance(text,str) else text for text in failures]))

    def fake_connection(self):
        from unittest.mock import Mock
        raw=Mock()
        raw.execute.return_value.description=[('server_encoding',)]
        raw.execute.return_value.fetchone.return_value=('UTF8',)
        return raw

    def postgres(self):
        return Database('unused','postgresql://synthetic:'+self.SECRET+'@private-host.example/game?sslmode=verify-full&channel_binding=require')

    def test_only_constant_categories_for_secret_bearing_messages(self):
        from remote_server.database import connection_failure_category, ConnectionUnavailable
        cases={'root certificate file not found':'TLS_ROOTS','certificate verify failed':'TLS_VERIFY',
               'password authentication failed':'AUTH','channel binding required':'CHANNEL_BINDING',
               'could not translate host name':'DNS','timeout expired':'TIMEOUT',
               'connection refused':'NETWORK','unexpected failure':'OTHER'}
        for message,expected in cases.items():
            self.assertEqual(connection_failure_category(RuntimeError(message+' '+self.SECRET)),expected)
        self.assertEqual(ConnectionUnavailable(self.SECRET).category,'OTHER')
        self.assertNotIn(self.SECRET,str(ConnectionUnavailable(self.SECRET)))

    def test_startup_tls_diagnostic_no_secret_no_retry_or_weakening(self):
        import traceback
        from unittest.mock import patch
        from remote_server.database import ConnectionUnavailable
        driver=self.fake_driver(['root certificate file unavailable '+self.SECRET+' postgresql://private-host.example'])
        with patch.dict('sys.modules',{'psycopg':driver}),patch('remote_server.database.time.sleep') as sleep:
            with self.assertLogs('remote_server.database',level='ERROR') as logs:
                try:
                    self.postgres().initialize()
                except ConnectionUnavailable as error:
                    rendered=''.join(traceback.format_exception(error))
                    self.assertIsNone(error.__context__)
                    self.assertIsNone(error.__cause__)
                else:
                    self.fail('Expected safe connection failure')
            self.assertEqual(logs.output,['ERROR:remote_server.database:GA_DB_CONNECT category=TLS_ROOTS attempt=1'])
            self.assertEqual(driver.connect.call_count,1);sleep.assert_not_called()
            self.assertEqual(driver.connect.call_args.kwargs['sslmode'],'verify-full')
            import certifi
            self.assertEqual(driver.connect.call_args.kwargs['sslrootcert'],certifi.where())
            self.assertEqual(driver.connect.call_args.kwargs['connect_timeout'],5)
            for secret in (self.SECRET,'private-host.example','postgresql://'):
                self.assertNotIn(secret,rendered+' '.join(logs.output))

    def test_transient_startup_recovers_without_repeating_initialize(self):
        from unittest.mock import patch
        raw=self.fake_connection();driver=self.fake_driver(['timeout expired '+self.SECRET,raw])
        db=self.postgres()
        with patch.dict('sys.modules',{'psycopg':driver}),patch('remote_server.database.time.sleep') as sleep:
            with self.assertLogs('remote_server.database',level='ERROR') as logs: db.initialize()
            db.initialize()
            self.assertEqual(driver.connect.call_count,2);sleep.assert_called_once_with(1)
            self.assertIn('category=TIMEOUT attempt=1',logs.output[0])
            raw.commit.assert_called_once();raw.close.assert_called_once()

    def test_transient_startup_retries_are_bounded(self):
        from unittest.mock import patch,call
        from remote_server.database import ConnectionUnavailable
        for text in ('could not translate host name','timeout expired','connection refused'):
            driver=self.fake_driver([text+' '+self.SECRET]*3)
            with patch.dict('sys.modules',{'psycopg':driver}),patch('remote_server.database.time.sleep') as sleep:
                with self.assertLogs('remote_server.database',level='ERROR') as logs,self.assertRaises(ConnectionUnavailable):
                    self.postgres().initialize()
                self.assertEqual(driver.connect.call_count,3)
                self.assertEqual(sleep.call_args_list,[call(1),call(2)])
                self.assertEqual(len(logs.output),3)
                self.assertNotIn(self.SECRET,' '.join(logs.output))

    def test_auth_channel_binding_unknown_fail_without_retries(self):
        from unittest.mock import patch
        from remote_server.database import ConnectionUnavailable
        for text in ('password authentication failed','channel binding required','unrecognized failure','certificate verify failed'):
            driver=self.fake_driver([text+' '+self.SECRET])
            with patch.dict('sys.modules',{'psycopg':driver}),patch('remote_server.database.time.sleep') as sleep:
                with self.assertLogs('remote_server.database',level='ERROR'),self.assertRaises(ConnectionUnavailable):
                    self.postgres().initialize()
                self.assertEqual(driver.connect.call_count,1);sleep.assert_not_called()

    def test_normal_transaction_does_not_retry(self):
        from unittest.mock import patch
        from remote_server.database import ConnectionUnavailable
        driver=self.fake_driver(['timeout expired '+self.SECRET])
        with patch.dict('sys.modules',{'psycopg':driver}),patch('remote_server.database.time.sleep') as sleep:
            with self.assertRaises(ConnectionUnavailable):
                with self.postgres().transaction(): pass
            self.assertEqual(driver.connect.call_count,1);sleep.assert_not_called()


class TrustedRootDiagnosticTests(unittest.TestCase):
    SECRET = ConnectionDiagnosticTests.SECRET
    fake_driver = ConnectionDiagnosticTests.fake_driver
    fake_connection = ConnectionDiagnosticTests.fake_connection
    postgres = ConnectionDiagnosticTests.postgres
    def test_specific_tls_subcategories_are_constant_and_never_transient(self):
        from remote_server.database import connection_failure_category, _TRANSIENT_CATEGORIES
        cases={'SSL error: certificate verify failed: unable to get local issuer certificate':'TLS_ISSUER',
               'SSL error: certificate verify failed: self-signed certificate':'TLS_SELF_SIGNED',
               'SSL error: certificate verify failed: certificate has expired':'TLS_EXPIRED',
               'server certificate does not match host name':'TLS_HOSTNAME',
               'SSL error: wrong version number':'TLS_PROTOCOL',
               'SSL error: alert handshake failure':'TLS_HANDSHAKE',
               'SSL error: something unspecified':'TLS_OTHER',
               'certificate verify failed':'TLS_VERIFY'}
        for text,category in cases.items():
            self.assertEqual(connection_failure_category(RuntimeError(text+' '+self.SECRET)),category)
            self.assertNotIn(category,_TRANSIENT_CATEGORIES)

    def test_system_dsn_root_uses_certifi_without_changing_channel_binding(self):
        import certifi
        from unittest.mock import patch
        raw=self.fake_connection();driver=self.fake_driver([raw])
        db=Database('unused','postgresql://test:test@private-host.example/game?sslmode=verify-full&sslrootcert=system&channel_binding=require')
        with patch.dict('sys.modules',{'psycopg':driver}):
            db.initialize()
        self.assertEqual(driver.connect.call_args.kwargs['sslrootcert'],certifi.where())
        self.assertEqual(driver.connect.call_args.kwargs['sslmode'],'verify-full')
        self.assertIn('channel_binding=require',driver.connect.call_args.args[0])

    def test_missing_trusted_bundle_fails_closed_without_connecting(self):
        from unittest.mock import patch
        from remote_server.database import ConnectionUnavailable
        driver=self.fake_driver([])
        with patch.dict('sys.modules',{'psycopg':driver}),patch('certifi.where',return_value='/nonexistent/synthetic-ca-file'),patch('remote_server.database.time.sleep') as sleep:
            with self.assertLogs('remote_server.database',level='ERROR') as logs,self.assertRaises(ConnectionUnavailable):
                self.postgres().initialize()
            driver.connect.assert_not_called();sleep.assert_not_called()
            self.assertEqual(logs.output,['ERROR:remote_server.database:GA_DB_CONNECT category=TLS_ROOTS attempt=1'])
