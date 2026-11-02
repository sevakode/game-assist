import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from deck.client import Store, Runner, RePairRequired, main, status_report


class LocalStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.save = self.root / 'PRIVATE_SAVE'
        self.save.write_bytes(b'PRIVATE_CONTENT')
        self.store = Store(self.root / 'state')
        self.config = dict(appid=4231820, mode='metadata', path=str(self.save),
                           server='https://example.test', device_token='PRIVATE_TOKEN',
                           pairing_id='PRIVATE_GENERATION', expires_at=1000)
        self.store.write('config.json', self.config)
        self.transport = unittest.mock.Mock()
        self.transport.post.return_value = {'accepted': True}

    def report(self):
        with patch('deck.client.Transport.post', side_effect=AssertionError('No network')), \
             patch('deck.client.Store.write', side_effect=AssertionError('No writes')), \
             patch('deck.client.os.read', side_effect=AssertionError('No save contents')):
            result = status_report(self.store, now=100)
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn(str(self.root), json.dumps(result))
        return result

    def runner(self):
        return Runner(self.store, self.transport, self.config, now=lambda: 10)

    def test_local_observation_and_ack_are_separate(self):
        self.transport.post.side_effect = OSError('PRIVATE_NETWORK')
        runner = self.runner(); runner.tick(); runner.tick()
        result = self.report()
        self.assertEqual(result['last_local_observation_at'], 10)
        self.assertIsNone(result['last_server_ack_local_at'])
        self.assertTrue(result['pending_unsent_snapshot'])
        self.assertEqual(result['sync_status'], 'offline_or_rejected')
        self.transport.post.side_effect = None
        runner.retry_at = 0; runner.tick()
        result = self.report()
        self.assertEqual(result['last_server_ack_local_at'], 10)
        self.assertFalse(result['pending_unsent_snapshot'])
        self.assertEqual(result['watcher'], 'unknown')
        self.assertEqual(result['server_received_time'], 'unknown')
        self.assertEqual(result['source_observation_time'], 'unknown')

    def test_revocation_is_not_success(self):
        self.transport.post.side_effect = urllib.error.HTTPError('https://example.test', 403, 'PRIVATE', {}, None)
        runner = self.runner(); runner.tick()
        with self.assertRaises(RePairRequired): runner.tick()
        result = self.report()
        self.assertEqual(result['pairing'], 'reauthorization_required')
        self.assertTrue(result['pending_unsent_snapshot'])
        self.assertIsNone(result['last_server_ack_local_at'])

    def test_stale_and_missing_file_do_not_claim_current_parse(self):
        runner = self.runner(); runner.tick(); runner.tick()
        self.assertEqual(self.report()['snapshot'], 'matches_file_metadata')
        self.save.write_bytes(b'PRIVATE_DIFFERENT_SIZE')
        self.assertEqual(self.report()['snapshot'], 'stale_or_not_observed')
        self.save.unlink()
        with self.assertRaises(Exception): runner.tick()
        result = self.report()
        self.assertEqual(result['selected_file'], 'missing_unsafe_or_unreadable')
        self.assertEqual(result['parse'], 'error')
        self.assertEqual(result['last_server_ack_local_at'], 10)

    def test_unsupported_summary_remains_distinct_from_metadata(self):
        self.config['mode'] = 'belmont-summary'
        self.store.write('config.json', self.config)
        runner = self.runner(); runner.tick()
        with self.assertRaises(Exception): runner.tick()
        result = self.report()
        self.assertEqual(result['parse'], 'unsupported_or_error')
        self.assertIsNone(result['last_server_ack_local_at'])
        self.transport.post.assert_not_called()

    def test_supported_parse_is_historical_after_file_changes(self):
        self.config['mode'] = 'belmont-summary'
        self.store.write('config.json', self.config)
        self.save.write_text(json.dumps({'version': '1.1.3', 'playerSave': {
            'currentHealth': 42, 'currentMana': 10,
            'healthUpgradeFragmentCount': 1, 'manaUpgradeFragmentCount': 2}}))
        runner = self.runner(); runner.tick(); runner.tick()
        self.assertEqual(self.report()['parse'], 'supported_four_raw_fields')
        self.save.write_bytes(b'PRIVATE_NEW_UNPARSED')
        result = self.report()
        self.assertEqual(result['parse'], 'previous_supported_current_unknown')
        self.assertEqual(result['last_server_ack_local_at'], 10)

    def test_stale_pairing_and_untrusted_fields_are_not_reported(self):
        state = dict(pairing_id='OTHER', sync_status='synced', synced_at=10, queue={'secret': 'PRIVATE'})
        self.store.write('state.json', state)
        self.assertEqual(self.report()['snapshot'], 'old_pairing_ignored')
        state.update(pairing_id=self.config['pairing_id'], mode='metadata', appid=4231820,
                     sync_status='PRIVATE', synced_at='PRIVATE', observed_at={'PRIVATE': 1},
                     observation_status='PRIVATE')
        self.store.write('state.json', state)
        result = self.report()
        self.assertEqual(result['sync_status'], 'not_synced')
        self.assertIsNone(result['last_server_ack_local_at'])

    def test_unpaired_command_does_not_create_state(self):
        missing = self.root / 'absent'
        with patch('deck.client.Store', side_effect=lambda **kw: Store(missing, **kw)), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['status']), 0)
        self.assertEqual(json.loads(output.getvalue())['pairing'], 'unpaired')
        self.assertFalse(missing.exists())

    def test_ack_state_write_failure_is_not_a_parse_failure_and_recovers(self):
        runner = self.runner(); runner.tick()
        real_write = self.store.write
        failed = False

        def fail_ack_once(name, value):
            nonlocal failed
            if value.get('sync_status') == 'synced' and not failed:
                failed = True
                raise OSError('PRIVATE_TRANSIENT_STATE_WRITE')
            return real_write(name, value)

        with patch.object(self.store, 'write', side_effect=fail_ack_once):
            with self.assertRaises(OSError): runner.tick()
        self.assertTrue(failed)
        self.transport.post.assert_called_once()
        self.assertNotIn('observation_error', runner.state)
        result = self.report()
        self.assertEqual(result['parse'], 'not_attempted_metadata_only')
        self.assertTrue(result['pending_unsent_snapshot'])
        self.assertIsNone(result['last_server_ack_local_at'])
        runner.tick()  # Unchanged file: no spurious persistent parse error.
        self.assertNotIn('observation_error', runner.state)
        self.assertEqual(self.report()['parse'], 'not_attempted_metadata_only')
        # Restart recovers the retained event; acknowledgement persistence succeeds.
        restarted = self.runner(); restarted.tick()
        result = self.report()
        self.assertEqual(result['parse'], 'not_attempted_metadata_only')
        self.assertEqual(result['last_server_ack_local_at'], 10)
        self.assertFalse(result['pending_unsent_snapshot'])

    def test_invalid_queue_is_not_a_parse_failure(self):
        runner = self.runner(); runner.tick(); runner.tick()
        runner.state['queue'] = {'event_id': 'invalid'}
        with self.assertRaises(ValueError): runner.tick()
        self.assertNotIn('observation_error', runner.state)
        self.assertEqual(self.report()['parse'], 'not_attempted_metadata_only')
