"""Read-only SNFHFZLC envelope inspector; never gameplay evidence.

No decompression, game-build identification, or save-format version inference.
See docs/witcher3.md for pinned sources, conservative gates and evidence gaps.
"""
from __future__ import annotations

import argparse
import json
import struct

from .belmont import DecodeError
from .inspection import read_snapshot

MAGIC = b"SNFHFZLC"
MAX_BYTES = 32 * 1024 * 1024
MAX_CHUNKS = 4096
MAX_DECLARED_CHUNK_BYTES = 16 * 1024 * 1024
MAX_DECLARED_TOTAL_BYTES = 128 * 1024 * 1024
SOURCE_REVISION = "d96247169f2e669bb6b7e0bd42ace79b6b07627d"
SOURCE_URL = "https://github.com/rfvgyhn/W3SavegameEditor/tree/" + SOURCE_REVISION + "/W3SavegameEditor.Core/ChunkedLz4"


def _result(status, reason):
    return {
        "status": status,
        "reason": reason,
        "structure": "unknown",
        "validation_scope": "envelope_and_chunk_ranges_only",
        "game_build_status": "unknown",
        "save_format_version_status": "unknown",
        "semantic_mapping_status": "unknown",
        "collected_item_status": "unknown",
        "compressed_payload_status": "unknown",
        "gameplay_adapter_status": "unsupported",
        "provenance": {
            "kind": "source_review_only",
            "reference": SOURCE_URL,
            "source_revision": SOURCE_REVISION,
            "real_save_validation": "not_performed",
        },
    }


def inspect_bytes(raw: bytes) -> dict:
    """Inspect immutable bytes, returning only fixed labels and bounded sizes.

    ``known`` refers only to the envelope/ranges. Opaque payload bytes may be
    invalid LZ4 or belong to another game. No strings, hashes or IDs are exposed.
    Limits are local policy, not claims about maxima in the game's format.
    """
    if type(raw) is not bytes:
        return _result("unknown", "invalid_input_type")
    if len(raw) > MAX_BYTES:
        return _result("unknown", "input_limit_exceeded")
    if len(raw) < len(MAGIC):
        return _result("unknown", "truncated_signature")
    if raw[:8] != MAGIC:
        return _result("unsupported", "container_variant_not_supported")
    if len(raw) < 16:
        return _result("unknown", "truncated_header")
    count, payload_offset = struct.unpack_from("<ii", raw, 8)
    if count <= 0:
        return _result("unknown", "invalid_chunk_count")
    if count > MAX_CHUNKS:
        return _result("unknown", "chunk_limit_exceeded")
    table_end = 16 + 12 * count
    if table_end > len(raw):
        return _result("unknown", "truncated_chunk_table")
    if not table_end <= payload_offset <= len(raw):
        return _result("unknown", "invalid_payload_offset")

    cursor = payload_offset
    declared_total = 0
    for index in range(count):
        compressed, declared, end = struct.unpack_from("<iii", raw, 16 + index * 12)
        if compressed <= 0 or declared <= 0 or end < 0:
            return _result("unknown", "invalid_chunk_descriptor")
        if declared > MAX_DECLARED_CHUNK_BYTES:
            return _result("unknown", "declared_chunk_limit_exceeded")
        declared_total += declared
        if declared_total > MAX_DECLARED_TOTAL_BYTES:
            return _result("unknown", "declared_total_limit_exceeded")
        cursor += compressed
        if cursor > len(raw):
            return _result("unknown", "truncated_chunk_payload")
        # The reference accepts zero as an unspecified end, including nonfinal
        # chunks. A supplied end must match the sequential compressed range.
        if end not in (0, cursor):
            return _result("unknown", "chunk_end_mismatch")
    if cursor != len(raw):
        return _result("unsupported", "trailing_data_not_supported")

    result = _result("known", "structural_only")
    result["structure"] = "snfh_fzlc_envelope"
    result["safe_summary"] = {
        "chunk_count": count,
        "payload_offset": payload_offset,
        "opaque_header_bytes": payload_offset - table_end,
        "compressed_payload_bytes": cursor - payload_offset,
        "declared_uncompressed_bytes": declared_total,
    }
    return result


class _ArgumentError(Exception):
    """Discard argparse diagnostics, which may contain private input strings."""


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise _ArgumentError from None


def main(argv=None):
    parser = _ArgumentParser(prog="python -m decoders.witcher3", description=__doc__)
    parser.add_argument("save")
    try:
        args = parser.parse_args(argv)
        result = inspect_bytes(read_snapshot(args.save))
    except _ArgumentError:
        result = _result("unknown", "invalid_arguments")
    except (DecodeError, ValueError):
        result = _result("unknown", "snapshot_unavailable")
    print(json.dumps(result, allow_nan=False, indent=2))
    return 0 if result["status"] == "known" else 2


if __name__ == "__main__":
    raise SystemExit(main())
