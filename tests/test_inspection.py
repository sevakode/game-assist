"""Entirely synthetic observations; no private save or semantic fixture."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from decoders import inspection as i
from decoders.belmont import DecodeError
from knowledge.save_diff_evidence import Observation


def raw(player=None, **extra):
    return json.dumps({'version': '1.1.3', 'playerSave': player or {}, **extra}).encode()


class InspectionTests(unittest.TestCase):
    def compare(self, a, b):
        return i.compare_bytes(4231820, a, b)

    def test_dispatch_and_gate(self):
        self.assertEqual(i.inspect_bytes(4231820, raw())['status'], 'known')
        for app in (1245620, 292030, 1, True, '4231820'):
            self.assertEqual(i.inspect_bytes(app, raw())['status'], 'unsupported')
        self.assertEqual(i.inspect_bytes(1245620, b'BND4')['structure'], 'bnd4_signature_only')
        self.assertEqual(i.inspect_bytes(1245620, b'BND4')['semantic_mapping_status'], 'unknown')
        self.assertEqual(i.inspect_bytes(4231820, b'{"version":"1.1.4"}')['status'], 'unsupported')

    def test_invalid_and_limits(self):
        for data in (b'{', b'\xff', b'{"version":"1.1.3","version":"1.1.3"}',
                     raw({'currentHealth': True}), raw({'currentHealth': -1}),
                     b'{"version":"1.1.3","x":NaN}', b'[' * 80 + b'0' + b']' * 80):
            self.assertEqual(i.inspect_bytes(4231820, data)['status'], 'unknown')
        with patch.object(i, 'MAX_BYTES', 2):
            self.assertEqual(i.inspect_bytes(4231820, raw())['status'], 'unknown')
        self.assertEqual(i.inspect_bytes(4231820, 'secret')['status'], 'unknown')

    def test_scalar_categories_fit_existing_protocol(self):
        result = self.compare(raw({'currentHealth': 1}), raw({'currentHealth': 2}))
        self.assertTrue(result['structural_changes_detected'])
        self.assertEqual(result['observations'][2]['change'], 'increased')
        for observation in result['observations']:
            Observation.model_validate(observation)
        self.assertEqual(result['semantic_mapping_status'], 'unknown')
        self.assertEqual(result['collected_item_status'], 'unknown')

    def test_absent_null_zero_and_integer_decimal_distinct(self):
        pairs = [({}, {}, 'unknown'), ({}, {'currentHealth': None}, 'added'),
                 ({'currentHealth': None}, {}, 'removed'),
                 ({'currentHealth': None}, {'currentHealth': None}, 'null'),
                 ({'currentHealth': None}, {'currentHealth': 0}, 'type_changed'),
                 ({'currentHealth': 1}, {'currentHealth': 1.0}, 'type_changed'),
                 ({'currentHealth': 0}, {'currentHealth': 0}, 'unchanged')]
        for a, b, expected in pairs:
            with self.subTest(expected=expected, a=a, b=b):
                self.assertEqual(self.compare(raw(a), raw(b))['observations'][2]['change'], expected)

    def test_decimal_precision_not_rounded_away(self):
        template = b'{"version":"1.1.3","playerSave":{"currentHealth":%s}}'
        for a, b in ((b'1.000000000000000001', b'1.000000000000000002'),
                     (b'1e-400', b'2e-400')):
            result = self.compare(template % a, template % b)
            self.assertTrue(result['structural_changes_detected'])
            self.assertEqual(result['observations'][2]['change'], 'increased')

    def test_unrepresentable_exponent_is_unknown_not_exception(self):
        data = b'{"version":"1.1.3","x":1e-9999999999999999999999}'
        result = self.compare(data, data)
        self.assertEqual(result['status'], 'unknown')
        self.assertIsNone(result['structural_changes_detected'])

    def test_control_includes_unclassified_fields_and_types(self):
        for a, b in ((True, 1), (None, 0), ('1', 1), (2**60, 2**60 + 1)):
            result = self.compare(raw(hidden=a), raw(hidden=b))
            self.assertTrue(result['structural_changes_detected'])
            self.assertEqual(result['observations'][-1]['change'], 'unknown')
        self.assertFalse(self.compare(raw(hidden=1), raw(hidden=1))['structural_changes_detected'])

    def test_object_order_is_not_change(self):
        self.assertFalse(self.compare(raw(hidden={'a': 1, 'b': 2}),
                                      raw(hidden={'b': 2, 'a': 1}))['structural_changes_detected'])

    def test_array_order_and_added_container_are_positional(self):
        for a, b in (({'items': [1, 2]}, {'items': [2, 1]}),
                     ({}, {'nested': {'items': []}}),
                     ({'nested': {'items': []}}, {})):
            result = self.compare(raw(**a), raw(**b))
            self.assertEqual(result['observations'][-1]['identity'], 'positional_only')

    def test_nested_entity_strings_remain_unclassified(self):
        def entity(value):
            return raw(worldSaves={'m_keys': ['SYNTHETIC_WORLD'], 'm_values': [{
                'savableEntityStates': {'m_keys': ['SYNTHETIC_ENTITY'],
                                        'm_values': [value]}}]})
        result = self.compare(entity('{"flag":true}'), entity('{"flag":1}'))
        self.assertTrue(result['structural_changes_detected'])
        self.assertNotIn('candidate_item_flag', json.dumps(result))
        self.assertNotIn('SYNTHETIC', json.dumps(result))
        self.assertEqual(i.inspect_bytes(4231820, entity('{"a":0,"a":1}'))['status'], 'unknown')

    def test_redaction(self):
        result = self.compare(raw(SYNTHETIC_PRIVATE='SYNTHETIC_BEFORE'),
                              raw(SYNTHETIC_PRIVATE='SYNTHETIC_AFTER'))
        output = json.dumps(result)
        for forbidden in ('SYNTHETIC', 'sha256', 'source_hash', 'world_id', 'entity_id'):
            self.assertNotIn(forbidden, output)

    def test_unsupported_pair_does_not_infer_false(self):
        for app, a, b in ((292030, raw(), raw()), (1245620, b'BND4', b'BND4'),
                          (4231820, raw(), b'{"version":"future"}'),
                          (4231820, raw(), b'{')):
            result = i.compare_bytes(app, a, b)
            self.assertIsNone(result['structural_changes_detected'])
            self.assertEqual(result['observations'], [])

    def test_read_only_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'SYNTHETIC_PRIVATE.sav'
            data = raw({'currentHealth': 2}, SYNTHETIC_SECRET='private')
            path.write_bytes(data)
            before = path.stat()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(i.main(['--appid', '4231820', str(path), '--compare', str(path)]), 0)
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
            self.assertNotIn('SYNTHETIC', output.getvalue())
            link = Path(directory) / 'link'
            link.symlink_to(path)
            with self.assertRaises(DecodeError):
                i.read_snapshot(link)
            with self.assertRaises(DecodeError):
                i.read_snapshot(directory)

    def test_changed_file_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture'
            path.write_bytes(raw())
            real = i.os.fstat
            calls = 0
            def mutate(fd):
                nonlocal calls
                calls += 1
                if calls == 2:
                    path.write_bytes(raw() + b' ')
                return real(fd)
            with patch.object(i.os, 'fstat', side_effect=mutate), self.assertRaises(DecodeError):
                i.read_snapshot(path)

    def test_error_cli_does_not_echo_path(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(i.main(['--appid', '4231820', '/SYNTHETIC_MISSING']), 2)
        self.assertNotIn('SYNTHETIC', output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['status'], 'unknown')
