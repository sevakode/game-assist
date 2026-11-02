"""Synthetic server-bound review contracts; renderer fixture is not production UI."""
import base64
import hashlib
import json
import inspect
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs,urlsplit
from unittest.mock import patch
from starlette.testclient import TestClient
from remote_server.app import Config,create_app,COOKIE,digest
from remote_server import ui
import test_remote_service as service
import test_remote_games as games
import test_mcp_tool_metadata as metadata


class ConsolidatedConsentTests(unittest.TestCase):
    sign_in=service.RemoteTests.sign_in
    csrf=service.RemoteTests.csrf
    owner=games.GameSelectionTests.owner
    catalog=games.GameSelectionTests.catalog
    choose=games.GameSelectionTests.choose
    permission=games.GameSelectionTests.permission
    revoke=games.GameSelectionTests.revoke
    credentials=metadata.MCPToolMetadataTests.credentials
    rpc=metadata.MCPToolMetadataTests.rpc
    called=metadata.MCPToolMetadataTests.called

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.steam=service.FakeSteam()
        self.app=create_app(Config(service.ORIGIN,str(Path(self.temp.name)/'db'),(service.REDIRECT,)),
            steam=self.steam,database=self.database(),achievement_reader=SimpleNamespace(configured=True),library_reader=SimpleNamespace(configured=True))
        self.client=TestClient(self.app,base_url=service.ORIGIN,follow_redirects=False)
        self.client.__enter__();self.addCleanup(self.client.__exit__,None,None,None)
        self.sign_in()

    def database(self):
        return None

    def pending(self,scopes='progress.read library.read'):
        r=self.client.post('/register',json={'redirect_uris':[service.REDIRECT],
            'token_endpoint_auth_method':'none','scope':scopes})
        self.assertEqual(r.status_code,201);cid=r.json()['client_id']
        challenge=base64.urlsafe_b64encode(hashlib.sha256(b'x'*64).digest()).decode().rstrip('=')
        r=self.client.get('/authorize',params={'client_id':cid,'redirect_uri':service.REDIRECT,
            'response_type':'code','scope':scopes,'state':'fixture-state','resource':service.ORIGIN+'/mcp',
            'code_challenge':challenge,'code_challenge_method':'S256'})
        self.assertEqual(r.status_code,302)
        return r.headers['location'],cid

    def review(self,scopes='progress.read library.read'):
        location,cid=self.pending(scopes); captured={}
        def renderer(csrf,req,client_label,scopes,*,review_plan=None):
            captured.update(review_plan)
            return '<form method="post" action="/oauth/consent">'+ui.hidden('csrf',csrf)+ui.hidden('request',req)+ui.hidden('plan_id',review_plan['plan_id'])+'<button name="approve" value="yes">Confirm shown plan</button></form>'
        with patch('remote_server.app.ui.consent_body',new=renderer):
            r=self.client.get(location)
        self.assertEqual(r.status_code,200)
        req=parse_qs(urlsplit(location).query)['request'][0]
        return {'csrf':self.csrf(),'request':req,'plan_id':captured['plan_id'],'approve':'yes'},captured,cid

    def approve(self,form):
        return self.client.post('/oauth/consent',data=form,headers={'origin':service.ORIGIN})

    def counts(self):
        with self.app.state.store.db() as db:
            return {t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in
                ('grants','library_cache','achievement_cache','oauth_codes','oauth_tokens')}

    def test_review_cancel_approve_replay_and_old_client_visibility(self):
        old=self.credentials()
        self.choose([4231820,1245620])
        form,plan,cid=self.review()
        self.assertEqual(set(plan),{'plan_id','games','oauth_scopes','library_source_change','zero_games'})
        self.assertEqual(plan['games'][0]['appid'],1245620)
        self.assertEqual(plan['games'][1]['categories'],['metadata','summary','achievements'])
        self.assertEqual(plan['games'][1]['trusted_name_or_null'],'Castlevania: Belmont’s Curse')
        self.assertTrue(plan['library_source_change'])
        before=self.counts();self.client.get('/');self.assertEqual(self.counts(),before)
        self.assertEqual(before['grants'],0)
        response=self.approve(form);self.assertEqual(response.status_code,303,response.text)
        callback=parse_qs(urlsplit(response.headers['location']).query)
        self.assertEqual(callback['state'],['fixture-state']);self.assertEqual(callback['iss'],[service.ORIGIN+'/'])
        self.assertEqual(self.counts()['grants'],5)
        self.assertEqual(self.counts()['achievement_cache'],2)
        # Account-wide grants are visible to existing authorized clients as well.
        self.assertEqual(len(self.called(old,'get_progress')['games']),2)
        self.assertEqual(self.called(old,'get_library')['reason'],'oauth_library_scope_required')
        counts=self.counts();self.assertEqual(self.approve(form).status_code,400);self.assertEqual(self.counts(),counts)
        exchanged=self.client.post('/token',data={'client_id':cid,'grant_type':'authorization_code',
            'code':callback['code'][0],'redirect_uri':service.REDIRECT,'code_verifier':'x'*64,'resource':service.ORIGIN+'/mcp'})
        self.assertEqual(exchanged.status_code,200)
        with self.app.state.store.db() as db:
            data=json.loads(db.execute("SELECT data FROM oauth_tokens WHERE kind='access' ORDER BY expires DESC LIMIT 1").fetchone()[0])
            self.assertNotIn('_review_plan',data);self.assertNotIn('_review_owner',data)

    def test_legacy_post_never_expands_even_after_plan_review(self):
        self.choose([4231820]);form,_,_=self.review()
        legacy={'csrf':form['csrf'],'request':form['request'],'library_read':'yes'}
        self.assertEqual(self.approve(legacy).status_code,303)
        counts=self.counts()
        for name in ('grants','library_cache','achievement_cache'):self.assertEqual(counts[name],0)

    def test_legacy_renderer_does_not_prepare_expanding_plan(self):
        # This is explicitly the legacy integration, regardless of the real UI's
        # current review_plan support. Keep the production renderer untouched.
        def legacy_renderer(csrf, req, client_label, scopes=('progress.read',)):
            return '<form method="post" action="/oauth/consent">' + ui.hidden('csrf',csrf) + ui.hidden('request',req) + '<button>Confirm existing access</button></form>'
        location,_=self.pending()
        with patch('remote_server.app.ui.consent_body',new=legacy_renderer):
            self.assertEqual(self.client.get(location).status_code,200)
        req=parse_qs(urlsplit(location).query)['request'][0]
        self.assertNotIn('_review_plan',self.app.state.provider.get_pending(req))
        self.assertEqual(self.counts()['grants'],0)

    def test_zero_games_and_progress_only_do_not_enable_library(self):
        form,plan,_=self.review('progress.read')
        self.assertTrue(plan['zero_games']);self.assertEqual(plan['games'],[])
        self.assertFalse(plan['library_source_change'])
        self.assertEqual(self.approve(form).status_code,303)
        self.assertEqual(self.counts()['grants'],0);self.assertEqual(self.counts()['library_cache'],0)

    def test_revoke_regrant_aba_invalidates_plan(self):
        self.choose([4231820]);self.permission(4231820)
        form,_,_=self.review()
        self.permission(4231820,enabled='no');self.permission(4231820)
        self.assertEqual(self.approve(form).status_code,409)
        self.assertEqual(self.counts()['grants'],1);self.assertEqual(self.counts()['library_cache'],0)

    def test_selection_library_global_revoke_writers_invalidate(self):
        for writer in ('selection','library','game_revoke','global_revoke','scope'):
            with self.subTest(writer=writer):
                self.choose([4231820]);form,_,_=self.review()
                if writer=='selection':self.choose([4231820,1245620])
                elif writer=='library':self.client.post('/account/library/permission',data={'csrf':self.csrf(),'enabled':'yes'},headers={'origin':service.ORIGIN})
                elif writer=='game_revoke':self.revoke(4231820)
                elif writer=='scope':self.permission(4231820)
                else:self.client.post('/account/revoke',data={'csrf':self.csrf()},headers={'origin':service.ORIGIN})
                before=self.counts();self.assertEqual(self.approve(form).status_code,409);self.assertEqual(self.counts(),before)

    def test_capacity_and_code_failure_roll_back_all_mutations_and_keep_plan(self):
        self.choose([4231820,1245620]);form,_,_=self.review()
        for target in ('remote_server.app.ACHIEVEMENT_ROWS_GLOBAL','remote_server.app.LIBRARY_ROWS_GLOBAL','remote_server.oauth.MAX_CODE_ROWS'):
            before=self.counts()
            with patch(target,0):response=self.approve(form)
            self.assertIn(response.status_code,(400,429));self.assertEqual(self.counts(),before)
            self.assertIn('_review_plan',self.app.state.provider.get_pending(form['request']))
        self.assertEqual(self.approve(form).status_code,303)

    def test_expired_logged_out_and_switched_sessions_never_apply(self):
        self.choose([4231820]);form,_,_=self.review()
        with self.app.state.store.db() as db:db.execute('UPDATE sessions SET expires=1')
        self.assertEqual(self.approve(form).status_code,401)
        self.sign_in();form,_,_=self.review()
        self.client.post('/logout',data={'csrf':self.csrf()},headers={'origin':service.ORIGIN})
        self.assertEqual(self.approve(form).status_code,401)
        self.sign_in();self.assertEqual(self.approve(form|{'csrf':self.csrf()}).status_code,409)
        self.assertEqual(self.counts()['grants'],0)

    def test_explicit_fields_and_original_guards(self):
        self.choose([4231820]);form,_,_=self.review()
        for bad in (form|{'approve':'no'}, {k:v for k,v in form.items() if k!='approve'},form|{'appid':'1245620'},form|{'library_read':'yes'}):
            self.assertEqual(self.approve(bad).status_code,422)
        self.assertEqual(self.approve(form|{'csrf':'bad'}).status_code,403)
        self.assertEqual(self.client.post('/oauth/consent',data=form,headers={'origin':'null'}).status_code,403)
        self.assertEqual(self.counts()['grants'],0)

    def test_two_approvals_are_atomic_and_invalidate_other_plan(self):
        self.choose([4231820]);first,_,_=self.review();second,_,_=self.review()
        with ThreadPoolExecutor(2) as pool:
            codes=list(pool.map(lambda f:self.approve(f).status_code,(first,second)))
        self.assertEqual(sorted(codes),[303,409]);self.assertEqual(self.counts()['oauth_codes'],1)
        self.assertEqual(self.counts()['grants'],3)

    def test_pairing_approval_invalidates_plan(self):
        self.choose([4231820]);form,_,_=self.review()
        pair=self.client.post('/v1/devices/pair/start',json={}).json()
        response=self.client.post('/devices/approve',data={'csrf':self.csrf(),
            'user_code':pair['user_code'],'appid':'4231820','saves.summary':'yes'},headers={'origin':service.ORIGIN})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.approve(form).status_code,409)

    def test_cross_owner_plan_and_pending_expiry_fail_closed(self):
        self.choose([4231820]);form,_,_=self.review()
        self.client.cookies.clear();self.sign_in('76561198000000002')
        self.assertEqual(self.approve(form|{'csrf':self.csrf()}).status_code,409)
        self.assertEqual(self.counts()['grants'],0)
        other,_,_=self.review()
        with self.app.state.store.db() as db:db.execute('UPDATE oauth_pending SET expires=1')
        self.assertEqual(self.approve(other).status_code,400)

    def test_source_capability_change_and_old_review_fail_closed(self):
        self.choose([4231820]);form,_,_=self.review()
        self.app.state.store.achievements_available=False
        self.assertEqual(self.approve(form).status_code,409)
        self.assertEqual(self.counts()['grants'],0)

    def test_original_session_rechecked_after_handler_authentication(self):
        self.choose([4231820]);form,_,_=self.review()
        import remote_server.app as app_module
        original=app_module.approve_plan
        def expire_then_approve(store,provider,session,*args,**kwargs):
            with store.db() as db:db.execute('DELETE FROM sessions WHERE hash=?',(session['hash'],))
            return original(store,provider,session,*args,**kwargs)
        with patch('remote_server.app.approve_plan',side_effect=expire_then_approve):
            self.assertEqual(self.approve(form).status_code,401)
        self.assertEqual(self.counts()['grants'],0)

    def test_concurrent_revoke_cannot_leave_expanding_grants(self):
        self.choose([4231820]);form,_,_=self.review()
        with ThreadPoolExecutor(2) as pool:
            approved=pool.submit(self.approve,form)
            revoked=pool.submit(self.revoke,4231820)
            self.assertIn(approved.result().status_code,(303,409))
            self.assertEqual(revoked.result().status_code,303)
        self.assertEqual(self.counts()['grants'],0)
        self.assertEqual(self.counts()['achievement_cache'],0)

    def test_library_revoke_regrant_aba_invalidates_plan(self):
        def library(enabled):
            r=self.client.post('/account/library/permission',data={'csrf':self.csrf(),'enabled':enabled},headers={'origin':service.ORIGIN})
            self.assertEqual(r.status_code,303)
        library('yes');form,_,_=self.review()
        library('no');library('yes')
        self.assertEqual(self.approve(form).status_code,409)
        self.assertEqual(self.counts()['grants'],0)

    def test_another_owners_mutation_does_not_invalidate_first_plan(self):
        self.choose([4231820]);form,_,_=self.review()
        first_cookie=self.client.cookies[COOKIE]
        self.client.cookies.clear();self.sign_in('76561198000000002')
        self.choose([1245620]);self.permission(1245620,scope='saves.metadata')
        self.client.cookies.clear();self.client.cookies.set(COOKIE,first_cookie)
        self.assertEqual(self.approve(form).status_code,303)


    def test_integrated_renderer_bundle_shows_disclosure_and_approves_exact_plan(self):
        if 'review_plan' not in inspect.signature(ui.consent_body).parameters:
            self.skipTest('Task E review_plan renderer not integrated in this checkout')
        from test_remote_browser_flows import FormReader
        self.choose([4231820,1245620]);location,_=self.pending()
        page=self.client.get(location);self.assertEqual(page.status_code,200)
        self.assertIn('Castlevania: Belmont’s Curse',page.text)
        self.assertIn('Elden Ring',page.text)
        self.assertIn('другим',page.text.lower())
        self.assertIn('помощник',page.text.lower())
        form=FormReader(page.text).forms[0]
        self.assertEqual(form['action'],'/oauth/consent')
        self.assertEqual(set(form['fields']),{'csrf','request','plan_id','approve'})
        self.assertEqual(form['fields']['approve'],'yes')
        before=self.counts();self.client.get('/');self.assertEqual(self.counts(),before)
        self.assertEqual(self.approve(form['fields']).status_code,303)
        self.assertEqual(self.counts()['grants'],5)
        self.assertEqual(self.counts()['library_cache'],1)
        self.assertEqual(self.approve(form['fields']).status_code,400)

    def test_integrated_renderer_zero_games_keeps_empty_progress(self):
        if 'review_plan' not in inspect.signature(ui.consent_body).parameters:
            self.skipTest('Task E review_plan renderer not integrated in this checkout')
        from test_remote_browser_flows import FormReader
        location,_=self.pending('progress.read')
        page=self.client.get(location);self.assertEqual(page.status_code,200)
        form=FormReader(page.text).forms[0]['fields']
        self.assertEqual(form['approve'],'yes')
        self.assertEqual(self.approve(form).status_code,303)
        self.assertEqual(self.counts()['grants'],0)
        self.assertEqual(self.counts()['library_cache'],0)
        self.assertEqual(self.counts()['achievement_cache'],0)



@unittest.skipUnless(os.environ.get('GA_TEST_POSTGRES_URL'),'Disposable local PostgreSQL DSN not supplied')
class PostgresConsolidatedConsentTests(ConsolidatedConsentTests):
    def database(self):
        import test_remote_postgres
        return test_remote_postgres.database()
