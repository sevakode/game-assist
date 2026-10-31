"""Public artifact tests use code-only synthetic staging, never real account data."""
import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

from starlette.testclient import TestClient
from remote_server.app import Config, create_app
from tools.package_deck import FILES, README, build

ROOT=Path(__file__).resolve().parents[1]

class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def test_exact_allowlist_deterministic_hash_and_no_private_files(self):
        source=self.root/'source';source.mkdir()
        for name in FILES:
            target=source/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/name,target)
        for name in ('deck/config.json','deck/token','deck/private.sav','deck/__pycache__/module.pyc','server.db','fixtures/save.sav','.env'):
            target=source/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text('SYNTHETIC-SECRET-DO-NOT-PACK')
        a,ha=build(source,self.root/'a');b,hb=build(source,self.root/'b')
        self.assertEqual(a.read_bytes(),b.read_bytes());self.assertEqual(ha,hb)
        self.assertEqual(ha,hashlib.sha256(a.read_bytes()).hexdigest())
        with zipfile.ZipFile(a) as archive:
            self.assertEqual(set(archive.namelist()),set(FILES)|{'README.md'})
            for info in archive.infolist():
                self.assertFalse(info.filename.startswith('/'));self.assertNotIn('..',Path(info.filename).parts)
                self.assertNotIn(b'SYNTHETIC-SECRET-DO-NOT-PACK',archive.read(info))
                self.assertEqual(info.date_time,(2020,1,1,0,0,0))
                self.assertEqual((info.external_attr >> 16)&0o777,0o644)

    def test_symlinked_source_rejected(self):
        source=self.root/'source';source.mkdir()
        for name in FILES:
            target=source/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,target)
        secret=self.root/'private';secret.write_text('SYNTHETIC_SECRET')
        (source/'agent/watch.py').unlink();(source/'agent/watch.py').symlink_to(secret)
        with self.assertRaises(ValueError):build(source,self.root/'output')

    def test_fixed_download_routes_setup_hash_and_missing_artifact(self):
        directory=self.root/'downloads';archive,checksum=build(ROOT,directory)
        config=Config('https://configured.example',str(self.root/'db'),('https://client.example/callback',))
        app=create_app(config,download_dir=directory)
        with TestClient(app,base_url=config.issuer) as client:
            response=client.get('/downloads/deck-companion.zip')
            self.assertEqual(response.status_code,200);self.assertEqual(response.content,archive.read_bytes())
            self.assertEqual(client.get('/downloads/deck-companion.zip.sha256').text,checksum+'  deck-companion.zip\n')
            page=client.get('/setup').text
            self.assertIn(checksum,page);self.assertIn('--server https://configured.example',page)
            self.assertIn('Desktop Mode',page);self.assertNotIn('curl |',page)
            self.assertIn('&amp;&amp;',page)
            self.assertIn('mkdir deck-companion',page)
            self.assertIn('python3 -I -m zipfile',page)
            self.assertEqual(client.get('/setup',headers={'host':'evil.example'}).status_code,400)
            for path in ('/downloads/app.py','/downloads/config.json','/downloads/../app.py','/downloads/deck-companion.zip/extra'):
                self.assertEqual(client.get(path).status_code,404)
        missing=create_app(config,download_dir=self.root/'absent')
        with TestClient(missing,base_url=config.issuer) as client:
            self.assertEqual(client.get('/downloads/deck-companion.zip').status_code,503)
            self.assertIn('ещё не собран',client.get('/setup').text)

    def test_modified_archive_fails_closed_at_start(self):
        directory=self.root/'downloads';archive,_=build(ROOT,directory)
        archive.write_bytes(archive.read_bytes()+b'changed')
        config=Config('https://configured.example',str(self.root/'db'),('https://client.example/callback',))
        with self.assertRaises(ValueError):create_app(config,download_dir=directory)
