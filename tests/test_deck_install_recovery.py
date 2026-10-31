"""Own-app failure injection on synthetic private state; all systemctl mocked."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import sys
import unittest
from unittest.mock import patch

from deck.client import Store
from deck.doctor import installation_state, report
from deck.install import install, uninstall, paths, publish_unit, unit_text, main


REAL_RUN = subprocess.run


class InstallRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'home'
        self.home.mkdir()
        self.destination, self.unit, self.config = paths(self.home)
        self.store = Store(self.config)
        self.old = {'synthetic_previous_config': True}
        self.store.write('config.json', self.old)
        self.source = Path(self.tmp.name) / 'source'
        for package in ('deck', 'agent', 'decoders'):
            directory = self.source / package
            directory.mkdir(parents=True)
            (directory / '__main__.py').write_text('# synthetic code\n')
            (directory / 'client.py').write_text('# synthetic code\n')
        self.preflight = patch('deck.install.preflight').start()
        self.addCleanup(patch.stopall)
        self.commands = patch('deck.install.subprocess.run').start()
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    @staticmethod
    def venv(path):
        (path / 'bin').mkdir(parents=True)
        (path / 'bin/python').write_text('# synthetic interpreter\n')

    def do_install(self):
        with patch('venv.EnvBuilder.create', side_effect=self.venv):
            install(self.home, self.source)

    def test_copy_failure_rolls_back_only_new_files_then_retry_succeeds(self):
        with patch('deck.install.shutil.copytree', side_effect=OSError('PRIVATE')), self.assertRaises(OSError):
            self.do_install()
        self.assertFalse(self.destination.exists())
        self.assertFalse(self.unit.exists())
        self.assertEqual(self.store.read('config.json'), self.old)
        self.commands.assert_not_called()
        self.do_install()
        self.assertEqual(installation_state(self.home), 'present')
        self.assertEqual(self.unit.read_text(), unit_text(self.destination))
        self.assertEqual(self.unit.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.read('config.json'), self.old)
        self.assertEqual(self.commands.call_args.args[0], ['systemctl', '--user', 'daemon-reload'])

    def test_cancelled_venv_build_removes_new_tree_preserves_config(self):
        with patch('venv.EnvBuilder.create', side_effect=KeyboardInterrupt()), self.assertRaises(KeyboardInterrupt):
            install(self.home, self.source)
        self.assertFalse(self.destination.exists())
        self.assertFalse(self.unit.exists())
        self.assertEqual(self.store.read('config.json'), self.old)
        self.commands.assert_not_called()

    def test_unit_write_failure_never_publishes_partial_unit(self):
        self.unit.parent.mkdir(parents=True)
        with patch('deck.install.os.fsync', side_effect=OSError('PRIVATE')), self.assertRaises(OSError):
            publish_unit(self.unit, 'complete synthetic unit')
        self.assertFalse(self.unit.exists())
        self.assertEqual(list(self.unit.parent.iterdir()), [])

    def test_existing_unit_never_overwritten(self):
        self.unit.parent.mkdir(parents=True)
        self.unit.write_text('existing owner unit')
        with self.assertRaises(FileExistsError):
            publish_unit(self.unit, 'new unit')
        self.assertEqual(self.unit.read_text(), 'existing owner unit')
        self.assertEqual(list(self.unit.parent.iterdir()), [self.unit])

    def test_reload_failure_marks_interrupted_and_recovery_preserves_config(self):
        self.commands.side_effect = subprocess.TimeoutExpired('PRIVATE', 15)
        with self.assertRaises(subprocess.TimeoutExpired):
            self.do_install()
        self.assertEqual(installation_state(self.home), 'interrupted')
        self.assertEqual(self.unit.read_text(), unit_text(self.destination))
        self.assertEqual(self.store.read('config.json'), self.old)
        with self.assertRaises(ValueError):
            self.do_install()
        self.commands.side_effect = None
        uninstall(self.home, remove_config=False)
        self.do_install()
        self.assertEqual(installation_state(self.home), 'present')
        self.assertEqual(self.store.read('config.json'), self.old)
        self.assertFalse(any('enable' in c.args[0] or 'start' in c.args[0] for c in self.commands.call_args_list))

    def test_failed_stop_does_not_remove_installation_or_config(self):
        self.do_install()
        self.commands.side_effect = subprocess.CalledProcessError(1, 'PRIVATE')
        with self.assertRaises(subprocess.CalledProcessError):
            uninstall(self.home, remove_config=True)
        self.assertTrue(self.unit.exists())
        self.assertTrue(self.destination.exists())
        self.assertEqual(self.store.read('config.json'), self.old)

    def test_partial_build_without_unit_can_be_removed_and_repeated(self):
        self.destination.mkdir(parents=True)
        (self.destination / '.installing').write_text('incomplete\n')
        self.assertEqual(installation_state(self.home), 'interrupted')
        self.commands.return_value = subprocess.CompletedProcess([], 4, stdout='unknown')
        uninstall(self.home, remove_config=False)
        uninstall(self.home, remove_config=False)
        self.assertEqual(self.store.read('config.json'), self.old)
        self.do_install()
        self.assertEqual(installation_state(self.home), 'present')

    def test_missing_unit_with_active_or_unavailable_manager_keeps_files(self):
        self.destination.mkdir(parents=True)
        for code, output in ((0, 'active'), (1, ''), (3, 'failed')):
            self.commands.return_value = subprocess.CompletedProcess([], code, stdout=output)
            with self.assertRaises(ValueError):
                uninstall(self.home, remove_config=True)
            self.assertTrue(self.destination.exists())
            self.assertEqual(self.store.read('config.json'), self.old)

    def test_doctor_identifies_partial_or_modified_unit_without_echo(self):
        self.do_install()
        self.unit.write_text('PRIVATE_PATH_AND_TOKEN')
        self.assertEqual(installation_state(self.home), 'unit_mismatch')
        with patch('deck.doctor.service_state', return_value='inactive'):
            result = report(self.home)
        self.assertNotIn('PRIVATE', str(result))
        self.assertTrue(any('reviewed' in action for action in result['actions']))

    def test_uninstall_interrupted_after_config_removal_does_not_claim_preservation(self):
        self.do_install()
        self.commands.reset_mock()
        self.commands.side_effect = [subprocess.CompletedProcess([], 0), KeyboardInterrupt()]
        with patch('deck.install.os.geteuid', return_value=1000), \
             patch('deck.install.Path.home', return_value=self.home), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['uninstall', '--remove-config']), 1)
        self.assertFalse(self.config.exists())
        self.assertEqual(self.commands.call_args_list[0].args[0][2], 'disable')
        self.assertEqual(self.commands.call_args_list[1].args[0][2], 'daemon-reload')
        self.assertIn('may have changed', output.getvalue())
        self.assertIn('doctor', output.getvalue())
        self.assertNotIn('was not changed', output.getvalue())

    def doctor_pairing_case(self, pairing):
        config_file = self.config / 'config.json'
        if pairing == 'missing':
            config_file.unlink(missing_ok=True)
        else:
            self.store.write('config.json', {
                'server': 'https://example.test', 'appid': 999999, 'mode': 'metadata',
                'device_token': 'SYNTHETIC', 'expires_at': 1 if pairing == 'expired' else 1000,
                'path': str(self.source / 'deck/client.py'), 'pairing_id': 'synthetic'})
            self.store.write('state.json', {'pairing_id': 'synthetic', 'appid': 999999,
                'mode': 'metadata', 'sync_status': 'pairing_or_consent_required'})
        return report(self.home, now=10)

    def test_doctor_unreviewed_installation_never_recommends_start_or_restart(self):
        for installation in ('missing', 'partial', 'interrupted', 'unsafe_or_unreadable', 'unit_mismatch'):
            for pairing in ('missing', 'expired', 'revoked'):
                with self.subTest(installation=installation, pairing=pairing), \
                     patch('deck.doctor.installation_state', return_value=installation), \
                     patch('deck.doctor.service_state', return_value='inactive'):
                    result = self.doctor_pairing_case(pairing)
                actions = ' '.join(result['actions'])
                self.assertIn('Recover or review the installation first', actions)
                self.assertNotIn('restart', actions)
                self.assertNotIn('enable/start', actions)

    def test_doctor_present_installation_retains_explicit_service_guidance(self):
        self.do_install()
        for pairing in ('missing', 'expired', 'revoked'):
            with self.subTest(pairing=pairing), \
                 patch('deck.doctor.service_state', return_value='inactive'):
                result = self.doctor_pairing_case(pairing)
            self.assertEqual(result['installation'], 'present')
            actions = ' '.join(result['actions'])
            self.assertIn('Then explicitly restart', actions)
            self.assertIn('enable/start', actions)
            self.assertNotIn('Recover or review the installation first', actions)

    def test_abrupt_build_exit_leaves_marker_and_preserves_pairing(self):
        code = """
