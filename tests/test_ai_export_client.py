"""Deterministic browser-event model; not a claim of native browser acceptance."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


class AIExportClientTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_delays_repeats_navigation_back_and_clipboard_denial(self):
        script=(Path(__file__).parents[1]/'remote_server/ai-export.js').read_text()
        harness=r'''
const vm=require('node:vm'), assert=require('node:assert/strict');
function fixture(){
 const listeners={}, windows={}, writes=[], requests=[];
 let click, resolveFetch, mutation, clock=0;
 const button={dataset:{appid:'1245620',csrf:'SYNTHETIC_CSRF',binding:'SYNTHETIC_BINDING'},hidden:true,disabled:false,textContent:'Copy',addEventListener:(t,h)=>click=h};
 const status={textContent:''}, manual={hidden:true}, manualText={value:'',focused:false,selected:false,focus(){this.focused=true},select(){this.selected=true}};
 const elements={'ai-export-copy':button,'ai-export-status':status,'ai-export-manual':manual,'ai-export-text':manualText};
 const doc={hidden:false,getElementById:id=>elements[id]||null,addEventListener:(t,h)=>listeners[t]=h};
 const context={MutationObserver:class{constructor(fn){mutation=fn}observe(){}},document:doc,window:{addEventListener:(t,h)=>windows[t]=h},performance:{now:()=>clock},AbortController,URLSearchParams,setTimeout:()=>1,clearTimeout:()=>{},navigator:{clipboard:{writeText:async t=>writes.push(t)}},fetch:async(url,options)=>{requests.push({url,options});return await new Promise(r=>resolveFetch=r)}};
 vm.runInNewContext(SCRIPT,context);
 const result=(extra={})=>({ok:true,redirected:false,headers:{get:()=> 'application/json'},json:async()=>({text:'FRESH_SYNTHETIC_TEXT',appid:1245620,checked_at:1}),...extra});
 return {button,status,manual,manualText,mutate:()=>mutation(),doc,listeners,windows,writes,requests,context,result,click:()=>click(),resolve:r=>resolveFetch(r),advance:ms=>clock+=ms};
}
(async()=>{
 let f=fixture();assert.equal(f.button.hidden,false);
 let task=f.click();await f.click();assert.equal(f.requests.length,1);
 assert.equal(f.requests[0].options.redirect,'error');assert.equal(f.requests[0].options.mode,'same-origin');
 f.resolve(f.result());await task;assert.deepEqual(f.writes,['FRESH_SYNTHETIC_TEXT']);
 task=f.click();assert.equal(f.requests.length,2);f.resolve(f.result({ok:false}));await task;
 assert.equal(f.writes.length,1);assert.ok(f.status.textContent.includes('Старый текст не используется'));
 for(const event of ['pagehide','pageshow','visibilitychange']){
  f=fixture();task=f.click();
  if(event==='visibilitychange'){f.doc.hidden=true;f.listeners[event]()}else f.windows[event]({persisted:true});
  f.resolve(f.result());await task;assert.equal(f.writes.length,0);assert.equal(f.button.disabled,true);
  f.doc.hidden=false;await f.click();assert.equal(f.requests.length,1);
 }
 f=fixture();task=f.click();f.advance(10001);f.resolve(f.result());await task;assert.equal(f.writes.length,0);
 f=fixture();task=f.click();f.button.dataset.appid='292030';f.resolve(f.result());await task;assert.equal(f.writes.length,0);assert.equal(f.button.disabled,true);
 for(const bad of [{redirected:true},{headers:{get:()=> 'text/html'}},{json:async()=>({text:'STALE',appid:292030,checked_at:1})}]){
  f=fixture();task=f.click();f.resolve(f.result(bad));await task;assert.equal(f.writes.length,0);
 }
 f=fixture();f.context.navigator.clipboard.writeText=async()=>{throw Error('denied')};task=f.click();f.resolve(f.result());await task;
 assert.equal(f.writes.length,0);assert.ok(!f.status.textContent.includes('FRESH_SYNTHETIC_TEXT'));assert.equal(f.button.disabled,false);
 assert.equal(f.manual.hidden,false);assert.equal(f.manualText.value,'FRESH_SYNTHETIC_TEXT');assert.equal(f.manualText.focused,true);assert.equal(f.manualText.selected,true);
 assert.ok(f.status.textContent.includes('Автокопирование'));assert.ok(f.status.textContent.includes('вручную'));
 task=f.click();assert.equal(f.manual.hidden,true);assert.equal(f.manualText.value,'');assert.equal(f.requests.length,2);f.resolve(f.result({ok:false}));await task;assert.equal(f.writes.length,0);assert.equal(f.manualText.value,'');
 f=fixture();f.context.navigator.clipboard=undefined;task=f.click();assert.equal(f.requests.length,1);f.resolve(f.result());await task;assert.equal(f.manualText.value,'FRESH_SYNTHETIC_TEXT');
 for(const event of ['pagehide','pageshow','visibilitychange','context']){
  f=fixture();f.context.navigator.clipboard=undefined;task=f.click();f.resolve(f.result());await task;assert.equal(f.manual.hidden,false);
  if(event==='context'){f.button.dataset.appid='292030';f.mutate()}
  else if(event==='visibilitychange'){f.doc.hidden=true;f.listeners[event]()}
  else f.windows[event]({persisted:true});
  assert.equal(f.manual.hidden,true);assert.equal(f.manualText.value,'');assert.equal(f.button.disabled,true);
 }
 // Delayed clipboard rejection is not a new authorization check; stale/changed results stay hidden.
 for(const event of ['expired','context','pagehide']){
  f=fixture();let rejectCopy;f.context.navigator.clipboard.writeText=()=>new Promise((_,reject)=>rejectCopy=reject);
  task=f.click();f.resolve(f.result());for(let i=0;i<10&&!rejectCopy;i++)await Promise.resolve();assert.ok(rejectCopy);
  if(event==='expired')f.advance(10001);
  else if(event==='context')f.button.dataset.appid='292030';
  else f.windows.pagehide({});
  rejectCopy(Error('denied'));await task;assert.equal(f.manual.hidden,true);assert.equal(f.manualText.value,'');
 }
 for(const bad of [{ok:false},{redirected:true},{json:async()=>({text:'WRONG_GAME',appid:292030,checked_at:1})},{headers:{get:()=> 'text/html'}}]){
  f=fixture();f.context.navigator.clipboard=undefined;task=f.click();f.resolve(f.result(bad));await task;assert.equal(f.manual.hidden,true);assert.equal(f.manualText.value,'');
 }
})().catch(e=>{console.error(e);process.exit(1)});
'''.replace('SCRIPT',json.dumps(script))
        result=subprocess.run(['node','-e',harness],text=True,capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        for forbidden in ['localStorage','sessionStorage','console.','createElement','innerHTML','document.cookie']:
            self.assertNotIn(forbidden,script)
