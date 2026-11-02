"""Synthetic OAuth + account-consent + cached library MCP flow."""
import base64
import hashlib
import json
import re
import unittest
from consent_fixtures import legacy_consent
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import test_remote_library as library_tests
import test_remote_service as service


class MCPLibraryTests(unittest.TestCase):
    setUp=library_tests.LibraryTests.setUp
    tearDown=library_tests.LibraryTests.tearDown
    sign_in=library_tests.LibraryTests.sign_in
    csrf=library_tests.LibraryTests.csrf
    owner=library_tests.LibraryTests.owner
    permission=library_tests.LibraryTests.permission
    refresh=library_tests.LibraryTests.refresh
    mcp=service.RemoteTests.mcp

    def register(self, scope=None):
        body={'redirect_uris':[service.REDIRECT],'token_endpoint_auth_method':'none',
              'grant_types':['authorization_code','refresh_token']}
        if scope is not None:body['scope']=scope
        response=self.client.post('/register',json=body)
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def start(self, client, scope):
        challenge=base64.urlsafe_b64encode(hashlib.sha256(('v'*64).encode()).digest()).decode().rstrip('=')
        return self.client.get('/authorize',params={'client_id':client['client_id'],
            'redirect_uri':service.REDIRECT,'response_type':'code','scope':scope,'state':'library-state',
            'code_challenge':challenge,'code_challenge_method':'S256','resource':service.ORIGIN+'/mcp'})

    @legacy_consent
    def tokens(self, client, scope, *, approve_library=True):
        response=self.start(client,scope)
        self.assertEqual(response.status_code,302,response.text)
        location=response.headers['location']
        consent=self.client.get(location).text
        self.assertEqual('library.read' in consent,'library.read' in scope.split())
        self.assertIn('progress.read',consent)
        if 'library.read' in scope.split():
            for text in ('AppID и названия','Без времени игры и иконок','не выбирает игры'):
                self.assertIn(text,consent)
            checkbox=re.search(r'<input[^>]+name="library_read"[^>]*>',consent)[0]
            self.assertIn('type="checkbox"',checkbox)
            self.assertNotIn('checked',checkbox)
        else:
            self.assertNotIn('name="library_read"',consent)
        request=parse_qs(urlsplit(location).query)['request'][0]
        form={'csrf':self.csrf(path=location),'request':request}
        if approve_library and 'library.read' in scope.split():form['library_read']='yes'
        response=self.client.post('/oauth/consent',data=form,headers={'origin':service.ORIGIN})
        self.assertEqual(response.status_code,303,response.text)
        callback=parse_qs(urlsplit(response.headers['location']).query)
        self.assertEqual(callback['state'],['library-state'])
        self.assertEqual(callback['iss'],[service.ORIGIN+'/'])
        code=callback['code'][0]
        token_payload={'grant_type':'authorization_code','code':code,
            'client_id':client['client_id'],'redirect_uri':service.REDIRECT,
            'code_verifier':'v'*64,'resource':service.ORIGIN+'/mcp'}
        self.assertEqual(self.client.post('/token',data=token_payload | {'code_verifier':'wrong'}).status_code,400)
        response=self.client.post('/token',data=token_payload)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.post('/token',data=token_payload).status_code,400)
        expected=set(scope.split()) if approve_library else {'progress.read'}
        self.assertEqual(set(response.json()['scope'].split()),expected)
        return response.json()

    def rotate(self, client, tokens, scope=None):
        body={'grant_type':'refresh_token','client_id':client['client_id'],
            'refresh_token':tokens['refresh_token'],'resource':service.ORIGIN+'/mcp'}
        if scope is not None:body['scope']=scope
        return self.client.post('/token',data=body)

    def read(self, tokens):
        response=self.mcp(tokens['access_token'],'tools/call',{'name':'get_library','arguments':{}})
        self.assertEqual(response.status_code,200,response.text)
        result=response.json()['result'];self.assertFalse(result.get('isError'),result)
        return json.loads(result['content'][0]['text'])

    def test_old_client_tokens_and_refresh_never_expand(self):
        self.sign_in();self.permission();self.refresh()
        old=self.register('progress.read')
        self.assertEqual(old['scope'],'progress.read')
        with self.app.state.store.db() as db:
            old_row=db.execute('SELECT data FROM oauth_clients WHERE id=?',(old['client_id'],)).fetchone()[0]
        self.assertEqual(self.register()['scope'],'progress.read library.read')
        with self.app.state.store.db() as db:
            self.assertEqual(db.execute('SELECT data FROM oauth_clients WHERE id=?',(old['client_id'],)).fetchone()[0],old_row)
        tokens=self.tokens(old,'progress.read')
        self.assertEqual(self.read(tokens)['reason'],'oauth_library_scope_required')
        attempted=self.start(old,'progress.read library.read')
        self.assertEqual(parse_qs(urlsplit(attempted.headers['location']).query)['error'],['invalid_scope'])
        self.assertEqual(self.rotate(old,tokens,'progress.read library.read').status_code,400)
        rotated=self.rotate(old,tokens)
        self.assertEqual(rotated.status_code,200,rotated.text)
        self.assertEqual(rotated.json()['scope'],'progress.read')
        self.assertEqual(self.read(rotated.json())['reason'],'oauth_library_scope_required')

    def test_default_registration_capabilities_are_not_default_consent(self):
        self.sign_in();self.permission();self.refresh()
        client=self.register()
        self.assertEqual(client['scope'],'progress.read library.read')
        declined=self.tokens(client,'progress.read library.read',approve_library=False)
        self.assertEqual(declined['scope'],'progress.read')
        result=self.read(declined)
        self.assertEqual(result['reason'],'oauth_library_scope_required')
        self.assertEqual(result['action'],'review_fresh_connection_and_library_consent')
        self.assertEqual(self.rotate(client,declined,'progress.read library.read').status_code,400)
        rotated=self.rotate(client,declined)
        self.assertEqual(rotated.status_code,200,rotated.text)
        self.assertEqual(rotated.json()['scope'],'progress.read')
        approved=self.tokens(client,'progress.read library.read',approve_library=True)
        self.assertEqual(len(self.read(approved)['games']),1)

    def test_consent_cannot_confirm_unrequested_unknown_or_invalid_scope(self):
        self.sign_in();client=self.register()
        for requested in ('progress.read','progress.read library.read'):
            response=self.start(client,requested);location=response.headers['location']
            request=parse_qs(urlsplit(location).query)['request'][0]
            csrf=self.csrf(path=location)
            changes=[{'library_read':'no'},{'library_read':'true'},{'library_read':''},
                {'scope':'progress.read library.read'},{'granted_scopes':'activity.read'}]
            if requested=='progress.read':changes.append({'library_read':'yes'})
            for extra in changes:
                with self.subTest(requested=requested,extra=extra):
                    answer=self.client.post('/oauth/consent',data={'csrf':csrf,'request':request,**extra},
                        headers={'origin':service.ORIGIN})
                    self.assertIn(answer.status_code,(400,422))
                    self.assertNotIn('location',answer.headers)
                    self.assertIsNotNone(self.app.state.provider.get_pending(request))
            with self.app.state.store.db() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM oauth_codes').fetchone()[0],0)

    def test_registration_rejects_unsupported_or_unusable_scopes(self):
        for scope in ('library.read','progress.read activity.read','progress.write'):
            response=self.client.post('/register',json={'redirect_uris':[service.REDIRECT],
                'token_endpoint_auth_method':'none','scope':scope})
            self.assertEqual(response.status_code,400,response.text)

    def test_missing_authorization_scope_is_controlled_without_pending_grant(self):
        challenge=base64.urlsafe_b64encode(hashlib.sha256(('v'*64).encode()).digest()).decode().rstrip('=')
        for registered_scope in (None,'progress.read library.read'):
            client=self.register(registered_scope)
            params={'client_id':client['client_id'],'redirect_uri':service.REDIRECT,
                'response_type':'code','state':'missing-scope-state','code_challenge':challenge,
                'code_challenge_method':'S256','resource':service.ORIGIN+'/mcp'}
            for method in ('GET','POST'):
                with self.subTest(registered_scope=registered_scope,method=method):
                    response=(self.client.get('/authorize',params=params) if method=='GET'
                        else self.client.post('/authorize',data=params))
                    self.assertEqual(response.status_code,302,response.text)
                    query=parse_qs(urlsplit(response.headers['location']).query)
                    self.assertEqual(query['error'],['invalid_scope'])
                    self.assertEqual(query['state'],['missing-scope-state'])
                    self.assertEqual(query['iss'],[service.ORIGIN+'/'])
                    self.assertNotIn('code',query)
        with self.app.state.store.db() as db:
            for table in ('oauth_pending','oauth_codes','oauth_tokens'):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)

    def test_refresh_must_retain_progress_and_rejection_does_not_consume(self):
        self.sign_in();client=self.register('progress.read library.read')
        tokens=self.tokens(client,'progress.read library.read')
        with self.app.state.store.db() as db:
            before=[tuple(row) for row in db.execute('SELECT * FROM oauth_tokens ORDER BY hash')]
        response=self.rotate(client,tokens,'library.read')
        self.assertEqual(response.status_code,400,response.text)
        self.assertEqual(response.json()['error'],'invalid_scope')
        with self.app.state.store.db() as db:
            self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM oauth_tokens ORDER BY hash')],before)
        self.assertEqual(self.mcp(tokens['access_token'],'tools/list').status_code,200)
        unchanged=self.rotate(client,tokens)
        self.assertEqual(unchanged.status_code,200,unchanged.text)
        self.assertEqual(set(unchanged.json()['scope'].split()),{'progress.read','library.read'})
        narrowed=self.rotate(client,unchanged.json(),'progress.read')
        self.assertEqual(narrowed.status_code,200,narrowed.text)
        self.assertEqual(narrowed.json()['scope'],'progress.read')
        self.assertEqual(self.read(narrowed.json())['reason'],'oauth_library_scope_required')
        self.assertEqual(self.rotate(client,narrowed.json(),'progress.read library.read').status_code,400)

    def test_both_consents_required_and_games_never_auto_selected(self):
        self.sign_in();client=self.register('progress.read library.read')
        tokens=self.tokens(client,'progress.read library.read')
        self.assertEqual(self.read(tokens)['reason'],'account_library_permission_required')
        self.assertEqual(self.permission().status_code,303)
        self.assertEqual(self.read(tokens)['reason'],'cache_not_requested')
        self.assertEqual(self.reader.calls,[])
        self.assertEqual(self.refresh().status_code,303)
        calls=list(self.reader.calls)
        with patch.object(self.reader,'get_games',side_effect=AssertionError('MCP must not fetch')):
            result=self.read(tokens)
        self.assertEqual(result['games'],[{'appid':1086940,'name':"Baldur's Gate 3"}])
        self.assertEqual(result['action'],'ask_user_which_game')
        self.assertEqual(result['current_game'],'unknown')
        self.assertEqual(self.reader.calls,calls)
        with self.app.state.store.db() as db:
            for table in ('game_selections','game_registrations','grants'):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
        progress=self.mcp(tokens['access_token'],'tools/call',{'name':'get_progress','arguments':{}})
        self.assertNotIn('1086940',progress.text)
        self.permission('no')
        self.assertEqual(self.read(tokens)['reason'],'account_library_permission_required')
        self.permission()
        self.assertEqual(self.read(tokens)['games'],[])

    def test_expired_private_empty_absent_key_are_unknown_and_read_only(self):
        self.sign_in();client=self.register('progress.read library.read')
        tokens=self.tokens(client,'progress.read library.read')
        self.permission();self.refresh()
        with self.app.state.store.db() as db:
            db.execute('UPDATE library_cache SET expires=1')
            before=tuple(db.execute('SELECT * FROM library_cache').fetchone())
        self.assertEqual(self.read(tokens)['reason'],'cache_expired')
        self.assertEqual(self.read(tokens)['games'],[])
        with self.app.state.store.db() as db:
            self.assertEqual(tuple(db.execute('SELECT * FROM library_cache').fetchone()),before)
        for status,payload in [('unavailable',None),('ok','[]')]:
            with self.app.state.store.db() as db:
                db.execute('UPDATE library_cache SET status=?,payload=?,expires=?',(status,payload,9999999999))
            result=self.read(tokens)
            self.assertEqual(result['status'],'unknown')
            self.assertEqual(result['games'],[])
        self.reader.configured=False;self.app.state.store.library_available=False
        self.assertEqual(self.read(tokens)['reason'],'operator_source_not_configured')

    def test_scope_narrowing_and_two_tenants(self):
        self.sign_in();self.permission();self.refresh()
        first=self.register('progress.read library.read')
        tokens=self.tokens(first,'progress.read library.read')
        self.client.cookies.clear();self.sign_in('76561198000000002')
        second=self.register('progress.read library.read')
        other=self.tokens(second,'progress.read library.read')
        self.assertEqual(self.read(other)['games'],[])
        substituted=self.mcp(other['access_token'],'tools/call',{'name':'get_library',
            'arguments':{'owner':'76561198000000001','appid':1086940}})
        self.assertNotIn("Baldur",substituted.text)
        self.assertEqual(len(self.read(tokens)['games']),1)
        narrowed=self.rotate(first,tokens,'progress.read')
        self.assertEqual(narrowed.status_code,200,narrowed.text)
        self.assertEqual(self.read(narrowed.json())['reason'],'oauth_library_scope_required')
        self.assertEqual(self.rotate(first,narrowed.json(),'progress.read library.read').status_code,400)
        self.assertEqual(self.rotate(first,narrowed.json()).json()['scope'],'progress.read')

    def test_full_revoke_and_refresh_do_not_restore_library_access(self):
        self.sign_in();self.permission();self.refresh()
        client=self.register('progress.read library.read')
        tokens=self.tokens(client,'progress.read library.read')
        response=self.client.post('/account/revoke',data={'csrf':self.csrf()},headers={'origin':service.ORIGIN})
        self.assertEqual(response.status_code,303)
        self.assertEqual(self.mcp(tokens['access_token'],'tools/call',{'name':'get_library','arguments':{}}).status_code,401)
        self.assertEqual(self.rotate(client,tokens).status_code,400)
        fresh=self.tokens(client,'progress.read library.read')
        self.assertEqual(self.read(fresh)['games'],[])
        self.assertEqual(self.read(fresh)['reason'],'account_library_permission_required')

    def test_only_requested_consent_and_strict_library_output(self):
        self.sign_in();client=self.register('progress.read library.read')
        progress_only=self.tokens(client,'progress.read')
        with patch.object(self.app.state.store,'library',side_effect=AssertionError('No scope')):
            self.assertEqual(self.read(progress_only)['reason'],'oauth_library_scope_required')
        tokens=self.tokens(client,'progress.read library.read')
        self.permission();self.refresh()
        with self.app.state.store.db() as db:
            db.execute('UPDATE library_cache SET payload=?',(json.dumps([{'appid':1086940,
                'name':'Synthetic title','playtime_forever':123,'img_icon_url':'SECRET',
                'steamid':'PRIVATE'}]),))
        result=self.read(tokens)
        self.assertEqual(result['games'],[{'appid':1086940,'name':'Synthetic title'}])
        for field in ('playtime','SECRET','PRIVATE','steamid','img_icon'):
            self.assertNotIn(field,json.dumps(result))
        metadata=self.client.get('/.well-known/oauth-authorization-server').json()
        resource=self.client.get('/.well-known/oauth-protected-resource/mcp').json()
        self.assertEqual(metadata['scopes_supported'],['progress.read','library.read'])
        self.assertEqual(resource['scopes_supported'],metadata['scopes_supported'])
        tool=next(t for t in self.mcp(tokens['access_token'],'tools/list').json()['result']['tools'] if t['name']=='get_library')
        self.assertEqual(tool['inputSchema']['properties'],{})
        self.assertTrue(tool['annotations']['readOnlyHint'])
        self.assertFalse(tool['annotations']['destructiveHint'])
        self.assertFalse(tool['annotations']['openWorldHint'])
