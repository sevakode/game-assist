import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from server.app import create_app

TOKEN = 'test-secret-' + 'a' * 32
FILE = {'name': 'save.dat', 'size': 10, 'sha256': 'a' * 64, 'modified_ns': 123}


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'test.db'
        self.client = TestClient(create_app(self.db, TOKEN))
        self.client.headers['Authorization'] = 'Bearer ' + TOKEN
        for appid in (1, 2):
            self.client.post('/v1/games', json={'appid': appid, 'name': f'Game {appid}'})

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def grant(self, scopes, appid=1):
        response = self.client.put(f'/v1/games/{appid}/permissions', json={'scopes': scopes})
        self.assertEqual(response.status_code, 200)

    def save(self, appid=1):
        return self.client.post('/v1/observations', json={'appid': appid, 'kind': 'save_metadata', 'payload': {'files': [FILE]}})

    def rpc(self, method, params=None):
        return self.client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}}).json()

    def test_auth_every_data_route(self):
        self.client.headers.pop('Authorization')
        for method, route, body in [('get', '/v1/games', None), ('get', '/v1/export', None), ('get', '/v1/games/1/progress', None), ('get', '/v1/games/1/permissions', None), ('get', '/v1/games/1/achievements', None), ('get', '/v1/games/1/save-status', None), ('delete', '/v1/games/1/data', None), ('put', '/v1/games/1/permissions', {'scopes': []}), ('post', '/v1/games', {'appid': 3, 'name': 'x'}), ('post', '/v1/observations', {'appid': 1, 'kind': 'save_metadata', 'payload': {'files': []}}), ('post', '/mcp', {})]:
            response = self.client.request(method, route, json=body)
            self.assertEqual(response.status_code, 401, route)
        self.assertEqual(self.client.get('/health').status_code, 200)

    def test_deny_default_and_cross_game(self):
        self.assertEqual(self.client.get('/v1/games').json(), {'games': []})
        self.assertEqual(self.save().status_code, 403)
        self.grant(['saves.metadata', 'library.read'])
        self.assertEqual(self.save().status_code, 200)
        self.assertEqual(self.save(2).status_code, 403)
        self.assertEqual(self.client.get('/v1/games/2/progress').status_code, 403)
        self.assertEqual(len(self.client.get('/v1/games').json()['games']), 1)

    def test_revocation_and_export_filter(self):
        self.grant(['saves.metadata', 'achievements.read', 'library.read'])
        self.save()
        self.client.post('/v1/observations', json={'appid': 1, 'kind': 'achievements', 'payload': {'achievements': [{'apiname': 'a', 'achieved': False}]}})
        self.grant(['achievements.read'])
        data = self.client.get('/v1/games/1/progress').json()
        self.assertNotIn('save_metadata', data['observations'])
        self.assertEqual(data['coverage']['save_metadata'], 'not_permitted')
        exported = self.client.get('/v1/export').json()['games'][0]
        self.assertNotIn('name', exported)
        self.assertNotIn('save_metadata', exported['observations'])
        self.grant([])
        self.assertEqual(self.client.get('/v1/export').json()['games'], [])
        self.assertEqual(self.client.get('/v1/games/1/progress').status_code, 403)

    def test_nested_watcher_metadata(self):
        self.grant(['saves.metadata'])
        response = self.client.post('/v1/observations', json={'appid': 1, 'kind': 'save_metadata', 'payload': {'files': [{**FILE, 'name': 'root-1/slot/save.bin'}]}})
        self.assertEqual(response.status_code, 200)
        for name in ('/absolute', 'slot/../secret', 'C:/save', 'slot\\save', 'bad\nname'):
            response = self.client.post('/v1/observations', json={'appid': 1, 'kind': 'save_metadata', 'payload': {'files': [{**FILE, 'name': name}]}})
            self.assertEqual(response.status_code, 422, name)

    def test_validation(self):
        self.grant(['saves.metadata', 'achievements.read'])
        bad = [ {'appid': 1, 'kind': 'save_decoded', 'payload': {}}, {'appid': True, 'kind': 'save_metadata', 'payload': {'files': []}}, {'appid': 1, 'kind': 'save_metadata', 'payload': {'files': [{**FILE, 'contents': 'secret'}]}}, {'appid': 1, 'kind': 'save_metadata', 'payload': {'files': [{**FILE, 'name': '../secret'}]}}, {'appid': 1, 'kind': 'achievements', 'payload': {'achievements': [{'apiname': 'x', 'achieved': 'yes'}]}}, {'appid': 1, 'kind': 'save_metadata', 'steamid': 'someone-else', 'payload': {'files': []}} ]
        for payload in bad:
            self.assertEqual(self.client.post('/v1/observations', json=payload).status_code, 422, payload)
        self.assertEqual(self.client.put('/v1/games/1/permissions', json={'scopes': ['saves.read']}).status_code, 422)
        self.assertEqual(self.client.get('/v1/games/-1/progress').status_code, 422)

    def test_metadata_is_not_completion_and_delete(self):
        self.grant(['saves.metadata'])
        self.save()
        data = self.client.get('/v1/games/1/progress').json()
        self.assertEqual(data['game_completion'], 'unknown')
        self.assertEqual(data['observations']['save_metadata']['data'], {'file_count': 1, 'total_bytes': 10, 'last_modified_ns': 123})
        self.assertEqual(self.client.delete('/v1/games/1/data').json()['deleted'], 1)
        self.assertEqual(self.client.get('/v1/games/1/save-status').json()['status'], 'unknown')

    def test_persistent_permissions(self):
        self.grant(['library.read'])
        other = TestClient(create_app(self.db, TOKEN))
        with other:
            self.assertEqual(len(other.get('/v1/games', headers={'Authorization': 'Bearer ' + TOKEN}).json()['games']), 1)

    def test_legacy_untyped_data_never_disclosed(self):
        self.grant(['achievements.read', 'saves.metadata'])
        with sqlite3.connect(self.db) as db:
            db.execute('INSERT INTO observations(steamid,appid,kind,payload,observed_at) VALUES (?,?,?,?,?)', ('local', 1, 'save_metadata', '{"secret":"unexpected"}', 1))
            db.execute('INSERT INTO observations(steamid,appid,kind,payload,observed_at) VALUES (?,?,?,?,?)', ('local', 1, 'save_decoded', '{"bosses":100}', 1))
        self.assertEqual(self.client.get('/v1/games/1/progress').json()['observations'], {})

    def test_mcp_read_only_and_permissions(self):
        self.assertEqual(self.rpc('initialize')['result']['protocolVersion'], '2025-03-26')
        listing = self.rpc('tools/list')['result']['tools']
        self.assertEqual(len(listing), 6)
        self.assertTrue(all(tool['annotations']['readOnlyHint'] for tool in listing))
        call = lambda name, appid=1: self.rpc('tools/call', {'name': name, 'arguments': {'appid': appid}})['result']
        self.assertTrue(call('get_progress')['isError'])
        self.grant(['saves.metadata'])
        self.save()
        self.assertFalse(call('get_progress')['isError'])
        self.assertTrue(call('get_progress', 2)['isError'])
        self.assertTrue(call('suggest_next_step')['isError'])
        self.grant(['saves.metadata', 'recommendations'])
        self.assertFalse(call('suggest_next_step')['isError'])
        self.grant([])
        self.assertTrue(call('get_save_status')['isError'])

    def test_mcp_transport(self):
        self.assertEqual(self.client.get('/mcp').status_code, 405)
        self.assertEqual(self.client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}, headers={'MCP-Protocol-Version': 'invalid'}).status_code, 400)
        response = self.client.post('/mcp', json={'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, b'')
        self.assertEqual(self.client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}, headers={'Origin': 'https://hostile.example'}).status_code, 403)

    def test_mcp_invalid_requests(self):
        self.assertEqual(self.client.post('/mcp', content='{').json()['error']['code'], -32700)
        self.assertEqual(self.client.post('/mcp', json=[]).json()['error']['code'], -32600)
        self.assertEqual(self.rpc('nonsense')['error']['code'], -32601)
        for arguments in ({'appid': True}, {'appid': -1}, {'appid': 1, 'extra': True}):
            self.assertEqual(self.rpc('tools/call', {'name': 'get_progress', 'arguments': arguments})['error']['code'], -32602)
        self.assertEqual(self.client.post('/mcp', json={'jsonrpc': '2.0', 'method': 'notifications/initialized'}).status_code, 202)

    def test_local_origin_boundary_and_no_cors(self):
        self.assertEqual(self.client.get('/health', headers={'Host': 'evil.example'}).status_code, 403)
        self.assertEqual(self.client.get('/health', headers={'Origin': 'https://evil.example'}).status_code, 403)
        response = self.client.get('/health')
        self.assertNotIn('access-control-allow-origin', response.headers)
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_spoiler_filter_all_views_and_assistance_modes(self):
        self.grant(['library.read', 'achievements.read', 'saves.metadata', 'recommendations'])
        locked_id, locked_name, save_name = 'SECRET_BOSS_ID', 'Secret future encounter', 'Secret-future-area.sav'
        payload = {'achievements': [{'apiname': locked_id, 'name': locked_name, 'achieved': False}, {'apiname': 'KNOWN', 'name': 'Already discovered', 'achieved': True}]}
        self.assertEqual(self.client.post('/v1/observations', json={'appid': 1, 'kind': 'achievements', 'payload': payload}).status_code, 200)
        self.assertEqual(self.client.post('/v1/observations', json={'appid': 1, 'kind': 'save_metadata', 'payload': {'files': [{**FILE, 'name': save_name}]}}).status_code, 200)
        for mode in ('minimal', 'standard', 'guided'):
            setting = self.client.put('/v1/games/1/settings', json={'assistance': mode})
            self.assertEqual(setting.json(), {'assistance': mode, 'spoiler_policy': 'strict', 'neutral_reminders': True})
            views = [self.client.get(path).json() for path in ('/v1/games/1/achievements', '/v1/games/1/save-status', '/v1/games/1/progress', '/v1/export')]
            for name in ('get_achievements', 'get_save_status', 'get_progress', 'suggest_next_step'):
                views.append(self.rpc('tools/call', {'name': name, 'arguments': {'appid': 1}}))
            for view in views:
                text = json.dumps(view)
                for secret in (locked_id, locked_name, save_name, FILE['sha256'], 'KNOWN'):
                    self.assertNotIn(secret, text)
                self.assertNotIn('locked_count', text)
                self.assertNotIn('total_achievements', text)
            achievements = views[0]['observation']['data']
            self.assertEqual(achievements, {'achievements': [{'name': 'Already discovered', 'achieved': True, 'unlock_time': None}]})
        with sqlite3.connect(self.db) as db:
            raw = db.execute("SELECT payload FROM observations WHERE kind='achievements'").fetchone()[0]
            self.assertIn(locked_id, raw)  # Keep the source locally, filter every disclosure.
        self.assertEqual(self.client.get('/v1/games/2/settings').json()['assistance'], 'standard')

    def test_settings_validation_and_auth(self):
        self.assertEqual(self.client.get('/v1/games/1/settings').json(), {'assistance': 'standard', 'spoiler_policy': 'strict', 'neutral_reminders': True})
        for data in ({'assistance': 'easy'}, {'assistance': 'guided', 'spoiler_policy': 'off'}):
            self.assertEqual(self.client.put('/v1/games/1/settings', json=data).status_code, 422)
        self.assertEqual(self.client.get('/v1/games/999/settings').status_code, 404)
        self.client.headers.pop('Authorization')
        self.assertEqual(self.client.get('/v1/games/1/settings').status_code, 401)
        self.assertEqual(self.client.put('/v1/games/1/settings', json={'assistance': 'guided'}).status_code, 401)

    def test_only_locked_rows_reveal_no_identifiers_or_total(self):
        self.grant(['achievements.read'])
        self.client.post('/v1/observations', json={'appid': 1, 'kind': 'achievements', 'payload': {'achievements': [{'apiname': 'HIDDEN', 'name': 'Secret', 'achieved': False}]}})
        data = self.client.get('/v1/games/1/achievements').json()['observation']['data']
        self.assertEqual(data, {'achievements': []})


    def test_reminders_policy_without_fabricated_trigger(self):
        self.grant(['saves.metadata', 'recommendations'])
        self.save()
        for enabled in (False, True):
            response = self.client.put('/v1/games/1/settings', json={'assistance': 'minimal', 'neutral_reminders': enabled})
            self.assertEqual(response.json()['neutral_reminders'], enabled)
            self.client.put('/v1/games/1/settings', json={'assistance': 'guided'})
            self.assertEqual(self.client.get('/v1/games/1/settings').json()['neutral_reminders'], enabled)
            result = self.rpc('tools/call', {'name': 'suggest_next_step', 'arguments': {'appid': 1}})['result']
            data = json.loads(result['content'][0]['text'])
            self.assertEqual(data['neutral_reminder'], {'enabled': enabled, 'status': 'no_verified_trigger', 'text': None})
        self.assertEqual(self.client.put('/v1/games/1/settings', json={'neutral_reminders': 'yes'}).status_code, 422)
        self.assertEqual(self.client.put('/v1/games/1/settings', json={'neutral_reminders': None}).status_code, 422)

    def test_storage_dedup_and_retention(self):
        self.grant(['saves.metadata'])
        for _ in range(3):
            self.assertEqual(self.save().status_code, 200)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM observations').fetchone()[0], 1)
        for size in range(30):
            self.assertEqual(self.client.post('/v1/observations', json={'appid': 1, 'kind': 'save_metadata', 'payload': {'files': [{**FILE, 'size': size}]}}).status_code, 200)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM observations').fetchone()[0], 10)
        self.assertEqual(self.client.get('/v1/games/1/save-status').json()['observation']['data']['total_bytes'], 29)
        self.grant([])
        self.assertEqual(self.client.get('/v1/games/1/save-status').status_code, 403)
        self.assertEqual(self.client.get('/v1/export').json()['games'], [])

    def test_request_body_size_bound(self):
        response = self.client.post('/mcp', content=b'x' * (2 * 1024 * 1024 + 1))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.rpc('ping')['result'], {})


    def summary_fixture(self):
        from decoders.belmont import decode_bytes, safe_summary
        return safe_summary(decode_bytes(json.dumps({'version': '1.1.3', 'playerSave': {'healthUpgradeFragmentCount': 2, 'manaUpgradeFragmentCount': 3, 'currentHealth': 4.5, 'currentMana': 6.5}}).encode()))

    def setup_summary_game(self):
        self.client.post('/v1/games', json={'appid': 4231820, 'name': 'Synthetic test game'})

    def post_summary(self, payload=None, appid=4231820, **extra):
        return self.client.post('/v1/observations', json={'appid': appid, 'kind': 'save_summary', 'payload': self.summary_fixture() if payload is None else payload, **extra})

    def test_summary_scope_is_separate_and_default_off(self):
        self.setup_summary_game()
        self.assertEqual(self.post_summary().status_code, 403)
        self.grant(['saves.metadata'], 4231820)
        self.assertEqual(self.post_summary().status_code, 403)
        self.assertEqual(self.client.get('/v1/games/4231820/save-summary').status_code, 403)
        self.grant(['saves.summary'], 4231820)
        self.assertEqual(self.post_summary().status_code, 200)
        result = self.client.get('/v1/games/4231820/save-summary').json()
        self.assertEqual(result['observation']['data'], self.summary_fixture())
        self.assertEqual(result['observation']['source'], 'local_reported_parser')
        self.assertEqual(result['observation']['verification'], 'reported_not_independently_verified')
        progress = self.client.get('/v1/games/4231820/progress').json()
        self.assertEqual(progress['coverage']['save_summary'], 'available')
        self.assertEqual(progress['game_completion'], 'unknown')
        self.assertEqual(self.client.get('/v1/games/4231820/save-status').status_code, 403)

    def test_summary_strict_allowlist(self):
        import copy
        self.setup_summary_game()
        self.grant(['saves.summary'], 4231820)
        fixture = self.summary_fixture()
        bad = []
        for field in ('world_id', 'entity_id', 'raw_save', 'collected_pickups', 'maxHealth'):
            bad.append({**fixture, field: 'SYNTHETIC_PRIVATE_MARKER'})
        item = copy.deepcopy(fixture); item['player_scalars']['maxHealth'] = {'status': 'known', 'value': 8}; bad.append(item)
        item = copy.deepcopy(fixture); item['semantic_caveats'] = ['currentHealth is maximum HP']; bad.append(item)
        item = copy.deepcopy(fixture); item['decoder_coverage']['collectible_semantics'] = 'verified'; bad.append(item)
        item = copy.deepcopy(fixture); item['format_version'] = 'unknown'; bad.append(item)
        for payload in bad:
            response = self.post_summary(payload)
            self.assertEqual(response.status_code, 422)
            self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', response.text)
        self.assertEqual(self.post_summary(source='verified').status_code, 422)
        self.assertEqual(self.post_summary(appid=1).status_code, 422)

    def test_summary_scalar_validation(self):
        import copy
        self.setup_summary_game()
        self.grant(['saves.summary'], 4231820)
        for value in (True, -1, '4', 2**53 + 1):
            payload = copy.deepcopy(self.summary_fixture())
            payload['player_scalars']['currentHealth']['value'] = value
            self.assertEqual(self.post_summary(payload).status_code, 422)
        for scalar in ({'status': 'known', 'value': None}, {'status': 'unknown', 'value': 1}, {'status': 'missing', 'value': 0}):
            payload = copy.deepcopy(self.summary_fixture())
            payload['player_scalars']['currentHealth'] = scalar
            self.assertEqual(self.post_summary(payload).status_code, 422)
        payload = copy.deepcopy(self.summary_fixture())
        payload['player_scalars']['healthUpgradeFragmentCount']['value'] = 1.5
        self.assertEqual(self.post_summary(payload).status_code, 422)
        payload['player_scalars']['healthUpgradeFragmentCount'] = {'status': 'missing', 'value': None}
        self.assertEqual(self.post_summary(payload).status_code, 200)

    def test_summary_export_mcp_revocation_and_dedup(self):
        self.setup_summary_game()
        self.grant(['saves.summary'], 4231820)
        self.post_summary(); self.post_summary()
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM observations WHERE kind='save_summary'").fetchone()[0], 1)
        self.assertIn('save_summary', self.client.get('/v1/export').text)
        for name in ('get_save_summary', 'get_progress'):
            result = self.rpc('tools/call', {'name': name, 'arguments': {'appid': 4231820}})['result']
            self.assertFalse(result['isError'])
            self.assertIn('currentHealth', result['content'][0]['text'])
        self.grant(['saves.metadata'], 4231820)
        self.assertNotIn('currentHealth', self.client.get('/v1/export').text)
        self.assertNotIn('currentHealth', self.client.get('/v1/games/4231820/progress').text)
        result = self.rpc('tools/call', {'name': 'get_save_summary', 'arguments': {'appid': 4231820}})['result']
        self.assertTrue(result['isError'])
        self.client.headers.pop('Authorization')
        self.assertEqual(self.client.get('/v1/games/4231820/save-summary').status_code, 401)


