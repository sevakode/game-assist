"""Bounded local LZ4 block validation; no game version or gameplay inference.

Only inspect_bytes/main results are suitable for tool responses. Decompressed
bytes are private and must never be logged, serialized or returned via HTTP/MCP.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import importlib.metadata
import json
import struct

from . import witcher3 as envelope

REQUIRED_LZ4_VERSION = "4.4.5"
MAX_COMPRESSED_BLOCK_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BLOCK_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 64 * 1024 * 1024


class DecodeError(ValueError):
    """Fixed-label failures only; never include native exception text."""


class UnsupportedError(DecodeError):
    pass


@dataclass(frozen=True, repr=False)
class PrivatePayload:
    # No generated repr: payload may contain arbitrary private game data.
    blocks: tuple[bytes, ...] = field(repr=False)
    payload_offset: int


def _load_lz4():
    try:
        if importlib.metadata.version("lz4") != REQUIRED_LZ4_VERSION:
            raise UnsupportedError("lz4_version_not_supported")
        return importlib.import_module("lz4.block")
    except (ImportError, OSError):
        raise UnsupportedError("lz4_dependency_unavailable") from None


def decompress_bytes(raw: bytes) -> PrivatePayload:
    """Return private blocks only after every block succeeds; no partial result.

    All descriptors and aggregate budgets are checked before import/native work.
    Input is immutable. No retry, dictionary, frame decoder, output concatenation
    or allocation using an unchecked embedded size is allowed.
    """
    checked = envelope.inspect_bytes(raw)
    if checked["status"] != "known":
        error = UnsupportedError if checked["status"] == "unsupported" else DecodeError
        raise error(checked["reason"])
    summary = checked["safe_summary"]
    if summary["declared_uncompressed_bytes"] > MAX_OUTPUT_BYTES:
        raise DecodeError("output_total_limit_exceeded")
    cursor = summary["payload_offset"]
    descriptors = []
    for index in range(summary["chunk_count"]):
        compressed, declared, _ = struct.unpack_from("<iii", raw, 16 + 12 * index)
        if compressed > MAX_COMPRESSED_BLOCK_BYTES:
            raise DecodeError("compressed_block_limit_exceeded")
        if declared > MAX_OUTPUT_BLOCK_BYTES:
            raise DecodeError("output_block_limit_exceeded")
        descriptors.append((cursor, compressed, declared))
        cursor += compressed

    lz4 = _load_lz4()
    blocks = []
    view = memoryview(raw)
    actual_total = 0
    for start, compressed, declared in descriptors:
        try:
            decoded = lz4.decompress(view[start:start + compressed], uncompressed_size=declared)
        except (lz4.LZ4BlockError, ValueError, OverflowError, MemoryError):
            raise DecodeError("lz4_block_decode_failed") from None
        if len(decoded) != declared:
            raise DecodeError("decoded_size_mismatch")
        actual_total += len(decoded)
        if actual_total > MAX_OUTPUT_BYTES:
            raise DecodeError("output_total_limit_exceeded")
        blocks.append(decoded)
    return PrivatePayload(tuple(blocks), summary["payload_offset"])


def inspect_bytes(raw: bytes) -> dict:
    """Public allowlist: no decoded bytes, strings, paths or hashes."""
    try:
        payload = decompress_bytes(raw)
    except UnsupportedError as exc:
        return envelope._result("unsupported", str(exc))
    except DecodeError as exc:
        return envelope._result("unknown", str(exc))
    result = envelope.inspect_bytes(raw)
    result["validation_scope"] = "envelope_and_lz4_blocks_only"
    result["reason"] = "structural_only"
    result["compressed_payload_status"] = "validated_lz4_blocks"
    result["safe_summary"]["decoded_bytes"] = sum(map(len, payload.blocks))
    result["provenance"]["lz4_package_version"] = REQUIRED_LZ4_VERSION
    return result


def main(argv=None):
    parser = envelope._ArgumentParser(prog="python -m decoders.witcher3_lz4", description=__doc__)
    parser.add_argument("save")
    try:
        args = parser.parse_args(argv)
        result = inspect_bytes(envelope.read_snapshot(args.save))
    except envelope._ArgumentError:
        result = envelope._result("unknown", "invalid_arguments")
    except (envelope.DecodeError, ValueError):
        result = envelope._result("unknown", "snapshot_unavailable")
    print(json.dumps(result, allow_nan=False, indent=2))
    return 0 if result["status"] == "known" else 2


if __name__ == "__main__":
    raise SystemExit(main())
