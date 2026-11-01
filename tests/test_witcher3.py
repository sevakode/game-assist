"""Synthetic envelope fixtures only. Payloads are deliberately NOT real saves."""
import contextlib
import io
import json
import os
from pathlib import Path
import random
import struct
import tempfile
import unittest
from unittest.mock import patch

from decoders import witcher3 as w
from decoders import inspection


def envelope(chunks=(b"private-payload",), declared=None, padding=b"", zero_ends=False):
    offset = 16 + 12 * len(chunks) + len(padding)
    cursor = offset
    table = bytearray()
    for index, chunk in enumerate(chunks):
        cursor += len(chunk)
        size = len(chunk) if declared is None else declared[index]
        table.extend(struct.pack("<iii", len(chunk), size, 0 if zero_ends else cursor))
    return w.MAGIC + struct.pack("<ii", len(chunks), offset) + bytes(table) + padding + b"".join(chunks)


def integer(raw, offset, value):
    return raw[:offset] + struct.pack("<i", value) + raw[offset + 4:]


class Witcher3Tests(unittest.TestCase):
    def test_summary_and_unknowns(self):
        raw = envelope((b"abc", b"defgh"), (100, 200), b"secret-id")
        result = w.inspect_bytes(raw)
        self.assertEqual(result["status"], "known")
        self.assertEqual(result["safe_summary"], {
            "chunk_count": 2, "payload_offset": 49, "opaque_header_bytes": 9,
            "compressed_payload_bytes": 8, "declared_uncompressed_bytes": 300})
        for key in ("game_build_status", "save_format_version_status", "semantic_mapping_status",
                    "collected_item_status", "compressed_payload_status"):
            self.assertEqual(result[key], "unknown")
        self.assertEqual(result["gameplay_adapter_status"], "unsupported")
        self.assertNotIn("secret", json.dumps(result))
        self.assertEqual(result["provenance"]["real_save_validation"], "not_performed")

    def test_all_truncations_fail(self):
        raw = envelope((b"abc", b"defgh"), padding=b"padding")
        for length in range(len(raw)):
            with self.subTest(length=length):
                self.assertNotEqual(w.inspect_bytes(raw[:length])["status"], "known")

    def test_format_gate_and_trailing_bytes(self):
        for raw in (b"SNFHFZLZ" + bytes(30), b"BND4" + bytes(30), envelope() + b"extra"):
            self.assertEqual(w.inspect_bytes(raw)["status"], "unsupported")
        for raw in (None, "SNFHFZLC", bytearray(envelope()), memoryview(envelope())):
            self.assertEqual(w.inspect_bytes(raw)["reason"], "invalid_input_type")

    def test_signed_descriptors_and_offsets(self):
        raw = envelope()
        for offset, value, reason in (
            (8, -1, "invalid_chunk_count"), (8, 0, "invalid_chunk_count"),
            (8, 2**31 - 1, "chunk_limit_exceeded"),
            (12, -1, "invalid_payload_offset"), (12, 27, "invalid_payload_offset"),
            (12, len(raw) + 1, "invalid_payload_offset"),
            (16, 0, "invalid_chunk_descriptor"), (16, -1, "invalid_chunk_descriptor"),
            (16, 2**31 - 1, "truncated_chunk_payload"),
            (20, -1, "invalid_chunk_descriptor"), (20, 0, "invalid_chunk_descriptor"),
            (24, -1, "invalid_chunk_descriptor"), (24, 28, "chunk_end_mismatch"),
            (24, len(raw) + 1, "chunk_end_mismatch"),
        ):
            with self.subTest(offset=offset, value=value):
                self.assertEqual(w.inspect_bytes(integer(raw, offset, value))["reason"], reason)

    def test_zero_end_sentinel_on_each_chunk(self):
        self.assertEqual(w.inspect_bytes(envelope((b"a", b"b"), zero_ends=True))["status"], "known")

    def test_resource_limits(self):
        raw = envelope()
        with patch.object(w, "MAX_BYTES", len(raw)):
            self.assertEqual(w.inspect_bytes(raw)["status"], "known")
            self.assertEqual(w.inspect_bytes(raw + b"x")["reason"], "input_limit_exceeded")
        self.assertEqual(w.inspect_bytes(integer(raw, 20, w.MAX_DECLARED_CHUNK_BYTES + 1))["reason"],
                         "declared_chunk_limit_exceeded")
        self.assertEqual(w.inspect_bytes(integer(raw, 20, w.MAX_DECLARED_CHUNK_BYTES))["status"], "known")
        raw = envelope((b"a",) * 9, (w.MAX_DECLARED_CHUNK_BYTES,) * 9)
        self.assertEqual(w.inspect_bytes(raw)["reason"], "declared_total_limit_exceeded")
        self.assertEqual(w.inspect_bytes(envelope((b"a",) * 8, (w.MAX_DECLARED_CHUNK_BYTES,) * 8))["status"], "known")
        self.assertEqual(w.inspect_bytes(envelope((b"a",) * w.MAX_CHUNKS))["status"], "known")

    def test_no_payload_validation_or_runtime_enable(self):
        # Even invalid LZ4 passes the envelope scope; never imply a valid save.
        result = w.inspect_bytes(envelope((b"\xff",)))
        self.assertEqual(result["status"], "known")
        self.assertEqual(result["compressed_payload_status"], "unknown")
        self.assertEqual(inspection.inspect_bytes(292030, envelope())["status"], "unsupported")

    def test_cli_read_only_and_identifier_free_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "private-user-id.sav"
            raw = envelope()
            path.write_bytes(raw)
            before = path.stat()
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(w.main([str(path)]), 0)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
            self.assertNotIn(str(path), output.getvalue())
            link = Path(tmp) / "link"
            link.symlink_to(path)
            fifo = Path(tmp) / "pipe"
            os.mkfifo(fifo)
            for invalid in (link, fifo, Path(tmp), Path(tmp) / "absent"):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(w.main([str(invalid)]), 2)
                self.assertEqual(json.loads(output.getvalue())["reason"], "snapshot_unavailable")
                self.assertNotIn(tmp, output.getvalue())

    def test_cli_argument_errors_do_not_disclose_input(self):
        sentinel = "/private/SENTINEL-player-secret/save.sav"
        for argv in ([], [sentinel, sentinel], ["--" + sentinel],
                     [sentinel, "--private-option=" + sentinel]):
            with self.subTest(argv=argv):
                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    self.assertEqual(w.main(argv), 2)
                self.assertEqual(json.loads(stdout.getvalue())["reason"], "invalid_arguments")
                self.assertEqual(stderr.getvalue(), "")
                self.assertNotIn(sentinel, stdout.getvalue())
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("sys.argv", [sentinel, "--help"]), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                w.main()
        self.assertEqual(raised.exception.code, 0)
        self.assertNotIn(sentinel, stdout.getvalue() + stderr.getvalue())

    def test_bounded_mutations_do_not_raise(self):
        rng = random.Random(292030)
        raw = envelope((b"a", b"b"))
        for _ in range(500):
            mutated = bytearray(raw)
            for _ in range(4):
                mutated[rng.randrange(len(raw))] = rng.randrange(256)
            result = w.inspect_bytes(bytes(mutated))
            self.assertIn(result["status"], ("known", "unknown", "unsupported"))
            self.assertLess(len(json.dumps(result)), 2000)


if __name__ == "__main__":
    unittest.main()
