"""Structural Belmont 1.1.3 reader, NOT a collectible/location decoder.

Only safe_summary/comparison_summary are suitable for public tool responses.
BelmontSave and private_diff contain private opaque save identifiers: keep local.
No save writes, entity classification, location mapping, or inferred maxima.
Path reading is validated on Linux only; Windows is untested. Symlink checks
and snapshot verification do not claim race-proof traversal of hostile directories.
Use a private local directory whose parent directories are not concurrently changed.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import stat
from typing import Any

VERSION = "1.1.3"
MAX_BYTES = 32 * 1024 * 1024
MAX_DEPTH = 64
MAX_NODES = 500_000
MAX_ENTITIES = 100_000
MAX_NESTED_BYTES = 256 * 1024
SCALARS = ("healthUpgradeFragmentCount", "manaUpgradeFragmentCount", "currentHealth", "currentMana")


class DecodeError(ValueError):
    """A deliberately identifier-free error safe to expose to callers."""


@dataclass(repr=False)
class BelmontSave:
    version: str
    scalars: dict[str, dict[str, Any]] = field(repr=False)
    entities: dict[tuple[str, str], Any] = field(repr=False)
    world_status: str
    source_hash: str = field(repr=False)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DecodeError("Duplicate JSON object key")
        result[key] = value
    return result


def _bounded_tree(value, budget):
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        budget[0] -= 1
        if depth > MAX_DEPTH or budget[0] < 0:
            raise DecodeError("JSON complexity limit exceeded")
        if isinstance(item, dict):
            stack.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            stack.extend((v, depth + 1) for v in item)
        elif isinstance(item, float) and not math.isfinite(item):
            raise DecodeError("Non-finite JSON number")


def _json(raw, budget):
    try:
        result = json.loads(raw, object_pairs_hook=_pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(DecodeError("Non-finite JSON number")))
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, DecodeError):
            raise
        raise DecodeError("Invalid JSON encoding or structure") from None
    _bounded_tree(result, budget)
    return result


def _parallel(value):
    if not isinstance(value, dict):
        raise DecodeError("Invalid parallel-map container")
    keys, values = value.get("m_keys"), value.get("m_values")
    if not isinstance(keys, list) or not isinstance(values, list) or len(keys) != len(values):
        raise DecodeError("Invalid parallel-map lengths")
    if len(keys) > MAX_ENTITIES or any(not isinstance(k, str) for k in keys):
        raise DecodeError("Invalid parallel-map keys")
    if len(set(keys)) != len(keys):
        raise DecodeError("Duplicate parallel-map key")
    return zip(keys, values)


def _scalar(player, key):
    if key not in player:
        return {"status": "missing", "value": None}
    value = player[key]
    if value is None:
        return {"status": "unknown", "value": None}
    if type(value) not in (int, float) or value < 0 or value > 2**53 or not math.isfinite(value):
        raise DecodeError("Invalid player scalar")
    if key.endswith("FragmentCount") and type(value) is not int:
        raise DecodeError("Invalid fragment counter")
    return {"status": "known", "value": value}


def decode_bytes(raw: bytes) -> BelmontSave:
    """Validate a bounded snapshot; never return this object through MCP/HTTP."""
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise DecodeError("Save size or input type not supported")
    budget = [MAX_NODES]
    root = _json(raw, budget)
    if not isinstance(root, dict) or root.get("version") != VERSION:
        raise DecodeError("Unsupported save version; expected 1.1.3")
    player = root.get("playerSave", {})
    if not isinstance(player, dict):
        raise DecodeError("Invalid player container")
    scalars = {k: _scalar(player, k) for k in SCALARS}
    entities = {}
    world_status = "missing" if "worldSaves" not in root else "validated_structural_only"
    for world_id, world in _parallel(root["worldSaves"]) if "worldSaves" in root else ():
        if not isinstance(world, dict) or "savableEntityStates" not in world:
            raise DecodeError("Invalid world container")
        for entity_id, encoded in _parallel(world["savableEntityStates"]):
            if len(entities) >= MAX_ENTITIES or not isinstance(encoded, str) or len(encoded.encode("utf-8", errors="surrogatepass")) > MAX_NESTED_BYTES:
                raise DecodeError("Invalid or oversized entity state")
            # Some values are opaque strings (including 'True'), not JSON.
            # Preserve rather than guessing bool, activation, or collection semantics.
            try:
                state = _json(encoded, budget)
            except DecodeError as exc:
                if str(exc) != "Invalid JSON encoding or structure" or encoded.lstrip().startswith(("{", "[")):
                    raise
                state = {"$opaque": encoded}
            entities[(world_id, entity_id)] = state
    return BelmontSave(VERSION, scalars, entities, world_status, hashlib.sha256(raw).hexdigest())


def _reject_symlinks(path):
    for part in (path, *path.parents):
        if stat.S_ISLNK(part.lstat().st_mode):
            raise DecodeError("Symlink paths are not accepted")


def read_save(path: str | Path) -> BelmontSave:
    """Read twice and verify inode, metadata, and hashes without modifying input."""
    path = Path(os.path.abspath(path))
    try:
        _reject_symlinks(path)
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as stream:
            start = os.fstat(stream.fileno())
            if not stat.S_ISREG(start.st_mode) or start.st_size > MAX_BYTES:
                raise DecodeError("Input must be a bounded regular file")
            first = stream.read(MAX_BYTES + 1)
            stream.seek(0)
            second = stream.read(MAX_BYTES + 1)
            end = os.fstat(stream.fileno())
            _reject_symlinks(path)
            current = path.stat()
            stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            if stamp(start) != stamp(end) or stamp(end) != stamp(current) or hashlib.sha256(first).digest() != hashlib.sha256(second).digest():
                raise DecodeError("Save changed during read; retry after saving finishes")
        return decode_bytes(first)
    except OSError:
        raise DecodeError("Save could not be read safely") from None


def safe_summary(save: BelmontSave) -> dict:
    """Explicit allowlist: no paths, hashes, IDs, world names, or entity totals."""
    return {
        "format_version": save.version,
        "player_scalars": {k: dict(save.scalars[k]) for k in SCALARS},
        "semantic_caveats": [
            "Fragment counters are raw values; cumulative versus remainder semantics are unknown.",
            "currentHealth and currentMana are current values, not maxima.",
            "No HP/mana pickup classification, collected-state semantics, or location mapping is established.",
        ],
        "decoder_coverage": {"player_scalars": "four_raw_fields_only", "world_structure": save.world_status,
                             "collectible_semantics": "unknown", "location_mapping": "unknown"},
    }


def _same(a, b):
    # Python treats True == 1; JSON state comparisons must preserve type.
    return json.dumps(a, sort_keys=True, separators=(",", ":")) == json.dumps(b, sort_keys=True, separators=(",", ":"))


def private_diff(before: BelmontSave, after: BelmontSave) -> dict:
    """LOCAL RESEARCH ONLY. Contains opaque identifiers; never expose as a tool result.

    A changed state key is an observation, not evidence of a collected pickup.
    Values are deliberately excluded; unrelated top-level save noise is ignored.
    """
    changes = []
    for world_id, entity_id in sorted(before.entities.keys() | after.entities.keys()):
        ident = (world_id, entity_id)
        present_before, present_after = ident in before.entities, ident in after.entities
        a, b = before.entities.get(ident), after.entities.get(ident)
        if present_before == present_after and _same(a, b):
            continue
        keys = sorted(k for k in (a.keys() | b.keys()) if k not in a or k not in b or not _same(a[k], b[k])) if isinstance(a, dict) and isinstance(b, dict) else []
        changes.append({"world_id": world_id, "entity_id": entity_id,
                        "presence": "changed" if present_before and present_after else "added" if present_after else "removed",
                        "changed_state_keys": keys})
    return {"changed_player_fields": [k for k in SCALARS if before.scalars[k] != after.scalars[k]], "entity_changes": changes}


def comparison_summary(before: BelmontSave, after: BelmontSave) -> dict:
    diff = private_diff(before, after)
    return {"changes_detected": bool(diff["changed_player_fields"] or diff["entity_changes"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only structural save summary; no collectible interpretation.")
    parser.add_argument("save")
    parser.add_argument("--compare", metavar="OTHER_SAVE", help="Return only whether tracked fields/states changed")
    args = parser.parse_args(argv)
    try:
        save = read_save(args.save)
        result = comparison_summary(save, read_save(args.compare)) if args.compare else safe_summary(save)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except DecodeError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
