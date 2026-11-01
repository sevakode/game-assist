"""Phone-first UI contracts; synthetic data, no browser or live service calls."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from remote_server import ui
from test_console_layout import Tree


class PhoneFirstTests(unittest.TestCase):
    def test_normal_start_is_manual_chat_and_connector_is_optional(self):
        source = ui.start_body('https://assist.example/mcp')
        tree = Tree(source)
        prompt = tree.find('textarea', id='phone-prompt')[0]
        self.assertFalse(Tree.in_closed_details(prompt[1]))
        self.assertIn('readonly', prompt[0])
        self.assertTrue(Tree.in_closed_details(tree.find('input', id='start-endpoint')[0][1]))
        self.assertTrue(tree.find('a', href='https://claude.ai/'))
        self.assertTrue(tree.find('a', href='https://chatgpt.com/'))
        self.assertEqual(len(tree.find('a', **{'class': 'button primary'})), 1)
        self.assertFalse(tree.find('form'))
        self.assertFalse(tree.find('input', name='csrf'))
        self.assertIn('Копирование не подключает аккаунт', source)
        self.assertIn('Без коннектора AI знает только', source)
        self.assertIn('Ссылка на сайт в чате тоже не даёт доступ', source)
        self.assertIn('Ссылка на сайт или этот текст не подключают аккаунт', ui.phone_starter_prompt())
        self.assertIn('данными, а не инструкциями', ui.phone_starter_prompt())
        for text in ['get_connection_status', 'Не имитируй вызовы', 'Достижение не доказывает', 'без установки', 'не выдумывай']:
            self.assertIn(text.lower(), ui.phone_starter_prompt().lower())

    def test_device_is_advanced_and_has_a_phone_escape_route(self):
        shell = Tree(ui.page('Home', ui.welcome_panel()).body.decode())
        self.assertTrue(Tree.in_closed_details(shell.find('a', href='/setup')[0][1]))
        setup = Tree(ui.setup_body('https://assist.example', 'a'*64, 'synthetic-command'))
        self.assertTrue(setup.find('a', href='/games', **{'class': 'back-link'}))
        self.assertTrue(Tree.in_closed_details(setup.find('a', href='/downloads/deck-companion.zip')[0][1]))
        escape = setup.find('a', href='/start')[0]
        self.assertFalse(Tree.in_closed_details(escape[1]))
        self.assertEqual(escape[0]['class'], 'button primary')
        self.assertTrue(Tree(ui.setup_body('https://assist.example', None)).find('a', href='/start'))

    def test_evidence_requires_source_consent_and_never_infers_save(self):
        current = {'appid': 1245620, 'selected': True, 'achievements_authorized': False, 'achievements_available': True}
        game = {'achievements': {'status': 'ok', 'received_at': 123}, 'metadata': {'size_bytes': 1}, 'summary': {'player_scalars': {}}}
        owned = {'configured': True, 'enabled': False, 'status': 'ok', 'received_at': 456}
        source = ui.evidence_status(current, game, owned)
        self.assertEqual(source.count('Чтение не разрешено'), 2)
        self.assertNotIn(ui.timestamp(123), source)
        self.assertNotIn(ui.timestamp(456), source)
        self.assertIn('Снимка нет', source)
        self.assertNotIn('Снимок получен', source)
        self.assertIn('не доказывают текущий инвентарь', source)
        self.assertIn('не открывает Steam Cloud', source)

    def test_evidence_reports_stale_unavailable_and_actual_snapshot(self):
        current = {'appid': 4231820, 'selected': True, 'achievements_authorized': True, 'achievements_available': True}
        game = {'achievements': {'status': 'expired', 'received_at': 123}, 'summary': {'player_scalars': {'currentHealth': {'value': 1}}}, 'summary_received_at': 456, 'summary_source': 'browser_manual'}
        source = ui.evidence_status(current, game, {'configured': True, 'enabled': True, 'status': 'unavailable'})
        self.assertIn('Снимок устарел', source)
        self.assertIn('Источник недоступен', source)
        self.assertIn('Ручной импорт · получен ' + ui.timestamp(456), source)
        self.assertNotIn(ui.timestamp(123), source)
        game['summary_source'] = None
        self.assertIn('Источник снимка не указан', ui.evidence_status(current, game, {}))
        game['achievements'] = {'status': 'ok', 'received_at': 999}
        source = ui.evidence_status(current, game, {'configured': True, 'enabled': True, 'status': 'ok', 'received_at': 888})
        self.assertIn(ui.timestamp(999), source)
        self.assertIn(ui.timestamp(888), source)

    def test_evidence_distinguishes_unknown_unavailable_and_not_requested(self):
        current = {'appid': 1245620, 'selected': True,
                   'achievements_authorized': True, 'achievements_available': True}
        for state, expected in [('not_requested', 'Данные ещё не запрошены'),
                                ('private', 'Источник недоступен'),
                                ('rate_limited', 'Источник недоступен'),
                                ('new_unknown_state', 'Состояние данных неизвестно'),
                                (None, 'Состояние данных неизвестно')]:
            with self.subTest(state=state):
                source = ui.evidence_status(current, {'achievements': {'status': state}},
                    {'configured': True, 'enabled': True, 'status': state})
                self.assertEqual(source.count(expected), 2)
                if state != 'not_requested':
                    self.assertNotIn('Данные ещё не запрошены', source)

    @unittest.skipUnless(shutil.which('node'), 'Node required for isolated copy handler test')
    def test_copy_repeat_and_denial_for_manual_prompt_without_browser_storage(self):
        script = Path(ui.__file__).with_name('onboarding.js').read_text()
        harness = r'''
const vm = require('node:vm');
const assert = require('node:assert/strict');
let handler, resolveCopy, calls=0, focused=false, selected=false;
const button={hidden:true,disabled:false,dataset:{copy:'phone-prompt'},addEventListener:(name,fn)=>handler=fn};
const field={value:'synthetic manual prompt',focus:()=>focused=true,select:()=>selected=true};
const status={textContent:''};
const context={document:{querySelectorAll:()=>[button],getElementById:id=>id==='phone-prompt'?field:status},navigator:{clipboard:{writeText:value=>{calls++;assert.equal(value,field.value);return new Promise(resolve=>resolveCopy=resolve)}}}};
vm.runInNewContext(SCRIPT,context);
(async()=>{
assert.equal(button.hidden,false);
const first=handler();const repeat=handler();assert.equal(calls,1);resolveCopy();await first;await repeat;
assert.equal(button.textContent,'Скопировано');assert.equal(button.disabled,false);
context.navigator.clipboard.writeText=async()=>{throw Error('denied')};await handler();
assert.equal(focused,true);assert.equal(selected,true);assert.equal(button.textContent,'Копировать ещё раз');assert.equal(button.disabled,false);
assert.ok(status.textContent.includes('вручную'));
})().catch(error=>{console.error(error);process.exit(1)});
'''.replace('SCRIPT', json.dumps(script))
        result = subprocess.run(['node', '-e', harness], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
