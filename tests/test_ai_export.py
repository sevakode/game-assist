"""Synthetic snapshot export isolation and strict output allowlist."""
import json
import time
import unittest
from unittest.mock import patch
from remote_server.app import COOKIE, digest
from remote_server.ai_export import ManualAIExport, stamp
from test_remote_ui import Elements
from test_remote_service import ORIGIN
import test_remote_achievements as achievement_tests
import test_remote_games as game_tests


class AIExportTests(unittest.TestCase):
    setUp = achievement_tests.AchievementTests.setUp
    tearDown = achievement_tests.AchievementTests.tearDown
    sign_in = achievement_tests.AchievementTests.sign_in
    csrf = achievement_tests.AchievementTests.csrf
    owner = achievement_tests.AchievementTests.owner
    choose = achievement_tests.AchievementTests.choose
    catalog = achievement_tests.AchievementTests.catalog
    permission = achievement_tests.AchievementTests.permission
    observation = game_tests.GameSelectionTests.observation

    def page_fields(self, appid=1245620):
        response = self.client.get('/games', params={'game':appid})
        self.assertEqual(response.status_code, 200)
        fields = Elements(response.text).find('button', id='ai-export-copy')[0]
        return {name:fields['data-'+name] for name in ('csrf','appid','binding')}

    def export(self, fields, **extra):
        return self.client.post('/account/ai-export', data={**fields, **extra}, headers={'origin':ORIGIN})

    def prepare(self, appid=1245620, items=None):
        self.sign_in(); self.cached_owner=self.owner(); self.choose([appid])
        self.assertEqual(self.permission(appid, scope='achievements.read').status_code,303)
        with self.app.state.store.db() as db:
            db.execute("UPDATE achievement_cache SET status='ok',payload=?,received_at=?,expires=? WHERE owner=? AND appid=?", (json.dumps(items if items is not None else [{'apiname':'PRIVATE_RAW_ID','name':'SPOILER_SECRET','unlock_time':123}]), time.time()-5,time.time()+1000,self.cached_owner,appid))
        return self.page_fields(appid)

    def test_count_only_no_other_game_data_or_network(self):
        fields = self.prepare()
        response = self.export(fields)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(set(response.json()),{'text','appid','checked_at'})
        text=response.json()['text']
        self.assertIn('Открытые достижения: 1',text)
        self.assertIn('Elden Ring',text)
        self.assertIn('Разрешения проверены сервером',text)
        for sentinel in ['PRIVATE_RAW_ID','SPOILER_SECRET',fields['csrf'],fields['binding'],'76561198000000001','apiname','unlock_time','http','SteamID']:
            self.assertNotIn(sentinel,text)
        self.assertEqual(self.reader.calls,[])
        self.assertIn('no-store',response.headers['cache-control'])

    def test_empty_cache_zero_is_not_completion_and_repeat_rechecks(self):
        fields=self.prepare(items=[])
        self.assertIn('Открытые достижения: 0',self.export(fields).json()['text'])
        self.assertIn('только пустой возвращённый список',self.export(fields).json()['text'])
        self.permission(1245620,scope='achievements.read',enabled='no')
        self.assertEqual(self.export(fields).status_code,403)

    def test_expired_session_public_games_does_not_become_export(self):
        fields=self.prepare()
        with self.app.state.store.db() as db:db.execute('UPDATE sessions SET expires=1')
        self.assertEqual(self.client.get('/games').status_code,200)
        response=self.export(fields)
        self.assertEqual(response.status_code,401)
        self.assertEqual(set(response.json()),{'error'})
        self.assertNotIn('location',response.headers)

    def test_same_owner_new_session_and_other_account_cannot_use_old_binding(self):
        fields=self.prepare()
        for identity in ['76561198000000001','76561198000000002']:
            self.client.cookies.clear();self.sign_in(identity)
            response=self.export(fields,csrf=self.csrf())
            self.assertIn(response.status_code,(403,409))
            self.assertNotIn('PRIVATE_RAW_ID',response.text)

    def test_change_game_selection_grants_or_cache_rejects_original_page(self):
        fields=self.prepare()
        self.choose([1245620,292030])
        self.assertEqual(self.export(fields).status_code,409)
        fields=self.page_fields()
        self.assertEqual(self.export(fields,appid='292030').status_code,403)
        self.permission(1245620,scope='achievements.read',enabled='no')
        self.permission(1245620,scope='achievements.read',enabled='yes')
        self.assertEqual(self.export(fields).status_code,409)

    def test_expired_cache_and_no_data_never_return_partial_or_old_text(self):
        fields=self.prepare()
        with self.app.state.store.db() as db:db.execute('UPDATE achievement_cache SET expires=1')
        self.assertEqual(self.export(fields).status_code,409)
        fresh=self.page_fields()
        self.assertEqual(self.export(fresh).status_code,409)
        with self.app.state.store.db() as db:db.execute("UPDATE achievement_cache SET payload=NULL,status='not_requested',expires=NULL")
        self.assertEqual(self.export(self.page_fields()).status_code,409)

    def test_csrf_origin_request_allowlist_and_binding_required(self):
        fields=self.prepare()
        self.assertEqual(self.export(fields,csrf='bad').status_code,403)
        self.assertEqual(self.export(fields,owner='other').status_code,422)
        self.assertEqual(self.export(fields,binding='bad').status_code,409)
        self.assertEqual(self.export(fields,binding=str(int(time.time()))+'.'+'я'*64).status_code,409)
        self.assertEqual(self.client.post('/account/ai-export',data=fields).status_code,403)
        self.assertEqual(self.client.post('/account/ai-export',data=fields,headers={'origin':'null'}).status_code,403)
        self.assertEqual(self.client.get('/account/ai-export').status_code,405)
        with patch('remote_server.ai_export.time.time',return_value=time.time()+301):
            self.assertEqual(self.export(fields).status_code,409)

    def test_original_session_rechecked_after_form_validation(self):
        fields=self.prepare(); original=ManualAIExport.construct
        def expired(exporter,session,appid,binding):
            with exporter.store.db() as db:db.execute('UPDATE sessions SET expires=1')
            return original(exporter,session,appid,binding)
        with patch.object(ManualAIExport,'construct',expired):
            self.assertEqual(self.export(fields).status_code,401)

    def test_four_scalars_unknown_and_historical_receipt_no_metadata(self):
        self.sign_in();owner=self.owner();self.choose([4231820],summary=True)
        summary=self.observation()['payload'];summary['player_scalars']['currentMana']={'status':'unknown','value':None}
        with self.app.state.store.db() as db:
            db.execute("INSERT INTO observations_v2(owner,appid,kind,payload,observed,source) VALUES(?,4231820,'save_summary',?,123,'browser_manual')",(owner,json.dumps(summary)))
            db.execute("INSERT INTO observations_v2(owner,appid,kind,payload,observed,source) VALUES(?,4231820,'save_metadata',?,123,'device')",(owner,json.dumps({'size_bytes':987654321,'modified_ns':123})))
        text=self.export(self.page_fields(4231820)).json()['text']
        for phrase in ['Текущее здоровье: 42','Текущая мана: неизвестно','фрагментов здоровья: 2','фрагментов маны: 3','исторический снимок','1970-01-01','Время самого сейва неизвестно']:
            self.assertIn(phrase,text)
        self.assertNotIn('987654321',text)
        self.assertNotIn('world_structure',text)

    def test_unknown_public_title_falls_back_and_bad_timestamps_are_unknown(self):
        self.sign_in();owner=self.owner()
        with self.app.state.store.db() as db:
            db.execute('INSERT INTO game_registrations(owner,appid,label,created) VALUES(?,?,?,?)',(owner,99999999,'PRIVATE_USER_LABEL',time.time()))
        self.choose([99999999]);self.permission(99999999,scope='achievements.read')
        with self.app.state.store.db() as db:
            db.execute("UPDATE achievement_cache SET status='ok',payload='[]',received_at=?,expires=?",(time.time()+9000,time.time()+1000))
        text=self.export(self.page_fields(99999999)).json()['text']
        self.assertIn('Steam AppID 99999999',text)
        self.assertNotIn('PRIVATE_USER_LABEL',text)
        self.assertIn('получен сервером: неизвестно',text)
        for value in [None,True,-1,0,float('nan'),float('inf'),time.time()+1000,'PRIVATE_TIMESTAMP']:
            self.assertEqual(stamp(value,time.time()),'неизвестно')

    def test_malformed_cached_data_rejects_and_unknown_source_is_not_copied(self):
        self.prepare()
        with self.app.state.store.db() as db:
            session=dict(db.execute('SELECT * FROM sessions WHERE hash=?',(digest(self.client.cookies[COOKIE]),)).fetchone())
            db.execute("UPDATE achievement_cache SET payload=?", (json.dumps([{'apiname':'id','name':'PRIVATE','achieved':False}]),))
        helper=ManualAIExport(self.app.state.store)
        from starlette.exceptions import HTTPException
        with self.assertRaises(HTTPException) as error:
            helper.construct(session,1245620,helper.issue(session,1245620))
        self.assertEqual(error.exception.status_code,409)
        self.choose([4231820],summary=True)
        with self.app.state.store.db() as db:
            db.execute("INSERT INTO observations_v2(owner,appid,kind,payload,observed,source) VALUES(?,4231820,'save_summary',?,?,?)",(session['owner'],json.dumps(self.observation()['payload']),time.time()+5000,'PRIVATE_SOURCE_URL'))
        text=self.export(self.page_fields(4231820)).json()['text']
        self.assertIn('источник: неизвестно; получен сервером: неизвестно',text)
        self.assertNotIn('PRIVATE_SOURCE_URL',text)

    def test_manual_clipboard_fallback_starts_empty_readonly_and_hidden(self):
        self.prepare()
        source = self.client.get('/games', params={'game': 1245620}).text
        elements = Elements(source)
        area = elements.find('textarea', id='ai-export-text')[0]
        self.assertIn('readonly', area)
        self.assertNotIn('name', area)
        self.assertEqual(area['spellcheck'], 'false')
        self.assertEqual(area['aria-describedby'], 'ai-export-status')
        self.assertIn('hidden', elements.find('div', id='ai-export-manual')[0])
        self.assertRegex(source, r'<textarea id="ai-export-text"[^>]*></textarea>')
        self.assertIn('не непрерывный доступ', source)
        self.assertIn('При подготовке снимка сервер заново проверит разрешения', source)
        self.assertNotIn('При каждом копировании сервер', source)

    def test_fresh_csp_narrow_script_and_no_generic_prompt_regression(self):
        self.prepare()
        for path in ['/games','/games?game=1245620']:
            policy=self.client.get(path).headers['content-security-policy']
            self.assertIn("script-src 'self'",policy);self.assertIn("connect-src 'self'",policy)
            self.assertNotIn('unsafe-inline',policy)
        self.assertNotIn('script-src',self.client.get('/').headers['content-security-policy'])
        self.assertIn('phone-prompt',self.client.get('/start').text)
        self.assertEqual(self.client.get('/assets/ai-export.js').status_code,200)
