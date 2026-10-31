"""Request-driven achievement consent/cache tests; never external Steam calls."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import unittest
from urllib.parse import urlsplit,parse_qs
import test_remote_games as games
from test_remote_service import ORIGIN

class FakeReader:
    configured=True
    def __init__(self):self.calls=[];self.status='ok';self.entered=None;self.release=None
    def get_unlocked(self,steamid,appid):
        self.calls.append((steamid,appid))
        if self.entered:self.entered.set();self.release.wait(5)
        return {'status':self.status,'achievements':[{'apiname':'UNLOCKED','name':'Opened','unlock_time':123}] if self.status=='ok' else [],'source':'steam_web_api'}

class AchievementTests(unittest.TestCase):
    def setUp(self):
        self.reader=FakeReader()
        with patch('remote_server.app.AchievementReader',return_value=self.reader):games.GameSelectionTests.setUp(self)
    tearDown=games.GameSelectionTests.tearDown
    sign_in=games.GameSelectionTests.sign_in
    csrf=games.GameSelectionTests.csrf
    choose=games.GameSelectionTests.choose
    catalog=games.GameSelectionTests.catalog
    owner=games.GameSelectionTests.owner
    revoke=games.GameSelectionTests.revoke
    permission=games.GameSelectionTests.permission
    def enable(self,appid=1245620):return self.permission(appid,scope='achievements.read')
    def refresh(self,appid=1245620,**extra):
        return self.client.post('/account/achievements/refresh',data={'csrf':self.csrf(),'appid':str(appid),**extra},headers={'origin':ORIGIN})
    def projection(self):return self.app.state.store.projection(self.owner())['games']
    def age(self):
        with self.app.state.store.db() as db:db.execute('UPDATE achievement_cache SET attempted_at=0')

    def test_absent_key_no_automatic_grant_or_request(self):
        self.reader.configured=False;self.app.state.store.achievements_available=False
        self.sign_in();self.choose([1245620])
        self.assertEqual(self.enable().status_code,503);self.assertEqual(self.refresh().status_code,503)
        self.assertEqual(self.reader.calls,[]);self.assertEqual(self.projection(),[])
        self.reader.configured=True;self.app.state.store.achievements_available=True
        self.assertEqual(self.refresh().status_code,403);self.assertEqual(self.reader.calls,[])
        self.assertEqual(self.projection(),[])

    def test_explicit_scope_cache_only_read_cooldown_and_unavailable(self):
        self.sign_in();self.choose([1245620]);self.assertEqual(self.enable().status_code,303)
        self.assertEqual(self.projection()[0]['achievements']['status'],'not_requested')
        self.assertEqual(self.reader.calls,[])
        response=self.refresh();self.assertEqual(response.status_code,303,response.text)
        cached=self.projection()[0]['achievements'];self.assertEqual(cached['items'][0]['name'],'Opened')
        self.assertNotIn('steamid',json.dumps(cached).lower())
        self.assertEqual(self.refresh().status_code,429);self.assertEqual(len(self.reader.calls),1)
        self.reader.status='unavailable';self.age();self.refresh()
        cached=self.projection()[0]['achievements'];self.assertEqual(cached['status'],'unavailable');self.assertEqual(cached['items'],[])
        with self.app.state.store.db() as db:self.assertIsNone(db.execute('SELECT payload FROM achievement_cache').fetchone()[0])

    def test_tenant_csrf_expiry_and_revoke(self):
        self.sign_in();self.choose([1245620]);self.enable();first=self.owner()
        self.assertEqual(self.refresh(csrf='bad').status_code,403)
        self.assertEqual(self.refresh(owner='other').status_code,422)
        self.assertEqual(self.refresh(292030).status_code,403)
        self.refresh()
        with self.app.state.store.db() as db:db.execute('UPDATE achievement_cache SET expires=1')
        self.assertEqual(self.projection()[0]['achievements']['status'],'expired')
        self.assertEqual(self.projection()[0]['achievements']['items'],[])
        self.client.cookies.clear();self.sign_in('76561198000000002');self.choose([1245620]);self.enable()
        self.assertEqual(self.projection()[0]['achievements']['status'],'not_requested')
        self.revoke(1245620)
        with self.app.state.store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM achievement_cache WHERE owner=?',(first,)).fetchone()[0],1)

    def test_inflight_revoke_regrant_does_not_restore_old_response(self):
        self.sign_in();self.choose([1245620]);self.enable();csrf=self.csrf()
        self.reader.entered=threading.Event();self.reader.release=threading.Event()
        with ThreadPoolExecutor(2) as pool:
            result=pool.submit(self.client.post,'/account/achievements/refresh',data={'csrf':csrf,'appid':'1245620'},headers={'origin':ORIGIN})
            self.assertTrue(self.reader.entered.wait(5))
            self.assertEqual(self.permission(1245620,enabled='no',scope='achievements.read').status_code,303)
            self.enable();self.reader.release.set()
            self.assertEqual(result.result().status_code,409)
        self.assertEqual(self.projection()[0]['achievements']['status'],'not_requested')
        self.assertEqual(self.projection()[0]['achievements']['items'],[])

    def test_device_scope_never_achievement_and_all_revoke_clears(self):
        self.sign_in();self.choose([1245620]);self.enable();self.refresh()
        self.assertEqual(self.client.post('/v1/devices/pair/start',json={'appid':1245620,'scopes':['achievements.read']}).status_code,422)
        self.client.post('/account/revoke',data={'csrf':self.csrf()},headers={'origin':ORIGIN})
        with self.app.state.store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM achievement_cache').fetchone()[0],0)
        self.assertEqual(self.refresh().status_code,403)

    def test_import_safe_login_continuation(self):
        response=self.client.get('/import');self.assertEqual(response.status_code,303)
        self.assertEqual(response.headers['location'],'/login?next=%2Fimport')
        self.client.get(response.headers['location'])
        state=parse_qs(urlsplit(self.steam.return_to).query)['state'][0]
        response=self.client.get('/steam/callback',params={'state':state,'test_identity':'76561198000000001'})
        self.assertEqual(response.headers['location'],'/import')
        for target in ('https://evil.test','//evil.test','/import?next=https://evil.test','/import/../login'):
            self.assertEqual(self.client.get('/login',params={'next':target}).status_code,400)

    def test_global_owner_storage_budget_fail_before_io(self):
        self.sign_in();self.choose([1245620,292030]);self.enable()
        with patch('remote_server.app.ACHIEVEMENT_ROWS_PER_OWNER',1):
            self.assertEqual(self.enable(292030).status_code,429)
        with patch('remote_server.app.ACHIEVEMENT_ROWS_GLOBAL',1):
            self.assertEqual(self.enable(292030).status_code,429)
        self.assertEqual(self.reader.calls,[])
        with self.app.state.store.db() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM grants WHERE appid=292030 AND scope='achievements.read'").fetchone())
        self.permission(1245620,enabled='no',scope='achievements.read')
        with patch('remote_server.app.ACHIEVEMENT_ROWS_GLOBAL',1):self.assertEqual(self.enable(292030).status_code,303)
