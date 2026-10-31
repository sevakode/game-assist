"""Synthetic-only read-only package comparisons; no game evidence."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from decoders import capture
from decoders import compare_captures as c
from knowledge.save_diff_evidence import Observation


@unittest.skipUnless(c.sys.platform == 'linux', 'Linux-only packet reader')
class CompareCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'SYNTHETIC_PRIVATE.sav'
        self.before, self.after = self.root / 'before', self.root / 'after'
        self.raw = json.dumps({'version': '1.1.3', 'playerSave': {
            'currentHealth': 1, 'currentMana': 2, 'healthUpgradeFragmentCount': 0,
            'manaUpgradeFragmentCount': 0}, 'hidden': 'SYNTHETIC_SECRET'}).encode()
        self.source.write_bytes(self.raw)
        for destination, phase in ((self.before, 'before'), (self.after, 'after')):
            capture.capture(self.source, destination, role='action', phase=phase,
                            action='hp_pickup', build='SYNTHETIC_BUILD', platform='linux', confirmed=True)
        self.meta = json.loads((self.before / 'observation.json').read_text())

    def compare(self):
        return c.compare_captures(self.before, self.after)

    def modify_meta(self, path, **changes):
        target = path / 'observation.json'
        data = json.loads(target.read_text())
        data.update(changes)
        target.write_text(json.dumps(data))

    def test_complete_pair_has_structure_but_no_attestations(self):
        report = self.compare()
        self.assertEqual(report['status'], 'unknown')
        self.assertEqual(report['comparison_status'], 'known')
        self.assertFalse(report['structural_changes_detected'])
        self.assertFalse(report['observations_verified'])
        self.assertIn('same_selected_slot_unconfirmed', report['review_blockers'])
        self.assertIn('action_control_repeat_not_evaluated', report['review_blockers'])
        for observation in report['observations']:
            Observation.model_validate(observation)
        for key in ('semantic_mapping_status', 'collected_item_status'):
            self.assertEqual(report[key], 'unknown')

    def test_scalar_change_only_categories(self):
        target = self.after / 'snapshot.sav'
        target.write_bytes(self.raw.replace(b'"currentHealth": 1', b'"currentHealth": 3'))
        result = self.compare()
        self.assertTrue(result['structural_changes_detected'])
        self.assertEqual(result['observations'][2]['change'], 'increased')
        self.assertNotIn('SYNTHETIC', json.dumps(result))

    def test_incomplete_or_mismatched_context_blocks_comparison(self):
        original = (self.after / 'observation.json').read_bytes()
        for update in ({'game_build': None}, {'platform': 'unknown'}, {'action': 'unknown'},
                       {'role': 'unknown'}, {'game_build': 'OTHER'}, {'platform': 'windows'},
                       {'action': 'mana_pickup'}, {'role': 'repeat'}, {'phase': 'before'}):
            with self.subTest(update=update):
                (self.after / 'observation.json').write_bytes(original)
                self.modify_meta(self.after, **update)
                result = self.compare()
                self.assertEqual(result['status'], 'unknown')
                self.assertEqual(result['comparison_status'], 'unknown')
                self.assertIsNone(result['structural_changes_detected'])
                self.assertEqual(result['observations'], [])

    def test_reversed_and_same_packet_rejected(self):
        self.assertEqual(c.compare_captures(self.after, self.before)['reason'], 'before_after_order_unconfirmed')
        self.assertEqual(c.compare_captures(self.before, self.before)['reason'], 'distinct_capture_packages_required')

    def test_trial_role_action_consistency(self):
        for path in (self.before, self.after):
            self.modify_meta(path, action='no_action')
        self.assertEqual(self.compare()['reason'], 'trial_action_mismatch')
        for path in (self.before, self.after):
            self.modify_meta(path, role='baseline')
        self.assertEqual(self.compare()['reason'], 'trial_role_not_comparable')

    def test_changed_control_blocked(self):
        for path in (self.before, self.after):
            self.modify_meta(path, role='control', action='no_action')
        target = self.after / 'snapshot.sav'
        target.write_bytes(self.raw.replace(b'SYNTHETIC_SECRET', b'SYNTHETIC_CHANGED'))
        report = self.compare()
        self.assertIn('control_changed', report['review_blockers'])
        self.assertIn('ambiguous_observations', report['review_blockers'])
        self.assertEqual(report['status'], 'unknown')

    def test_clean_control_still_not_ground_truth(self):
        for path in (self.before, self.after):
            self.modify_meta(path, role='control', action='no_action')
        report = self.compare()
        self.assertEqual(report['comparison_status'], 'known')
        self.assertNotIn('control_changed', report['review_blockers'])
        self.assertIn('independent_ground_truth_unconfirmed', report['review_blockers'])

    def test_positional_and_missing_scalar_blockers(self):
        data = json.loads(self.raw)
        data['array'] = [1, 2]
        data['playerSave'].pop('currentMana')
        (self.after / 'snapshot.sav').write_text(json.dumps(data))
        result = self.compare()
        self.assertIn('positional_array_changes_not_identity', result['review_blockers'])
        self.assertEqual(result['status'], 'unknown')

    def test_strict_metadata_rejects_paths_types_and_attestations(self):
        original = (self.after / 'observation.json').read_bytes()
        for update in ({'snapshot_path': str(self.source)}, {'observations_verified': True},
                       {'observations_verified': 0}, {'same_selected_slot': True},
                       {'independent_ground_truth': 'verified'}, {'appid': 4231820.0},
                       {'game_build': ['SYNTHETIC']}, {'role': {'secret': 'value'}},
                       {'private_package_encrypted': 0}):
            (self.after / 'observation.json').write_bytes(original)
            self.modify_meta(self.after, **update)
            result = self.compare()
            self.assertEqual(result['reason'], 'invalid_capture_metadata')
            self.assertEqual(result['observations'], [])

    def test_unknown_schema_format_and_actual_save_version(self):
        original = (self.after / 'observation.json').read_bytes()
        for update in ({'schema_version': 'future'}, {'save_format_version': 'future'}, {'appid': 292030}):
            (self.after / 'observation.json').write_bytes(original)
            self.modify_meta(self.after, **update)
            self.assertEqual(self.compare()['status'], 'unsupported')
        (self.after / 'observation.json').write_bytes(original)
        (self.after / 'snapshot.sav').write_bytes(b'{"version":"future"}')
        self.assertEqual(self.compare()['status'], 'unsupported')

    def test_missing_extra_and_staging_files(self):
        target = self.after / 'extra'
        target.write_text('SYNTHETIC')
        self.assertEqual(self.compare()['reason'], 'incomplete_or_extra_packet_files')
        target.unlink()
        metadata = self.after / 'observation.json'
        metadata.unlink()
        self.assertEqual(self.compare()['reason'], 'incomplete_or_extra_packet_files')
        stage = self.root / '.capture-synthetic'
        self.before.rename(stage)
        self.assertEqual(c.compare_captures(stage, self.after)['reason'], 'incomplete_capture_package')

    def test_duplicate_and_malformed_metadata(self):
        target = self.after / 'observation.json'
        for raw in (b'{', b'\xff', b'[]', b'{"schema_version":"1.0","schema_version":"1.0"}',
                    b'[' * 1000 + b'0' + b']' * 1000):
            target.write_bytes(raw)
            self.assertEqual(self.compare()['reason'], 'invalid_capture_metadata')

    def test_bounded_metadata_and_snapshot(self):
        with patch.object(c, 'MAX_METADATA_BYTES', 4):
            self.assertEqual(self.compare()['reason'], 'invalid_or_oversized_packet_file')
        with patch.object(c.inspection, 'MAX_BYTES', 4):
            self.assertEqual(self.compare()['reason'], 'invalid_or_oversized_packet_file')

    def test_packet_and_ancestor_symlinks(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.before, target_is_directory=True)
        self.assertEqual(c.compare_captures(alias, self.after)['comparison_status'], 'unknown')
        alias.unlink()
        alias.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(c.compare_captures(alias / 'before', self.after)['comparison_status'], 'unknown')

    def test_internal_symlink_hardlink_and_fifo(self):
        target = self.after / 'snapshot.sav'
        target.unlink()
        target.symlink_to(self.source)
        self.assertEqual(self.compare()['comparison_status'], 'unknown')
        target.unlink()
        # Exercise the hardlink gate independently of the process umask.
        self.source.chmod(0o600)
        os.link(self.source, target)
        self.assertEqual(self.compare()['reason'], 'invalid_or_oversized_packet_file')
        target.unlink()
        os.mkfifo(target, 0o600)
        self.assertEqual(self.compare()['reason'], 'invalid_or_oversized_packet_file')

    def test_private_permissions_required(self):
        self.after.chmod(0o755)
        self.assertEqual(self.compare()['reason'], 'private_packet_permissions_required')
        self.after.chmod(0o700)
        (self.after / 'observation.json').chmod(0o644)
        self.assertEqual(self.compare()['reason'], 'private_packet_permissions_required')

    def test_changed_file_during_packet_read(self):
        original = c._read_file
        def change(fd, name, limit):
            result = original(fd, name, limit)
            if name == 'observation.json':
                (self.before / 'snapshot.sav').write_bytes(self.raw + b' ')
            return result
        with patch.object(c, '_read_file', side_effect=change):
            self.assertEqual(self.compare()['reason'], 'unstable_capture_package')

    def test_changed_pair_between_reads(self):
        original = c._read_packet
        count = 0
        def change(path):
            nonlocal count
            result = original(path)
            count += 1
            if count == 2:
                (self.before / 'snapshot.sav').write_bytes(self.raw + b' ')
            return result
        with patch.object(c, '_read_packet', side_effect=change):
            self.assertEqual(self.compare()['reason'], 'unstable_capture_package')

    def test_directory_replacement_during_read_rejected(self):
        original = c._read_file
        replaced = False
        def replace(fd, name, limit):
            nonlocal replaced
            result = original(fd, name, limit)
            if not replaced:
                replaced = True
                self.before.rename(self.root / 'original')
                self.before.mkdir(mode=0o700)
            return result
        with patch.object(c, '_read_file', side_effect=replace):
            self.assertEqual(self.compare()['reason'], 'unstable_capture_package')

    def test_no_source_mutation_or_side_effect_files(self):
        def inventory():
            return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                    for p in self.root.rglob('*') if p.is_file()}
        before = inventory()
        self.compare()
        self.assertEqual(inventory(), before)
        with patch.object(c, '_read_file', side_effect=OSError('SYNTHETIC')):
            self.compare()
        self.assertEqual(inventory(), before)

    def test_cli_redaction_and_exit_codes(self):
        for argv, code in (([str(self.before), str(self.after)], 0),
                           ([str(self.before), '/SYNTHETIC_MISSING'], 2),
                           (['--SYNTHETIC_BAD'], 2)):
            output, errors = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                self.assertEqual(c.main(argv), code)
            for forbidden in ('SYNTHETIC', str(self.root), 'currentHealth', 'sha256', 'snapshot.sav'):
                self.assertNotIn(forbidden, output.getvalue() + errors.getvalue())

    def test_cancel_does_not_modify_packages(self):
        with patch.object(c, '_read_packet', side_effect=KeyboardInterrupt):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(c.main([str(self.before), str(self.after)]), 130)
            self.assertEqual(json.loads(output.getvalue())['reason'], 'comparison_interrupted')
        self.assertEqual((self.before / 'snapshot.sav').read_bytes(), self.raw)
        self.assertEqual((self.after / 'snapshot.sav').read_bytes(), self.raw)
