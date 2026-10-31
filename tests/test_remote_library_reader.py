import io,json,logging,unittest
import httpx
from remote_server.library_reader import LibraryReader,ENDPOINT
STEAM='76561198000000001'
class LibraryReaderTests(unittest.TestCase):
    def response(self,**extra):return {'response':{'game_count':1,'games':[{'appid':1086940,'name':"Baldur's Gate 3",'playtime_forever':999,'img_icon_url':'PRIVATE_ART'}],**extra}}
    def read(self,data,status=200):return LibraryReader('SYNTHETIC_KEY',transport=httpx.MockTransport(lambda _:httpx.Response(status,json=data))).get_games(STEAM)
    def test_header_fixed_request_minimal_result(self):
        def handle(request):
            self.assertEqual(str(request.url).split('?')[0],ENDPOINT)
            self.assertEqual(request.headers['x-webapi-key'],'SYNTHETIC_KEY')
            self.assertNotIn('SYNTHETIC_KEY',str(request.url))
            self.assertEqual(json.loads(request.url.params['input_json']),{'steamid':STEAM,'include_appinfo':True,'include_played_free_games':True})
            return httpx.Response(200,json=self.response())
        result=LibraryReader('SYNTHETIC_KEY',transport=httpx.MockTransport(handle)).get_games(STEAM)
        self.assertEqual(result['status'],'ok');self.assertEqual(result['games'],[{'appid':1086940,'name':"Baldur's Gate 3"}])
        self.assertNotIn('playtime',json.dumps(result));self.assertNotIn('PRIVATE_ART',json.dumps(result))
    def test_absent_key_no_io_and_empty_private_unknown(self):
        def fail(_):self.fail('No key must not call transport')
        self.assertEqual(LibraryReader('',transport=httpx.MockTransport(fail)).get_games(STEAM)['status'],'not_configured')
        for data in ({},{'response':{}},{'response':{'game_count':0,'games':[]}},self.response(steamid='76561198000000002')):
            self.assertEqual(self.read(data)['status'],'unavailable')
    def test_invalid_rows_counts_caps_and_upstream(self):
        for games in ([{'appid':True,'name':'bad'}],[{'appid':0,'name':'bad'}],[{'appid':1,'name':'x'*121}],[{'appid':1,'name':'bad\n'}],[{'appid':1,'name':'same'}]*2,[{'appid':i+1,'name':'ok'} for i in range(1001)]):
            self.assertEqual(self.read(self.response(games=games,game_count=len(games)))['status'],'unavailable')
        self.assertEqual(self.read(self.response(game_count=2))['status'],'unavailable')
        for status in (302,401,403,429,500):self.assertEqual(self.read(self.response(),status)['status'],'unavailable')
        huge=httpx.MockTransport(lambda _:httpx.Response(200,content=b'x'*1048577))
        self.assertEqual(LibraryReader('SYNTHETIC_KEY',transport=huge).get_games(STEAM)['status'],'unavailable')
    def test_private_transport_logs_are_redacted(self):
        stream=io.StringIO();handler=logging.StreamHandler(stream);logger=logging.getLogger('httpx');before=logger.level;logger.setLevel(logging.DEBUG);logger.addHandler(handler)
        try:self.assertEqual(self.read(self.response())['status'],'ok')
        finally:logger.removeHandler(handler);logger.setLevel(before)
        self.assertNotIn(STEAM,stream.getvalue());self.assertNotIn('SYNTHETIC_KEY',stream.getvalue())
    def test_duplicate_json_and_nonfinite_fail_closed(self):
        for raw in (b'{"response":{},"response":{}}',b'{"response":{"game_count":NaN}}'):
            reader=LibraryReader('SYNTHETIC_KEY',transport=httpx.MockTransport(lambda _:httpx.Response(200,content=raw)))
            self.assertEqual(reader.get_games(STEAM)['status'],'unavailable')
