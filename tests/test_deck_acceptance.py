"""Synthetic owner journeys, not SteamOS/systemd/Steam or network acceptance.

Real installer/Store/pair/Runner/doctor logic runs on temporary files. Only the
OS service boundary, venv creation, clock and HTTPS peer are simulated.
"""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from deck.client import Runner, Store, main as client_main, pair
from deck.doctor import report
from deck.install import install, paths, uninstall
from deck.setup import setup

ROOT = Path(__file__).resolve().parents[1]


class ServiceModel:
    """A deliberately small test peer; it never executes a process."""
    def __init__(self):
        self.calls = []
        self.active = False
        self.enabled = False
        self.interrupt_reload = False

    def run(self, command, **kwargs):
        if command[:2] != ['systemctl', '--user']:
            raise AssertionError('Unexpected process request')
        self.calls.append(command)
        operation = command[2]
        output, code = '', 0
        if operation == 'daemon-reload':
            if self.interrupt_reload:
                self.interrupt_reload = False
                raise KeyboardInterrupt()
        elif operation == 'enable':
            if command[3] != '--now':
                raise AssertionError('Unexpected enable contract')
            self.enabled = self.active = True
        elif operation == 'disable':
            self.enabled = self.active = False
        elif operation == 'is-active':
            output, code = ('active', 0) if self.active else ('inactive', 3)
        elif operation == 'is-enabled':
            output, code = ('enabled', 0) if self.enabled else ('disabled', 1)
        elif operation != 'show-environment':
            raise AssertionError('Unexpected service operation')
        return subprocess.CompletedProcess(command, code, stdout=output, stderr='')


class ServicePeer:
    """Explicit test-owner approval, fake observations and fake revocation."""
    origin = 'https://example.test'

    def __init__(self):
        self.calls = []
        self.approved = False
        self.revoked = False
        self.offline = False
        self.generation = 0
        self.intent = None

    def approve_as_test_owner(self):
        self.approved = True
        self.revoked = False

    def post(self, route, payload, token=None):
        self.calls.append((route, payload, token))
        if route.endswith('/start'):
            self.approved = False
            self.generation += 1
            self.intent = payload
            return {'verification_uri': self.origin + '/devices/approve',
                    'user_code': 'SYNTHETIC-CODE', 'device_code': 'PRIVATE_DEVICE',
                    'expires_in': 600, 'interval': 5}
        if route.endswith('/poll'):
            if not self.approved:
                return {'status': 'pending'}
            return {'status': 'approved', 'device_token': 'PRIVATE_TOKEN_' + str(self.generation),
                    'expires_in': 2592000, **self.intent}
        if route != '/v1/device/observations':
            raise AssertionError('Unexpected service route')
        if self.revoked:
            raise urllib.error.HTTPError(self.origin, 401, 'synthetic revocation', {}, None)
        if self.offline:
            raise urllib.error.URLError('synthetic offline')
        if token != 'PRIVATE_TOKEN_' + str(self.generation):
            raise AssertionError('Unexpected pairing credential')
        return {'accepted': True}


class DeckAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'home'
        self.home.mkdir()
        self.destination, self.unit, self.config_dir = paths(self.home)
        self.save = self.home / 'PRIVATE_SYNTHETIC_SAVE'
        self.save.write_bytes(b'PRIVATE_SYNTHETIC_CONTENT')
        self.original = self.save.read_bytes()
        self.service = ServiceModel()
        self.peer = ServicePeer()
        self.output = io.StringIO()
        self.clock = 0
        self.approval_check = lambda: None
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(contextlib.redirect_stdout(self.output))
        stack.enter_context(patch('socket.socket', side_effect=AssertionError('No real sockets permitted')))
        stack.enter_context(patch('subprocess.run', side_effect=self.service.run))
        stack.enter_context(patch('deck.install.shutil.which', return_value='/synthetic/systemctl'))
        stack.enter_context(patch('venv.EnvBuilder.create', side_effect=self.fake_venv))
        stack.enter_context(patch('deck.setup.os.geteuid', return_value=1000))
        stack.enter_context(patch('deck.setup.Path.home', return_value=self.home))
        stack.enter_context(patch('deck.setup.Store', side_effect=self.store))
        stack.enter_context(patch('deck.setup.Transport', return_value=self.peer))
        stack.enter_context(patch('deck.setup.pair', side_effect=self.pair_with_test_owner))

    @staticmethod
    def fake_venv(path):
        (path / 'bin').mkdir(parents=True)
        (path / 'bin/python').write_text('# synthetic interpreter, never executed\n')

    def store(self):
        return Store(self.config_dir)

    def pair_with_test_owner(self, store, transport, path, **kwargs):
        waits = 0
        def wait(seconds):
            nonlocal waits
            self.clock += seconds
            waits += 1
            # First poll remains pending. Approval is a separate simulated owner
            # action after verifying no credential/observation has been committed.
            if waits == 2:
                self.approval_check()
                self.peer.approve_as_test_owner()
        return pair(store, transport, path, sleep=wait, monotonic=lambda: self.clock, **kwargs)

    def first_setup(self, enable=False):
        return setup(self.peer.origin, str(self.save), appid=999999, mode='metadata',
                     enable=enable, ask=lambda _: 'no')

    def diagnostics(self):
        result = report(self.home)
        text = json.dumps(result)
        self.assertNotIn('PRIVATE_', text)
        self.assertNotIn(str(self.home), text)
        return result

    def observe(self, runner):
        with patch('deck.client.os.read', side_effect=AssertionError('No save content reads')), \
             patch('deck.client.watch.snapshot', side_effect=AssertionError('No hashing/decoding')):
            runner.tick()
            runner.tick()

    def observations(self):
        return [payload for route, payload, _ in self.peer.calls if route == '/v1/device/observations']

    def assert_redacted_output(self):
        self.assertNotIn('PRIVATE_', self.output.getvalue())
        self.assertNotIn(str(self.home), self.output.getvalue())

    def test_first_start_pending_approval_revocation_and_explicit_repair(self):
        self.assertEqual(self.diagnostics()['pairing'], 'missing')
        self.assertFalse(self.config_dir.exists())
        def before_approval():
            self.assertEqual(self.store().read('config.json'), {})
            self.assertEqual(self.observations(), [])
            self.assertFalse(self.service.enabled)
        self.approval_check = before_approval
        self.assertEqual(self.first_setup(), 0)
        self.assertFalse(self.service.active)  # owner declined background operation
        self.assertFalse(self.service.enabled)
        self.assertEqual(self.diagnostics()['installation'], 'present')
        store = self.store()
        config = store.read('config.json')
        self.service.run(['systemctl', '--user', 'enable', '--now', 'steam-game-companion.service'])
        self.observe(Runner(store, self.peer, config))
        observation = self.observations()[0]
        self.assertEqual(observation['kind'], 'save_metadata')
        self.assertEqual(set(observation['payload']), {'size_bytes', 'modified_ns'})
        self.assertNotIn('PRIVATE_', json.dumps(observation))
        self.assertEqual(self.save.read_bytes(), self.original)

        self.peer.revoked = True
        self.save.write_bytes(b'PRIVATE_NEXT_SYNTHETIC_SAVE')  # synthetic game, not companion
        with patch('deck.client.Store', return_value=store), \
             patch('deck.client.Transport', return_value=self.peer), \
             patch('deck.client.time.sleep'), \
             patch('deck.client.os.read', side_effect=AssertionError('No save reads')):
            self.assertEqual(client_main(['run']), 3)
        self.assertEqual(len(self.observations()), 2)  # one success, one rejected send
        self.assertEqual(self.diagnostics()['sync'], 'pairing_or_consent_required')
        self.assertIn('RestartPreventExitStatus=3', self.unit.read_text())
        # Model process exit explicitly; this is not a real systemd restart test.
        self.service.active = False
        old_state = store.read('state.json')
        def before_repair_approval():
            self.assertEqual(store.read('config.json'), config)
            self.assertEqual(store.read('state.json'), old_state)
            self.assertFalse(self.service.active)
        self.approval_check = before_repair_approval
        self.pair_with_test_owner(store, self.peer, str(self.save), appid=999999,
                                  mode='metadata', ask=lambda _: 'yes')
        new_config = store.read('config.json')
        self.assertNotEqual(new_config['pairing_id'], config['pairing_id'])
        self.assertNotIn('queue', store.read('state.json'))
        self.assertFalse(self.service.active)  # pairing never restarts a service
        self.service.run(['systemctl', '--user', 'enable', '--now', 'steam-game-companion.service'])
        self.observe(Runner(store, self.peer, new_config))
        self.assertEqual(self.diagnostics()['sync'], 'synced')
        self.assertEqual(self.save.read_bytes(), b'PRIVATE_NEXT_SYNTHETIC_SAVE')
        self.assert_redacted_output()

    def test_interrupted_first_install_repeated_setup_then_owner_recovery(self):
        self.service.interrupt_reload = True
        self.assertEqual(self.first_setup(enable=True), 1)
        self.assertEqual(self.diagnostics()['installation'], 'interrupted')
        self.assertEqual(self.peer.calls, [])
        self.assertFalse(self.config_dir.exists())
        self.assertFalse(self.service.enabled)
        self.assertEqual(self.first_setup(enable=True), 1)
        self.assertEqual(self.peer.calls, [])
        uninstall(self.home, remove_config=False)
        self.assertEqual(self.diagnostics()['installation'], 'missing')
        self.assertEqual(self.first_setup(), 0)
        self.assertEqual(self.diagnostics()['installation'], 'present')
        self.assertFalse(self.service.active)
        self.assertFalse(self.service.enabled)
        self.assertEqual(self.save.read_bytes(), self.original)
        self.assert_redacted_output()

    def test_reinstall_after_cancel_preserves_pairing_and_offline_queue(self):
        self.assertEqual(self.first_setup(enable=True), 0)
        store = self.store()
        self.peer.offline = True
        self.observe(Runner(store, self.peer, store.read('config.json')))
        self.assertEqual(self.diagnostics()['sync'], 'offline_or_rejected')
        queue = store.read('state.json')['queue']
        before = {name: (self.config_dir / name).read_bytes() for name in ('config.json', 'state.json')}
        starts = sum(route.endswith('/start') for route, _, _ in self.peer.calls)
        uninstall(self.home, remove_config=False)
        self.assertFalse(self.service.active)
        with patch('venv.EnvBuilder.create', side_effect=KeyboardInterrupt()), self.assertRaises(KeyboardInterrupt):
            install(self.home, ROOT)
        self.assertEqual(self.diagnostics()['installation'], 'missing')
        self.assertEqual(before, {name: (self.config_dir / name).read_bytes() for name in before})
        install(self.home, ROOT)  # manual install preserves pairing; not setup/pair
        self.assertEqual(self.diagnostics()['installation'], 'present')
        self.assertEqual(before, {name: (self.config_dir / name).read_bytes() for name in before})
        self.assertFalse(self.service.active)
        self.assertFalse(self.service.enabled)
        self.assertEqual(starts, sum(route.endswith('/start') for route, _, _ in self.peer.calls))
        self.peer.offline = False
        self.service.run(['systemctl', '--user', 'enable', '--now', 'steam-game-companion.service'])
        Runner(store, self.peer, store.read('config.json')).tick()
        self.assertEqual(self.observations()[-1]['event_id'], queue['event_id'])
        self.assertEqual(self.diagnostics()['sync'], 'synced')
        self.assertEqual(self.save.read_bytes(), self.original)
        self.assert_redacted_output()
