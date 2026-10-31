"""Synthetic legacy-schema upgrades, consent preservation, and rollback."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from remote_server.database import Database
from remote_server.schema import migrate

LEGACY = '''
CREATE TABLE grants(owner TEXT,appid INTEGER,scope TEXT,PRIMARY KEY(owner,appid,scope));
CREATE TABLE pairings(hash TEXT PRIMARY KEY,user_hash TEXT UNIQUE,expires REAL,last_poll REAL NOT NULL DEFAULT 0,owner TEXT,scopes TEXT,consumed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE devices(hash TEXT PRIMARY KEY,owner TEXT NOT NULL,appid INTEGER NOT NULL,scopes TEXT NOT NULL,expires REAL NOT NULL);
CREATE TABLE observations(owner TEXT,appid INTEGER,payload TEXT,observed REAL,PRIMARY KEY(owner,appid));
CREATE TABLE events(owner TEXT,device_hash TEXT,event_id TEXT,created REAL,payload_hash TEXT NOT NULL,PRIMARY KEY(device_hash,event_id));
'''


class UniversalMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'old.sqlite'
        db=sqlite3.connect(self.path)
        db.executescript(LEGACY)
        db.execute('INSERT INTO grants VALUES(?,?,?)',('owner-a',4231820,'saves.summary'))
        db.execute('INSERT INTO grants VALUES(?,?,?)',('owner-a',4231820,'saves.metadata'))
        db.execute('INSERT INTO grants VALUES(?,?,?)',('owner-b',4231820,'saves.metadata'))
        for owner in ('owner-a','owner-b'):
            db.execute('INSERT INTO observations VALUES(?,?,?,?)',(owner,4231820,'{"synthetic":"summary"}',1700000000.125))
        db.execute('INSERT INTO devices VALUES(?,?,?,?,?)',('summary','owner-a',4231820,'["saves.summary"]',1900000000))
        db.execute('INSERT INTO devices VALUES(?,?,?,?,?)',('metadata','owner-b',4231820,'["saves.metadata"]',1900000000))
        db.execute('INSERT INTO devices VALUES(?,?,?,?,?)',('mixed','owner-a',4231820,'["saves.summary","saves.metadata"]',1900000000))
        db.execute('INSERT INTO pairings VALUES(?,?,?,?,?,?,?)',('pending','usercode',1900000000,0,None,None,0))
        db.execute('INSERT INTO pairings VALUES(?,?,?,?,?,?,?)',('approved','usercode2',1900000000,0,'owner-b','["saves.metadata"]',0))
        db.execute('INSERT INTO events VALUES(?,?,?,?,?)',('owner-a','summary','old-event',1700000000.125,'unchanged-hash'))
        db.commit();db.close()

    def test_old_columns_scopes_and_owner_data_migrate_safely(self):
        Database(self.path).initialize()
        with Database(self.path).transaction() as db:
            event=db.execute('SELECT * FROM events').fetchone()
            self.assertEqual((event['appid'],event['kind'],event['payload_hash']),(4231820,'save_summary','unchanged-hash'))
            pairing=db.execute('SELECT * FROM pairings WHERE hash=?',('pending',)).fetchone()
            self.assertEqual(pairing['appid'],4231820)
            self.assertEqual(json.loads(pairing['requested_scopes']),['saves.summary'])
            self.assertEqual(db.execute('SELECT count(*) FROM observations_v2').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT owner,observed FROM observations_v2').fetchone()[0],'owner-a')
            self.assertEqual(db.execute('SELECT observed FROM observations_v2').fetchone()[0],1700000000.125)
            self.assertEqual(db.execute('SELECT count(*) FROM observations').fetchone()[0],2)
            self.assertIsNone(db.execute("SELECT 1 FROM grants WHERE scope='saves.metadata'").fetchone())
            self.assertIsNone(db.execute('SELECT 1 FROM devices WHERE hash=?',('metadata',)).fetchone())
            self.assertIsNone(db.execute('SELECT 1 FROM pairings WHERE hash=?',('approved',)).fetchone())
            self.assertEqual(json.loads(db.execute('SELECT scopes FROM devices WHERE hash=?',('mixed',)).fetchone()[0]),['saves.summary'])
            self.assertEqual(db.execute('SELECT count(*) FROM schema_migrations').fetchone()[0],1)

    def test_upgrade_is_idempotent_and_new_metadata_consent_is_not_removed(self):
        Database(self.path).initialize()
        with Database(self.path).transaction() as db:
            db.execute('INSERT INTO grants VALUES(?,?,?)',('owner-b',1245620,'saves.metadata'))
            db.execute('INSERT INTO devices VALUES(?,?,?,?,?)',('new-metadata','owner-b',1245620,'["saves.metadata"]',1900000000))
            db.execute("UPDATE observations_v2 SET payload='new-current-summary' WHERE owner='owner-a'")
        Database(self.path).initialize()
        with Database(self.path).transaction() as db:
            self.assertIsNotNone(db.execute('SELECT 1 FROM grants WHERE owner=? AND appid=?',('owner-b',1245620)).fetchone())
            self.assertIsNotNone(db.execute('SELECT 1 FROM devices WHERE hash=?',('new-metadata',)).fetchone())
            self.assertEqual(db.execute('SELECT payload FROM observations_v2').fetchone()[0],'new-current-summary')
            for table in ('pairings','events'):
                columns=[row['name'] for row in db.execute(f'PRAGMA table_info({table})').fetchall()]
                self.assertEqual(columns.count('appid'),1)

    def test_failed_upgrade_rolls_back_columns_cleanup_and_marker(self):
        def fail_after(connection,backend):
            migrate(connection,backend)
            raise RuntimeError('synthetic migration failure')
        with patch('remote_server.database.migrate',side_effect=fail_after):
            with self.assertRaises(RuntimeError):Database(self.path).initialize()
        with sqlite3.connect(self.path) as db:
            self.assertNotIn('appid',[row[1] for row in db.execute('PRAGMA table_info(events)')])
            self.assertEqual(db.execute("SELECT count(*) FROM grants WHERE scope='saves.metadata'").fetchone()[0],2)
            self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name='schema_migrations'").fetchone()[0],0)
        Database(self.path).initialize()
        with Database(self.path).transaction() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM schema_migrations').fetchone()[0],1)


import os
from uuid import uuid4
from remote_server.schema import SCHEMA


@unittest.skipUnless(os.environ.get('GA_TEST_POSTGRES_URL'),'Real local PostgreSQL DSN not supplied')
class PostgresUniversalMigrationTests(unittest.TestCase):
    def test_real_postgres_legacy_upgrade_and_idempotent_consent(self):
        db=Database('/unused-migration-test',os.environ['GA_TEST_POSTGRES_URL'],allow_insecure_test=True)
        schema='test_migration_'+uuid4().hex
        with db.transaction() as connection:
            connection.execute('CREATE SCHEMA '+schema)
            connection.execute('SET LOCAL search_path TO '+schema)
            # Only fixed, synthetic local schema; never the hosted application's data.
            connection.executescript(LEGACY.replace(' REAL',' DOUBLE PRECISION'))
            connection.execute('INSERT INTO grants VALUES(?,?,?)',('owner-a',4231820,'saves.summary'))
            connection.execute('INSERT INTO grants VALUES(?,?,?)',('owner-a',4231820,'saves.metadata'))
            connection.execute('INSERT INTO observations VALUES(?,?,?,?)',('owner-a',4231820,'synthetic-summary',1700000000.125))
            connection.execute('INSERT INTO events VALUES(?,?,?,?,?)',('owner-a','device','event',1700000000.125,'old-hash'))
            connection.executescript(SCHEMA['postgres'])
            migrate(connection,'postgres')
            self.assertEqual(connection.execute('SELECT appid,kind FROM events').fetchone()['kind'],'save_summary')
            self.assertEqual(connection.execute('SELECT payload FROM observations_v2').fetchone()[0],'synthetic-summary')
            self.assertIsNone(connection.execute("SELECT 1 FROM grants WHERE scope='saves.metadata'").fetchone())
            connection.execute('INSERT INTO grants VALUES(?,?,?)',('owner-a',1245620,'saves.metadata'))
            migrate(connection,'postgres')
            self.assertIsNotNone(connection.execute('SELECT 1 FROM grants WHERE appid=?',(1245620,)).fetchone())
            self.assertEqual(connection.execute('SELECT count(*) FROM schema_migrations').fetchone()[0],1)
            connection.execute('DROP SCHEMA '+schema+' CASCADE')
