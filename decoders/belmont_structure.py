"""Local Belmont 1.1.3 structural checks; no progress or enum interpretation.

Based on redacted owner-authorized observations reported by the parent task.
This module has not independently read that private fixture. No raw objects,
IDs, counts, coordinates, strings or hashes leave inspect_bytes().
"""
from __future__ import annotations

import argparse
import json

from . import belmont, inspection

MAX_BYTES = belmont.MAX_BYTES
MAX_NODES = belmont.MAX_NODES
MAX_NESTED_BYTES = belmont.MAX_NESTED_BYTES
VERSION = '1.1.3'
CHECKS = ('exploration_map', 'chunks_arrays', 'secret_arrays', 'world_map',
          'completion_counters')


def _report(status='unknown', reason='structure_unavailable'):
    return {'status': status, 'reason': reason,
            'checks': {name: 'unknown' for name in CHECKS},
            'semantic_mapping_status': 'unknown', 'collected_item_status': 'unknown',
            'coverage': 'selected_structure_only'}


def _map(value):
    # Strict map shape validation (including duplicates and parallel lengths)
    # reuses the existing bounded structural primitive, not gameplay semantics.
    return list(belmont._parallel(value))


def _int_array(value):
    # No inferred enum domain, nonnegative constraint or unique-array invariant.
    # bool is deliberately not an integer here. Empty arrays are valid structure.
    return isinstance(value, list) and all(type(item) is int for item in value)


def _exploration(root, budget):
    player = root.get('playerSave')
    if not isinstance(player, dict) or player.get('worldRoomExplorationStates') is None:
        return ('unknown',) * 3
    pairs = _map(player['worldRoomExplorationStates'])
    chunks, secrets = [], []
    for _, encoded in pairs:
        if not isinstance(encoded, str) or len(encoded.encode('utf-8', errors='surrogatepass')) > MAX_NESTED_BYTES:
            raise belmont.DecodeError('Invalid nested structure')
        obj = belmont._json(encoded, budget)
        if not isinstance(obj, dict):
            raise belmont.DecodeError('Invalid nested structure')
        chunks.append(_int_array(obj.get('chunksExplorationState')))
        secrets.append(_int_array(obj.get('discoveredSecretZones')))
    # An empty map validates its container but provides no evidence of fields.
    return ('known', 'known' if chunks and all(chunks) else 'unknown',
            'known' if secrets and all(secrets) else 'unknown')


def _worlds(root):
    if root.get('worldSaves') is None:
        return ('unknown',) * 2
    pairs = _map(root['worldSaves'])
    fields = []
    for _, obj in pairs:
        if not isinstance(obj, dict):
            raise belmont.DecodeError('Invalid world structure')
        fields.append(type(obj.get('currentCompletionItemCount')) is int)
    return 'known', 'known' if fields and all(fields) else 'unknown'


def inspect_bytes(raw):
    """Return only fixed statuses. `known` means type/shape, never game meaning.

    A single shared node budget covers the outer JSON and every decoded target
    string, including unknown object fields. Per-document depth and nested byte
    caps apply. Unknown fields are permitted and are never projected.
    """
    if type(raw) is not bytes or len(raw) > MAX_BYTES:
        return _report(reason='invalid_or_oversized_input')
    try:
        budget = [MAX_NODES]
        root = belmont._json(raw, budget)
        if not isinstance(root, dict):
            return _report(reason='invalid_structure')
        if 'version' not in root or root['version'] is None:
            return _report(reason='format_unknown')
        if type(root['version']) is not str or root['version'] != VERSION:
            return _report('unsupported', 'save_format_not_supported')
        exploration = _exploration(root, budget)
        worlds = _worlds(root)
        checks = dict(zip(CHECKS, (*exploration, *worlds)))
        complete = all(value == 'known' for value in checks.values())
        return {**_report('known' if complete else 'unknown',
                          'selected_structure_validated' if complete else 'selected_structure_incomplete'),
                'checks': checks}
    except (belmont.DecodeError, UnicodeError, RecursionError, ValueError):
        # Errors never echo JSON keys, private IDs, decoder values or paths.
        return _report(reason='invalid_or_overbudget_structure')


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise belmont.DecodeError('Invalid arguments')


def main(argv=None):
    parser = _Parser(description='Local selected-container structural checks; no gameplay facts')
    parser.add_argument('save')
    try:
        args = parser.parse_args(argv)
        result = inspect_bytes(inspection.read_snapshot(args.save))
        code = 0 if result['status'] == 'known' else 2
    except belmont.DecodeError:
        result, code = _report(reason='input_unavailable'), 2
    except KeyboardInterrupt:
        result, code = _report(reason='inspection_interrupted'), 130
    print(json.dumps(result, allow_nan=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
