"""Synthetic only: no private files and no external requests."""
import json,subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from decoders.belmont import decode_bytes,safe_summary
SCRIPT="const p=require('./remote_server/belmont-parser.js');let s='';process.stdin.on('data',d=>s+=d);process.stdin.on('end',()=>{try{console.log(JSON.stringify({ok:true,value:p.decodeText(s)}))}catch(e){console.log(JSON.stringify({ok:false}))}});"
class Matrix(unittest.TestCase):
 def pair(self,raw):
  try: py={'ok':True,'value':safe_summary(decode_bytes(raw.encode()))}
  except Exception: py={'ok':False}
  js=json.loads(subprocess.run(['node','-e',SCRIPT],cwd=ROOT,input=raw,text=True,capture_output=True,check=True).stdout)
  return py,js
 def test_shared_valid_and_invalid_scalars(self):
  for field in ('healthUpgradeFragmentCount','manaUpgradeFragmentCount','currentHealth','currentMana'):
   for token in ('0','-0','1','9007199254740991','null','true','false','-1','"1"','[]','{}','1e309'):
    with self.subTest(field=field,token=token):
     a,b=self.pair('{"version":"1.1.3","playerSave":{"'+field+'":'+token+'}}');self.assertEqual(a,b)
 def test_opaque_numbers_do_not_escape(self):
  for token in ('9007199254740993','0.12345678901234567890123','1e-999','-1234567890123456789012345'):
   with self.subTest(token=token):
    a,b=self.pair('{"version":"1.1.3","opaque":'+token+'}');self.assertEqual(a,b);self.assertNotIn('opaque',str(b))
 def test_invalid_structures(self):
  for extra in ('"playerSave":[]','"playerSave":null','"worldSaves":{}','"worldSaves":{"m_keys":["x"],"m_values":[]}','"version":"1.1.3"'):
   with self.subTest(extra=extra):
    a,b=self.pair('{"version":"1.1.3",'+extra+'}');self.assertEqual(a,{'ok':False});self.assertEqual(b,a)
 def test_conservative_browser_boundary_documented(self):
  a,b=self.pair('{"version":"1.1.3","playerSave":{"currentHealth":9007199254740992}}');self.assertTrue(a['ok']);self.assertFalse(b['ok'])
if __name__=='__main__':unittest.main()
