"""Permitted public game identity and check-time DTO contracts; synthetic only."""
import json
import time
import unittest
from unittest.mock import patch
import test_mcp_tool_metadata as fixtures
import test_remote_games as games
import test_remote_service as service
from remote_server.games import DISCOVERY_TITLES


class GameIdentityTests(unittest.TestCase):
    setUp = fixtures.MCPToolMetadataTests.setUp
    sign_in = fixtures.MCPToolMetadataTests.sign_in
    credentials = fixtures.MCPToolMetadataTests.credentials
    rpc = fixtures.MCPToolMetadataTests.rpc
    called = fixtures.MCPToolMetadataTests.called
    csrf = service.RemoteTests.csrf
    owner = games.GameSelectionTests.owner
    catalog = games.GameSelectionTests.catalog
    choose = games.GameSelectionTests.choose
    permission = games.GameSelectionTests.permission
    revoke = games.GameSelectionTests.revoke

    def test_permitted_name_check_time_and_unknown_save_time(self):
        token = self.credentials()
        self.choose([4231820,1245620], summary=True)
        now = time.time()
        with patch('remote_server.app.time.time', return_value=now):
            progress = self.called(token, 'get_progress')
            status = self.called(token, 'get_connection_status')
        for dto in (progress, status):
            self.assertEqual(dto['checked_at'], now)
            self.assertEqual(len(dto['games']), 1)
            game = dto['games'][0]
            self.assertEqual(game['appid'], 4231820)
            self.assertEqual(game['name'], DISCOVERY_TITLES[4231820])
            self.assertEqual(game['name_source'], 'public_registry')
            self.assertNotIn('Elden Ring', json.dumps(dto))
        self.assertEqual(status['version'], 1)
        self.assertEqual(status['observation_time'], 'unknown')
        self.assertEqual(status['phone_context']['current_game_and_position'], 'unknown')
        self.assertEqual(progress['games'][0]['observation_time'], 'unknown')
        self.assertIsNone(progress['games'][0]['received_at'])
        self.assertIsNone(progress['games'][0]['summary_received_at'])
        self.assertIn('no_visible_save_snapshot', status['games'][0]['reasons'])
        self.revoke(4231820)
        for name in ('get_progress','get_connection_status'):
            self.assertEqual(self.called(token,name)['games'], [])
        self.client.cookies.clear(); self.sign_in('76561198000000002')
        other = self.credentials()
        self.assertEqual(self.called(other,'get_progress')['games'], [])

    def test_registry_wins_over_user_labels_and_unknown_remains_null(self):
        token = self.credentials()
        for appid in (1086940,987654321):
            response=self.client.post('/account/games/add',data={'csrf':self.csrf(),
                'appid':str(appid),'label':'UNTRUSTED_INSTRUCTION_SENTINEL'},headers={'origin':service.ORIGIN})
            self.assertEqual(response.status_code,303)
        self.choose([1086940,987654321])
        for appid in (1086940,987654321):
            self.assertEqual(self.permission(appid,scope='saves.metadata').status_code,303)
        for name in ('get_progress','get_connection_status'):
            dto=self.called(token,name)
            rows={g['appid']:g for g in dto['games']}
            self.assertEqual(rows[1086940]['name'], DISCOVERY_TITLES[1086940])
            self.assertEqual(rows[987654321]['name_source'],'unknown')
            self.assertIsNone(rows[987654321]['name'])
            self.assertNotIn('UNTRUSTED_INSTRUCTION_SENTINEL',json.dumps(dto))

    def test_check_time_advances_without_refreshing_snapshot(self):
        self.choose([4231820],summary=True); token=self.credentials()
        observation=service.RemoteTests.observation(self)
        response=self.client.post('/v1/browser/observations',json=observation|{'csrf':self.csrf()},headers={'origin':service.ORIGIN})
        self.assertEqual(response.status_code,200)
        first=self.called(token,'get_progress'); now=time.time()+10
        with patch('remote_server.app.time.time',return_value=now):
            second=self.called(token,'get_progress')
            status=self.called(token,'get_connection_status')
        self.assertGreater(second['checked_at'],first['checked_at'])
        self.assertEqual(second['games'],first['games'])
        self.assertEqual(status['games'][0]['snapshots']['summary']['received_at'],first['games'][0]['summary_received_at'])
        self.assertEqual(status['observation_time'],'unknown')