class FakeSteam:
    configured = True

    def __init__(self):
        self.before_fetch = lambda: None
        self.before_verify = lambda: None

    def login_url(self, return_to):
        self.return_to = return_to
        return 'https://steamcommunity.com/openid/login?return_to=redacted'

    def verify_callback(self, params, expected_return_to):
        self.before_verify()
        assert expected_return_to == self.return_to
        return '76561198000000000'

    def get_achievements(self, steamid, appid):
        self.before_fetch()
        return {'status': 'ok', 'achievements': [{'apiname': 'A', 'name': 'A', 'achieved': True, 'unlock_time': 1}]}


class SteamRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.steam = FakeSteam()
        self.client = TestClient(create_app(Path(self.temp.name) / 'db', TOKEN, steam_service=self.steam))
        self.client.headers['Authorization'] = 'Bearer ' + TOKEN
        self.client.post('/v1/games', json={'appid': 1, 'name': 'Game'})
        self.client.put('/v1/games/1/permissions', json={'scopes': ['achievements.read']})

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def start(self):
        response = self.client.post('/v1/steam/login')
        self.assertEqual(response.status_code, 200)
        self.assertIn('HttpOnly', response.headers['set-cookie'])
        self.assertIn('SameSite=lax', response.headers['set-cookie'])
        self.assertNotIn(TOKEN, response.text)
        return self.steam.return_to

    def link(self):
        url = self.start()
        response = self.client.get(url + '&openid.mode=id_res', follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        return url

    def test_link_sync_provenance_and_unlink(self):
        self.link()
        self.assertTrue(self.client.get('/v1/steam/status').json()['linked'])
        self.assertEqual(self.client.post('/v1/games/1/steam-sync').json()['unlocked_count'], 1)
        data = self.client.get('/v1/games/1/achievements').json()
        self.assertEqual(data['observation']['source'], 'steam_web_api')
        self.client.post('/v1/steam/unlink')
        self.assertFalse(self.client.get('/v1/steam/status').json()['linked'])
        self.assertEqual(self.client.get('/v1/games/1/achievements').json()['status'], 'unknown')

    def test_state_mismatch_replay_and_cancel(self):
        url = self.start()
        self.assertEqual(self.client.get(url.replace('state=', 'state=bad'), follow_redirects=False).status_code, 400)
        response = self.client.get(url + '&openid.mode=cancel', follow_redirects=False)
        self.assertEqual(response.headers['location'], '/?steam=canceled')
        self.assertEqual(self.client.get(url + '&openid.mode=id_res', follow_redirects=False).status_code, 400)
        self.assertFalse(self.client.get('/v1/steam/status').json()['linked'])

    def test_missing_browser_cookie(self):
        url = self.start()
        self.client.cookies.clear()
        self.assertEqual(self.client.get(url + '&openid.mode=id_res', follow_redirects=False).status_code, 400)

    def test_revocation_during_fetch(self):
        self.link()
        self.steam.before_fetch = lambda: self.client.put('/v1/games/1/permissions', json={'scopes': []})
        self.assertEqual(self.client.post('/v1/games/1/steam-sync').status_code, 403)
        self.client.put('/v1/games/1/permissions', json={'scopes': ['achievements.read']})
        self.assertEqual(self.client.get('/v1/games/1/achievements').json()['status'], 'unknown')

    def test_unlink_during_verify_or_fetch(self):
        url = self.start()
        self.steam.before_verify = lambda: self.client.post('/v1/steam/unlink')
        self.assertEqual(self.client.get(url + '&openid.mode=id_res', follow_redirects=False).status_code, 400)
        self.steam.before_verify = lambda: None
        self.link()
        self.steam.before_fetch = lambda: self.client.post('/v1/steam/unlink')
        self.assertEqual(self.client.post('/v1/games/1/steam-sync').status_code, 409)
        self.assertEqual(self.client.get('/v1/games/1/achievements').json()['status'], 'unknown')

    def test_no_scope_no_network_and_auth(self):
        self.steam.before_fetch = lambda: self.fail('No network without permission')
        self.assertEqual(self.client.post('/v1/games/1/steam-sync').status_code, 409)
        self.client.put('/v1/games/1/permissions', json={'scopes': []})
        self.assertEqual(self.client.post('/v1/games/1/steam-sync').status_code, 403)
        self.client.headers.pop('Authorization')
        for method, route in [('get', '/v1/steam/status'), ('post', '/v1/steam/login'), ('post', '/v1/steam/unlink'), ('post', '/v1/games/1/steam-sync')]:
            self.assertEqual(self.client.request(method, route).status_code, 401)


if __name__ == '__main__':
    unittest.main()
