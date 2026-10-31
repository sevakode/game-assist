"""Synthetic saves and fake HTTP only; no personal Steam data or installation."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from deck.client import Store, Transport, Runner, RePairRequired, clean_summary, pair, server_origin
from deck.install import unit_text, install, uninstall
from decoders import belmont


def fixture(health=42):
    return {'version': '1.1.3', 'playerSave': {'currentHealth': health},
            'worldSaves': {'m_keys': ['SECRET_WORLD'], 'm_values': [
                {'savableEntityStates': {'m_keys': ['SECRET_ENTITY'], 'm_values': ['True']}}]},
            'privateNoise': 'RAW_SECRET'}


class FakeTransport:
    origin = 'https://companion.example'

    def __init__(self):
        self.calls = []
        self.error = None

    def post(self, route, payload, token=None):
        self.calls.append((route, payload, token))
        if self.error:
            raise self.error
        if route.endswith('/start'):
            return {'verification_uri': self.origin + '/pair', 'user_code': 'ABCD-1234',
                    'device_code': 'PRIVATE_DEVICE_CODE', 'expires_in': 600, 'interval': 5}
        if route.endswith('/poll'):
            return {'status': 'approved', 'device_token': 'PRIVATE_TOKEN', 'expires_in': 1000}
        return {'accepted': True, 'duplicate': False}


class DeckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.save = self.root / 'save.json'
        self.save.write_text(json.dumps(fixture()))
        self.store = Store(self.root / 'state')
        self.transport = FakeTransport()
        self.config = {'server': self.transport.origin, 'path': str(self.save), 'device_token': 'PRIVATE_TOKEN'}

    def tearDown(self):
        self.tmp.cleanup()

    def test_https_origin_and_explicit_local_only(self):
        for origin in ('http://example.com', 'http://127.0.0.1', 'https://user:secret@example.com',
                       'https://example.com/path', 'https://example.com?q=1', 'https://example.com#frag'):
            with self.assertRaises(ValueError):
                server_origin(origin)
        self.assertEqual(server_origin('http://localhost:9999', True), 'http://127.0.0.1:9999')
        with self.assertRaises(ValueError):
            server_origin('http://example.com', True)

    def test_pair_only_private_credential(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            pair(self.store, self.transport, str(self.save), sleep=lambda _: None)
        self.assertNotIn('PRIVATE_', output.getvalue())
        self.assertIn('ABCD-1234', output.getvalue())
        self.assertEqual(self.store.read('config.json')['device_token'], 'PRIVATE_TOKEN')
        self.assertEqual((self.store.directory / 'config.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.directory.stat().st_mode & 0o777, 0o700)

    def test_pair_pending_does_not_save_token(self):
        self.transport.post = lambda route, payload: ({'device_code': 'SECRET', 'user_code': 'ABCD',
            'verification_uri': self.transport.origin + '/pair', 'expires_in': 1, 'interval': 5}
            if route.endswith('start') else {'status': 'pending'})
        ticks = iter([0, 0, 2])
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            pair(self.store, self.transport, str(self.save), sleep=lambda _: None, monotonic=lambda: next(ticks))
        self.assertEqual(self.store.read('config.json'), {})

    def test_safe_queue_and_no_restart_full_scan(self):
        before = self.save.read_bytes()
        runner = Runner(self.store, self.transport, self.config, now=lambda: 10)
        runner.tick()
        self.assertEqual(self.transport.calls, [])
        runner.tick()
        self.assertEqual(len(self.transport.calls), 1)
        payload = self.transport.calls[0][1]
        serialized = json.dumps(payload)
        for secret in ('SECRET_WORLD', 'SECRET_ENTITY', 'RAW_SECRET', str(self.save), 'sha256'):
            self.assertNotIn(secret, serialized)
        self.assertEqual(payload['kind'], 'save_summary')
        self.assertEqual(payload['appid'], 4231820)
        self.assertEqual(self.save.read_bytes(), before)
        restarted = Runner(self.store, self.transport, self.config)
        with patch('deck.client.watch.snapshot', side_effect=AssertionError('must not rescan')):
            restarted.tick()
        self.assertEqual(len(self.transport.calls), 1)

    def test_offline_latest_only_retry_same_event(self):
        self.transport.error = urllib.error.URLError('offline')
        runner = Runner(self.store, self.transport, self.config, now=lambda: 10)
        runner.tick(); runner.tick()
        first = self.store.read('state.json')['queue']['event_id']
        self.save.write_text(json.dumps(fixture(24)))
        runner.tick(); runner.tick()
        state = self.store.read('state.json')
        self.assertNotEqual(first, state['queue']['event_id'])
        self.assertEqual(state['queue']['payload']['player_scalars']['currentHealth']['value'], 24)
        self.assertLess((self.store.directory / 'state.json').stat().st_size, 16384)
        self.transport.error = None
        runner.retry_at = 0
        runner.tick()
        self.assertEqual(self.transport.calls[-1][1]['event_id'], state['queue']['event_id'])
        self.assertNotIn('queue', self.store.read('state.json'))

    def test_rejected_token_stops_for_explicit_pairing(self):
        self.transport.error = urllib.error.HTTPError('https://example.com', 401, 'denied', {}, None)
        runner = Runner(self.store, self.transport, self.config)
        runner.tick()
        with self.assertRaises(RePairRequired):
            runner.tick()
        self.assertEqual(self.store.read('state.json')['sync_status'], 'pairing_or_consent_required')

    def test_summary_rejects_extra_fields_and_guessed_maxima(self):
        summary = belmont.safe_summary(belmont.decode_bytes(json.dumps(fixture()).encode()))
        self.assertEqual(clean_summary(summary), summary)
        summary['hp_max'] = 100
        with self.assertRaises(ValueError):
            clean_summary(summary)

    def test_symlink_save_and_state_rejected(self):
        link = self.root / 'link'
        link.symlink_to(self.save)
        config = dict(self.config, path=str(link))
        with self.assertRaises(OSError):
            Runner(self.store, self.transport, config).tick()
        (self.store.directory / 'config.json').symlink_to(self.save)
        with self.assertRaises(OSError):
            self.store.read('config.json')

    def test_store_size_budget_and_permissions(self):
        with self.assertRaises(ValueError):
            self.store.write('state.json', {'raw': 'x' * 16384})
        self.store.directory.chmod(0o755)
        with self.assertRaises(ValueError):
            Store(self.store.directory)

    def test_unit_has_no_local_test_or_privileged_operations(self):
        unit = unit_text(Path('/home/deck/.local/share/steam-game-companion'))
        self.assertIn(' -m deck run', unit)
        self.assertIn('RestartPreventExitStatus=3', unit)
        for forbidden in ('sudo', 'allow-local-test', 'linger', 'device_token', 'steam-readonly'):
            self.assertNotIn(forbidden, unit)


    def test_pair_rejects_foreign_browser_origin(self):
        original = self.transport.post
        def post(route, payload):
            result = original(route, payload)
            if route.endswith('start'):
                result['verification_uri'] = 'https://evil.example/pair'
            return result
        self.transport.post = post
        with self.assertRaises(ValueError):
            pair(self.store, self.transport, str(self.save))
        self.assertEqual(self.store.read('config.json'), {})

    def test_expired_credential_stops_without_network(self):
        runner = Runner(self.store, self.transport, dict(self.config, expires_at=1), now=lambda: 2)
        with self.assertRaises(RePairRequired):
            runner.tick()
        self.assertEqual(self.transport.calls, [])

    def test_installer_preflight_before_any_write(self):
        home = self.root / 'empty-home'
        home.mkdir()
        with patch('deck.install.preflight', side_effect=ValueError('unsupported')):
            with self.assertRaises(ValueError):
                install(home, self.root)
        self.assertEqual(list(home.iterdir()), [])

    def test_uninstall_mock_preserves_save_and_optional_config(self):
        from deck.install import paths
        home = self.root / 'home'
        destination, unit, config = paths(home)
        destination.mkdir(parents=True)
        unit.parent.mkdir(parents=True)
        unit.write_text('synthetic unit')
        config.mkdir()
        (config / 'config.json').write_text('synthetic credential')
        with patch('deck.install.subprocess.run'), contextlib.redirect_stdout(io.StringIO()):
            uninstall(home, remove_config=False)
        self.assertTrue(config.exists())
        self.assertTrue(self.save.exists())
        self.assertFalse(destination.exists())
        with patch('deck.install.subprocess.run'), contextlib.redirect_stdout(io.StringIO()):
            uninstall(home, remove_config=True)
        self.assertFalse(config.exists())
        self.assertTrue(self.save.exists())

    def test_repair_generation_invalidates_old_runner_and_queue(self):
        old = dict(self.config, pairing_id='old')
        self.store.write('config.json', old)
        runner = Runner(self.store, self.transport, old)
        runner.tick()
        newer = dict(self.config, pairing_id='new')
        self.store.write('config.json', newer)
        # Simulates a crash before old state could be replaced.
        self.store.write('state.json', {'pairing_id': 'old', 'queue': {'payload': 'PRIVATE_OLD'}})
        with self.assertRaises(RePairRequired):
            runner.tick()
        fresh = Runner(self.store, self.transport, newer)
        self.assertNotIn('queue', fresh.state)
        self.assertEqual(self.transport.calls, [])

    def test_guided_setup_decline_and_enable_are_explicit(self):
        from deck.setup import setup
        for enable in (False, True):
            with patch('deck.setup.os.geteuid', return_value=1000), \
                 patch('deck.setup.Path.home', return_value=self.root / 'fresh-home'), \
                 patch('deck.setup.install') as installer, \
                 patch('deck.setup.pair') as pairing, \
                 patch('deck.setup.Store'), patch('deck.setup.Transport'), \
                 patch('deck.setup.subprocess.run') as command, \
                 contextlib.redirect_stdout(io.StringIO()):
                result = setup('https://companion.example', str(self.save), enable=enable, ask=lambda _: 'no')
                self.assertEqual(result, 0)
                installer.assert_called_once()
                pairing.assert_called_once()
                self.assertEqual(command.call_count, int(enable))

    def test_guided_setup_failed_pair_never_enables(self):
        from deck.setup import setup
        with patch('deck.setup.os.geteuid', return_value=1000), \
             patch('deck.setup.Path.home', return_value=self.root / 'fresh-home'), \
             patch('deck.setup.install'), patch('deck.setup.pair', side_effect=ValueError('private')), \
             patch('deck.setup.Store'), patch('deck.setup.Transport'), \
             patch('deck.setup.subprocess.run') as command, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(setup('https://companion.example', str(self.save), enable=True), 1)
            command.assert_not_called()

    def test_transport_uses_no_proxies_and_refuses_redirects(self):
        transport = Transport(self.transport.origin)
        redirect = next(x for x in transport.opener.handlers if hasattr(x, 'redirect_request'))
        with self.assertRaises(urllib.error.HTTPError):
            redirect.redirect_request(__import__('urllib.request', fromlist=['Request']).Request('https://companion.example'), None, 302, 'Found', {}, 'https://evil.example')


if __name__ == '__main__':
    unittest.main()
