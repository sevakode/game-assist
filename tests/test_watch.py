import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.error

SPEC = importlib.util.spec_from_file_location('watch', Path(__file__).parents[1] / 'agent' / 'watch.py')
watch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watch)


@unittest.skipUnless(watch._supported(), 'Requires POSIX safe traversal primitives; Windows not tested')
class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'slot').mkdir()
        self.file = self.root / 'slot' / 'save.bin'
        self.file.write_bytes(b'secret save content')

    def test_metadata_and_read_only(self):
        before = self.file.stat()
        data = watch.snapshot([self.root])
        self.assertEqual(data, [{'name': 'slot/save.bin', 'size': 19,
                                'sha256': hashlib.sha256(b'secret save content').hexdigest(),
                                'modified_ns': before.st_mtime_ns}])
        self.assertEqual(self.file.read_bytes(), b'secret save content')
        self.assertEqual(self.file.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertNotIn(str(self.root), json.dumps(data))
        self.assertNotIn('secret save content', json.dumps(data))

    def test_symlink_and_ancestor_rejected(self):
        (self.root / 'link').symlink_to(self.root / 'slot', target_is_directory=True)
        for path in (self.root, self.root / 'link', self.root / 'link' / 'save.bin'):
            with self.subTest(path=path), self.assertRaises(watch.SnapshotError):
                watch.snapshot([path])

    def test_parent_traversal_rejected(self):
        with self.assertRaises(watch.SnapshotError):
            watch.snapshot([str(self.root / 'slot') + '/../slot'])

    def test_missing_or_inaccessible_root_is_not_empty(self):
        with self.assertRaises(watch.SnapshotError):
            watch.snapshot([self.root / 'missing'])
        with mock.patch.object(watch.os, 'open', side_effect=PermissionError), self.assertRaises(watch.SnapshotError):
            watch.snapshot([self.root])

    def test_changed_during_read_rejected(self):
        original = os.read
        def changing_read(fd, count):
            data = original(fd, count)
            self.file.write_bytes(b'new content')
            return data
        with mock.patch.object(watch.os, 'read', side_effect=changing_read), self.assertRaises(watch.SnapshotError):
            watch.snapshot([self.root])

    def test_root_replaced_during_observation(self):
        original = watch._open_root
        count = 0
        def replacing_open(path):
            nonlocal count
            count += 1
            if count == 2:
                self.file.unlink()
                (self.root / 'slot').rmdir()
                self.root.rmdir()
                self.root.mkdir()
            return original(path)
        with mock.patch.object(watch, '_open_root', side_effect=replacing_open), self.assertRaises(watch.SnapshotError):
            watch.snapshot([self.root])

    def test_all_budgets_fail_closed(self):
        for key, value in [('MAX_FILE_BYTES', 1), ('MAX_TOTAL_BYTES', 1),
                           ('MAX_FILES', 0), ('MAX_ENTRIES', 0), ('MAX_DEPTH', 0)]:
            with self.subTest(key=key), mock.patch.object(watch, key, value), self.assertRaises(watch.SnapshotError):
                watch.snapshot([self.root])

    def test_empty_directory_valid(self):
        self.file.unlink()
        self.assertEqual(watch.snapshot([self.root]), [])

    def test_names_escape_controls_and_backslashes(self):
        (self.root / 'bad\nname\\test').write_bytes(b'x')
        names = [entry['name'] for entry in watch.snapshot([self.root])]
        self.assertIn('bad%0Aname%5Ctest', names)

    def test_multiple_roots_disambiguated(self):
        items = watch.snapshot([self.file, self.file])
        self.assertEqual([i['name'] for i in items], ['root-1/save.bin', 'root-2/save.bin'])


class WatchTests(unittest.TestCase):
    def run_once(self, samples):
        with mock.patch.dict(os.environ, {'SGC_TOKEN': 'test-token'}), \
             mock.patch.object(watch, 'snapshot', side_effect=samples), \
             mock.patch.object(watch, 'send', return_value=200) as send, \
             mock.patch.object(watch.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
            result = watch.main(['--path', '/explicit', '--once', '--interval', '.01'])
            return result, send.call_args_list

    def test_debounce_once(self):
        records = [{'name': 'save', 'size': 1, 'sha256': 'a', 'modified_ns': 1}]
        result, calls = self.run_once([records, records])
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[-1], records)

    def test_unstable_once_never_sends(self):
        result, calls = self.run_once([[{'name': 'a'}], [{'name': 'b'}]])
        self.assertEqual(result, 1)
        self.assertEqual(calls, [])

    def test_scan_error_never_clears(self):
        for samples in ([watch.SnapshotError('missing')], [[{'name': 'a'}], watch.SnapshotError('denied')]):
            result, calls = self.run_once(samples)
            self.assertEqual(result, 1)
            self.assertEqual(calls, [])

    def test_unsupported_platform_fails_closed(self):
        with mock.patch.object(watch, '_supported', return_value=False), self.assertRaises(watch.SnapshotError):
            watch.snapshot(['/explicit'])

    def test_interval_validation(self):
        for value in ('0', '-1', 'nan', 'inf'):
            with self.subTest(value=value), self.assertRaises(watch.argparse.ArgumentTypeError):
                watch._positive(value)

    def test_url_restrictions(self):
        for url in ('https://localhost', 'http://example.com', 'http://127.0.0.2',
                    'http://localhost@evil.test', 'http://localhost/path',
                    'http://localhost?x=1', 'http://localhost#fragment',
                    'http://localhost:99999', 'file:///tmp/x'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                watch.validate_url(url)
        self.assertEqual(watch.validate_url('http://localhost:8000/'), 'http://127.0.0.1:8000')
        self.assertEqual(watch.validate_url('http://[::1]:8000'), 'http://[::1]:8000')

    def test_redirect_refused_and_payload_metadata_only(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append((self.path, self.headers.get('Authorization'),
                                 json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(307)
                self.send_header('Location', '/redirect-target')
                self.end_headers()
            def log_message(self, *args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(urllib.error.HTTPError):
                watch.send('http://127.0.0.1:' + str(server.server_port), 'test-token', 4231820, [])
            self.assertEqual(requests, [('/v1/observations', 'Bearer test-token',
                                        {'appid': 4231820, 'kind': 'save_metadata', 'payload': {'files': []}})])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


@unittest.skipUnless(watch._supported(), 'Requires POSIX safe traversal; Windows untested')
class BelmontWatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / 'synthetic.json'
        self.raw = json.dumps({'version': '1.1.3', 'playerSave': {
            'healthUpgradeFragmentCount': 2, 'manaUpgradeFragmentCount': 3,
            'currentHealth': 7.5, 'currentMana': 8}, 'worldSaves': {
            'm_keys': ['PRIVATE_WORLD'], 'm_values': [{'savableEntityStates': {
                'm_keys': ['PRIVATE_ENTITY'], 'm_values': ['{"activated":true,"fileID":"PRIVATE_FILE"}']}}]}}).encode()
        self.file.write_bytes(self.raw)

    def invoke(self, extra=(), summary_error=None):
        with mock.patch.dict(os.environ, {'SGC_TOKEN': 'test'}), \
             mock.patch.object(watch.time, 'sleep'), \
             mock.patch.object(watch, 'send', return_value=200) as metadata, \
             mock.patch.object(watch, 'send_summary', return_value=200, side_effect=summary_error) as summary, \
             contextlib.redirect_stdout(io.StringIO()):
            code = watch.main(['--path', str(self.file), '--once', '--interval', '.01', *extra])
            return code, metadata.call_args_list, summary.call_args_list

    def test_opt_in_summary_only_allowlisted_fields(self):
        before = self.file.stat()
        code, metadata, summaries = self.invoke(['--decode-belmont'])
        self.assertEqual(code, 0)
        self.assertEqual(len(metadata), 0)
        self.assertEqual(len(summaries), 1)
        summary = summaries[0].args[-1]
        self.assertEqual(summary['format_version'], '1.1.3')
        self.assertEqual(summary['player_scalars']['currentHealth']['value'], 7.5)
        self.assertEqual(len(summary['player_scalars']), 4)
        for forbidden in ('PRIVATE_WORLD', 'PRIVATE_ENTITY', 'PRIVATE_FILE', 'activated', str(self.file)):
            self.assertNotIn(forbidden, json.dumps(summary))
        self.assertIn('not maxima', ' '.join(summary['semantic_caveats']))
        self.assertEqual(self.file.read_bytes(), self.raw)
        self.assertEqual(self.file.stat().st_mtime_ns, before.st_mtime_ns)

    def test_decode_default_off(self):
        with mock.patch.object(watch, 'belmont_summary', side_effect=AssertionError('must not decode')):
            code, metadata, summaries = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(len(metadata), 1)
        self.assertEqual(summaries, [])

    def test_unknown_version_rejected_without_sending(self):
        self.file.write_bytes(b'{"version":"future"}')
        code, metadata, summaries = self.invoke(['--decode-belmont'])
        self.assertEqual(code, 1)
        self.assertEqual(metadata, [])
        self.assertEqual(summaries, [])

    def test_malformed_source_rejected(self):
        self.file.write_bytes(b'not-json')
        code, metadata, summaries = self.invoke(['--decode-belmont'])
        self.assertEqual((code, metadata, summaries), (1, [], []))

    def test_scope_denial_nonzero_no_clear_request(self):
        error = urllib.error.HTTPError('http://127.0.0.1', 403, 'scope denied', {}, None)
        code, metadata, summaries = self.invoke(['--decode-belmont'], summary_error=error)
        self.assertEqual(code, 1)
        self.assertEqual(len(metadata), 0)
        self.assertEqual(len(summaries), 1)
        self.assertTrue(summaries[0].args[-1]['player_scalars'])

    def test_directory_rejected_before_scanning(self):
        with mock.patch.object(watch.os, 'scandir', side_effect=AssertionError('must not scan')):
            with self.assertRaises(watch.SnapshotError):
                watch.snapshot([self.file.parent], single_file_only=True)

    def test_changed_after_debounce_rejected(self):
        records = watch.snapshot([self.file])
        self.file.write_bytes(self.raw + b' ')
        with self.assertRaises(watch.SnapshotError):
            watch.belmont_summary(self.file, records)

    def test_symlink_source_rejected(self):
        records = watch.snapshot([self.file])
        link = self.file.parent / 'link'
        link.symlink_to(self.file)
        with self.assertRaises(watch.SnapshotError):
            watch.belmont_summary(link, records)

    def test_decode_appid_and_single_path_required(self):
        for extra in (['--appid', '1'], ['--path', 'another']):
            with self.subTest(extra=extra), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                self.invoke(['--decode-belmont', *extra])
            self.assertEqual(caught.exception.code, 2)

    def test_direct_script_sends_only_safe_summary(self):
        import subprocess
        import sys
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')
            def log_message(self, *args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            completed = subprocess.run([
                sys.executable, str(Path(watch.__file__).resolve()), '--path', str(self.file),
                '--once', '--interval', '.01', '--decode-belmont',
                '--url', 'http://127.0.0.1:' + str(server.server_port)],
                env={**os.environ, 'SGC_TOKEN': 'synthetic-token'},
                cwd=self.temp.name, capture_output=True, text=True, timeout=10)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual([item['kind'] for item in requests], ['save_summary'])
            self.assertEqual(requests[0]['payload']['format_version'], '1.1.3')
            for forbidden in ('PRIVATE_WORLD', 'PRIVATE_ENTITY', 'PRIVATE_FILE', 'activated'):
                self.assertNotIn(forbidden, json.dumps(requests))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_import_does_not_modify_search_path(self):
        import sys
        original = list(sys.path)
        watch._belmont_decoder()
        self.assertEqual(sys.path, original)


if __name__ == '__main__':
    unittest.main()
