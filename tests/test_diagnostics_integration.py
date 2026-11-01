"""Real create_app ASGI paths, synthetic local sessions, no external services."""
import io
import json
import logging
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import httpx
from starlette.routing import Route
from starlette.testclient import TestClient
from diagnostics.preview import preview_script
from diagnostics.report import build_report
from remote_server.observability import valid_event
from remote_server.app import Config, create_app
import test_remote_service as service

SECRET = 'SENTINEL-private-token-path-SteamID-76561198000009999'

class IntegratedDiagnosticsTests(unittest.TestCase):
    sign_in = service.RemoteTests.sign_in
    csrf = service.RemoteTests.csrf
    oauth = service.RemoteTests.oauth
    mcp = service.RemoteTests.mcp

    def setUp(self):
        names = ['', 'game_assist.safe_events', 'httpx', 'httpcore', 'uvicorn', 'uvicorn.error', 'uvicorn.access']
        names += [name for name in logging.Logger.manager.loggerDict
                  if name.startswith(('httpx.', 'httpcore.', 'uvicorn.')) and name not in names]
        self.logging_state = [(logging.getLogger(n), logging.getLogger(n).handlers[:],
            logging.getLogger(n).level, logging.getLogger(n).propagate, logging.getLogger(n).disabled) for n in names]
        self.output = io.StringIO()
        self.stdout = patch('sys.stdout', self.output); self.stdout.start()
        self.temp = tempfile.TemporaryDirectory()
        self.steam = service.FakeSteam()
        self.app = create_app(Config(service.ORIGIN, str(Path(self.temp.name)/'test.db'), (service.REDIRECT,)), self.steam)
        self.client = TestClient(self.app, base_url=service.ORIGIN, follow_redirects=False, raise_server_exceptions=False)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup(); self.stdout.stop()
        for logger, handlers, level, propagate, disabled in self.logging_state:
            logger.handlers[:] = handlers; logger.setLevel(level)
            logger.propagate = propagate; logger.disabled = disabled

    def events(self):
        events = [json.loads(line) for line in self.output.getvalue().splitlines()]
        self.assertTrue(all(valid_event(e) for e in events))
        self.assertNotIn(SECRET, self.output.getvalue())
        return events

    def check_response(self, response):
        event = self.events()[-1]
        self.assertEqual(event['request_id'], response.headers['x-request-id'])
        self.assertRegex(event['request_id'], r'^[0-9a-f]{32}$')
        self.assertEqual(event['status'], response.status_code)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(response.headers['referrer-policy'], 'strict-origin')
        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
        self.assertEqual(response.headers['strict-transport-security'], 'max-age=31536000')
        self.assertIn("frame-ancestors 'none'", response.headers['content-security-policy'])
        self.assertNotIn('access-control-allow-origin', response.headers)
        return event

    def test_normal_unknown_and_outer_error_paths_preserve_security(self):
        health = self.client.get('/healthz', headers={'x-request-id': 'a'*32, 'cookie': SECRET})
        event = self.check_response(health)
        self.assertEqual(event['category'], 'health')
        self.assertNotEqual(event['request_id'], 'a'*32)
        event = self.check_response(self.client.get('/'+SECRET+'?private='+SECRET))
        self.assertEqual(event['category'], 'unknown')
        self.assertEqual(event['reason'], 'not_found')
        event = self.check_response(self.client.get('/healthz', headers={'host': 'wrong.example'}))
        self.assertEqual(event['status'], 400)
        async def fail(request):
            raise RuntimeError(SECRET)
        self.app.routes.insert(0, Route('/synthetic-failure', fail))
        response = self.client.get('/synthetic-failure')
        event = self.check_response(response)
        self.assertEqual((response.status_code, event['reason']), (500, 'internal_error'))
        self.assertNotIn(SECRET, response.text)
        self.assertEqual(len({e['request_id'] for e in self.events()}), 4)

    def test_origin_csrf_and_body_limits_are_still_enforced(self):
        self.sign_in()
        for origin, classification in [('null', 'null'), ('https://other.example', 'other')]:
            response = self.client.post('/logout', data={'csrf': SECRET}, headers={'origin': origin})
            event = self.check_response(response)
            self.assertEqual((response.status_code, event['reason'], event['origin']), (403, 'origin_denied', classification))
        response = self.client.post('/logout', data={'csrf': SECRET})
        self.assertEqual(self.check_response(response)['reason'], 'origin_denied')
        response = self.client.post('/logout', data={'csrf': SECRET}, headers={'origin': service.ORIGIN})
        self.assertEqual(self.check_response(response)['reason'], 'csrf_denied')
        self.assertEqual(response.status_code, 403)
        response = self.client.post('/v1/device/observations', content=SECRET*600,
            headers={'authorization': 'Bearer '+SECRET})
        self.assertEqual(self.check_response(response)['status'], 413)
        response = self.client.get('/healthz?'+SECRET*300)
        self.assertEqual(self.check_response(response)['status'], 414)
        # Failed guards did not revoke or replace the session.
        self.assertEqual(self.client.get('/games').status_code, 200)

    def test_pairing_pending_and_expired_codes_without_credential_correlation(self):
        first = self.client.post('/v1/devices/pair/start', json={})
        first_event = self.check_response(first)
        self.assertEqual((first_event['category'], first_event['reason']), ('pair_start', 'pairing_pending'))
        pair = first.json()
        response = self.client.post('/v1/devices/pair/poll', json={'device_code': pair['device_code']})
        pending = self.check_response(response)
        self.assertEqual((pending['category'], pending['reason']), ('pair_poll', 'pairing_pending'))
        self.assertNotEqual(first_event['request_id'], pending['request_id'])
        response = self.client.post('/v1/devices/pair/poll', json={'device_code': SECRET})
        self.assertEqual(self.check_response(response)['reason'], 'pairing_expired')
        self.assertNotIn(pair['device_code'], self.output.getvalue())
        self.assertNotIn(pair['user_code'], self.output.getvalue())
        # Backward-compatible body: no new required fields or correlation credentials.
        self.assertEqual(set(pair), {'device_code','user_code','verification_uri','expires_in','interval','appid','scopes'})

    def test_preview_is_session_only_readonly_and_has_no_submission(self):
        self.assertEqual(self.client.get('/diagnostics').status_code, 401)
        self.sign_in()
        response = self.client.get('/diagnostics')
        self.assertEqual(response.status_code, 200)
        self.check_response(response)
        self.assertIn("connect-src 'none'", response.headers['content-security-policy'])
        self.assertIn('Отправка отчётов пока отключена', response.text)
        self.assertIn('type="button"', response.text)
        self.assertNotIn('<form', response.text)
        self.assertNotIn('76561198000000001', response.text)
        css = self.client.get('/assets/console.css')
        self.assertEqual(css.status_code, 200)
        self.assertIn('text/css', css.headers['content-type'])
        self.assertIn('color-scheme:dark', css.text)
        self.assertIn('white-space:pre-wrap', css.text)
        self.assertIn('overflow-wrap:anywhere', css.text)
        self.assertIn('min-height:48px', css.text)
        script = self.client.get('/assets/diagnostics.js')
        self.assertEqual(script.status_code, 200)
        for forbidden in ('fetch(', 'XMLHttpRequest', 'sendBeacon', 'localStorage', 'sessionStorage', 'innerHTML', 'navigator.'):
            self.assertNotIn(forbidden, script.text)
        with self.app.state.store.db() as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        self.assertFalse(any('diagnostic' in name for name in tables))
        for path in ('/diagnostics', '/account/diagnostics/preview', '/account/diagnostics/confirm'):
            self.assertIn(self.client.post(path, json={'logs': SECRET}, headers={'origin':service.ORIGIN}).status_code, (404,405))
        token = self.oauth()
        listing = self.mcp(token, 'tools/list').json()['result']['tools']
        self.assertFalse(any('diagnostic' in tool['name'] or 'report' in tool['name'] for tool in listing))
        # A progress.read bearer credential is not a browser session.
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/diagnostics', headers={'authorization': 'Bearer '+token}).status_code, 401)
        self.events()

    def test_actual_oauth_and_httpx_verbose_logs_never_reach_stdout_sink(self):
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger('httpx').setLevel(logging.DEBUG)
        self.sign_in()
        token = self.oauth()
        response = self.client.get('/healthz?steamid='+SECRET, headers={'authorization':'Bearer '+SECRET})
        self.check_response(response)
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as upstream:
            upstream.get('https://synthetic.example/?key='+SECRET+'&steamid=76561198000000001')
        logging.getLogger('uvicorn.error').error('Exception '+SECRET, exc_info=True)
        self.assertNotIn(token, self.output.getvalue())
        self.assertNotIn('76561198000000001', self.output.getvalue())
        self.assertTrue(self.events())

    def test_entrypoint_keeps_safe_logging_configuration(self):
        from remote_server.__main__ import main
        with patch('remote_server.__main__.server_options', return_value={'access_log':False}), \
             patch('remote_server.__main__.Config.from_env', return_value=self.app.state.config), \
             patch('remote_server.__main__.create_app', return_value=self.app), \
             patch('remote_server.__main__.uvicorn.run') as run:
            main()
        self.assertIsNone(run.call_args.kwargs['log_config'])
        self.assertFalse(run.call_args.kwargs['access_log'])


