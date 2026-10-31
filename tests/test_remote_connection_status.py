"""Synthetic MCP onboarding contracts: no Steam/AI clients or network calls."""
import copy
import json
import unittest
from unittest.mock import patch

from remote_server.connection_status import connection_status, receipt
import test_remote_games as games
import test_remote_service as service


class ConnectionStatusTests(unittest.TestCase):
    setUp = service.RemoteTests.setUp
    tearDown = service.RemoteTests.tearDown
    sign_in = service.RemoteTests.sign_in
    csrf = service.RemoteTests.csrf
    oauth = service.RemoteTests.oauth
    mcp = service.RemoteTests.mcp
    observation = service.RemoteTests.observation
    owner = games.GameSelectionTests.owner
    catalog = games.GameSelectionTests.catalog
    choose = games.GameSelectionTests.choose
    permission = games.GameSelectionTests.permission
    revoke = games.GameSelectionTests.revoke

    def status(self, token):
        response = self.mcp(token, 'tools/call', {'name':'get_connection_status','arguments':{}})
        self.assertEqual(response.status_code,200,response.text)
        result = response.json()['result']
        self.assertFalse(result.get('isError'),result)
        return json.loads(result['content'][0]['text'])

    def submit(self, body=None):
        return self.client.post('/v1/browser/observations',
            json=(body or self.observation()) | {'csrf':self.csrf()},
            headers={'origin':service.ORIGIN})

    def test_empty_selected_unpermitted_and_revoke_are_indistinguishable(self):
        self.sign_in(); token=self.oauth()
        empty=self.status(token)
        self.assertEqual(empty['reasons'],['no_authorized_games_visible'])
        self.assertEqual(empty['actions'],['review_game_selection_and_permissions'])
        self.choose([4231820,1245620])
        self.assertEqual(self.status(token),empty)
        self.choose([4231820,1245620],summary=True)
        pending=self.status(token)['games']
        self.assertEqual([game['appid'] for game in pending],[4231820])
        self.assertEqual(pending[0]['reasons'],['no_visible_save_snapshot'])
        self.assertIn('review_manual_import',pending[0]['actions'])
        self.assertEqual(self.submit().status_code,200)
        self.assertIn('summary_snapshot_available',self.status(token)['games'][0]['reasons'])
        self.revoke(4231820)
        self.assertEqual(self.status(token),empty)
        response=self.client.post('/account/revoke',data={'csrf':self.csrf()},headers={'origin':service.ORIGIN})
        self.assertEqual(response.status_code,303)
        self.assertEqual(self.mcp(token,'tools/call',{'name':'get_connection_status','arguments':{}}).status_code,401)

    def test_receipt_age_unknown_fields_and_source_not_liveness(self):
        self.sign_in();self.choose([4231820],summary=True);token=self.oauth()
        body=self.observation()
        body['payload']['player_scalars']['currentHealth']={'status':'unknown','value':None}
        self.assertEqual(self.submit(body).status_code,200)
        with self.app.state.store.db() as db:
            db.execute('UPDATE observations_v2 SET observed=?',(1000000,))
        with patch('remote_server.app.time.time',return_value=1000300):
            # Tokens minted at actual time remain valid; receipt clock is synthetic.
            current=self.status(token)
        snapshot=current['games'][0]['snapshots']['summary']
        self.assertEqual(snapshot,{'source':'browser_manual','received_at':1000000,
            'received_age_seconds':300,'reason':'receipt_age_known'})
        self.assertIn('summary_fields_unknown',current['games'][0]['reasons'])
        with patch('remote_server.app.time.time',return_value=1086400):
            old=self.status(token)
        self.assertEqual(old['games'][0]['snapshots']['summary']['received_age_seconds'],86400)
        self.assertEqual(old['games'][0]['snapshots']['summary']['reason'],'receipt_older_than_review_threshold')
        self.assertEqual(old['observation_time'],'unknown')
        self.assertEqual(old['capabilities']['device_connection'],'unknown')
        self.assertNotIn('offline',json.dumps(old))
        self.assertNotIn('currentHealth',json.dumps(old))
        with patch('remote_server.app.time.time',return_value=999999):
            unknown=self.status(token)
        self.assertEqual(unknown['games'][0]['snapshots']['summary']['reason'],'receipt_time_unknown')

    def test_metadata_only_decoder_unavailable_and_key_absent(self):
        self.app.state.store.achievements_available=False
        self.sign_in();self.choose([1245620])
        self.assertEqual(self.permission(1245620,scope='saves.metadata').status_code,303)
        token=self.oauth()
        status=self.status(token)
        self.assertEqual(status['capabilities']['steam_achievements'],'operator_source_not_configured')
        self.assertEqual(status['capabilities']['steam_cloud'],'source_not_connected')
        self.assertIn('summary_decoder_unavailable',status['games'][0]['reasons'])
        self.assertNotIn('review_manual_import',status['games'][0]['actions'])
        owner=self.owner()
        with self.app.state.store.db() as db:
            db.execute('INSERT INTO observations_v2 VALUES(?,?,?,?,?,?)',
                (owner,1245620,'save_metadata',json.dumps({'size_bytes':123,'modified_ns':456}),1000000,'device'))
        status=self.status(token)
        self.assertIn('metadata_is_not_game_progress',status['games'][0]['reasons'])
        self.assertEqual(status['games'][0]['snapshots']['metadata']['source'],'device')
        self.assertNotIn('size_bytes',json.dumps(status))

    def test_diagnostics_do_not_call_sources_or_read_private_library(self):
        self.sign_in();token=self.oauth()
        with (patch('remote_server.app.AchievementReader.get_unlocked',side_effect=AssertionError('network')),
             patch('remote_server.app.LibraryReader.get_games',side_effect=AssertionError('network')),
             patch.object(self.app.state.store,'library',side_effect=AssertionError('private library'))):
            self.assertEqual(self.status(token)['games'],[])

    def test_subject_binding_annotations_and_no_new_scope(self):
        self.sign_in();self.choose([4231820],summary=True);self.submit();first=self.oauth()
        self.client.cookies.clear();self.sign_in('76561198000000002');second=self.oauth()
        self.assertEqual(self.status(second)['games'],[])
        self.assertEqual(len(self.status(first)['games']),1)
        response=self.mcp(second,'tools/call',{'name':'get_connection_status','arguments':{'owner':'76561198000000001','appid':4231820}})
        self.assertNotIn('summary_snapshot_available',response.text)
        listing=self.mcp(second,'tools/list').json()['result']['tools']
        tools={tool['name']:tool for tool in listing}
        self.assertTrue({'get_progress','suggest_next_step','get_connection_status'} <= tools.keys())
        tool=tools['get_connection_status']
        self.assertEqual(tool['inputSchema']['properties'],{})
        self.assertTrue(tool['annotations']['readOnlyHint'])
        self.assertFalse(tool['annotations']['destructiveHint'])
        self.assertFalse(tool['annotations']['openWorldHint'])
        with self.app.state.store.db() as db:
            rows=db.execute("SELECT hash,data FROM oauth_tokens WHERE kind='access'").fetchall()
            for row in rows:
                data=json.loads(row['data']);data['scopes']=[]
                db.execute('UPDATE oauth_tokens SET data=? WHERE hash=?',(json.dumps(data),row['hash']))
        self.assertEqual(self.mcp(second,'tools/call',{'name':'get_connection_status','arguments':{}}).status_code,403)

    def test_expired_achievement_read_does_not_mutate_or_expose_payload(self):
        self.sign_in();self.choose([1245620]);self.app.state.store.achievements_available=True
        owner=self.owner()
        with self.app.state.store.db() as db:
            db.execute('INSERT INTO grants VALUES(?,?,?)',(owner,1245620,'achievements.read'))
        # Synthetic expired cache; the diagnostic must not clear stored data.
        with self.app.state.store.db() as db:
            db.execute('INSERT INTO achievement_cache(owner,appid,status,payload,received_at,expires,attempted_at,consent_id) VALUES(?,?,?,?,?,?,?,?)',
                (owner,1245620,'ok',json.dumps([{'name':'PRIVATE_SENTINEL'}]),100,200,100,'synthetic'))
        token=self.oauth()
        with self.app.state.store.db() as db:
            before=tuple(db.execute('SELECT * FROM achievement_cache').fetchone())
        status=self.status(token)
        self.assertEqual(status['games'][0]['achievements']['status'],'expired')
        self.assertNotIn('PRIVATE_SENTINEL',json.dumps(status))
        with self.app.state.store.db() as db:
            self.assertEqual(tuple(db.execute('SELECT * FROM achievement_cache').fetchone()),before)


class ConnectionStatusProjectionTests(unittest.TestCase):
    def test_receipt_unknown_and_future_do_not_claim_freshness(self):
        for value in (None,True,'100',-1,float('nan'),float('inf'),101):
            with self.subTest(value=value):
                self.assertEqual(receipt(value,100),{'received_at':None,
                    'received_age_seconds':None,'reason':'receipt_time_unknown'})

    def test_fixed_output_ignores_noncontract_private_fields(self):
        projection={'games':[], 'owned_library':['PRIVATE_LIBRARY'], 'steamid':'PRIVATE_ID'}
        before=copy.deepcopy(projection)
        output=connection_status(projection,'https://configured.example',achievements_available=False,now=100)
        self.assertEqual(projection,before)
        self.assertNotIn('PRIVATE',json.dumps(output))
        self.assertEqual(output['links'],{'games':'https://configured.example/games',
            'import':'https://configured.example/import','setup':'https://configured.example/setup',
            'claude':'https://configured.example/connect/claude'})
