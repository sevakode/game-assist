"""Universal registration and generic metadata never imply universal parsing."""
from concurrent.futures import ThreadPoolExecutor
import json
import unittest
from uuid import uuid4

from remote_server.app import APPID,MAX_GAMES
import test_remote_games as game_tests
import test_remote_service as service_tests


class UniversalGameTests(unittest.TestCase):
    setUp=game_tests.GameSelectionTests.setUp
    tearDown=game_tests.GameSelectionTests.tearDown
    sign_in=game_tests.GameSelectionTests.sign_in
    csrf=game_tests.GameSelectionTests.csrf
    pair=game_tests.GameSelectionTests.pair
    observation=game_tests.GameSelectionTests.observation
    owner=game_tests.GameSelectionTests.owner
    choose=game_tests.GameSelectionTests.choose
    catalog=game_tests.GameSelectionTests.catalog
    selected=game_tests.GameSelectionTests.selected
    permission=game_tests.GameSelectionTests.permission
    revoke=game_tests.GameSelectionTests.revoke
    oauth=game_tests.GameSelectionTests.oauth
    mcp=game_tests.GameSelectionTests.mcp

    def add(self,appid,label='',**extra):
        return self.client.post('/account/games/add',data={'csrf':self.csrf(),'appid':str(appid),'label':label,**extra},headers={'origin':service_tests.ORIGIN})

    def metadata_pair(self,appid):
        response=self.client.post('/v1/devices/pair/start',json={'appid':appid,'scopes':['saves.metadata']})
        self.assertEqual(response.status_code,200,response.text);pair=response.json()
        response=self.client.post('/devices/approve',data={'csrf':self.csrf(),'user_code':pair['user_code'],'appid':str(appid),'saves.metadata':'yes'},headers={'origin':service_tests.ORIGIN})
        self.assertEqual(response.status_code,200,response.text)
        result=self.client.post('/v1/devices/pair/poll',json={'device_code':pair['device_code']}).json()
        self.assertEqual(result['appid'],appid);self.assertEqual(result['scopes'],['saves.metadata'])
        return result['device_token']

    def metadata(self,token,appid,payload=None,event=None):
        return self.client.post('/v1/device/observations',json={'appid':appid,'kind':'save_metadata','event_id':event or str(uuid4()),'payload':payload if payload is not None else {'size_bytes':123,'modified_ns':123456789}},headers={'authorization':'Bearer '+token})

    def test_arbitrary_game_label_is_unverified_private_and_escaped(self):
        self.sign_in();self.assertEqual(self.add(999999,'<script>UNVERIFIED</script>').status_code,303)
        custom=next(g for g in self.catalog() if g['appid']==999999)
        self.assertTrue(custom['user_label_unverified']);self.assertFalse(custom['summary_supported'])
        self.assertTrue(custom['metadata_supported']);self.assertEqual(custom['authorized_scopes'],[])
        home=self.client.get('/').text
        self.assertIn('&lt;script&gt;UNVERIFIED&lt;/script&gt;',home);self.assertNotIn('<script>UNVERIFIED',home)
        self.choose([999999]);self.assertEqual(self.client.get('/?game=999999').status_code,200)
        self.assertEqual(self.permission(999999).status_code,422)
        first=self.owner();self.client.cookies.clear();self.sign_in('76561198000000002')
        self.assertNotIn(999999,{g['appid'] for g in self.catalog()})
        self.assertEqual(self.revoke(999999).status_code,404)
        self.assertIn(999999,{g['appid'] for g in self.app.state.store.catalog(first)})

    def test_invalid_ids_labels_csrf_and_cap_atomic(self):
        self.sign_in()
        for invalid in ('0','-1','01','+3','1.0','2147483648','true'):
            self.assertEqual(self.add(invalid).status_code,422)
        for label in ('x'*121,'bad\nline'):
            self.assertEqual(self.add(999999,label).status_code,422)
        self.assertEqual(self.add(999999,csrf='bad').status_code,403)
        self.assertEqual(self.add(999999,owner='other').status_code,422)
        owner=self.owner()
        with self.app.state.store.db() as db:
            for appid in range(100000,100096):db.execute('INSERT INTO game_registrations VALUES(?,?,?,?)',(owner,appid,'synthetic',0))
        csrf=self.csrf()
        def add(appid):return self.client.post('/account/games/add',data={'csrf':csrf,'appid':str(appid),'label':''},headers={'origin':service_tests.ORIGIN})
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(add,(999998,999999)))
        self.assertEqual(sorted(r.status_code for r in results),[303,429]);self.assertEqual(len(self.catalog()),MAX_GAMES)

    def test_review_snapshot_rejects_new_games_and_never_auto_grants(self):
        self.sign_in();self.add(999999,'One')
        old=self.app.state.store.catalog_revision(self.owner(),self.catalog())
        review=self.choose(action='review_all');self.assertEqual(review.status_code,200)
        self.assertIn('game_999999',review.text)
        self.add(888888,'Two')
        self.assertEqual(self.choose([4231820,1245620,292030,999999],catalog_revision=old).status_code,409)
        self.choose([4231820,1245620,292030,999999])
        self.assertNotIn(888888,self.selected())
        self.assertTrue(all(not g['authorized_scopes'] for g in self.catalog()))

    def test_metadata_ingest_projection_privacy_and_kind_binding(self):
        self.sign_in();self.add(999999,'Unknown game');token=self.metadata_pair(999999)
        event=str(uuid4());self.assertEqual(self.metadata(token,999999,event=event).status_code,200)
        self.assertTrue(self.metadata(token,999999,event=event).json()['duplicate'])
        self.assertEqual(self.metadata(token,999999,{'size_bytes':124,'modified_ns':123456789},event).status_code,409)
        projection=self.app.state.store.projection(self.owner())
        self.assertEqual(projection['games'][0]['metadata'],{'size_bytes':123,'modified_ns':123456789})
        self.assertIsNone(projection['games'][0]['summary']);self.assertEqual(projection['games'][0]['status'],'metadata_only_not_game_progress')
        self.assertEqual(self.metadata(token,1245620).status_code,403)
        body=self.observation();body['appid']=999999
        self.assertEqual(self.client.post('/v1/device/observations',json=body,headers={'authorization':'Bearer '+token}).status_code,422)
        for extra in ('filename','path','sha256','raw_save','steamid'):
            self.assertEqual(self.metadata(token,999999,{'size_bytes':1,'modified_ns':1,extra:'SYNTHETIC_SECRET'}).status_code,422)
        for payload in ({'size_bytes':True,'modified_ns':1},{'size_bytes':2**30+1,'modified_ns':1},{'size_bytes':1,'modified_ns':2**63},{'size_bytes':-1,'modified_ns':1}):
            self.assertEqual(self.metadata(token,999999,payload).status_code,422)
        response=self.mcp(self.oauth(),'tools/call',{'name':'get_progress','arguments':{}})
        self.assertIn('size_bytes',response.text)
        self.assertNotIn('SYNTHETIC_SECRET',response.text);self.assertNotIn('76561198000000001',response.text)

    def test_pairing_intent_cannot_be_changed_in_browser(self):
        self.sign_in()
        pair=self.client.post('/v1/devices/pair/start',json={'appid':1245620,'scopes':['saves.metadata']}).json()
        for appid,scope in ((APPID,'saves.metadata'),(1245620,'saves.summary')):
            response=self.client.post('/devices/approve',data={'csrf':self.csrf(),'user_code':pair['user_code'],'appid':str(appid),scope:'yes'},headers={'origin':service_tests.ORIGIN})
            self.assertEqual(response.status_code,422)
        for body in ({'appid':True,'scopes':['saves.metadata']},{'appid':999999,'scopes':['saves.summary']},{'appid':1,'scopes':['saves.metadata','saves.metadata']}):
            self.assertEqual(self.client.post('/v1/devices/pair/start',json=body).status_code,422)

    def test_per_game_and_per_kind_revoke_preserve_other_data(self):
        self.sign_in();summary=self.pair();meta=self.metadata_pair(APPID);elden=self.metadata_pair(1245620)
        self.client.post('/v1/device/observations',json=self.observation(),headers={'authorization':'Bearer '+summary})
        self.metadata(meta,APPID);self.metadata(elden,1245620)
        self.assertEqual(self.permission(APPID,enabled='no').status_code,303)
        games={g['appid']:g for g in self.app.state.store.projection(self.owner())['games']}
        self.assertIsNone(games[APPID]['summary']);self.assertIsNotNone(games[APPID]['metadata'])
        self.assertEqual(self.metadata(meta,APPID).status_code,200)
        self.assertEqual(self.revoke(APPID).status_code,303)
        self.assertEqual(self.metadata(meta,APPID).status_code,401)
        self.assertEqual(self.metadata(elden,1245620).status_code,200)
        self.choose([APPID,1245620],metadata_4231820='yes',metadata_1245620='yes')
        self.assertEqual(self.metadata(meta,APPID).status_code,401)
        games=self.app.state.store.projection(self.owner())['games']
        self.assertIsNotNone(next(g for g in games if g['appid']==1245620)['metadata'])

    def test_metadata_receipt_does_not_refresh_summary_timestamp(self):
        self.sign_in();summary=self.pair();meta=self.metadata_pair(APPID)
        self.client.post('/v1/device/observations',json=self.observation(),headers={'authorization':'Bearer '+summary})
        owner=self.owner()
        with self.app.state.store.db() as db:
            db.execute("UPDATE observations_v2 SET observed=1000 WHERE owner=? AND appid=? AND kind='save_summary'",(owner,APPID))
        self.metadata(meta,APPID)
        item=self.app.state.store.projection(owner)['games'][0]
        self.assertEqual(item['summary_received_at'],1000)
        self.assertGreater(item['metadata_received_at'],1000)
        self.assertEqual(item['received_at'],item['metadata_received_at'])

    def test_public_presets_are_not_owned_library_and_focus_works(self):
        public=self.client.get('/?game=1245620')
        self.assertEqual(public.status_code,200)
        self.assertIn('Elden Ring',public.text)
        self.assertEqual(self.client.get('/?game=999999').status_code,404)
        self.assertEqual(self.client.get('/?game=not-int').status_code,404)
