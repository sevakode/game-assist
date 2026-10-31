"""Real PostgreSQL acceptance suite. Explicit local test DSN; never production DSN.

GA_TEST_POSTGRES_URL points to a disposable loopback database. This suite truncates
all application tables before every test. It is skipped without that exact variable.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.parse import parse_qs, urlsplit

from mcp.server.auth.provider import TokenError
from starlette.testclient import TestClient
from remote_server.app import Config, Store, create_app, digest
from remote_server.database import Database
from remote_server.oauth import OAuthProvider
import test_remote_oauth as oauth_tests
import test_remote_service as service_tests

DSN=os.environ.get('GA_TEST_POSTGRES_URL')
TABLES='notification_settings,notifications,users,sessions,login_states,grants,pairings,devices,observations,events,limits,steam_nonces,oauth_clients,oauth_pending,oauth_codes,oauth_tokens'


def database():
    db=Database('/unused-postgres-test',database_url=DSN,allow_insecure_test=True)
    db.initialize()
    with db.transaction() as connection:
        connection.execute('TRUNCATE '+TABLES)
    return db


@unittest.skipUnless(DSN, 'Real local PostgreSQL DSN not supplied')
class PostgresOAuthTests(oauth_tests.OAuthTests):
    def setUp(self):
        self.database=database()
        super().setUp()

    def test_two_connection_code_and_refresh_races(self):
        provider,client=self.oauth
        code=oauth_tests.issue_code(provider,client)
        loaded=[oauth_tests.run(provider.load_authorization_code(client,code)) for _ in range(2)]
        def redeem(item):
            try: return oauth_tests.run(provider.exchange_authorization_code(client,item))
            except TokenError: return None
        with ThreadPoolExecutor(2) as pool: results=list(pool.map(redeem,loaded))
        self.assertEqual(sum(x is not None for x in results),1)
        tokens=next(x for x in results if x)
        refresh=[oauth_tests.run(provider.load_refresh_token(client,tokens.refresh_token)) for _ in range(2)]
        def rotate(item):
            try: return oauth_tests.run(provider.exchange_refresh_token(client,item,['progress.read']))
            except TokenError: return None
        with ThreadPoolExecutor(2) as pool: results=list(pool.map(rotate,refresh))
        self.assertEqual(sum(x is not None for x in results),1)
        winner=next(x for x in results if x)
        self.assertIsNone(oauth_tests.run(provider.load_access_token(winner.access_token)))

    def test_frozen_exception_rollback_and_timestamp_precision(self):
        with self.assertRaises(TokenError):
            with self.database.transaction() as db:
                db.execute('INSERT INTO limits VALUES(?,?,?)',('rollback',1700000000.125,1))
                raise TokenError('invalid_grant')
        with self.database.transaction() as db:
            self.assertIsNone(db.execute('SELECT * FROM limits WHERE bucket=?',('rollback',)).fetchone())
            db.execute('INSERT INTO limits VALUES(?,?,?)',('precision',1700000000.125,1))
            self.assertEqual(db.execute('SELECT start FROM limits WHERE bucket=?',('precision',)).fetchone()[0],1700000000.125)


@unittest.skipUnless(DSN, 'Real local PostgreSQL DSN not supplied')
class PostgresServiceTests(service_tests.RemoteTests):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.steam=service_tests.FakeSteam()
        self.database=database()
        self.app=create_app(Config(service_tests.ORIGIN,str(Path(self.temp.name)/'unused'),(service_tests.REDIRECT,)),self.steam,database=self.database)
        self.client=TestClient(self.app,base_url=service_tests.ORIGIN,follow_redirects=False)
        self.client.__enter__()

    def test_restart_keeps_grants_devices_sessions_and_summary(self):
        self.sign_in(); device=self.pair(); body=self.observation()
        self.client.post('/v1/device/observations',json=body,headers={'authorization':'Bearer '+device})
        access=self.oauth()
        fresh_db=Database('/unused-restarted',DSN,allow_insecure_test=True)
        fresh=create_app(self.app.state.config,self.steam,database=fresh_db)
        with TestClient(fresh,base_url=service_tests.ORIGIN,follow_redirects=False) as client:
            client.cookies.update(self.client.cookies)
            self.assertIn('Текущее здоровье',client.get('/').text)
            self.assertEqual(client.post('/v1/device/observations',json=body,headers={'authorization':'Bearer '+device}).json()['duplicate'],True)
            token=oauth_tests.run(fresh.state.provider.load_access_token(access))
            self.assertIsNotNone(token)

    def test_two_connection_device_poll_single_issue(self):
        self.sign_in()
        pair=self.client.post('/v1/devices/pair/start',json={}).json()
        self.client.post('/devices/approve',data={'csrf':self.csrf(),'user_code':pair['user_code'],'appid':'4231820','saves.summary':'yes'},headers={'origin':service_tests.ORIGIN})
        def poll(_): return self.client.post('/v1/devices/pair/poll',json={'device_code':pair['device_code']})
        with ThreadPoolExecutor(2) as pool: results=list(pool.map(poll,range(2)))
        self.assertEqual(sorted(x.status_code for x in results),[200,400])
        with self.database.transaction() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM devices').fetchone()[0],1)

    def test_duplicate_ingest_and_revoke_are_serialized(self):
        self.sign_in(); device=self.pair(); body=self.observation(); hdr={'authorization':'Bearer '+device}
        def ingest(_): return self.client.post('/v1/device/observations',json=body,headers=hdr)
        with ThreadPoolExecutor(2) as pool: results=list(pool.map(ingest,range(2)))
        self.assertEqual([x.status_code for x in results],[200,200])
        self.assertEqual(sorted(x.json()['duplicate'] for x in results),[False,True])
        csrf=self.csrf()
        def revoke(): return self.client.post('/account/revoke',data={'csrf':csrf},headers={'origin':service_tests.ORIGIN})
        with ThreadPoolExecutor(2) as pool:
            a=pool.submit(ingest,0); b=pool.submit(revoke); a.result(); self.assertEqual(b.result().status_code,303)
        with self.database.transaction() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM observations').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM devices').fetchone()[0],0)

    def test_steam_nonce_survives_restart(self):
        self.client.get('/login')
        state=parse_qs(urlsplit(self.steam.return_to).query)['state'][0]
        nonce='2026-10-31T15:00:00Zsynthetic-only'
        params={'state':state,'test_identity':'76561198000000001','openid.response_nonce':nonce}
        self.assertEqual(self.client.get('/steam/callback',params=params).status_code,303)
        fresh=create_app(self.app.state.config,self.steam,database=Database('/unused',DSN,allow_insecure_test=True))
        with TestClient(fresh,base_url=service_tests.ORIGIN,follow_redirects=False) as client:
            client.get('/login'); params['state']=parse_qs(urlsplit(self.steam.return_to).query)['state'][0]
            self.assertEqual(client.get('/steam/callback',params=params).status_code,400)


import test_remote_inbox as inbox_tests

@unittest.skipUnless(DSN, 'Real local PostgreSQL DSN not supplied')
class PostgresInboxTests(inbox_tests.InboxTests):
    setUp=PostgresServiceTests.setUp
