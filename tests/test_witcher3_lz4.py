"""Synthetic raw LZ4 blocks only; no real save or semantic compatibility claim."""
import contextlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from decoders import witcher3_lz4 as w

try:
    import lz4.block as codec
except ImportError:
    codec = None


def container(blocks, sizes):
    offset = 16 + 12 * len(blocks)
    cursor = offset
    descriptors = []
    for block, size in zip(blocks, sizes):
        cursor += len(block)
        descriptors.append(struct.pack("<iii", len(block), size, cursor))
    return b"SNFHFZLC" + struct.pack("<ii", len(blocks), offset) + b"".join(descriptors + blocks)


class DependencyTests(unittest.TestCase):
    def test_missing_and_wrong_dependency_are_unsupported(self):
        raw = container([b"x"], [1])
        with patch.object(w.importlib.metadata, "version", side_effect=w.importlib.metadata.PackageNotFoundError("private")):
            result = w.inspect_bytes(raw)
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["reason"], "lz4_dependency_unavailable")
        with patch.object(w.importlib.metadata, "version", return_value="0.0"):
            self.assertEqual(w.inspect_bytes(raw)["reason"], "lz4_version_not_supported")
        with patch.object(w.importlib.metadata, "version", return_value="4.4.5"), patch.object(w.importlib, "import_module", side_effect=ImportError("private")):
            self.assertEqual(w.inspect_bytes(raw)["reason"], "lz4_dependency_unavailable")

    def test_entire_table_and_budgets_checked_before_native(self):
        raw = container([b"a", b"b"], [4, 5])
        with patch.object(w, "_load_lz4") as load:
            for invalid in (raw[:-1], raw + b"extra", b"unknown!"):
                self.assertNotEqual(w.inspect_bytes(invalid)["status"], "known")
            with patch.object(w, "MAX_OUTPUT_BYTES", 8):
                self.assertEqual(w.inspect_bytes(raw)["reason"], "output_total_limit_exceeded")
            with patch.object(w, "MAX_OUTPUT_BLOCK_BYTES", 4):
                self.assertEqual(w.inspect_bytes(raw)["reason"], "output_block_limit_exceeded")
            with patch.object(w, "MAX_COMPRESSED_BLOCK_BYTES", 1):
                self.assertEqual(w.inspect_bytes(container([b"a", b"bb"], [1, 2]))["reason"], "compressed_block_limit_exceeded")
            load.assert_not_called()


@unittest.skipUnless(codec is not None, "optional lz4 not installed; run isolated LZ4 test environment")
class NativeLz4Tests(unittest.TestCase):
    def encode(self, *blocks):
        return container([codec.compress(b, store_size=False) for b in blocks], list(map(len, blocks)))

    def test_real_codec_multiblock_and_private_result(self):
        self.assertEqual(w.importlib.metadata.version("lz4"), "4.4.5")
        blocks = (b"SENTINEL-PRIVATE" * 100, bytes(range(256)) * 10)
        raw = self.encode(*blocks)
        decoded = w.decompress_bytes(raw)
        self.assertEqual(decoded.blocks, blocks)
        self.assertNotIn("SENTINEL", repr(decoded))
        result = w.inspect_bytes(raw)
        self.assertEqual(result["compressed_payload_status"], "validated_lz4_blocks")
        self.assertEqual(result["safe_summary"]["decoded_bytes"], sum(map(len, blocks)))
        for name in ("game_build_status", "save_format_version_status", "semantic_mapping_status", "collected_item_status"):
            self.assertEqual(result[name], "unknown")
        self.assertEqual(result["gameplay_adapter_status"], "unsupported")
        self.assertNotIn("SENTINEL", json.dumps(result))

    def test_declared_sizes_are_exact_not_just_capacity(self):
        block = codec.compress(b"a" * 100, store_size=False)
        self.assertEqual(w.inspect_bytes(container([block], [99]))["reason"], "lz4_block_decode_failed")
        self.assertEqual(w.inspect_bytes(container([block], [101]))["reason"], "decoded_size_mismatch")

    def test_native_truncated_and_malformed_blocks(self):
        block = codec.compress(b"abcdef" * 100, store_size=False)
        for length in range(1, len(block)):
            result = w.inspect_bytes(container([block[:length]], [600]))
            self.assertEqual(result["status"], "unknown")
        for invalid in (b"\xff", b"\x00\x00\x00", block + b"extra"):
            self.assertEqual(w.inspect_bytes(container([invalid], [600]))["status"], "unknown")

    def test_second_block_failure_never_returns_partial_success(self):
        good = codec.compress(b"SENTINEL-PRIVATE", store_size=False)
        # Use exact first length so the second native call is exercised.
        raw = container([good, b"\xff"], [len(b"SENTINEL-PRIVATE"), 16])
        with patch.object(codec, "decompress", wraps=codec.decompress) as native:
            result = w.inspect_bytes(raw)
            self.assertEqual(native.call_count, 2)
        self.assertEqual(result["status"], "unknown")
        self.assertNotIn("safe_summary", result)
        self.assertEqual(result["compressed_payload_status"], "unknown")
        with self.assertRaises(w.DecodeError) as caught:
            w.decompress_bytes(raw)
        self.assertEqual(str(caught.exception), "lz4_block_decode_failed")

    def test_boundary_budgets_with_actual_codec(self):
        raw = self.encode(b"a" * 4, b"b" * 5)
        with patch.object(w, "MAX_OUTPUT_BYTES", 9), patch.object(w, "MAX_OUTPUT_BLOCK_BYTES", 5):
            self.assertEqual(w.inspect_bytes(raw)["status"], "known")
        with patch.object(w, "MAX_OUTPUT_BYTES", 8):
            self.assertEqual(w.inspect_bytes(raw)["status"], "unknown")

    def test_cli_no_private_output_or_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "SENTINEL-PRIVATE.sav"
            raw = self.encode(b"SENTINEL-PRIVATE" * 20)
            path.write_bytes(raw)
            stamp = path.stat().st_mtime_ns
            for argv, expected in (([str(path)], 0), ([str(path), str(path)], 2)):
                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    self.assertEqual(w.main(argv), expected)
                self.assertEqual(stderr.getvalue(), "")
                self.assertNotIn("SENTINEL", stdout.getvalue())
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(path.stat().st_mtime_ns, stamp)

    def test_native_error_text_not_exposed(self):
        raw = self.encode(b"private")
        with patch.object(codec, "decompress", side_effect=codec.LZ4BlockError("SENTINEL-PRIVATE")):
            result = w.inspect_bytes(raw)
            self.assertNotIn("SENTINEL", json.dumps(result))
            with self.assertRaises(w.DecodeError) as caught:
                w.decompress_bytes(raw)
            self.assertTrue(caught.exception.__suppress_context__)
            self.assertEqual(str(caught.exception), "lz4_block_decode_failed")


if __name__ == "__main__":
    unittest.main()
