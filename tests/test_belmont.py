"""Synthetic-only fixtures. Never add a real save or private identifier here."""
import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from decoders import belmont as b


WORLD = "SYNTHETIC_SECRET_WORLD"
ENTITY = "SYNTHETIC_SECRET_ENTITY"


def fixture():
    return {"version": "1.1.3", "playerSave": {
        "healthUpgradeFragmentCount": 2, "manaUpgradeFragmentCount": 3,
        "currentHealth": 42.0, "currentMana": 50.0},
        "worldSaves": {"m_keys": [WORLD], "m_values": [{
            "savableEntityStates": {"m_keys": [ENTITY], "m_values": [json.dumps({"activated": False, "state": "unknown"})]}}]},
        "unrelatedNoise": "secret"}


def decode(value):
    return b.decode_bytes(json.dumps(value).encode())


class BelmontTests(unittest.TestCase):
    def test_summary_allowlist_no_spoilers(self):
        result = b.safe_summary(decode(fixture()))
        self.assertEqual(set(result), {"format_version", "player_scalars", "semantic_caveats", "decoder_coverage"})
        self.assertEqual(result["player_scalars"]["healthUpgradeFragmentCount"], {"status": "known", "value": 2})
        text = json.dumps(result)
        for marker in (WORLD, ENTITY, "secret", "activated", "source_hash"):
            self.assertNotIn(marker, text)
        self.assertIn("not maxima", text)
        self.assertIn("unknown", text)

    def test_private_diff_flag_counter_noise(self):
        before = fixture()
        after = copy.deepcopy(before)
        after["playerSave"]["healthUpgradeFragmentCount"] += 1
        after["worldSaves"]["m_values"][0]["savableEntityStates"]["m_values"][0] = json.dumps({"activated": True, "state": "unknown"})
        after["unrelatedNoise"] = "different"
        a, c = decode(before), decode(after)
        diff = b.private_diff(a, c)
        self.assertEqual(diff["changed_player_fields"], ["healthUpgradeFragmentCount"])
        self.assertEqual(diff["entity_changes"], [{"world_id": WORLD, "entity_id": ENTITY, "presence": "changed", "changed_state_keys": ["activated"]}])
        self.assertEqual(b.comparison_summary(a, c), {"changes_detected": True})
        after = copy.deepcopy(before)
        after["unrelatedNoise"] = "different"
        self.assertEqual(b.comparison_summary(a, decode(after)), {"changes_detected": False})

    def test_state_type_change_is_not_lost(self):
        a, z = fixture(), fixture()
        a["worldSaves"]["m_values"][0]["savableEntityStates"]["m_values"][0] = '{"state":true}'
        z["worldSaves"]["m_values"][0]["savableEntityStates"]["m_values"][0] = '{"state":1}'
        self.assertEqual(b.private_diff(decode(a), decode(z))["entity_changes"][0]["changed_state_keys"], ["state"])

    def test_missing_unknown_zero_distinct(self):
        value = fixture()
        del value["playerSave"]["currentHealth"]
        value["playerSave"]["currentMana"] = None
        value["playerSave"]["healthUpgradeFragmentCount"] = 0
        scalars = b.safe_summary(decode(value))["player_scalars"]
        self.assertEqual(scalars["currentHealth"]["status"], "missing")
        self.assertEqual(scalars["currentMana"]["status"], "unknown")
        self.assertEqual(scalars["healthUpgradeFragmentCount"]["status"], "known")
        del value["worldSaves"]
        self.assertEqual(decode(value).world_status, "missing")

    def test_opaque_unknown_not_activated_or_collected(self):
        value = fixture()
        value["worldSaves"]["m_values"][0]["savableEntityStates"]["m_values"][0] = "True"
        save = decode(value)
        self.assertEqual(save.entities[(WORLD, ENTITY)], {"$opaque": "True"})
        self.assertNotIn("True", json.dumps(b.safe_summary(save)))

    def test_version_fail_closed(self):
        for version in (None, True, 1.13, "1.1.4", "1.1.3-extra"):
            value = fixture()
            value["version"] = version
            with self.assertRaises(b.DecodeError):
                decode(value)

    def test_invalid_counters(self):
        for bad in (True, False, -1, 1.5, "2", float("inf"), float("nan"), 2**54, 10**400):
            value = fixture()
            value["playerSave"]["healthUpgradeFragmentCount"] = bad
            with self.assertRaises(b.DecodeError):
                decode(value)

    def test_parallel_duplicate_and_length_errors(self):
        for nested in (False, True):
            for duplicate in (False, True):
                value = fixture()
                target = value["worldSaves"]
                if nested:
                    target = target["m_values"][0]["savableEntityStates"]
                target["m_keys"].append(target["m_keys"][0])
                if duplicate:
                    target["m_values"].append(copy.deepcopy(target["m_values"][0]))
                with self.assertRaises(b.DecodeError) as caught:
                    decode(value)
                self.assertNotIn(WORLD, str(caught.exception))
                self.assertNotIn(ENTITY, str(caught.exception))

    def test_invalid_json_duplicate_and_nested(self):
        for raw in (b'{', b'{"version":"1.1.3","version":"1.1.3"}', b'[]', b'\xff'):
            with self.assertRaises(b.DecodeError):
                b.decode_bytes(raw)
        for nested in ('{"state":0,"state":1}', '{broken', '[' * 80 + '0' + ']' * 80):
            value = fixture()
            value["worldSaves"]["m_values"][0]["savableEntityStates"]["m_values"][0] = nested
            with self.assertRaises(b.DecodeError):
                decode(value)

    def test_limits(self):
        with patch.object(b, "MAX_BYTES", 2), self.assertRaises(b.DecodeError):
            decode(fixture())
        with patch.object(b, "MAX_NODES", 2), self.assertRaises(b.DecodeError):
            decode(fixture())
        with patch.object(b, "MAX_ENTITIES", 0), self.assertRaises(b.DecodeError):
            decode(fixture())
        with patch.object(b, "MAX_NESTED_BYTES", 2), self.assertRaises(b.DecodeError):
            decode(fixture())

    def test_readonly_and_cli_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sav"
            raw = json.dumps(fixture()).encode()
            path.write_bytes(raw)
            mtime = path.stat().st_mtime_ns
            save = b.read_save(path)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(path.stat().st_mtime_ns, mtime)
            self.assertNotIn(WORLD, repr(save))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(b.main([str(path)]), 0)
            for marker in (WORLD, ENTITY, str(path)):
                self.assertNotIn(marker, out.getvalue())
            link = Path(directory) / "link.sav"
            link.symlink_to(path)
            with self.assertRaises(b.DecodeError):
                b.read_save(link)
            linkdir = Path(directory) / "linked_dir"
            linkdir.symlink_to(Path(directory), target_is_directory=True)
            with self.assertRaises(b.DecodeError):
                b.read_save(linkdir / "test.sav")

    def test_unstable_file_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sav"
            path.write_text(json.dumps(fixture()))
            real_fstat = b.os.fstat
            calls = 0
            def mutate(fd):
                nonlocal calls
                calls += 1
                if calls == 2:
                    path.write_text(json.dumps(fixture()) + " ")
                return real_fstat(fd)
            with patch.object(b.os, "fstat", side_effect=mutate), self.assertRaises(b.DecodeError):
                b.read_save(path)


if __name__ == "__main__":
    unittest.main()
