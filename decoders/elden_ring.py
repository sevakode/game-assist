"""Local read-only PC fixed-region checksum inspector, not a gameplay decoder.

See docs/elden_ring_inspector.md for pinned evidence and deliberately narrow scope.
The BND4 directory and payload semantics remain unvalidated, even on success.
"""
from __future__ import annotations

import argparse
import hashlib
import json

from .inspection import read_snapshot
from .belmont import DecodeError

LAYOUT_ID = "er-pc-fixed-regions-v1"
SOURCE_REVISION = "014107f0ca1cff867b5f7565cb79d6684f9b35df"
HEADER_BYTES = 0x300
CHECKSUM_BYTES = 0x10
PAYLOAD_SIZES = (0x280000,) * 10 + (0x60000, 0x240010)
EXPECTED_BYTES = HEADER_BYTES + sum(CHECKSUM_BYTES + n for n in PAYLOAD_SIZES)
MAX_BYTES = 32 * 1024 * 1024


def _result(status: str, reason: str) -> dict:
    return {
        "status": status,
        "reason": reason,
        "structure": "unknown",
        "inspection_scope": "fixed_region_checksums_only",
        "layout_id": LAYOUT_ID,
        "game_identity_status": "unknown",
        "game_build_status": "unknown",
        "save_format_version_status": "unknown",
        "bnd4_directory_status": "unknown",
        "payload_structure_status": "unknown",
        "semantic_mapping_status": "unknown",
        "collected_item_status": "unknown",
        "checksum_status": "unknown",
        "provenance": {
            "kind": "source_review_and_synthetic_tests",
            "source_revision": SOURCE_REVISION,
            "real_save_validation": "not_performed",
        },
    }


def inspect_bytes(raw: bytes, *, layout_id: str = LAYOUT_ID) -> dict:
    """Check one explicitly named research layout; return no input-derived values.

    Known means only exact byte extent and twelve MD5 comparisons passed. MD5
    is a format checksum, not authentication or proof a game can load the file.
    Unsupported lengths may be a different layout OR a truncated/extended file;
    do not label those as corruption. No allocation/loop uses an input count.
    """
    if type(raw) is not bytes or len(raw) > MAX_BYTES:
        return _result("unknown", "invalid_or_oversized_input")
    if type(layout_id) is not str or layout_id != LAYOUT_ID:
        return _result("unsupported", "layout_not_supported")
    if len(raw) < 4:
        return _result("unknown", "truncated_signature")
    if raw[:4] != b"BND4":
        return _result("unsupported", "signature_not_supported")
    if len(raw) != EXPECTED_BYTES:
        return _result("unsupported", "byte_extent_not_supported")
    view = memoryview(raw)
    offset = HEADER_BYTES
    matched = True
    for size in PAYLOAD_SIZES:
        start, end = offset + CHECKSUM_BYTES, offset + CHECKSUM_BYTES + size
        # Explicit bounds before every slice, even though the extent is fixed.
        if not 0 <= offset < start < end <= len(raw):
            return _result("unknown", "invalid_region_bounds")
        try:
            digest = hashlib.md5(view[start:end], usedforsecurity=False).digest()
        except ValueError:
            return _result("unknown", "checksum_algorithm_unavailable")
        matched = (digest == view[offset:start]) and matched
        offset = end
    result = _result("known" if matched else "unknown",
                     "fixed_region_checksums_match" if matched else "checksum_mismatch")
    result["structure"] = "bnd4_signature_and_fixed_extent"
    result["checksum_status"] = "match" if matched else "mismatch"
    return result


class _ArgumentError(ValueError):
    """No user-controlled argparse text may reach stdout/stderr."""


class _PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise _ArgumentError()


def main(argv=None) -> int:
    parser = _PrivateArgumentParser(prog="elden-ring-inspector", description=__doc__)
    parser.add_argument("save", help="Private local snapshot; input is never modified")
    parser.add_argument("--layout", default=LAYOUT_ID)
    try:
        args = parser.parse_args(argv)
        result = inspect_bytes(read_snapshot(args.save), layout_id=args.layout)
    except _ArgumentError:
        result = _result("unknown", "invalid_arguments")
    except (DecodeError, ValueError):
        result = _result("unknown", "snapshot_unavailable")
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["status"] == "known" else 2


if __name__ == "__main__":
    raise SystemExit(main())
