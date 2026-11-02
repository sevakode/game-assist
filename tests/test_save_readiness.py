"""Synthetic permitted-save readiness over real local MCP/SQLite."""
import json
import unittest
from unittest.mock import patch
import test_mcp_game_identity as identity
import test_remote_service as service
from remote_server.connection_status import save_readiness


class SaveReadinessTests(unittest.TestCase):
    setUp = identity.GameIdentityTests.setUp
    sign_in = identity.GameIdentityTests.sign_in
    credentials = identity.GameIdentityTests.credentials
    rpc = identity.GameIdentityTests.rpc
    called = identity.GameIdentityTests.called
    csrf = identity.GameIdentityTests.csrf
    owner = identity.GameIdentityTests.owner
    catalog = identity.GameIdentityTests.catalog
    choose = identity.GameIdentityTests.choose
    permission = identity.GameIdentityTests.permission
    revoke = identity.GameIdentityTests.revoke

    def outputs(self, token):
        return [self.called(token, tool) for tool in ('get_progress', 'get_connection_status')]

    def submit(self, unknown=False):
        body = service.RemoteTests.observation(self)
        if unknown:
            for field in body['payload']['player_scalars'].values():
                field.update(status='unknown', value=None)
        response = self.client.post('/v1/browser/observations',
            json=body | {'csrf': self.csrf()}, headers={'origin': service.ORIGIN})
        self.assertEqual(response.status_code, 200)

    def test_absent_and_four_fields_remain_limited(self):
        self.choose([4231820], summary=True); token = self.credentials()
        for dto in self.outputs(token):
            self.assertEqual(dto['games'][0]['save_readiness']['state'], 'no_visible_save_summary')
            self.assertTrue(dto['guidance_policy']['ordinary_conversation_allowed'])
            self.assertTrue(dto['guidance_policy']['personalized_walkthrough_requires_save'])
        self.submit()
        outputs = self.outputs(token)
        self.assertEqual(outputs[0]['games'][0]['save_readiness'], outputs[1]['games'][0]['save_readiness'])
        for dto in outputs:
            r = dto['games'][0]['save_readiness']
            self.assertEqual(r['state'], 'limited_summary_available')
            self.assertEqual(r['known_scalar_count'], 4)
            self.assertEqual(r['source'], 'browser_manual')
            self.assertEqual(r['coverage'], 'four_raw_scalars_only')
            self.assertEqual(r['inventory_boss_map_coverage'], 'none')
            self.assertFalse(r['synchronized_walkthrough_ready'])
            self.assertFalse(r['item_specific_guidance_ready'])
            self.assertFalse(r['independently_verified'])
            self.assertIsNone(r['game_observed_at'])
            self.assertEqual(r['game_freshness'], 'unknown')

    def test_historical_receipt_never_becomes_game_freshness(self):
        self.choose([4231820], summary=True); token = self.credentials(); self.submit()
        with self.app.state.store.db() as db:
            db.execute('UPDATE observations_v2 SET observed=?', (1000000,))
        for clock, reason in ((1000300, 'receipt_age_known'),
                              (1086400, 'receipt_older_than_review_threshold'),
                              (999999, 'receipt_time_unknown')):
            with patch('remote_server.app.time.time', return_value=clock):
                progress, status = self.outputs(token)
            self.assertEqual(status['games'][0]['snapshots']['summary']['reason'], reason)
            for dto in (progress, status):
                r = dto['games'][0]['save_readiness']
                self.assertEqual(r['snapshot_basis'], 'reported_snapshot')
                self.assertIsNone(r['game_observed_at'])
                self.assertEqual(r['game_freshness'], 'unknown')
                self.assertFalse(r['synchronized_walkthrough_ready'])

    def test_unknown_scalars_and_unsupported_parser(self):
        self.choose([4231820, 1245620], summary=True); token = self.credentials()
        self.permission(1245620, scope='saves.metadata'); self.submit(unknown=True)
        for dto in self.outputs(token):
            rows = {game['appid']: game['save_readiness'] for game in dto['games']}
            self.assertEqual(rows[4231820]['state'], 'summary_fields_unknown')
            self.assertEqual(rows[4231820]['known_scalar_count'], 0)
            self.assertEqual(rows[1245620]['state'], 'unsupported_parser')
            self.assertEqual(rows[1245620]['coverage'], 'none')

    def test_revoked_summary_hidden_even_when_metadata_still_permitted(self):
        self.choose([4231820], summary=True); token = self.credentials(); self.submit()
        self.permission(4231820, scope='saves.metadata')
        self.permission(4231820, scope='saves.summary', enabled='no')
        for dto in self.outputs(token):
            r = dto['games'][0]['save_readiness']
            self.assertEqual(r['state'], 'no_visible_save_summary')
            self.assertEqual(r['known_scalar_count'], 0)
            self.assertEqual(r['source'], 'unknown')
        self.revoke(4231820)
        for dto in self.outputs(token):
            self.assertEqual(dto['games'], [])

    def test_cross_tenant_and_unselected_visibility_no_source_calls(self):
        self.choose([4231820], summary=True); first = self.credentials(); self.submit()
        self.client.cookies.clear(); self.sign_in('76561198000000002'); second = self.credentials()
        with (patch('remote_server.app.AchievementReader.get_unlocked', side_effect=AssertionError('fetch')),
              patch('remote_server.app.LibraryReader.get_games', side_effect=AssertionError('fetch'))):
            for dto in self.outputs(second):
                self.assertEqual(dto['games'], [])
                self.assertNotIn('browser_manual', json.dumps(dto))
            for dto in self.outputs(first):
                self.assertEqual(dto['games'][0]['save_readiness']['known_scalar_count'], 4)
        self.choose([4231820])
        for dto in self.outputs(second):
            self.assertEqual(dto['games'], [])

    def test_untrusted_extra_data_is_not_promoted_to_coverage(self):
        projection = {'summary_supported': True, 'summary': None,
                      'inventory': ['PRIVATE'], 'summary_source': 'UNTRUSTED'}
        r = save_readiness(projection)
        self.assertNotIn('PRIVATE', json.dumps(r))
        self.assertNotIn('UNTRUSTED', json.dumps(r))
        self.assertFalse(r['item_specific_guidance_ready'])

        projection.update(summary={'player_scalars': {
            'currentHealth': {'status': 'known', 'value': 1},
            'currentMana': {'status': 'unknown', 'value': None},
            'healthUpgradeFragmentCount': {'status': 'unknown', 'value': None},
            'manaUpgradeFragmentCount': {'status': 'unknown', 'value': None},
        }}, summary_source='device')
        r = save_readiness(projection)
        self.assertEqual(r['state'], 'limited_summary_available')
        self.assertEqual(r['known_scalar_count'], 1)
        self.assertEqual(r['source'], 'device')
        self.assertFalse(r['item_specific_guidance_ready'])
