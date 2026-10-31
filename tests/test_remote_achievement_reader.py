"""Synthetic-only transport tests; no Steam credentials or external requests."""
import json
import logging
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest

import httpx

from remote_server.achievements import AchievementReader, ENDPOINT, MAX_RESPONSE

ID = '76561198000000001'
APPID = 1245620
KEY = 'synthetic-operator-key-never-log'


def unlocked(name='VISIBLE'):
    return {'apiname':name,'achieved':1,'name':'Verified unlocked title','unlocktime':123}


def response(rows=None, **extra):
    return {'playerstats':{'steamID':ID,'success':True,'appid':APPID,
                          'achievements':rows if rows is not None else [unlocked()],**extra}}


class AchievementReaderTests(unittest.TestCase):
    def reader(self, data=None, status=200, handler=None, key=KEY, **kwargs):
        self.requests=[]
        def transport(request):
            self.requests.append(request)
            return handler(request) if handler else httpx.Response(status,json=data if data is not None else response())
        return AchievementReader(api_key=key,transport=httpx.MockTransport(transport),**kwargs)

    def test_absent_key_and_bad_subject_are_offline(self):
        reader=self.reader(key='')
        self.assertFalse(reader.configured)
        self.assertEqual(reader.get_unlocked(ID,APPID)['status'],'not_configured')
        self.assertEqual(self.requests,[])
        reader=self.reader()
        for identity,appid in [('wrong',APPID),(ID,True),(ID,0),(ID,2147483648)]:
            self.assertEqual(reader.get_unlocked(identity,appid)['status'],'unavailable')
        self.assertEqual(self.requests,[])

    def test_request_contract_unlocked_only_and_no_schema(self):
        reader=self.reader(response([unlocked(),{'apiname':'LOCKED_SECRET','achieved':0,'name':'Hidden spoiler','description':'Hidden quest'}]))
        result=reader.get_unlocked(ID,APPID)
        self.assertEqual(result,{'status':'ok','achievements':[{'apiname':'VISIBLE','name':'Verified unlocked title','unlock_time':123}],'source':'steam_web_api'})
        self.assertNotIn('LOCKED',json.dumps(result));self.assertNotIn('total',result)
        request=self.requests[0]
        self.assertEqual(request.method,'GET');self.assertEqual(str(request.url).split('?')[0],ENDPOINT)
        self.assertEqual(request.headers['x-webapi-key'],KEY);self.assertNotIn(KEY,str(request.url))
        self.assertEqual(request.url.params['steamid'],ID);self.assertEqual(request.url.params['appid'],str(APPID))
        self.assertEqual(request.extensions['timeout']['connect'],3.0)
        self.assertEqual(request.extensions['timeout']['read'],8.0)
        self.assertEqual(len(self.requests),1)

    def test_identity_success_and_optional_appid_binding(self):
        for update in ({'steamID':'76561198000000002'},{'steamID':int(ID)},{'steamID':None},
                       {'appid':True},{'appid':292030},{'success':1},{'success':False,'error':'Private profile'}):
            result=self.reader(response(**update)).get_unlocked(ID,APPID)
            self.assertEqual(result['status'],'unavailable');self.assertEqual(result['achievements'],[])
        data=response();del data['playerstats']['appid']
        self.assertEqual(self.reader(data).get_unlocked(ID,APPID)['status'],'ok')

    def test_malformed_and_oversized_fail_closed(self):
        bad=[None,[],{'apiname':'X','achieved':True},unlocked()|{'unlocktime':-1},
             unlocked()|{'unlocktime':2**63},unlocked()|{'name':'x'*301},unlocked()|{'apiname':'bad\nname'}]
        for row in bad:
            self.assertEqual(self.reader(response([row])).get_unlocked(ID,APPID)['status'],'unavailable')
        for rows in ([unlocked(),unlocked()], [unlocked(str(i)) for i in range(501)], [{'apiname':str(i),'achieved':0} for i in range(10001)]):
            self.assertEqual(self.reader(response(rows)).get_unlocked(ID,APPID)['status'],'unavailable')
        for body in (b'{"playerstats":{},"playerstats":{}}',b'{"bad":NaN}',b'x'*(MAX_RESPONSE+1)):
            reader=self.reader(handler=lambda req,body=body:httpx.Response(200,content=body))
            self.assertEqual(reader.get_unlocked(ID,APPID)['status'],'unavailable')
        # Byte-sized result limit applies independently of bounded string counts.
        rows=[unlocked(str(i))|{'name':'\u754c'*300} for i in range(150)]
        self.assertEqual(self.reader(response(rows)).get_unlocked(ID,APPID)['status'],'unavailable')

    def test_unavailable_not_zero_progress_no_redirect_or_retry(self):
        for status in (301,302,401,403,429,500):
            reader=self.reader(status=status,handler=lambda request,status=status:httpx.Response(status,headers={'Location':'https://elsewhere.invalid'}))
            result=reader.get_unlocked(ID,APPID)
            self.assertEqual(result['status'],'unavailable');self.assertEqual(len(self.requests),1)
        def timeout(request):raise httpx.ReadTimeout(KEY+' '+ID,request=request)
        reader=self.reader(handler=timeout)
        self.assertEqual(reader.get_unlocked(ID,APPID),{'status':'unavailable','achievements':[],'source':'steam_web_api'})
        clock=iter((0,13))
        reader=self.reader(monotonic=lambda:next(clock))
        self.assertEqual(reader.get_unlocked(ID,APPID)['status'],'unavailable')

    def test_transport_logs_redacted_security_logs_preserved(self):
        def handler(request):
            logging.getLogger('httpcore.future.child').debug('headers %s url %s',dict(request.headers),request.url)
            try:raise ValueError(KEY+' '+ID)
            except ValueError:logging.getLogger('httpcore.http11').exception('request failed %s',request.url)
            logging.getLogger('game_assist.security').warning('synthetic security audit retained')
            return httpx.Response(200,json=response())
        reader=self.reader(handler=handler)
        with self.assertLogs(level='DEBUG') as captured:
            self.assertEqual(reader.get_unlocked(ID,APPID)['status'],'ok')
        logs='\n'.join(captured.output)
        self.assertNotIn(KEY,logs);self.assertNotIn(ID,logs);self.assertNotIn(ENDPOINT,logs)
        self.assertIn('security audit retained',logs);self.assertIn('redacted',logs)
        with self.assertLogs('httpx',level='INFO') as ordinary:
            logging.getLogger('httpx').info('unrelated nonprivate request retained')
        self.assertIn('unrelated nonprivate request retained',ordinary.output[0])

    def test_redaction_context_is_thread_local(self):
        entered=threading.Event();release=threading.Event()
        def handler(request):
            entered.set();release.wait(3)
            logging.getLogger('httpcore.concurrent').warning('secret %s',KEY)
            return httpx.Response(200,json=response())
        reader=self.reader(handler=handler)
        with self.assertLogs(level='DEBUG') as captured, ThreadPoolExecutor(1) as pool:
            work=pool.submit(reader.get_unlocked,ID,APPID)
            self.assertTrue(entered.wait(2))
            logging.getLogger('httpcore.other_request').warning('unrelated concurrent transport retained')
            release.set();self.assertEqual(work.result()['status'],'ok')
        logs='\n'.join(captured.output)
        self.assertIn('unrelated concurrent transport retained',logs);self.assertNotIn(KEY,logs)
