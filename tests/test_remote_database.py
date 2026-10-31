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
                self.assertEqual(count[0],14)
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
