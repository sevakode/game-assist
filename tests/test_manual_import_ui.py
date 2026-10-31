"""Synthetic browser import parser/state tests; never reads a private save."""
import json
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import unittest
from remote_server import ui
from decoders.belmont import decode_bytes, safe_summary

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')


class SectionLinks(HTMLParser):
    """Record link location and visible label, not an unrelated global href match."""
    def __init__(self, source):
        super().__init__()
        self.sections = []
        self.links = []
        self.current = None
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'section':
            self.sections.append(attrs.get('id'))
        elif tag == 'a':
            self.current = {'section': self.sections[-1] if self.sections else None,
                            'href': attrs.get('href'), 'class': attrs.get('class', ''), 'text': ''}

    def handle_data(self, text):
        if self.current is not None:
            self.current['text'] += text

    def handle_endtag(self, tag):
        if tag == 'a' and self.current is not None:
            self.links.append(self.current)
            self.current = None
        elif tag == 'section' and self.sections:
            self.sections.pop()


class ManualImportUI(unittest.TestCase):
    def test_initial_controls_disabled_and_no_raw_file_form(self):
        source = ui.manual_import_body('token"<>', True)
        self.assertIn('id="import-file" type="file"', source)
        self.assertIn('id="import-send" type="button" class="primary" disabled', source)
        self.assertIn('<noscript>', source)
        self.assertNotIn('enctype=', source)
        self.assertNotIn('<form', source)
        self.assertIn('token&quot;&lt;&gt;', source)
        self.assertIn('/assets/belmont-parser.js', source)
        self.assertIn('/assets/import.js', source)
        self.assertIn('заменят последнюю сводку', source)
        self.assertIn('До 2 МиБ', source)
        self.assertIn('data-permitted="no"', ui.manual_import_body('token', False))

    def test_manual_source_labeled_and_import_cta_only_on_supported_game(self):
        source = ui.home_body({'games':[{'appid':4231820,'summary':{'player_scalars':{}},'summary_source':'browser_manual'}]}, 'csrf')
        self.assertIn('Ручной импорт', source)
        self.assertNotIn('Сводка от устройства', source)
        links = SectionLinks(source).links
        primary = [link for link in links if link['href'] == '/import' and 'primary' in link['class'].split()]
        self.assertEqual(len(primary), 1)
        self.assertEqual(primary[0]['section'], 'context')
        self.assertEqual(primary[0]['text'], 'Импортировать сводку')
        for appid in (292030, 1245620):
            with self.subTest(appid=appid):
                source = ui.home_body({'games':[]}, 'csrf', capabilities={'selected_appid':appid})
                links = [link for link in SectionLinks(source).links if link['href'] == '/import']
                # Unsupported games never expose an import CTA; shared help is separate.
                self.assertEqual(links, [])
                self.assertIn('href="/connect/claude"', source)
                guide = ui.claude_body('https://assist.example/mcp')
                fallback = [link for link in SectionLinks(guide).links if link['href'] == '/import']
                self.assertEqual(len(fallback), 1)
                self.assertEqual(fallback[0]['text'], 'Импортировать Belmont')
                self.assertNotIn('primary', fallback[0]['class'].split())
                self.assertIn('Для Belmont’s Curse поддерживается ручной импорт формата 1.1.3', guide)
                self.assertIn('Проверь выбранную игру и её разрешения', guide)
                self.assertIn('Для этой игры нет проверенного декодера', source)

    @unittest.skipUnless(NODE, 'Node required for local browser JavaScript tests')
    def test_javascript_parser_and_state_machine(self):
        result=subprocess.run([NODE,str(ROOT/'tests/manual_import.test.js')],cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    @unittest.skipUnless(NODE, 'Node required for opaque numeric parity check')
    def test_irrelevant_numeric_precision_does_not_block_safe_projection(self):
        raw='{"version":"1.1.3","playerSave":{"currentHealth":42},"opaque":{"fraction":0.12345678901234567890123,"integer":9007199254740993,"tiny":1e-999}}'
        script="const p=require('./remote_server/belmont-parser.js');let s='';process.stdin.on('data',d=>s+=d);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(p.decodeText(s))));"
        result=subprocess.run([NODE,'-e',script],input=raw,cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),safe_summary(decode_bytes(raw.encode())))
        self.assertNotIn('opaque',result.stdout)

    @unittest.skipUnless(NODE, 'Node required for Python/JS decoder parity check')
    def test_projection_matches_python_decoder_on_synthetic_fixture(self):
        fixture={'version':'1.1.3','playerSave':{'healthUpgradeFragmentCount':2,'manaUpgradeFragmentCount':3,'currentHealth':42.5,'currentMana':None},'worldSaves':{'m_keys':['PRIVATE_WORLD'],'m_values':[{'savableEntityStates':{'m_keys':['PRIVATE_ENTITY'],'m_values':['{"active":false}']}}]}}
        raw=json.dumps(fixture)
        script="const p=require('./remote_server/belmont-parser.js');let s='';process.stdin.on('data',d=>s+=d);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(p.decodeText(s))));"
        result=subprocess.run([NODE,'-e',script],input=raw,cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),safe_summary(decode_bytes(raw.encode())))

