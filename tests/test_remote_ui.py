"""Presentation contracts: safe dynamic content and truthful, usable empty states."""
import unittest
from html.parser import HTMLParser
from remote_server import ui


class Elements(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.elements = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def find(self, tag, **attrs):
        return [a for t, a in self.elements if t == tag and all(a.get(k) == v for k, v in attrs.items())]


class ConsoleUITests(unittest.TestCase):
    def test_shell_is_russian_accessible_and_self_hosted(self):
        source = ui.page('<unsafe>', ui.landing_body()).body.decode()
        elements = Elements(source)
        self.assertTrue(elements.find('html', lang='ru'))
        self.assertTrue(elements.find('main', id='main'))
        self.assertTrue(elements.find('a', href='#main'))
        self.assertEqual(elements.find('link', rel='stylesheet')[0]['href'], '/assets/console.css')
        self.assertEqual(elements.find('script'), [])
        self.assertNotIn('<unsafe>', source)
        self.assertTrue(elements.find('a', href='/login'))
        self.assertIn('Steam Cloud недоступно', source)

    def test_empty_home_does_not_offer_unavailable_toggle_or_fake_progress(self):
        source = ui.home_body({'games': []}, 'token')
        elements = Elements(source)
        self.assertIn('Пока без сводки', source)
        self.assertNotIn('class="metric"', source)
        self.assertFalse(elements.find('form', action='/account/notifications'))
        self.assertIn('нет чата', source)
        for action in ['/account/revoke', '/logout']:
            self.assertTrue(elements.find('form', method='post', action=action))
        self.assertTrue(elements.find('input', name='csrf', value='token'))

    def test_scalars_are_values_not_python_dicts_or_invented_maxima(self):
        source = ui.home_body({'games':[{'appid':4231820,'received_at':100,'summary':{'player_scalars':{
            'currentHealth':{'status':'known','value':42},
            'currentMana':{'status':'unknown','value':None},
            'healthUpgradeFragmentCount':{'status':'known','value':0},
            'manaUpgradeFragmentCount':{'status':'missing','value':None}}}}]}, 'token')
        self.assertIn('<dd>42</dd>', source)
        self.assertIn('<dd>0</dd>', source)
        self.assertEqual(source.count('<dd>Неизвестно</dd>'), 2)
        self.assertNotIn("&#x27;status&#x27;", source)
        self.assertIn('Время самого сохранения неизвестно', source)
        self.assertNotIn('<progress', source)

    def test_inbox_toggle_is_explicit_and_notifications_escaped(self):
        source = ui.home_body({'games':[]}, '"<token>', {'can_enable':True,'enabled':False,'items':[
            {'id':'123" onclick="bad','message':'<script>alert(1)</script>','created_at':None,'read':False}]})
        elements = Elements(source)
        self.assertTrue(elements.find('input', name='enabled', value='yes'))
        self.assertTrue(elements.find('input', name='csrf', value='"<token>'))
        self.assertTrue(elements.find('form', method='post', action='/account/notifications/read'))
        self.assertNotIn('<script>', source)
        self.assertIn('&lt;script&gt;', source)
        self.assertFalse(any('onclick' in attrs for _, attrs in elements.elements))
        source = ui.home_body({'games':[]}, 'token', {'enabled':True,'can_enable':True,'items':[]})
        self.assertTrue(Elements(source).find('input', name='enabled', value='no'))

    def test_pair_and_consent_preserve_field_contract(self):
        elements = Elements(ui.device_body('csrf-value'))
        self.assertTrue(elements.find('form', method='post'))
        for name in ['csrf','user_code','saves.summary','saves.metadata']:
            self.assertTrue(elements.find('input', name=name))
        self.assertTrue(elements.find('select', name='appid', required=None))
        self.assertTrue(all('checked' not in item for item in elements.find('input', type='checkbox')))
        source = ui.consent_body('csrf', 'request"<>', 'Client <img src=x onerror=alert(1)>')
        elements = Elements(source)
        self.assertFalse(elements.find('img'))
        self.assertTrue(elements.find('input', name='request', value='request"<>'))
        self.assertTrue(elements.find('a', href='/'))

    def test_setup_unavailable_has_no_download_or_commands(self):
        source = ui.setup_body('https://assist.example', None)
        self.assertIn('Загрузка пока недоступна', source)
        self.assertFalse(Elements(source).find('a', href='/downloads/deck-companion.zip'))
        source = ui.setup_body('https://assist.example', 'a'*64, 'echo "<script>"')
        self.assertIn('echo &quot;&lt;script&gt;&quot;', source)
        self.assertTrue(Elements(source).find('a', href='/downloads/deck-companion.zip'))
        self.assertIn('не используй sudo', source)
        self.assertIn('требует проверки на реальном Deck', source)

    def test_mcp_connection_is_real_readonly_and_escaped(self):
        source = ui.home_body({'games':[]}, 'token', capabilities={'mcp_url':'https://assist.example/mcp'})
        elements = Elements(source)
        endpoint = elements.find('input', id='mcp-url')[0]
        self.assertIn('readonly', endpoint)
        self.assertEqual(endpoint['value'], 'https://assist.example/mcp')
        self.assertIn('мобильном ChatGPT здесь не проверена', source)
        self.assertIn('Settings → Connectors', source)
        self.assertFalse(elements.find('script'))

    def test_unknown_timestamp_and_scalar_are_safe(self):
        for value in [None, '<script>', float('inf')]:
            self.assertEqual(ui.timestamp(value), 'Время неизвестно')
        self.assertEqual(ui.scalar_text({'status':'known','value':'<script>'}), 'Неизвестно')


if __name__ == '__main__':
    unittest.main()
