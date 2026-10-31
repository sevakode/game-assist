"""Stdlib-only package/doctor contracts; never install or contact a user service."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

from tools.package_deck import FILES, build

ROOT = Path(__file__).resolve().parents[1]


class CompanionPackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_archive_is_deterministic_code_only_and_private_noise_excluded(self):
        source = self.root / 'source'
        for name in FILES:
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        for name in ('deck/config.json', 'deck/state.json', 'deck/private.sav', '.env'):
            (source / name).write_text('SYNTHETIC_PRIVATE_NOT_FOR_ARCHIVE')
        first, digest = build(source, self.root / 'first')
        second, second_digest = build(source, self.root / 'second')
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(digest, second_digest)
        self.assertEqual(digest, hashlib.sha256(first.read_bytes()).hexdigest())
        with zipfile.ZipFile(first) as archive:
            self.assertEqual(set(archive.namelist()), set(FILES) | {'README.md'})
            for entry in archive.infolist():
                self.assertEqual(entry.date_time, (2020, 1, 1, 0, 0, 0))
                self.assertEqual(entry.external_attr >> 16 & 0o777, 0o644)
                self.assertNotIn(b'SYNTHETIC_PRIVATE', archive.read(entry))

    def test_extracted_archive_doctor_works_without_site_packages_or_systemctl(self):
        archive, _ = build(ROOT, self.root / 'archive')
        extracted = self.root / 'extracted'
        with zipfile.ZipFile(archive) as package:
            package.extractall(extracted)
        home = self.root / 'home'
        home.mkdir()
        # No PATH/systemd session inherited; no real systemctl can be located.
        env = {'HOME': str(home), 'PATH': '', 'PYTHONDONTWRITEBYTECODE': '1'}
        script = """
import runpy, sys
sys.path.insert(0, sys.argv.pop(1))
sys.argv = ['deck', 'doctor']
runpy.run_module('deck', run_name='__main__')
"""
        result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', script, str(extracted)],
                                cwd=extracted, env=env, text=True, capture_output=True,
                                timeout=15, check=True)
        diagnostic = json.loads(result.stdout)
        self.assertEqual(diagnostic['installation'], 'missing')
        self.assertEqual(diagnostic['pairing'], 'missing')
        self.assertEqual(diagnostic['service'], 'unavailable')
        self.assertEqual(diagnostic['network'], 'not_tested')
        self.assertEqual(list(home.iterdir()), [])
        self.assertNotIn(str(home), result.stdout)

    def test_archive_rejects_symlinked_code(self):
        source = self.root / 'source'
        for name in FILES:
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        target = source / 'deck/client.py'
        target.unlink()
        target.symlink_to(ROOT / 'deck/client.py')
        with self.assertRaises(ValueError):
            build(source, self.root / 'archive')
