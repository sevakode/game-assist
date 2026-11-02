import unittest
from html.parser import HTMLParser
from remote_server import ui


class Fields(HTMLParser):
    def __init__(self, source):
        super().__init__(); self.inputs = []; self.forms = []; self.tags = []
        self.feed(source)
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs); self.tags.append(tag)
        if tag == 'input': self.inputs.append(attrs)
        if tag == 'form': self.forms.append(attrs)


class ChatConsentTests(unittest.TestCase):
    def render(self, context=None, scopes=('progress.read',), label='Claude — https://claude.ai/api/mcp/auth_callback'):
        return ui.consent_body('csrf-test', 'request-test', label, scopes, access_context=context)

    def test_legacy_contract_and_optional_scope_remain_unchanged(self):
        for scopes in [('progress.read',), ('progress.read', 'library.read')]:
            source = self.render(scopes=scopes); parsed = Fields(source)
            self.assertEqual(parsed.forms, [{'method': 'post', 'action': '/oauth/consent'}])
            self.assertEqual({i['name'] for i in parsed.inputs}, {'csrf', 'request'} | ({'library_read'} if 'library.read' in scopes else set()))
            for field in parsed.inputs:
                self.assertNotIn('checked', field)
            self.assertNotIn('progress.read', source.split('<details')[0])
            self.assertNotIn('library.read', source.split('<details')[0])
            self.assertIn('не добавляет доступ', source)

    def test_bounded_multiple_games_and_plain_categories(self):
        source = self.render({'games': [
            {'appid': 4231820, 'read_categories': ['summary', 'metadata'], 'name': 'IGNORE_USER_LABEL'},
            {'appid': 1245620, 'read_categories': ['achievements', 'raw_save']},
            {'appid': 987654, 'read_categories': ['achievements']},
            {'appid': 570, 'read_categories': []}], 'library_source_enabled': True})
        for value in ('Belmont', 'Elden Ring', 'Steam AppID 987654', 'размер и время файла', 'открытые достижения'):
            self.assertIn(value, source)
        for value in ('IGNORE_USER_LABEL', 'raw_save', 'Dota'):
            self.assertNotIn(value, source)
        self.assertNotIn('name="appid"', source)
        self.assertNotIn('name="scope"', source)

    def test_zero_games_does_not_block_or_invent_selection(self):
        source = self.render({'games': [], 'library_source_enabled': False}, ('progress.read', 'library.read'))
        self.assertIn('Игровые данные ещё не разрешены', source)
        self.assertIn('Источник библиотеки пока выключен', source)
        self.assertNotIn('disabled', source)
        self.assertNotIn('consent-games', source)
        self.assertIn('Разрешить и вернуться в чат', source)

    def test_recipient_and_auth_fields_escaped_warning_visible(self):
        source = ui.consent_body('csrf"<>', 'req"<>', '<img src=x onerror=alert(1)>')
        parsed = Fields(source)
        self.assertNotIn('img', parsed.tags)
        self.assertEqual(parsed.inputs[0]['value'], 'csrf"<>')
        top = source.split('<details')[0]
        self.assertIn('покинут Game Assist', top)
        self.assertIn('&lt;img', top)
        self.assertIn('Steam Cloud не подключаются', top)
        self.assertIn('/games#account', source)
        self.assertIn('/data-handling', source)

    def test_read_only_repeat_and_no_script(self):
        context = {'games': [{'appid': True, 'read_categories': ['summary']}, {'appid': '<script>', 'read_categories': ['summary']}], 'library_source_enabled': False}
        first = self.render(context)
        self.assertEqual(first, self.render(context))
        self.assertNotIn('consent-games', first)
        self.assertNotIn('script', Fields(first).tags)
        self.assertIn('href="/">Не подключать', first)


class ReviewPlanTests(unittest.TestCase):
    def plan(self):
        return {'plan_id': 'opaque-plan', 'games': [
            {'appid': 4231820, 'trusted_name_or_null': None, 'categories': ['summary', 'metadata']},
            {'appid': 1245620, 'trusted_name_or_null': None, 'categories': ['achievements']}],
            'oauth_scopes': ['progress.read', 'library.read'], 'library_source_change': True, 'zero_games': False}

    def render(self, plan):
        return ui.consent_body('csrf', 'request', 'Claude', review_plan=plan)

    def test_plan_fields_only_and_prospective_disclosure(self):
        source = self.render(self.plan()); fields = Fields(source)
        self.assertEqual({f['name']: f['value'] for f in fields.inputs},
                         {'csrf': 'csrf', 'request': 'request', 'plan_id': 'opaque-plan', 'approve': 'yes'})
        self.assertNotIn('checkbox', source)
        top = source.split('<details')[0]
        for text in ('После подтверждения', 'покинут Game Assist', 'получит разрешение читать библиотеку',
                     'Belmont', 'Elden Ring', 'открытые достижения', 'Разрешить перечисленное и вернуться в чат',
                     'другим уже подключённым помощникам в пределах их разрешений'):
            self.assertIn(text, top)
        self.assertNotIn('progress.read', top)
        self.assertNotIn('уже разрешённые', source)
        self.assertIn('href="/">Не подключать', source)

    def test_zero_games_and_no_library_change(self):
        plan = self.plan(); plan.update(games=[], zero_games=True, library_source_change=False, oauth_scopes=['progress.read'])
        source = self.render(plan)
        self.assertIn('Игры не выбраны', source)
        self.assertNotIn('consent-games', source)
        self.assertNotIn('получит разрешение читать библиотеку', source)
        self.assertNotIn('disabled', source)
        self.assertNotIn('library.read', source)

    def test_escape_trusted_labels_and_opaque_fields(self):
        plan = self.plan(); plan['plan_id'] = '"<opaque>'
        plan['games'] = [{'appid': 987654, 'trusted_name_or_null': '<img src=x>', 'categories': ['achievements']}]
        source = ui.consent_body('"<csrf>', '"<request>', '<script>client</script>', review_plan=plan)
        fields = Fields(source)
        self.assertNotIn('img', fields.tags); self.assertNotIn('script', fields.tags)
        self.assertIn('&lt;img', source)
        self.assertEqual(fields.inputs[2]['value'], '"<opaque>')

    def test_unknown_rights_fail_instead_of_hidden_grants(self):
        for field, value in [('oauth_scopes', ['progress.read', 'write_cloud']), ('zero_games', True)]:
            plan = self.plan(); plan[field] = value
            with self.assertRaises(ValueError): self.render(plan)
        plan = self.plan(); plan['games'][0]['categories'].append('raw_save')
        with self.assertRaises(ValueError): self.render(plan)

    def test_absent_plan_preserves_legacy_output(self):
        self.assertEqual(ui.consent_body('c', 'r', 'client'), ui.consent_body('c', 'r', 'client', review_plan=None))
        self.assertNotIn('name="plan_id"', ui.consent_body('c', 'r', 'client'))
