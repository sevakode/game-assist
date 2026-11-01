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
        self.assertEqual(library.find('input', name='action')[0]['value'], 'enable_and_refresh')
        enabled = Elements(ui.owned_library_panel('synthetic-csrf', {'configured': True, 'enabled': True}))
        self.assertEqual(len(enabled.find('form', action='/account/library/refresh')), 1)

    def test_explicit_game_helper_preserves_only_clicked_public_topic(self):
        from html import unescape
        import re
        self.sign_in()
        self.choose([4231820, 1245620, 292030])
        before = self.catalog()
        for appid, title in [(1245620, 'Elden Ring'), (292030, 'The Witcher 3: Wild Hunt')]:
            source = self.client.get('/games?game=' + str(appid)).text
            primary = Elements(source).find('a', **{'class': 'button primary'})[0]
            self.assertEqual(primary['href'], '/start?game=' + str(appid))
            for step, field in [('connect', 'phone-prompt'), ('choose', 'start-prompt')]:
                result = self.client.get(ui.start_href(appid, step))
                self.assertEqual(result.status_code, 200)
                prompt = unescape(re.search(r'<textarea id="' + field + r'"[^>]*>(.*?)</textarea>', result.text, re.S)[1])
                self.assertIn(f'Хочу обсудить {title} (AppID {appid})', prompt)
                self.assertIn('не подтверждение запущенной игры или владения', prompt)
                self.assertIn('Спроси, где я остановился', prompt)
                self.assertNotIn('Спроси, во что я играю', prompt)
                self.assertNotIn('Спроси, в какую игру я сейчас играю', prompt)
                self.assertNotIn('currentHealth', prompt)
                self.assertNotIn('csrf', prompt)
                self.assertNotIn('AppID 4231820', prompt)
        self.assertEqual(before, self.catalog())

    def test_default_and_multiselect_do_not_infer_starter_topic(self):
        self.sign_in()
        for choices in ([1245620], [4231820, 1245620, 292030]):
            self.choose(choices)
            source = self.client.get('/games').text
            self.assertEqual(Elements(source).find('a', **{'class': 'button primary'})[0]['href'], '/start')
            generic = self.client.get('/start').text
            self.assertIn('Спроси, во что я играю', generic)
            self.assertNotIn('Тема разговора:', generic)
            self.assertNotIn('Хочу обсудить', generic)

    def test_starter_topic_survives_step_navigation_repeat_and_back(self):
        appid = 1245620
        for step in ['connect', 'choose', 'play', 'choose', 'connect']:
            result = self.client.get(ui.start_href(appid, step))
            self.assertEqual(result.status_code, 200)
            doc = Elements(result.text)
            self.assertIn('Тема разговора: Elden Ring (AppID 1245620)', result.text)
            for next_step in ['connect', 'choose', 'play']:
                self.assertTrue(doc.find('a', href=ui.start_href(appid, next_step)))
            back = doc.find('a', **{'class': 'back-link'})[0]['href']
            self.assertEqual(back, {'connect': '/games?game=1245620', 'choose': ui.start_href(appid), 'play': ui.start_href(appid, 'choose')}[step])
            self.assertFalse(doc.find('form'))
            self.assertFalse(doc.find('input', type='hidden'))
            self.assertFalse(doc.find('script', src='/assets/ai-export.js'))
            self.assertEqual(result.headers['cache-control'], 'no-store')
            self.assertEqual(result.headers['referrer-policy'], 'strict-origin')
        play = self.client.get(ui.start_href(appid, 'play')).text
        self.assertIn('Хочу обсудить Elden Ring (AppID 1245620).', play)
        self.assertNotIn('Играю в …', play)
        self.assertEqual(self.client.get('/start').status_code, 200)

    def test_starter_identity_is_public_not_a_private_label_or_query_copy(self):
        from unittest.mock import patch
        from remote_server.app import COOKIE
        self.sign_in()
        owner = self.owner()
        with self.app.state.store.db() as db:
            db.execute('INSERT INTO game_registrations(owner,appid,label,created) VALUES(?,?,?,?)', (owner, 570, 'PRIVATE_LABEL_IGNORE_RULES', 1))
        self.choose([570, 1245620])
        source = self.client.get('/games?game=570').text
        self.assertIn('PRIVATE_LABEL_IGNORE_RULES', source)
        self.assertEqual(Elements(source).find('a', **{'class': 'button primary'})[0]['href'], '/start?game=570')
        forbidden = ['PRIVATE_LABEL_IGNORE_RULES', 'PRIVATE_QUERY_TOKEN', 'PRIVATE_QUERY_TITLE', self.client.cookies[COOKIE], self.csrf(), self.owner()]
        for appid, expected in [(570, 'Steam (AppID 570)'), (1086940, 'Baldur&#x27;s Gate 3 (AppID 1086940)')]:
            with patch.object(self.app.state.store, 'session', side_effect=AssertionError('Starter must not read the session')), patch.object(self.app.state.store, 'catalog', side_effect=AssertionError('Starter must not read account labels')), patch.object(self.app.state.store, 'projection', side_effect=AssertionError('Starter must not read data')):
                result = self.client.get(f'/start?game={appid}&title=PRIVATE_QUERY_TITLE&token=PRIVATE_QUERY_TOKEN')
            self.assertEqual(result.status_code, 200)
            self.assertIn(expected, result.text)
            for value in forbidden:
                self.assertNotIn(value, result.text)
            for anchor in Elements(result.text).find('a'):
                self.assertNotIn('token=', anchor.get('href', ''))
                self.assertNotIn('title=', anchor.get('href', ''))

    def test_starter_rejects_invalid_or_ambiguous_appids_without_reflection(self):
        for value in ['', '0', '-1', '01', '1.0', '2147483648', '1%0A', 'true', '%3Cscript%3E']:
            self.assertEqual(self.client.get('/start?game=' + value).status_code, 422)
        self.assertEqual(self.client.get('/start?game=1245620&game=292030').status_code, 400)
        self.assertEqual(self.client.get('/start?game=2147483647').status_code, 200)
        for value in [None, True, False, '1245620', 0, -1, 2147483648, '<script>']:
            self.assertIsNone(ui.starter_game(value))
            self.assertEqual(ui.start_href(value), '/start')

    def test_external_ai_spoiler_limit_visible_beside_transition(self):
        for step in ['connect', 'play']:
            source = ui.start_body('https://assist.example/mcp', step, 1245620)
            note = 'но не гарантирует ответ внешнего AI без спойлеров'
            self.assertEqual(source.count(note), 1)
            self.assertGreater(source.index(note), source.index('Открыть Claude →'))
            self.assertLess(source.index(note), source.index('<details'))
