"""Generic metadata privacy and consent regressions; synthetic files/fake HTTP."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from deck.client import Runner, Store, pair, clean_metadata, selection, RePairRequired
from agent.watch import SnapshotError


class Transport:
    origin = 'https://example.test'

    def __init__(self):
        self.calls = []
        self.intent = None

    def post(self, route, value, token=None):
        self.calls.append((route, value, token))
        if route.endswith('/start'):
            self.intent = value
            return {'verification_uri': self.origin + '/devices/approve', 'user_code': 'SHORTCODE',
                    'device_code': 'PRIVATE_DEVICE', 'expires_in': 600, 'interval': 5}
        if route.endswith('/poll'):
            return {'status': 'approved', 'device_token': 'PRIVATE_CREDENTIAL', 'expires_in': 1000, **self.intent}
        return {'accepted': True}


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / 'PRIVATE_FILE.bin'
        self.path.write_bytes(b'PRIVATE_RAW_SAVE_CONTENTS_UNKNOWN_FORMAT')
        self.store = Store(self.root / 'state')
        self.transport = Transport()
        self.config = {'appid': 999999, 'mode': 'metadata', 'path': str(self.path),
                       'server': self.transport.origin, 'device_token': 'PRIVATE_CREDENTIAL'}

    def tearDown(self):
        self.tmp.cleanup()

    def test_unknown_game_metadata_never_reads_decodes_or_uploads_contents(self):
        before = self.path.read_bytes()
        runner = Runner(self.store, self.transport, self.config)
        with patch('deck.client.os.read', side_effect=AssertionError('No content reads')), \
             patch('deck.client.watch.snapshot', side_effect=AssertionError('No hashing')), \
             patch('deck.client.watch.belmont_summary', side_effect=AssertionError('No decoder')):
            runner.tick(); runner.tick()
        _, envelope, _ = self.transport.calls[0]
        self.assertEqual(envelope['appid'], 999999)
        self.assertEqual(envelope['kind'], 'save_metadata')
        self.assertEqual(envelope['payload'], {'size_bytes': len(before), 'modified_ns': self.path.stat().st_mtime_ns})
        self.assertNotIn('PRIVATE_', json.dumps(envelope))
        self.assertNotIn('sha256', json.dumps(envelope))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(runner.state['observation_status'], 'metadata_only_contents_and_progress_unknown')

    def test_strict_metadata_limits(self):
        for value in ({'size_bytes': True, 'modified_ns': 1}, {'size_bytes': -1, 'modified_ns': 1},
                      {'size_bytes': 2**30+1, 'modified_ns': 1}, {'size_bytes': 1, 'modified_ns': 2**63},
                      {'size_bytes': 1, 'modified_ns': -1}, {'size_bytes': 1, 'modified_ns': 1, 'name': 'secret'}):
            with self.assertRaises(ValueError):
                clean_metadata(value)
        self.assertEqual(clean_metadata({'size_bytes': 0, 'modified_ns': 0}), {'size_bytes': 0, 'modified_ns': 0})

    def test_unknown_game_summary_and_bad_appids_rejected(self):
        with self.assertRaises(ValueError):
            selection(999999, 'belmont-summary')
        for appid in (True, 0, -1, 2147483648):
            with self.assertRaises(ValueError):
                selection(appid, 'metadata')

    def test_metadata_pair_scope_binding_and_no_progress_claim(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            pair(self.store, self.transport, str(self.path), sleep=lambda _: None,
                 appid=999999, mode='metadata')
        self.assertEqual(self.transport.intent, {'appid': 999999, 'scopes': ['saves.metadata']})
        self.assertEqual(self.store.read('config.json')['mode'], 'metadata')
        self.assertIn('прогресс игры неизвестен', output.getvalue())
        self.assertNotIn('PRIVATE_', output.getvalue())

    def test_wrong_approved_game_or_scope_never_saved(self):
        original = self.transport.post
        def post(route, value, token=None):
            result = original(route, value, token)
            if route.endswith('/poll'):
                result['appid'] = 123
            return result
        self.transport.post = post
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            pair(self.store, self.transport, str(self.path), sleep=lambda _: None,
                 appid=999999, mode='metadata')
        self.assertEqual(self.store.read('config.json'), {})

    def test_replacement_requires_confirmation_before_any_network(self):
        self.store.write('config.json', dict(self.config, pairing_id='existing'))
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            pair(self.store, self.transport, str(self.path), appid=555, mode='metadata', ask=lambda _: 'no')
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(self.store.read('config.json')['appid'], 999999)

    def test_queue_cannot_change_game_or_mode(self):
        self.store.write('state.json', {'appid': 4231820, 'mode': 'belmont-summary',
            'queue': {'appid': 4231820, 'kind': 'save_summary', 'payload': 'PRIVATE_OLD'}})
        runner = Runner(self.store, self.transport, self.config)
        self.assertNotIn('queue', runner.state)
        self.config['pairing_id'] = 'same-generation'
        self.store.write('config.json', self.config)
        runner = Runner(self.store, self.transport, self.config)
        self.store.write('config.json', dict(self.config, appid=555))
        with self.assertRaises(RePairRequired):
            runner.tick()
        self.assertEqual(self.transport.calls, [])

    def test_unknown_version_summary_fails_without_metadata_fallback(self):
        runner = Runner(self.store, self.transport, dict(self.config, appid=4231820, mode='belmont-summary'))
        runner.tick()
        with self.assertRaises(SnapshotError):
            runner.tick()
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(runner.state['observation_status'], 'unsupported_or_invalid_or_unstable_summary_format')

    def test_unknown_game_setup_never_discovers_other_paths(self):
        from deck.setup import setup
        answers = iter([str(self.path), 'yes', 'no'])
        with patch('deck.setup.os.geteuid', return_value=1000), \
             patch('deck.setup.Path.home', return_value=self.root / 'uninstalled'), \
             patch('deck.discovery.discover', side_effect=AssertionError('No discovery for unknown game')), \
             patch('deck.setup.install'), patch('deck.setup.Store'), patch('deck.setup.Transport'), \
             patch('deck.setup.pair') as pairing, patch('deck.setup.subprocess.run'), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(setup('https://example.test', appid=999999, mode='metadata', ask=lambda _: next(answers)), 0)
            self.assertEqual(pairing.call_args.kwargs['appid'], 999999)
            self.assertEqual(pairing.call_args.kwargs['mode'], 'metadata')


if __name__ == '__main__':
    unittest.main()
