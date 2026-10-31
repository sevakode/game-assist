"""Only bounded explicit safe projections cross the browser/server boundary."""
from concurrent.futures import ThreadPoolExecutor
import unittest
from uuid import uuid4
from unittest.mock import patch
import test_remote_games as games
from test_remote_service import ORIGIN

class ManualImportTests(unittest.TestCase):
    setUp=games.GameSelectionTests.setUp
    tearDown=games.GameSelectionTests.tearDown
    sign_in=games.GameSelectionTests.sign_in
    csrf=games.GameSelectionTests.csrf
    owner=games.GameSelectionTests.owner
    choose=games.GameSelectionTests.choose
    catalog=games.GameSelectionTests.catalog
    observation=games.GameSelectionTests.observation
    pair=games.GameSelectionTests.pair
    revoke=games.GameSelectionTests.revoke

    def submit(self,data=None,origin=ORIGIN):
        data=data or self.observation()
        data.setdefault('csrf',self.csrf())
        return self.client.post('/v1/browser/observations',json=data,headers={'origin':origin})

    def test_permission_csrf_and_exact_schema(self):
        self.assertEqual(self.client.post('/v1/browser/observations',json={}).status_code,401)
        self.sign_in();self.assertEqual(self.submit().status_code,403)
        self.choose([4231820],summary=True)
        self.assertEqual(self.submit(origin='https://evil.test').status_code,403)
        data=self.observation()|{'csrf':'wrong'};self.assertEqual(self.submit(data).status_code,403)
        for extra in ({'owner':'other'},{'source':'device'},{'filename':'private.sav'},{'raw':'private'}):
            self.assertEqual(self.submit(self.observation()|extra).status_code,422)
        for appid in (1245620,292030,True):
            self.assertEqual(self.submit(self.observation()|{'appid':appid}).status_code,422)
        data=self.observation();data['payload']['extra']='raw';self.assertEqual(self.submit(data).status_code,422)
        self.assertEqual(self.client.post('/v1/browser/observations',content='x'*16385).status_code,413)

    def test_dedup_source_replacement_and_revoke(self):
        self.sign_in();token=self.pair();owner=self.owner()
        device=self.observation()
        self.assertEqual(self.client.post('/v1/device/observations',json=device,headers={'authorization':'Bearer '+token}).status_code,200)
        self.assertEqual(self.app.state.store.projection(owner)['games'][0]['summary_source'],'device')
        data=self.observation();first=self.submit(data);self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json()['source'],'browser_manual')
        before=self.app.state.store.projection(owner)['games'][0]
        self.assertTrue(self.submit(data).json()['duplicate'])
        self.assertEqual(self.app.state.store.projection(owner)['games'][0],before)
        changed=self.observation()|{'event_id':data['event_id']};changed['payload']['player_scalars']['currentHealth']['value']=7
        self.assertEqual(self.submit(changed).status_code,409)
        self.assertEqual(before['summary_source'],'browser_manual')
        device['event_id']=str(uuid4());self.client.post('/v1/device/observations',json=device,headers={'authorization':'Bearer '+token})
        self.assertEqual(self.app.state.store.projection(owner)['games'][0]['summary_source'],'device')
        self.revoke(4231820);self.assertEqual(self.submit(data).status_code,403)
        self.assertEqual(self.app.state.store.projection(owner)['games'],[])

    def test_owner_namespace_and_concurrent_duplicate(self):
        self.sign_in();self.choose([4231820],summary=True);first_owner=self.owner()
        data=self.observation()|{'csrf':self.csrf()}
        with ThreadPoolExecutor(2) as pool:responses=list(pool.map(lambda _:self.submit(dict(data)),range(2)))
        self.assertEqual(sorted(r.json()['duplicate'] for r in responses),[False,True])
        self.client.cookies.clear();self.sign_in('76561198000000002');self.choose([4231820],summary=True)
        self.assertIsNone(self.app.state.store.projection(self.owner())['games'][0]['summary'])
        data['csrf']=self.csrf();self.assertFalse(self.submit(data).json()['duplicate'])
        self.revoke(4231820)
        self.assertIsNotNone(self.app.state.store.projection(first_owner)['games'][0]['summary'])

    def test_identical_summary_does_not_notify_and_no_device_created(self):
        self.sign_in();self.choose([4231820],summary=True)
        self.client.post('/account/notifications',data={'csrf':self.csrf(),'appid':'4231820','enabled':'yes'},headers={'origin':ORIGIN})
        self.assertEqual(self.submit().status_code,200)
        self.assertEqual(self.submit().status_code,200)
        self.assertEqual(self.app.state.store.inbox(self.owner())['items'],[])
        data=self.observation();data['payload']['player_scalars']['healthUpgradeFragmentCount']['value']=9
        self.assertEqual(self.submit(data).status_code,200)
        self.assertEqual(len(self.app.state.store.inbox(self.owner())['items']),1)
        with self.app.state.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM devices').fetchone()[0],0)

    def test_revoke_race_and_transaction_rollback(self):
        self.sign_in();self.choose([4231820],summary=True);owner=self.owner()
        data=self.observation()|{'csrf':self.csrf()}
        with patch.object(self.app.state.store,'record_notification',side_effect=RuntimeError('synthetic rollback')):
            with self.assertRaises(RuntimeError):self.submit(dict(data))
        with self.app.state.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM observations_v2').fetchone()[0],0)
        csrf=self.csrf()
        def revoke():
            return self.client.post('/account/games/revoke',data={'csrf':csrf,'appid':'4231820'},headers={'origin':ORIGIN})
        with ThreadPoolExecutor(2) as pool:
            submitted=pool.submit(self.submit,dict(data));revoked=pool.submit(revoke)
            self.assertIn(submitted.result().status_code,(200,403));self.assertEqual(revoked.result().status_code,303)
        self.assertEqual(self.app.state.store.projection(owner)['games'],[])
        with self.app.state.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM observations_v2').fetchone()[0],0)

    def test_import_routes_are_authenticated_and_scripts_are_scoped(self):
        self.assertEqual(self.client.get('/import').status_code,401)
        self.sign_in()
        blocked=self.client.get('/import');self.assertEqual(blocked.status_code,200)
        self.choose([4231820],summary=True)
        page=self.client.get('/import');self.assertEqual(page.status_code,200)
        self.assertIn("script-src 'self'",page.headers['content-security-policy'])
        self.assertIn("connect-src 'self'",page.headers['content-security-policy'])
        self.assertNotIn('script-src',self.client.get('/').headers['content-security-policy'])
        for name in ('import.js','belmont-parser.js'):
            self.assertIn('/assets/'+name,page.text)
            asset=self.client.get('/assets/'+name)
            self.assertEqual(asset.status_code,200);self.assertIn('javascript',asset.headers['content-type'])
        self.assertEqual(self.client.get('/assets/other.js').status_code,404)
