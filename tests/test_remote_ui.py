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
        self.assertIn('Steam Cloud недоступен', source)

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
        for name in ['csrf','user_code','saves.summary']:
            self.assertTrue(elements.find('input', name=name))
        self.assertTrue(elements.find('input', name='saves.metadata'))
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

    def test_console_layout_has_real_controls_and_no_marketing_shell(self):
        source = ui.landing_body()
        elements = Elements(source)
        self.assertTrue(elements.find('aside', id='library'))
        self.assertTrue(elements.find('header', id='selected-game'))
        self.assertTrue(elements.find('section', id='context'))
        self.assertIn('Добавленные игры, не библиотека твоего Steam', source)
        self.assertNotIn('class="hero"', source)
        self.assertNotIn('eyebrow', source)
        self.assertNotIn('Продолжим', source)
        self.assertNotIn('<em>', source)
        self.assertEqual(source.count('Steam Cloud'), 1)
        self.assertFalse(elements.find('progress'))
        self.assertTrue(elements.find('a', href='/devices/approve'))
        self.assertTrue(elements.find('a', href='/setup'))

    def test_revoke_requires_expanding_explicit_consequence(self):
        source = ui.home_body({'games': []}, 'token')
        elements = Elements(source)
        self.assertTrue(elements.find('details', **{'class':'revoke-confirm'}))
        self.assertIn('удалит сводки с сервера', source)
        self.assertTrue(elements.find('form', method='post', action='/account/revoke'))

    def test_three_game_chooser_uses_unique_fields_and_explicit_review(self):
        catalog = [{'appid':4231820,'selected':True,'authorized':True}, {'appid':1245620,'selected':False,'authorized':False}, {'appid':292030,'selected':True,'authorized':False}]
        source = ui.home_body({'games':[]}, 'csrf', capabilities={'catalog':catalog,'selected_appid':292030})
        elements = Elements(source)
        self.assertTrue(elements.find('form', method='post', action='/account/games'))
        for appid in ui.GAMES:
            self.assertTrue(elements.find('input', name=f'game_{appid}', value='yes'))
        self.assertTrue(elements.find('button', name='action', value='review_all'))
        self.assertTrue(elements.find('button', name='action', value='review'))
        self.assertFalse(elements.find('input', name='selected_appids'))
        self.assertIn('не включает будущие добавления', source)
        self.assertIn('Прогресс пока не расшифровывается', source)
        self.assertFalse(elements.find('form', action='/account/notifications'))
        self.assertTrue(elements.find('input', name='scope', value='saves.metadata'))
        self.assertFalse(elements.find('input', name='scope', value='saves.summary'))
        self.assertNotIn('class="metric"', source)

    def test_review_all_three_has_only_real_permission_and_exact_revision(self):
        catalog = [{'appid':appid,'selected':True,'authorized':False} for appid in ui.GAMES]
        source = ui.games_review_body('csrf',catalog)
        elements = Elements(source)
        self.assertTrue(elements.find('input', name='catalog_revision', value='initial-three-v1'))
        self.assertTrue(elements.find('input', name='action', value='confirm'))
        self.assertEqual(len(elements.find('input', type='checkbox')), 4)
        self.assertNotIn('checked', elements.find('input', name='summary_4231820')[0])
        for appid in ui.GAMES:
            self.assertTrue(elements.find('input', name=f'game_{appid}', value='yes'))
        self.assertIn('Elden Ring', source)
        self.assertIn('The Witcher 3', source)
        self.assertIn('Локальные сохранения не меняются', source)

    def test_selected_belmont_permission_is_separate_from_game_choice(self):
        source = ui.home_body({'games':[]}, 'csrf', capabilities={'catalog':[{'appid':4231820,'selected':True,'authorized':False}]})
        elements = Elements(source)
        self.assertTrue(elements.find('form', action='/account/games/permissions', method='post'))
        self.assertTrue(elements.find('input', name='scope', value='saves.summary'))
        self.assertTrue(elements.find('input', name='enabled', value='yes'))
        self.assertIn('Разрешить сводку из 4 полей', source)
        source = ui.home_body({'games':[]}, 'csrf', capabilities={'catalog':[{'appid':4231820,'selected':True,'authorized':True}]})
        self.assertTrue(Elements(source).find('input', name='enabled', value='no'))

    def test_public_other_game_never_implies_working_decoder(self):
        for appid in (1245620,292030):
            source=ui.landing_body(appid)
            self.assertIn(ui.GAMES[appid], source)
            self.assertIn('Декодер этой игры пока недоступен', source)
            self.assertFalse(Elements(source).find('a', href='/devices/approve'))

    def test_custom_game_is_escaped_selectable_and_has_no_decoder_claim(self):
        custom={'appid':570,'name':'My <img src=x onerror=alert(1)>','selected':True,'authorized':False,'user_label_unverified':True}
        source=ui.home_body({'games':[]}, 'csrf', capabilities={'catalog':[custom],'selected_appid':570})
        elements=Elements(source)
        self.assertFalse(elements.find('img'))
        self.assertIn('My &lt;img', source)
        self.assertIn('Название задано пользователем; не проверено', source)
        self.assertTrue(elements.find('input', name='game_570', value='yes'))
        self.assertIn('Выбрать все текущие (4)', source)
        self.assertIn('Обновления для этой игры недоступны', source)
        self.assertTrue(elements.find('input', name='scope', value='saves.metadata'))
        self.assertFalse(elements.find('input', name='scope', value='saves.summary'))
        review=ui.games_review_body('csrf',[custom],catalog_revision='revision"<safe>')
        fields=Elements(review)
        self.assertTrue(fields.find('input', name='catalog_revision', value='revision"<safe>'))
        self.assertTrue(fields.find('input', name='game_570', value='yes'))
        self.assertNotIn('Только эти три', review)
        self.assertFalse(fields.find('input', name='summary_570'))

    def test_add_game_form_has_validated_identifier_and_optional_label(self):
        elements=Elements(ui.home_body({'games':[]}, 'csrf'))
        self.assertTrue(elements.find('form', method='post', action='/account/games/add'))
        appid=elements.find('input', name='appid', type='number')[0]
        self.assertEqual(appid['min'],'1')
        self.assertEqual(appid['max'],'2147483647')
        self.assertIn('required', appid)
        label=elements.find('input', name='label')[0]
        self.assertEqual(label['maxlength'],'120')
        self.assertNotIn('required',label)

    def test_generic_metadata_never_exposes_content_path_or_invents_progress(self):
        custom={'appid':570,'name':'Custom game','selected':True,'metadata_authorized':True,'authorized_scopes':['saves.metadata']}
        projection={'games':[{'appid':570,'metadata':{'size_bytes':4096,'modified_ns':0,'path':'private-path','content':'private-content'}}]}
        source=ui.home_body(projection,'csrf',capabilities={'catalog':[custom],'selected_appid':570})
        self.assertIn('4 096 байт',source)
        self.assertIn('01.01.1970',source)
        self.assertNotIn('private-path',source)
        self.assertNotIn('private-content',source)
        self.assertNotIn('class="metric"',source)
        self.assertIn('Это сведения о файле, не расшифрованный прогресс',source)
        elements=Elements(source)
        self.assertTrue(elements.find('input', name='scope',value='saves.metadata'))
        self.assertTrue(elements.find('input', name='enabled',value='no'))
        review=Elements(ui.games_review_body('csrf',[custom],catalog_revision='rev'))
        self.assertIn('checked',review.find('input',name='metadata_570')[0])
        self.assertFalse(review.find('input',name='summary_570'))

    def test_pairing_catalog_lists_only_selected_and_new_permissions_unchecked(self):
        source=ui.device_body('csrf',[{'appid':570,'name':'Mine','selected':True},{'appid':292030,'selected':False}],{'appid':570})
        elements=Elements(source)
        self.assertTrue(elements.find('option',value='570'))
        self.assertFalse(elements.find('option',value='292030'))
        self.assertFalse(elements.find('option',value='4231820'))
        self.assertTrue(all('checked' not in el for el in elements.find('input',type='checkbox')))
        self.assertIn('содержимое сейва на сервер не отправляется',source)

    def test_all_views_have_unique_ids_and_no_nested_forms(self):
        class Forms(HTMLParser):
            def __init__(self,source):
                super().__init__(); self.open_form=False; self.nested=False; self.ids=[]; self.feed(source)
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if 'id' in attrs: self.ids.append(attrs['id'])
                if tag=='form':
                    if self.open_form: self.nested=True
                    self.open_form=True
            def handle_endtag(self,tag):
                if tag=='form': self.open_form=False
        catalog=[{'appid':appid,'selected':True,'name':name} for appid,name in ui.GAMES.items()]+[{'appid':570,'name':'X'*120,'selected':True}]
        views=[ui.landing_body(),ui.home_body({'games':[]},'csrf',capabilities={'catalog':catalog,'selected_appid':570}),ui.games_review_body('csrf',catalog,'revision'),ui.device_body('csrf',catalog),ui.consent_body('csrf','req','client'),ui.setup_body('https://example.com',None)]
        for view in views:
            parsed=Forms(ui.page('View',view).body.decode())
            self.assertFalse(parsed.nested)
            self.assertEqual(len(parsed.ids),len(set(parsed.ids)))

    def test_summary_receipt_is_not_refreshed_by_new_metadata(self):
        game={'appid':4231820,'summary':{'player_scalars':{}},'received_at':2000,'metadata_received_at':2000,'summary_received_at':1000}
        source=ui.home_body({'games':[game]}, 'csrf')
        self.assertIn('Получено: '+ui.timestamp(1000),source)
        self.assertNotIn('Получено: '+ui.timestamp(2000),source)
        game['summary_received_at']=None
        source=ui.home_body({'games':[game]}, 'csrf')
        self.assertIn('Получено: Время неизвестно',source)
        del game['summary_received_at']
        source=ui.home_body({'games':[game]}, 'csrf')
        self.assertIn('Получено: '+ui.timestamp(2000),source)

    def test_unknown_timestamp_and_scalar_are_safe(self):
        for value in [None, '<script>', float('inf')]:
            self.assertEqual(ui.timestamp(value), 'Время неизвестно')
        self.assertEqual(ui.scalar_text({'status':'known','value':'<script>'}), 'Неизвестно')


if __name__ == '__main__':
    unittest.main()
