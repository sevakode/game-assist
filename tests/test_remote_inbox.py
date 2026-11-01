"""Opt-in site inbox only. No cloud/push/LLM or real save fixtures."""
from concurrent.futures import ThreadPoolExecutor
import json
from html.parser import HTMLParser
import time
import unittest
from uuid import uuid4

from remote_server.app import APPID, COOKIE, INBOX_LIMIT, INBOX_TTL, NOTICE, digest
import test_remote_service as service_tests


class ScriptBlocks(HTMLParser):
    def __init__(self, source):
        super().__init__(); self.scripts=[]; self.current=None; self.feed(source)
    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.current={'attrs':dict(attrs), 'text':''}; self.scripts.append(self.current)
    def handle_data(self, data):
        if self.current is not None: self.current['text'] += data
    def handle_endtag(self, tag):
        if tag == 'script': self.current=None


class InboxTests(unittest.TestCase):
    setUp=service_tests.RemoteTests.setUp
    tearDown=service_tests.RemoteTests.tearDown
    sign_in=service_tests.RemoteTests.sign_in
    csrf=service_tests.RemoteTests.csrf
    pair=service_tests.RemoteTests.pair
    observation=service_tests.RemoteTests.observation

    def owner(self):
        with self.app.state.store.db() as db:
            return db.execute('SELECT owner FROM sessions WHERE hash=?',(digest(self.client.cookies[COOKIE]),)).fetchone()[0]

    def inbox(self): return self.app.state.store.inbox(self.owner())

    def choose(self,enabled='yes',**extra):
        return self.client.post('/account/notifications',data={'csrf':self.csrf(),'appid':str(APPID),'enabled':enabled,**extra},headers={'origin':service_tests.ORIGIN})

    def upload(self,token,value=42,event_id=None,status='known'):
        body=self.observation();body['event_id']=event_id or str(uuid4())
        body['payload']['player_scalars']['healthUpgradeFragmentCount']={'status':status,'value':value}
        return self.client.post('/v1/device/observations',json=body,headers={'authorization':'Bearer '+token}),body

    def prepared(self):
        self.sign_in();token=self.pair();self.assertEqual(self.choose().status_code,303)
        self.upload(token,42);self.upload(token,43)
        return token

    def test_default_off_grant_required_and_first_sample_is_baseline(self):
        self.sign_in()
        self.assertEqual(self.choose().status_code,403)
        token=self.pair();self.upload(token,42);self.upload(token,43)
        self.assertFalse(self.inbox()['enabled']);self.assertEqual(self.inbox()['items'],[])
        self.assertEqual(self.choose().status_code,303)
        self.assertEqual(self.inbox()['items'],[])
        self.upload(token,43);self.assertEqual(self.inbox()['items'],[])
        self.upload(token,44);self.assertEqual(len(self.inbox()['items']),1)
        self.assertEqual(self.inbox()['items'][0]['message'],NOTICE)
        self.assertFalse(self.inbox()['cloud_available']);self.assertFalse(self.inbox()['push_available'])

    def test_dedup_unknown_and_coalescing(self):
        self.sign_in();token=self.pair();self.choose();self.upload(token,42)
        self.assertEqual(self.inbox()['items'],[])
        event=str(uuid4());self.upload(token,43,event)
        original=self.inbox()['items'][0]['id']
        self.upload(token,43,event);self.upload(token,43)
        self.assertEqual(len(self.inbox()['items']),1)
        self.upload(token,None,status='unknown');self.upload(token,44)
        self.assertEqual(self.inbox()['items'][0]['id'],original)
        self.upload(token,45)
        self.assertEqual(len(self.inbox()['items']),1)
        self.assertNotEqual(self.inbox()['items'][0]['id'],original)
        self.assertEqual(self.client.post('/account/notifications/read',data={'csrf':self.csrf(),'notification_id':original},headers={'origin':service_tests.ORIGIN}).status_code,404)
        payload=json.dumps(self.inbox())
        for text in ('76561198000000001','worldSaves','maximum','boss','location'):
            self.assertNotIn(text,payload)

    def test_transient_health_mana_fluctuations_do_not_notify(self):
        self.sign_in();token=self.pair();self.choose();self.upload(token,42)
        body=self.observation();body['payload']['player_scalars']['healthUpgradeFragmentCount']['value']=42
        body['payload']['player_scalars']['currentHealth']['value']=1
        body['payload']['player_scalars']['currentMana']['value']=0
        self.assertEqual(self.client.post('/v1/device/observations',json=body,headers={'authorization':'Bearer '+token}).status_code,200)
        self.assertEqual(self.inbox()['items'],[])

    def test_read_and_cross_tenant_denial(self):
        self.prepared();first_owner=self.owner();item=self.inbox()['items'][0]
        read={'csrf':self.csrf(),'notification_id':item['id']}
        self.assertEqual(self.client.post('/account/notifications/read',data=read,headers={'origin':service_tests.ORIGIN}).status_code,303)
        self.assertEqual(self.inbox()['unread_count'],0)
        self.client.cookies.clear();self.sign_in('76561198000000002');self.pair();self.choose()
        self.assertEqual(self.inbox()['items'],[])
        read['csrf']=self.csrf()
        self.assertEqual(self.client.post('/account/notifications/read',data=read,headers={'origin':service_tests.ORIGIN}).status_code,404)
        self.assertEqual(len(self.app.state.store.inbox(first_owner)['items']),1)
        self.assertEqual(self.choose(owner=first_owner).status_code,422)

    def test_csrf_origin_duplicate_and_unknown_fields(self):
        self.sign_in();self.pair()
        data={'csrf':'bad','appid':str(APPID),'enabled':'yes'}
        self.assertEqual(self.client.post('/account/notifications',data=data,headers={'origin':service_tests.ORIGIN}).status_code,403)
        data['csrf']=self.csrf()
        self.assertEqual(self.client.post('/account/notifications',data=data).status_code,403)
        self.assertEqual(self.choose('maybe').status_code,422)
        encoded='csrf='+data['csrf']+'&appid=4231820&enabled=yes&enabled=no'
        self.assertEqual(self.client.post('/account/notifications',content=encoded,headers={'origin':service_tests.ORIGIN,'content-type':'application/x-www-form-urlencoded'}).status_code,403)
        self.assertEqual(self.client.post('/account/notifications/read',data={'csrf':data['csrf'],'notification_id':str(uuid4()),'owner':'other'},headers={'origin':service_tests.ORIGIN}).status_code,422)

    def test_optout_reenable_and_revoke(self):
        token=self.prepared();self.assertEqual(self.inbox()['unread_count'],1)
        self.choose('no');self.assertFalse(self.inbox()['enabled']);self.assertEqual(self.inbox()['items'],[])
        self.upload(token,44);self.choose('yes');self.upload(token,44)
        self.assertEqual(self.inbox()['items'],[])
        self.upload(token,45);self.assertEqual(self.inbox()['unread_count'],1)
        self.client.post('/account/revoke',data={'csrf':self.csrf()},headers={'origin':service_tests.ORIGIN})
        self.assertFalse(self.inbox()['enabled']);self.assertEqual(self.inbox()['items'],[])
        self.assertEqual(self.upload(token,46)[0].status_code,401)
        owner=self.owner()
        with self.app.state.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM notification_settings WHERE owner=?',(owner,)).fetchone()[0],0)

    def test_retention_count_and_transaction_rollback(self):
        token=self.prepared();owner=self.owner()
        with self.app.state.store.db() as db:
            db.execute('DELETE FROM notifications WHERE owner=?',(owner,))
            for n in range(60):
                db.execute('INSERT INTO notifications VALUES(?,?,?,?,?,NULL)',(str(uuid4()),owner,APPID,str(n),time.time()-1000-n))
            db.execute('INSERT INTO notifications VALUES(?,?,?,?,?,NULL)',('expired',owner,APPID,'expired',time.time()-INBOX_TTL-1))
        self.upload(token,44)
        self.assertEqual(len(self.inbox()['items']),INBOX_LIMIT)
        with self.app.state.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM notifications WHERE owner=?',(owner,)).fetchone()[0],INBOX_LIMIT)
        _,body=self.upload(token,45)
        count=len(self.inbox()['items'])
        with self.assertRaises(RuntimeError):
            with self.app.state.store.db() as db:
                body['payload']['player_scalars']['healthUpgradeFragmentCount']['value']=46
                self.app.state.store.record_notification(db,owner,APPID,json.dumps(body['payload']),'rollback-only',time.time()+400)
                raise RuntimeError('synthetic rollback')
        self.assertEqual(len(self.inbox()['items']),count)

    def test_rendered_console_routes_have_inbox_and_self_only_styles(self):
        landing=self.client.get('/')
        self.assertIn('/assets/console.css',landing.text)
        self.assertIn("style-src 'self'",landing.headers['content-security-policy'])
        scripts=ScriptBlocks(landing.text).scripts
        self.assertEqual(len(scripts),1)
        self.assertEqual(scripts[0]['attrs'],{'type':'application/ld+json'})
        metadata=json.loads(scripts[0]['text'])
        self.assertEqual(metadata['@type'],'WebPage')
        self.assertEqual(metadata['url'],service_tests.ORIGIN+'/')
        self.assertEqual(landing.headers['content-security-policy'],
                         "default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        css=self.client.get('/assets/console.css')
        self.assertEqual(css.status_code,200);self.assertTrue(css.headers['content-type'].startswith('text/css'))
        self.assertEqual(self.client.get('/assets/../app.py').status_code,404)
        self.prepared()
        home=self.client.get('/games')
        self.assertEqual(ScriptBlocks(home.text).scripts,[{'attrs': {'src': '/assets/ai-export.js', 'defer': None}, 'text': ''}])
        self.assertIn("script-src 'self'",home.headers['content-security-policy'])
        self.assertIn("connect-src 'self'",home.headers['content-security-policy'])
        self.assertIn(NOTICE,home.text)
        self.assertIn('/account/notifications/read',home.text)
        self.assertIn('/account/notifications',home.text)
        self.assertIn('Steam Cloud',home.text)
        self.assertNotIn('76561198000000001',home.text)
        self.assertIn('csrf',home.text)

    def test_concurrent_duplicate_and_revoke(self):
        self.sign_in();token=self.pair();self.choose();self.upload(token,42)
        event=str(uuid4())
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:self.upload(token,43,event)[0],range(2)))
        self.assertEqual([r.status_code for r in results],[200,200])
        self.assertEqual(self.inbox()['unread_count'],1)
        csrf=self.csrf()
        with ThreadPoolExecutor(2) as pool:
            one=pool.submit(self.upload,token,44)
            two=pool.submit(self.client.post,'/account/revoke',data={'csrf':csrf},headers={'origin':service_tests.ORIGIN})
            one.result();self.assertEqual(two.result().status_code,303)
        self.assertEqual(self.inbox()['items'],[])
