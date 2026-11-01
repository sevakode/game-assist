import unittest
from html.parser import HTMLParser
from remote_server import ui


class Actions(HTMLParser):
    def __init__(self, source):
        super().__init__(); self.primary = []; self.inputs = {}; self.forms = []
        self.feed(source)
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if 'primary' in a.get('class', '').split(): self.primary.append((tag, a))
        if tag == 'input': self.inputs[a['name']] = a.get('value')
        if tag == 'form': self.forms.append(a)


class SelectedNextStepTests(unittest.TestCase):
    def render(self, *, selected=True, configured=True, authorized=False, state=None, appid=4231820, scopes=(), summary=None):
        current = dict(appid=appid, selected=selected, achievements_available=configured,
                       achievements_authorized=authorized, scopes=scopes, title='UNTRUSTED_INSTRUCTION')
        return ui.selected_next_step(current, {'achievements': {'status': state, 'items': [{'name': 'HIDDEN_SENTINEL'}]}, 'summary': summary}, 'csrf-synthetic', ui.start_href(appid))

    def test_explicit_permission_then_separate_refresh_then_chat(self):
        off = self.render(); allowed = self.render(authorized=True, state='not_requested'); ready = self.render(authorized=True, state='ok')
        for source in (off, allowed, ready):
            self.assertEqual(len(Actions(source).primary), 1)
            self.assertIn('Игра выбрана', source)
            self.assertIn('Снимка сохранения нет', source)
            self.assertNotIn('HIDDEN_SENTINEL', source)
            self.assertNotIn('UNTRUSTED_INSTRUCTION', source)
            self.assertNotIn('<script', source)
        self.assertEqual(Actions(off).forms[0]['action'], '/account/games/permissions')
        self.assertEqual(Actions(off).inputs, dict(csrf='csrf-synthetic', appid='4231820', scope='achievements.read', enabled='yes'))
        self.assertNotIn('/account/achievements/refresh', off)
        self.assertEqual(Actions(allowed).forms[0]['action'], '/account/achievements/refresh')
        self.assertNotIn('name="scope"', allowed)
        self.assertEqual(Actions(ready).primary[0][1]['href'], '/start?game=4231820')

    def test_retry_expiry_and_unavailable_fallback(self):
        self.assertIn('/account/achievements/refresh', self.render(authorized=True, state='expired'))
        for state in ('unavailable', 'private', 'rate_limited', 'not_configured'):
            source = self.render(authorized=True, state=state)
            self.assertEqual(Actions(source).primary[0][0], 'a')
            self.assertFalse(Actions(source).forms)
        self.assertFalse(Actions(self.render(configured=False)).forms)
        self.assertFalse(Actions(self.render(selected=False)).forms)

    def test_optional_import_requires_existing_separate_grant(self):
        denied = self.render()
        self.assertNotIn('href="/import"', denied)
        self.assertIn('href="#save-permissions"', denied)
        allowed = self.render(scopes=['saves.summary'])
        self.assertIn('href="/import"', allowed)
        self.assertIn('Steam Cloud пока недоступно в Game Assist', allowed)
        self.assertNotIn('href="/import"', self.render(appid=1245620, scopes=['saves.summary']))
        self.assertNotIn('optional-save', self.render(summary={'player_scalars': {}}))

    def test_rendering_back_cancel_repeat_is_read_only(self):
        before = self.render()
        self.render(authorized=True, state='ok')
        self.assertEqual(self.render(), before)
        self.assertIn('Продолжить без этих данных', before)
        self.assertIn('<details class="optional-save">', before)
        self.assertNotIn(' open', before)

    def test_post_redirect_anchors_land_outside_collapsed_settings(self):
        current = dict(appid=4231820, selected=True, achievements_available=True,
                       achievements_authorized=True, authorized_scopes=['achievements.read'])
        source = ui.home_body({'games': []}, 'csrf', capabilities={'catalog': [current], 'selected_appid': 4231820})
        # The existing POST redirects must land before any collapsed settings,
        # beside the next refresh action, never on the unrelated save grant.
        hero_end = source.index('Сводка для AI') if 'Сводка для AI' in source else source.index('class="evidence-status"')
        self.assertLess(source.index('id="permissions"'), hero_end)
        self.assertLess(source.index('id="achievements"'), hero_end)
        self.assertIn('Разрешение уже дано', source[:hero_end])
        self.assertIn('/account/achievements/refresh', source[:hero_end])
        self.assertNotIn('Доступ к сохранению', source[:hero_end])
        self.assertEqual(source.count('id="permissions"'), 1)
        self.assertEqual(source.count('id="achievements"'), 1)
        self.assertIn('id="save-permissions"', source)
        self.assertIn('id="achievement-details"', source)
        self.assertIn('/games?game=4231820#save-permissions', ui.manual_import_body('csrf', False))

        ready = ui.home_body({'games': [{'appid': 4231820, 'achievements': {'status': 'ok', 'items': []}}]}, 'csrf', capabilities={'catalog': [current], 'selected_appid': 4231820, 'starter_appid': 4231820})
        hero = ready[:ready.index('class="evidence-status"')]
        self.assertIn('Снимок достижений получен', hero)
        self.assertIn('href="/start?game=4231820"', hero)
        self.assertIn('Продолжить с помощником', hero)
        self.assertNotIn('href="/connect"', hero)
        self.assertIn('Доступ к сохранению</h3><span class="status-text">Не разрешён', ready)