import os, sys
from pathlib import Path
from unittest.mock import patch
from deck.install import install
with patch('deck.install.preflight'), patch('venv.EnvBuilder.create', side_effect=lambda _: os._exit(77)):
    install(Path(sys.argv[1]), Path(sys.argv[2]))
"""
        # The child never reaches systemctl: it exits during the synthetic build.
        # Capture the real subprocess implementation before the install-module mock.
        completed = REAL_RUN([sys.executable, '-c', code, str(self.home), str(self.source)],
                             capture_output=True, timeout=15)
        self.assertEqual(completed.returncode, 77)
        self.assertEqual(installation_state(self.home), 'interrupted')
        self.assertFalse(self.unit.exists())
        self.assertEqual(self.store.read('config.json'), self.old)

    def test_cli_cancellation_fixed_message_no_traceback(self):
        with patch('deck.install.os.geteuid', return_value=1000), \
             patch('deck.install.install', side_effect=KeyboardInterrupt()), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['install']), 1)
        self.assertIn('doctor', output.getvalue())


class StateCommitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / 'state')
        self.old = {'device_token': 'SYNTHETIC_OLD', 'pairing_id': 'old'}
        self.new = {'device_token': 'SYNTHETIC_NEW', 'pairing_id': 'new'}
        self.store.write('config.json', self.old)

    def test_precommit_failure_or_cancel_keeps_previous_config(self):
        for failure in (OSError('synthetic'), KeyboardInterrupt()):
            with patch('deck.client.os.fsync', side_effect=failure), self.assertRaises(type(failure)):
                self.store.write('config.json', self.new)
            self.assertEqual(self.store.read('config.json'), self.old)
            self.assertEqual(list(self.store.directory.iterdir()), [self.store.directory / 'config.json'])

    def test_rename_failure_keeps_previous_config_and_removes_temporary(self):
        with patch('deck.client.os.replace', side_effect=OSError('synthetic')), self.assertRaises(OSError):
            self.store.write('config.json', self.new)
        self.assertEqual(self.store.read('config.json'), self.old)
        self.assertEqual(len(list(self.store.directory.iterdir())), 1)

    def test_postcommit_durability_failure_leaves_complete_new_config(self):
        fsync = os.fsync
        calls = []
        def fail_directory(fd):
            calls.append(fd)
            if len(calls) == 2:
                raise OSError('synthetic directory fsync failure')
            fsync(fd)
        with patch('deck.client.os.fsync', side_effect=fail_directory), self.assertRaises(OSError):
            self.store.write('config.json', self.new)
        self.assertEqual(self.store.read('config.json'), self.new)
        self.assertEqual((self.store.directory / 'config.json').stat().st_mode & 0o777, 0o600)

    def test_orphaned_temporary_is_not_configuration(self):
        (self.store.directory / '.tmp-interrupted').write_bytes(b'{"device_token":')
        self.assertEqual(self.store.read('config.json'), self.old)
        (self.store.directory / 'config.json').unlink()
        self.assertEqual(self.store.read('config.json'), {})

    def test_directory_replaced_between_operations_requires_reopen(self):
        self.store.directory.rename(self.root / 'old-state')
        replacement = Store(self.store.directory)
        replacement.write('config.json', {'other': True})
        with self.assertRaises(ValueError):
            self.store.write('config.json', self.new)
        self.assertEqual(replacement.read('config.json'), {'other': True})
        self.assertEqual(Store(self.root / 'old-state').read('config.json'), self.old)

    def test_fixed_state_names_only(self):
        for name in ('../other', '/other', '.lock', '.tmp-interrupted'):
            with self.assertRaises(ValueError):
                self.store.write(name, self.new)
            with self.assertRaises(ValueError):
                self.store.read(name)

    def test_abrupt_state_write_exit_keeps_previous_configuration(self):
        code = """
import os, sys
from unittest.mock import patch
from deck.client import Store
store = Store(sys.argv[1])
with patch('deck.client.os.fsync', side_effect=lambda _: os._exit(77)):
    store.write('config.json', {'device_token': 'SYNTHETIC_NEW', 'pairing_id': 'new'})
"""
        completed = subprocess.run([sys.executable, '-c', code, str(self.store.directory)],
                                   capture_output=True, timeout=15)
        self.assertEqual(completed.returncode, 77)
        self.assertEqual(self.store.read('config.json'), self.old)
        temporary = list(self.store.directory.glob('.tmp-*'))
        self.assertEqual(len(temporary), 1)
        self.assertEqual(temporary[0].stat().st_mode & 0o777, 0o600)
        self.store.write('config.json', self.new)
        self.assertEqual(self.store.read('config.json'), self.new)