class BrowserContractTests(unittest.TestCase):
    def test_browser_validator_matches_python(self):
        # Execute the actual served JS validator and UI with a tiny DOM harness.
        valid = build_report(component='web', stage='pairing')
        script = preview_script()
        harness = r'''
const assert = require('node:assert/strict');
assert.deepEqual(validateReport(VALID), VALID);
for (const [key, value] of [['logs','SECRET'],['schema_version',true],['http_status','200'],
 ['http_status',600],['request_id','a'.repeat(32)+'\n'],['app_version','1.2.3\n']]) {
 assert.throws(() => validateReport({...VALID, [key]:value}), /invalid_diagnostic_report/);
}
assert.throws(() => validateReport({...VALID, reason:'SECRET'}));
'''.replace('VALID', json.dumps(valid))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'contract.cjs'; path.write_text(script+'\n'+harness)
            result = subprocess.run(['node', str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_browser_script_previews_downloads_and_invalidates_locally(self):
        valid = build_report(component='web', stage='unknown')
        harness = r'''const vm = require('node:vm');
const assert = require('node:assert/strict');
const facts = VALID;
const elements = {};
for (const [key, value] of Object.entries(facts)) {
  elements[key] = {value: value === null ? (key === 'venv_available' ? 'unknown' : '') : String(value)};
}
for (const id of ['report-preview','report-error','download-report','prepare-report','reset-report']) elements[id] = {};
for (const key of Object.keys(facts)) elements[key + '-error'] = {};
for (const el of Object.values(elements)) {
  el.attrs = {}; el.setAttribute = (k,v) => {el.attrs[k] = v;};
  el.removeAttribute = k => {delete el.attrs[k];}; el.focus = () => {}; el.closest = () => null;
  el.handlers = {}; el.textContent = ''; el.disabled = true;
  el.addEventListener = (name, fn) => {el.handlers[name] = fn;};
}
let downloads = 0, blobs = 0;
const context = {
 document: {
  getElementById: id => elements[id],
  querySelectorAll: () => Object.keys(facts).filter(k => k !== 'schema_version').map(k => elements[k]),
  createElement: () => ({click: () => {downloads += 1;}})
 },
 URL: {createObjectURL: () => {blobs += 1; return 'blob:synthetic';}, revokeObjectURL: () => {}},
 Blob, TextEncoder, setTimeout: fn => fn(),
 fetch: () => {throw Error('unexpected network');},
 localStorage: {setItem: () => {throw Error('unexpected persistence');}}
};
elements.app_version.value = '';
elements.python_version.value = '';
vm.runInNewContext(SCRIPT, context);
assert.equal(elements['report-preview'].textContent, '');
assert.equal(downloads, 0);
elements['prepare-report'].handlers.click();
assert.deepEqual(JSON.parse(elements['report-preview'].textContent), facts);
assert.equal(elements['download-report'].disabled, false);
assert.equal(downloads, 0); // Preparing never downloads or submits.
elements['download-report'].handlers.click();
assert.equal(downloads, 1); assert.equal(blobs, 1);
elements.reason.value = 'SENTINEL-secret';
elements.reason.handlers.input();
assert.equal(elements['download-report'].disabled, true);
assert.equal(elements['report-preview'].textContent, '');
elements['download-report'].handlers.click();
assert.equal(downloads, 1);
elements['prepare-report'].handlers.click();
assert.equal(elements['download-report'].disabled, true);
assert.equal(elements['report-preview'].textContent, '');
assert.ok(!elements['report-error'].textContent.includes('SENTINEL'));
assert.equal(elements.reason.attrs['aria-invalid'], 'true');
assert.ok(elements['reason-error'].textContent.length > 0);
elements['reset-report'].handlers.click();
assert.equal(elements.reason.value, 'unknown');
assert.equal(elements['reason-error'].textContent, '');
assert.equal(elements.reason.attrs['aria-invalid'], undefined);
elements.http_status.value = '999';
elements['prepare-report'].handlers.click();
assert.equal(elements['download-report'].disabled, true);
assert.equal(elements.http_status.attrs['aria-invalid'], 'true');
assert.ok(elements['http_status-error'].textContent.includes('100'));
assert.equal(downloads, 1);
elements['reset-report'].handlers.click();
assert.equal(elements.http_status.value, '');
assert.equal(elements['report-preview'].textContent, '');
assert.equal(elements['download-report'].disabled, true);
assert.equal(elements.component.value, 'web');
'''.replace('VALID', json.dumps(valid)).replace('SCRIPT', json.dumps(preview_script()))
        result = subprocess.run(['node', '-e', harness], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
