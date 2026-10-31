import asyncio
import base64
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from starlette.testclient import TestClient
from remote_server.app import Config, create_app, COOKIE
from decoders.belmont import decode_bytes, safe_summary

ORIGIN='https://assist.example'
REDIRECT='https://client.example/callback'

class FakeSteam:
    def login_url(self, return_to, realm):
        self.return_to=return_to
        return 'https://steamcommunity.com/openid/login'
    def verify_callback(self, params, expected):
        assert expected==self.return_to
        return params['test_identity']

class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.steam=FakeSteam()
        self.app=create_app(Config(ORIGIN,str(Path(self.temp.name)/'test.db'),(REDIRECT,)), self.steam)
        self.client=TestClient(self.app,base_url=ORIGIN,follow_redirects=False)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.temp.cleanup()

    def sign_in(self, identity='76561198000000001', client=None):
        client=client or self.client
        r=client.get('/login')
        self.assertEqual(r.status_code,303)
        self.assertIn('Secure',r.headers['set-cookie'])
        state=parse_qs(urlsplit(self.steam.return_to).query)['state'][0]
        r=client.get('/steam/callback',params={'state':state,'test_identity':identity})
        self.assertEqual(r.status_code,303)
        return state

    def csrf(self,client=None,path='/devices/approve'):
        text=(client or self.client).get(path).text
        return re.search('name="csrf" value="([^"]+)"',text)[1]

    def pair(self,client=None,scope='saves.summary'):
        client=client or self.client
        pair=client.post('/v1/devices/pair/start',json={}).json()
        r=client.post('/devices/approve',data={'csrf':self.csrf(client),'user_code':pair['user_code'],'appid':'4231820',scope:'yes'},headers={'origin':ORIGIN})
        self.assertEqual(r.status_code,200,r.text)
        return client.post('/v1/devices/pair/poll',json={'device_code':pair['device_code']}).json()['device_token']

    def observation(self):
        raw={'version':'1.1.3','playerSave':{'healthUpgradeFragmentCount':2,'manaUpgradeFragmentCount':3,'currentHealth':42,'currentMana':50}}
        return {'event_id':str(uuid4()),'appid':4231820,'kind':'save_summary','payload':safe_summary(decode_bytes(json.dumps(raw).encode()))}

    def oauth(self):
        r=self.client.post('/register',json={'redirect_uris':[REDIRECT],'token_endpoint_auth_method':'none','grant_types':['authorization_code','refresh_token'],'response_types':['code'],'scope':'progress.read'})
        self.assertEqual(r.status_code,201,r.text)
        cid=r.json()['client_id']
        verifier='v'*64
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        r=self.client.get('/authorize',params={'client_id':cid,'redirect_uri':REDIRECT,'response_type':'code','scope':'progress.read','state':'client-state','code_challenge':challenge,'code_challenge_method':'S256','resource':ORIGIN+'/mcp'})
        self.assertEqual(r.status_code,302,r.text)
        loc=r.headers['location']; req=parse_qs(urlsplit(loc).query)['request'][0]
        csrf=self.csrf(path=loc)
        r=self.client.post('/oauth/consent',data={'csrf':csrf,'request':req},headers={'origin':ORIGIN})
        self.assertEqual(r.status_code,303,r.text)
        code=parse_qs(urlsplit(r.headers['location']).query)['code'][0]
        r=self.client.post('/token',data={'client_id':cid,'grant_type':'authorization_code','code':code,'redirect_uri':REDIRECT,'code_verifier':verifier,'resource':ORIGIN+'/mcp'})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()['access_token']

    def mcp(self,token,method,params=None):
        return self.client.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':method,'params':params or {}},headers={'authorization':'Bearer '+token,'accept':'application/json, text/event-stream'})

    def test_failclosed_and_host(self):
        with self.assertRaises(ValueError): Config('', 'x', (REDIRECT,))
        with self.assertRaises(ValueError): Config('http://example.com','x',(REDIRECT,))
        self.assertEqual(self.client.get('/login',headers={'host':'evil.example'}).status_code,400)
        self.assertEqual(self.client.get('/mcp').status_code,401)
        metadata=self.client.get('/.well-known/oauth-authorization-server').json()
        self.assertEqual(metadata['token_endpoint_auth_methods_supported'],['none'])
        self.assertNotIn('access-control-allow-origin',self.client.get('/').headers)

    def test_login_state_replay_and_csrf(self):
        state=self.sign_in()
        self.assertEqual(self.client.get('/steam/callback',params={'state':state,'test_identity':'76561198000000001'}).status_code,400)
        self.assertEqual(self.client.post('/account/revoke',data={'csrf':'bad'},headers={'origin':ORIGIN}).status_code,403)
        self.assertEqual(self.client.post('/account/revoke',data={'csrf':self.csrf()}).status_code,403)
        self.assertNotIn('76561198000000001',self.client.get('/').text)

    def test_pair_expiration_replay_rate_grants(self):
        self.sign_in()
        unavailable=self.client.post('/v1/devices/pair/start',json={}).json()
        denied=self.client.post('/devices/approve',data={'csrf':self.csrf(),'user_code':unavailable['user_code'],'appid':'4231820','saves.metadata':'yes'},headers={'origin':ORIGIN})
        self.assertEqual(denied.status_code,422)
        pair=self.client.post('/v1/devices/pair/start',json={}).json()
        self.assertEqual(self.client.post('/v1/devices/pair/poll',json={'device_code':pair['device_code']}).json()['status'],'pending')
        self.assertEqual(self.client.post('/v1/devices/pair/poll',json={'device_code':pair['device_code']}).status_code,429)
        with self.app.state.store.db() as db: db.execute('UPDATE pairings SET expires=0')
        self.assertEqual(self.client.post('/v1/devices/pair/poll',json={'device_code':pair['device_code']}).json()['status'],'expired')

    def test_ingest_filter_idempotence_and_revoke(self):
        self.sign_in(); token=self.pair(); data=self.observation(); hdr={'authorization':'Bearer '+token}
        self.assertEqual(self.client.post('/v1/device/observations',json=data,headers=hdr).json(),{'accepted':True,'duplicate':False})
        self.assertTrue(self.client.post('/v1/device/observations',json=data,headers=hdr).json()['duplicate'])
        changed=json.loads(json.dumps(data)); changed['payload']['player_scalars']['currentHealth']['value']=1
        self.assertEqual(self.client.post('/v1/device/observations',json=changed,headers=hdr).status_code,409)
        for key in ('steamid','owner','raw_save'):
            bad=dict(data);bad[key]='SECRET'
            self.assertEqual(self.client.post('/v1/device/observations',json=bad,headers=hdr).status_code,422)
        oauth=self.oauth()
        response=self.mcp(oauth,'tools/call',{'name':'get_progress','arguments':{}})
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn('currentHealth',response.text)
        for marker in ('76561198000000001','steamid','worldSaves','maxHealth'):
            self.assertNotIn(marker,response.text)
        self.client.post('/account/revoke',data={'csrf':self.csrf()},headers={'origin':ORIGIN})
        self.assertEqual(self.client.post('/v1/device/observations',json=data,headers=hdr).status_code,401)
        self.assertEqual(self.mcp(oauth,'tools/list').status_code,401)

    def test_two_users_mcp_no_cross_tenant(self):
        self.sign_in(); device=self.pair()
        self.client.post('/v1/device/observations',json=self.observation(),headers={'authorization':'Bearer '+device})
        first=self.oauth()
        self.client.cookies.clear(); self.sign_in('76561198000000002'); second=self.oauth()
        a=self.mcp(first,'tools/call',{'name':'get_progress','arguments':{}})
        b=self.mcp(second,'tools/call',{'name':'get_progress','arguments':{}})
        self.assertIn('currentHealth',a.text);self.assertNotIn('currentHealth',b.text)
        forbidden=self.mcp(second,'tools/call',{'name':'get_progress','arguments':{'owner':'76561198000000001'}})
        self.assertNotIn('currentHealth',forbidden.text)

    def test_login_continues_pairing_and_cookie_bound_state(self):
        r=self.client.get('/devices/approve')
        self.assertEqual(r.status_code,303)
        r=self.client.get(r.headers['location'])
        state=parse_qs(urlsplit(self.steam.return_to).query)['state'][0]
        outsider=TestClient(self.app,base_url=ORIGIN)
        self.assertEqual(outsider.get('/steam/callback',params={'state':state,'test_identity':'76561198000000002'}).status_code,401)
        r=self.client.get('/steam/callback',params={'state':state,'test_identity':'76561198000000001'})
        self.assertEqual(r.headers['location'],'/devices/approve')
        self.assertEqual(self.client.get('/login?next=https://evil.example').status_code,400)

    def test_pair_one_use_device_expiry_and_malformed_uuid(self):
        self.sign_in()
        pair=self.client.post('/v1/devices/pair/start',json={}).json()
        data={'csrf':self.csrf(),'user_code':pair['user_code'],'appid':'4231820','saves.summary':'yes'}
        self.assertEqual(self.client.post('/devices/approve',data=data,headers={'origin':ORIGIN}).status_code,200)
        self.assertEqual(self.client.post('/devices/approve',data=data,headers={'origin':ORIGIN}).status_code,400)
        token=self.client.post('/v1/devices/pair/poll',json={'device_code':pair['device_code']}).json()['device_token']
        self.assertEqual(self.client.post('/v1/devices/pair/poll',json={'device_code':pair['device_code']}).status_code,400)
        hdr={'authorization':'Bearer '+token}
        for invalid in (None,5,[],{},'x'*100):
            body=self.observation();body['event_id']=invalid
            self.assertEqual(self.client.post('/v1/device/observations',json=body,headers=hdr).status_code,422)
        with self.app.state.store.db() as db: db.execute('UPDATE devices SET expires=0')
        self.assertEqual(self.client.post('/v1/device/observations',json=self.observation(),headers=hdr).status_code,401)

    def test_strict_registration_and_duplicate_body(self):
        for uris in ('not-list',None,[5],['https://CLIENT.example/callback']):
            self.assertEqual(self.client.post('/register',json={'redirect_uris':uris}).status_code,400)
        self.assertEqual(self.client.post('/v1/devices/pair/start',content='{"x":1,"x":2}').status_code,422)
        self.assertEqual(self.client.get('/authorize?state=a&state=b').status_code,400)

    def test_persistent_nonce_and_deployment_config(self):
        from remote_server.__main__ import server_options
        from unittest.mock import patch
        env={'GA_DEPLOYMENT_MODE':'render','RENDER_EXTERNAL_URL':ORIGIN,'GA_OAUTH_REDIRECT_URIS':REDIRECT}
        with patch.dict('os.environ',env,clear=True):
            self.assertEqual(Config.from_env().issuer,ORIGIN)
        with patch.dict('os.environ',env|{'GA_PUBLIC_ORIGIN':'https://custom.example'},clear=True):
            self.assertEqual(Config.from_env().issuer,'https://custom.example')
        for extra in ({'RENDER_EXTERNAL_URL':'http://evil.example'}, {'GA_PUBLIC_ORIGIN':''}, {'RENDER_EXTERNAL_URL':'https://good.example/path'}):
            with patch.dict('os.environ',env|extra,clear=True):
                with self.assertRaises(ValueError): Config.from_env()
        env['GA_DEPLOYMENT_MODE']='local'
        with patch.dict('os.environ',env,clear=True):
            with self.assertRaises(ValueError): Config.from_env()
        self.assertEqual(server_options({})['host'],'127.0.0.1')
        self.assertEqual(server_options({'GA_DEPLOYMENT_MODE':'render','DATABASE_URL':'provided','PORT':'1234'})['host'],'0.0.0.0')
        for env in ({'GA_DEPLOYMENT_MODE':'render'},{'GA_TRUSTED_PROXY_IPS':'*'},{'GA_TRUSTED_PROXY_IPS':'0.0.0.0/0'},{'PORT':'0'}):
            with self.assertRaises(ValueError): server_options(env)
        self.client.get('/login')
        state=parse_qs(urlsplit(self.steam.return_to).query)['state'][0]
        nonce='2026-10-31T15:00:00Zsynthetic-only'
        params={'state':state,'test_identity':'76561198000000001','openid.response_nonce':nonce}
        self.assertEqual(self.client.get('/steam/callback',params=params).status_code,303)
        fresh=create_app(self.app.state.config,self.steam,database=self.app.state.store.database)
        with TestClient(fresh,base_url=ORIGIN,follow_redirects=False) as client:
            client.get('/login');params['state']=parse_qs(urlsplit(self.steam.return_to).query)['state'][0]
            self.assertEqual(client.get('/steam/callback',params=params).status_code,400)
        self.assertEqual(self.client.get('/healthz').json(),{'status':'ok'})

    def test_body_and_malformed_and_unknown_routes(self):
        self.assertEqual(self.client.post('/v1/devices/pair/start',content='x'*17000).status_code,413)
        for content in ('not json','[]','null'):
            self.assertEqual(self.client.post('/v1/devices/pair/start',content=content).status_code,422)
        self.assertEqual(self.client.post('/v1/raw-save',content='secret').status_code,404)
        self.assertEqual(self.client.post('/v1/devices/pair/start',json={},headers={'origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.get('/authorize?redirect_uri=https://evil.example').status_code,400)
        self.assertEqual(self.client.post('/token',data={'resource':'https://evil.example'}).status_code,400)

if __name__=='__main__': unittest.main()
