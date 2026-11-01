"""Recovery with synthetic files and mocked user service; no device claims."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from deck.client import Store, pair, main, Runner, RePairRequired
from deck.doctor import report, service_state
from deck.install import paths
from deck.setup import setup
from test_deck_metadata import Transport


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.file = self.home / 'PRIVATE_FILE'
        self.file.write_bytes(b'PRIVATE_CONTENT')
        self.store = Store(paths(self.home)[2])
        self.config = {'server': 'https://example.test', 'appid': 999999, 'mode': 'metadata',
                       'device_token': 'PRIVATE_TOKEN', 'path': str(self.file),
                       'expires_at': 1000, 'pairing_id': 'old'}
        self.store.write('config.json', self.config)
        self.transport = Transport()

    def report(self):
        with patch('deck.doctor.service_state', return_value='inactive'), \
             patch('deck.doctor.shutil.which', return_value='/synthetic/systemctl'):
            return report(self.home, now=10)

    def test_report_private_read_only_no_contents_or_network(self):
        before = {p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        with patch('deck.client.os.read', side_effect=AssertionError('No save reads')), \
             patch('deck.client.Transport.post', side_effect=AssertionError('No network')), \
             patch('deck.client.Store.write', side_effect=AssertionError('No writes')):
            result = self.report()
        self.assertEqual(result['selected_file'], 'regular_bounded')
        self.assertEqual(result['network'], 'not_tested')
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn(str(self.home), json.dumps(result))
        self.assertEqual(before, {p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()})

    def test_missing_configuration_does_not_create_directory(self):
        untouched = self.home / 'empty'
        untouched.mkdir()
        with patch('deck.doctor.service_state', return_value='unavailable'):
            self.assertEqual(report(untouched)['pairing'], 'missing')
        self.assertEqual(list(untouched.iterdir()), [])

    def test_expired_and_offline_have_distinct_recovery(self):
        self.store.write('config.json', dict(self.config, expires_at=1))
        self.assertEqual(self.report()['pairing'], 'expired')
        self.store.write('config.json', self.config)
        self.store.write('state.json', {'pairing_id': 'old', 'appid': 999999, 'mode': 'metadata',
                                      'sync_status': 'offline_or_rejected', 'queue': {'private': 'PRIVATE'}})
        result = self.report()
        self.assertEqual(result['queue'], 'pending')
        self.assertTrue(any('sleeping host' in action for action in result['actions']))
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_old_generation_status_not_reported_after_interruption(self):
        self.store.write('state.json', {'pairing_id': 'other', 'sync_status': 'synced', 'queue': {'private': 'PRIVATE'}})
        self.assertEqual(self.report()['queue'], 'old_pairing_ignored')
        with patch('deck.client.Store', return_value=self.store), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['status']), 0)
        self.assertEqual(json.loads(out.getvalue())['sync_status'], 'not_synced')
        self.assertFalse(json.loads(out.getvalue())['queued'])

    def test_selected_symlink_directory_fifo_and_missing_are_rejected(self):
        link = self.home / 'link'
        link.symlink_to(self.file)
        fifo = self.home / 'fifo'
        os.mkfifo(fifo)
        for path in (link, self.home, fifo, self.home / 'missing'):
            self.store.write('config.json', dict(self.config, path=str(path)))
            self.assertEqual(self.report()['selected_file'], 'missing_unsafe_or_unreadable')

    def test_private_config_permissions_and_untrusted_fields_not_echoed(self):
        self.store.write('config.json', dict(self.config, server='PRIVATE_INVALID'))
        self.assertEqual(self.report()['pairing'], 'invalid_or_unreadable')
        self.assertNotIn('PRIVATE', json.dumps(self.report()))
        self.store.write('config.json', self.config)
        (self.store.directory / 'config.json').chmod(0o644)
        self.assertEqual(self.report()['pairing'], 'invalid_or_unreadable')

    def test_service_failures_bounded_and_redacted(self):
        for value in (subprocess.CompletedProcess([], 1, stdout='PRIVATE_PATH', stderr='PRIVATE_TOKEN'),
                      subprocess.TimeoutExpired('systemctl', 5), FileNotFoundError('PRIVATE')):
            kwargs = {'side_effect': value} if isinstance(value, Exception) else {'return_value': value}
            with patch('deck.doctor.subprocess.run', **kwargs) as run:
                self.assertEqual(service_state('is-active'), 'unavailable')
                self.assertEqual(run.call_args.kwargs['timeout'], 5)

    def run_pair(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            pair(self.store, self.transport, str(self.file), appid=999999, mode='metadata',
                 ask=lambda _: 'yes', **kwargs)

    def test_poll_offline_then_cold_start_then_success(self):
        original = self.transport.post
        failures = iter([urllib.error.URLError('PRIVATE'),
                         urllib.error.HTTPError('PRIVATE', 503, 'PRIVATE', {}, None), None])
        def post(route, payload, token=None):
            if route.endswith('/poll'):
                error = next(failures)
                if error:
                    raise error
            return original(route, payload, token)
        self.transport.post = post
        clock = [0]
        def sleep(seconds):
            clock[0] += seconds
        self.run_pair(sleep=sleep, monotonic=lambda: clock[0])
        self.assertNotEqual(self.store.read('config.json')['pairing_id'], 'old')
        self.assertEqual(clock[0], 35)

    def test_interrupted_or_expired_pairing_retains_old_config_and_queue(self):
        self.store.write('state.json', {'pairing_id': 'old', 'queue': {'synthetic': True}})
        before = self.store.read('state.json')
        with self.assertRaises(KeyboardInterrupt):
            self.run_pair(sleep=lambda _: (_ for _ in ()).throw(KeyboardInterrupt()))
        self.assertEqual(self.store.read('config.json'), self.config)
        self.assertEqual(self.store.read('state.json'), before)
        original = self.transport.post
        def offline(route, payload, token=None):
            if route.endswith('/poll'):
                raise urllib.error.URLError('PRIVATE')
            return original(route, payload, token)
        self.transport.post = offline
        clock = [0]
        def sleep(seconds):
            clock[0] += seconds
        with self.assertRaises(ValueError):
            self.run_pair(sleep=sleep, monotonic=lambda: clock[0])
        self.assertLessEqual(clock[0], 660)
        self.assertEqual(self.store.read('config.json'), self.config)
        self.assertEqual(self.store.read('state.json'), before)

    def test_selection_rechecked_after_phone_approval(self):
        original = self.transport.post
        def swap(route, payload, token=None):
            result = original(route, payload, token)
            if route.endswith('/poll'):
                self.file.unlink()
                self.file.symlink_to(self.home / 'missing')
            return result
        self.transport.post = swap
        with self.assertRaises(OSError):
            self.run_pair(sleep=lambda _: None)
        self.assertEqual(self.store.read('config.json'), self.config)

    def test_interrupted_two_file_commit_never_sends_old_queue(self):
        self.store.write('state.json', {'pairing_id': 'old', 'appid': 999999, 'mode': 'metadata', 'queue': {'private': 'PRIVATE_OLD'}})
        original = self.store.write
        def interrupted(name, value):
            if name == 'state.json':
                raise KeyboardInterrupt()
            original(name, value)
        with patch.object(self.store, 'write', side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
            self.run_pair(sleep=lambda _: None)
        new = self.store.read('config.json')
        self.assertNotEqual(new['pairing_id'], 'old')
        runner = Runner(self.store, self.transport, new)
        self.assertNotIn('queue', runner.state)
        old_runner = Runner(self.store, self.transport, self.config)
        with self.assertRaises(RePairRequired):
            old_runner.tick()
        self.assertEqual(self.report()['queue'], 'old_pairing_ignored')

    def test_repeated_setup_partial_install_does_not_pair_or_enable(self):
        paths(self.home)[0].mkdir(parents=True)
        with patch('deck.setup.os.geteuid', return_value=1000), \
             patch('deck.setup.Path.home', return_value=self.home), \
             patch('deck.setup.pair') as pairing, patch('deck.setup.install') as install, \
             patch('deck.setup.subprocess.run') as service, contextlib.redirect_stdout(io.StringIO()) as out:
            for _ in range(2):
                self.assertEqual(setup('https://example.test', str(self.file), appid=999999, mode='metadata', enable=True), 1)
            pairing.assert_not_called()
            install.assert_not_called()
            service.assert_not_called()
        self.assertIn('uninstall --keep-config', out.getvalue())
        self.assertEqual(self.store.read('config.json'), self.config)

    def test_pairing_nontransient_rejection_preserves_old_config(self):
        original = self.transport.post
        polls = []
        def denied(route, payload, token=None):
            if route.endswith('/poll'):
                polls.append(route)
                raise urllib.error.HTTPError('PRIVATE', 403, 'PRIVATE', {}, None)
            return original(route, payload, token)
        self.transport.post = denied
        with self.assertRaises(ValueError):
            self.run_pair(sleep=lambda _: None)
        self.assertEqual(len(polls), 1)
        self.assertEqual(self.store.read('config.json'), self.config)

    def test_setup_timeout_is_reported_without_raw_service_output(self):
        with patch('deck.setup.os.geteuid', return_value=1000), \
             patch('deck.setup.Path.home', return_value=self.home / 'fresh'), \
             patch('deck.setup.install', side_effect=subprocess.TimeoutExpired('PRIVATE', 15)), \
             patch('deck.setup.pair') as pairing, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(setup('https://example.test', str(self.file), appid=999999, mode='metadata'), 1)
        pairing.assert_not_called()
        self.assertIn('doctor', out.getvalue())
        self.assertNotIn('PRIVATE', out.getvalue())


class PairingReasonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.file = self.root / 'PRIVATE_FILE'
        self.file.write_bytes(b'PRIVATE_SAVE')
        self.store = Store(self.root / 'state')
        self.old = {'pairing_id': 'old', 'device_token': 'PRIVATE_OLD'}
        self.store.write('config.json', self.old)
        self.store.write('state.json', {'pairing_id': 'old', 'queue': {'synthetic': True}})
        self.before = self.store.read('state.json')
        self.clock = 0
        self.calls = []
        self.response = {'status': 'pending'}
        self.start_error = None
        self.transport = Transport()
        self.transport.post = self.post

    def post(self, route, payload, token=None):
        self.calls.append(route)
        if route.endswith('/start'):
            if self.start_error:
                raise self.start_error
            return {'verification_uri': self.transport.origin + '/devices/approve',
                    'device_code': 'PRIVATE_DEVICE', 'user_code': 'SYNTHETIC-CODE',
                    'expires_in': 20, 'interval': 5}
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def run_failure(self):
        def sleep(seconds):
            self.clock += seconds
        with contextlib.redirect_stdout(io.StringIO()) as output, self.assertRaises(ValueError):
            pair(self.store, self.transport, str(self.file), appid=999999, mode='metadata',
                 ask=lambda _: 'yes', sleep=sleep, monotonic=lambda: self.clock)
        text = output.getvalue()
        self.assertNotIn('PRIVATE_', text)
        self.assertNotIn(str(self.file), text)
        self.assertEqual(self.store.read('config.json'), self.old)
        self.assertEqual(self.store.read('state.json'), self.before)
        return text

    def test_pending_deadline_does_not_invent_stale_approval_root_cause(self):
        text = self.run_failure()
        self.assertIn('approval for this attempt was not observed', text)
        self.assertIn('cause is not established', text)
        self.assertEqual(text.count('Waiting for approval'), 1)
        self.assertNotIn('service reports this pairing attempt expired', text)

    def test_network_deadline_and_start_timeout_are_distinct(self):
        self.response = urllib.error.URLError(TimeoutError('PRIVATE_NETWORK_DETAIL'))
        self.assertIn('Approval status is unknown', self.run_failure())
        self.start_error = TimeoutError('PRIVATE_TIMEOUT')
        self.assertIn('Pairing connection unavailable', self.run_failure())

    def test_explicit_expired_denied_and_invalid_response(self):
        for status, expected in (('expired', 'attempt expired'), ('denied', 'attempt denied'),
                                 ('PRIVATE_UNKNOWN', 'not understood')):
            self.clock = 0
            self.response = {'status': status, 'body': 'PRIVATE_RESPONSE'}
            self.assertIn(expected, self.run_failure())

    def test_http_errors_do_not_read_or_echo_response_body(self):
        for code, expected in ((400, 'cannot be distinguished'), (410, 'cannot be distinguished'),
                               (401, 'request rejected'), (403, 'request rejected')):
            self.clock = 0
            body = io.BytesIO(b'PRIVATE_RESPONSE_TOKEN')
            self.response = urllib.error.HTTPError('https://example.test/PRIVATE_PATH', code,
                                                  'PRIVATE_REASON', {}, body)
            self.assertIn(expected, self.run_failure())
            self.assertEqual(body.tell(), 0)

    def test_concurrent_pairing_is_preserved_and_reported(self):
        original = self.post
        newer = {'pairing_id': 'newer', 'device_token': 'PRIVATE_NEWER'}
        def changed(route, payload, token=None):
            if route.endswith('/poll'):
                self.store.write('config.json', newer)
                return {'status': 'approved', 'device_token': 'PRIVATE_LATE', 'expires_in': 1000,
                        'appid': 999999, 'scopes': ['saves.metadata']}
            return original(route, payload, token)
        self.transport.post = changed
        with contextlib.redirect_stdout(io.StringIO()) as output, self.assertRaises(ValueError):
            pair(self.store, self.transport, str(self.file), appid=999999, mode='metadata',
                 ask=lambda _: 'yes', sleep=lambda _: None)
        self.assertIn('Another local pairing changed', output.getvalue())
        self.assertNotIn('PRIVATE_', output.getvalue())
        self.assertEqual(self.store.read('config.json'), newer)
        self.assertEqual(self.store.read('state.json'), self.before)

    def test_setup_exposes_specific_reason_before_generic_incomplete_message(self):
        self.response = {'status': 'denied'}
        def pairing(*args, **kwargs):
            return pair(*args, sleep=lambda _: None, **kwargs)
        with patch('deck.setup.os.geteuid', return_value=1000), \
             patch('deck.setup.Path.home', return_value=self.root / 'fresh-home'), \
             patch('deck.setup.install'), patch('deck.setup.Store', return_value=self.store), \
             patch('deck.setup.Transport', return_value=self.transport), \
             patch('deck.setup.pair', side_effect=pairing), \
             patch('deck.setup.subprocess.run') as command, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(setup(self.transport.origin, str(self.file), appid=999999,
                                   mode='metadata', enable=True, ask=lambda _: 'yes'), 1)
        text = output.getvalue()
        self.assertIn('attempt denied', text)
        self.assertIn('Setup incomplete', text)
        self.assertNotIn('PRIVATE_', text)
        command.assert_not_called()
        self.assertEqual(self.store.read('config.json'), self.old)
        self.assertEqual(self.store.read('state.json'), self.before)
