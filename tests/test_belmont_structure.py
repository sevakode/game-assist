"""Small invented fixtures only; no private IDs, sizes, values or distributions."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from decoders import belmont, belmont_structure as s


def fixture():
    return {'version': '1.1.3', 'playerSave': {'worldRoomExplorationStates': {
        'm_keys': ['SYNTHETIC_ROOM'], 'm_values': [json.dumps({
            'chunksExplorationState': [7, -2], 'discoveredSecretZones': [],
            'SYNTHETIC_UNKNOWN': {'private': 'SYNTHETIC_SECRET'}})]}},
        'worldSaves': {'m_keys': ['SYNTHETIC_WORLD'],
                       'm_values': [{'currentCompletionItemCount': -3}]}}


def inspect(obj):
    return s.inspect_bytes(json.dumps(obj).encode())


class StructureTests(unittest.TestCase):
    def test_known_means_only_structure(self):
        result = inspect(fixture())
        self.assertEqual(result['status'], 'known')
        self.assertEqual(set(result['checks'].values()), {'known'})
        self.assertEqual(result['semantic_mapping_status'], 'unknown')
        self.assertEqual(result['collected_item_status'], 'unknown')
        self.assertNotIn('SYNTHETIC', repr(result))
        self.assertNotIn('currentCompletionItemCount', repr(result))

    def test_missing_null_and_wrong_type_not_zero(self):
        for value in (None, False, 0, 'SYNTHETIC', []):
            data = fixture()
            data['playerSave']['worldRoomExplorationStates'] = value
            self.assertEqual(inspect(data)['status'], 'unknown')
        data = fixture()
        del data['playerSave']['worldRoomExplorationStates']
        self.assertEqual(inspect(data)['checks']['exploration_map'], 'unknown')
        del data['worldSaves']
        self.assertEqual(inspect(data)['checks']['completion_counters'], 'unknown')

    def test_version_gate(self):
        for version in (True, 1.13, 'future'):
            data = fixture()
            data['version'] = version
            self.assertEqual(inspect(data)['status'], 'unsupported')
        for data in ({}, {'version': None}, []):
            self.assertEqual(inspect(data)['status'], 'unknown')

    def test_nested_exact_int_arrays(self):
        for value in (None, True, 0, '[]', {}, [True], [1.0], ['1'], [None]):
            data = fixture()
            obj = {'chunksExplorationState': value, 'discoveredSecretZones': []}
            data['playerSave']['worldRoomExplorationStates']['m_values'] = [json.dumps(obj)]
            result = inspect(data)
            self.assertEqual(result['checks']['chunks_arrays'], 'unknown')
            self.assertEqual(result['checks']['secret_arrays'], 'known')
        for values in ([], [-1, -1, 2**60]):
            data = fixture()
            obj = {'chunksExplorationState': values, 'discoveredSecretZones': values}
            data['playerSave']['worldRoomExplorationStates']['m_values'] = [json.dumps(obj)]
            self.assertEqual(inspect(data)['status'], 'known')

    def test_counter_strict_type(self):
        for value in (None, True, 1.0, '1', [], {}):
            data = fixture()
            data['worldSaves']['m_values'][0]['currentCompletionItemCount'] = value
            result = inspect(data)
            self.assertEqual(result['checks']['completion_counters'], 'unknown')
            self.assertEqual(result['checks']['world_map'], 'known')
        data = fixture()
        data['worldSaves']['m_values'] = [{}]
        self.assertEqual(inspect(data)['checks']['completion_counters'], 'unknown')

    def test_empty_maps_do_not_assert_child_fields(self):
        data = fixture()
        data['worldSaves'] = {'m_keys': [], 'm_values': []}
        data['playerSave']['worldRoomExplorationStates'] = {'m_keys': [], 'm_values': []}
        result = inspect(data)
        self.assertEqual(result['checks']['world_map'], 'known')
        self.assertEqual(result['checks']['exploration_map'], 'known')
        self.assertEqual(result['checks']['chunks_arrays'], 'unknown')
        self.assertEqual(result['checks']['completion_counters'], 'unknown')

    def test_parallel_maps_strict(self):
        for kind in ('world', 'exploration'):
            for mode in ('length', 'duplicate', 'key_type', 'value_type'):
                data = fixture()
                target = data['worldSaves'] if kind == 'world' else data['playerSave']['worldRoomExplorationStates']
                if mode == 'length': target['m_keys'].append('SYNTHETIC_OTHER')
                if mode == 'duplicate':
                    target['m_keys'] *= 2
                    target['m_values'] *= 2
                if mode == 'key_type': target['m_keys'] = [False]
                if mode == 'value_type': target['m_values'] = [None]
                self.assertEqual(inspect(data)['status'], 'unknown')

    def test_duplicate_keys_and_invalid_nested(self):
        self.assertEqual(s.inspect_bytes(b'{"version":"1.1.3","version":"1.1.3"}')['status'], 'unknown')
        for raw in ('{"x":1,"x":2}', 'null', '[]', 'true', '{broken', '{"x":NaN}'):
            data = fixture()
            data['playerSave']['worldRoomExplorationStates']['m_values'] = [raw]
            self.assertEqual(inspect(data)['status'], 'unknown')

    def test_unknown_fields_bounded_but_not_projected(self):
        data = fixture()
        data['SYNTHETIC_PRIVATE'] = {'unknown': [False, None, 'SYNTHETIC']}
        self.assertEqual(inspect(data), inspect(fixture()))
        nested = {'unknown': []}
        for _ in range(belmont.MAX_DEPTH + 1): nested = {'next': nested}
        data['playerSave']['worldRoomExplorationStates']['m_values'] = [json.dumps(nested)]
        self.assertEqual(inspect(data)['status'], 'unknown')

    def test_shared_nodes_not_reset_for_each_string(self):
        data = fixture()
        target = data['playerSave']['worldRoomExplorationStates']
        target['m_keys'].append('SYNTHETIC_SECOND')
        target['m_values'] *= 2
        nested_budget = [10000]
        belmont._json(target['m_values'][0], nested_budget)
        nested_used = 10000 - nested_budget[0]
        outer_nodes = [10000]
        belmont._json(json.dumps(data).encode(), outer_nodes)
        used = 10000 - outer_nodes[0]
        with patch.object(s, 'MAX_NODES', used + nested_used):
            self.assertEqual(inspect(data)['status'], 'unknown')
        with patch.object(s, 'MAX_NODES', used + 50):
            self.assertEqual(inspect(data)['status'], 'known')

    def test_limits_and_invalid_bytes(self):
        for attr in ('MAX_BYTES', 'MAX_NESTED_BYTES', 'MAX_NODES'):
            with patch.object(s, attr, 1):
                self.assertEqual(inspect(fixture())['status'], 'unknown')
        for raw in (b'\xff', b'{', 'private', None):
            self.assertEqual(s.inspect_bytes(raw)['status'], 'unknown')

    def test_exact_outer_and_utf8_nested_byte_boundaries(self):
        data = fixture()
        nested = json.dumps({'chunksExplorationState': [], 'discoveredSecretZones': [],
                             'SYNTHETIC_EXTRA': '\u00e9'}, ensure_ascii=False)
        data['playerSave']['worldRoomExplorationStates']['m_values'] = [nested]
        raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
        for limit, expected in ((len(raw), 'known'), (len(raw) - 1, 'unknown')):
            with patch.object(s, 'MAX_BYTES', limit):
                self.assertEqual(s.inspect_bytes(raw)['status'], expected)
        size = len(nested.encode('utf-8'))
        for limit, expected in ((size, 'known'), (size - 1, 'unknown')):
            with patch.object(s, 'MAX_NESTED_BYTES', limit):
                self.assertEqual(s.inspect_bytes(raw)['status'], expected)

    def test_exact_shared_node_boundary_including_unknown_fields(self):
        data = fixture()
        raw = json.dumps(data).encode()
        budget = [10000]
        belmont._json(raw, budget)
        for nested in data['playerSave']['worldRoomExplorationStates']['m_values']:
            belmont._json(nested, budget)
        used = 10000 - budget[0]
        for limit, expected in ((used, 'known'), (used - 1, 'unknown')):
            with patch.object(s, 'MAX_NODES', limit):
                self.assertEqual(s.inspect_bytes(raw)['status'], expected)

    def test_map_entry_limit_applies_to_both_containers(self):
        for kind in ('world', 'exploration'):
            data = fixture()
            with patch.object(belmont, 'MAX_ENTITIES', 1):
                self.assertEqual(inspect(data)['status'], 'known')
                target = (data['worldSaves'] if kind == 'world' else
                          data['playerSave']['worldRoomExplorationStates'])
                target['m_keys'].append('SYNTHETIC_SECOND')
                target['m_values'] *= 2
                self.assertEqual(inspect(data)['status'], 'unknown')

    def test_outer_depth_and_nonfinite_unknown_fields_rejected(self):
        data = fixture()
        nested = {}
        for _ in range(belmont.MAX_DEPTH + 1):
            nested = {'next': nested}
        data['SYNTHETIC_EXTRA'] = nested
        self.assertEqual(inspect(data)['status'], 'unknown')
        for value in (float('nan'), float('inf'), float('-inf')):
            data = fixture()
            data['SYNTHETIC_EXTRA'] = value
            self.assertEqual(inspect(data)['status'], 'unknown')

    def test_one_invalid_entry_prevents_full_field_claim(self):
        data = fixture()
        target = data['playerSave']['worldRoomExplorationStates']
        target['m_keys'].append('SYNTHETIC_OTHER')
        target['m_values'].append('{}')
        self.assertEqual(inspect(data)['checks']['chunks_arrays'], 'unknown')

    def test_readonly_cli_and_safe_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'SYNTHETIC_PRIVATE.sav'
            raw = json.dumps(fixture()).encode()
            path.write_bytes(raw)
            stamp = path.stat().st_mtime_ns
            for args, code in (([str(path)], 0), ([str(path)+'missing'], 2), (['--SYNTHETIC'], 2)):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(s.main(args), code)
                self.assertNotIn('SYNTHETIC', out.getvalue())
                self.assertNotIn(str(path), out.getvalue())
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(path.stat().st_mtime_ns, stamp)

    def test_existing_reader_projection_unchanged(self):
        data = fixture()
        data['worldSaves']['m_values'][0]['savableEntityStates'] = {'m_keys': [], 'm_values': []}
        raw = json.dumps(data).encode()
        before = belmont.safe_summary(belmont.decode_bytes(raw))
        s.inspect_bytes(raw)
        self.assertEqual(belmont.safe_summary(belmont.decode_bytes(raw)), before)
