"""Browser action and recovery regressions using synthetic users and local DB only."""
import unittest
from html.parser import HTMLParser
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs
import base64
import hashlib
from starlette.requests import Request
from starlette.exceptions import HTTPException
from remote_server import ui
from remote_server.browser_errors import wants_browser_error, http_exception
import test_remote_games as games
import test_remote_service as service
from test_remote_achievements import FakeReader

HTML = {'accept': 'text/html', 'origin': service.ORIGIN}


class FormReader(HTMLParser):
    def __init__(self, source):
        super().__init__(); self.forms=[];self.current=None;self.links=[];self.feed(source)
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='a' and attrs.get('href'): self.links.append(attrs['href'])
        if tag=='form':
            self.current={'action':attrs.get('action',''),'fields':{}}
            self.forms.append(self.current)
        if tag=='input' and self.current is not None and attrs.get('name'):
            if attrs.get('type') not in ('checkbox','radio') or 'checked' in attrs:
                self.current['fields'][attrs['name']]=attrs.get('value','')
    def handle_endtag(self,tag):
        if tag=='form':self.current=None


class BrowserFlowTests(unittest.TestCase):
    setUp=games.GameSelectionTests.setUp
    tearDown=games.GameSelectionTests.tearDown
    sign_in=games.GameSelectionTests.sign_in
    csrf=games.GameSelectionTests.csrf
    owner=games.GameSelectionTests.owner
    choose=games.GameSelectionTests.choose
    catalog=games.GameSelectionTests.catalog
    permission=games.GameSelectionTests.permission
    observation=games.GameSelectionTests.observation
    pair=games.GameSelectionTests.pair
    oauth=games.GameSelectionTests.oauth
    mcp=games.GameSelectionTests.mcp

    def post(self,path,data):
        return self.client.post(path,data=data,headers=HTML)

    def test_public_games_navigation_and_all_local_get_targets_resolve(self):
        for appid in (4231820,1245620,292030):
            response=self.client.get('/games?game='+str(appid),headers=HTML)
            self.assertEqual(response.status_code,200)
            for href in set(FormReader(response.text).links):
                parsed=urlsplit(href)
                if parsed.netloc or parsed.scheme or not parsed.path or parsed.path=='/login':continue
                target=self.client.get(href,headers=HTML)
                self.assertIn(target.status_code,(200,303),href)
        self.assertEqual(self.client.get('/mcp',headers=HTML).status_code,401)

    def test_selection_review_cancel_confirm_is_data_driven(self):
        self.sign_in()
        initial=self.catalog()
        page=self.post('/account/games',{'csrf':self.csrf(),'action':'review_all'})
        self.assertEqual(page.status_code,200)
        self.assertEqual(self.catalog(),initial) # Review does not mutate.
        self.client.get('/games#library',headers=HTML) # Cancel is navigation only.
        self.assertEqual(self.catalog(),initial)
        form=next(f for f in FormReader(page.text).forms if f['action']=='/account/games')
        response=self.post(form['action'],form['fields'])
        self.assertEqual(response.status_code,303)
        self.assertTrue(all(g['selected'] for g in self.catalog()))
        self.assertTrue(all(not g['authorized_scopes'] for g in self.catalog()))

    def test_permission_actions_keep_current_game_and_preserve_others(self):
        self.sign_in();self.choose([4231820,1245620,292030])
        for appid in (1245620,292030,4231820):
            for enabled in ('yes','no'):
                response=self.permission(appid,scope='saves.metadata',enabled=enabled)
                self.assertEqual(response.status_code,303)
                self.assertEqual(response.headers['location'],f'/games?game={appid}#permissions')
                page=self.client.get(response.headers['location'],headers=HTML)
                self.assertEqual(page.status_code,200)
                self.assertIn(ui.GAMES[appid],page.text)
        self.assertTrue(all(g['selected'] for g in self.catalog()))

    def test_add_custom_review_and_scope_do_not_fabricate_progress(self):
        self.sign_in()
        r=self.post('/account/games/add',{'csrf':self.csrf(),'appid':'570','label':'Synthetic local game'})
        self.assertEqual(r.status_code,303)
        game=next(g for g in self.catalog() if g['appid']==570)
        self.assertFalse(game['selected']);self.assertFalse(game['authorized_scopes'])
        self.assertEqual(self.choose([570]).status_code,303)
        self.assertEqual(self.permission(570,scope='saves.metadata').status_code,303)
        page=self.client.get('/games?game=570',headers=HTML)
        self.assertEqual(page.status_code,200)
        self.assertIn('Synthetic local game',page.text)
        self.assertFalse(next(g for g in self.catalog() if g['appid']==570)['summary_supported'])
        self.assertNotIn('<progress',page.text)

    def test_missing_session_form_has_safe_login_recovery_no_automatic_mutation(self):
        response=self.post('/account/games/add',{'csrf':'expired','appid':'570'})
        self.assertEqual(response.status_code,401)
        self.assertIn('text/html',response.headers['content-type'])
        self.assertIn('Нужно войти снова',response.text)
        self.assertIn('/login',FormReader(response.text).links)
        with self.app.state.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM game_registrations').fetchone()[0],0)

    def test_invalid_csrf_form_has_recovery_and_preserves_grants(self):
        self.sign_in();self.choose([4231820],summary=True);before=self.catalog()
        r=self.post('/account/revoke',{'csrf':'old'})
        self.assertEqual(r.status_code,403)
        self.assertIn('Проверь доступ',r.text)
        self.assertEqual(self.catalog(),before)
        self.assertNotIn('old',r.text)
        self.assertEqual(r.headers['cache-control'],'no-store')
        self.assertIn("frame-ancestors 'none'",r.headers['content-security-policy'])

    def test_stale_selection_page_recovers_without_silent_confirmation(self):
        self.sign_in()
        review=self.post('/account/games',{'csrf':self.csrf(),'action':'review_all'})
        form=FormReader(review.text).forms[0]
        self.post('/account/games/add',{'csrf':self.csrf(),'appid':'570','label':'New'})
        r=self.post('/account/games',form['fields'])
        self.assertEqual(r.status_code,409)
        self.assertIn('Данные изменились',r.text)
        self.assertFalse(any(g['selected'] for g in self.catalog()))
        self.assertIn('/games#library',FormReader(r.text).links)

    def test_invalid_pair_code_can_retry_without_creating_device(self):
        self.sign_in();self.choose([4231820])
        data={'csrf':self.csrf(),'user_code':'00000000','appid':'4231820','saves.summary':'yes'}
        r=self.post('/devices/approve',data)
        self.assertEqual(r.status_code,400)
        self.assertIn('/devices/approve',FormReader(r.text).links)
        self.assertIn('код',r.text)
        with self.app.state.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM devices').fetchone()[0],0)

    def test_disabled_achievement_action_is_truthful_and_recoverable(self):
        self.sign_in();self.choose([1245620])
        page=self.client.get('/games?game=1245620',headers=HTML)
        self.assertIn('не настроен оператором',page.text)
        self.assertFalse(any(f['action']=='/account/achievements/refresh' for f in FormReader(page.text).forms))
        r=self.post('/account/achievements/refresh',{'csrf':self.csrf(),'appid':'1245620'})
        self.assertEqual(r.status_code,503)
        self.assertIn('Возможность пока недоступна',r.text)

    def test_bad_appid_not_reflected_and_recovery_target_stays_local(self):
        self.sign_in()
        value='https://untrusted.invalid/private'
        r=self.post('/account/games/add',{'csrf':self.csrf(),'appid':value,'label':'private label'})
        self.assertEqual(r.status_code,422)
        self.assertNotIn(value,r.text);self.assertNotIn('private label',r.text)
        self.assertTrue(all(not urlsplit(href).netloc for href in FormReader(r.text).links))

    def test_browser_observation_api_retains_protocol_response_with_html_accept(self):
        r=self.client.post('/v1/browser/observations',json={},headers=HTML)
        self.assertEqual(r.status_code,401)
        self.assertNotIn('text/html',r.headers['content-type'])
        r=self.client.post('/register',json={},headers=HTML)
        self.assertEqual(r.status_code,400)
        self.assertEqual(r.json(),{'error':'invalid_client_metadata'})

    def test_notification_controls_return_to_belmont_and_dedup_read(self):
        self.sign_in();token=self.pair();self.choose([4231820,1245620],summary=True)
        r=self.post('/account/notifications',{'csrf':self.csrf(),'appid':'4231820','enabled':'yes'})
        self.assertEqual(r.headers['location'],'/games?game=4231820#updates')
        data=self.observation()
        self.client.post('/v1/device/observations',json=data,headers={'authorization':'Bearer '+token})
        data=self.observation();data['payload']['player_scalars']['healthUpgradeFragmentCount']['value']=9
        self.client.post('/v1/device/observations',json=data,headers={'authorization':'Bearer '+token})
        item=self.app.state.store.inbox(self.owner())['items'][0]
        r=self.post('/account/notifications/read',{'csrf':self.csrf(),'notification_id':item['id']})
        self.assertEqual(r.headers['location'],'/games?game=4231820#updates')
        self.assertTrue(self.app.state.store.inbox(self.owner())['items'][0]['read'])
        self.assertEqual(self.post('/account/notifications/read',{'csrf':self.csrf(),'notification_id':item['id']}).status_code,303)

    def test_stale_disable_notifications_returns_to_library_when_game_deselected(self):
        self.sign_in()
        response=self.post('/account/notifications',{'csrf':self.csrf(),'appid':'4231820','enabled':'no'})
        self.assertEqual(response.status_code,303)
        self.assertEqual(response.headers['location'],'/games#library')
        self.assertEqual(self.client.get(response.headers['location'],headers=HTML).status_code,200)

    def test_logout_repeated_click_does_not_leave_broken_document(self):
        self.sign_in();data={'csrf':self.csrf()}
        self.assertEqual(self.post('/logout',data).status_code,303)
        r=self.post('/logout',data)
        self.assertEqual(r.status_code,401)
        self.assertIn('Нужно войти снова',r.text)
        guest=self.client.get('/')
        self.assertEqual(guest.status_code,200)
        self.assertIn('href="/login?next=/games">Привязать Steam',guest.text)
        self.assertNotIn('Steam подключён',guest.text)
        self.assertNotIn('action="/account/revoke"',guest.text)

    def test_mcp_end_to_end_and_revoke_still_work(self):
        self.sign_in();device=self.pair();oauth=self.oauth()
        self.client.post('/v1/device/observations',json=self.observation(),headers={'authorization':'Bearer '+device})
        r=self.mcp(oauth,'tools/call',{'name':'get_progress','arguments':{}})
        self.assertEqual(r.status_code,200);self.assertIn('currentHealth',r.text)
        self.assertEqual(self.post('/account/revoke',{'csrf':self.csrf()}).status_code,303)
        self.assertEqual(self.mcp(oauth,'tools/list').status_code,401)

    def test_boundary_rejects_browser_forms_with_recovery_and_no_store(self):
        self.sign_in();self.choose([4231820],summary=True);before=self.catalog()
        response=self.client.post('/account/revoke',data={'csrf':self.csrf()},headers={'accept':'text/html','origin':'https://different.invalid'})
        self.assertEqual(response.status_code,403)
        self.assertIn('Проверь доступ',response.text)
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertEqual(self.catalog(),before)
        response=self.client.post('/account/games/add',content='x'*16385,headers=HTML)
        self.assertEqual(response.status_code,413)
        self.assertIn('Слишком большой запрос',response.text)
        response=self.client.get('/login',params={'padding':'x'*8193},headers=HTML)
        self.assertEqual(response.status_code,414)
        self.assertIn('text/html',response.headers['content-type'])

    def test_boundary_api_errors_keep_json_and_security_headers(self):
        response=self.client.post('/v1/browser/observations',json={},headers={'origin':'https://different.invalid','accept':'text/html'})
        self.assertEqual(response.status_code,403)
        self.assertEqual(response.json(),{'error':'origin_denied'})
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertEqual(response.headers['x-content-type-options'],'nosniff')

    def test_pair_cancel_and_repeated_approval_are_safe_and_recoverable(self):
        self.sign_in();self.choose([4231820])
        pair=self.client.post('/v1/devices/pair/start',json={}).json()
        page=self.client.get('/devices/approve',headers=HTML)
        self.assertEqual(page.status_code,200)
        self.client.get('/',headers=HTML) # Cancel returns without approving.
        with self.app.state.store.db() as db:
            self.assertIsNone(db.execute('SELECT owner FROM pairings').fetchone()[0])
            self.assertEqual(db.execute('SELECT count(*) FROM devices').fetchone()[0],0)
        data={'csrf':self.csrf(),'user_code':pair['user_code'],'appid':'4231820','saves.summary':'yes'}
        self.assertEqual(self.post('/devices/approve',data).status_code,200)
        repeat=self.post('/devices/approve',data)
        self.assertEqual(repeat.status_code,400)
        self.assertIn('/devices/approve',FormReader(repeat.text).links)
        issued=self.client.post('/v1/devices/pair/poll',json={'device_code':pair['device_code']})
        self.assertEqual(issued.status_code,200)
        self.assertEqual(issued.json()['status'],'approved')
        repeat=self.client.post('/v1/devices/pair/poll',json={'device_code':pair['device_code']})
        self.assertEqual(repeat.status_code,400)
        self.assertNotIn('device_token',repeat.json())
        with self.app.state.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM devices').fetchone()[0],1)

    def test_oauth_consent_cancel_and_repeat_do_not_issue_extra_codes(self):
        self.sign_in()
        registration=self.client.post('/register',json={'redirect_uris':[service.REDIRECT],'token_endpoint_auth_method':'none','grant_types':['authorization_code','refresh_token'],'response_types':['code'],'scope':'progress.read'}).json()
        challenge=base64.urlsafe_b64encode(hashlib.sha256(('a'*64).encode()).digest()).decode().rstrip('=')
        response=self.client.get('/authorize',params={'client_id':registration['client_id'],'redirect_uri':service.REDIRECT,'response_type':'code','scope':'progress.read','state':'synthetic-test-state','code_challenge':challenge,'code_challenge_method':'S256','resource':service.ORIGIN+'/mcp'})
        target=response.headers['location']
        page=self.client.get(target,headers=HTML)
        self.assertEqual(page.status_code,200)
        form=FormReader(page.text).forms[0]
        self.assertEqual(form['action'], '/oauth/consent')
        self.assertNotIn('<script', page.text)
        self.assertNotIn('onsubmit', page.text)
        self.assertNotIn('disabled', page.text)
        policy = page.headers['content-security-policy']
        baseline = self.client.get('/', headers=HTML).headers['content-security-policy']
        self.assertEqual(page.headers.get_list('content-security-policy'), [policy])
        self.assertEqual(policy, baseline.replace("form-action 'self'", "form-action 'self' " + service.REDIRECT))
        injected = self.client.get(target + '&redirect_uri=https%3A%2F%2Funtrusted.example%2Fcallback', headers=HTML)
        self.assertEqual(injected.headers['content-security-policy'], policy)
        # A second review GET intentionally rotates a server-bound plan.
        # Submit the most recently displayed form, never the stale first tab.
        form=FormReader(injected.text).forms[0]
        self.client.get('/',headers=HTML) # Navigation cancellation never approves.
        with self.app.state.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM oauth_codes').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM oauth_tokens').fetchone()[0],0)
        response=self.post('/oauth/consent',form['fields'])
        self.assertEqual(response.status_code,303)
        callback = urlsplit(response.headers['location'])
        self.assertEqual(callback._replace(query='', fragment='').geturl(), service.REDIRECT)
        values = parse_qs(callback.query)
        self.assertEqual(set(values), {'code', 'state', 'iss'})
        self.assertEqual(values['state'], ['synthetic-test-state'])
        self.assertEqual(values['iss'], [service.ORIGIN + '/'])
        self.assertEqual(response.content, b'')
        self.assertEqual(response.headers.get_list('content-security-policy'), [baseline])
        self.assertNotIn('set-cookie', response.headers)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        repeat=self.post('/oauth/consent',form['fields'])
        self.assertEqual(repeat.status_code,400)
        self.assertIn('text/html',repeat.headers['content-type'])
        for recovery in (repeat, self.client.get(target, headers={'accept':'text/html'})):
            self.assertEqual(recovery.status_code, 400)
            self.assertEqual(recovery.headers.get_list('content-security-policy'), [baseline])
            self.assertIn('Начни подключение заново из AI-клиента', recovery.text)
            self.assertIn('не подтверждает подключение', recovery.text)
            self.assertIn('/connect/claude', FormReader(recovery.text).links)
            self.assertNotIn('location', recovery.headers)
            self.assertNotIn(values['code'][0], recovery.text)
            self.assertNotIn(form['fields']['request'], recovery.text)
        with self.app.state.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM oauth_pending').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM oauth_codes').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM oauth_tokens').fetchone()[0],0)
        exchange = {'client_id':registration['client_id'], 'grant_type':'authorization_code',
                    'code':values['code'][0], 'redirect_uri':service.REDIRECT,
                    'code_verifier':'a'*64, 'resource':service.ORIGIN+'/mcp'}
        self.assertEqual(self.client.post('/token', data=exchange).status_code, 200)
        self.assertEqual(self.client.post('/token', data=exchange).status_code, 400)

    def test_unknown_selected_game_has_local_recovery_and_no_data(self):
        self.sign_in()
        response=self.client.get('/games?game=1245620',headers=HTML)
        self.assertEqual(response.status_code,404)
        self.assertIn('Игра или страница недоступна',response.text)
        self.assertIn('/games#library',FormReader(response.text).links)

    def test_html_negotiation_does_not_override_nonbrowser_errors(self):
        def request(accept,path='/account/games'):
            return Request({'type':'http','path':path,'scheme':'https','server':('assist.example',443),'query_string':b'','headers':[(b'accept',accept.encode())]})
        for accept in ('text/html','text/html;q=0.9','application/xhtml+xml, text/html;q=0.5'):
            self.assertTrue(wants_browser_error(request(accept)))
        for accept in ('application/json','*/*','text/html;q=0','text/html;q=bogus','text/html;q=nan'):
            self.assertFalse(wants_browser_error(request(accept)))
        self.assertFalse(wants_browser_error(request('text/html','/mcp')))


class AchievementBrowserFlowTests(unittest.TestCase):
    tearDown=BrowserFlowTests.tearDown
    sign_in=BrowserFlowTests.sign_in
    csrf=BrowserFlowTests.csrf
    owner=BrowserFlowTests.owner
    choose=BrowserFlowTests.choose
    catalog=BrowserFlowTests.catalog
    permission=BrowserFlowTests.permission
    post=BrowserFlowTests.post
    def setUp(self):
        self.reader=FakeReader()
        with patch('remote_server.app.AchievementReader',return_value=self.reader):
            BrowserFlowTests.setUp(self)

    def test_refresh_success_and_cooldown_keep_game_and_do_not_retry_automatically(self):
        self.sign_in();self.choose([4231820,1245620])
        self.permission(1245620,scope='achievements.read')
        data={'csrf':self.csrf(),'appid':'1245620'}
        r=self.post('/account/achievements/refresh',data)
        self.assertEqual(r.headers['location'],'/games?game=1245620#achievements')
        r=self.post('/account/achievements/refresh',data)
        self.assertEqual(r.status_code,429)
        self.assertIn('15 минут',r.text)
        self.assertIn('/games?game=1245620#achievements',FormReader(r.text).links)
        self.assertEqual(len(self.reader.calls),1)
