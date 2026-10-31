"""Browser-shaped consent acceptance; all identities and Steam data are synthetic.

Uses actual local ASGI OAuth/MCP endpoints. Never contacts Claude or Steam.
"""
import base64
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from urllib.parse import parse_qs, urlsplit

from starlette.testclient import TestClient
from remote_server.app import Config, create_app
from test_remote_service import FakeSteam
from test_remote_library import FakeLibrary


ORIGIN = 'https://consent-acceptance.example'
CALLBACK = 'https://claude.ai/api/mcp/auth_callback'
VERIFIER = 'synthetic-pkce-verifier-' * 3


class ConsentForm(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.inputs = {}
        self.in_form = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.in_form = True
        if self.in_form and tag == 'input' and attrs.get('name'):
            self.inputs[attrs['name']] = attrs

    def handle_endtag(self, tag):
        if tag == 'form':
            self.in_form = False

    def default_submission(self):
        # Browsers omit unchecked checkboxes. Do not infer consent from value=yes.
        return {name: field.get('value', '') for name, field in self.inputs.items()
                if field.get('type') == 'hidden'
                or (field.get('type') == 'checkbox' and 'checked' in field)}


class MCPConsentAcceptance(unittest.TestCase):
    def database(self):
        return None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.steam, self.library = FakeSteam(), FakeLibrary()
        self.app = create_app(Config(ORIGIN, str(Path(self.temp.name)/'acceptance.sqlite'),
            (CALLBACK,)), steam=self.steam, database=self.database(),
            achievement_reader=SimpleNamespace(configured=False), library_reader=self.library)
        self.http = TestClient(self.app, base_url=ORIGIN, follow_redirects=False)
        self.http.__enter__()
        self.addCleanup(self.http.__exit__, None, None, None)

    def call(self, credentials, name):
        response = self.http.post('/mcp', json={'jsonrpc':'2.0','id':1,
            'method':'tools/call','params':{'name':name,'arguments':{}}}, headers={
                'authorization':'Bearer '+credentials['access_token'],
                'accept':'application/json, text/event-stream'})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()['result']
        self.assertFalse(result.get('isError'), result)
        return json.loads(result['content'][0]['text'])

    def authorize(self, client_id, state):
        challenge = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip('=')
        response = self.http.get('/authorize', params={'client_id':client_id,
            'redirect_uri':CALLBACK,'response_type':'code','scope':'progress.read library.read',
            'state':state,'code_challenge':challenge,'code_challenge_method':'S256',
            'resource':ORIGIN+'/mcp'})
        self.assertEqual(response.status_code,302,response.text)
        return response.headers['location']

    def consent(self, location, client_id, state, *, allow_library):
        page = self.http.get(location)
        self.assertEqual(page.status_code,200,page.text)
        form = ConsentForm(page.text)
        checkbox = form.inputs['library_read']
        self.assertEqual(checkbox['type'],'checkbox')
        self.assertNotIn('checked',checkbox)
        submission = form.default_submission()
        self.assertNotIn('library_read',submission)
        if allow_library:
            submission['library_read'] = 'yes'
        approved = self.http.post('/oauth/consent',data=submission,headers={'origin':ORIGIN})
        self.assertEqual(approved.status_code,303,approved.text)
        callback = urlsplit(approved.headers['location'])
        self.assertEqual(callback.scheme+'://'+callback.netloc+callback.path,CALLBACK)
        params = parse_qs(callback.query)
        self.assertEqual(params['state'],[state])
        self.assertEqual(params['iss'],[ORIGIN+'/'])
        response = self.http.post('/token',data={'client_id':client_id,
            'grant_type':'authorization_code','code':params['code'][0],'redirect_uri':CALLBACK,
            'code_verifier':VERIFIER,'resource':ORIGIN+'/mcp'})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def rotate(self, client_id, credentials, scope=None):
        data = {'client_id':client_id,'grant_type':'refresh_token',
                'refresh_token':credentials['refresh_token'],'resource':ORIGIN+'/mcp'}
        if scope is not None:
            data['scope'] = scope
        return self.http.post('/token',data=data)

    def site_action(self, path, **fields):
        form = ConsentForm(self.http.get('/devices/approve').text)
        return self.http.post(path,data={'csrf':form.inputs['csrf']['value'],**fields},
                              headers={'origin':ORIGIN})

    def test_decline_then_reconsent_still_requires_source_opt_in(self):
        registered = self.http.post('/register',json={'redirect_uris':[CALLBACK],
            'token_endpoint_auth_method':'none','grant_types':['authorization_code','refresh_token']})
        self.assertEqual(registered.status_code,201,registered.text)
        self.assertEqual(set(registered.json()['scope'].split()),{'progress.read','library.read'})
        client_id = registered.json()['client_id']

        # Start from the AI client's authorization, then follow the Steam handoff.
        location = self.authorize(client_id,'declined-library')
        login = self.http.get(location)
        self.assertEqual(login.status_code,303)
        self.assertEqual(self.http.get(login.headers['location']).status_code,303)
        steam_state = parse_qs(urlsplit(self.steam.return_to).query)['state'][0]
        signed_in = self.http.get('/steam/callback',params={'state':steam_state,
                                                         'test_identity':'76561198000000001'})
        self.assertEqual(signed_in.status_code,303)
        self.assertEqual(signed_in.headers['location'],urlsplit(location).path+'?'+urlsplit(location).query)

        declined = self.consent(location,client_id,'declined-library',allow_library=False)
        self.assertEqual(declined['scope'],'progress.read')
        self.assertEqual(self.call(declined,'get_progress')['games'],[])
        self.assertEqual(self.call(declined,'get_library')['reason'],'oauth_library_scope_required')
        expanded = self.rotate(client_id,declined,'progress.read library.read')
        self.assertEqual(expanded.status_code,400)
        self.assertEqual(expanded.json()['error'],'invalid_scope')
        renewed = self.rotate(client_id,declined)
        self.assertEqual(renewed.status_code,200,renewed.text)
        self.assertEqual(renewed.json()['scope'],'progress.read')

        location = self.authorize(client_id,'accepted-library')
        accepted = self.consent(location,client_id,'accepted-library',allow_library=True)
        self.assertEqual(set(accepted['scope'].split()),{'progress.read','library.read'})
        self.assertEqual(self.call(accepted,'get_library')['reason'],'account_library_permission_required')
        self.assertEqual(self.library.calls,[])
        self.assertEqual(self.site_action('/account/library/permission',enabled='yes').status_code,303)
        self.assertEqual(self.call(accepted,'get_library')['reason'],'cache_not_requested')
        self.assertEqual(self.library.calls,[])
        self.assertEqual(self.site_action('/account/library/refresh').status_code,303)
        self.assertEqual(len(self.library.calls),1)
        visible = self.call(accepted,'get_library')
        self.assertEqual(visible['games'],[{'appid':1086940,'name':"Baldur's Gate 3"}])
        self.assertEqual(visible['current_game'],'unknown')
        self.assertEqual(len(self.library.calls),1)  # MCP never fetched the source.
        self.assertEqual(self.call(renewed.json(),'get_library')['games'],[])
        self.assertEqual(self.call(accepted,'get_progress')['games'],[])
        self.assertEqual(self.call(accepted,'get_connection_status')['games'],[])
        with self.app.state.store.db() as db:
            for table in ('game_registrations','game_selections','grants'):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)

        # Narrowing one family does not grant more access or modify site consent.
        narrowed = self.rotate(client_id,accepted,'progress.read')
        self.assertEqual(narrowed.status_code,200,narrowed.text)
        self.assertEqual(self.call(narrowed.json(),'get_library')['reason'],'oauth_library_scope_required')
        self.assertEqual(self.rotate(client_id,narrowed.json(),'progress.read library.read').status_code,400)


@unittest.skipUnless(os.environ.get('GA_TEST_POSTGRES_URL'), 'Disposable local PostgreSQL DSN not supplied')
class PostgresMCPConsentAcceptance(MCPConsentAcceptance):
    def database(self):
        # Reuse the existing guarded disposable DB factory; never a production DSN.
        import test_remote_postgres
        return test_remote_postgres.database()
