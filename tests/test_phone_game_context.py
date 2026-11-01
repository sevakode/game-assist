"""Phone-only synthetic SQLite/Steam transport/MCP contracts, no external I/O."""
import json
import tempfile
import unittest
from pathlib import Path

import httpx
from starlette.testclient import TestClient
from remote_server.app import Config, create_app
from remote_server.achievements import AchievementReader
from remote_server.library_reader import LibraryReader
from remote_server.connection_status import phone_context
import test_remote_service as service
import test_remote_games as games


class PhoneContextTests(unittest.TestCase):
    tearDown = service.RemoteTests.tearDown
    sign_in = service.RemoteTests.sign_in
    csrf = service.RemoteTests.csrf
    oauth = service.RemoteTests.oauth
    mcp = service.RemoteTests.mcp
    owner = games.GameSelectionTests.owner
    choose = games.GameSelectionTests.choose
    catalog = games.GameSelectionTests.catalog
    permission = games.GameSelectionTests.permission
    revoke = games.GameSelectionTests.revoke

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.steam = service.FakeSteam()
        self.requests = []
        def respond(request):
            self.requests.append(request.url.path)
            return httpx.Response(200, json={'playerstats': {
                'success': True, 'steamID': request.url.params['steamid'],
                'achievements': [
                    {'apiname': 'OPENED', 'name': 'Opened', 'achieved': 1, 'unlocktime': 123},
                    {'apiname': 'PRIVATE_FUTURE', 'name': 'SPOILER_SENTINEL', 'achieved': 0}]}})
        self.app = create_app(Config(service.ORIGIN, str(Path(self.temp.name)/'test.db'),
            (service.REDIRECT,)), self.steam,
            achievement_reader=AchievementReader(api_key='synthetic', transport=httpx.MockTransport(respond)),
            library_reader=LibraryReader(api_key=''))
        self.client = TestClient(self.app, base_url=service.ORIGIN, follow_redirects=False)
        self.client.__enter__()

    def call(self, token, name='get_connection_status'):
        response = self.mcp(token, 'tools/call', {'name': name, 'arguments': {}})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()['result']
        self.assertFalse(result.get('isError'), result)
        return json.loads(result['content'][0]['text'])

    def refresh(self, origin=service.ORIGIN, csrf=None):
        return self.client.post('/account/achievements/refresh',
            data={'appid': '1245620', 'csrf': self.csrf() if csrf is None else csrf},
            headers={'origin': origin})

    def test_phone_permission_refresh_mcp_revoke_and_other_owner(self):
        self.sign_in(); token = self.oauth()
        self.assertEqual(self.call(token)['phone_context']['games'], [])
        self.choose([1245620])
        self.assertEqual(self.call(token)['phone_context']['games'], [])
        self.assertEqual(self.permission(1245620, scope='achievements.read').status_code, 303)
        context = self.call(token)['phone_context']
        self.assertFalse(context['companion_required_for_conversation'])
        self.assertEqual(context['games'][0]['reason'], 'permission_only')
        self.assertEqual(self.requests, [])
        self.assertEqual(self.refresh(csrf='bad').status_code, 403)
        self.assertEqual(self.refresh(origin='null').status_code, 403)
        self.assertEqual(self.refresh(origin='https://other.example').status_code, 403)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.refresh().status_code, 303)
        progress = self.call(token, 'get_progress')
        self.assertEqual(progress['games'][0]['achievements']['items'][0]['name'], 'Opened')
        status = self.call(token)
        self.assertEqual(status['phone_context']['games'][0]['reason'], 'received')
        self.assertEqual(status['phone_context']['games'][0]['visible_unlocked_count'], 1)
        self.assertEqual(status['phone_context']['current_game_and_position'], 'unknown')
        self.assertNotIn('SPOILER_SENTINEL', json.dumps(progress) + json.dumps(status))
        self.assertNotIn('PRIVATE_FUTURE', json.dumps(progress) + json.dumps(status))
        self.assertEqual(len(self.requests), 1)
        self.client.cookies.clear(); self.sign_in('76561198000000002')
        other = self.oauth()
        self.assertEqual(self.call(other)['phone_context']['games'], [])
        self.assertEqual(self.call(token)['phone_context']['games'][0]['reason'], 'received')
        self.client.cookies.clear(); self.sign_in()
        self.assertEqual(self.revoke(1245620).status_code, 303)
        self.assertEqual(self.call(token)['phone_context']['games'], [])
        self.assertEqual(self.call(token, 'get_progress')['games'], [])
        self.assertEqual(len(self.requests), 1)

    def test_expired_cache_read_does_not_mutate_or_fetch(self):
        self.sign_in(); self.choose([1245620]); self.permission(1245620, scope='achievements.read')
        token = self.oauth(); self.refresh()
        with self.app.state.store.db() as db:
            db.execute('UPDATE achievement_cache SET expires=1')
            before = tuple(db.execute('SELECT * FROM achievement_cache').fetchone())
        item = self.call(token)['phone_context']['games'][0]
        self.assertEqual(item['reason'], 'expired')
        self.assertIsNone(item['visible_unlocked_count'])
        with self.app.state.store.db() as db:
            self.assertEqual(tuple(db.execute('SELECT * FROM achievement_cache').fetchone()), before)
        self.assertEqual(len(self.requests), 1)

    def test_fixed_states_and_no_unpermitted_fields(self):
        for status, expected in [('ok', 'received_empty'), ('not_requested', 'permission_only'),
                ('expired', 'expired'), ('unavailable', 'source_unavailable'),
                ('private', 'source_unavailable'), ('unexpected', 'unknown')]:
            projection = {'games': [{'appid': 42, 'private': 'SECRET', 'achievements':
                {'status': status, 'items': [], 'received_at': None}}], 'library': 'SECRET'}
            context = phone_context(projection, service.ORIGIN, achievements_available=True, now=100)
            item = context['games'][0]
            self.assertEqual(item['reason'], expected)
            self.assertEqual(item['url'], service.ORIGIN + '/games')
            self.assertEqual(item['receipt']['reason'], 'receipt_time_unknown')
            self.assertNotIn('SECRET', json.dumps(context))
        projection = {'games': [{'appid': 42}]}
        self.assertEqual(phone_context(projection, service.ORIGIN, achievements_available=True,
            now=100)['games'][0]['reason'], 'achievement_permission_not_visible')
        self.assertEqual(phone_context(projection, service.ORIGIN, achievements_available=False,
            now=100)['games'][0]['reason'], 'operator_source_not_configured')
