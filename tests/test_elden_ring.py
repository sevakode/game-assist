"""Fabricated checksum envelopes only. No real save/build/semantic coverage."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from decoders import elden_ring as er


def synthetic_envelope():
    # This is intentionally NOT a valid BND4 directory or game save.
    header = b"BND4" + b"SYNTHETIC_PRIVATE_HEADER".ljust(764, b"\x00")
    parts = [header]
    for size in [2621440] * 10 + [393216, 2359312]:
        payload = b"SYNTHETIC_PRIVATE_PAYLOAD".ljust(size, b"\x00")
        parts.extend((hashlib.md5(payload, usedforsecurity=False).digest(), payload))
    return b"".join(parts)


class EldenRingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = synthetic_envelope()

    def test_scope_and_unknowns_even_on_checksum_match(self):
        result = er.inspect_bytes(self.raw)
        self.assertEqual(len(self.raw), 28967888)
        self.assertEqual(result["status"], "known")
        self.assertEqual(result["checksum_status"], "match")
        self.assertEqual(result["inspection_scope"], "fixed_region_checksums_only")
        for key in ("game_identity_status", "game_build_status", "save_format_version_status",
                    "bnd4_directory_status", "payload_structure_status",
                    "semantic_mapping_status", "collected_item_status"):
            self.assertEqual(result[key], "unknown")
        self.assertEqual(result["provenance"]["real_save_validation"], "not_performed")

    def test_checksum_and_payload_corruption_in_each_region(self):
        offset = 768
        for size in [2621440] * 10 + [393216, 2359312]:
            for position in (offset, offset + 16, offset + 15 + size):
                with self.subTest(position=position):
                    raw = bytearray(self.raw)
                    raw[position] ^= 1
                    result = er.inspect_bytes(bytes(raw))
                    self.assertEqual(result["status"], "unknown")
                    self.assertEqual(result["checksum_status"], "mismatch")
                    self.assertEqual(result["collected_item_status"], "unknown")
            offset += 16 + size

    def test_truncation_and_trailing_bytes_never_succeed(self):
        for length in (0, 1, 3, 4, 63, 767, 768, 783, 784, 2622224,
                       26215328, len(self.raw) - 1):
            with self.subTest(length=length):
                self.assertNotEqual(er.inspect_bytes(self.raw[:length])["status"], "known")
        self.assertEqual(er.inspect_bytes(self.raw + b"\x00")["reason"],
                         "byte_extent_not_supported")

    def test_format_layout_and_type_gates(self):
        for raw in (b"DCX\x00", b"\xcb\x01\x9c\x2c", b"BND3", b"{}  "):
            self.assertEqual(er.inspect_bytes(raw)["reason"], "signature_not_supported")
        for layout in ("future", "1.16", None, True):
            self.assertEqual(er.inspect_bytes(self.raw, layout_id=layout)["reason"],
                             "layout_not_supported")
        for raw in (None, "BND4", bytearray(b"BND4"), memoryview(b"BND4")):
            self.assertEqual(er.inspect_bytes(raw)["reason"], "invalid_or_oversized_input")
        with patch.object(er, "MAX_BYTES", len(self.raw) - 1):
            self.assertEqual(er.inspect_bytes(self.raw)["reason"], "invalid_or_oversized_input")

    def test_no_hashing_before_format_and_size_gates(self):
        with patch.object(er.hashlib, "md5", side_effect=AssertionError):
            for raw in (b"BND4", self.raw[:-1], self.raw + b"\x00"):
                self.assertNotEqual(er.inspect_bytes(raw)["status"], "known")

    def test_header_is_explicitly_opaque_not_validated(self):
        raw = self.raw[:4] + b"\xff" * 764 + self.raw[768:]
        result = er.inspect_bytes(raw)
        self.assertEqual(result["checksum_status"], "match")
        self.assertEqual(result["bnd4_directory_status"], "unknown")

    def test_algorithm_unavailable_fails_closed(self):
        with patch.object(er.hashlib, "md5", side_effect=ValueError("SYNTHETIC_SECRET")):
            result = er.inspect_bytes(self.raw)
        self.assertEqual(result["reason"], "checksum_algorithm_unavailable")
        self.assertNotIn("SYNTHETIC", json.dumps(result))

    def test_fixed_projection_and_no_private_values(self):
        output = json.dumps(er.inspect_bytes(self.raw))
        for secret in ("SYNTHETIC", "steam_id", "character_name", "source_hash", "inventory"):
            self.assertNotIn(secret, output)
        self.assertNotIn(hashlib.sha256(self.raw).hexdigest(), output)

    def test_read_only_cli_and_rejected_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "SYNTHETIC_PRIVATE.sl2"
            path.write_bytes(self.raw)
            before = path.stat()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(er.main([str(path)]), 0)
            self.assertEqual(path.read_bytes(), self.raw)
            self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
            self.assertNotIn("SYNTHETIC", output.getvalue())
            link = Path(directory) / "link"
            link.symlink_to(path)
            for rejected in (link, Path(directory), Path(directory) / "missing"):
                output, error = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                    self.assertEqual(er.main([str(rejected)]), 2)
                self.assertEqual(json.loads(output.getvalue())["reason"], "snapshot_unavailable")
                self.assertNotIn(directory, output.getvalue() + error.getvalue())
                self.assertEqual(error.getvalue(), "")

    def test_runtime_dispatch_remains_unsupported(self):
        from decoders.inspection import inspect_bytes
        self.assertEqual(inspect_bytes(1245620, self.raw)["status"], "unsupported")

    def test_argument_errors_never_echo_arguments_to_either_stream(self):
        sentinel = "SYNTHETIC_PRIVATE_PATH_OR_TOKEN"
        cases = ([], ["--" + sentinel], [sentinel, sentinel],
                 [sentinel, "--layout"], [sentinel, "--layout", sentinel, "--" + sentinel])
        for args in cases:
            with self.subTest(args=args):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    self.assertEqual(er.main(args), 2)
                self.assertEqual(json.loads(out.getvalue())["reason"], "invalid_arguments")
                self.assertNotIn(sentinel, out.getvalue() + err.getvalue())
                self.assertEqual(err.getvalue(), "")

    def test_help_does_not_echo_program_path_or_other_arguments(self):
        sentinel = "SYNTHETIC_PRIVATE_PATH_OR_TOKEN"
        out, err = io.StringIO(), io.StringIO()
        with patch("sys.argv", [sentinel]), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as raised:
            er.main([sentinel, "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertNotIn(sentinel, out.getvalue() + err.getvalue())
        self.assertIn("elden-ring-inspector", out.getvalue())


if __name__ == "__main__":
    unittest.main()
