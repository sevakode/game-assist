"""Synthetic bounded Proton discovery; no real Steam files or save decoding."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from deck.discovery import discover, choose_path, library_paths, SAVE_RELATIVE, MAX_VDF_BYTES


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.steam = self.home / '.local/share/Steam'

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, library):
        path = library / SAVE_RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'PRIVATE_SYNTHETIC_BYTES_NOT_A_VALID_SAVE')
        return path

    def vdf(self, value):
        path = self.steam / 'steamapps/libraryfolders.vdf'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        return path

    def test_standard_candidate_without_reading_contents(self):
        save = self.save(self.steam)
        with patch('deck.discovery.os.read', side_effect=AssertionError('save contents must not be read')):
            self.assertEqual(discover(self.home), [save])

    def test_known_library_only_and_deduplicated(self):
        first = self.save(self.steam)
        library = self.home / 'external-library'
        second = self.save(library)
        self.save(self.home / 'unlisted-library')
        self.vdf('"libraryfolders" { "0" { "path" "' + str(self.steam) + '" } "1" { "path" "' + str(library) + '" } }')
        self.assertEqual(discover(self.home), [first, second])

    def test_symlink_candidate_and_vdf_are_rejected(self):
        real = self.save(self.home / 'actual')
        candidate = self.steam / SAVE_RELATIVE
        candidate.parent.mkdir(parents=True)
        candidate.symlink_to(real)
        self.assertEqual(discover(self.home), [])
        other = self.home / 'other.vdf'
        other.write_text('"path" "' + str(self.home / 'actual') + '"')
        vdf = self.steam / 'steamapps/libraryfolders.vdf'
        vdf.symlink_to(other)
        self.assertEqual(discover(self.home), [])

    def test_malicious_or_unbounded_vdf_paths_fail_closed(self):
        for raw in (b'"path" "/tmp/../outside"', b'"path" "relative"',
                    b'"path" "/tmp/evil\\nname"', b'"path" "/tmp/evil\nname"',
                    b'"path" "/tmp" garbage', b'x' * (MAX_VDF_BYTES + 1),
                    b' '.join(b'"path" "/tmp/library"' for _ in range(33))):
            with self.subTest(raw=raw[:80]):
                self.assertEqual(library_paths(raw), [])

    def test_no_other_app_or_slot_discovery(self):
        wrong = self.steam / str(SAVE_RELATIVE).replace('4231820', '999')
        wrong.parent.mkdir(parents=True)
        wrong.write_bytes(b'private')
        self.assertEqual(discover(self.home), [])

    def test_single_candidate_requires_confirmation(self):
        save = self.save(self.steam)
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):
                choose_path(home=self.home, ask=lambda _: 'no')
            self.assertEqual(choose_path(home=self.home, ask=lambda _: 'yes'), str(save))

    def test_multiple_require_selection_then_confirmation(self):
        self.save(self.steam)
        other = self.home / 'library'
        save = self.save(other)
        self.vdf('"path" "' + str(other) + '"')
        answers = iter(['2', 'yes'])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(choose_path(home=self.home, ask=lambda _: next(answers)), str(save))
            with self.assertRaises(ValueError):
                choose_path(home=self.home, ask=lambda _: '0')

    def test_no_candidates_asks_actual_explicit_path_then_confirmation(self):
        save = self.save(self.home / 'unlisted')
        answers = iter([str(save), 'yes'])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(choose_path(home=self.home, ask=lambda _: next(answers)), str(save))
            with self.assertRaises(ValueError):
                choose_path(home=self.home, ask=lambda _: '')


if __name__ == '__main__':
    unittest.main()
