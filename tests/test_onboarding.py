"""First-run routes use synthetic sessions; no Steam API or real grants."""
import unittest
from remote_server import ui
import test_remote_games as games
from test_remote_ui import Elements


class OnboardingTests(unittest.TestCase):
    setUp = games.GameSelectionTests.setUp
    tearDown = games.GameSelectionTests.tearDown
    sign_in = games.GameSelectionTests.sign_in
    csrf = games.GameSelectionTests.csrf
    owner = games.GameSelectionTests.owner
    choose = games.GameSelectionTests.choose
    catalog = games.GameSelectionTests.catalog

    def test_steam_first_and_read_only_navigation(self):
        home = Elements(self.client.get('/').text)
        self.assertEqual(home.find('a', **{'class': 'button primary'})[0]['href'], '/login?next=/games')
        self.sign_in()
        before = self.catalog()
        for path in ['/start', '/start?step=choose', '/start?step=play', '/start?step=choose', '/start']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn("script-src 'self'", response.headers['content-security-policy'])
            doc = Elements(response.text)
            self.assertEqual(len(doc.find('a', **{'class': 'button primary'})), 1)
            self.assertFalse(doc.find('form'))
        self.assertEqual(before, self.catalog())
        self.assertEqual(self.client.get('/start?step=unknown').status_code, 400)

    def test_unconfigured_library_has_immediate_next_action(self):
        source = ui.owned_library_panel('csrf', {'configured': False, 'enabled': False})
        doc = Elements(source)
        self.assertEqual(doc.find('a', **{'class': 'button primary'})[0]['href'], '/start')
        self.assertIn('Продолжить без данных', source)
        self.assertFalse(doc.find('form'))
        self.assertLess(source.index('Продолжить без данных'), source.index('class="action-row"'))
        unknown = ui.owned_library_panel('csrf', {'configured': True, 'enabled': True, 'status': 'ok', 'games': [{'appid': 570, 'name': 'Game'}]})
        self.assertIn('Добавить, затем выбрать', unknown)
        self.assertIn('После добавления открой «Выбрать игру из списка»', unknown)
        self.assertNotIn('После добавления откроется список', unknown)
        self.assertTrue(Elements(unknown).find('form', action='/account/games/add'))

    def test_guides_explain_independent_optional_library_permissions(self):
        short = ui.start_body('https://assist.example/mcp')
        self.assertIn('Базовый доступ — к разрешённым данным прогресса', short)
        self.assertIn('Отдельно отметь доступ к библиотеке при подключении помощника', short)
        self.assertIn('разреши её чтение на сайте', short)
        self.assertIn('Это необязательно и не открывает закрытую библиотеку Steam', short)
        detailed = ui.claude_body('https://assist.example/mcp')
        self.assertIn('<code>progress.read</code>', detailed)
        self.assertIn('необязательный доступ к библиотеке <code>library.read</code>', detailed)
        self.assertIn('отдельно разреши чтение библиотеки на сайте', detailed)
        self.assertIn('Без обоих разрешений список недоступен помощнику', detailed)
        self.assertNotIn('подтверди только чтение данных', detailed)
        for source in (short, detailed):
            self.assertFalse(Elements(source).find('input', type='checkbox'))

    def test_copy_feedback_is_adjacent_and_claude_opens_at_first_step(self):
        for step, field in [('connect', 'phone-prompt'), ('choose', 'start-prompt')]:
            source = ui.start_body('https://assist.example/mcp', step)
            doc = Elements(source)
            button = doc.find('button', **{'data-copy': field})[0]
            self.assertEqual(button['aria-describedby'], field + '-status')
            self.assertTrue(doc.find('p', id=field + '-status', role='status', **{'aria-live': 'polite', 'aria-atomic': 'true'}))
            self.assertLess(source.index('id="' + field + '-status"'), source.index('class="button primary"'))
            self.assertFalse(doc.find('p', id='copy-status'))
        doc = Elements(ui.start_body('https://assist.example/mcp'))
        link = doc.find('a', href='https://claude.ai/')[0]
        self.assertEqual(link['class'], 'button primary')
        self.assertEqual(link['target'], '_blank')
        self.assertIn('noopener', link['rel'])
        self.assertEqual(len(doc.find('a', **{'class': 'button primary'})), 1)

    def test_phone_flow_return_and_repeat_do_not_change_selection(self):
        self.sign_in()
        self.choose([1245620])
        before = self.catalog()
        for path in ['/start', '/start?step=choose', '/start', '/games', '/start', '/start?step=play', '/games']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.catalog(), before)
        self.assertTrue(Elements(self.client.get('/start').text).find('a', href='/games'))

    def test_connect_keeps_data_disclosure_link(self):
        self.assertTrue(Elements(self.client.get('/connect').text).find('a', href='/data-handling'))

    def test_library_choice_keeps_previous_selection_without_granting(self):
        panel = Elements(ui.owned_library_panel('csrf', {'configured': True, 'enabled': True, 'status': 'ok', 'games': [{'appid': 1245620, 'name': 'ER'}]}, [1245620], [4231820]))
        self.assertTrue(panel.find('input', name='game_4231820', value='yes'))
        self.assertTrue(panel.find('input', name='game_1245620', value='yes'))
        self.assertTrue(panel.find('button', name='action', value='review'))
        self.assertFalse(panel.find('input', name='summary_4231820'))
        self.assertFalse(panel.find('input', name='scope'))

    def test_script_is_local_and_copy_only_has_public_text(self):
        result = self.client.get('/assets/onboarding.js')
        self.assertEqual(result.status_code, 200)
        self.assertIn('javascript', result.headers['content-type'])
        for forbidden in ['localStorage', 'sessionStorage', 'fetch(', 'document.cookie']:
            self.assertNotIn(forbidden, result.text)
        source = ui.start_body('https://assist.example/mcp')
        doc = Elements(source)
        self.assertEqual(doc.find('input', id='start-endpoint')[0]['value'], 'https://assist.example/mcp')
        self.assertIn('hidden', doc.find('button')[0])
        self.assertIn('readonly', doc.find('input')[0])
        self.assertFalse(doc.find('input', type='hidden'))
        self.assertIn('скопировать вручную', source)
        self.assertIn('&lt;unsafe&gt;', ui.start_body('<unsafe>'))

    def test_new_account_permissions_remain_explicit_and_off(self):
        self.sign_in()
        page = Elements(self.client.get('/games').text)
        self.assertFalse(any('checked' in field for field in page.find('input', type='checkbox')))
        review = self.choose([4231820], action='review')
        doc = Elements(review.text)
        self.assertFalse(any('checked' in field for field in doc.find('input', type='checkbox')))
        library = Elements(ui.owned_library_panel('synthetic-csrf', {'configured': True, 'enabled': False}))
        self.assertEqual(len(library.find('form', action='/account/library/permission')), 1)
        self.assertFalse(library.find('form', action='/account/library/refresh'))
        self.assertEqual(library.find('input', name='enabled')[0]['value'], 'yes')
        enabled = Elements(ui.owned_library_panel('synthetic-csrf', {'configured': True, 'enabled': True}))
        self.assertEqual(len(enabled.find('form', action='/account/library/refresh')), 1)
