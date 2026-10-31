"""Discovery wiring is public-only; snapshots and authorization remain private."""
import unittest
from html.parser import HTMLParser
from remote_server import ui, discovery
import test_remote_service as service
ORIGIN=service.ORIGIN

class Head(HTMLParser):
    def __init__(self, source):
        super().__init__(); self.nodes=[];self.feed(source)
    def handle_starttag(self, tag, attrs):self.nodes.append((tag,dict(attrs)))
    def find(self,tag,**attrs):return [a for t,a in self.nodes if t==tag and all(a.get(k)==v for k,v in attrs.items())]

class DiscoveryIntegration(unittest.TestCase):
    setUp=service.RemoteTests.setUp
    tearDown=service.RemoteTests.tearDown
    sign_in=service.RemoteTests.sign_in

    def test_fixed_public_head_and_existing_security(self):
        for path in ('/','/connect','/connect/claude','/setup'):
            r=self.client.get(path+'?source=private-query',headers={'x-forwarded-host':'untrusted.invalid'})
            self.assertEqual(r.status_code,200)
            doc=Head(r.text)
            self.assertEqual(doc.find('link',rel='canonical'),[{'rel':'canonical','href':ORIGIN+path}])
            self.assertFalse(doc.find('meta',name='robots'))
            self.assertEqual(len(doc.find('script',type='application/ld+json')),1)
            self.assertNotIn('untrusted.invalid',r.text)
            self.assertNotIn('private-query',r.text)
            self.assertNotIn("'unsafe-inline'",r.headers.get('content-security-policy',''))
            self.assertIn("default-src 'none'",r.headers['content-security-policy'])

    def test_private_and_error_views_default_noindex(self):
        self.sign_in()
        for path in ('/games','/games?game=0','/import'):
            r=self.client.get(path,headers={'accept':'text/html'})
            doc=Head(r.text)
            self.assertTrue(doc.find('meta',name='robots',content='noindex, nofollow'),path)
            self.assertFalse(doc.find('link',rel='canonical'))
        self.assertIn(discovery.NOINDEX_HEAD,ui.page('Private','private').body.decode())
        with self.assertRaises(TypeError):ui.page('Private','private','untrusted')

    def test_public_files_mounted_once_and_hub_uses_real_button(self):
        for path in ('/connect','/robots.txt','/sitemap.xml','/llms.txt'):
            self.assertEqual(sum(getattr(r,'path',None)==path for r in self.app.routes),1)
            self.assertEqual(self.client.get(path).status_code,200)
        doc=Head(self.client.get('/connect').text)
        links=doc.find('a',href='/connect/claude')
        self.assertEqual(len(links),1)
        self.assertEqual(links[0]['class'],'button primary')
        self.assertFalse(doc.find('button'))
        home=Head(self.client.get('/').text)
        self.assertTrue(home.find('a',href='/connect',id='assistant'))
        self.assertFalse(home.find('textarea'))

    def test_optional_tools_do_not_disable_working_progress_or_infer_current_game(self):
        text=ui.claude_starter_prompt(ORIGIN+'/mcp')
        for phrase in ('Если доступен get_connection_status','затем вызови get_progress',
                       'Если get_progress работает','отсутствие get_connection_status или get_library',
                       'вызови его один раз','не назначай её автоматически','Каталог сервиса не означает владение',
                       'не определяют текущую игру','явное согласие','Steam Cloud здесь недоступен',
                       'не максимумы','Не имитируй вызовы','не число готовых улучшений'):
            self.assertIn(phrase,text)
        self.assertNotIn('скажи «Game Assist не подключён»',text)
        guide=self.client.get('/connect/claude').text
        self.assertEqual(len(Head(guide).find('textarea',id='claude-prompt',readonly=None)),1)
