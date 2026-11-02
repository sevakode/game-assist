"""Serialized MCP metadata on a local OAuth/PKCE client; no external services."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from consent_fixtures import legacy_consent
from urllib.parse import parse_qs, urlsplit

from starlette.testclient import TestClient

from remote_server.app import Config, create_app
import test_remote_service as service
from test_remote_browser_flows import FormReader

TITLES = {
    'get_progress': 'Read permitted game progress',
    'suggest_next_step': 'Clarify the next step',
    'get_connection_status': 'Check connection status',
    'get_library': 'Read cached game library',
}


class MCPToolMetadataTests(unittest.TestCase):
    sign_in = service.RemoteTests.sign_in

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.steam = service.FakeSteam()
        self.app = create_app(
            Config(service.ORIGIN, str(Path(self.temp.name)/'metadata.sqlite'),
                   (service.REDIRECT,)), steam=self.steam,
            achievement_reader=SimpleNamespace(configured=False),
            library_reader=SimpleNamespace(configured=False))
        self.client = TestClient(self.app, base_url=service.ORIGIN, follow_redirects=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.sign_in()

    @legacy_consent
    def credentials(self, scope='progress.read'):
        registered = self.client.post('/register', json={
            'redirect_uris':[service.REDIRECT], 'token_endpoint_auth_method':'none',
            'scope':scope})
        self.assertEqual(registered.status_code, 201)
        client_id = registered.json()['client_id']
        verifier = 'synthetic-tool-metadata-verifier-' * 2
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        authorize = self.client.get('/authorize', params={
            'client_id':client_id, 'redirect_uri':service.REDIRECT, 'response_type':'code',
            'scope':scope, 'state':'synthetic-metadata-state', 'code_challenge':challenge,
            'code_challenge_method':'S256', 'resource':service.ORIGIN+'/mcp'})
        self.assertEqual(authorize.status_code, 302)
        form = FormReader(self.client.get(authorize.headers['location']).text).forms[0]['fields']
        if 'library.read' in scope.split():
            form['library_read'] = 'yes'
        approved = self.client.post('/oauth/consent', data=form, headers={'origin':service.ORIGIN})
        self.assertEqual(approved.status_code, 303)
        callback = parse_qs(urlsplit(approved.headers['location']).query)
        self.assertEqual(callback['state'], ['synthetic-metadata-state'])
        exchanged = self.client.post('/token', data={
            'client_id':client_id, 'grant_type':'authorization_code', 'code':callback['code'][0],
            'redirect_uri':service.REDIRECT, 'code_verifier':verifier, 'resource':service.ORIGIN+'/mcp'})
        self.assertEqual(exchanged.status_code, 200)
        self.assertEqual(exchanged.json()['scope'], scope)
        return exchanged.json()['access_token']

    def rpc(self, token, method, params=None):
        headers = {'accept':'application/json, text/event-stream'}
        if token:
            headers['authorization'] = 'Bearer '+token
        return self.client.post('/mcp', json={
            'jsonrpc':'2.0', 'id':1, 'method':method, 'params':params or {}}, headers=headers)

    def listed(self, token):
        response = self.rpc(token, 'tools/list')
        self.assertEqual(response.status_code, 200)
        return response.json()['result']['tools']

    def called(self, token, name):
        response = self.rpc(token, 'tools/call', {'name':name, 'arguments':{}})
        self.assertEqual(response.status_code, 200)
        result = response.json()['result']
        self.assertFalse(result.get('isError'), result)
        return json.loads(result['content'][0]['text'])

    def test_serialized_tools_have_neutral_titles_and_original_contracts(self):
        tools = self.listed(self.credentials())
        self.assertEqual({tool['name'] for tool in tools}, set(TITLES))
        for tool in tools:
            with self.subTest(name=tool['name']):
                self.assertEqual(tool.get('title'), TITLES[tool['name']])
                self.assertEqual(tool['annotations'], {
                    'readOnlyHint':True, 'destructiveHint':False,
                    'openWorldHint':False})
                self.assertEqual(tool['inputSchema'], {
                    'properties':{}, 'title':tool['name']+'Arguments', 'type':'object'})
                self.assertNotIn('outputSchema', tool)
                self.assertTrue(tool['description'])

    def test_metadata_does_not_grant_library_or_change_empty_outputs(self):
        progress = self.credentials()
        both = self.credentials('progress.read library.read')
        self.assertEqual(self.listed(progress), self.listed(both))
        self.assertEqual(self.rpc(None, 'tools/list').status_code, 401)
        result = self.called(progress, 'get_progress')
        self.assertIsInstance(result.pop('checked_at'), (int, float))
        self.assertEqual(result, {'spoiler_policy':'strict', 'games':[]})
        suggestion = self.called(progress, 'suggest_next_step')
        self.assertEqual(suggestion, {
            'progress':{'spoiler_policy':'strict', 'games':[]},
            'suggestion':'What is your current goal and what have you already discovered?',
            'confidence':'unknown'})
        denied = self.called(progress, 'get_library')
        self.assertEqual(denied['reason'], 'oauth_library_scope_required')
        self.assertEqual(denied['games'], [])
        unconfigured = self.called(both, 'get_library')
        self.assertEqual(unconfigured['games'], [])
        self.assertEqual(unconfigured['reason'], 'operator_source_not_configured')
        self.app.state.store.library_available = True
        opt_in_missing = self.called(both, 'get_library')
        self.assertEqual(opt_in_missing['reason'], 'account_library_permission_required')
        self.assertEqual(opt_in_missing['games'], [])
        with self.app.state.store.db() as db:
            for table in ('grants', 'game_selections', 'library_cache'):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0], 0)

    def test_singleton_strict_origin_is_retained(self):
        self.assertEqual(self.client.get('/games').headers.get_list('referrer-policy'),
                         ['strict-origin'])


if __name__ == '__main__':
    unittest.main()
