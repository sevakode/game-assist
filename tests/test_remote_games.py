"""Three-game selection is not a Steam library or Cloud authorization claim."""
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

from remote_server.app import APPID, COOKIE, digest
from remote_server.database import Database
from remote_server.games import CURRENT_GAME_IDS,CATALOG_REVISION
import test_remote_service as service_tests


class GameSelectionTests(unittest.TestCase):
    setUp=service_tests.RemoteTests.setUp
    tearDown=service_tests.RemoteTests.tearDown
    sign_in=service_tests.RemoteTests.sign_in
    csrf=service_tests.RemoteTests.csrf
    pair=service_tests.RemoteTests.pair
    observation=service_tests.RemoteTests.observation
    oauth=service_tests.RemoteTests.oauth
    mcp=service_tests.RemoteTests.mcp

    def owner(self):
        with self.app.state.store.db() as db:
            return db.execute('SELECT owner FROM sessions WHERE hash=?',(digest(self.client.cookies[COOKIE]),)).fetchone()[0]

    def choose(self,ids=(),summary=False,action='confirm',**extra):
        data={'csrf':self.csrf(),'action':action,**{f'game_{appid}':'yes' for appid in ids}}
        if action=='confirm': data['catalog_revision']=self.app.state.store.catalog_revision(self.owner(),self.catalog())
        if summary:data['summary_4231820']='yes'
        return self.client.post('/account/games',data=data|extra,headers={'origin':service_tests.ORIGIN})

    def catalog(self):return self.app.state.store.catalog(self.owner())
    def selected(self):return {g['appid'] for g in self.catalog() if g['selected']}

    def permission(self,appid=APPID,enabled='yes',scope='saves.summary',**extra):
        return self.client.post('/account/games/permissions',data={'csrf':self.csrf(),'appid':str(appid),'scope':scope,'enabled':enabled,**extra},headers={'origin':service_tests.ORIGIN})

    def revoke(self,appid):
        return self.client.post('/account/games/revoke',data={'csrf':self.csrf(),'appid':str(appid)},headers={'origin':service_tests.ORIGIN})

    def test_visible_review_single_multiple_all_no_implicit_scope(self):
        self.sign_in();home=self.client.get('/games').text
        for name in ('Elden Ring','The Witcher 3','Castlevania'):
            self.assertIn(name,home)
        self.assertEqual(self.selected(),set())
        self.assertEqual(self.choose([1245620],action='review').status_code,200)
        self.assertEqual(self.selected(),set())
        self.assertEqual(self.choose([1245620]).status_code,303)
        self.assertEqual(self.selected(),{1245620})
        self.assertEqual(self.choose([1245620,292030]).status_code,303)
        self.assertEqual(self.selected(),{1245620,292030})
        review=self.choose(action='review_all')
        self.assertEqual(review.status_code,200)
        for appid in CURRENT_GAME_IDS:self.assertIn(f'name="game_{appid}"',review.text)
        self.assertNotIn('name="summary_1245620"',review.text)
        self.choose(CURRENT_GAME_IDS)
        self.assertEqual(self.selected(),set(CURRENT_GAME_IDS))
        self.assertTrue(all(not g['authorized'] for g in self.catalog()))
        self.assertEqual(self.app.state.store.projection(self.owner())['games'],[])

    def test_explicit_available_grant_and_unavailable_sources_denied(self):
        self.sign_in();self.assertEqual(self.permission().status_code,403)
        self.choose(CURRENT_GAME_IDS,summary=True)
        catalog={g['appid']:g for g in self.catalog()}
        self.assertTrue(catalog[APPID]['authorized']);self.assertTrue(catalog[APPID]['summary_supported'])
        for appid in (1245620,292030):
            self.assertFalse(catalog[appid]['authorized']);self.assertFalse(catalog[appid]['summary_supported'])
            self.assertEqual(catalog[appid]['source_status'],'metadata_only_parser_unavailable')
            self.assertEqual(self.permission(appid).status_code,422)
        for scope in ('achievements.read','read_cloud'):
            self.assertEqual(self.permission(scope=scope).status_code,503 if scope=='achievements.read' else 422)
        self.assertTrue(all(not g['cloud_available'] and not g['achievements_available'] for g in catalog.values()))
        self.assertEqual(self.permission(enabled='no').status_code,303)
        self.assertEqual(self.selected(),set(CURRENT_GAME_IDS))
        self.assertFalse(next(g for g in self.catalog() if g['appid']==APPID)['authorized'])

    def test_catalog_revision_future_games_and_strict_csrf(self):
        self.sign_in()
        self.assertEqual(self.choose(CURRENT_GAME_IDS,catalog_revision='old').status_code,409)
        self.assertEqual(self.choose([999999]).status_code,422)
        self.assertEqual(self.choose([],summary=True).status_code,422)
        with patch.dict('remote_server.games.GAMES',{999999:{'name':'SYNTHETIC_FUTURE','summary_supported':False}}):
            review=self.choose(action='review_all')
            self.assertNotIn('SYNTHETIC_FUTURE',review.text)
            self.assertNotIn('game_999999',review.text)
        self.assertEqual(self.choose(CURRENT_GAME_IDS,csrf='bad').status_code,403)
        self.assertEqual(self.choose(CURRENT_GAME_IDS,owner='other').status_code,422)
        data={'csrf':self.csrf(),'action':'review_all'}
        self.assertEqual(self.client.post('/account/games',data=data).status_code,403)
        encoded='csrf='+data['csrf']+'&action=review&game_4231820=yes&game_4231820=yes'
        self.assertEqual(self.client.post('/account/games',content=encoded,headers={'origin':service_tests.ORIGIN,'content-type':'application/x-www-form-urlencoded'}).status_code,403)

    def test_per_game_revoke_clears_data_old_token_and_preserves_other_choices(self):
        self.sign_in();token=self.pair();self.choose(CURRENT_GAME_IDS,summary=True)
        self.client.post('/v1/device/observations',json=self.observation(),headers={'authorization':'Bearer '+token})
        oauth=self.oauth()
        self.assertIn('currentHealth',self.mcp(oauth,'tools/call',{'name':'get_progress','arguments':{}}).text)
        self.assertEqual(self.revoke(1245620).status_code,303)
        self.assertIn(APPID,self.selected())
        self.assertIn('currentHealth',self.mcp(oauth,'tools/call',{'name':'get_progress','arguments':{}}).text)
        self.assertEqual(self.revoke(APPID).status_code,303)
        self.assertEqual(self.selected(),{292030})
        self.assertNotIn('currentHealth',self.mcp(oauth,'tools/call',{'name':'get_progress','arguments':{}}).text)
        self.choose([APPID,292030],summary=True)
        self.assertEqual(self.client.post('/v1/device/observations',json=self.observation(),headers={'authorization':'Bearer '+token}).status_code,401)
        owner=self.owner()
        with self.app.state.store.db() as db:
            for table in ('devices','observations_v2','notifications','notification_settings'):
                self.assertEqual(db.execute(f'SELECT count(*) FROM {table} WHERE owner=? AND appid=?',(owner,APPID)).fetchone()[0],0)

    def test_cross_tenant_selection_focus_and_revoke(self):
        self.sign_in();self.choose([APPID,1245620],summary=True);first=self.owner()
        self.client.cookies.clear();self.sign_in('76561198000000002')
        self.assertEqual(self.selected(),set())
        self.assertEqual(self.client.get('/games?game=1245620').status_code,404)
        self.assertEqual(self.permission(owner=first).status_code,422)
        self.revoke(APPID)
        self.assertTrue(next(g for g in self.app.state.store.catalog(first) if g['appid']==APPID)['authorized'])
        self.choose([292030]);self.assertEqual(self.client.get('/games?game=292030').status_code,200)
        self.assertEqual(self.client.get('/games?game=999999').status_code,404)
        self.assertEqual(self.client.get('/games?game=not-int').status_code,400)

    def test_unsupported_game_ingestion_and_pairing_rejected(self):
        self.sign_in();token=self.pair();self.choose(CURRENT_GAME_IDS,summary=True)
        for appid in (1245620,292030):
            body=self.observation();body['appid']=appid
            self.assertEqual(self.client.post('/v1/device/observations',json=body,headers={'authorization':'Bearer '+token}).status_code,422)
            pair=self.client.post('/v1/devices/pair/start',json={}).json()
            self.assertEqual(self.client.post('/devices/approve',data={'csrf':self.csrf(),'appid':str(appid),'saves.summary':'yes','user_code':pair['user_code']},headers={'origin':service_tests.ORIGIN}).status_code,422)
        self.assertIn('name="saves.metadata"',self.client.get('/devices/approve').text)

    def test_legacy_belmont_only_migration_and_global_revoke(self):
        self.sign_in();owner=self.owner()
        with self.app.state.store.db() as db:
            db.execute('INSERT OR IGNORE INTO grants VALUES(?,?,?)',(owner,APPID,'saves.summary'))
            db.execute('INSERT OR IGNORE INTO grants VALUES(?,?,?)',(owner,APPID,'saves.metadata'))
        with self.app.state.store.db() as db:
            db.execute("DELETE FROM schema_migrations WHERE name='universal_metadata_v1'")
        old=self.app.state.store.database
        Database(old.path,old.database_url,allow_insecure_test=old.allow_insecure_test).initialize()
        self.assertEqual(self.selected(),{APPID})
        with self.app.state.store.db() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM grants WHERE owner=? AND scope='saves.metadata'",(owner,)).fetchone())
        self.choose(CURRENT_GAME_IDS,summary=True)
        self.client.post('/account/revoke',data={'csrf':self.csrf()},headers={'origin':service_tests.ORIGIN})
        self.assertEqual(self.selected(),set())

    def test_revoke_game_concurrent_ingest_cannot_restore_data(self):
        self.sign_in();token=self.pair();csrf=self.csrf();body=self.observation()
        with ThreadPoolExecutor(2) as pool:
            a=pool.submit(self.client.post,'/v1/device/observations',json=body,headers={'authorization':'Bearer '+token})
            b=pool.submit(self.client.post,'/account/games/revoke',data={'csrf':csrf,'appid':str(APPID)},headers={'origin':service_tests.ORIGIN})
            a.result();self.assertEqual(b.result().status_code,303)
        self.assertEqual(self.app.state.store.projection(self.owner())['games'],[])
        self.assertNotIn(APPID,self.selected())
