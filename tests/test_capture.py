"""Synthetic private packages in disposable directories only."""
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from decoders import capture as c


@unittest.skipUnless(c.sys.platform == 'linux', 'Linux-only capture')
class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'SYNTHETIC_SOURCE.sav'
        self.raw = b'{"version":"1.1.3","playerSave":{"currentHealth":12},"private":"SYNTHETIC_SECRET"}'
        self.source.write_bytes(self.raw)
        self.parent = self.root / 'private'
        self.parent.mkdir(mode=0o700)
        self.dest = self.parent / 'trial-action-before'
        self.stamp = self.source.stat()

    def run_capture(self, **kwargs):
        return c.capture(self.source, self.dest, confirmed=True, **kwargs)

    def assert_unchanged(self):
        self.assertEqual(self.source.read_bytes(), self.raw)
        current = self.source.stat()
        self.assertEqual((current.st_ino, current.st_size, current.st_mtime_ns),
                         (self.stamp.st_ino, self.stamp.st_size, self.stamp.st_mtime_ns))

    def assert_empty(self):
        self.assertEqual(list(self.parent.iterdir()), [])
        self.assert_unchanged()

    def test_success_private_modes_and_untrusted_metadata(self):
        report = self.run_capture(role='action', phase='before', action='hp_pickup',
                                  build='1.2.3', platform='steamos_proton')
        self.assertEqual(report['status'], 'captured')
        self.assertEqual((self.dest / 'snapshot.sav').read_bytes(), self.raw)
        metadata = json.loads((self.dest / 'observation.json').read_text())
        self.assertEqual(metadata['game_build'], '1.2.3')
        self.assertFalse(metadata['observations_verified'])
        self.assertEqual(metadata['same_selected_slot'], 'unknown')
        self.assertEqual(stat.S_IMODE(self.dest.stat().st_mode), 0o700)
        for file in self.dest.iterdir():
            self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
        self.assert_unchanged()
        self.assertEqual(set(p.name for p in self.parent.iterdir()), {self.dest.name})

    def test_missing_observations_remain_unknown(self):
        self.run_capture()
        meta = json.loads((self.dest / 'observation.json').read_text())
        self.assertIsNone(meta['game_build'])
        for key in ('platform', 'role', 'phase', 'action', 'independent_ground_truth'):
            self.assertEqual(meta[key], 'unknown')

    def test_cancel_before_any_read_or_write(self):
        with patch.object(c.inspection, 'read_snapshot', side_effect=AssertionError('must not read')):
            report = c.capture(self.source, self.dest)
        self.assertEqual(report['status'], 'cancelled')
        self.assert_empty()

    def test_interrupted_write_cleans_partial_package(self):
        original = c._write_file
        def interrupt(fd, name, data):
            original(fd, name, data)
            raise KeyboardInterrupt
        with patch.object(c, '_write_file', side_effect=interrupt), self.assertRaises(KeyboardInterrupt):
            self.run_capture()
        self.assert_empty()

    def test_write_error_cleans_partial_package(self):
        original = c._write_file
        def fail(fd, name, data):
            if name == 'observation.json':
                raise OSError('SYNTHETIC_PRIVATE_ERROR')
            original(fd, name, data)
        with patch.object(c, '_write_file', side_effect=fail), self.assertRaises(c.CaptureError):
            self.run_capture()
        self.assert_empty()

    def test_publish_error_cleans_package(self):
        with patch.object(c, '_publish', side_effect=c.CaptureError('atomic_publish_failed')):
            with self.assertRaises(c.CaptureError):
                self.run_capture()
        self.assert_empty()

    def test_fsync_failure_cleans_package(self):
        with patch.object(c.os, 'fsync', side_effect=OSError('SYNTHETIC')):
            with self.assertRaises(c.CaptureError):
                self.run_capture()
        self.assert_empty()

    def test_deferred_ctrl_c_after_mkdir_cleans_package(self):
        original = c.signal.pthread_sigmask
        def interrupt(how, mask):
            result = original(how, mask)
            if how == c.signal.SIG_SETMASK:
                raise KeyboardInterrupt
            return result
        with patch.object(c.signal, 'pthread_sigmask', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_capture()
        self.assert_empty()

    def test_readonly_source_allowed_and_unchanged(self):
        self.source.chmod(0o400)
        self.run_capture()
        self.assertEqual(stat.S_IMODE(self.source.stat().st_mode), 0o400)
        self.assert_unchanged()

    def test_snapshot_failure_creates_nothing(self):
        with patch.object(c.inspection, 'read_snapshot', side_effect=c.DecodeError('changed')):
            with self.assertRaises(c.CaptureError):
                self.run_capture()
        self.assert_empty()

    def test_interrupt_after_commit_preserves_complete_package(self):
        original = c._publish
        def interrupt(*args):
            original(*args)
            raise KeyboardInterrupt
        with patch.object(c, '_publish', side_effect=interrupt), self.assertRaises(KeyboardInterrupt):
            self.run_capture()
        self.assertEqual((self.dest / 'snapshot.sav').read_bytes(), self.raw)
        self.assertTrue((self.dest / 'observation.json').is_file())
        self.assertEqual(len(list(self.parent.iterdir())), 1)
        self.assert_unchanged()

    def test_no_overwrite_file_directory_or_symlink(self):
        for kind in ('file', 'directory', 'symlink'):
            with self.subTest(kind=kind):
                if kind == 'file':
                    self.dest.write_text('SYNTHETIC_EXISTING')
                elif kind == 'directory':
                    self.dest.mkdir()
                else:
                    self.dest.symlink_to(self.source)
                with self.assertRaises(c.CaptureError):
                    self.run_capture()
                if kind == 'directory':
                    self.dest.rmdir()
                else:
                    self.dest.unlink()
                self.assert_empty()

    def test_publish_race_does_not_replace_empty_directory(self):
        original = c._publish
        def raced(fd, stage, name):
            os.mkdir(name, 0o700, dir_fd=fd)
            original(fd, stage, name)
        with patch.object(c, '_publish', side_effect=raced), self.assertRaises(c.CaptureError):
            self.run_capture()
        self.assertEqual(list(self.dest.iterdir()), [])
        self.assertEqual(list(self.parent.iterdir()), [self.dest])
        self.assert_unchanged()

    def test_staging_collision_does_not_remove_existing_directory(self):
        existing = self.parent / '.capture-collision'
        existing.mkdir(mode=0o700)
        with patch.object(c.secrets, 'token_hex', return_value='collision'), self.assertRaises(c.CaptureError):
            self.run_capture()
        self.assertTrue(existing.is_dir())
        self.assertEqual(list(self.parent.iterdir()), [existing])

    def test_source_symlink_rejected(self):
        link = self.root / 'link'
        link.symlink_to(self.source)
        with self.assertRaises(c.CaptureError):
            c.capture(link, self.dest, confirmed=True)
        self.assert_empty()

    def test_destination_parent_symlink_rejected(self):
        link = self.root / 'link'
        link.symlink_to(self.parent, target_is_directory=True)
        with self.assertRaises(c.CaptureError):
            c.capture(self.source, link / 'capture', confirmed=True)
        self.assert_empty()

    def test_parent_mode_and_relative_path_rejected(self):
        self.parent.chmod(0o755)
        with self.assertRaises(c.CaptureError):
            self.run_capture()
        self.parent.chmod(0o700)
        for dest in ('relative/capture', self.parent / '..' / 'capture'):
            with self.assertRaises(c.CaptureError):
                c.capture(self.source, dest, confirmed=True)
        self.assert_empty()

    def test_git_directory_and_worktree_file_rejected(self):
        for kind in ('directory', 'file', 'symlink'):
            marker = self.root / '.git'
            if kind == 'directory':
                marker.mkdir()
                (marker / 'HEAD').write_text('ref: refs/heads/synthetic')
            elif kind == 'file':
                marker.write_text('gitdir: SYNTHETIC')
            else:
                marker.symlink_to(self.root / 'missing')
            with self.assertRaisesRegex(c.CaptureError, 'repository_destination_forbidden'):
                self.run_capture()
            if kind == 'directory':
                (marker / 'HEAD').unlink()
                marker.rmdir()
            else:
                marker.unlink()
            self.assert_empty()

    def test_bare_repository_rejected(self):
        for name in ('HEAD', 'objects', 'refs'):
            (self.root / name).mkdir()
        with self.assertRaises(c.CaptureError):
            self.run_capture()
        self.assert_empty()

    def test_invalid_observation_does_not_write(self):
        for kwargs in ({'role': 'SYNTHETIC'}, {'build': '/private/name'},
                       {'role': 'control', 'action': 'hp_pickup'}, {'platform': 'console'}):
            with self.assertRaises(c.CaptureError):
                self.run_capture(**kwargs)
            self.assert_empty()

    def test_invalid_save_does_not_write(self):
        self.source.write_bytes(b'{"version":"future"}')
        with self.assertRaises(c.CaptureError):
            self.run_capture()
        self.assertEqual(list(self.parent.iterdir()), [])
        self.assertEqual(self.source.read_bytes(), b'{"version":"future"}')

    def test_cli_redacts_success_errors_and_arguments(self):
        argv = ['--source', str(self.source), '--destination', str(self.dest), '--confirm-capture']
        for args, expected in ((argv, 0), (argv, 2), (argv + ['--role', 'SYNTHETIC_PRIVATE'], 2)):
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(c.main(args), expected)
            output = stdout.getvalue() + stderr.getvalue()
            for forbidden in (str(self.root), 'SYNTHETIC', 'currentHealth', 'sha256', 'snapshot.sav'):
                self.assertNotIn(forbidden, output)
            self.assertEqual(json.loads(stdout.getvalue())['semantic_mapping_status'], 'unknown')

    def test_cli_interrupt_has_redacted_uncertain_result(self):
        with patch.object(c, 'capture', side_effect=KeyboardInterrupt):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(c.main(['--source', 'SYNTHETIC', '--destination', 'SYNTHETIC']), 130)
            self.assertEqual(json.loads(stdout.getvalue())['reason'], 'interrupted_check_private_destination')
