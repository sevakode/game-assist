"""Synthetic browser import parser/state tests; never reads a private save."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from remote_server import ui
from decoders.belmont import decode_bytes, safe_summary

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')


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

    def test_manual_source_labeled_and_link_only_on_supported_game(self):
        source = ui.home_body({'games':[{'appid':4231820,'summary':{'player_scalars':{}},'summary_source':'browser_manual'}]}, 'csrf')
        self.assertIn('Ручной импорт',source)
        self.assertNotIn('Сводка от устройства',source)
        self.assertIn('href="/import"',source)
        source = ui.home_body({'games':[]},'csrf',capabilities={'selected_appid':292030})
        self.assertNotIn('href="/import"',source)

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
