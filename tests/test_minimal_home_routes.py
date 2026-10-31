"""Independent minimal-home acceptance; all accounts and save data are synthetic."""
import unittest
from html.parser import HTMLParser
from urllib.parse import urlsplit, parse_qs
import test_remote_games as games
from test_remote_service import ORIGIN

class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(); self.elements=[]; self.text=[]; self.feed(source)
    def handle_starttag(self, tag, attrs): self.elements.append((tag,dict(attrs)))
    def handle_data(self, value): self.text.append(value)
    def find(self,tag,**attrs):
        return [a for t,a in self.elements if t==tag and all(a.get(k)==v for k,v in attrs.items())]

class MinimalHomeRoutes(unittest.TestCase):
    setUp=games.GameSelectionTests.setUp
    tearDown=games.GameSelectionTests.tearDown
    sign_in=games.GameSelectionTests.sign_in
    csrf=games.GameSelectionTests.csrf
    owner=games.GameSelectionTests.owner
    choose=games.GameSelectionTests.choose
    catalog=games.GameSelectionTests.catalog
    observation=games.GameSelectionTests.observation
    oauth=games.GameSelectionTests.oauth
    mcp=games.GameSelectionTests.mcp

    def assert_minimal(self,response):
        self.assertEqual(response.status_code,200)
        doc=Document(response.text)
        self.assertEqual(len(doc.find('h1')),1)
        self.assertFalse(doc.find('input',name='appid'))
        self.assertFalse(doc.find('form',action='/account/games'))
        self.assertFalse(doc.find('textarea',id='claude-prompt'))
        self.assertFalse(doc.find('input',id='mcp-url'))
        for title in ('Elden Ring','The Witcher 3','Castlevania','Baldur'):
            self.assertNotIn(title,response.text)
        self.assertLess(len(' '.join(doc.text).split()),240)
        self.assertTrue(doc.find('a',href='/connect'))
        self.assertTrue(any(a.get('id')=='assistant' for _,a in doc.elements))
        self.assertTrue(any(a.get('id')=='library' for _,a in doc.elements))
        self.assertNotIn('script-src',response.headers['content-security-policy'])

    def test_public_and_signed_in_root_are_minimal(self):
        self.assert_minimal(self.client.get('/'))
        self.sign_in(); self.assert_minimal(self.client.get('/'))
        self.choose([4231820,1245620],summary=True)
        before=self.catalog()
        self.assert_minimal(self.client.get('/'))
        self.assertEqual(self.catalog(),before)

    def test_catalog_workspace_is_separate(self):
        response=self.client.get('/games'); self.assertEqual(response.status_code,200)
        self.assertIn('Elden Ring',response.text)
        self.assertIn('/login',response.text)
        self.sign_in(); response=self.client.get('/games')
        self.assertEqual(response.status_code,200)
        self.assertTrue(Document(response.text).find('form',action='/account/games'))

    def test_legacy_game_link_keeps_valid_focus(self):
        self.sign_in(); self.choose([4231820,1245620])
        response=self.client.get('/?game=1245620')
        self.assertIn(response.status_code,(302,303,307,308))
        self.assertEqual(response.headers['location'],'/games?game=1245620')
        self.assertEqual(self.client.get(response.headers['location']).status_code,200)
        self.assertEqual(self.client.get('/games?game=292030').status_code,404)

    def test_new_workspace_keeps_human_error_recovery(self):
        self.sign_in(); self.choose([4231820])
        response=self.client.get('/games?game=292030',headers={'accept':'text/html'})
        self.assertEqual(response.status_code,404)
        self.assertIn('text/html',response.headers['content-type'])
        self.assertIn('/games',response.text)

    def test_game_selection_and_permissions_return_to_workspace(self):
        self.sign_in()
        review=self.choose([4231820,1245620],action='review')
        self.assertEqual(review.status_code,200)
        self.assertTrue(Document(review.text).find('input',name='game_4231820'))
        confirmed=self.choose([4231820,1245620],summary=True)
        self.assertEqual(confirmed.status_code,303)
        self.assertEqual(urlsplit(confirmed.headers['location']).path,'/games')
        changed=self.client.post('/account/games/permissions',data={'csrf':self.csrf(),'appid':'4231820','scope':'saves.summary','enabled':'no'},headers={'origin':ORIGIN})
        self.assertEqual(changed.status_code,303)
        self.assertEqual(changed.headers['location'],'/games?game=4231820#permissions')
        self.assertEqual({g['appid'] for g in self.catalog() if g['selected']},{4231820,1245620})

    def test_login_explicit_workspace_and_import_return_preserved(self):
        for target in ('/games','/import'):
            with self.subTest(target=target):
                self.client.cookies.clear()
                login=self.client.get('/login',params={'next':target}); self.assertEqual(login.status_code,303)
                state=parse_qs(urlsplit(self.steam.return_to).query)['state'][0]
                callback=self.client.get('/steam/callback',params={'state':state,'test_identity':'76561198000000001'})
                self.assertEqual(callback.status_code,303)
                self.assertEqual(callback.headers['location'],target)

    def test_public_claude_guide_has_trusted_endpoint_and_prompt(self):
        response=self.client.get('/connect/claude',headers={'x-forwarded-host':'untrusted.invalid'})
        self.assertEqual(response.status_code,200)
        doc=Document(response.text)
        endpoint=doc.find('input',id='mcp-url'); self.assertEqual(len(endpoint),1)
        self.assertEqual(endpoint[0]['value'],ORIGIN+'/mcp'); self.assertIn('readonly',endpoint[0])
        prompt=doc.find('textarea',id='claude-prompt'); self.assertEqual(len(prompt),1)
        self.assertIn('readonly',prompt[0]); self.assertIn('get_progress',response.text)
        self.assertIn('Register automatically',response.text)
        self.assertNotIn('untrusted.invalid',response.text)
        self.assertIn(ORIGIN+'/import',response.text)
        self.assertIn(ORIGIN+'/setup',response.text)
        self.assertNotIn('script-src',response.headers['content-security-policy'])

    def test_import_and_oauth_still_expose_only_granted_summary(self):
        self.assertEqual(self.client.get('/import').headers['location'],'/login?next=%2Fimport')
        self.sign_in(); self.choose([4231820,1245620],summary=True)
        data=self.observation()|{'csrf':self.csrf()}
        imported=self.client.post('/v1/browser/observations',json=data,headers={'origin':ORIGIN})
        self.assertEqual(imported.status_code,200)
        token=self.oauth()
        response=self.mcp(token,'tools/call',{'name':'get_progress','arguments':{}})
        self.assertEqual(response.status_code,200); self.assertIn('currentHealth',response.text)
        self.assertEqual(self.client.get('/games?game=4231820').status_code,200)
        self.assert_minimal(self.client.get('/'))

    def test_entry_and_workspace_internal_navigation_resolves(self):
        for signed_in in (False,True):
            if signed_in:
                self.sign_in(); self.choose([4231820,1245620],summary=True)
            for path in ('/','/games','/connect/claude'):
                doc=Document(self.client.get(path).text)
                ids={a['id'] for _,a in doc.elements if 'id' in a}
                for link in doc.find('a'):
                    href=link.get('href','')
                    if href.startswith('#'):
                        self.assertIn(href[1:],ids,(path,href))
                    elif href.startswith('/') and not href.startswith('/login'):
                        response=self.client.get(href)
                        self.assertIn(response.status_code,(200,303),(signed_in,path,href,response.status_code))

    def test_legacy_game_validation_is_bounded_without_state_change(self):
        self.sign_in(); self.choose([4231820],summary=True); before=self.catalog()
        for value in ('0','-1','2147483648','not-int'):
            self.assertEqual(self.client.get('/',params={'game':value}).status_code,400)
        self.assertEqual(self.catalog(),before)
