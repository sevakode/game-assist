import threading,unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import test_remote_games as games
from test_remote_service import ORIGIN
class FakeLibrary:
    configured=True
    def __init__(self):self.calls=[];self.status='ok';self.entered=None;self.release=None
    def get_games(self,steamid):
        self.calls.append(steamid)
        if self.entered:self.entered.set();self.release.wait(5)
        return {'status':self.status,'games':[{'appid':1086940,'name':"Baldur's Gate 3"}] if self.status=='ok' else [],'source':'steam_web_api'}
class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.reader=FakeLibrary()
        with patch('remote_server.app.LibraryReader',return_value=self.reader):games.GameSelectionTests.setUp(self)
    tearDown=games.GameSelectionTests.tearDown
    sign_in=games.GameSelectionTests.sign_in
    csrf=games.GameSelectionTests.csrf
    owner=games.GameSelectionTests.owner
    def permission(self,enabled='yes',**extra):return self.client.post('/account/library/permission',data={'csrf':self.csrf(),'enabled':enabled,**extra},headers={'origin':ORIGIN})
    def refresh(self,**extra):return self.client.post('/account/library/refresh',data={'csrf':self.csrf(),**extra},headers={'origin':ORIGIN})
    def state(self):return self.app.state.store.library(self.owner())
    def age(self):
        with self.app.state.store.db() as db:db.execute('UPDATE library_cache SET attempted_at=0')
    def test_no_key_or_consent_no_call_no_auto_selection(self):
        self.sign_in();self.reader.configured=False;self.app.state.store.library_available=False
        self.assertEqual(self.permission().status_code,503);self.assertEqual(self.refresh().status_code,503)
        self.reader.configured=True;self.app.state.store.library_available=True
        self.assertEqual(self.refresh().status_code,403);self.assertEqual(self.reader.calls,[])
        self.assertEqual(self.permission().status_code,303);self.assertEqual(self.refresh().status_code,303)
        self.assertEqual(self.state()['games'][0]['appid'],1086940)
        with self.app.state.store.db() as db:
            for table in ('game_registrations','game_selections','grants'):self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
        self.assertEqual(self.app.state.store.projection(self.owner())['games'],[])
    def test_exact_fields_csrf_tenant_and_clear(self):
        self.sign_in();self.assertEqual(self.permission(csrf='bad').status_code,403)
        self.assertEqual(self.permission(owner='other').status_code,422)
        self.permission();self.assertEqual(self.refresh(steamid='other').status_code,422);self.refresh();first=self.owner()
        self.client.cookies.clear();self.sign_in('76561198000000002')
        self.assertFalse(self.state()['enabled']);self.assertEqual(self.state()['games'],[])
        self.permission();self.refresh();self.permission('no')
        self.assertEqual(self.state()['games'],[])
        self.assertEqual(self.app.state.store.library(first)['status'],'ok')
    def test_unavailable_expiry_and_cooldown(self):
        self.sign_in();self.permission();self.refresh()
        self.assertEqual(self.refresh().status_code,429);self.assertEqual(len(self.reader.calls),1)
        self.age();self.reader.status='unavailable';self.refresh()
        self.assertEqual(self.state()['status'],'unavailable');self.assertEqual(self.state()['games'],[])
        self.age();self.reader.status='ok';self.refresh()
        with self.app.state.store.db() as db:db.execute('UPDATE library_cache SET expires=1')
        self.assertEqual(self.state()['status'],'expired');self.assertEqual(self.state()['games'],[])
        with self.app.state.store.db() as db:self.assertIsNone(db.execute('SELECT payload FROM library_cache').fetchone()[0])
    def test_revoke_regrant_race_and_capacity(self):
        self.sign_in()
        with patch('remote_server.app.LIBRARY_ROWS_GLOBAL',0):self.assertEqual(self.permission().status_code,429)
        self.assertFalse(self.state()['enabled']);self.assertEqual(self.reader.calls,[])
        self.permission();csrf=self.csrf();self.reader.entered=threading.Event();self.reader.release=threading.Event()
        with ThreadPoolExecutor(2) as pool:
            req=pool.submit(self.client.post,'/account/library/refresh',data={'csrf':csrf},headers={'origin':ORIGIN})
            self.assertTrue(self.reader.entered.wait(5));self.permission('no');self.permission();self.reader.release.set()
            self.assertEqual(req.result().status_code,409)
        self.assertEqual(self.state()['status'],'not_requested');self.assertEqual(self.state()['games'],[])
    def test_all_access_revoke_clears_library(self):
        self.sign_in();self.permission();self.refresh()
        self.client.post('/account/revoke',data={'csrf':self.csrf()},headers={'origin':ORIGIN})
        self.assertFalse(self.state()['enabled']);self.assertEqual(self.refresh().status_code,403)

    def test_site_controls_use_real_routes_and_cache_only(self):
        self.sign_in();html=self.client.get('/').text
        self.assertIn('/account/library/permission',html)
        self.assertNotIn('/account/library/refresh',html)
        self.assertEqual(self.reader.calls,[])
        self.permission();html=self.client.get('/').text
        self.assertIn('/account/library/refresh',html)
        self.assertEqual(self.reader.calls,[])
        self.refresh();html=self.client.get('/').text
        self.assertIn('Baldur',html);self.assertIn('name="appid" value="1086940"',html)
        self.assertIn('/account/games/add',html)
        self.permission('no')
        self.assertFalse(self.state()['enabled'])
