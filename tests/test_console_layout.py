"""Static DOM/accessibility contracts. These do not substitute for browser layout QA."""
from html.parser import HTMLParser
from pathlib import Path
import unittest
from remote_server import ui


class Tree(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, source):
        super().__init__()
        self.stack = []
        self.nodes = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.nodes.append((tag, attrs, tuple(self.stack)))
        if tag not in self.VOID:
            self.stack.append((tag, attrs))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                self.stack = self.stack[:i]
                return

    def find(self, tag, **attrs):
        return [(a, ancestors) for t, a, ancestors in self.nodes if t == tag and all(a.get(k) == v for k, v in attrs.items())]

    @staticmethod
    def in_closed_details(ancestors):
        return any(tag == 'details' and 'open' not in attrs for tag, attrs in ancestors)


class ConsoleLayoutTests(unittest.TestCase):
    def selected_body(self, title='Custom <unsafe> game'):
        return ui.home_body({'games': []}, 'synthetic-csrf', capabilities={
            'selected_appid': 1245620,
            'catalog': [{'appid': 1245620, 'selected': True}, {'appid': 570, 'name': title, 'selected': True}],
            'owned_library': {'configured': True, 'enabled': False},
        })

    def test_public_surface_has_one_start_and_no_fictional_library(self):
        tree = Tree(ui.page('Game Assist', ui.welcome_panel()).body.decode())
        self.assertEqual(len(tree.find('h1')), 1)
        self.assertEqual(tree.find('a', **{'class': 'button primary'})[0][0]['href'], '/login?next=/games')
        self.assertEqual(len(tree.find('a', **{'class': 'button primary'})), 1)
        self.assertFalse(tree.find('aside'))
        self.assertFalse(tree.find('a', **{'class': 'game-tile selected'}))
        self.assertFalse(tree.find('form'))
        self.assertFalse(tree.find('script'))
        self.assertTrue(tree.find('nav', **{'aria-label': 'Основная навигация'}))
        self.assertTrue(tree.find('a', **{'href': '/', 'aria-current': 'page'}))
        self.assertTrue(tree.find('main', id='main', tabindex='-1'))
        self.assertTrue(tree.find('a', href='/data-handling'))

    def test_public_heading_is_short_without_forced_multiline_slogan(self):
        source = ui.welcome_panel()
        self.assertIn('<h1 id="entry-title">Игровой помощник</h1>', source)
        self.assertNotIn('Твой следующий шаг', source)
        self.assertLess(source.index('Привязать Steam'), source.index('class="entry-beta"'))
        css = (Path(ui.__file__).with_name('ui.css')).read_text()
        self.assertNotIn('max-width:12ch', css)
        self.assertIn('.entry h1{font-size:28px;letter-spacing:-.5px}', css)

    def test_chosen_game_and_shelf_are_not_hidden_in_settings(self):
        tree = Tree(self.selected_body())
        focus = tree.find('section', **{'class': 'game-focus'})
        shelf = tree.find('section', **{'class': 'selected-shelf'})
        self.assertEqual(len(focus), 1)
        self.assertEqual(len(shelf), 1)
        self.assertFalse(Tree.in_closed_details(focus[0][1]))
        self.assertFalse(Tree.in_closed_details(shelf[0][1]))
        tiles = [(a, ancestors) for t, a, ancestors in tree.nodes if t == 'a' and 'game-tile' in a.get('class', '').split() and not Tree.in_closed_details(ancestors)]
        self.assertEqual({a['href'] for a, _ in tiles}, {'/games?game=1245620#selected-game', '/games?game=570#selected-game'})
        active = [a for a, _ in tiles if a.get('aria-current') == 'page']
        self.assertEqual(len(active), 1)
        self.assertIn('1245620', active[0]['href'])
        visible_primary = [a for t, a, anc in tree.nodes if t in ('a', 'button') and 'primary' in a.get('class', '').split() and not Tree.in_closed_details(anc)]
        self.assertEqual(len(visible_primary), 1)
        self.assertEqual(visible_primary[0]['href'], '/start')

    def test_dynamic_titles_escaped_and_ids_unique(self):
        source = self.selected_body('<script>unsafe</script>')
        tree = Tree(source)
        self.assertFalse(tree.find('script'))
        ids = [a['id'] for _, a, _ in tree.nodes if 'id' in a]
        self.assertEqual(len(ids), len(set(ids)))
        for attrs, _ in tree.find('a'):
            if attrs.get('href', '').startswith('#'):
                self.assertIn(attrs['href'][1:], ids)
        self.assertIn('&lt;script&gt;unsafe&lt;/script&gt;', source)

    def test_permissions_and_destructive_actions_stay_explicit(self):
        tree = Tree(self.selected_body())
        for attrs, ancestors in tree.find('form'):
            self.assertEqual(attrs.get('method'), 'post')
            if attrs.get('action') in ('/account/revoke', '/account/games/revoke', '/logout'):
                self.assertTrue(Tree.in_closed_details(ancestors))
        self.assertTrue(tree.find('input', name='csrf', value='synthetic-csrf'))
        source = ui.games_review_body('synthetic-csrf', [{'appid': 1245620, 'selected': True}])
        self.assertFalse(any('checked' in a for a, _ in Tree(source).find('input', type='checkbox')))
        self.assertIn('Разбор сохранений этой игры пока недоступен', self.selected_body())
        self.assertNotIn('<progress', self.selected_body())

    def test_permission_is_not_presented_as_received_data(self):
        source = ui.library('Нет данных', catalog=[{'appid': 4231820, 'selected': True, 'title': 'Belmont', 'scopes': ['saves.summary']}], csrf='csrf')
        self.assertIn('Сводка разрешена', source)
        self.assertNotIn('Сводка доступна', source)

    def test_copy_and_instruction_navigation_do_not_fake_completion(self):
        source = ui.start_body('https://assist.example/mcp', 'choose')
        tree = Tree(source)
        self.assertTrue(tree.find('a', href='/start?step=choose', **{'aria-current': 'step'}))
        self.assertTrue(tree.find('p', id='start-prompt-status', role='status'))
        self.assertTrue(tree.find('textarea', id='start-prompt'))
        self.assertFalse(tree.find('input', type='checkbox'))
        self.assertTrue(tree.find('button', **{'data-copy': 'start-prompt'}))
        self.assertFalse(any(int(a.get('tabindex', '0')) > 0 for _, a, _ in tree.nodes if 'tabindex' in a))

    def test_css_has_responsive_and_keyboard_support_without_remote_assets(self):
        css = (Path(ui.__file__).with_name('ui.css')).read_text()
        self.assertIn(':focus-visible', css)
        self.assertIn('@media(max-width:700px)', css)
        self.assertIn('@media(max-width:380px)', css)
        self.assertIn('prefers-reduced-motion', css)
        self.assertIn('forced-colors', css)
        self.assertNotIn('gradient(', css)
        self.assertNotIn('url(', css)
        self.assertNotIn('@import', css)
